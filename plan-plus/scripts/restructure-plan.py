#!/usr/bin/env python3
"""plan-plus: PostToolUse hook for ExitPlanMode.

Splits plan into step files.
Creates skeleton with instructions + step list with paths.
Injects Step 0: agent refines skeleton with real requirements.
Reads JSONL only for display name (customTitle) and goals (first user messages).
"""
import json
import os
import re
import sys
from pathlib import Path


def read_stdin():
    try:
        return json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return {}


def find_plan_file(hook_input):
    for path_expr in [
        lambda d: d.get("tool_input", {}).get("planFilePath"),
        lambda d: d.get("tool_response", {}).get("filePath"),
        lambda d: d.get("tool_response", {}).get("data", {}).get("filePath"),
    ]:
        try:
            candidate = path_expr(hook_input)
            if candidate and os.path.isfile(candidate):
                return candidate
        except (TypeError, AttributeError):
            continue

    plans_dir = Path.home() / ".claude" / "plans"
    if plans_dir.is_dir():
        md_files = sorted(
            plans_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if md_files:
            return str(md_files[0])
    return None


def slugify(text):
    text = re.sub(r'[^\w\s-]', '', text.lower()).strip()
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return text[:60] if text else "unnamed"


CONTEXT_HEADERS = {"context", "background", "overview", "summary", "introduction", "about"}


def split_plan_into_sections(plan_content):
    """Split plan on ## headers. Returns (preamble, context_sections, step_sections)."""
    lines = plan_content.splitlines(keepends=True)
    preamble_lines = []
    context_sections = []
    step_sections = []
    current_header = None
    current_lines = []

    for line in lines:
        if re.match(r'^## ', line):
            if current_header is not None:
                header_lower = current_header.lower().strip()
                if header_lower in CONTEXT_HEADERS:
                    context_sections.append((current_header, "".join(current_lines).strip()))
                else:
                    step_sections.append((current_header, "".join(current_lines).strip()))
            current_header = line.strip().lstrip('#').strip()
            current_lines = []
        elif current_header is None:
            preamble_lines.append(line)
        else:
            current_lines.append(line)

    if current_header is not None:
        header_lower = current_header.lower().strip()
        if header_lower in CONTEXT_HEADERS:
            context_sections.append((current_header, "".join(current_lines).strip()))
        else:
            step_sections.append((current_header, "".join(current_lines).strip()))

    return "".join(preamble_lines).strip(), context_sections, step_sections


def summarize_section(header, content, max_lines=3):
    summary_parts = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('```') or stripped.startswith('---'):
            continue
        if (re.match(r'^[-*]\s', stripped)
                or re.match(r'^\d+[.)]\s', stripped)
                or re.match(r'^###\s', stripped)
                or (len(stripped) < 120 and not stripped.startswith('#'))):
            clean = stripped.lstrip('-*#').strip()
            clean = re.sub(r'^\d+[.)]\s*', '', clean).strip()
            if clean and len(clean) > 5:
                summary_parts.append(clean)
                if len(summary_parts) >= max_lines:
                    break

    if not summary_parts:
        return header
    return ", ".join(summary_parts[:max_lines])


def write_step_files(sections, steps_dir, abs_steps_dir):
    step_entries = []
    for i, (header, content) in enumerate(sections, 1):
        slug = slugify(header)
        filename = f"{i:02d}-{slug}.md"
        filepath = steps_dir / filename
        filepath.write_text(f"# {header}\n\n{content}\n", encoding="utf-8")

        summary = summarize_section(header, content)
        step_entries.append(
            f"{i}. [ ] {header} — {summary}\n"
            f"   Step requires using agent: plan-plus-executor — details: {abs_steps_dir}/{filename}"
        )
    return step_entries


def write_step_zero(steps_dir, abs_steps_dir, skeleton_path):
    content = f"""# Step 0: Update plan skeleton

Skeleton file to edit: {skeleton_path}

Read all step files and context files. Rewrite the skeleton plan file with:
- A requirements section: stack, architecture, design patterns, constraints, key features
- Each step described in one sentence or a few tiny bullets
- Any global-level critical info that deserves to be in the skeleton

Read these before starting:
- All files in steps/
- All files in context/
- plan-full.md for the original complete plan

Keep the skeleton lightweight.
"""
    (steps_dir / "00-update-skeleton.md").write_text(content, encoding="utf-8")
    return (
        f"0. [ ] Update plan skeleton — read all steps + context, add requirements, refine summaries\n"
        f"   Step requires using agent: plan-plus-executor — details: {abs_steps_dir}/00-update-skeleton.md"
    )



def mine_goals(jsonl_path, limit=5):
    """Extract first few user messages as goals."""
    messages = []
    with open(jsonl_path) as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get("type") != "user" or entry.get("isMeta"):
                    continue
                content = entry.get("message", {}).get("content", "")
                if isinstance(content, list):
                    parts = [p.get("text", "") for p in content
                             if isinstance(p, dict) and p.get("type") == "text"]
                    content = "\n".join(parts)
                if isinstance(content, str) and content.strip():
                    if '"tool_use_id"' in content:
                        continue
                    messages.append(content.strip()[:300])
                    if len(messages) >= limit:
                        break
            except (json.JSONDecodeError, KeyError):
                continue

    if not messages:
        return ""

    lines = ["# Goals (from conversation)"]
    for i, msg in enumerate(messages, 1):
        summary = msg.replace("\n", " ").strip()
        if len(msg) >= 300:
            summary += "..."
        lines.append(f"- User msg {i}: {summary}")
    return "\n".join(lines)


def main():
    hook_input = read_stdin()

    cwd = hook_input.get("cwd", os.getcwd())
    transcript_path = hook_input.get("transcript_path", "")

    plan_file = find_plan_file(hook_input)
    if not plan_file:
        sys.exit(0)

    plan_path = Path(plan_file)
    plan_basename = plan_path.stem
    skeleton_path = str(plan_path)

    # Skip if already restructured by plan-plus
    try:
        existing_content = plan_path.read_text(encoding="utf-8")
        if "## Instructions" in existing_content and "plan-plus-executor" in existing_content:
            sys.exit(0)
    except Exception:
        pass

    plan_dir = Path(cwd) / ".claude" / "plans" / f"plan-plus--{plan_basename}"
    steps_dir = plan_dir / "steps"
    context_dir = plan_dir / "context"
    abs_dir = str(plan_dir)
    abs_steps = str(steps_dir)

    # Check for existing plan directory and snapshot existing step files
    existing_plan_dir = plan_dir.exists()
    existing_step_files = set()
    if existing_plan_dir and steps_dir.exists():
        existing_step_files = {f.name for f in steps_dir.iterdir() if f.is_file()}

    # Create structure
    steps_dir.mkdir(parents=True, exist_ok=True)
    context_dir.mkdir(parents=True, exist_ok=True)

    # Read and backup original
    plan_content = plan_path.read_text(encoding="utf-8")
    (plan_dir / "plan-full.md").write_text(plan_content, encoding="utf-8")

    # Split plan into sections
    preamble, context_sections, step_sections = split_plan_into_sections(plan_content)

    # Write preamble + context sections to context/project.md
    context_parts = []
    if preamble:
        context_parts.append(preamble)
    for header, content in context_sections:
        context_parts.append(f"## {header}\n\n{content}")
    if context_parts:
        (context_dir / "project.md").write_text(
            "# Project Context\n\n" + "\n\n".join(context_parts) + "\n",
            encoding="utf-8",
        )

    # Write step files
    step_entries = write_step_files(step_sections, steps_dir, abs_steps)
    step_zero = write_step_zero(steps_dir, abs_steps, skeleton_path)

    # Mine JSONL for goals only
    if transcript_path and os.path.isfile(transcript_path):
        try:
            goals = mine_goals(transcript_path)
            if goals:
                (context_dir / "goals.md").write_text(goals, encoding="utf-8")
        except Exception:
            pass

    # Build skeleton — requirements left as placeholder for step 0
    all_steps = [step_zero] + step_entries
    steps_block = "\n".join(all_steps)

    skeleton = f"""# plan-plus: {plan_basename}
skeleton: {skeleton_path}

## Instructions
- If adding new steps to this plan, create a step file alongside the others in steps/ and add a brief reference line here — do not inline step details in this skeleton
- Use plan-plus-executor agent for each step — pass the step's detail file + relevant context/ files
- One agent call per step — do not combine multiple steps into a single agent call
- Agent context is ephemeral — won't bloat this conversation
- Update context/ files with discoveries as you go
- Split context files if they exceed ~200 lines
- Mark steps done in this skeleton as you complete them
- Do not put verbose content in this skeleton

full plan: {abs_dir}/plan-full.md
context: {abs_dir}/context/
steps: {abs_dir}/steps/

## Requirements
(to be filled in by step 0)

## Steps
{steps_block}
"""

    # Write skeleton
    plan_path.write_text(skeleton, encoding="utf-8")

    # Output
    n_steps = len(step_sections)
    existing_warning = ""
    existing_context = ""
    if existing_plan_dir:
        all_step_files = sorted(f.name for f in steps_dir.iterdir() if f.is_file())
        tree_lines = [f"steps/ ({abs_steps})"]
        for name in all_step_files:
            tag = "OLD" if name in existing_step_files else "NEW"
            tree_lines.append(f"  {'└──' if name == all_step_files[-1] else '├──'} [{tag}] {name}")
        tree = "\n".join(tree_lines)
        existing_warning = (
            f" WARNING: plan directory already existed — new step files added alongside old ones.\n{tree}"
        )
        existing_context = (
            f" NOTE: The plan directory already existed from a previous plan mode exit. "
            f"Step files marked [OLD] are from the previous plan; [NEW] are from this plan. "
            f"Ask the user if they want to remove the [OLD] files before proceeding.\n{tree}"
        )

    output = {
        "systemMessage": (
            f"plan-plus: extracted {n_steps} step details to files, created skeleton. "
            f"Files: {abs_dir}/"
            f"{existing_warning}"
        ),
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"plan-plus restructured the plan into {n_steps} step files. "
                f"Original: {abs_dir}/plan-full.md. "
                f"Skeleton is now the auto-injected file with instructions at top. "
                f"Step files in {abs_dir}/steps/. Context in {abs_dir}/context/. "
                f"START WITH STEP 0: use plan-plus-executor agent to read all step "
                f"files and context, then refine the skeleton with real requirements "
                f"(stack, architecture, patterns, constraints) and one sentence or a "
                f"few tiny bullets per step. Then proceed with step 1."
                f"{existing_context}"
            ),
        },
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()

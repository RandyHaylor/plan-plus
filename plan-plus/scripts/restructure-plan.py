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


def write_step_files(sections, steps_dir, rel_steps_dir):
    step_entries = []
    for i, (header, content) in enumerate(sections, 1):
        slug = slugify(header)
        filename = f"{i:02d}-{slug}.md"
        filepath = steps_dir / filename
        filepath.write_text(f"# {header}\n\n{content}\n", encoding="utf-8")

        summary = summarize_section(header, content)
        step_entries.append(
            f"{i}. [ ] {header} — {summary}\n"
            f"   details: {rel_steps_dir}/{filename}"
        )
    return step_entries


def write_step_zero(steps_dir, rel_steps_dir):
    content = """# Step 0: Update plan skeleton

Read all step files and context files. Rewrite the skeleton plan file with:
- A requirements section: stack, architecture, design patterns, constraints, key features
- Accurate brief summaries for each step (one line each)
- Any critical project-wide info that every step needs to know

Read these before starting:
- All files in steps/
- All files in context/
- plan-full.md for the original complete plan

Keep the skeleton under ~40 lines. Do not add verbose content.
"""
    (steps_dir / "00-update-skeleton.md").write_text(content, encoding="utf-8")
    return (
        f"0. [ ] Update plan skeleton — read all steps + context, add requirements, refine summaries\n"
        f"   details: {rel_steps_dir}/00-update-skeleton.md"
    )


def get_display_name(hook_input, transcript_path):
    """Get display name: session_name > customTitle from JSONL > session ID."""
    session_name = hook_input.get("session_name", "")
    if session_name:
        return session_name

    if transcript_path and os.path.isfile(transcript_path):
        try:
            with open(transcript_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry.get("type") == "custom-title":
                            title = entry.get("customTitle", "")
                            if title:
                                return title
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            pass

    session_id = hook_input.get("session_id", "")
    if session_id:
        return session_id[:12]

    return "unnamed"


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

    if plan_basename.startswith("plan-plus--"):
        sys.exit(0)

    display_name = get_display_name(hook_input, transcript_path)
    display_name = re.sub(r'[^\w\s-]', '', display_name).strip().replace(' ', '-').lower()
    if not display_name:
        display_name = "unnamed"

    plan_dir = Path(cwd) / "plans" / f"plan-plus--{display_name}"
    steps_dir = plan_dir / "steps"
    context_dir = plan_dir / "context"
    rel_dir = f"plans/plan-plus--{display_name}"
    rel_steps = f"{rel_dir}/steps"

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
    step_entries = write_step_files(step_sections, steps_dir, rel_steps)
    step_zero = write_step_zero(steps_dir, rel_steps)

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

    skeleton = f"""# plan-plus--{display_name}

## Instructions
- Use plan-plus-executor agent for each step — pass the step's detail file + relevant context/ files
- Agent context is ephemeral — won't bloat this conversation
- Update context/ files with discoveries as you go
- Split context files if they exceed ~200 lines
- Mark steps done in this skeleton as you complete them
- Do not put verbose content in this skeleton

full plan: {rel_dir}/plan-full.md
context: {rel_dir}/context/
steps: {rel_dir}/steps/

## Requirements
(to be filled in by step 0)

## Steps
{steps_block}
"""

    # Write skeleton
    plan_path.write_text(skeleton, encoding="utf-8")

    # Rename for CLI display
    new_plan_path = plan_path.parent / f"plan-plus--{display_name}.md"
    if plan_path != new_plan_path:
        plan_path.rename(new_plan_path)

    # Output
    n_steps = len(step_sections)
    output = {
        "systemMessage": (
            f"plan-plus: split plan into {n_steps} step files + skeleton. "
            f"Start with step 0 to refine the skeleton. "
            f"Files: {rel_dir}/"
        ),
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"plan-plus restructured the plan into {n_steps} step files. "
                f"Original: {rel_dir}/plan-full.md. "
                f"Skeleton is now the auto-injected file with instructions at top. "
                f"Step files in {rel_dir}/steps/. Context in {rel_dir}/context/. "
                f"START WITH STEP 0: use plan-plus-executor agent to read all step "
                f"files and context, then refine the skeleton with real requirements "
                f"(stack, architecture, patterns, constraints) and better summaries. "
                f"Then proceed with step 1."
            ),
        },
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()

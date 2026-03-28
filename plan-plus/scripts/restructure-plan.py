#!/usr/bin/env python3
"""plan-plus: PostToolUse hook for ExitPlanMode.

Reads the full plan + conversation JSONL.
Creates skeleton plan + context files.
Renames plan file for plan-plus-- CLI display.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path


def read_stdin():
    """Read hook input JSON from stdin."""
    try:
        return json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return {}


def find_plan_file(hook_input):
    """Find the plan file path from hook input."""
    # Try multiple locations in the response
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

    # Fallback: most recently modified .md in plans dir
    plans_dir = Path.home() / ".claude" / "plans"
    if plans_dir.is_dir():
        md_files = sorted(plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if md_files:
            return str(md_files[0])

    return None


def mine_goals(jsonl_path, limit=5):
    """Extract goals from early user messages in JSONL."""
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


def mine_requirements(jsonl_path):
    """Extract tech stack, patterns, constraints from conversation."""
    all_text = ""
    with open(jsonl_path) as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get("type") not in ("user", "assistant"):
                    continue
                content = entry.get("message", {}).get("content", "")
                if isinstance(content, list):
                    parts = [p.get("text", "") for p in content
                             if isinstance(p, dict) and p.get("type") == "text"]
                    content = "\n".join(parts)
                if isinstance(content, str):
                    all_text += " " + content[:2000]
            except (json.JSONDecodeError, KeyError):
                continue

    all_lower = all_text.lower()
    lines = ["# Requirements (from conversation)"]

    # Detect stack
    stack_kw = {
        "react": "React", "vue": "Vue", "next.js": "Next.js", "nextjs": "Next.js",
        "node": "Node.js", "python": "Python", "typescript": "TypeScript",
        "javascript": "JavaScript", "rust": "Rust", "golang": "Go",
        "postgres": "PostgreSQL", "mysql": "MySQL", "mongodb": "MongoDB",
        "redis": "Redis", "docker": "Docker", "kubernetes": "Kubernetes",
        "fastapi": "FastAPI", "django": "Django", "flask": "Flask",
        "express": "Express", "svelte": "Svelte", "tailwind": "Tailwind",
    }
    found_stack = sorted({name for kw, name in stack_kw.items() if kw in all_lower})
    if found_stack:
        lines.append(f"- Stack: {', '.join(found_stack)}")

    # Detect patterns
    pattern_kw = {
        "microservice": "Microservices", "monolith": "Monolith",
        "serverless": "Serverless", "event-driven": "Event-driven",
        "rest api": "REST API", "graphql": "GraphQL", "grpc": "gRPC",
        "mvc": "MVC", "clean architecture": "Clean Architecture",
        "hexagonal": "Hexagonal", "domain-driven": "DDD",
        "tdd": "TDD", "test-driven": "TDD",
    }
    found_patterns = sorted({name for kw, name in pattern_kw.items() if kw in all_lower})
    if found_patterns:
        lines.append(f"- Patterns: {', '.join(found_patterns)}")

    # Detect constraints
    constraints = []
    if "security" in all_lower or "auth" in all_lower:
        constraints.append("Security-sensitive")
    if "performance" in all_lower:
        constraints.append("Performance-critical")
    if "backward compat" in all_lower or "backwards compat" in all_lower:
        constraints.append("Backward compatibility")
    if constraints:
        lines.append(f"- Constraints: {', '.join(constraints)}")

    if len(lines) == 1:
        lines.append("- (review plan-full.md for details)")

    return "\n".join(lines)


def extract_steps(plan_content):
    """Extract step-like lines from plan content."""
    step_lines = []
    for line in plan_content.splitlines():
        stripped = line.strip()
        if re.match(r'^[-*]\s', stripped) or re.match(r'^\d+[.)]\s', stripped):
            step_lines.append(stripped)
            if len(step_lines) >= 20:
                break
    return "\n".join(step_lines) if step_lines else "- See plan-full.md"


def main():
    hook_input = read_stdin()

    cwd = hook_input.get("cwd", os.getcwd())
    transcript_path = hook_input.get("transcript_path", "")

    plan_file = find_plan_file(hook_input)
    if not plan_file:
        sys.exit(0)

    plan_path = Path(plan_file)
    plan_basename = plan_path.stem

    # Skip if already restructured
    if plan_basename.startswith("plan-plus--"):
        sys.exit(0)

    plan_dir = Path(cwd) / "plans" / f"plan-plus--{plan_basename}"

    # Create structure
    (plan_dir / "steps").mkdir(parents=True, exist_ok=True)
    (plan_dir / "context").mkdir(parents=True, exist_ok=True)

    # Read and backup original
    plan_content = plan_path.read_text(encoding="utf-8")
    (plan_dir / "plan-full.md").write_text(plan_content, encoding="utf-8")

    # Mine JSONL
    goals = ""
    requirements = ""
    if transcript_path and os.path.isfile(transcript_path):
        try:
            goals = mine_goals(transcript_path)
        except Exception:
            pass
        try:
            requirements = mine_requirements(transcript_path)
        except Exception:
            pass

    # Write context files
    if goals:
        (plan_dir / "context" / "goals.md").write_text(goals, encoding="utf-8")
    if requirements:
        (plan_dir / "context" / "requirements.md").write_text(requirements, encoding="utf-8")

    # Build skeleton
    req_block = requirements if requirements else "## Requirements\n- (see plan-full.md)"
    steps = extract_steps(plan_content)
    rel_dir = f"plans/plan-plus--{plan_basename}"

    skeleton = f"""# plan-plus--{plan_basename}
dir: {rel_dir}/
full: {rel_dir}/plan-full.md
ctx: {rel_dir}/context/

{req_block}

## Steps
{steps}

## Agents
Use plan-plus-executor agent for step execution.
Pass step details + relevant context/ files.
Update context/ with discoveries.
"""

    # Write skeleton to plan file
    plan_path.write_text(skeleton, encoding="utf-8")

    # Rename for CLI display
    new_plan_path = plan_path.parent / f"plan-plus--{plan_basename}.md"
    if plan_path != new_plan_path:
        plan_path.rename(new_plan_path)

    # Output for both user (systemMessage) and Claude (additionalContext)
    output = {
        "systemMessage": (
            f"plan-plus: restructured plan to skeleton. "
            f"Full plan: {rel_dir}/plan-full.md | "
            f"Context: {rel_dir}/context/"
        ),
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"plan-plus restructured the plan. "
                f"Original: {rel_dir}/plan-full.md. "
                f"Skeleton is now the auto-injected file. "
                f"Context files in {rel_dir}/context/. "
                f"Use the plan-plus-executor agent to work through steps — "
                f"pass it the step details and relevant context files. "
                f"The agent's context is ephemeral so it won't bloat your conversation."
            )
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()

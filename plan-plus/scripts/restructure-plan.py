#!/usr/bin/env python3
"""plan-plus: PostToolUse hook for ExitPlanMode.

Simplified flow:
  1. Locate the plan file Claude just produced.
  2. Copy the full original plan to `<plan-dir>/plan-full.md` (the reference copy).
  3. Clear the on-disk plan file and rewrite it as a compressed line-reference
     index: a pointer to the copy, a usage hint, then the compressed plan
     (each `## ` header followed by `(lines N-M)`, body deleted), produced by
     `compress-to-line-reference.py`.
"""
import json
import os
import sys
from pathlib import Path

# Make the sibling compressor script importable regardless of cwd.
THIS_SCRIPT_DIR = Path(__file__).resolve().parent
if str(THIS_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_SCRIPT_DIR))

# Filename on disk uses a hyphen; import via importlib to handle that.
import importlib.util as _importlib_util

_compressor_spec = _importlib_util.spec_from_file_location(
    "compress_to_line_reference_module",
    str(THIS_SCRIPT_DIR / "compress-to-line-reference.py"),
)
_compressor_module = _importlib_util.module_from_spec(_compressor_spec)
_compressor_spec.loader.exec_module(_compressor_module)
compress_to_line_reference = _compressor_module.compress_to_line_reference


def read_stdin_as_json():
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


def build_line_reference_plan_text(
    full_plan_copy_absolute_path,
    reference_docs_directory_absolute_path,
    executor_agent_session_name,
    original_plan_text,
):
    compressed_plan_text = compress_to_line_reference(original_plan_text)
    header_block = (
        f"- plan body (read indicated line ranges): {full_plan_copy_absolute_path}\n"
        f"- fine-grained context files (place/reference here): {reference_docs_directory_absolute_path}\n"
        f"\n"
    )
    injected_step_zero_header_line = (
        "## Step 0 - Create or copy docs for small chunks of requirements "
        "or reference that will be frequently referenced during the project "
        "to the reference-docs folder.\n\n"
    )
    return header_block + injected_step_zero_header_line + compressed_plan_text


def main():
    hook_input = read_stdin_as_json()

    current_working_directory = hook_input.get("cwd", os.getcwd())
    claude_code_session_id = hook_input.get("session_id", "") or ""
    # Short, stable agent session name so it's easy to type and stays unique per project session.
    executor_agent_session_name = (
        f"plan-plus-executor-{claude_code_session_id[:8]}"
        if claude_code_session_id
        else "plan-plus-executor-session"
    )

    plan_file_absolute_path = find_plan_file(hook_input)
    if not plan_file_absolute_path:
        sys.exit(0)

    plan_file_path_obj = Path(plan_file_absolute_path)
    plan_basename_without_extension = plan_file_path_obj.stem

    # Skip if already restructured by plan-plus (idempotent).
    try:
        existing_on_disk_text = plan_file_path_obj.read_text(encoding="utf-8")
        if existing_on_disk_text.startswith("- plan body") and "fine-grained context files" in existing_on_disk_text:
            sys.exit(0)
    except Exception:
        existing_on_disk_text = ""

    plan_documents_directory = (
        Path(current_working_directory)
        / ".claude"
        / "plans"
        / f"plan-plus--{plan_basename_without_extension}"
    )
    plan_documents_directory.mkdir(parents=True, exist_ok=True)

    reference_docs_directory = plan_documents_directory / "reference-docs"
    reference_docs_directory.mkdir(parents=True, exist_ok=True)

    original_plan_text = plan_file_path_obj.read_text(encoding="utf-8")

    full_plan_copy_path = plan_documents_directory / "plan-full.md"
    full_plan_copy_path.write_text(original_plan_text, encoding="utf-8")

    line_reference_plan_text = build_line_reference_plan_text(
        str(full_plan_copy_path),
        str(reference_docs_directory),
        executor_agent_session_name,
        original_plan_text,
    )

    # Clear + rewrite the actual plan doc with the compressed reference.
    plan_file_path_obj.write_text(line_reference_plan_text, encoding="utf-8")

    output = {
        "systemMessage": (
            f"plan-plus: copied full plan to {full_plan_copy_path}; "
            f"rewrote {plan_file_absolute_path} as a line-reference index."
        ),
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"plan-plus compressed the plan. The on-disk plan file at "
                f"{plan_file_absolute_path} now contains a reference header "
                f"(pointing to {full_plan_copy_path}) followed by the "
                f"compressed plan: each `## ` header has `(lines N-M)` "
                f"appended and its body removed. To read a section, open "
                f"{full_plan_copy_path} at those line numbers."
            ),
        },
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Self-contained, reusable plan compressor.

Public API: compress_to_line_reference(plan_text: str) -> str

Keeps `## ` and `### ` headers from the input plan. For each kept
header, appends ` (N-M)` where N and M are the 1-indexed start/end
line numbers of that section in the INPUT text.

Section bounds:
- An H2 section runs from its header line to the line before the next
  H2 header (or EOF).
- An H3 section runs from its header line to the line before the next
  H2 *or* H3 header (or EOF).

Output shape:
- Any preamble text before the first H2/H3 header is preserved as-is.
- Then one annotated header per line, blank line between them.
- All other body content is removed.

Can also be run as a script: reads stdin, writes stdout.
"""
import re
import sys


H2_HEADER_PATTERN = re.compile(r'^##\s+\S')
H3_HEADER_PATTERN = re.compile(r'^###\s+\S')


def classify_line_as_header(line_text):
    """Return 'h2', 'h3', or None."""
    # Check H3 first because H2 pattern would also match H3's `###` prefix
    # via `##\s+`? Actually `## ` requires a space right after `##`, and
    # `### ` has `#` there, so H2 pattern won't match `### `. But be safe:
    if H3_HEADER_PATTERN.match(line_text):
        return "h3"
    if H2_HEADER_PATTERN.match(line_text):
        return "h2"
    return None


def find_kept_header_entries(plan_lines):
    """Return list of dicts describing each H2/H3 header in order.

    Each entry: {"level": "h2"|"h3", "line_index": 0-based int, "text": str}.
    """
    kept_headers = []
    for line_index, line_text in enumerate(plan_lines):
        level = classify_line_as_header(line_text)
        if level is not None:
            kept_headers.append({
                "level": level,
                "line_index": line_index,
                "text": line_text,
            })
    return kept_headers


def compute_section_end_line_zero_based(header_entry_index, kept_headers, total_line_count):
    """Return the 0-indexed inclusive end-line of this section.

    H2 ends before the next H2; H3 ends before the next H2 or H3.
    """
    current = kept_headers[header_entry_index]
    for lookahead_entry_index in range(header_entry_index + 1, len(kept_headers)):
        next_entry = kept_headers[lookahead_entry_index]
        if current["level"] == "h2":
            if next_entry["level"] == "h2":
                return next_entry["line_index"] - 1
        else:  # h3
            if next_entry["level"] in ("h2", "h3"):
                return next_entry["line_index"] - 1
    return total_line_count - 1


def build_annotated_header_line(header_entry, section_start_one_based, section_end_one_based):
    original_header_text = header_entry["text"]
    header_without_trailing_newline = original_header_text.rstrip('\r\n')
    return (
        f"{header_without_trailing_newline} "
        f"({section_start_one_based}-{section_end_one_based})"
    )


def compress_to_line_reference(plan_text):
    """See module docstring."""
    plan_lines = plan_text.splitlines(keepends=True)
    total_line_count = len(plan_lines)

    kept_headers = find_kept_header_entries(plan_lines)
    if not kept_headers:
        return plan_text

    # Preamble = everything before the first H2/H3 header, verbatim.
    first_header_line_index = kept_headers[0]["line_index"]
    preamble_text = "".join(plan_lines[:first_header_line_index])

    annotated_header_lines = []
    for header_entry_index, header_entry in enumerate(kept_headers):
        section_start_one_based = header_entry["line_index"] + 1
        section_end_zero_based = compute_section_end_line_zero_based(
            header_entry_index, kept_headers, total_line_count
        )
        section_end_one_based = section_end_zero_based + 1
        annotated_header_lines.append(
            build_annotated_header_line(
                header_entry, section_start_one_based, section_end_one_based
            )
        )

    headers_block = "\n\n".join(annotated_header_lines) + "\n"

    if preamble_text and not preamble_text.endswith("\n"):
        preamble_text += "\n"

    return preamble_text + headers_block


def main():
    input_plan_text = sys.stdin.read()
    sys.stdout.write(compress_to_line_reference(input_plan_text))


if __name__ == "__main__":
    main()

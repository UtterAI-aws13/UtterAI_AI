from __future__ import annotations

import difflib


def produce_diff_ops(original: str, revised: str) -> list[dict]:
    """Return a list of diff operations between original and revised text."""
    orig_lines = original.splitlines()
    rev_lines = revised.splitlines()
    matcher = difflib.SequenceMatcher(None, orig_lines, rev_lines)
    ops = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            ops.append({
                "op": tag,
                "a_lines": list(range(i1, i2)),
                "b_text": rev_lines[j1:j2],
            })
    return ops


def render_diff_text(original: str, revised: str) -> str:
    """Return a human-readable unified diff string."""
    return "\n".join(
        difflib.unified_diff(
            original.splitlines(),
            revised.splitlines(),
            lineterm="",
        )
    )

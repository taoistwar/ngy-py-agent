"""Unified-diff construction shared by the file-editing and file-writing tools.

Both tools hand structured records to the UI, and both must emit a ``gitDiff``
that really applies. Two rules make that hold (verified by ``git apply --check``
in ``test/tools/edit_file/edit_file_test.py``):

- a hunk reports **whole lines**, never fragments of a line, and
- ``gitDiff`` keeps the carriage return, so CRLF files still match.

``structured_patch`` is display only and strips the terminator, hence the
``keep_cr`` switch. See ``docs/decisions/0003-edit-write-and-patch.md``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent.tools.text_lines import strip_line_ending

# Context lines emitted around every hunk (git default).
CONTEXT_LINES = 3


def render_row(prefix: str, line: str, keep_cr: bool) -> str:
    """Render one diff row, keeping the carriage return when asked."""
    if keep_cr:
        content = line[:-1] if line.endswith("\n") else line
    else:
        content = strip_line_ending(line)
    return f"{prefix}{content}"


def build_hunks(
    hunk_groups: List[List[Dict[str, int]]],
    old_lines: List[str],
    new_lines: List[str],
    keep_cr: bool,
) -> List[Dict[str, Any]]:
    """Build unified-diff hunks; ``newStart`` follows unified diff semantics.

    Each group is a list of items, and each item is inclusive line ranges on the
    old and the new side (``new_last < new_first`` means "no new lines", i.e. a
    deletion). A group holding several items renders the untouched lines between
    them as context, which is what keeps a merged ``gitDiff`` hunk valid.
    """
    last_old_line = len(old_lines) - 1
    line_delta = 0
    hunks: List[Dict[str, Any]] = []

    for items in hunk_groups:
        old_first = items[0]["old_first"]
        old_last = items[-1]["old_last"]
        before = min(CONTEXT_LINES, old_first)
        after = min(CONTEXT_LINES, max(last_old_line - old_last, 0))

        rows = [render_row(" ", old_lines[index], keep_cr) for index in range(old_first - before, old_first)]
        cursor = old_first
        for item in items:
            if item["old_first"] > cursor:
                rows.extend(
                    render_row(" ", old_lines[index], keep_cr)
                    for index in range(cursor, item["old_first"])
                )
            rows.extend(
                render_row("-", old_lines[index], keep_cr)
                for index in range(item["old_first"], item["old_last"] + 1)
            )
            if item["new_last"] >= item["new_first"]:
                rows.extend(
                    render_row("+", new_lines[index], keep_cr)
                    for index in range(item["new_first"], item["new_last"] + 1)
                )
            cursor = item["old_last"] + 1
        rows.extend(
            render_row(" ", old_lines[index], keep_cr)
            for index in range(old_last + 1, old_last + 1 + after)
        )

        old_count = (old_last + after) - (old_first - before) + 1
        change = sum(
            max(item["new_last"] - item["new_first"] + 1, 0)
            - (item["old_last"] - item["old_first"] + 1)
            for item in items
        )
        new_count = old_count + change

        hunks.append(
            {
                "oldStart": old_first - before + 1,
                "oldLines": old_count,
                "newStart": old_first - before + 1 + line_delta,
                "newLines": new_count,
                "lines": rows,
            }
        )
        line_delta += new_count - old_count

    return hunks


def build_git_diff(display: str, hunks: List[Dict[str, Any]]) -> str:
    """Unified diff aligned with git's format (no blob hashes available)."""
    if not hunks:
        return ""
    parts = [
        f"diff --git a/{display} b/{display}",
        f"--- a/{display}",
        f"+++ b/{display}",
    ]
    for hunk in hunks:
        parts.append(
            f"@@ -{hunk['oldStart']},{hunk['oldLines']} +{hunk['newStart']},{hunk['newLines']} @@"
        )
        parts.extend(hunk["lines"])
    return "\n".join(parts) + "\n"


def whole_file_hunk(old_line_count: int, new_line_count: int) -> Dict[str, int]:
    """A single item covering both files end to end (a full rewrite)."""
    return {
        "old_first": 0,
        "old_last": old_line_count - 1,
        "new_first": 0,
        "new_last": new_line_count - 1,
    }

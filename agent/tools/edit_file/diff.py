"""Turning an edit's match positions into whole-line patches.

The UI and other consumers get ``gitDiff`` and ``structured_patch``; the model never
sees them (ADR 0001). Only whole lines are reported, so matches that land on the same
line are collapsed into one whole-line replacement before the hunks are built.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from agent.tools.file_patch import CONTEXT_LINES, build_git_diff, build_hunks
from agent.tools.text_lines import line_index


def line_span(offsets: List[int], start: int, end: int) -> Tuple[int, int]:
    """Inclusive line range covering ``[start, end)``; empty when ``end <= start``."""
    if not offsets:
        return 0, -1
    first = line_index(offsets, start)
    if end <= start:
        return first, first - 1
    return first, max(line_index(offsets, end - 1), first)


def collapsed_groups(
    spans: List[int],
    old_length: int,
    inserted_length: int,
    old_offsets: List[int],
    new_offsets: List[int],
) -> List[Dict[str, int]]:
    """One item per group of matches that covers distinct whole lines.

    Matches landing on the same line are collapsed into a single whole-line
    replacement, because the diff reports whole lines: the surrounding text on
    that line changed too, even when the match itself was a fragment.
    """
    groups: List[Dict[str, int]] = []
    for index, start in enumerate(spans):
        delta = index * (inserted_length - old_length)
        o_first, o_last = line_span(old_offsets, start, start + old_length)
        n_first, n_last = line_span(new_offsets, start + delta, start + delta + inserted_length)

        if groups and o_first <= groups[-1]["old_last"]:
            last = groups[-1]
            last["old_last"] = max(last["old_last"], o_last)
            last["new_first"] = min(last["new_first"], n_first)
            last["new_last"] = max(last["new_last"], n_last)
            continue

        groups.append(
            {
                "old_first": o_first,
                "old_last": o_last,
                "new_first": n_first,
                "new_last": n_last,
            }
        )
    return groups


def merge_by_context(items: List[Dict[str, int]], last_line: int) -> List[List[Dict[str, int]]]:
    """Merge items whose context windows touch, so ``gitDiff`` stays applicable."""
    merged: List[List[Dict[str, int]]] = []
    current: List[Dict[str, int]] = []
    group_end = 0

    for item in items:
        start = max(item["old_first"] - CONTEXT_LINES, 0)
        end = min(item["old_last"] + CONTEXT_LINES, last_line)
        if current and start <= group_end + 1:
            current.append(item)
            group_end = max(group_end, end)
            continue
        if current:
            merged.append(current)
        current = [item]
        group_end = end

    if current:
        merged.append(current)
    return merged


def build_diff(display: str, groups: List[Dict[str, int]], old_lines: List[str], new_lines: List[str]) -> str:
    """Whole-line patch, with ``\\r`` kept so ``git apply`` accepts it."""
    return build_git_diff(
        display,
        build_hunks(
            merge_by_context(groups, max(len(old_lines) - 1, 0)),
            old_lines,
            new_lines,
            keep_cr=True,
        ),
    )


def build_patch(groups: List[Dict[str, int]], old_lines: List[str], new_lines: List[str]) -> List[Any]:
    """One hunk per match group, without ``\\r``: the structured payload for the UI."""
    return build_hunks([[group] for group in groups], old_lines, new_lines, keep_cr=False)

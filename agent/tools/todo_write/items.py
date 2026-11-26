"""Validation, counting and rendering of the checklist a call carries.

Everything here is pure: the tool in ``tool.py`` decides what to do with the
result, so the rules that make a plan renderable can be read (and tested) without a
board, a session or a database.
"""

from __future__ import annotations

import ast
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

# A plan longer than this is not a plan, it is a transcript: the panel cannot show
# it and the model cannot keep it current.
MAX_TODOS = 20

STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"

STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_COMPLETED)

# The markers the model already reads as a checklist. Kept short so the rendered
# list stays scannable inside a tool result.
_MARKERS = {
    STATUS_PENDING: "[ ]",
    STATUS_IN_PROGRESS: "[>]",
    STATUS_COMPLETED: "[x]",
}


def parse_todos(raw: Any) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    """Validate a call's ``todos``; returns ``(items, error)``.

    A string is accepted as JSON or as a Python literal representation, without
    ``eval`` (``ast.literal_eval`` parses only literals): some models send the array
    back as text, and refusing that would buy a retry and nothing else.
    """
    if isinstance(raw, str):
        raw, error = _parse_text(raw)
        if error is not None:
            return None, error

    if not isinstance(raw, list):
        return None, "todos must be an array of {content, status} objects"

    if len(raw) > MAX_TODOS:
        return None, f"at most {MAX_TODOS} todos per call, got {len(raw)}"

    items: List[Dict[str, str]] = []
    in_progress = 0
    for index, entry in enumerate(raw):
        item, error = _parse_item(entry, index)
        if error is not None:
            return None, error
        if item["status"] == STATUS_IN_PROGRESS:
            in_progress += 1
        items.append(item)

    if in_progress > 1:
        return None, (
            f"{in_progress} todos are 'in_progress'; keep at most one step in progress "
            "and leave the rest 'pending'"
        )

    return items, None


def _parse_text(raw: str) -> Tuple[Any, Optional[str]]:
    text = raw.strip()
    if not text:
        return None, "todos must be an array of {content, status} objects"
    try:
        return json.loads(text), None
    except ValueError:
        pass
    try:
        return ast.literal_eval(text), None
    except (ValueError, SyntaxError):
        return None, "todos is neither valid JSON nor a list literal"


def _parse_item(entry: Any, index: int) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    number = index + 1
    if not isinstance(entry, dict):
        return None, f"todo #{number} must be an object with 'content' and 'status'"

    content = entry.get("content")
    if not isinstance(content, str) or not content.strip():
        return None, f"todo #{number} needs a non-empty 'content'"

    # A missing status is read as "not started" rather than rejected: that is what
    # an item without a status means, and it costs the model nothing.
    status = entry.get("status", STATUS_PENDING)
    if status not in STATUSES:
        return None, (
            f"todo #{number} has unknown status {status!r}; use one of: "
            + ", ".join(STATUSES)
        )

    return {"content": content.strip(), "status": str(status)}, None


def counts(todos: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Per-status totals, plus ``total``. The UI reads the same numbers."""
    items = list(todos)
    result = {"total": len(items)}
    for status in STATUSES:
        result[status] = sum(1 for item in items if item.get("status") == status)
    return result


def render_todos(todos: List[Dict[str, Any]]) -> str:
    """The checklist as the model reads it back, and as an earlier task left it."""
    summary = counts(todos)
    lines = [f"Todo list ({summary[STATUS_COMPLETED]}/{summary['total']} completed)"]
    if not todos:
        lines.append("(empty: the plan was cleared)")
        return "\n".join(lines)
    for item in todos:
        lines.append(f"{_MARKERS.get(item.get('status'), '[ ]')} {item.get('content', '')}")
    return "\n".join(lines)

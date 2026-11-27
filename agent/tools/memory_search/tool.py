"""The ``memory_search`` call: find the notes a keyword reaches, read them back.

The result is deliberately verbose about its own state - "no memories yet", "nothing
matches", "2 of 7 notes shown" - because a silent empty string reads as a broken tool
and sends the model looking for another way to remember.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from agent.models import ToolOutcome
from agent.tools.memory_search.description import MAX_RESULT_CHARS
from agent.tools.memory_store import MemoryBook

# Enough to read a handful of notes and still leave room for the answer.
MAX_LIMIT = 10
DEFAULT_LIMIT = 5


def _render_note(record: Dict[str, Any]) -> str:
    header = f"### [{record.get('type') or 'user'}] {record.get('name')}"
    description = str(record.get("description") or "").strip()
    body = str(record.get("body") or "").strip()
    parts = [header]
    if description:
        parts.append(description)
    if body:
        parts.append(body)
    return "\n".join(parts)


def memory_search_impl(
    query: Any,
    limit: Any,
    book: MemoryBook,
) -> Tuple[str, Dict[str, Any]]:
    """Find and render matching notes; returns ``(model_text, details)``."""
    text = " ".join(str(query or "").split())
    if not text:
        return (
            "Error: query is required: pass a few keywords, such as a topic, a tool name or a "
            "file name.",
            {"success": False, "reason": "invalid_argument", "matches": 0},
        )

    try:
        requested = int(limit)
    except (TypeError, ValueError):
        requested = DEFAULT_LIMIT
    requested = max(1, min(MAX_LIMIT, requested))

    total = len(book.snapshot())
    found = book.search(text, requested)
    if not found:
        if total == 0:
            return "No memories have been stored yet.", {
                "success": True,
                "query": text,
                "matches": 0,
                "total": 0,
            }
        return (
            f"No stored memory matches {text!r}. The library holds {total} note(s); try a "
            "single keyword such as a tool name, a module name or a topic.",
            {"success": True, "query": text, "matches": 0, "total": total},
        )

    blocks: list[str] = []
    used = 0
    for record in found:
        block = _render_note(record)
        if used + len(block) + 2 > MAX_RESULT_CHARS:
            blocks.append(
                f"### ({len(found) - len(blocks)} further match(es) not shown: the result is "
                "capped. Narrow the query if you need them.)"
            )
            break
        blocks.append(block)
        used += len(block) + 2

    header = f"{len(found)} of {total} stored memory note(s) match {text!r}:"
    return "\n\n".join([header, *blocks]), {
        "success": True,
        "query": text,
        "matches": len(found),
        "total": total,
        "names": [record.get("name") for record in found],
    }


def make_memory_search_tool(book: Optional[MemoryBook] = None):
    """Bind the read tool to one run's memory library (``None`` reads an empty one)."""
    book = book if book is not None else MemoryBook()

    def memory_search(query: str = "", limit: int = DEFAULT_LIMIT) -> ToolOutcome:
        if not book.enabled:
            return ToolOutcome(
                model_text=(
                    "Memory is disabled for this deployment: nothing is stored and nothing can "
                    "be recalled. Answer from this conversation instead."
                ),
                details={"success": False, "reason": "disabled", "matches": 0},
            )
        try:
            model_text, details = memory_search_impl(query, limit, book)
        except Exception as exc:  # noqa: BLE001 - a store failure must reach the model
            return ToolOutcome(
                model_text=f"Error: memories could not be read: {exc}",
                details={"success": False, "reason": "store_error", "error": str(exc)},
            )
        return ToolOutcome(model_text=model_text, details=details)

    return memory_search

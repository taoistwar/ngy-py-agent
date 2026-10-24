"""Keep one step's tool results from flooding the context.

A model turn can ask for several tools at once, and their results land in
``messages`` together. When that batch is larger than the budget, the biggest
results move to ``<workspace>/.task_outputs/tool-results/<tool_call_id>.txt`` and
the message keeps a path plus a preview, which the model reads back with
``read_file`` (see ``docs/decisions/0012-tool-result-budget.md``).

Two passes, because "too large" is asked twice with different meanings:

1. a single result over :data:`DEFAULT_LARGE_RESULT_CHAR_LIMIT` is worth moving on
   its own - it is one observation that cannot fit anyway;
2. if the batch is *still* over budget, move the largest results regardless of size.
   Without this, a batch of thirty 20k results would pass both checks and defeat the
   budget entirely.

Only the latest batch is considered: a result that already left the context as a
path cannot grow back, and rewriting older messages every step would only break the
prompt cache.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.agent_loop.runtime import _emit
from agent.models import EventCategory, EventSink, TaskEvent
from agent.telemetry import current_trace_ids
from agent.tools.output_store import (
    DEFAULT_PREVIEW_CHARS,
    ensure_result_directory,
    persist_text,
    workspace_result_directory,
)

# Batch budget for the tool results of one step, in characters.
BUDGET_CHARS_ENV = "TOOL_RESULT_BUDGET_CHARS"
DEFAULT_MAX_CHARS = 200_000

# A single result above this is persisted even when the batch is still fine.
LARGE_LIMIT_ENV = "TOOL_RESULT_LARGE_CHAR_LIMIT"
DEFAULT_LARGE_RESULT_CHAR_LIMIT = 30_000

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_FALLBACK_STEM = "tool-result"


def resolve_max_chars(configured: Optional[int] = None) -> int:
    """The batch budget; ``<= 0`` disables the step."""
    if configured is not None:
        return int(configured)
    return _env_int(BUDGET_CHARS_ENV, DEFAULT_MAX_CHARS)


def resolve_large_limit(configured: Optional[int] = None) -> int:
    """The size above which one result is worth persisting on its own."""
    if configured is not None:
        return int(configured)
    return _env_int(LARGE_LIMIT_ENV, DEFAULT_LARGE_RESULT_CHAR_LIMIT)


def _env_int(name: str, default: int) -> int:
    try:
        value = int((os.getenv(name) or "").strip())
    except (TypeError, ValueError):
        return default
    return value


def apply_result_budget(
    messages: List[Dict[str, Any]],
    batch_start: int = 0,
    base_dir: Optional[str] = None,
    event_sink: EventSink | None = None,
    task_id: str | None = None,
    step: int = 0,
    max_chars: Optional[int] = None,
    large_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Rewrite the tool results appended since ``batch_start``.

    Mutates ``messages`` in place and returns a summary (also used for the event).
    A result whose write fails stays in the context untouched: losing the content
    silently is worse than exceeding a budget we can see.
    """
    budget = resolve_max_chars(max_chars)
    floor = resolve_large_limit(large_limit)
    summary: Dict[str, Any] = {
        "step": step,
        "max_chars": budget,
        "large_result_char_limit": floor,
        "before_chars": 0,
        "after_chars": 0,
        "persisted": [],
        "failed": [],
    }

    blocks = _tool_blocks(messages, batch_start)
    summary["before_chars"] = _total(blocks)
    summary["after_chars"] = summary["before_chars"]
    if budget <= 0 or summary["before_chars"] <= budget:
        return summary

    directory = workspace_result_directory(base_dir)
    # Ranked once, on the original sizes: a result that just left the context is a
    # path now, and re-ranking would shuffle the order mid-sweep.
    ranked = sorted(range(len(blocks)), key=lambda index: len(blocks[index]["content"]), reverse=True)

    # An index is visited once: a result that was persisted (or that could not be
    # written) must not be touched again by the second sweep, or it would overwrite
    # the full output with its own replacement text.
    handled: set = set()
    for minimum in _passes(floor):
        for index in ranked:
            if summary["after_chars"] <= budget:
                break
            if index in handled:
                continue
            block = blocks[index]
            if len(block["content"]) <= minimum:
                continue
            handled.add(index)
            replacement = _persist(directory, block, summary, step, event_sink, task_id)
            if replacement is None:
                continue
            summary["after_chars"] += len(replacement) - len(block["content"])
            block["content"] = replacement

    _report(summary, event_sink, task_id)
    return summary


def _passes(floor: int) -> tuple:
    """The floor of each sweep: the large-result limit first, then no floor."""
    if floor <= 0:
        return (0,)
    return (floor, 0)


def _tool_blocks(messages: List[Dict[str, Any]], batch_start: int) -> List[Dict[str, Any]]:
    start = max(0, int(batch_start or 0))
    blocks = []
    for message in messages[start:]:
        if isinstance(message, dict) and message.get("role") == "tool":
            # Content is always a string from the loop, but a caller may hand a
            # placeholder message over directly, so normalize instead of trusting it.
            message["content"] = str(message.get("content") or "")
            blocks.append(message)
    return blocks


def _total(blocks: List[Dict[str, Any]]) -> int:
    return sum(len(block["content"]) for block in blocks)


def _persist(
    directory: Path,
    block: Dict[str, Any],
    summary: Dict[str, Any],
    step: int,
    event_sink: EventSink | None,
    task_id: str | None,
) -> Optional[str]:
    """Write one result out and return its replacement, or ``None`` if that failed."""
    content = block["content"]
    name = _file_name(block)
    placeholder = _placeholder(directory / name, content)
    if len(placeholder) >= len(content):
        # Persisting would make the message longer; the budget is not served.
        return None
    try:
        ensure_result_directory(directory)
        path = persist_text(directory, name, content)
    except OSError as exc:
        summary["failed"].append(
            {"tool_call_id": block.get("tool_call_id"), "name": block.get("name"), "error": str(exc)}
        )
        _emit(
            event_sink,
            task_id,
            TaskEvent(
                task_id=task_id or "",
                category=EventCategory.ERROR,
                title=f"Tool result budget failed: {block.get('name') or 'unknown'}",
                data={
                    "step": step,
                    "tool_call_id": block.get("tool_call_id"),
                    "name": block.get("name"),
                    "error": str(exc),
                    "action": "kept the full result in the context",
                    **current_trace_ids(),
                },
                collapsed=True,
            ),
        )
        return None
    summary["persisted"].append(
        {
            "tool_call_id": block.get("tool_call_id"),
            "name": block.get("name"),
            "chars": len(content),
            "path": path.as_posix(),
        }
    )
    return placeholder


def _report(
    summary: Dict[str, Any],
    event_sink: EventSink | None,
    task_id: str | None,
) -> None:
    if not summary["persisted"]:
        return
    _emit(
        event_sink,
        task_id,
        TaskEvent(
            task_id=task_id or "",
            category=EventCategory.DEBUG,
            title=f"Tool result budget Step {summary['step']}",
            data={
                "step": summary["step"],
                "max_chars": summary["max_chars"],
                "before_chars": summary["before_chars"],
                "after_chars": summary["after_chars"],
                "persisted": summary["persisted"],
                **current_trace_ids(),
            },
            collapsed=True,
        ),
    )


def _file_name(block: Dict[str, Any]) -> str:
    """``<tool_call_id>.txt``, reduced to something every filesystem accepts."""
    raw = str(block.get("tool_call_id") or "").strip()
    stem = _SAFE_NAME.sub("-", raw).strip("-.")[:80]
    return f"{stem or _FALLBACK_STEM}.txt"


def _placeholder(path: Path, content: str) -> str:
    """What the model sees instead of the result: where it went, and its head."""
    return (
        "<persisted-output>\n"
        f"Full output: {path.as_posix()} ({len(content):,} chars)\n"
        f"Preview (first {DEFAULT_PREVIEW_CHARS:,} chars):\n"
        f"{content[:DEFAULT_PREVIEW_CHARS]}\n"
        "</persisted-output>"
    )

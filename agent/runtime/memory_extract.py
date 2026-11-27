"""What a finished task learned that the next session should not have to be told again.

The write side has two entry points, and they cover different moments. ``memory_save`` is
the model deciding, mid-task, that something is worth keeping. This is the other one: the
user rarely says "remember that", so when a task ends the exchange is read once and the
durable facts in it are kept (ADR 0035).

The model returns *candidates*, never writes: every one still goes through
``parse_record`` and ``should_store`` - the same checks the tool applies - so a note that
only constrained this task cannot get in through this door either.

It runs on its own thread after the task finished, exactly like ``agent.runtime.naming``:
a slow model must not delay an answer that is already complete, and a failure here costs
the task nothing.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from agent.provider import ProviderConfig, build_provider
from agent.runtime.memories import memory_book_for_run
from agent.tools.memory_notes import (
    MAX_MEMORIES,
    TYPE_HINTS,
    parse_record,
    render_memory_line,
    should_store,
)
from agent.tools.memory_store import MemoryBook
from commons import state

# At most a handful per task: a run that produced ten "memories" mostly produced noise,
# and the library is meant to stay readable by a human.
MAX_CANDIDATES = 3
# How much of the finished exchange the extractor reads. The durable fact is almost
# always in the request or in the closing summary; the middle of a long tool log is not.
MAX_SOURCE_CHARS = 4000
# How much of the existing index it is shown, so it corrects instead of duplicating.
MAX_EXISTING_CHARS = 2000

_EXTRACT_PROMPT = (
    "You read one finished task (the user's request and the agent's final answer) and keep "
    "what a later session would still need. Return only a JSON array, at most "
    f"{MAX_CANDIDATES} items, each shaped like "
    '{"name": "short-slug", "type": "user|feedback|project|reference", "description": '
    '"one line", "body": "a few sentences", "scope": "persistent|current_task"}.\n'
    "Types: "
    + "; ".join(f"{kind} = {hint}" for kind, hint in TYPE_HINTS.items())
    + ".\n"
    "Return [] when nothing durable is in it: no lasting preference, no standing rule about "
    "how work should be done, no stable project fact, no reference to where something lives. "
    "Commands, temporary paths, intermediate findings, and anything that only constrained "
    "this task are scope 'current_task' and are not worth returning at all. "
    "Write the body in the language the user used. Never invent a fact: only keep what the "
    "exchange actually says."
)


def parse_candidates(text: Any) -> List[Dict[str, Any]]:
    """The valid candidates inside a model answer, ignoring everything malformed.

    Models wrap JSON in prose or fences often enough that hunting for the array is
    cheaper than asking again; a candidate that fails validation is dropped rather than
    failing the batch.
    """
    raw = str(text or "").strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        payload = json.loads(raw[start : end + 1])
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    candidates: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        record, error = parse_record(item, require_scope=True)
        if error is None and record is not None:
            candidates.append(record)
        if len(candidates) >= MAX_CANDIDATES:
            break
    return candidates


def save_candidates(candidates: List[Dict[str, Any]], book: MemoryBook) -> List[Dict[str, Any]]:
    """Write the candidates that still add something; returns what was stored."""
    saved: List[Dict[str, Any]] = []
    for record in candidates:
        existing = book.snapshot()
        keep, _ = should_store(record, existing)
        if not keep:
            continue
        known = {item.get("name") for item in existing}
        if len(existing) >= MAX_MEMORIES and record["name"] not in known:
            # No room left: stop rather than raising into a background thread.
            break
        try:
            saved.append(book.save(record))
        # Deliberately broad: this runs off the task's thread and has no reader to
        # report to; one bad write must not drop the others.
        except Exception:  # noqa: BLE001
            continue
    return saved


def extract_memories(
    query: str,
    result: str,
    provider_name: str,
    provider_config: Optional[ProviderConfig],
    existing: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Ask the model what in this exchange belongs in the library; ``[]`` on any failure."""
    known = (existing or [])[:MAX_MEMORIES]
    index = "\n".join(render_memory_line(record) for record in known)[:MAX_EXISTING_CHARS]
    user_message = (
        "Existing memories (do not repeat them; use the same name only to correct one):\n"
        f"{index or '(none)'}\n\n"
        "User request:\n"
        f"{str(query or '')[:MAX_SOURCE_CHARS]}\n\n"
        "Final answer:\n"
        f"{str(result or '')[:MAX_SOURCE_CHARS]}"
    )
    try:
        provider = build_provider(provider_name, provider_config)
        response = provider.chat_completion(
            messages=[
                {"role": "system", "content": _EXTRACT_PROMPT},
                {"role": "user", "content": user_message},
            ]
        )
        message = response.choices[0].message
        content = (
            message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        )
    except Exception:  # noqa: BLE001 - extraction is a convenience; the task is already done
        return []
    return parse_candidates(content)


def extract_after_task(
    task_id: str,
    query: str,
    result: str,
    provider_name: str,
    provider_config: Optional[ProviderConfig],
    emit: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    book: Optional[MemoryBook] = None,
) -> None:
    """Read one finished task and keep what it learned; safe to run on its own thread."""
    if not (state.memories_enabled and state.memories_auto_extract):
        return
    if not str(result or "").strip():
        return
    book = book if book is not None else memory_book_for_run(task_id)
    candidates = extract_memories(
        query, result, provider_name, provider_config, existing=book.snapshot()
    )
    if not candidates:
        return
    saved = save_candidates(candidates, book)
    if not saved:
        return
    if emit is not None:
        emit(
            "Memories updated",
            {
                "task_id": task_id,
                "saved": len(saved),
                "names": [record.get("name") for record in saved],
            },
        )


__all__ = [
    "MAX_CANDIDATES",
    "extract_after_task",
    "extract_memories",
    "parse_candidates",
    "save_candidates",
]

"""The conversation a session has already had, rebuilt from its finished tasks.

A task is one turn of a session: the stored query is the user message and the
stored result is the assistant message. A task created in the same session starts
from that transcript, so a follow-up ("make it faster", "add tests for that") still
refers to what the earlier task built instead of starting from nothing.

It reads the live store through :mod:`app_state` for the same reason the task
runtime does: every reader goes through one module, so a test can swap the store.
"""

from __future__ import annotations

from typing import Any

import app_state
from agent.models import TaskStatus

# The transcript is context, not a record: an unbounded session would otherwise
# outgrow any model window. Whole turns are dropped, never half of one.
MAX_HISTORY_MESSAGES = 40
MAX_HISTORY_CHARS = 24000
# A single answer can be an entire file; keeping all of it would evict every other
# turn from the budget above, so one message is capped before the budget is applied.
MAX_MESSAGE_CHARS = 8000

_TRUNCATION_NOTE = "\n… (truncated)"


def _clip(text: str) -> str:
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return text[:MAX_MESSAGE_CHARS].rstrip() + _TRUNCATION_NOTE


def _finished_turns(session_id: str) -> list[tuple[str, str]]:
    """Query/result pairs of the session's finished tasks, oldest first.

    Only ``success`` counts: a running task is the caller's own in-flight work, a
    failed one has no answer to continue from, and a stopped one stopped mid-way.
    """
    turns: list[tuple[str, str]] = []
    for task in app_state.monitor_store.list_tasks(session_id=session_id):
        if str(task.get("status")) != TaskStatus.SUCCESS.value:
            continue
        query = str(task.get("query") or "").strip()
        result = str(task.get("result") or "").strip()
        if not query or not result:
            continue
        turns.append((_clip(query), _clip(result)))
    return turns


def build_session_history(
    session_id: str | None,
    max_messages: int = MAX_HISTORY_MESSAGES,
    max_chars: int = MAX_HISTORY_CHARS,
) -> list[dict[str, str]]:
    """Earlier turns of the session as chat messages, oldest first.

    When the budget cannot hold every turn the newest ones win: the task right
    before the new one is the one a follow-up is most likely to mean. The newest
    turn is kept even if it alone is larger than the budget, because an empty
    transcript would silently turn a follow-up into a fresh conversation.
    """
    if not session_id:
        return []

    kept: list[tuple[str, str]] = []
    used_chars = 0
    for query, result in reversed(_finished_turns(session_id)):
        if len(kept) * 2 + 2 > max_messages:
            break
        cost = len(query) + len(result)
        if kept and used_chars + cost > max_chars:
            break
        kept.append((query, result))
        used_chars += cost

    messages: list[dict[str, Any]] = []
    for query, result in reversed(kept):
        messages.append({"role": "user", "content": query})
        messages.append({"role": "assistant", "content": result})
    return messages

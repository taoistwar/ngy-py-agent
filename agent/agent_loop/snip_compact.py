"""Archive most of a long conversation, keeping a bounded window (ADR 0015).

Every ReAct step appends an assistant message and its tool results, so a run with many
steps (or a session with injected history) grows without bound. Once the list passes
the limit, the conversation is written to ``<workspace>/.ngy-agent/.transcripts/``
and the live list keeps the first few messages, an archive marker, and the most
recent ones.

The rule that cannot be broken: an assistant tool call and the tool messages that
answer it are one unit. Cutting between them leaves an orphan ``tool_use`` (rejected by
Anthropic) or an orphan ``tool_result`` (rejected by everyone), so the cut widens
around a tool turn instead of landing inside it. Widening means the window may end up
a few messages over the limit - it is a bound, not an equality.

Only the count is bounded here. A retained result can still be enormous; that is what
:mod:`agent.agent_loop.result_budget` is for, and the two run in that order (see ADR
0012 D2 on why the budget looks at the latest batch only).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.agent_loop.runtime import _emit
from agent.agent_loop.transcript import write_transcript
from agent.models import EventCategory, EventSink, TaskEvent
from agent.telemetry import current_trace_ids

# Message-count budget for the conversation handed to the model.
MAX_MESSAGES_ENV = "TRANSCRIPT_MAX_MESSAGES"
DEFAULT_MAX_MESSAGES = 50

# The system prompt, the original question, and the first answer. Keeping a little of
# the beginning preserves *why* the task exists after the middle has been archived.
HEAD_MESSAGES = 3

# Below this many archived messages the snapshot costs more than the cut saves; the
# window is allowed to drift instead (ADR 0015 D3).
MIN_ARCHIVED_MESSAGES = 5


def resolve_max_messages(configured: Optional[int] = None) -> int:
    """The message budget; ``<= 0`` disables the step."""
    if configured is not None:
        return int(configured)
    try:
        return int((os.getenv(MAX_MESSAGES_ENV) or "").strip())
    except (TypeError, ValueError):
        return DEFAULT_MAX_MESSAGES


def apply_snip_compact(
    messages: List[Dict[str, Any]],
    max_messages: Optional[int] = None,
    base_dir: Optional[str] = None,
    event_sink: EventSink | None = None,
    task_id: str | None = None,
    step: int = 0,
) -> Dict[str, Any]:
    """Rewrite ``messages`` in place so it holds at most about ``max_messages``.

    In place, not by returning a new list: the loop works on the very object its caller
    handed over (``messages = initial_messages`` is an alias), so rebinding here would
    leave that caller's copy growing forever.

    A failed transcript write aborts the compaction. Dropping messages while the
    archive is missing is the one degradation this step must not have: the run would
    keep working with no way to find out what it forgot.
    """
    limit = resolve_max_messages(max_messages)
    summary: Dict[str, Any] = {
        "step": step,
        "max_messages": limit,
        "before_count": len(messages),
        "after_count": len(messages),
        "archived": 0,
        "transcript": None,
        "reason": "",
    }
    if limit <= HEAD_MESSAGES + 1 or len(messages) <= limit:
        return summary

    head_end = min(HEAD_MESSAGES, len(messages))
    if _has_tool_use(messages[head_end - 1]):
        # The head would end on a tool call whose results are all on the other side of
        # the cut. Pull them in with it.
        while head_end < len(messages) and _is_tool_result(messages[head_end]):
            head_end += 1

    room = limit - head_end - 1
    if room <= 0:
        summary["reason"] = "one tool turn fills the window"
        _report_skip(summary, event_sink, task_id)
        return summary

    tail_start = len(messages) - room
    while tail_start > head_end and _is_tool_result(messages[tail_start]):
        # Same rule from the other end: the tail may not open with a result whose
        # call was archived.
        tail_start -= 1
    if tail_start <= head_end:
        summary["reason"] = "one tool turn fills the window"
        _report_skip(summary, event_sink, task_id)
        return summary

    archived = tail_start - head_end
    min_archived = _min_archived(limit)
    if archived < min_archived:
        # A full snapshot to drop two messages costs more than it saves. Let the
        # window drift a little and archive a batch worth reading next time.
        summary["reason"] = f"only {archived} messages past the limit"
        _report_skip(summary, event_sink, task_id)
        return summary

    try:
        path = write_transcript(messages, base_dir)
    except OSError as exc:
        summary["reason"] = f"transcript write failed: {exc}"
        _emit(
            event_sink,
            task_id,
            TaskEvent(
                task_id=task_id or "",
                category=EventCategory.ERROR,
                title=f"snip_compact failed Step {step}",
                data={
                    "step": step,
                    "error": str(exc),
                    "action": "kept every message; nothing was archived",
                    **current_trace_ids(),
                },
                collapsed=True,
            ),
        )
        return summary

    messages[:] = [
        *messages[:head_end],
        {"role": "user", "content": _marker(archived, path)},
        *messages[tail_start:],
    ]
    summary.update(
        after_count=len(messages),
        archived=archived,
        transcript=path.as_posix(),
    )
    _emit(
        event_sink,
        task_id,
        TaskEvent(
            task_id=task_id or "",
            category=EventCategory.DEBUG,
            title=f"snip_compact Step {step}",
            data={
                "step": step,
                "max_messages": limit,
                "before_count": summary["before_count"],
                "after_count": summary["after_count"],
                "archived": archived,
                "transcript": summary["transcript"],
                **current_trace_ids(),
            },
            collapsed=True,
        ),
    )
    _report_orphans(messages, event_sink, task_id, step)
    return summary


def _min_archived(limit: int) -> int:
    """How many messages are worth a full snapshot.

    Scaled down for tiny windows: with a six-message budget, waiting for five
    messages' worth of slack means never compacting at all.
    """
    return min(MIN_ARCHIVED_MESSAGES, limit // 10)


def _is_tool_result(message: Dict[str, Any]) -> bool:
    return message.get("role") == "tool"


def _has_tool_use(message: Dict[str, Any]) -> bool:
    return message.get("role") == "assistant" and bool(message.get("tool_calls"))


def _find_orphans(messages: List[Dict[str, Any]]) -> List[str]:
    """Pair tool calls with their results, by role and id.

    Only a guard, not the slicer: the cuts are made on ``role`` alone because this
    repository has exactly one producer of tool messages (the loop), and it always
    emits the results right after the call. This check exists for the day a new shape
    appears: a broken pair fails the *next request*, and a 400 there says nothing
    about compaction.
    """
    problems: List[str] = []
    pending: Dict[str, int] = {}
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "assistant":
            for call_id in pending:
                problems.append(f"tool_use {call_id!r} (message {pending[call_id]}) has no result")
            pending = {}
            for entry in message.get("tool_calls") or []:
                call_id = entry.get("id") if isinstance(entry, dict) else None
                if call_id:
                    pending[str(call_id)] = index
            continue
        if role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            if call_id and call_id in pending:
                pending.pop(call_id)
            else:
                problems.append(f"tool_result {call_id!r} (message {index}) has no call")
    for call_id, index in pending.items():
        problems.append(f"tool_use {call_id!r} (message {index}) has no result")
    return problems


def _report_orphans(
    messages: List[Dict[str, Any]],
    event_sink: EventSink | None,
    task_id: str | None,
    step: int,
) -> None:
    problems = _find_orphans(messages)
    if not problems:
        return
    _emit(
        event_sink,
        task_id,
        TaskEvent(
            task_id=task_id or "",
            category=EventCategory.ERROR,
            title=f"snip_compact left an unpaired tool call Step {step}",
            data={
                "step": step,
                "problems": problems[:10],
                "count": len(problems),
                "action": "compaction already applied; the next request may be rejected",
                **current_trace_ids(),
            },
            collapsed=True,
        ),
    )


def _marker(archived: int, path: Path) -> str:
    """What replaces the archived range. The second line is not decoration.

    Without it the model reads this as a pointer and calls ``read_file`` blind: the
    file is line-numbered by that tool, and one call is capped by the output token
    budget (see the read-back contract in ADR 0012).
    """
    return (
        f"[{archived} messages archived to {path.as_posix()}]\n"
        "Read it with read_file (offset/limit): it is line-numbered and capped by the "
        "output token budget."
    )


def _report_skip(summary: Dict[str, Any], event_sink: EventSink | None, task_id: str | None) -> None:
    """Say why nothing happened; a silently ignored budget looks like a bug."""
    _emit(
        event_sink,
        task_id,
        TaskEvent(
            task_id=task_id or "",
            category=EventCategory.DEBUG,
            title=f"snip_compact skipped Step {summary['step']}",
            data={
                "step": summary["step"],
                "reason": summary["reason"],
                "before_count": summary["before_count"],
                "max_messages": summary["max_messages"],
                **current_trace_ids(),
            },
            collapsed=True,
        ),
    )

"""Delivering finished background commands into the conversation.

The one rule carried over from the reference implementation: a background result never
reuses the original tool call id. That call was already answered with a placeholder,
and a tool call gets exactly one result - so the notification arrives as its own
``user`` message at the start of the next turn (ADR 0034).

``user`` and not ``tool``: nothing in the protocol ties this text to a call, and the
model reads it the way it reads a message from the harness that says "the thing you
started is done". The image message the loop already appends after a tool batch uses
the same shape, for the same reason.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent.agent_loop.runtime import _emit
from agent.models import EventCategory, EventSink, TaskEvent
from agent.telemetry import current_trace_ids
from agent.tools.background import BackgroundTasks


def inject_background_results(
    messages: List[Dict[str, Any]],
    background: Optional[BackgroundTasks],
    event_sink: Optional[EventSink] = None,
    task_id: str = "",
    step: int = 0,
) -> int:
    """Append one message with every finished command; returns how many.

    Called before the request is built, so the report is part of the context the
    model answers from rather than something it discovers a turn later.
    """
    if background is None:
        return 0
    results = background.collect()
    if not results:
        return 0

    messages.append(
        {
            "role": "user",
            "content": "\n\n".join(result.as_notification() for result in results),
        }
    )
    _emit(
        event_sink,
        task_id,
        TaskEvent(
            task_id=task_id or "",
            category=EventCategory.DEBUG,
            title="Background command finished",
            data={
                "step": step,
                "count": len(results),
                "commands": [
                    {
                        "session_id": result.record.session_id,
                        "pid": result.record.pid,
                        "command": result.record.command,
                        "description": result.record.description,
                        "exit_code": result.exit_code,
                        "log_path": result.record.log_path,
                    }
                    for result in results
                ],
                **current_trace_ids(),
            },
            collapsed=True,
        ),
    )
    return len(results)

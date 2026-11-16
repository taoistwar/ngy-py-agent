"""The events a task emits, and the result the last one carried.

Every step of a run reports through ``event_sink``; these are the constructors that
shape those reports, so the loop, the brokers and the runtime all write the same keys.
"""

from __future__ import annotations

import json
from typing import Any

from agent.models import EventCategory, EventSink, TaskEvent


def build_event(
    task_id: str,
    category: EventCategory,
    title: str,
    data: dict[str, Any],
    collapsed: bool = True,
) -> TaskEvent:
    return TaskEvent(task_id=task_id, category=category, title=title, data=data, collapsed=collapsed)


def emit_debug(
    event_sink: EventSink | None, task_id: str, title: str, data: dict[str, Any]
) -> None:
    if event_sink is None:
        return
    event_sink(task_id, build_event(task_id, EventCategory.DEBUG, title, data))


def extract_task_result(events: list[dict[str, Any]] | None) -> str | None:
    """Get the latest task result from debug events."""
    if not events:
        return None

    for item in reversed(events):
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "")).strip().lower()
        if category != EventCategory.DEBUG.value:
            continue
        data = item.get("data")
        if not isinstance(data, dict):
            continue
        if "result" not in data:
            continue
        result = data.get("result")
        if result is None:
            continue
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False)
        except TypeError:
            return str(result)

    return None

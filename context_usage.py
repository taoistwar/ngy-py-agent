"""How full the model's context window already is, for the composer's meter.

The web admin shows a CodeBuddy-style reading next to the send button
(``12.5% · 32.0K / 256.0K context used``). The figure is read back from the event
log rather than estimated from the transcript: every answer already reports what the
provider itself counted (``prompt_tokens`` / ``input_tokens``), and a character
estimate would disagree with that by tens of percent on CJK text.

Two numbers, two sources:

- **used** - the newest model turn of the session. The conversation a task continues
  is the previous task's, so a task that has not answered yet must not blank the
  meter; the walk goes back a few tasks until one carries usage.
- **limit** - the window the selected model declares. A model that declares none is
  bounded by the loop's own budget (:mod:`agent.agent_loop.micro_compact`), so the
  denominator still describes the limit that will actually stop the run.

It reads the live store through :mod:`commons.state` for the same reason the other
readers do: a test can swap the store.
"""

from __future__ import annotations

from typing import Any

from agent.agent_loop.micro_compact import CHARS_PER_TOKEN, resolve_context_limit
from agent.models import EventCategory
from agent.telemetry.usage import extract_token_usage
from commons import state

# A reading further back than this is a stale number wearing a current label: the
# session history is rebuilt per task, so the previous task's turn already describes
# everything a new task starts from.
MAX_SCANNED_TASKS = 5

# The newest turn may be a compaction summary (ADR 0017 D9), which has no usage;
# a handful of turns is enough to find the last real reading.
RECENT_RESPONSES = 5


def _usage_of_task(task_id: str) -> dict[str, int]:
    """Token counts of the task's newest turn that reported any."""
    for event in state.monitor_store.recent_events_of_category(
        task_id, EventCategory.LLM_RESPONSE.value, RECENT_RESPONSES
    ):
        counts = extract_token_usage((event.get("data") or {}).get("raw_response"))
        if counts:
            return counts
    return {}


def _last_turn(tasks: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, int]]:
    """The newest task with a reading, and that reading."""
    for task in reversed(tasks[-MAX_SCANNED_TASKS:]):
        counts = _usage_of_task(task["task_id"])
        if counts:
            return task, counts
    return None, {}


def _resolve_limit(model: dict[str, Any] | None) -> tuple[int, str]:
    """The denominator, in tokens, and where it came from."""
    declared = int((model or {}).get("max_input_tokens") or 0)
    if declared > 0:
        return declared, "model"
    # ``resolve_context_limit`` answers in characters (the loop's unit); the meter
    # speaks tokens, so the same conversion the loop uses goes back the other way.
    chars = resolve_context_limit(None, declared)
    if chars <= 0:
        return 0, "none"
    return int(chars // CHARS_PER_TOKEN), "loop"


def session_context_usage(session_id: str, model_id: str | None = None) -> dict[str, Any]:
    """What the open session costs so far, and what it has room for.

    ``model_id`` is the model the composer has selected; it decides the denominator
    even when the last turn ran on another model, because the next request will be
    sent to the selected one.
    """
    tasks = state.monitor_store.list_tasks(session_id=session_id)
    reading_task, counts = _last_turn(tasks)
    input_tokens = int(counts.get("input_tokens") or 0)
    output_tokens = int(counts.get("output_tokens") or 0)
    used_tokens = input_tokens + output_tokens

    target_model_id = (
        model_id
        or (reading_task or {}).get("model_id")
        or (tasks[-1].get("model_id") if tasks else "")
        or ""
    )
    model = state.monitor_store.llm.get_model(target_model_id) if target_model_id else None
    max_tokens, limit_source = _resolve_limit(model)
    percent = round(used_tokens / max_tokens * 100, 1) if max_tokens > 0 else 0.0

    return {
        "session_id": session_id,
        "model_id": target_model_id or None,
        "model_name": (model or {}).get("name") or "",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "used_tokens": used_tokens,
        "max_tokens": max_tokens,
        "limit_source": limit_source,
        "percent": percent,
    }

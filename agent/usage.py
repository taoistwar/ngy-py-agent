"""What a run cost: the per-task totals and the session's context reading.

Two figures the web admin prints, both read back from the event log instead of being
guessed from the transcript:

- **task usage** - tokens summed over every ``llm_response`` event of one task, plus its
  wall-clock duration, for the result header ("Total tokens", "Duration"). A ReAct task
  makes one request per step, so the sum is what the whole run cost.
- **context usage** - how full the selected model's window already is, for the composer's
  meter (``12.5% · 32.0K / 256.0K context used``). The newest turn is the numerator; a
  model that declares no window is bounded by the loop's own budget.

Nothing new is persisted: the numbers come from records the task already wrote. The
context reading goes through :mod:`commons.state` for the same reason the other readers
do - a test can swap the store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from agent.agent_loop.micro_compact import CHARS_PER_TOKEN, resolve_context_limit
from agent.models import EventCategory
from agent.telemetry.usage import extract_token_usage
from commons import state

# ------------------------------------------------------------------ task usage


def _as_datetime(value: Any) -> datetime | None:
    """A stored timestamp as an aware ``datetime``; ``None`` when unusable."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    # Rows written before the store normalised timestamps may be naive; compare in UTC
    # rather than raising ``TypeError`` on a mixed pair.
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def sum_token_usage(events: Iterable[Mapping[str, Any]] | None) -> dict[str, int]:
    """``input_tokens``/``output_tokens``/``total_tokens`` over a task's events."""
    input_tokens = 0
    output_tokens = 0
    for event in events or ():
        if event.get("category") != EventCategory.LLM_RESPONSE.value:
            continue
        counts = extract_token_usage((event.get("data") or {}).get("raw_response"))
        input_tokens += int(counts.get("input_tokens") or 0)
        output_tokens += int(counts.get("output_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def elapsed_ms(started_at: Any, finished_at: Any) -> int:
    """Milliseconds between two timestamps, never negative.

    Time is wall-clock, from the task's creation to its last update: the writer bumps
    ``updated_at`` on every appended event and on the final status, so a finished task
    measures the run itself rather than the last tool's duration.
    """
    start = _as_datetime(started_at)
    end = _as_datetime(finished_at)
    if start is None or end is None:
        return 0
    return max(0, int((end - start).total_seconds() * 1000))


def task_usage_summary(trace: Mapping[str, Any] | None) -> dict[str, int]:
    """Every number the result header prints for one task record.

    A compaction summary carries no ``usage`` block (ADR 0017 D9) and therefore
    contributes nothing to the sum.
    """
    trace = trace or {}
    summary = sum_token_usage(trace.get("events"))
    summary["duration_ms"] = elapsed_ms(trace.get("created_at"), trace.get("updated_at"))
    return summary


# --------------------------------------------------------------- context usage

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

"""What one task spent: tokens and wall-clock time, for the result pane.

The detail pane prints both figures in the result header ("Total tokens", "Duration"),
so the reader sees the price of the turn next to the answer instead of guessing from
the event log. Nothing new is persisted: the numbers are read back from records the
task already wrote.

Tokens are summed over **every** ``llm_response`` event, because a ReAct task makes
one request per step - the sum is what the whole run cost, where the composer's meter
(:mod:`context_usage`) only cares about the newest turn. A compaction summary carries
no ``usage`` block (ADR 0017 D9) and therefore contributes nothing.

Time is wall-clock, from the task's creation to its last update: the writer bumps
``updated_at`` on every appended event and on the final status, so a finished task
measures the run itself rather than the last tool's duration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from agent.models import EventCategory
from agent.telemetry.usage import extract_token_usage


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
    """Milliseconds between two timestamps, never negative."""
    start = _as_datetime(started_at)
    end = _as_datetime(finished_at)
    if start is None or end is None:
        return 0
    return max(0, int((end - start).total_seconds() * 1000))


def task_usage_summary(trace: Mapping[str, Any] | None) -> dict[str, int]:
    """Every number the result header prints for one task record."""
    trace = trace or {}
    summary = sum_token_usage(trace.get("events"))
    summary["duration_ms"] = elapsed_ms(trace.get("created_at"), trace.get("updated_at"))
    return summary

"""Local exporters: a JSONL file that survives the process, or the console."""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from agent.telemetry.attributes import safe_attributes

_NAMESPACE = 1_000_000


def _iso_time(nanoseconds: int) -> str:
    return datetime.fromtimestamp(nanoseconds / 1_000_000_000, UTC).isoformat()


def span_to_record(span: ReadableSpan) -> dict[str, Any]:
    """The stable, human-readable shape of one span in the trace file."""
    context = span.get_span_context()
    return {
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
        "parent_span_id": format(span.parent.span_id, "016x") if span.parent else None,
        "name": span.name,
        "kind": span.kind.name,
        "start_time": span.start_time // _NAMESPACE,
        "end_time": span.end_time // _NAMESPACE,
        "start_time_ns": span.start_time,
        "end_time_ns": span.end_time,
        "started_at": _iso_time(span.start_time),
        "duration_ms": round((span.end_time - span.start_time) / _NAMESPACE, 3),
        "status": {
            "code": span.status.status_code.name,
            "description": span.status.description,
        },
        "attributes": safe_attributes(dict(span.attributes or {})),
    }


class JsonlSpanExporter(SpanExporter):
    """Append one JSON object per span to a file.

    A trace file that cannot be written is a diagnostic problem, never a task
    problem: ``export`` returns ``FAILURE`` and lets the run continue.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self._path.open("a", encoding="utf-8") as handle:
                for span in spans:
                    handle.write(json.dumps(span_to_record(span), ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 - a broken trace file must not stop the run
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        # Writes are synchronous inside ``export``, so there is nothing buffered.
        return True

    def shutdown(self) -> None:
        return

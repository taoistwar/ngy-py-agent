"""The four spans the agent knows about, plus their cross-thread handle.

Business code opens a ``with`` block and keeps its own error handling; nothing here
raises, and with tracing off every helper yields ``None`` so the block costs a
comparison and nothing else.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from opentelemetry import context as context_api
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from agent.telemetry.attributes import safe_attributes, summarize_arguments
from agent.telemetry.setup import active_tracer
from agent.telemetry.usage import extract_token_usage


@dataclass(frozen=True)
class TaskSpanHandle:
    """A started-but-not-ended task span, plus the context that carries it."""

    span: Any
    context: Any


def is_tracing_active() -> bool:
    return active_tracer() is not None


@contextmanager
def _start_span(
    name: str,
    attributes: Mapping[str, Any] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Iterator[Any]:
    tracer = active_tracer()
    if tracer is None:
        yield None
        return
    try:
        span_context = tracer.start_as_current_span(
            name, kind=kind, attributes=safe_attributes(attributes or {})
        )
    except Exception:  # noqa: BLE001 - telemetry must never break the caller
        yield None
        return
    # No try/except around the block: an exception from the body must propagate,
    # and the SDK's own context manager records it on the span on the way out.
    with span_context as span:
        yield span


def _task_attributes(
    task_id: str, attributes: Mapping[str, Any] | None
) -> dict[str, Any]:
    """``task.id`` only when there is one: a CLI run has no task record."""
    payload: dict[str, Any] = {}
    if task_id:
        payload["task.id"] = task_id
    payload.update(attributes or {})
    return payload


@contextmanager
def task_span(task_id: str, attributes: Mapping[str, Any] | None = None) -> Iterator[Any]:
    """The root of one run; reuses an already-recording span from the caller."""
    if not is_tracing_active():
        yield None
        return

    active = trace.get_current_span()
    if active.get_span_context().is_valid and active.is_recording():
        yield active
        return

    payload = _task_attributes(task_id, attributes)
    with _start_span("task", payload) as span:
        yield span


@contextmanager
def react_step_span(step: int, max_steps: int) -> Iterator[Any]:
    with _start_span(
        "react.step", {"react.step": step, "react.max_steps": max_steps}
    ) as span:
        yield span


@contextmanager
def llm_span(
    provider: str,
    model: str,
    step: int,
    message_count: int,
    name: str | None = None,
) -> Iterator[Any]:
    """One model request. ``name`` overrides the default ``chat <model>`` for calls that
    are not a ReAct turn (the compaction summary is a request, not a step)."""
    with _start_span(
        name or f"chat {model}",
        {
            "gen_ai.system": provider,
            "gen_ai.request.model": model,
            "gen_ai.request.message_count": message_count,
            "react.step": step,
        },
        kind=SpanKind.CLIENT,
    ) as span:
        yield span


@contextmanager
def tool_span(name: str, arguments: Any, step: int) -> Iterator[Any]:
    with _start_span(
        f"execute_tool {name}",
        {
            "gen_ai.tool.name": name,
            "gen_ai.tool.call.arguments": summarize_arguments(arguments),
            "react.step": step,
        },
    ) as span:
        yield span


def record_llm_response(
    span: Any, response_payload: Any, finish_reason: str | None = None
) -> None:
    """Attach the parts of a response that only exist after the call returns."""
    if span is None:
        return
    try:
        for key, value in extract_token_usage(response_payload).items():
            span.set_attribute(f"gen_ai.usage.{key}", value)
        if finish_reason:
            span.set_attribute("gen_ai.response.finish_reasons", (str(finish_reason),))
    except Exception:  # noqa: BLE001 - telemetry must never break the caller
        return


def record_throttle_wait(span: Any, milliseconds: int) -> None:
    """Attribute the part of a request that was spent waiting for the rate limit.

    Separate from the request duration because "slow model" and "we are rationing
    ourselves" are different problems with different fixes.
    """
    if span is None:
        return
    try:
        span.set_attribute("llm.rpm.wait_ms", max(0, int(milliseconds)))
    except Exception:  # noqa: BLE001 - telemetry must never break the caller
        return


def current_trace_ids() -> dict[str, str]:
    """Trace/span identifiers of the active span, for the event stream to carry."""
    try:
        span_context = trace.get_current_span().get_span_context()
    except Exception:  # noqa: BLE001 - telemetry must never break the caller
        return {}
    if not span_context.is_valid:
        return {}
    return {
        "trace_id": format(span_context.trace_id, "032x"),
        "span_id": format(span_context.span_id, "016x"),
    }


def start_task_span(
    task_id: str, attributes: Mapping[str, Any] | None = None
) -> TaskSpanHandle | None:
    """Start a task span without making it current, so another thread can attach it."""
    tracer = active_tracer()
    if tracer is None:
        return None
    payload = _task_attributes(task_id, attributes)
    try:
        span = tracer.start_span("task", attributes=safe_attributes(payload))
        return TaskSpanHandle(span=span, context=trace.set_span_in_context(span))
    except Exception:  # noqa: BLE001 - telemetry must never break the caller
        return None


def attach_task_span(handle: TaskSpanHandle | None) -> Any | None:
    if handle is None:
        return None
    try:
        return context_api.attach(handle.context)
    except Exception:  # noqa: BLE001 - telemetry must never break the caller
        return None


def detach_task_span(token: Any | None) -> None:
    if token is None:
        return
    try:
        context_api.detach(token)
    except Exception:  # noqa: BLE001 - telemetry must never break the caller
        return


def end_task_span(handle: TaskSpanHandle | None) -> None:
    if handle is None:
        return
    try:
        handle.span.end()
    except Exception:  # noqa: BLE001 - telemetry must never break the caller
        return

"""OpenTelemetry tracing for the ReAct loop.

The package is deliberately boring: business code only names a span and keeps its
existing ``try``/``except`` behaviour, while configuration, export and failure
handling live here. Import ``init_telemetry``/``shutdown_telemetry`` from the entry
point and one of the span helpers from the loop.
"""

from agent.telemetry.attributes import set_error_status, summarize_arguments
from agent.telemetry.config import TelemetryConfig, load_config
from agent.telemetry.setup import (
    active_provider,
    active_tracer,
    init_telemetry,
    is_telemetry_enabled,
    shutdown_telemetry,
)
from agent.telemetry.spans import (
    TaskSpanHandle,
    attach_task_span,
    current_trace_ids,
    detach_task_span,
    end_task_span,
    is_tracing_active,
    llm_span,
    react_step_span,
    record_llm_response,
    record_throttle_wait,
    start_task_span,
    task_span,
    tool_span,
)

__all__ = [
    "TaskSpanHandle",
    "TelemetryConfig",
    "active_provider",
    "active_tracer",
    "attach_task_span",
    "current_trace_ids",
    "detach_task_span",
    "end_task_span",
    "init_telemetry",
    "is_telemetry_enabled",
    "is_tracing_active",
    "llm_span",
    "load_config",
    "react_step_span",
    "record_llm_response",
    "record_throttle_wait",
    "set_error_status",
    "shutdown_telemetry",
    "start_task_span",
    "summarize_arguments",
    "task_span",
    "tool_span",
]

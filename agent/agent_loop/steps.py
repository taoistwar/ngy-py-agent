"""The tool half of a ReAct round trip: run what the model asked for.

The model half lives in :mod:`agent.agent_loop.model_turn`; the loop calls one of
each per step.
"""

from typing import Any, Dict

from agent.agent_loop.runtime import _emit, _execute_tool
from agent.agent_loop.tool_titles import tool_title
from agent.models import (
    EventCategory,
    EventSink,
    TaskEvent,
    ToolCallData,
    ToolOutcome,
    ToolResultData,
)
from agent.telemetry import current_trace_ids, set_error_status, tool_span


def run_tool(
    registry: Any,
    name: str,
    arguments: Dict[str, Any],
    call_id: str,
    step: int,
    event_sink: EventSink | None,
    task_id: str | None,
) -> tuple[Any, str]:
    """Execute one tool call, traced as ``execute_tool <name>``.

    A tool may raise anything, and each failure has to reach the model as a result
    instead of aborting the step, so the exception stops here.
    """
    call_data = ToolCallData(step=step, name=name, arguments=arguments, tool_call_id=call_id)

    with tool_span(name, arguments, step) as span:
        _emit(
            event_sink,
            task_id,
            TaskEvent(
                task_id=task_id or "",
                category=EventCategory.TOOL_CALL,
                title=tool_title(name, arguments),
                data={**call_data.model_dump(), **current_trace_ids()},
                collapsed=True,
            ),
        )

        outcome: Any = None
        try:
            outcome = _execute_tool(registry, name, arguments)
            result = outcome.model_text if isinstance(outcome, ToolOutcome) else outcome
            tool_result_payload = ToolResultData(
                step=step,
                name=name,
                tool_call_id=call_id,
                result=result,
                is_error=False,
            )
        except Exception as exc:  # noqa: BLE001
            set_error_status(span, exc)
            result = f"Error: {exc}"
            tool_result_payload = ToolResultData(
                step=step,
                name=name,
                tool_call_id=call_id,
                result=result,
                is_error=True,
            )
            _emit(
                event_sink,
                task_id,
                TaskEvent(
                    task_id=task_id or "",
                    category=EventCategory.ERROR,
                    title=f"Tool error: {name}",
                    data={"step": step, "name": name, "error": str(exc), **current_trace_ids()},
                    collapsed=True,
                ),
            )

        _emit(
            event_sink,
            task_id,
            TaskEvent(
                task_id=task_id or "",
                category=EventCategory.TOOL_RESULT,
                title=f"Tool result: {name}",
                data={**tool_result_payload.model_dump(), **current_trace_ids()},
                collapsed=True,
            ),
        )

        # Rich tool payloads (for the UI / external consumers) travel on their
        # own event so the model only ever sees the short ``model_text``.
        if isinstance(outcome, ToolOutcome) and outcome.event_category is not None:
            _emit(
                event_sink,
                task_id,
                TaskEvent(
                    task_id=task_id or "",
                    category=outcome.event_category,
                    title=outcome.event_title or f"{name}",
                    data={**outcome.details, **current_trace_ids()},
                    collapsed=True,
                ),
            )

    return outcome, result


__all__ = ["run_tool"]

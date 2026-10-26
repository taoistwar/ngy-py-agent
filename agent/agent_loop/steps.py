"""One ReAct round trip: ask the model, then run the tools it asked for.

Split out of the loop so each span covers a single responsibility: the model call
plus its two events, and one tool call plus its events.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from agent.agent_loop.messages import (
    _parse_tool_calls,
    _to_content_text,
    _to_dict,
    _tool_fallback_parse,
)
from agent.agent_loop.runtime import _emit, _execute_tool
from agent.llm_errors import describe_llm_failure
from agent.models import (
    EventCategory,
    EventSink,
    LLMRequestData,
    LLMResponseData,
    TaskEvent,
    ToolCallData,
    ToolOutcome,
    ToolResultData,
)
from agent.rate_limit import provider_throttle
from agent.telemetry import (
    current_trace_ids,
    llm_span,
    record_llm_response,
    record_throttle_wait,
    set_error_status,
    tool_span,
)
from agent.vision import redact_image_payload


@dataclass
class ModelTurn:
    """What one model call produced, already parsed into the loop's shape."""

    assistant_content: str
    tool_calls: List[Tuple[str, Dict[str, Any], str]]
    response_payload: Any


def _report_throttle_wait(
    span: Any,
    provider: Any,
    step: int,
    event_sink: EventSink | None,
    task_id: str | None,
) -> None:
    """Surface the part of the request that waited for the provider's RPM budget.

    The wait happens inside the adapter, so it is read back from the limiter rather
    than timed here: "the model is slow" and "we rationed ourselves" look identical
    from the outside and have different fixes. Reported once per request, because
    the limiter hands the figure over with ``take_last_wait``.
    """
    waited = provider_throttle.take_last_wait()
    if waited <= 0:
        return
    waited_ms = int(round(waited * 1000))
    record_throttle_wait(span, waited_ms)
    config = getattr(provider, "config", None)
    provider_name = getattr(config, "provider", "")
    base_url = getattr(config, "base_url", "") or ""
    _emit(
        event_sink,
        task_id,
        TaskEvent(
            task_id=task_id or "",
            category=EventCategory.DEBUG,
            title=f"LLM rate limit wait Step {step}",
            data={
                "step": step,
                "provider": provider_name,
                # The budget belongs to the endpoint, so the URL is part of the record.
                "base_url": base_url,
                "model": getattr(config, "model", ""),
                "rpm_limit": provider_throttle.limit_for(provider_name, base_url),
                "waited_ms": waited_ms,
                **current_trace_ids(),
            },
            collapsed=True,
        ),
    )


def run_model_turn(
    provider: Any,
    step: int,
    messages: List[Dict[str, Any]],
    request_tools: Any,
    request_kwargs: Dict[str, Any],
    event_sink: EventSink | None,
    task_id: str | None,
) -> ModelTurn:
    """One model request/response pair, traced as a ``chat <model>`` span."""
    with llm_span(
        provider.config.provider, provider.config.model, step, len(messages)
    ) as span:
        request_data = LLMRequestData(
            step=step,
            model=provider.config.model,
            provider=provider.config.provider,
            tool_count=len(request_tools or []),
            message_count=len(messages),
            tool_choice="auto",
        )
        raw_request_payload = provider.build_request_payload(
            messages=messages,
            tools=request_tools,
            **request_kwargs,
        )
        request_data_dict = request_data.model_dump()
        # Screenshots ride along as base64 data URLs; persist a redacted copy so
        # one observation does not add megabytes to the event log.
        request_data_dict["raw_request"] = redact_image_payload(raw_request_payload)
        _emit(
            event_sink,
            task_id,
            TaskEvent(
                task_id=task_id or "",
                category=EventCategory.LLM_REQUEST,
                title=f"LLM request Step {step}",
                data={**request_data_dict, **current_trace_ids()},
                collapsed=True,
            ),
        )

        # A model that is down or misconfigured is a routine failure, not a crash in
        # the agent: describe it in terms the operator can act on, record it as an
        # error event (the web admin shows it), and let the caller decide whether to
        # retry. The raw SDK exception never escapes this loop.
        try:
            response = provider.chat_completion(**raw_request_payload)
        except Exception as exc:  # noqa: BLE001 - every provider failure is reported
            _report_throttle_wait(span, provider, step, event_sink, task_id)
            failure = describe_llm_failure(exc, provider)
            _emit(
                event_sink,
                task_id,
                TaskEvent(
                    task_id=task_id or "",
                    category=EventCategory.ERROR,
                    title=f"LLM request failed (step {step})",
                    data={
                        "step": step,
                        "provider": failure.provider,
                        "model": failure.model,
                        "endpoint": failure.endpoint,
                        "type": type(exc).__name__,
                        "error": str(failure),
                        **current_trace_ids(),
                    },
                    collapsed=True,
                ),
            )
            raise failure from exc

        _report_throttle_wait(span, provider, step, event_sink, task_id)

        assistant_message = response.choices[0].message
        message_dict = _to_dict(assistant_message)
        messages.append(message_dict)

        assistant_content = _to_content_text(message_dict.get("content"))

        tool_calls = _parse_tool_calls(assistant_message)
        if not tool_calls:
            tool_call = _tool_fallback_parse(assistant_content)
            if tool_call is not None:
                tool_calls = [tool_call]

        finish_reason = (
            getattr(response, "choices", [{}])[0].finish_reason
            if getattr(response, "choices", None)
            else None
        )
        response_data = LLMResponseData(
            step=step,
            provider=provider.config.provider,
            model=provider.config.model,
            finish_reason=str(finish_reason) if finish_reason else None,
            content=assistant_content,
        )
        response_data.tool_call_count = len(tool_calls)
        response_data_dict = response_data.model_dump()
        if hasattr(response, "model_dump"):
            response_payload = response.model_dump()
        elif hasattr(response, "dict"):
            response_payload = response.dict()
        else:
            response_payload = _to_dict(response)
        response_data_dict["raw_response"] = response_payload
        # Token counts only exist after the call returns, so they are written onto
        # the span here instead of when it opened.
        record_llm_response(span, response_payload, finish_reason=response_data.finish_reason)

        _emit(
            event_sink,
            task_id,
            TaskEvent(
                task_id=task_id or "",
                category=EventCategory.LLM_RESPONSE,
                title=f"LLM response Step {step}",
                data={**response_data_dict, **current_trace_ids()},
                collapsed=True,
            ),
        )

    return ModelTurn(
        assistant_content=assistant_content,
        tool_calls=tool_calls,
        response_payload=response_payload,
    )


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
                title=f"Tool call: {name}",
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

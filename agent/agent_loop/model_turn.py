"""The model half of a ReAct round trip: request, read the stream, parse the turn.

Split out of ``steps`` so each module covers one responsibility: this one talks to
the provider, ``steps`` runs what the model asked for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agent.agent_loop.messages import (
    _parse_tool_calls,
    _to_content_text,
    _to_dict,
    _tool_fallback_parse,
)
from agent.agent_loop.runtime import _emit
from agent.llm_errors import describe_llm_failure
from agent.models import (
    EventCategory,
    EventSink,
    LLMRequestData,
    LLMResponseData,
    TaskEvent,
)
from agent.provider.wire import extra_field, usage_dict
from agent.rate_limit import provider_throttle
from agent.streaming import consume_stream
from agent.telemetry import (
    current_trace_ids,
    llm_span,
    record_llm_response,
    record_throttle_wait,
)
from agent.vision import redact_image_payload


@dataclass
class ModelTurn:
    """What one model call produced, already parsed into the loop's shape."""

    assistant_content: str
    tool_calls: List[Tuple[str, Dict[str, Any], str]]
    response_payload: Any
    reasoning: str = ""


@dataclass
class _TurnResult:
    """The request's answer, before the loop's parsing decides what it means."""

    message: Dict[str, Any]
    finish_reason: Optional[str]
    raw_response: Dict[str, Any]
    streamed: bool
    chunk_count: int = 0
    first_token_ms: Optional[int] = None
    duration_ms: Optional[int] = None


def _message_reasoning(message: Any) -> str:
    """Reasoning under any of the spellings the providers use for it."""
    for key in ("reasoning_content", "reasoning", "thinking"):
        value = extra_field(message, key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _finish_reason_of(response: Any) -> Optional[str]:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    reason = getattr(choices[0], "finish_reason", None)
    return str(reason) if reason else None


def _raw_payload(
    response: Any,
    message: Dict[str, Any],
    finish_reason: Optional[str],
) -> Dict[str, Any]:
    """The response as the raw viewer should see it.

    Adapters that decode another wire format build their own response object, so
    there is no SDK dump to hand over: the OpenAI shape is reconstructed instead of
    leaking that adapter's vocabulary into the event log.
    """
    if hasattr(response, "model_dump"):
        payload = response.model_dump()
        if isinstance(payload, dict):
            return payload
    if hasattr(response, "dict"):
        payload = response.dict()
        if isinstance(payload, dict):
            return payload
    payload: Dict[str, Any] = {
        "object": "chat.completion",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }
    usage = usage_dict(getattr(response, "usage", None))
    if usage:
        payload["usage"] = usage
    return payload


def _read_stream(provider: Any, payload: Dict[str, Any]) -> _TurnResult:
    completion = consume_stream(provider.stream_chat_completion(**payload))
    message = dict(completion.message)
    return _TurnResult(
        message=message,
        finish_reason=completion.finish_reason,
        raw_response=completion.raw_response(
            getattr(provider.config, "model", ""),
            getattr(provider.config, "provider", ""),
        ),
        streamed=True,
        chunk_count=completion.chunk_count,
        first_token_ms=completion.first_token_ms,
        duration_ms=completion.duration_ms,
    )


def _read_once(provider: Any, payload: Dict[str, Any]) -> _TurnResult:
    response = provider.chat_completion(**payload)
    assistant_message = response.choices[0].message
    message = _to_dict(assistant_message)
    reasoning = _message_reasoning(assistant_message)
    if reasoning:
        message["reasoning_content"] = reasoning
    finish_reason = _finish_reason_of(response)
    return _TurnResult(
        message=message,
        finish_reason=finish_reason,
        raw_response=_raw_payload(response, message, finish_reason),
        streamed=False,
    )


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
    stream: bool = True,
) -> ModelTurn:
    """One model request/response pair, traced as a ``chat <model>`` span.

    ``stream`` is a request preference, not a guarantee: an adapter without a stream
    mode answers in one piece and is parsed by the same code.
    """
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
        use_stream = bool(stream and getattr(provider, "supports_streaming", False))

        request_data_dict = request_data.model_dump()
        request_data_dict["stream"] = use_stream
        # Screenshots ride along as base64 data URLs; persist a redacted copy so
        # one observation does not add megabytes to the event log.
        logged_request = dict(raw_request_payload)
        if use_stream:
            logged_request["stream"] = True
        request_data_dict["raw_request"] = redact_image_payload(logged_request)
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
            if use_stream:
                turn = _read_stream(provider, raw_request_payload)
            else:
                turn = _read_once(provider, raw_request_payload)
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

        # Reasoning is shown, never sent back: gateways reject or bill it on the way
        # in, and it belongs to how this turn was produced rather than to the
        # conversation the next turn continues from.
        request_message = {
            key: value
            for key, value in turn.message.items()
            if key != "reasoning_content"
        }
        messages.append(request_message)

        assistant_content = _to_content_text(turn.message.get("content"))
        reasoning = turn.message.get("reasoning_content") or ""

        tool_calls = _parse_tool_calls(turn.message)
        if not tool_calls:
            tool_call = _tool_fallback_parse(assistant_content)
            if tool_call is not None:
                tool_calls = [tool_call]

        response_data = LLMResponseData(
            step=step,
            provider=provider.config.provider,
            model=provider.config.model,
            finish_reason=turn.finish_reason,
            content=assistant_content,
            reasoning=reasoning or None,
            stream=turn.streamed,
            chunk_count=turn.chunk_count,
            first_token_ms=turn.first_token_ms,
            duration_ms=turn.duration_ms,
        )
        response_data.tool_call_count = len(tool_calls)
        response_data_dict = response_data.model_dump()
        response_data_dict["raw_response"] = turn.raw_response
        # Token counts only exist after the call returns, so they are written onto
        # the span here instead of when it opened.
        record_llm_response(span, turn.raw_response, finish_reason=response_data.finish_reason)

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
        response_payload=turn.raw_response,
        reasoning=reasoning,
    )

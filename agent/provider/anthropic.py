"""Anthropic's Messages API, decoded into the OpenAI-shaped vocabulary."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator, List, Optional

from agent.provider.base import BaseProvider, ProviderDependencyError
from agent.provider.config import ProviderConfig
from agent.provider.wire import (
    OpenAIStyleFunction,
    OpenAIStyleToolCall,
    StreamDelta,
    coerce_tool_call_arguments,
    iter_tool_call_entries,
    to_content_text,
    to_json_string,
    tool_call_to_name_and_args,
)


def _field(payload: Any, name: str, default: Any = None) -> Any:
    """Read a field from an SDK event object or from the dict an SSE line decodes to."""
    if isinstance(payload, dict):
        return payload.get(name, default)
    return getattr(payload, name, default)


def normalize_tool_choice(tool_choice: Any) -> Optional[Dict[str, Any]]:
    """Translate OpenAI's short ``tool_choice`` strings into Anthropic's typed form."""
    if tool_choice is None:
        return None
    if isinstance(tool_choice, dict):
        return tool_choice
    if isinstance(tool_choice, str):
        choice = tool_choice.lower().strip()
        if choice in {"none", "auto"}:
            return {"type": choice}
        if choice in {"required", "any"}:
            return {"type": "any"}
    return {"type": "auto"}


def anthropic_usage(usage: Any) -> Optional[Dict[str, Any]]:
    """Anthropic reports input/output tokens; the rest of the app speaks one shape."""
    if usage is None:
        return None
    input_tokens = int(_field(usage, "input_tokens", 0) or 0)
    output_tokens = int(_field(usage, "output_tokens", 0) or 0)
    if not input_tokens and not output_tokens:
        return None
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def anthropic_event_deltas(event: Any) -> List[StreamDelta]:
    """Translate one Messages-API event into the deltas it carries.

    Shared by the SDK adapter and the raw HTTP one: they receive the same event
    vocabulary, only one as objects and the other as JSON dicts.
    """
    event_type = _field(event, "type", "")
    if event_type == "message_start":
        usage = anthropic_usage(_field(_field(event, "message"), "usage"))
        return [StreamDelta(usage=usage)] if usage else []

    if event_type == "content_block_start":
        block = _field(event, "content_block")
        if _field(block, "type", "") != "tool_use":
            return []
        return [
            StreamDelta(
                tool_calls=[{
                    "index": int(_field(event, "index", 0) or 0),
                    "id": str(_field(block, "id", "") or ""),
                    "name": str(_field(block, "name", "") or ""),
                    "arguments": "",
                }]
            )
        ]

    if event_type == "content_block_delta":
        delta = _field(event, "delta")
        delta_type = _field(delta, "type", "")
        index = int(_field(event, "index", 0) or 0)
        if delta_type == "text_delta":
            return [StreamDelta(content=str(_field(delta, "text", "") or ""))]
        if delta_type == "thinking_delta":
            return [StreamDelta(reasoning=str(_field(delta, "thinking", "") or ""))]
        if delta_type == "input_json_delta":
            return [
                StreamDelta(
                    tool_calls=[{
                        "index": index,
                        "id": "",
                        "name": "",
                        "arguments": str(_field(delta, "partial_json", "") or ""),
                    }]
                )
            ]
        return []

    if event_type == "message_delta":
        stop_reason = _field(_field(event, "delta"), "stop_reason")
        return [
            StreamDelta(
                finish_reason=str(stop_reason) if stop_reason else None,
                usage=anthropic_usage(_field(event, "usage")),
            )
        ]

    return []


class AnthropicProvider(BaseProvider):
    provider_name = "anthropic"
    schema_key = "anthropic"
    wire_compatible_with_openai = False
    supports_streaming = True

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        try:
            import anthropic
        except Exception as exc:  # pragma: no cover
            raise ProviderDependencyError(
                "anthropic package is required for anthropic provider."
            ) from exc

        if not config.api_key:
            raise ProviderDependencyError(
                "ANTHROPIC_API_KEY is required for anthropic provider."
            )

        self._client = anthropic.Anthropic(api_key=config.api_key)

    def _to_anthropic_messages(
        self, messages: List[Dict[str, Any]]
    ) -> tuple[str, List[Dict[str, Any]]]:
        system_prompt = ""
        anthropic_messages: List[Dict[str, Any]] = []

        for message in messages:
            role = message.get("role")
            content = to_content_text(message.get("content"))

            if role == "system":
                if system_prompt:
                    system_prompt += "\n"
                system_prompt += content
                continue

            if role == "user":
                anthropic_messages.append({"role": "user", "content": content})
                continue

            if role == "assistant":
                blocks: List[Dict[str, Any]] = []
                for raw_tool_call in iter_tool_call_entries(message):
                    item = tool_call_to_name_and_args(raw_tool_call)
                    if item is None:
                        continue
                    name, args, tool_call_id = item
                    blocks.append({
                        "type": "tool_use",
                        "id": tool_call_id,
                        "name": name,
                        "input": args,
                    })
                if not blocks:
                    anthropic_messages.append({"role": "assistant", "content": content})
                else:
                    if content:
                        blocks.insert(0, {"type": "text", "text": content})
                    anthropic_messages.append({"role": "assistant", "content": blocks})
                continue

            if role == "tool":
                tool_id = message.get("tool_call_id")
                tool_name = message.get("name")  # for logs only
                if not tool_id:
                    # Fall back to plain text if tool id is missing.
                    anthropic_messages.append(
                        {"role": "user", "content": f"[tool:{tool_name}] {content}"}
                    )
                    continue

                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": content,
                    }]
                })

        return system_prompt, anthropic_messages

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Any:
        self._throttle()
        request_params = self.build_request_payload(messages, tools=tools, **kwargs)
        response = self._client.messages.create(**request_params)
        tool_calls: List[OpenAIStyleToolCall] = []
        content_chunks: List[str] = []
        reasoning_chunks: List[str] = []

        for block in getattr(response, "content", []):
            block_type = getattr(block, "type", None)
            if block_type == "tool_use":
                name = getattr(block, "name", "")
                args = coerce_tool_call_arguments(getattr(block, "input", None))
                call_id = getattr(block, "id", None) or str(uuid.uuid4())
                tool_calls.append(
                    OpenAIStyleToolCall(
                        id=str(call_id),
                        function=OpenAIStyleFunction(name=name, arguments=to_json_string(args)),
                    )
                )
            elif block_type == "text":
                text = getattr(block, "text", "")
                if text:
                    content_chunks.append(str(text))
            elif block_type == "thinking":
                thinking = getattr(block, "thinking", "")
                if thinking:
                    reasoning_chunks.append(str(thinking))

        return self.as_openai_style(
            content="\n".join(content_chunks),
            tool_calls=tool_calls,
            reasoning="\n".join(reasoning_chunks),
            usage=anthropic_usage(getattr(response, "usage", None)),
        )

    def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Iterator[StreamDelta]:
        """Follow the raw event stream and translate each block delta.

        Content blocks arrive one at a time and are addressed by index: a text block
        and a tool-use block can interleave, so the index is what keeps their pieces
        apart when the accumulator folds them back together.
        """
        self._throttle()
        request_params = self.build_request_payload(messages, tools=tools, **kwargs)
        request_params["stream"] = True

        for event in self._client.messages.create(**request_params):
            for delta in anthropic_event_deltas(event):
                yield delta

    def build_request_payload(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        system_prompt, anthropic_messages = self._to_anthropic_messages(messages)
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.pop("max_tokens", 1024),
        }
        if system_prompt:
            payload["system"] = system_prompt
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)
        # The SDK validates this field against its own types: OpenAI's short strings
        # ("auto", "required") are rejected outright, so they are translated here.
        tool_choice = normalize_tool_choice(payload.pop("tool_choice", None))
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return payload

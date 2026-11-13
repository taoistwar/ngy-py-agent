"""Anthropic wire format over plain HTTP, for local servers that speak it."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterator, List, Optional

from agent.provider.anthropic import anthropic_event_deltas, normalize_tool_choice
from agent.provider.base import BaseProvider, ProviderDependencyError, ProviderError
from agent.provider.config import ProviderConfig
from agent.provider.wire import (
    OpenAIStyleFunction,
    OpenAIStyleToolCall,
    StreamDelta,
    coerce_tool_call_arguments,
    to_json_string,
)

# Reading a stream waits per chunk, not per request: a slow model may think for a
# while between two deltas without the connection being dead.
_STREAM_TIMEOUT = (10, 300)


class AnthropicOllamaProvider(BaseProvider):
    provider_name = "anthropic_compatible"
    schema_key = "anthropic"
    wire_compatible_with_openai = False
    supports_streaming = True

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        try:
            import requests
        except Exception as exc:  # pragma: no cover
            raise ProviderDependencyError(
                "requests package is required for ollama anthropic compatibility."
            ) from exc

        if not config.base_url:
            raise ProviderError("base_url is required for anthropic-compatible provider.")
        self._requests = requests

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

    def _endpoint(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/messages"

    def _to_anthropic_messages(
        self, messages: List[Dict[str, Any]]
    ) -> tuple[str, List[Dict[str, Any]]]:
        # Same message shaping as the SDK adapter: one translation, two transports.
        from agent.provider.anthropic import AnthropicProvider

        return AnthropicProvider._to_anthropic_messages(self, messages)  # type: ignore[arg-type]

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Any:
        self._throttle()
        request_payload = self.build_request_payload(messages, tools=tools, **kwargs)

        response = self._requests.post(
            self._endpoint(),
            json=request_payload,
            timeout=kwargs.pop("timeout", 30),
            headers=self._headers(),
        )
        if response.status_code >= 400:
            raise ProviderError(
                f"Anthropic-compatible request failed: {response.status_code}: {response.text}"
            )

        payload = response.json()
        if not isinstance(payload, dict):
            return self.as_openai_style(content=str(payload))

        message_content = payload.get("content", []) or []
        if isinstance(message_content, str):
            return self.as_openai_style(content=message_content)

        tool_calls: List[OpenAIStyleToolCall] = []
        content_chunks: List[str] = []
        reasoning_chunks: List[str] = []
        for block in message_content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "tool_use":
                name = block.get("name", "")
                args = coerce_tool_call_arguments(block.get("input"))
                call_id = block.get("id") or str(uuid.uuid4())
                tool_calls.append(
                    OpenAIStyleToolCall(
                        id=str(call_id),
                        function=OpenAIStyleFunction(
                            name=str(name),
                            arguments=to_json_string(args),
                        ),
                    )
                )
                continue
            if block_type == "thinking":
                thinking = block.get("thinking")
                if isinstance(thinking, str) and thinking:
                    reasoning_chunks.append(thinking)
                continue
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    content_chunks.append(text)

        return self.as_openai_style(
            content="\n".join(content_chunks),
            tool_calls=tool_calls,
            reasoning="\n".join(reasoning_chunks),
            usage=payload.get("usage"),
        )

    def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Iterator[StreamDelta]:
        """Read the server-sent events the same way the SDK adapter reads its objects."""
        self._throttle()
        request_payload = self.build_request_payload(messages, tools=tools, **kwargs)
        request_payload["stream"] = True

        with self._requests.post(
            self._endpoint(),
            json=request_payload,
            timeout=_STREAM_TIMEOUT,
            headers=self._headers(),
            stream=True,
        ) as response:
            if response.status_code >= 400:
                raise ProviderError(
                    f"Anthropic-compatible stream failed: {response.status_code}: {response.text}"
                )
            for raw_line in response.iter_lines(decode_unicode=True):
                line = (raw_line or "").strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    # A malformed frame is skipped rather than aborting the turn: the
                    # rest of the stream is still the model's answer.
                    continue
                if not isinstance(event, dict):
                    continue
                for delta in anthropic_event_deltas(event):
                    yield delta

    def build_request_payload(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        system_prompt, anthropic_messages = self._to_anthropic_messages(messages)
        request_payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.pop("max_tokens", 1024),
        }
        if system_prompt:
            request_payload["system"] = system_prompt
        if tools:
            request_payload["tools"] = tools
        tool_choice = normalize_tool_choice(kwargs.pop("tool_choice", "auto"))
        if tool_choice is not None:
            request_payload["tool_choice"] = tool_choice
        request_payload.update(kwargs)
        return request_payload

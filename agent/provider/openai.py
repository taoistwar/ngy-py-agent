"""OpenAI and every server that serves the same chat-completions wire format."""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from agent.provider.base import BaseProvider, ProviderDependencyError
from agent.provider.config import ProviderConfig
from agent.provider.wire import (
    StreamDelta,
    extra_field,
    usage_dict,
)


def chunk_delta(chunk: Any) -> StreamDelta:
    """Decode one ``chat.completion.chunk`` into our delta shape."""
    delta = StreamDelta(usage=usage_dict(getattr(chunk, "usage", None)))
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        # The usage-only tail chunk carries no choices; it is still worth folding in.
        return delta

    choice = choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason:
        delta.finish_reason = str(finish_reason)

    piece = getattr(choice, "delta", None)
    if piece is None:
        return delta

    delta.content = getattr(piece, "content", None) or ""
    # The reasoning trace is not part of OpenAI's schema; both spellings in the wild
    # are read here so the UI does not have to know which gateway answered.
    delta.reasoning = (
        extra_field(piece, "reasoning_content") or extra_field(piece, "reasoning") or ""
    )

    for call in getattr(piece, "tool_calls", None) or []:
        function = getattr(call, "function", None)
        delta.tool_calls.append(
            {
                "index": int(getattr(call, "index", 0) or 0),
                "id": str(getattr(call, "id", None) or ""),
                "name": str(getattr(function, "name", None) or "") if function else "",
                "arguments": (getattr(function, "arguments", None) or "") if function else "",
            }
        )
    return delta


class OpenAIProvider(BaseProvider):
    provider_name = "openai"
    wire_compatible_with_openai = True
    schema_key = "openai"
    supports_streaming = True

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover
            raise ProviderDependencyError(
                "openai package is required for openai-compatible providers."
            ) from exc

        # Ollama and other local OpenAI-compatible servers do not require a
        # real API key. Default a blank key to a harmless placeholder so the
        # SDK does not raise a "Missing credentials" error.
        api_key = config.api_key or "ollama"
        self._client = OpenAI(
            base_url=config.base_url,
            api_key=api_key,
        )

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Any:
        self._throttle()
        return self._client.chat.completions.create(
            **self.build_request_payload(messages, tools=tools, **kwargs)
        )

    def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Iterator[StreamDelta]:
        """Ask for ``stream=True`` and hand back each chunk as it lands.

        ``stream_options.include_usage`` is what makes the last chunk carry the token
        counts the UI shows; servers that predate the option ignore the extra key
        instead of failing the request.
        """
        self._throttle()
        payload = self.build_request_payload(messages, tools=tools, **kwargs)
        payload["stream"] = True
        payload.setdefault("stream_options", {"include_usage": True})
        for chunk in self._client.chat.completions.create(**payload):
            yield chunk_delta(chunk)

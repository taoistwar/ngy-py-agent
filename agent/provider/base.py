"""The provider surface the rest of the agent talks to.

Everything downstream (the ReAct loop, compaction, task naming) uses two calls:
``chat_completion`` for a one-shot answer and ``stream_chat_completion`` for the
incremental one the loop prefers. An adapter that cannot stream sets
``supports_streaming = False`` and inherits the fallback below, so the caller never
has to know which wire format it is talking to.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Protocol

from agent.provider.config import ProviderConfig
from agent.provider.wire import (
    OpenAIStyleChoice,
    OpenAIStyleFunction,
    OpenAIStyleMessage,
    OpenAIStyleResponse,
    OpenAIStyleToolCall,
    StreamDelta,
    delta_from_response,
    to_content_text,
)
from agent.rate_limit import provider_throttle


class ProviderError(RuntimeError):
    pass


class ProviderDependencyError(ProviderError):
    pass


class ChatCompletionProtocol(Protocol):
    def chat_completion(self, *args, **kwargs) -> Any:
        ...

    def stream_chat_completion(self, *args, **kwargs) -> Iterator[StreamDelta]:
        ...

    def build_request_payload(self, *args, **kwargs) -> Dict[str, Any]:
        ...


class BaseProvider(ChatCompletionProtocol):
    provider_name = "base"
    wire_compatible_with_openai = False
    schema_key = "openai"
    # Adapters that can serve a real token stream flip this on; the loop then reads
    # reasoning traces and partial output as they arrive instead of after the fact.
    supports_streaming = False

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def _throttle(self) -> None:
        """Spend this endpoint's per-minute request budget before the call goes out.

        Called by every wire adapter rather than by the callers: the ReAct loop is not
        the only thing asking the endpoint (task naming does too), and a limit that
        some path can skip is not a limit. The bucket is the endpoint - provider plus
        base URL - so two models on one server share one budget (ADR 0014).
        """
        provider_throttle.acquire(self.config.provider, self.config.base_url)

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Any:
        raise NotImplementedError

    def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Iterator[StreamDelta]:
        """Deliver a non-streaming call as a single-delta stream.

        One request, one increment. The loop consumes both paths the same way, which
        is why an endpoint without a stream mode still produces a complete turn.
        """
        response = self.chat_completion(messages, tools=tools, **kwargs)
        yield delta_from_response(response)

    def as_openai_style(
        self,
        content: Optional[str] = None,
        tool_calls: Optional[List[OpenAIStyleToolCall]] = None,
        reasoning: str = "",
        usage: Any = None,
    ) -> OpenAIStyleResponse:
        message = OpenAIStyleMessage(
            content=to_content_text(content),
            tool_calls=tool_calls or [],
            reasoning=reasoning or "",
        )
        return OpenAIStyleResponse(choices=[OpenAIStyleChoice(message=message)], usage=usage)

    def build_request_payload(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": self.config.model, "messages": messages}
        if tools is not None:
            payload["tools"] = tools
        payload.update(kwargs)
        return payload

    def get_tool_schemas(self, registry: Any) -> List[Dict[str, Any]]:
        return registry.get_tool_schemas(self.schema_key)


__all__ = [
    "BaseProvider",
    "ChatCompletionProtocol",
    "OpenAIStyleFunction",
    "ProviderDependencyError",
    "ProviderError",
]

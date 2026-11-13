"""Fold a streamed completion's deltas back into one assistant message.

The loop reasons about complete turns, not about tokens: it needs the full content,
the assembled tool calls and the token counts. This module is that fold. Keeping it
out of the adapters means every wire format is decoded the same way, and keeping it
out of the loop means the loop never counts characters.

Reasoning is carried on the message as ``reasoning_content`` - the spelling the
OpenAI-compatible gateways use - so the event log and the UI read one field
regardless of which provider produced it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agent.provider import StreamDelta


@dataclass
class StreamedCompletion:
    """One turn's worth of streamed output, already assembled."""

    message: Dict[str, Any]
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    chunk_count: int = 0
    first_token_ms: Optional[int] = None
    duration_ms: int = 0

    @property
    def content(self) -> str:
        content = self.message.get("content")
        return content if isinstance(content, str) else ""

    @property
    def reasoning(self) -> str:
        reasoning = self.message.get("reasoning_content")
        return reasoning if isinstance(reasoning, str) else ""

    def request_message(self) -> Dict[str, Any]:
        """The message to append to the conversation.

        Reasoning stays out of it: it is an artefact of how the model produced this
        turn, and gateways reject or bill it when it is sent back.
        """
        message = dict(self.message)
        message.pop("reasoning_content", None)
        return message

    def raw_response(self, model: str = "", provider: str = "") -> Dict[str, Any]:
        """OpenAI-shaped payload for the event log's raw viewer and the token tiles."""
        payload: Dict[str, Any] = {
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": self.message,
                    "finish_reason": self.finish_reason,
                }
            ],
            "stream": True,
            "chunk_count": self.chunk_count,
        }
        if provider:
            payload["provider"] = provider
        if self.usage:
            payload["usage"] = self.usage
        return payload


@dataclass
class StreamAccumulator:
    """Collect deltas until the stream ends, then answer with one message.

    ``clock`` is injected so tests can drive the timings without sleeping.
    """

    clock: Callable[[], float] = time.monotonic
    _content: List[str] = field(default_factory=list)
    _reasoning: List[str] = field(default_factory=list)
    _tool_calls: Dict[int, Dict[str, str]] = field(default_factory=dict)
    _finish_reason: Optional[str] = None
    _usage: Optional[Dict[str, Any]] = None
    _chunk_count: int = 0
    _started_at: float = 0.0
    _first_token_at: Optional[float] = None

    def __post_init__(self) -> None:
        self._started_at = self.clock()

    def _resolve_tool_index(self, fragment: Dict[str, Any]) -> int:
        index = int(fragment.get("index", 0) or 0)
        call_id = str(fragment.get("id") or "")
        if not call_id:
            return index
        existing = self._tool_calls.get(index)
        if existing and existing.get("id") and existing["id"] != call_id:
            # A server that restarts the index for the next call: keep them apart
            # instead of gluing two tool calls into one malformed entry.
            return max(self._tool_calls) + 1
        return index

    def feed(self, delta: StreamDelta) -> None:
        self._chunk_count += 1

        if delta.content:
            self._content.append(delta.content)
            if self._first_token_at is None:
                self._first_token_at = self.clock()
        if delta.reasoning:
            self._reasoning.append(delta.reasoning)
            if self._first_token_at is None:
                self._first_token_at = self.clock()

        for fragment in delta.tool_calls or []:
            index = self._resolve_tool_index(fragment)
            slot = self._tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if fragment.get("id") and not slot["id"]:
                slot["id"] = str(fragment["id"])
            if fragment.get("name") and not slot["name"]:
                slot["name"] = str(fragment["name"])
            arguments = fragment.get("arguments")
            if arguments:
                slot["arguments"] += str(arguments)

        if delta.finish_reason:
            self._finish_reason = delta.finish_reason
        if delta.usage:
            self._merge_usage(delta.usage)

    def _merge_usage(self, usage: Dict[str, Any]) -> None:
        """Merge a usage chunk instead of replacing the previous one.

        Anthropic reports the input tokens when the message starts and the output
        tokens when it ends, so the last chunk alone does not add up to a total the
        token tiles can show.
        """
        merged = dict(self._usage or {})
        for key, value in usage.items():
            if value:
                merged[key] = value
        prompt = merged.get("prompt_tokens")
        completion = merged.get("completion_tokens")
        if isinstance(prompt, int) and isinstance(completion, int):
            merged["total_tokens"] = prompt + completion
        self._usage = merged

    def _message(self) -> Dict[str, Any]:
        content = "".join(self._content)
        message: Dict[str, Any] = {"role": "assistant", "content": content}
        if self._tool_calls:
            message["tool_calls"] = [
                {
                    "id": slot["id"],
                    "type": "function",
                    "function": {"name": slot["name"], "arguments": slot["arguments"]},
                }
                for _, slot in sorted(self._tool_calls.items())
            ]
        reasoning = "".join(self._reasoning)
        if reasoning:
            message["reasoning_content"] = reasoning
        return message

    def result(self) -> StreamedCompletion:
        finished_at = self.clock()
        first_token_ms = None
        if self._first_token_at is not None:
            first_token_ms = int(round((self._first_token_at - self._started_at) * 1000))
        return StreamedCompletion(
            message=self._message(),
            finish_reason=self._finish_reason,
            usage=self._usage,
            chunk_count=self._chunk_count,
            first_token_ms=first_token_ms,
            duration_ms=int(round((finished_at - self._started_at) * 1000)),
        )


def consume_stream(deltas: Any, clock: Callable[[], float] = time.monotonic) -> StreamedCompletion:
    """Drain a delta iterator into one completion."""
    accumulator = StreamAccumulator(clock=clock)
    for delta in deltas:
        accumulator.feed(delta)
    return accumulator.result()

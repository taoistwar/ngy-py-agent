"""The OpenAI chat-completions shape every adapter answers in.

Each wire format is decoded into the same small set of data classes here, so the
loop only ever sees one vocabulary: a message with ``content`` and ``tool_calls``,
and - when the model streamed - a sequence of :class:`StreamDelta` increments.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


def to_json_string(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload or {}, ensure_ascii=False)


def to_content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def iter_tool_call_entries(message: Any) -> Iterable[Any]:
    tool_calls = None
    if isinstance(message, dict):
        tool_calls = message.get("tool_calls", [])
    else:
        tool_calls = getattr(message, "tool_calls", [])
    if not tool_calls:
        return []
    return list(tool_calls)


def coerce_tool_call_arguments(arguments: Any) -> Dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def tool_call_to_name_and_args(
    tool_call: Any,
) -> Optional[tuple[str, Dict[str, Any], str]]:
    if tool_call is None:
        return None

    call_id = getattr(tool_call, "id", None) or (
        tool_call.get("id") if isinstance(tool_call, dict) else None
    )
    if not call_id:
        call_id = str(uuid.uuid4())

    function = getattr(tool_call, "function", None)
    if function is None and isinstance(tool_call, dict):
        function = tool_call.get("function")

    if function is None:
        return None

    name = getattr(function, "name", None) or (
        function.get("name") if isinstance(function, dict) else None
    )
    if not name:
        return None

    arguments = getattr(function, "arguments", None)
    if arguments is None and isinstance(function, dict):
        arguments = function.get("arguments")
    args = coerce_tool_call_arguments(arguments)
    return name, args, str(call_id)


@dataclass
class OpenAIStyleFunction:
    name: str
    arguments: str


@dataclass
class OpenAIStyleToolCall:
    id: str
    function: OpenAIStyleFunction


@dataclass
class OpenAIStyleMessage:
    content: str
    tool_calls: Optional[List[OpenAIStyleToolCall]] = None
    # Reasoning traces travel next to the answer, not inside it: the loop shows them
    # in the event log and never sends them back to the model.
    reasoning: str = ""


@dataclass
class OpenAIStyleChoice:
    message: OpenAIStyleMessage


@dataclass
class OpenAIStyleUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class OpenAIStyleResponse:
    choices: List[OpenAIStyleChoice]
    usage: Optional[OpenAIStyleUsage] = None


@dataclass
class StreamDelta:
    """One increment of a streamed completion, in OpenAI's delta shape.

    ``tool_calls`` carries raw fragments: a streamed call arrives as an id and a name
    on one chunk and its JSON arguments in pieces across many. Folding is the
    accumulator's job, not each adapter's.
    """

    content: str = ""
    reasoning: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None

    def is_empty(self) -> bool:
        return not (
            self.content
            or self.reasoning
            or self.tool_calls
            or self.finish_reason
            or self.usage
        )


def usage_dict(usage: Any) -> Optional[Dict[str, Any]]:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return dict(usage)
    if hasattr(usage, "model_dump"):
        payload = usage.model_dump()
        return payload if isinstance(payload, dict) else None
    if hasattr(usage, "__dict__"):
        return {
            key: value
            for key, value in vars(usage).items()
            if not key.startswith("_") and isinstance(value, (int, float, str))
        }
    return None


def extra_field(payload: Any, name: str) -> Any:
    """Read a field the SDK's model does not declare.

    Reasoning traces ride on the OpenAI-shaped delta under several spellings
    (``reasoning_content``, ``reasoning``), and openai-python keeps anything outside
    its own schema in ``model_extra`` rather than as an attribute.
    """
    value = getattr(payload, name, None)
    if value:
        return value
    extra = getattr(payload, "model_extra", None)
    if isinstance(extra, dict):
        return extra.get(name)
    if isinstance(payload, dict):
        return payload.get(name)
    return None


def delta_from_message(
    message: Any,
    *,
    finish_reason: Any = None,
    usage: Any = None,
) -> StreamDelta:
    """Turn a completed assistant message into one delta.

    Providers without a stream mode are still consumed through the streaming code
    path: one request, one delta. That keeps the loop's parsing in one place.
    """
    delta = StreamDelta(finish_reason=str(finish_reason) if finish_reason else None)
    if message is None:
        return delta

    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    delta.content = to_content_text(content)

    reasoning = extra_field(message, "reasoning_content") or extra_field(message, "reasoning")
    delta.reasoning = reasoning if isinstance(reasoning, str) else ""

    for index, call in enumerate(iter_tool_call_entries(message)):
        function = getattr(call, "function", None)
        if function is None and isinstance(call, dict):
            function = call.get("function")
        if function is None:
            continue
        name = getattr(function, "name", None) or (
            function.get("name") if isinstance(function, dict) else None
        )
        arguments = getattr(function, "arguments", None)
        if arguments is None and isinstance(function, dict):
            arguments = function.get("arguments")
        call_id = getattr(call, "id", None) or (call.get("id") if isinstance(call, dict) else None)
        delta.tool_calls.append(
            {
                "index": index,
                "id": str(call_id or ""),
                "name": str(name or ""),
                "arguments": arguments if isinstance(arguments, str) else to_json_string(arguments),
            }
        )

    delta.usage = usage_dict(usage)
    return delta


def delta_from_response(response: Any) -> StreamDelta:
    """Same, for a one-shot response object (``choices[0].message``)."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return StreamDelta(usage=usage_dict(getattr(response, "usage", None)))
    choice = choices[0]
    return delta_from_message(
        getattr(choice, "message", None),
        finish_reason=getattr(choice, "finish_reason", None),
        usage=getattr(response, "usage", None),
    )

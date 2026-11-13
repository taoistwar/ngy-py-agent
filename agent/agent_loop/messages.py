"""Message shaping and tool-call parsing helpers for the ReAct loop."""

import json
from typing import Any, Dict, List, Optional, Tuple

from agent.tools.file_access import default_workspace_root


def _to_content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _to_dict(message: Any) -> Dict[str, Any]:
    if isinstance(message, dict):
        return message

    role = getattr(message, "role", "assistant")
    content = _to_content_text(getattr(message, "content", ""))

    tool_calls_obj = getattr(message, "tool_calls", None)
    tool_calls = []
    for tool_call in tool_calls_obj or []:
        function = getattr(tool_call, "function", None)
        if function is None and isinstance(tool_call, dict):
            function = tool_call.get("function")
        if function is None:
            continue
        name = getattr(function, "name", None) or (
            function.get("name") if isinstance(function, dict) else None
        )
        if not name:
            continue
        arguments = getattr(function, "arguments", None)
        if arguments is None and isinstance(function, dict):
            arguments = function.get("arguments")
        if isinstance(arguments, str):
            function_args = arguments
        else:
            function_args = _to_content_text(arguments)
        # The id has to be the one the provider issued: it is what the tool result
        # message refers back to, and a message history whose ids disagree makes the
        # next request invalid. A dict-shaped tool call carries it under a key.
        call_id = getattr(tool_call, "id", None)
        if call_id is None and isinstance(tool_call, dict):
            call_id = tool_call.get("id")
        tool_calls.append(
            {
                "id": str(call_id or _new_id()),
                "type": "function",
                "function": {
                    "name": str(name),
                    "arguments": function_args,
                },
            }
        )

    result = {"role": role, "content": content}
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result


def _new_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _parse_tool_calls(message: Any) -> List[Tuple[str, Dict[str, Any], str]]:
    parsed = []
    raw_tool_calls = getattr(message, "tool_calls", None)
    if raw_tool_calls is None and isinstance(message, dict):
        raw_tool_calls = message.get("tool_calls", [])

    for call in raw_tool_calls or []:
        function = getattr(call, "function", None)
        if function is None and isinstance(call, dict):
            function = call.get("function")
        if function is None:
            continue

        name = getattr(function, "name", None) or (
            function.get("name") if isinstance(function, dict) else None
        )
        if not name:
            continue

        raw_args = getattr(function, "arguments", None)
        if raw_args is None and isinstance(function, dict):
            raw_args = function.get("arguments")

        try:
            args = (
                json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            )
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError:
            args = {}

        call_id = getattr(call, "id", None)
        if call_id is None and isinstance(call, dict):
            call_id = call.get("id")
        parsed.append((str(name), args, str(call_id or _new_id())))
    return parsed


def _tool_fallback_parse(content: str) -> Optional[Tuple[str, Dict[str, Any], str]]:
    """Some providers may return tool calls as JSON in plain text content."""
    text = (content or "").strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        # Not JSON: the content was prose after all, so there is no tool call here.
        return None
    if not isinstance(payload, dict):
        return None
    name = str(payload.get("name", "")).strip()
    if not name:
        return None
    args = payload.get("arguments", {})
    if not isinstance(args, dict):
        return None
    return name, args, _new_id()


def _with_history(
    messages: List[Dict[str, Any]],
    history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Put earlier turns between the system prompt and this task's query.

    The system prompt is a preamble, not a turn: an earlier conversation placed
    before it would read as if the model had answered before being told how to
    behave. The caller's list is copied, so a loop run never edits stored history.
    """
    merged = list(messages)
    insert_at = 1 if merged and merged[0].get("role") == "system" else 0
    merged[insert_at:insert_at] = [dict(message) for message in history]
    return merged


def _with_base_dir(prompt: str, base_dir: Optional[str]) -> str:
    """Append the working directory so relative paths resolve against that folder."""
    directory = (base_dir or "").strip()
    if not directory:
        # An unbound session still resolves relative paths somewhere, and the model
        # has to know where that is before it writes a file into it.
        return (
            f"{prompt}\n\n## Working directory\n"
            "This session has no workspace bound, so relative file paths resolve against "
            f"{default_workspace_root().as_posix()}. Use an absolute path when you need a "
            "specific location."
        )
    return (
        f"{prompt}\n\n## Working directory\n"
        f"All project tasks run inside the workspace root folder: {directory}\n"
        "Treat this folder as the base for every relative file path and keep all reads "
        "and writes inside it."
    )

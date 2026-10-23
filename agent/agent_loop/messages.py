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
        tool_calls.append(
            {
                "id": getattr(tool_call, "id", None) or str(_new_id()),
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

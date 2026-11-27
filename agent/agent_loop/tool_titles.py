"""The one-line title of a tool event: ``<tool> : <core argument>``.

The log is read as a feed, and the category tag already says "tool call", so the
title spends its width on what the call was about instead of repeating the kind.
Which argument says that is a property of the tool's schema, not something the
event sink can guess, hence the per-tool table below.
"""

from typing import Any, Dict, Tuple

# Characters of the argument the title carries. A row is one line in a narrow panel,
# and the full value is one click away in the event body.
VALUE_LIMIT = 60

# The argument that names a call, best first, for the tools where the common order
# would pick the wrong one.
CORE_ARGUMENTS: Dict[str, Tuple[str, ...]] = {
    # A command is a whole script; its description is the sentence the model wrote
    # about what that script does.
    "exec_command": ("description", "command"),
    # The subject is the task itself; its description is the body underneath.
    "task_create": ("subject", "task_id"),
}

# Tried after the per-tool table, and on their own for a tool the table does not
# know (an MCP server, say): anything a reader can recognize a call by.
COMMON_ARGUMENTS: Tuple[str, ...] = (
    "description",
    "command",
    "prompt",
    "query",
    "url",
    "file_path",
    "path",
    "pattern",
    "subject",
    "name",
    "task_id",
    "session_id",
    "code",
    "action",
)


def tool_title(name: str, arguments: Any) -> str:
    """``<name> : <core argument>`` for one call, or just ``<name>``."""
    core = _core_argument(name, arguments)
    return f"{name} : {core}" if core else name


def _core_argument(name: str, arguments: Any) -> str:
    """The value that names this call, or ``""`` when nothing names it."""
    if not isinstance(arguments, dict):
        return ""
    for key in CORE_ARGUMENTS.get(name, ()) + COMMON_ARGUMENTS:
        value = _inline(arguments.get(key))
        if value:
            return value
    # A schema nobody listed still usually opens with the argument that matters.
    for value in arguments.values():
        text = _inline(value)
        if text:
            return text
    return ""


def _inline(value: Any) -> str:
    """One clipped line for a scalar argument; empty for lists, objects and bools."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = " ".join(str(value).split())
    if len(text) <= VALUE_LIMIT:
        return text
    return text[: VALUE_LIMIT - 1].rstrip() + "…"


__all__ = ["VALUE_LIMIT", "tool_title"]

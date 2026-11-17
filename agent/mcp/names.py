"""How a remote MCP tool is named inside one tool registry.

Every remote tool is exposed as ``mcp__<server>__<tool>``. The prefix keeps a remote
tool from ever colliding with a built-in one, and the server segment is what the
permission dialog keys its answer on ("may this server's tools run"). Both parts are
sanitised because a preset name and a remote tool name are free text, while a
provider's function name is not.

Kept in its own module so the permission layer can read the server out of a tool name
without importing the client (and therefore a process-spawning stack).
"""

from __future__ import annotations

import re
from typing import Iterable

MCP_TOOL_PREFIX = "mcp__"
# OpenAI-compatible function names stop at 64 characters, and every provider this
# repo speaks is at least as strict.
MAX_TOOL_NAME = 64
# The separator between the server slug and the remote tool name. ``__`` cannot occur
# inside a slug, because every unsafe run collapses to a single ``_``.
_SEPARATOR = "__"
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def sanitize(part: str, fallback: str) -> str:
    """Reduce free text to the characters a function name may contain."""
    cleaned = _UNSAFE.sub("_", str(part or "").strip()).strip("_")
    return cleaned or fallback


def server_slug(name: str) -> str:
    """The server part of a tool name, e.g. ``filesystem``."""
    return sanitize(name, "server")


def tool_name(server: str, tool: str, taken: Iterable[str] = ()) -> str:
    """The registered name for one remote tool, unique against ``taken``.

    Truncation is allowed to cut the remote name (the server segment is what the
    permission rule needs), and a collision - from truncation, or from two remote
    names sanitising to the same string - gets a numeric suffix instead of silently
    overwriting the first one.
    """
    prefix = f"{MCP_TOOL_PREFIX}{server_slug(server)}{_SEPARATOR}"
    if len(prefix) >= MAX_TOOL_NAME:
        # A pathologically long server name: keep a recognisable tail of it.
        prefix = prefix[: MAX_TOOL_NAME - 1]
    cleaned = sanitize(tool, "tool")
    candidate = f"{prefix}{cleaned[: MAX_TOOL_NAME - len(prefix)]}"
    if candidate not in set(taken):
        return candidate
    index = 2
    while True:
        suffix = f"_{index}"
        stem = candidate[: MAX_TOOL_NAME - len(suffix)]
        attempt = f"{stem}{suffix}"
        if attempt not in set(taken):
            return attempt
        index += 1


def server_of(name: str) -> str | None:
    """The server segment of a registered name, or ``None`` when it is not an MCP one."""
    if not isinstance(name, str) or not name.startswith(MCP_TOOL_PREFIX):
        return None
    server, _separator, _tool = name[len(MCP_TOOL_PREFIX) :].partition(_SEPARATOR)
    return server or None


def remote_of(name: str) -> str | None:
    """The remote tool name a registered name was built from, or ``None``."""
    if not isinstance(name, str) or not name.startswith(MCP_TOOL_PREFIX):
        return None
    _server, separator, tool = name[len(MCP_TOOL_PREFIX) :].partition(_SEPARATOR)
    return tool if separator else None

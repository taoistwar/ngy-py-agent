"""Run one tool of a configured MCP server, once, without a task.

The connection test lists what a preset offers; this is the next step on that
page: pick a tool, type its arguments, see what the server answers. It is the
same conversation a task run has (``initialize`` then ``tools/call``), minus the
run, so a preset can be checked tool by tool before an agent depends on it.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from agent.mcp import session as mcp_session
from agent.mcp.jsonrpc import McpProtocolError
from agent.mcp.models import McpToolCallResult
from agent.mcp.probe import DEFAULT_PROBE_TIMEOUT_SECONDS
from agent.mcp.session import McpToolError
from agent.mcp.stdio import McpSessionError
from agent.mcp.transport import SUPPORTED_TRANSPORTS, normalize_transport, open_session


def call_server_tool(
    preset: Mapping[str, Any],
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
    timeout: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
) -> McpToolCallResult:
    """Call one tool on one preset and report what it returned."""
    tool = str(tool_name or "").strip()
    if not tool:
        return McpToolCallResult(
            ok=False,
            tool="",
            error="The tool name is empty, so there is nothing to call.",
        )

    transport = normalize_transport(preset.get("transport"))
    started = time.monotonic()
    if transport not in SUPPORTED_TRANSPORTS:
        return McpToolCallResult(
            ok=False,
            tool=tool,
            error=f"The '{transport}' transport is not supported; use stdio, sse or http.",
        )

    try:
        session = open_session(preset)
    except McpSessionError as exc:
        return McpToolCallResult(
            ok=False,
            tool=tool,
            error=str(exc),
            duration_ms=_elapsed_ms(started),
        )

    try:
        session.start()
        mcp_session.initialize(session, timeout)
        outcome = mcp_session.call_tool(session, tool, dict(arguments or {}), timeout)
    except (McpSessionError, McpProtocolError, McpToolError) as exc:
        return McpToolCallResult(
            ok=False,
            tool=tool,
            error=str(exc),
            duration_ms=_elapsed_ms(started),
        )
    finally:
        session.close()

    return McpToolCallResult(
        ok=True,
        tool=tool,
        result=outcome.model_text,
        duration_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)

"""Probe one configured MCP server: connect, handshake, list its tools, disconnect.

The same conversation a task run has, minus the run: this is what the marketplace's
test button asks for - "does this preset work, and what would it offer?" - before any
agent depends on it. Whatever transport the preset names, the answer has the same shape.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from agent.mcp import session as mcp_session
from agent.mcp.jsonrpc import McpProtocolError
from agent.mcp.models import McpProbeResult
from agent.mcp.stdio import McpSessionError
from agent.mcp.transport import SUPPORTED_TRANSPORTS, normalize_transport, open_session

# A cold ``npx`` downloads the package before the server says anything, and a remote
# server may have to wake up; the budget applies per request, not to the whole probe.
DEFAULT_PROBE_TIMEOUT_SECONDS = 60.0


def probe_server(
    preset: Mapping[str, Any], timeout: float = DEFAULT_PROBE_TIMEOUT_SECONDS
) -> McpProbeResult:
    """Connect to one MCP preset and report what it is and what it offers."""
    transport = normalize_transport(preset.get("transport"))
    started = time.monotonic()
    if transport not in SUPPORTED_TRANSPORTS:
        return McpProbeResult(
            ok=False,
            transport=transport,
            error=f"The '{transport}' transport is not supported; use stdio, sse or http.",
        )
    try:
        session = open_session(preset)
    except McpSessionError as exc:
        return McpProbeResult(
            ok=False,
            transport=transport,
            error=str(exc),
            duration_ms=_elapsed_ms(started),
        )

    try:
        session.start()
        info = mcp_session.initialize(session, timeout)
        tools = mcp_session.list_tools(session, timeout)
    except (McpSessionError, McpProtocolError) as exc:
        return McpProbeResult(
            ok=False,
            transport=transport,
            error=str(exc),
            duration_ms=_elapsed_ms(started),
        )
    finally:
        session.close()

    return McpProbeResult(
        ok=True,
        transport=transport,
        server_name=info.name,
        server_version=info.version,
        protocol_version=info.protocol_version,
        tools=tuple(tools),
        duration_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)

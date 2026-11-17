"""Probe one configured MCP server: connect, handshake, list its tools, disconnect.

The same conversation a task run has, minus the run: this is what the marketplace's
test button asks for - "does this preset work, and what would it offer?" - before any
agent depends on it.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from agent.mcp import session as mcp_session
from agent.mcp.jsonrpc import McpProtocolError
from agent.mcp.models import McpProbeResult
from agent.mcp.stdio import McpSessionError, StdioSession

# A cold ``npx`` downloads the package before the server says anything, so the budget
# is generous; it applies per request, not to the whole probe.
DEFAULT_PROBE_TIMEOUT_SECONDS = 60.0
SUPPORTED_PROBE_TRANSPORTS = ("stdio",)


def probe_server(
    preset: Mapping[str, Any], timeout: float = DEFAULT_PROBE_TIMEOUT_SECONDS
) -> McpProbeResult:
    """Connect to one MCP preset and report what it is and what it offers."""
    transport = str(preset.get("transport") or "stdio").strip().lower()
    target = str(preset.get("target") or "").strip()
    if transport not in SUPPORTED_PROBE_TRANSPORTS:
        return McpProbeResult(
            ok=False,
            transport=transport,
            error=f"The '{transport}' transport cannot be tested yet; only stdio is supported.",
        )
    if not target:
        return McpProbeResult(
            ok=False,
            transport=transport,
            error="The MCP target is empty, so there is no command to run.",
        )

    started = time.monotonic()
    session = StdioSession(target)
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

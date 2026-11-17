"""Probe one configured MCP server: connect, handshake, list its tools, disconnect.

Deliberately not a tool bridge. An agent's stored MCP presets are still only
configurations (see ``dao/mcp.py``), so until a run can actually call a remote tool
the useful question is "does this preset work, and what would it offer?" - which is
what the marketplace's test button asks.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from agent.mcp.jsonrpc import McpProtocolError
from agent.mcp.models import McpProbeResult, McpToolInfo
from agent.mcp.stdio import McpSessionError, StdioSession

# What this client offers to speak. A server that only knows an older revision
# answers with the revision it picked, which is why the answer is reported back
# rather than assumed.
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "ngy-py-agent", "version": "0.1.0"}
# A cold ``npx`` downloads the package before the server says anything, so the budget
# is generous; it applies per request, not to the whole probe.
DEFAULT_PROBE_TIMEOUT_SECONDS = 60.0
# A server that never stopped paginating would otherwise keep the dialog waiting.
_MAX_TOOL_PAGES = 20
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
    server_name = ""
    server_version = ""
    protocol_version = ""
    tools: list[McpToolInfo] = []
    try:
        session.start()
        server_name, server_version, protocol_version = _initialize(session, timeout)
        tools = _list_tools(session, timeout)
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
        server_name=server_name,
        server_version=server_version,
        protocol_version=protocol_version,
        tools=tuple(tools),
        duration_ms=_elapsed_ms(started),
    )


def _initialize(session: StdioSession, timeout: float) -> tuple[str, str, str]:
    """Handshake, then tell the server the handshake is done. Returns its identity."""
    result = session.request(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": dict(CLIENT_INFO),
        },
        timeout,
    )
    # Required by the specification: without it a server may refuse to answer anything
    # else, and the failure looks like a broken preset rather than a missing step.
    session.notify("notifications/initialized")
    info = result.get("serverInfo")
    server = info if isinstance(info, dict) else {}
    return (
        str(server.get("name") or ""),
        str(server.get("version") or ""),
        str(result.get("protocolVersion") or ""),
    )


def _list_tools(session: StdioSession, timeout: float) -> list[McpToolInfo]:
    """Every tool the server offers, following its pagination cursors."""
    tools: list[McpToolInfo] = []
    cursor: str | None = None
    for _ in range(_MAX_TOOL_PAGES):
        result = session.request("tools/list", {"cursor": cursor} if cursor else {}, timeout)
        entries = result.get("tools")
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            tool = _tool_info(entry)
            if tool is not None:
                tools.append(tool)
        cursor = _next_cursor(result)
        if cursor is None:
            break
    return tools


def _tool_info(entry: dict[str, Any]) -> McpToolInfo | None:
    """One ``tools/list`` entry, or ``None`` when it has no usable name."""
    name = str(entry.get("name") or "").strip()
    if not name:
        return None
    schema = entry.get("inputSchema")
    return McpToolInfo(
        name=name,
        description=str(entry.get("description") or ""),
        input_schema=schema if isinstance(schema, dict) else {},
    )


def _next_cursor(result: dict[str, Any]) -> str | None:
    cursor = result.get("nextCursor")
    return cursor if isinstance(cursor, str) and cursor else None


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)

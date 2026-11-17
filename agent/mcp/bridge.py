"""Turn the MCP servers an agent selected into tools this run can call.

One bridge per run: it opens each configured server, asks for its tools, and registers
them as ``mcp__<server>__<tool>``. A server that cannot start is reported in the status
list and skipped - one broken preset must not cost the run its other tools, and it must
never fail the task.

The tools are ordinary registry entries, so the deny-list, the permission gate, the
result budget and the event stream apply to them exactly as they do to built-ins; there
is no second dispatch path (ADR 0031).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from agent.mcp import session as mcp_session
from agent.mcp.jsonrpc import McpProtocolError
from agent.mcp.models import McpToolInfo
from agent.mcp.names import tool_name
from agent.mcp.stdio import McpSessionError, StdioSession
from agent.tools.permissions import PERMISSION_MCP
from agent.tools.spec import CATEGORY_OTHER

# Long enough for a cold ``npx`` download, per request.
DEFAULT_START_TIMEOUT_SECONDS = 60.0
# A remote tool may be slower than a built-in one (it is a network call in the best
# case), but the loop is blocked while it runs, so the budget stays finite.
DEFAULT_CALL_TIMEOUT_SECONDS = 120.0
SUPPORTED_TRANSPORTS = ("stdio",)


@dataclass(frozen=True)
class McpServerStatus:
    """What happened to one configured server, as the task log reports it."""

    name: str
    ok: bool
    tool_count: int = 0
    error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "tool_count": self.tool_count,
            "error": self.error,
        }


@dataclass(frozen=True)
class _ConnectedServer:
    """One server that answered, and the tools it offered."""

    label: str
    server_name: str
    session: StdioSession
    tools: Sequence[McpToolInfo]


class McpBridge:
    """The servers of one run, opened together and closed together."""

    def __init__(
        self,
        presets: Iterable[Mapping[str, Any]],
        *,
        start_timeout: float = DEFAULT_START_TIMEOUT_SECONDS,
        call_timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS,
    ) -> None:
        self._presets = [dict(preset) for preset in presets or []]
        self.start_timeout = start_timeout
        self.call_timeout = call_timeout
        self._servers: List[_ConnectedServer] = []
        self._statuses: List[McpServerStatus] = []
        self._lock = threading.Lock()

    @property
    def statuses(self) -> List[Dict[str, Any]]:
        """One entry per configured server, including the ones that failed."""
        return [status.as_dict() for status in self._statuses]

    @property
    def connected(self) -> List[_ConnectedServer]:
        return list(self._servers)

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> List[Dict[str, Any]]:
        """Connect to every preset in turn, keeping whatever answered."""
        for preset in self._presets:
            self._statuses.append(self._open_one(preset))
        return self.statuses

    def _open_one(self, preset: Mapping[str, Any]) -> McpServerStatus:
        label = str(preset.get("name") or preset.get("target") or "mcp").strip() or "mcp"
        transport = str(preset.get("transport") or "stdio").strip().lower()
        target = str(preset.get("target") or "").strip()
        if transport not in SUPPORTED_TRANSPORTS:
            return McpServerStatus(
                name=label,
                ok=False,
                error=f"The '{transport}' transport is not supported yet; only stdio is.",
            )
        if not target:
            return McpServerStatus(
                name=label,
                ok=False,
                error="The MCP target is empty, so there is no command to run.",
            )

        session = StdioSession(target)
        try:
            session.start()
            info = mcp_session.initialize(session, self.start_timeout)
            tools = mcp_session.list_tools(session, self.start_timeout)
        except (McpSessionError, McpProtocolError) as exc:
            session.close()
            return McpServerStatus(name=label, ok=False, error=str(exc))
        self._servers.append(
            _ConnectedServer(
                label=label,
                server_name=info.name,
                session=session,
                tools=tuple(tools),
            )
        )
        return McpServerStatus(name=label, ok=True, tool_count=len(tools))

    def close(self) -> None:
        """Stop every server this bridge opened. Safe to call twice."""
        with self._lock:
            servers, self._servers = self._servers, []
        for server in servers:
            server.session.close()

    # -- tools -------------------------------------------------------------

    def register(self, registry: Any) -> int:
        """Register every connected tool on ``registry``; returns how many were added."""
        # The built-ins are already there, so a remote name must not shadow one.
        taken = set(registry.tools)
        added = 0
        for server in self._servers:
            for tool in server.tools:
                name = tool_name(server.label, tool.name, taken)
                taken.add(name)
                registry.register_tool(
                    name=name,
                    function=self._handler(server, tool),
                    description=_description(server, tool),
                    parameters=_parameters(tool),
                    permission=PERMISSION_MCP,
                    category=CATEGORY_OTHER,
                )
                added += 1
        return added

    def _handler(self, server: _ConnectedServer, tool: McpToolInfo):
        """A registry handler that forwards the call unchanged to the remote tool.

        The arguments are the remote tool's own schema, so they are passed through as
        they arrived: rewriting them here would be a second, silently different contract.
        """

        def call(**arguments: Any) -> str:
            return mcp_session.call_tool(
                server.session, tool.name, arguments, self.call_timeout
            )

        return call


def _description(server: _ConnectedServer, tool: McpToolInfo) -> str:
    """Model-facing text: the server's own words, plus where the tool came from."""
    origin = f"MCP server {server.label}"
    if server.server_name and server.server_name != server.label:
        origin = f"{origin} ({server.server_name})"
    body = tool.description.strip() or f"Run {tool.name} on the {origin}."
    return f"{body}\n\nProvided by {origin}."


def _parameters(tool: McpToolInfo) -> Dict[str, Any]:
    """The remote schema, normalised to the object shape a tool call needs."""
    schema = dict(tool.input_schema or {})
    schema.setdefault("type", "object")
    properties = schema.get("properties")
    schema["properties"] = properties if isinstance(properties, dict) else {}
    return schema

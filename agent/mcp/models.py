"""What a probe reports back: the server's identity and the tools it exposes.

Plain dataclasses rather than pydantic models, because ``agent/`` must stay free of
the HTTP layer's imports; the route turns these into its response models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class McpToolInfo:
    """One entry of a server's ``tools/list`` answer."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
        }


@dataclass(frozen=True)
class McpToolCallResult:
    """Outcome of one hand-run tool call from the marketplace.

    Like the probe, a failed call is a result to read: ``ok`` is false and ``error``
    carries the server's own wording, so the page renders it instead of catching.
    """

    ok: bool
    tool: str
    result: str = ""
    error: str = ""
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class McpProbeResult:
    """Outcome of one connection attempt.

    A failed attempt is still a result: ``ok`` is false and ``error`` says what went
    wrong, so the caller renders it instead of catching an exception per client.
    """

    ok: bool
    transport: str
    server_name: str = ""
    server_version: str = ""
    protocol_version: str = ""
    tools: tuple[McpToolInfo, ...] = ()
    error: str = ""
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "transport": self.transport,
            "server_name": self.server_name,
            "server_version": self.server_version,
            "protocol_version": self.protocol_version,
            "tools": [tool.as_dict() for tool in self.tools],
            "error": self.error,
            "duration_ms": self.duration_ms,
        }

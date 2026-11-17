"""MCP support: a connection probe today, a tool bridge later.

Agents store MCP presets and select them (``dao/mcp.py``, ``commons/schemas``), but
no remote tool is registered in a run yet. What exists here is the client side of a
single conversation - spawn, ``initialize``, ``tools/list`` - so a preset can be
checked from the marketplace before the bridge is built.

The package imports nothing from ``commons`` or ``dao``: it must stay usable from a
test, a script or a future runner without the web app.
"""

from agent.mcp.models import McpProbeResult, McpToolInfo
from agent.mcp.probe import (
    DEFAULT_PROBE_TIMEOUT_SECONDS,
    PROTOCOL_VERSION,
    SUPPORTED_PROBE_TRANSPORTS,
    probe_server,
)

__all__ = [
    "DEFAULT_PROBE_TIMEOUT_SECONDS",
    "PROTOCOL_VERSION",
    "SUPPORTED_PROBE_TRANSPORTS",
    "McpProbeResult",
    "McpToolInfo",
    "probe_server",
]

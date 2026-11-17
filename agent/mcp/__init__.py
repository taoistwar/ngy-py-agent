"""MCP support: a connection probe, and the bridge that gives a run its tools.

Agents store MCP presets and select them (``dao/mcp.py``, ``commons/schemas``). The
marketplace can test a preset without a task (``probe``), and a task whose agent
selected servers gets their tools registered as ``mcp__<server>__<tool>``
(``bridge`` + ``live``), with the confirmation gate keyed on the server.

Three transports are understood: a local command (``stdio``), Streamable HTTP
(``http``) and the older two-endpoint SSE transport (``sse``). ``transport.open_session``
is the only place that decides which one a preset means.

The package imports nothing from ``commons`` or ``dao``: it must stay usable from a
test, a script or the loop without the web app.
"""

from agent.mcp.models import McpProbeResult, McpToolInfo
from agent.mcp.probe import DEFAULT_PROBE_TIMEOUT_SECONDS, probe_server
from agent.mcp.protocol import PROTOCOL_VERSION
from agent.mcp.transport import SUPPORTED_TRANSPORTS

__all__ = [
    "DEFAULT_PROBE_TIMEOUT_SECONDS",
    "PROTOCOL_VERSION",
    "SUPPORTED_TRANSPORTS",
    "McpProbeResult",
    "McpToolInfo",
    "probe_server",
]

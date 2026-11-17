"""What every MCP transport agrees on: the revision this client speaks, and its shape.

Its own module so the transports, the session helpers and the factory can all import the
same constants without importing each other.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

# What this client offers to speak. A server that only knows an older revision answers
# with the revision it picked, which is why the answer is reported rather than assumed.
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "ngy-py-agent", "version": "0.1.0"}


class McpSession(Protocol):
    """One conversation with a server, whichever transport carries it.

    ``start`` opens whatever needs opening (a process, a stream), ``request`` sends one
    JSON-RPC call and returns its ``result``, ``notify`` sends a message nobody answers,
    and ``close`` releases everything without raising when it is already gone.
    """

    def start(self) -> None: ...

    def request(
        self, method: str, params: Optional[Dict[str, Any]], timeout: float
    ) -> Dict[str, Any]: ...

    def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None: ...

    def close(self) -> None: ...

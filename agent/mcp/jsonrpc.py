"""JSON-RPC 2.0 framing for the MCP stdio transport.

The stdio transport in the MCP specification is one JSON message per line, UTF-8
encoded, with no embedded newline. Keeping the framing here means the session code
only ever deals with dictionaries, and a malformed peer surfaces as one exception
type instead of an ``AttributeError`` three frames deeper.
"""

from __future__ import annotations

import json
from typing import Any

JSONRPC_VERSION = "2.0"
# JSON-RPC 2.0 error codes this client sends. The spec reserves them, so a server
# can tell "I do not implement that" from this client's own failures.
METHOD_NOT_FOUND = -32601


class McpProtocolError(Exception):
    """The peer sent something that is not a JSON-RPC 2.0 message."""


def encode_request(request_id: int, method: str, params: dict[str, Any] | None = None) -> str:
    """One request line. ``params`` is omitted rather than sent as ``null``."""
    message: dict[str, Any] = {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "method": method,
    }
    if params is not None:
        message["params"] = params
    return json.dumps(message, ensure_ascii=False)


def encode_notification(method: str, params: dict[str, Any] | None = None) -> str:
    """One notification line: same as a request, without an ``id``."""
    message: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
    if params is not None:
        message["params"] = params
    return json.dumps(message, ensure_ascii=False)


def encode_error(request_id: Any, code: int, message: str) -> str:
    """Answer a server-initiated request with an error, so the server is not left waiting."""
    payload = {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }
    return json.dumps(payload, ensure_ascii=False)


def decode_message(line: str) -> dict[str, Any]:
    """Parse one line into a message object, or raise ``McpProtocolError``."""
    text = line.strip()
    if not text:
        raise McpProtocolError("The MCP server sent an empty line.")
    try:
        message = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpProtocolError(
            f"The MCP server sent a line that is not JSON: {_preview(text)}"
        ) from exc
    if not isinstance(message, dict):
        raise McpProtocolError(f"The MCP server sent JSON that is not an object: {_preview(text)}")
    if message.get("jsonrpc") != JSONRPC_VERSION:
        raise McpProtocolError(f"The MCP server sent JSON-RPC that is not version 2.0: {_preview(text)}")
    return message


def _preview(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…"

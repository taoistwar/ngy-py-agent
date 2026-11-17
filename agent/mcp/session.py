"""The client half of an MCP conversation: handshake, tool list and tool calls.

Shared by the marketplace probe (one short conversation) and a task's tool bridge (a
conversation as long as the run), so the two cannot drift on what a handshake is or
on how a tool result is read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, List

from agent.mcp.images import tool_image_from_block
from agent.mcp.models import McpToolInfo
from agent.mcp.protocol import CLIENT_INFO, PROTOCOL_VERSION, McpSession
from agent.models import ToolImage, ToolOutcome

# A server that never stopped paginating would otherwise keep the caller waiting.
_MAX_TOOL_PAGES = 20

__all__ = [
    "PROTOCOL_VERSION",
    "McpToolError",
    "McpServerInfo",
    "initialize",
    "list_tools",
    "call_tool",
]


class McpToolError(Exception):
    """The remote tool ran and reported a failure of its own.

    Raised rather than returned because a failed tool call is not a result the model
    should keep as success: ``agent_loop`` turns it into the step's error, and the
    model reads "Error: <text the server gave>".
    """


@dataclass(frozen=True)
class McpServerInfo:
    """What the server called itself during ``initialize``."""

    name: str = ""
    version: str = ""
    protocol_version: str = ""


def initialize(session: McpSession, timeout: float) -> McpServerInfo:
    """Handshake, then tell the server the handshake is done."""
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
    return McpServerInfo(
        name=str(server.get("name") or ""),
        version=str(server.get("version") or ""),
        protocol_version=str(result.get("protocolVersion") or ""),
    )


def list_tools(session: McpSession, timeout: float) -> list[McpToolInfo]:
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


def call_tool(
    session: McpSession, tool: str, arguments: dict[str, Any], timeout: float
) -> ToolOutcome:
    """Run one remote tool and return what the model should read and see.

    Raises ``McpToolError`` when the server answers ``isError``, and lets the session's
    own ``McpSessionError`` / ``McpProtocolError`` through when the conversation itself
    failed: both reach the model as this step's error, with the server's own wording.
    """
    result = session.request(
        "tools/call",
        {"name": tool, "arguments": dict(arguments or {})},
        timeout,
    )
    text = _content_text(result)
    if result.get("isError"):
        raise McpToolError(text)
    return ToolOutcome(model_text=text, images=_content_images(result))


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


def _content_text(result: dict[str, Any]) -> str:
    """Flatten a ``tools/call`` result into the text the model sees.

    The specification allows a list of typed blocks; text is passed through, a resource
    keeps its URI, and media blocks become a one-line marker - the model cannot use the
    bytes anyway, and pretending it can would be worse than saying what arrived.
    """
    parts: list[str] = []
    content = result.get("content")
    for item in content if isinstance(content, list) else []:
        if isinstance(item, dict):
            parts.append(_block_text(item))
    if not any(part.strip() for part in parts):
        structured = result.get("structuredContent")
        if structured is not None:
            parts.append(json.dumps(structured, ensure_ascii=False, indent=2))
    text = "\n".join(part for part in parts if part.strip()).strip()
    return text or "(the MCP tool returned no content)"


def _block_text(block: dict[str, Any]) -> str:
    kind = str(block.get("type") or "")
    if kind == "text":
        return str(block.get("text") or "")
    if kind == "resource":
        resource = block.get("resource")
        if isinstance(resource, dict):
            uri = str(resource.get("uri") or "")
            body = resource.get("text")
            if isinstance(body, str) and body:
                return f"{uri}\n{body}".strip()
            return uri
        return str(resource or "")
    if kind in ("image", "audio"):
        media = str(block.get("mimeType") or "unknown type")
        # The text says what arrived; the bytes travel separately (and only image
        # blocks that the vision layer can send become an attachment).
        return f"[{kind} {media}]"
    return json.dumps(block, ensure_ascii=False)[:1000]


def _content_images(result: dict[str, Any]) -> List[ToolImage]:
    """Image attachments for one ``tools/call`` result.

    A block that cannot be decoded, is too large, or is a format the vision layer does
    not send is left out silently: the text marker already says an image arrived, and
    failing the tool call over its screenshot would lose the model's real answer.
    """
    images: List[ToolImage] = []
    content = result.get("content")
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "image":
            continue
        image = tool_image_from_block(block)
        if image is not None:
            images.append(image)
    return images

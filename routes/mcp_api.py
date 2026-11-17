"""HTTP API for the MCP server marketplace.

Agents select MCP servers from this marketplace instead of typing the transport
and target by hand. The router is mounted by ``main.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from agent.mcp import probe_server
from dao.mcp import MCP_TRANSPORTS, mcp_store

router = APIRouter(prefix="/api/mcp-servers", tags=["mcp"])


class McpServerUpsertRequest(BaseModel):
    """Create or replace one MCP server preset."""

    name: str = Field(min_length=1, max_length=200, description="Display name.")
    description: str = Field(default="", max_length=1024, description="What the server provides.")
    transport: str = Field(default="stdio", max_length=32, description="stdio or sse.")
    target: str = Field(default="", max_length=1024, description="Command line or URL.")


class McpServerUpdateRequest(BaseModel):
    """Partial update of one MCP server preset."""

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1024)
    transport: str | None = Field(default=None, max_length=32)
    target: str | None = Field(default=None, max_length=1024)


class McpServerItemResponse(BaseModel):
    """One MCP server preset."""

    mcp_id: str
    name: str
    description: str = ""
    transport: str = "stdio"
    target: str = ""
    created_at: datetime
    updated_at: datetime


class McpServerListResponse(BaseModel):
    """MCP marketplace listing."""

    servers: list[McpServerItemResponse]


class McpToolItemResponse(BaseModel):
    """One tool a probed server exposes."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class McpProbeResponse(BaseModel):
    """Outcome of one connection test.

    A failed attempt is a 200 with ``ok`` false and ``error`` filled in: the server
    answered the request, it was the server behind it that did not work.
    """

    ok: bool
    transport: str
    server_name: str = ""
    server_version: str = ""
    protocol_version: str = ""
    tools: list[McpToolItemResponse] = Field(default_factory=list)
    error: str = ""
    duration_ms: int = 0


def _reject_unknown_transport(transport: str | None) -> None:
    if transport is not None and transport not in MCP_TRANSPORTS:
        allowed = ", ".join(MCP_TRANSPORTS)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported MCP transport '{transport}'. Use one of: {allowed}.",
        )


@router.get("", response_model=McpServerListResponse)
async def list_mcp_servers() -> McpServerListResponse:
    """List every MCP server in the marketplace."""
    return McpServerListResponse(
        servers=[McpServerItemResponse(**item) for item in mcp_store.list_servers()]
    )


@router.post("", response_model=McpServerItemResponse)
async def create_mcp_server(payload: McpServerUpsertRequest) -> McpServerItemResponse:
    """Add a new MCP server to the marketplace."""
    _reject_unknown_transport(payload.transport)
    created = mcp_store.create_server(payload.model_dump())
    return McpServerItemResponse(**created)


@router.put("/{mcp_id}", response_model=McpServerItemResponse)
async def update_mcp_server(mcp_id: str, payload: McpServerUpdateRequest) -> McpServerItemResponse:
    """Update one MCP server (partial update)."""
    _reject_unknown_transport(payload.transport)
    updated = mcp_store.update_server(mcp_id, payload.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="MCP server not found.")
    return McpServerItemResponse(**updated)


@router.post("/{mcp_id}/probe", response_model=McpProbeResponse)
async def probe_mcp_server(mcp_id: str) -> McpProbeResponse:
    """Connect once and report what the server is and which tools it offers.

    Spawning the command is blocking work, so it runs in a worker thread: a cold
    ``npx`` must not hold the event loop every other request answers on.
    """
    server = mcp_store.get_server(mcp_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found.")
    result = await run_in_threadpool(probe_server, server)
    return McpProbeResponse(**result.as_dict())


@router.delete("/{mcp_id}")
async def delete_mcp_server(mcp_id: str) -> dict[str, Any]:
    """Remove one MCP server from the marketplace.

    Agents that already reference it keep their stored copy.
    """
    if not mcp_store.delete_server(mcp_id):
        raise HTTPException(status_code=404, detail="MCP server not found.")
    return {"mcp_id": mcp_id, "deleted": True}

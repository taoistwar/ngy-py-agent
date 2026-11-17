"""Workspaces a task runs in, plus the MCP presets an agent may carry."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WorkspaceCreateRequest(BaseModel):
    """Create workspace request."""

    name: str = Field(min_length=1, max_length=120, description="Workspace name.")
    root_path: str = Field(
        min_length=1,
        max_length=1024,
        description="Workspace root folder; tasks run relative to it.",
    )


class WorkspaceUpdateRequest(BaseModel):
    """Partial update of a workspace."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    root_path: str | None = Field(default=None, min_length=1, max_length=1024)


class WorkspaceItemResponse(BaseModel):
    """Workspace list item."""

    workspace_id: str
    name: str
    root_path: str
    created_at: datetime
    updated_at: datetime
    session_count: int = 0


class WorkspaceListResponse(BaseModel):
    """Workspace list response."""

    workspaces: list[WorkspaceItemResponse]


class McpServerConfig(BaseModel):
    """One MCP server entry configured on an agent.

    The entry is a snapshot resolved from the MCP marketplace. ``mcp_id`` keeps
    the link back to that marketplace entry so the agent editor can restore the
    selection; it is absent on entries written before the marketplace existed.
    """

    name: str = Field(min_length=1, max_length=120, description="MCP server name.")
    transport: str = Field(
        default="stdio", max_length=32, description="stdio, sse or http (Streamable HTTP)."
    )
    target: str = Field(
        default="", max_length=1024, description="Command (stdio) or URL (sse/http)."
    )
    mcp_id: str | None = Field(default=None, max_length=64, description="Marketplace entry id.")

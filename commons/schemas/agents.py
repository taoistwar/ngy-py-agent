"""Agent configurations: the system prompt, tools, skills and MCP servers it runs with."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from commons.schemas.workspace import McpServerConfig


class AgentUpsertRequest(BaseModel):
    """Create or update an agent configuration."""

    name: str = Field(min_length=1, max_length=120, description="Agent name.")
    icon: str = Field(
        default="",
        max_length=32,
        pattern=r"^[a-z0-9_-]*$",
        description="Icon key rendered by the web admin agent picker; empty means default.",
    )
    description: str = Field(default="", max_length=2000)
    system_prompt: str = Field(default="", description="System prompt used for this agent.")
    tool_names: list[str] | None = Field(
        default=None,
        description="Allowed tool names; null means all registered tools.",
    )
    skill_names: list[str] = Field(default_factory=list, description="Enabled skill names.")
    mcp_servers: list[McpServerConfig] = Field(default_factory=list, description="MCP servers.")


class AgentUpdateRequest(BaseModel):
    """Partial update of an agent configuration."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    icon: str | None = Field(default=None, max_length=32, pattern=r"^[a-z0-9_-]*$")
    description: str | None = Field(default=None, max_length=2000)
    system_prompt: str | None = None
    tool_names: list[str] | None = None
    skill_names: list[str] | None = None
    mcp_servers: list[McpServerConfig] | None = None


class AgentItemResponse(BaseModel):
    """Agent configuration item."""

    agent_id: str
    name: str
    icon: str = ""
    description: str = ""
    system_prompt: str = ""
    tool_names: list[str] | None = None
    skill_names: list[str] = Field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    is_builtin: bool = False
    created_at: datetime
    updated_at: datetime


class AgentListResponse(BaseModel):
    """Agent list response."""

    agents: list[AgentItemResponse]

"""Global settings the admin API reads and writes: retention, step cap, AGENTS.md, mode."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent.agents_md import MAX_BYTES_LIMIT as AGENTS_MD_MAX_BYTES_LIMIT
from agent.agents_md import MIN_MAX_BYTES as AGENTS_MD_MIN_BYTES

# One cap for the global setting and the per-task override. The ReAct loop is linear in
# steps, so this exists to reject runaway values, not to model a budget.
MAX_STEPS_LIMIT = 10_000


class RetentionConfigRequest(BaseModel):
    """Retention config request."""

    retention_days: int = Field(
        ge=0, description="Keep task detail data for this many days. 0 means keep all."
    )


class MaxStepsConfigRequest(BaseModel):
    """Global ReAct max steps config request."""

    max_steps: int = Field(
        ge=1, le=MAX_STEPS_LIMIT, description="Global limit of ReAct steps applied to new tasks."
    )


class MaxStepsConfigResponse(BaseModel):
    """Global ReAct max steps config response."""

    max_steps: int
    source: str


class AgentsMdConfigRequest(BaseModel):
    """Global AGENTS.md instruction config request."""

    enabled: bool = Field(
        description="Read the workspace's AGENTS.md files into the system prompt."
    )
    max_bytes: int = Field(
        ge=AGENTS_MD_MIN_BYTES,
        le=AGENTS_MD_MAX_BYTES_LIMIT,
        description="Byte cap for one AGENTS.md file; the rest is truncated.",
    )


class AgentsMdConfigResponse(BaseModel):
    """Global AGENTS.md instruction config response."""

    enabled: bool
    max_bytes: int
    source: str


class PermissionModeConfigRequest(BaseModel):
    """Global tool permission mode request."""

    mode: str = Field(description="ask / auto_approve / deny_all")


class PermissionModeConfigResponse(BaseModel):
    """Global tool permission mode response."""

    mode: str
    source: str


class RetentionConfigResponse(BaseModel):
    """Retention config response."""

    retention_days: int
    retention_source: str
    removed_tasks: int

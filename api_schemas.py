"""The HTTP request and response models, in one place.

They are pure types with no behaviour, so they live apart from both the routes that
return them and the app state they describe. Splitting them out is also what keeps the
route modules about routing (see ``app_state.py`` for the state and ``main.py`` for the
app assembly).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agent.modes import DEFAULT_MODE


class RunTaskRequest(BaseModel):
    """Create task request."""

    query: str = Field(min_length=1, description="User input")
    provider: str | None = None
    model_id: str | None = Field(default=None, description="Configured model id.")
    session_id: str | None = Field(default=None, description="Owning session id.")
    max_steps: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Optional override; omit to use the global REACT_MAX_STEPS config.",
    )
    agent_id: str | None = Field(
        default=None,
        description="Configured agent id; falls back to mode / the default agent when omitted.",
    )
    mode: str = Field(
        default=DEFAULT_MODE,
        description="Legacy agent mode (build / ask / plan); used when agent_id is omitted.",
    )
    permission_mode: str | None = Field(
        default=None,
        description=(
            "Optional override for tool confirmation (ask / auto_approve / deny_all); "
            "omit to use the global config."
        ),
    )
    stream: bool = False


class RunTaskResponse(BaseModel):
    """Create task response."""

    task_id: str
    status: str
    mode: str
    created_at: datetime


class TaskListItemResponse(BaseModel):
    """Task list item."""

    task_id: str
    query: str
    status: str
    provider: str
    session_id: str | None = None
    model_id: str | None = None
    model_name: str | None = None
    mode: str = DEFAULT_MODE
    created_at: datetime
    updated_at: datetime
    event_count: int
    result: str | None = None
    # Present while the task is blocked on a confirmation, so a task waiting in
    # the background is visible without opening it.
    pending_permission: dict[str, Any] | None = None
    # Same idea for the question channel: a batch the model is waiting on.
    pending_question: dict[str, Any] | None = None


class TaskDetailResponse(BaseModel):
    """Task detail."""

    task_id: str
    query: str
    status: str
    provider: str
    session_id: str | None = None
    model_id: str | None = None
    model_name: str | None = None
    mode: str = DEFAULT_MODE
    created_at: datetime
    updated_at: datetime
    result: str | None = None
    # Set while the task is blocked on a confirmation, so a client that (re)connects
    # late can still render the dialog without replaying the whole event stream.
    pending_permission: dict[str, Any] | None = None
    # Same for a pending question batch: the dialog is rendered from this, not from
    # the event stream, so a late client still sees it.
    pending_question: dict[str, Any] | None = None
    events: list[dict[str, Any]]


class EventResponse(BaseModel):
    """Event response."""

    events: list[dict[str, Any]]


class EventPageResponse(BaseModel):
    """Paged event response."""

    items: list[dict[str, Any]]
    offset: int
    limit: int
    next_offset: int
    total: int
    has_more: bool


class TaskListResponse(BaseModel):
    """Task list response."""

    tasks: list[TaskListItemResponse]


class RetentionConfigRequest(BaseModel):
    """Retention config request."""

    retention_days: int = Field(
        ge=0, description="Keep task detail data for this many days. 0 means keep all."
    )


class MaxStepsConfigRequest(BaseModel):
    """Global ReAct max steps config request."""

    max_steps: int = Field(
        ge=1, le=40, description="Global limit of ReAct steps applied to new tasks."
    )


class MaxStepsConfigResponse(BaseModel):
    """Global ReAct max steps config response."""

    max_steps: int
    source: str


class PermissionModeConfigRequest(BaseModel):
    """Global tool permission mode request."""

    mode: str = Field(description="ask / auto_approve / deny_all")


class PermissionModeConfigResponse(BaseModel):
    """Global tool permission mode response."""

    mode: str
    source: str


class PermissionRuleItem(BaseModel):
    """One persisted allow rule."""

    tool: str
    target: str
    kind: str = ""
    created_at: str = ""


class PermissionRuleListResponse(BaseModel):
    """Persisted allow rules."""

    rules: list[PermissionRuleItem]
    path: str


class PermissionRuleRequest(BaseModel):
    """Add a persisted allow rule without going through a dialog."""

    tool: str = Field(min_length=1, description="Tool name, e.g. exec.")
    target: str = Field(min_length=1, description="The exact target shown in the dialog.")


class PermissionDecisionRequest(BaseModel):
    """Answer to a pending permission request."""

    allowed: bool = Field(description="Whether the tool call may run.")
    scope: str = Field(
        default="once", description="once / session / always, as offered by the tool"
    )


class PermissionDecisionResponse(BaseModel):
    """Result of answering a permission request."""

    task_id: str
    request_id: str
    allowed: bool
    scope: str


class QuestionAnswerRequest(BaseModel):
    """Answer to a pending question batch.

    ``answers`` is keyed by question id and each value is ``{"answers": [...]}``, i.e.
    the same shape the model is promised as output. A question the user skipped may be
    omitted or carry an empty list (ADR 0010 D5).
    """

    answers: dict[str, Any] = Field(
        default_factory=dict,
        description='Answers keyed by question id, each an object with an "answers" array.',
    )


class QuestionAnswerResponse(BaseModel):
    """Result of answering a pending question batch."""

    task_id: str
    request_id: str
    status: str
    answered_count: int


class RetentionConfigResponse(BaseModel):
    """Retention config response."""

    retention_days: int
    retention_source: str
    removed_tasks: int


class SessionCreateRequest(BaseModel):
    """Create session request."""

    name: str | None = Field(
        default=None,
        max_length=120,
        description="Session name; auto-generated from the current time when omitted.",
    )
    workspace_id: str | None = Field(
        default=None,
        description="Owning workspace id; empty means the session has no workspace.",
    )


class SessionUpdateRequest(BaseModel):
    """Rename session request."""

    name: str = Field(min_length=1, max_length=120, description="Session name.")


class SessionItemResponse(BaseModel):
    """Session list item."""

    session_id: str
    name: str
    workspace_id: str | None = None
    created_at: datetime
    updated_at: datetime
    task_count: int = 0
    query_preview: str = ""
    result_preview: str = ""


class SessionListResponse(BaseModel):
    """Session list response."""

    sessions: list[SessionItemResponse]


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
    transport: str = Field(default="stdio", max_length=32, description="stdio or sse.")
    target: str = Field(default="", max_length=1024, description="Command (stdio) or URL (sse).")
    mcp_id: str | None = Field(default=None, max_length=64, description="Marketplace entry id.")


class AgentUpsertRequest(BaseModel):
    """Create or update an agent configuration."""

    name: str = Field(min_length=1, max_length=120, description="Agent name.")
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
    description: str | None = Field(default=None, max_length=2000)
    system_prompt: str | None = None
    tool_names: list[str] | None = None
    skill_names: list[str] | None = None
    mcp_servers: list[McpServerConfig] | None = None


class AgentItemResponse(BaseModel):
    """Agent configuration item."""

    agent_id: str
    name: str
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


class SkillsRootUpdateRequest(BaseModel):
    """Update the shared skills root folder."""

    skills_root: str = Field(default="", max_length=1024, description="Shared skills root folder.")


class SkillImportRequest(BaseModel):
    """Import a local folder as a new skill."""

    source_path: str = Field(min_length=1, max_length=1024, description="Local folder to copy in.")


class ModelUpsertRequest(BaseModel):
    """Create or update a model configuration."""

    name: str = Field(min_length=1, max_length=200, description="Model name.")
    provider: str = Field(
        default="openai-compatible",
        description=(
            "Provider protocol: openai-compatible / openai / anthropic / "
            "anthropic-compatible / gemini."
        ),
    )
    base_url: str = Field(default="", description="Provider base url.")
    api_key: str = Field(default="", description="Provider api key.")
    supports_tool_calls: bool = Field(default=True, description="Whether tools are enabled.")
    supports_image_input: bool = Field(
        default=False, description="Whether image input is supported."
    )
    thinking_mode: bool = Field(default=False, description="Whether thinking mode is enabled.")
    max_input_tokens: int = Field(default=0, ge=0, description="Input token limit, 0 means unset.")
    max_output_tokens: int = Field(
        default=0, ge=0, description="Output token limit, 0 means unset."
    )


class ModelUpdateRequest(BaseModel):
    """Partial update of a model configuration."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    supports_tool_calls: bool | None = None
    supports_image_input: bool | None = None
    thinking_mode: bool | None = None
    max_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)


class ModelItemResponse(BaseModel):
    """Model configuration item."""

    model_id: str
    name: str
    provider: str
    base_url: str = ""
    api_key: str = ""
    supports_tool_calls: bool = True
    supports_image_input: bool = False
    thinking_mode: bool = False
    max_input_tokens: int = 0
    max_output_tokens: int = 0
    created_at: datetime
    updated_at: datetime


class ModelListResponse(BaseModel):
    """Model list response."""

    models: list[ModelItemResponse]

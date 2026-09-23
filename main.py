"""NGY Agent CLI and Web Admin demo with ReAct task persistence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from uvicorn import run as uvicorn_run

from agent import skills as skill_library
from agent.agent_loop import DEFAULT_MAX_STEPS, DEFAULT_USER_QUERY, run_react_loop
from agent.models import (
    EventCategory,
    EventSink,
    TaskEvent,
    TaskStatus,
)
from agent.modes import (
    DEFAULT_MODE,
    MODE_CONFIGS,
    SKILLS,
    VALID_MODES,
    list_available_skills,
    list_available_tools,
)
from agent.provider import ProviderConfig, build_provider, canonicalize_provider
from agent.tools.permission_rules import PermissionRuleStore
from agent.tools.permissions import (
    SCOPES,
    PermissionBroker,
    PermissionMode,
    normalize_mode,
)
from mcp_api import router as mcp_router
from mcp_store import MCP_TRANSPORTS
from task_store import TASK_RETENTION_DEFAULT_DAYS, monitor_store

ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT_DIR / "web-admin"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
FRONTEND_DIST_INDEX = FRONTEND_DIST_DIR / "index.html"


def _resolve_frontend_dir() -> Path:
    if FRONTEND_DIST_INDEX.exists():
        return FRONTEND_DIST_DIR
    return FRONTEND_DIR


def _resolve_frontend_index() -> Path:
    frontend_dir = _resolve_frontend_dir()
    index_file = frontend_dir / "index.html"
    if not index_file.exists():
        raise FileNotFoundError("Neither web-admin/index.html nor web-admin/dist/index.html exists.")
    return index_file


_task_retention_days = TASK_RETENTION_DEFAULT_DAYS
_task_retention_source = "env"
_agent_max_steps = DEFAULT_MAX_STEPS
_agent_max_steps_source = "env"

_agent_permission_mode = PermissionMode.ASK
_agent_permission_mode_source = "env"

# Persisted "always allow" rules, shared by every task (ADR 0006 D8).
permission_rule_store = PermissionRuleStore()

_task_stop_events: Dict[str, threading.Event] = {}
_task_stop_lock = threading.Lock()

# Live permission brokers, one per running task, so the API can answer the
# questions they are blocked on. The broker lives exactly as long as the task's
# thread (see ADR 0006 D1).
_task_permission_brokers: Dict[str, PermissionBroker] = {}
_task_permission_lock = threading.Lock()


def _register_task_permission(task_id: str, broker: PermissionBroker) -> None:
    """Track a running task's broker so a decision can reach its waiting thread."""
    with _task_permission_lock:
        _task_permission_brokers[task_id] = broker


def _get_task_permission_broker(task_id: str) -> PermissionBroker | None:
    with _task_permission_lock:
        return _task_permission_brokers.get(task_id)


def _pending_permission(task_id: str) -> dict[str, Any] | None:
    """The confirmation this task is currently blocked on, if any."""
    broker = _get_task_permission_broker(task_id)
    if broker is None:
        return None
    pending = broker.pending()
    return pending.to_payload() if pending is not None else None


def _clear_task_permission(task_id: str) -> None:
    with _task_permission_lock:
        _task_permission_brokers.pop(task_id, None)


def _register_task_stop(task_id: str) -> threading.Event:
    """Register a cooperative stop flag for a running task."""
    event = threading.Event()
    with _task_stop_lock:
        _task_stop_events[task_id] = event
    return event


def _signal_task_stop(task_id: str) -> bool:
    """Request a running task to stop; returns whether it was registered."""
    with _task_stop_lock:
        event = _task_stop_events.get(task_id)
    if event is None:
        return False
    event.set()
    return True


def _clear_task_stop(task_id: str) -> None:
    with _task_stop_lock:
        _task_stop_events.pop(task_id, None)


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

    retention_days: int = Field(ge=0, description="Keep task detail data for this many days. 0 means keep all.")


class MaxStepsConfigRequest(BaseModel):
    """Global ReAct max steps config request."""

    max_steps: int = Field(ge=1, le=40, description="Global limit of ReAct steps applied to new tasks.")


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
    scope: str = Field(default="once", description="once / session / always, as offered by the tool")


class PermissionDecisionResponse(BaseModel):
    """Result of answering a permission request."""

    task_id: str
    request_id: str
    allowed: bool
    scope: str


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
        description="Provider protocol: openai-compatible / openai / anthropic / anthropic-compatible / gemini.",
    )
    base_url: str = Field(default="", description="Provider base url.")
    api_key: str = Field(default="", description="Provider api key.")
    supports_tool_calls: bool = Field(default=True, description="Whether tools are enabled.")
    supports_image_input: bool = Field(default=False, description="Whether image input is supported.")
    thinking_mode: bool = Field(default=False, description="Whether thinking mode is enabled.")
    max_input_tokens: int = Field(default=0, ge=0, description="Input token limit, 0 means unset.")
    max_output_tokens: int = Field(default=0, ge=0, description="Output token limit, 0 means unset.")


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


app = FastAPI(
    title="NGY Agent Web Admin",
    description="A lightweight ReAct task API plus management frontend for creating and tracking long-running tasks.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(mcp_router)


def _build_event(
    task_id: str,
    category: EventCategory,
    title: str,
    data: dict[str, Any],
    collapsed: bool = True,
) -> TaskEvent:
    return TaskEvent(
        task_id=task_id,
        category=category,
        title=title,
        data=data,
        collapsed=collapsed,
    )


def _emit_debug(event_sink: EventSink | None, task_id: str, title: str, data: dict[str, Any]) -> None:
    if event_sink is None:
        return
    event_sink(task_id, _build_event(task_id, EventCategory.DEBUG, title, data))


def _extract_task_result(events: list[dict[str, Any]] | None) -> str | None:
    """Get the latest task result from debug events."""
    if not events:
        return None

    for item in reversed(events):
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "")).strip().lower()
        if category != EventCategory.DEBUG.value:
            continue
        data = item.get("data")
        if not isinstance(data, dict):
            continue
        if "result" not in data:
            continue
        result = data.get("result")
        if result is None:
            continue
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False)
        except TypeError:
            return str(result)

    return None


def _build_provider_config(
    model: dict[str, Any] | None,
) -> ProviderConfig | None:
    if not model:
        return None
    return ProviderConfig(
        provider=canonicalize_provider(str(model.get("provider") or "openai-compatible")),
        model=str(model.get("name") or ""),
        api_key=str(model.get("api_key") or ""),
        base_url=(str(model.get("base_url")).strip() or None) if model.get("base_url") else None,
        max_input_tokens=int(model.get("max_input_tokens") or 0),
    )


_SESSION_TITLE_MAX_LENGTH = 60
_SESSION_TITLE_PROMPT = (
    "You generate a very short session title for a task list. "
    "Summarize the user's task into a concise title using the same language as the request. "
    "Reply with the title only, without quotes, and keep it under 20 characters when possible."
)


def _default_session_name() -> str:
    """Time-based session name used when the user does not provide one."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fallback_session_title(query: str) -> str:
    """Fallback title derived from the raw query when the LLM is unavailable."""
    collapsed = " ".join(str(query or "").split())
    if not collapsed:
        return _default_session_name()
    return collapsed[:_SESSION_TITLE_MAX_LENGTH]


def _summarize_session_title(
    provider_name: str,
    provider_config: ProviderConfig | None,
    query: str,
) -> str:
    """Ask the LLM for a short session title, falling back to the raw query."""
    try:
        provider = build_provider(provider_name, provider_config)
        response = provider.chat_completion(
            messages=[
                {"role": "system", "content": _SESSION_TITLE_PROMPT},
                {"role": "user", "content": str(query or "")},
            ]
        )
        message = response.choices[0].message
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    except Exception:  # noqa: BLE001 - a title is a convenience; fall back to the query
        return _fallback_session_title(query)

    title = str(content or "").strip().strip('"').strip("'").strip()
    if not title:
        return _fallback_session_title(query)
    return title[:_SESSION_TITLE_MAX_LENGTH]


def _update_session_title(
    session_id: str | None,
    provider_name: str,
    provider_config: ProviderConfig | None,
    query: str,
) -> None:
    """Rename a session with an LLM-generated title derived from the task query."""
    if not session_id:
        return
    title = _summarize_session_title(provider_name, provider_config, query)
    if title:
        monitor_store.rename_session(session_id, title)


def _get_global_max_steps() -> int:
    """Global ReAct step limit, loaded at startup and editable via the admin API."""
    return _agent_max_steps or DEFAULT_MAX_STEPS


def _resolve_max_steps(request: RunTaskRequest) -> int:
    """Resolve the step limit for one task: explicit override, else global config."""
    if request.max_steps is not None:
        return request.max_steps
    return _get_global_max_steps()


def _resolve_permission_mode(request: RunTaskRequest) -> PermissionMode:
    """Resolve the confirmation mode for one task: explicit override, else global."""
    if request.permission_mode:
        return normalize_mode(request.permission_mode)
    return _agent_permission_mode


def _resolve_session_base_dir(session_id: str | None) -> str | None:
    """Return the workspace root path bound to a session, if any."""
    if not session_id:
        return None
    session = monitor_store.get_session(session_id)
    workspace_id = (session or {}).get("workspace_id")
    if not workspace_id:
        return None
    workspace = monitor_store.get_workspace(workspace_id)
    root_path = str((workspace or {}).get("root_path") or "").strip()
    return root_path or None


def _agent_runtime_config(agent: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map a stored agent record to the runtime config consumed by the ReAct loop."""
    if not agent:
        return None
    return {
        "agent_id": agent.get("agent_id"),
        "name": agent.get("name"),
        "system_prompt": agent.get("system_prompt") or "",
        "tool_names": agent.get("tool_names"),
        "skills": agent.get("skill_names") or [],
        "mcp_servers": agent.get("mcp_servers") or [],
    }


def _resolve_skills_root() -> str:
    """Shared skills root folder: database setting, else env, else the repo ``skills`` folder."""
    stored = monitor_store.get_skills_root()
    if stored is not None and stored.strip():
        return stored.strip()
    env_root = os.getenv("SKILLS_ROOT", "").strip()
    if env_root:
        return env_root
    return str(ROOT_DIR / "skills")


def _run_task(
    task_id: str,
    request: RunTaskRequest,
    model: dict[str, Any] | None = None,
    base_dir: str | None = None,
    agent_config: dict[str, Any] | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    provider = str((model or {}).get("provider") or request.provider or "openai-compatible")
    provider_config = _build_provider_config(model)
    max_steps = _resolve_max_steps(request)

    def _sink(_: str, event: TaskEvent) -> None:
        monitor_store.append_event(task_id, event)
        # A task waiting on a confirmation is still in flight, but it must not look
        # like it is thinking - the UI shows "waiting for you" (ADR 0006 D10).
        if event.category is EventCategory.PERMISSION_REQUEST:
            monitor_store.set_task_status(task_id, TaskStatus.WAITING)
        elif event.category is EventCategory.PERMISSION_DECISION:
            monitor_store.set_task_status(task_id, TaskStatus.RUNNING)

    def _permission_event(category: str, title: str, data: dict[str, Any]) -> None:
        """Bridge the broker's audit events onto this task's event sink."""
        _sink(task_id, _build_event(task_id, EventCategory(category), title, data))

    _emit_debug(
        _sink,
        task_id,
        "Start task execution",
        {
            "provider": provider,
            "model": (model or {}).get("name"),
            "model_id": (model or {}).get("model_id"),
            "session_id": request.session_id,
            "base_dir": base_dir,
            "agent_id": (agent_config or {}).get("agent_id"),
            "max_steps": max_steps,
            "query": request.query,
            "mode": request.mode,
            "stream": request.stream,
            "supports_tool_calls": (model or {}).get("supports_tool_calls", True),
            "thinking_mode": (model or {}).get("thinking_mode", False),
            "max_output_tokens": (model or {}).get("max_output_tokens", 0),
        },
    )

    threading.Thread(
        target=_update_session_title,
        args=(request.session_id, provider, provider_config, request.query),
        daemon=True,
    ).start()

    try:
        permission_broker = PermissionBroker(
            task_id=task_id,
            emit=_permission_event,
            mode=_resolve_permission_mode(request),
            base_dir=base_dir,
            should_stop=stop_event.is_set if stop_event is not None else None,
            # One shared store, so the management API and every task agree on
            # which rules exist.
            rules=permission_rule_store,
        )
        _register_task_permission(task_id, permission_broker)
        result = run_react_loop(
            user_query=request.query,
            provider_name=provider,
            provider_config=provider_config,
            enable_tools=bool((model or {}).get("supports_tool_calls", True)),
            max_output_tokens=int((model or {}).get("max_output_tokens") or 0) or None,
            thinking_mode=bool((model or {}).get("thinking_mode", False)),
            max_steps=max_steps,
            verbose=False,
            task_id=task_id,
            event_sink=_sink,
            mode=request.mode,
            base_dir=base_dir,
            agent_config=agent_config,
            should_stop=stop_event.is_set if stop_event is not None else None,
            permission_broker=permission_broker,
        )
        if stop_event is not None and stop_event.is_set():
            _emit_debug(_sink, task_id, "Task stopped", {"result": result})
            monitor_store.finish_task(task_id, success=False, result=result, status=TaskStatus.STOPPED)
        else:
            _emit_debug(_sink, task_id, "Task finished", {"result": result})
            monitor_store.finish_task(task_id, success=True, result=result)
    except Exception as exc:  # noqa: BLE001 - a failed task must still be recorded as failed
        _emit_debug(
            _sink,
            task_id,
            "Task failed",
            {"error": str(exc), "type": exc.__class__.__name__},
        )
        monitor_store.finish_task(task_id, success=False)
    finally:
        active_broker = _get_task_permission_broker(task_id)
        if active_broker is not None:
            # Release anything still waiting, so no thread stays blocked until the
            # timeout after the run is already over.
            active_broker.cancel_all()
        _clear_task_permission(task_id)
        _clear_task_stop(task_id)


@app.get("/api/sessions", response_model=SessionListResponse)
async def list_sessions() -> SessionListResponse:
    sessions = monitor_store.list_sessions()
    items = []
    for item in sessions:
        tasks = monitor_store.list_tasks(session_id=item["session_id"])
        query_preview = " ".join(str(task.get("query", "")) for task in tasks)
        result_preview = " ".join(
            str(task.get("result", "")) for task in tasks if task.get("result")
        )
        items.append(
            SessionItemResponse(
                **item,
                query_preview=query_preview,
                result_preview=result_preview,
            )
        )
    return SessionListResponse(sessions=items)


@app.post("/api/sessions", response_model=SessionItemResponse)
async def create_session(payload: SessionCreateRequest) -> SessionItemResponse:
    name = (payload.name or "").strip() or _default_session_name()
    workspace_id = (payload.workspace_id or "").strip() or None
    if workspace_id and monitor_store.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    session_id = monitor_store.create_session(name, workspace_id)
    session = monitor_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=500, detail="Failed to read created session.")
    return SessionItemResponse(**session)


@app.put("/api/sessions/{session_id}", response_model=SessionItemResponse)
async def rename_session(session_id: str, payload: SessionUpdateRequest) -> SessionItemResponse:
    if not monitor_store.rename_session(session_id, payload.name.strip()):
        raise HTTPException(status_code=404, detail="Session not found.")
    session = monitor_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return SessionItemResponse(**session)


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    existing = monitor_store.list_sessions()
    if len(existing) <= 1:
        raise HTTPException(status_code=400, detail="At least one session must be kept.")
    if not monitor_store.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"session_id": session_id, "deleted": True}


@app.get("/api/workspaces", response_model=WorkspaceListResponse)
async def list_workspaces() -> WorkspaceListResponse:
    workspaces = monitor_store.list_workspaces()
    return WorkspaceListResponse(workspaces=[WorkspaceItemResponse(**item) for item in workspaces])


@app.post("/api/workspaces", response_model=WorkspaceItemResponse)
async def create_workspace(payload: WorkspaceCreateRequest) -> WorkspaceItemResponse:
    workspace_id = monitor_store.create_workspace(payload.name.strip(), payload.root_path.strip())
    workspace = monitor_store.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=500, detail="Failed to read created workspace.")
    return WorkspaceItemResponse(**workspace)


@app.put("/api/workspaces/{workspace_id}", response_model=WorkspaceItemResponse)
async def update_workspace(workspace_id: str, payload: WorkspaceUpdateRequest) -> WorkspaceItemResponse:
    name = payload.name.strip() if payload.name is not None else None
    root_path = payload.root_path.strip() if payload.root_path is not None else None
    updated = monitor_store.update_workspace(workspace_id, name=name, root_path=root_path)
    if updated is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return WorkspaceItemResponse(**updated)


@app.delete("/api/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str) -> dict[str, Any]:
    if not monitor_store.delete_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return {"workspace_id": workspace_id, "deleted": True}


@app.get("/api/models", response_model=ModelListResponse)
async def list_models() -> ModelListResponse:
    models = monitor_store.list_models()
    return ModelListResponse(models=[ModelItemResponse(**item) for item in models])


@app.post("/api/models", response_model=ModelItemResponse)
async def create_model(payload: ModelUpsertRequest) -> ModelItemResponse:
    created = monitor_store.create_model(payload.model_dump())
    return ModelItemResponse(**created)


@app.put("/api/models/{model_id}", response_model=ModelItemResponse)
async def update_model(model_id: str, payload: ModelUpdateRequest) -> ModelItemResponse:
    updated = monitor_store.update_model(model_id, payload.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    return ModelItemResponse(**updated)


@app.delete("/api/models/{model_id}")
async def delete_model(model_id: str) -> dict[str, Any]:
    if not monitor_store.delete_model(model_id):
        raise HTTPException(status_code=404, detail="Model not found.")
    return {"model_id": model_id, "deleted": True}


@app.post("/api/tasks", response_model=RunTaskResponse)
async def create_task(payload: RunTaskRequest) -> RunTaskResponse:
    _purge_expired_tasks_with_log("Creating new API task")
    agent_id = (payload.agent_id or "").strip() or (
        payload.mode if payload.mode in VALID_MODES else DEFAULT_MODE
    )
    agent = monitor_store.get_agent(agent_id)
    if agent is None:
        agent_id = payload.mode if payload.mode in VALID_MODES else DEFAULT_MODE
        agent = monitor_store.get_agent(agent_id)
    model = monitor_store.get_model(payload.model_id) if payload.model_id else None
    if payload.model_id and model is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    session_id = payload.session_id
    if session_id and monitor_store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if not session_id:
        session_id = monitor_store.ensure_default_session()

    provider = str((model or {}).get("provider") or payload.provider or "openai-compatible")
    task_id = monitor_store.create_task(
        query=payload.query,
        provider=provider,
        session_id=session_id,
        model_id=payload.model_id,
        mode=agent_id,
    )

    request = payload.model_copy(update={"session_id": session_id, "mode": agent_id})
    agent_config = _agent_runtime_config(agent)
    base_dir = _resolve_session_base_dir(session_id)
    stop_event = _register_task_stop(task_id)
    threading.Thread(
        target=_run_task,
        args=(task_id, request, model, base_dir, agent_config, stop_event),
        daemon=True,
    ).start()

    trace = monitor_store.get_task(task_id)
    if trace is None:
        raise HTTPException(status_code=500, detail="Failed to read created task record.")
    return RunTaskResponse(
        task_id=task_id,
        status=str(trace["status"]),
        mode=trace["mode"],
        created_at=trace["created_at"],
    )


@app.get("/api/modes")
async def list_modes() -> dict[str, Any]:
    """List available agent modes with their prompt/tool/skill configuration."""
    modes = []
    for name in VALID_MODES:
        config = MODE_CONFIGS[name]
        modes.append(
            {
                "mode": name,
                "label": config.get("label", name),
                "description": config.get("description", ""),
                "is_default": name == DEFAULT_MODE,
                "tool_names": config.get("tool_names"),
                "skills": [
                    {"name": skill, "label": SKILLS.get(skill, {}).get("label", skill)}
                    for skill in config.get("skills", [])
                    if skill in SKILLS
                ],
            }
        )
    return {"modes": modes, "default_mode": DEFAULT_MODE}


@app.get("/api/agents", response_model=AgentListResponse)
async def list_agents() -> AgentListResponse:
    agents = monitor_store.list_agents()
    return AgentListResponse(agents=[AgentItemResponse(**item) for item in agents])


@app.get("/api/agents/meta")
async def get_agent_meta() -> dict[str, Any]:
    """Available tools, skills and MCP transports used to build agents.

    ``skills`` are the built-in registry skills injected into the system prompt;
    ``library_skills`` are the folders of the shared skills root, listed in the
    agent editor for reference but not yet injected at runtime.
    """
    return {
        "tools": list_available_tools(),
        "skills": list_available_skills(),
        "library_skills": skill_library.list_skills(_resolve_skills_root()),
        "mcp_transports": list(MCP_TRANSPORTS),
    }


@app.post("/api/agents", response_model=AgentItemResponse)
async def create_agent(payload: AgentUpsertRequest) -> AgentItemResponse:
    created = monitor_store.create_agent(payload.model_dump())
    return AgentItemResponse(**created)


@app.put("/api/agents/{agent_id}", response_model=AgentItemResponse)
async def update_agent(agent_id: str, payload: AgentUpdateRequest) -> AgentItemResponse:
    updated = monitor_store.update_agent(agent_id, payload.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return AgentItemResponse(**updated)


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str) -> dict[str, Any]:
    agent = monitor_store.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    if agent.get("is_builtin"):
        raise HTTPException(status_code=400, detail="Built-in agents cannot be deleted.")
    if not monitor_store.delete_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found.")
    return {"agent_id": agent_id, "deleted": True}


@app.get("/api/skills")
async def list_skills() -> dict[str, Any]:
    """List skills stored under the shared root folder."""
    root = _resolve_skills_root()
    return {"skills_root": root, "skills": skill_library.list_skills(root)}


@app.get("/api/admin/skills-root")
async def get_skills_root() -> dict[str, Any]:
    stored = monitor_store.get_skills_root()
    return {
        "skills_root": _resolve_skills_root(),
        "skills_root_source": "database" if stored and stored.strip() else "env",
    }


@app.put("/api/admin/skills-root")
async def update_skills_root(payload: SkillsRootUpdateRequest) -> dict[str, Any]:
    monitor_store.set_skills_root(payload.skills_root.strip())
    return {"skills_root": _resolve_skills_root()}


@app.post("/api/skills/import")
async def import_skill(payload: SkillImportRequest) -> dict[str, Any]:
    root = _resolve_skills_root()
    try:
        return skill_library.import_skill(root, payload.source_path.strip())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/skills/{name}")
async def delete_skill(name: str) -> dict[str, Any]:
    if not skill_library.delete_skill(_resolve_skills_root(), name):
        raise HTTPException(status_code=404, detail="Skill not found.")
    return {"name": name, "deleted": True}


@app.get("/api/tasks", response_model=TaskListResponse)
async def list_tasks(
    session_id: str | None = Query(None, description="Only return tasks that belong to this session."),
) -> TaskListResponse:
    tasks = monitor_store.list_tasks(session_id=session_id)
    return TaskListResponse(
        tasks=[
            TaskListItemResponse(**{**item, "pending_permission": _pending_permission(item["task_id"])})
            for item in tasks
        ]
    )


@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str) -> dict[str, Any]:
    """Request a running task to stop; marks stale running tasks as stopped."""
    trace = monitor_store.get_task(task_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    stopped = _signal_task_stop(task_id)
    if not stopped and str(trace.get("status")) == TaskStatus.RUNNING.value:
        monitor_store.finish_task(task_id, success=False, status=TaskStatus.STOPPED)
        stopped = True
    return {"task_id": task_id, "stopped": stopped}


@app.post(
    "/api/tasks/{task_id}/permission/{request_id}",
    response_model=PermissionDecisionResponse,
)
async def answer_permission(
    task_id: str,
    request_id: str,
    payload: PermissionDecisionRequest,
) -> PermissionDecisionResponse:
    """Answer a pending confirmation, unblocking the task's waiting thread.

    This is the other half of the gate: the tool call is parked inside the task
    thread until this arrives, the deadline passes, or the task is stopped.
    """
    broker = _get_task_permission_broker(task_id)
    if broker is None:
        raise HTTPException(status_code=404, detail="Task not found or not running.")
    # Rejected rather than coerced: mapping an unknown scope onto "once" would
    # silently turn "always allow" into a one-off without telling anyone.
    if payload.scope not in SCOPES:
        raise HTTPException(
            status_code=400, detail=f"Unknown permission scope '{payload.scope}'."
        )
    # A tool may offer fewer answers than the global set (``write_stdin`` cannot take
    # a standing rule). Refuse the answer it does not accept rather than downgrading.
    offered = broker.request_scopes(request_id)
    if offered is not None and payload.scope not in offered:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This tool does not accept the '{payload.scope}' scope; "
                f"choose one of: {', '.join(offered)}."
            ),
        )
    if not broker.resolve(request_id, payload.allowed, payload.scope):
        raise HTTPException(status_code=409, detail="Permission request is no longer pending.")
    return PermissionDecisionResponse(
        task_id=task_id,
        request_id=request_id,
        allowed=payload.allowed,
        scope=payload.scope,
    )


@app.get("/api/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(task_id: str) -> TaskDetailResponse:
    trace = monitor_store.get_task(task_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    result = _extract_task_result(trace.get("events"))
    broker = _get_task_permission_broker(task_id)
    pending = broker.pending() if broker is not None else None
    return TaskDetailResponse(
        task_id=trace["task_id"],
        query=trace["query"],
        status=trace["status"],
        provider=trace["provider"],
        session_id=trace.get("session_id"),
        model_id=trace.get("model_id"),
        model_name=trace.get("model_name"),
        mode=trace.get("mode", DEFAULT_MODE),
        created_at=trace["created_at"],
        updated_at=trace["updated_at"],
        result=result,
        pending_permission=pending.to_payload() if pending is not None else None,
        events=trace["events"],
    )


async def _iter_task_events(task_id: str):
    seen = 0
    while True:
        task = monitor_store.get_task(task_id)
        if task is None:
            return
        events = monitor_store.get_events(task_id)

        while seen < len(events):
            yield events[seen]
            seen += 1

        # WAITING is still in flight: if the stream stopped here, the client would
        # never receive the confirmation request it is supposed to answer.
        if task["status"] not in (TaskStatus.RUNNING, TaskStatus.WAITING):
            return

        await asyncio.sleep(0.6)


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str) -> dict[str, Any]:
    removed = monitor_store.delete_task(task_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"task_id": task_id, "deleted": True}


@app.get("/api/tasks/{task_id}/events", response_model=EventPageResponse)
async def get_task_events(
    task_id: str,
    offset: int = Query(0, ge=0, description="Start position in the event list."),
    limit: int = Query(30, ge=1, le=100, description="Number of events to return, 1-100."),
    since: int | None = Query(None, ge=0, description="Start at this offset instead of the default offset."),
) -> EventPageResponse:
    if monitor_store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    real_offset = offset if since is None else max(0, since)
    items, total = monitor_store.list_events_paginated(
        task_id=task_id,
        offset=real_offset,
        limit=limit,
    )
    next_offset = real_offset + len(items)
    return EventPageResponse(
        items=items,
        offset=real_offset,
        limit=limit,
        next_offset=next_offset,
        total=total,
        has_more=next_offset < total,
    )


@app.get("/api/tasks/{task_id}/events/stream")
async def stream_task_events(task_id: str) -> StreamingResponse:
    if monitor_store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    async def _generator() -> Any:
        async for event in _iter_task_events(task_id):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(_generator(), media_type="text/event-stream")


@app.websocket("/api/tasks/{task_id}/events/ws")
async def stream_task_events_ws(
    websocket: WebSocket,
    task_id: str,
    since: str | None = None,
    heartbeat: int = 0,
) -> None:
    await websocket.accept()
    if monitor_store.get_task(task_id) is None:
        await websocket.close(code=1008, reason="Task not found.")
        return

    heartbeat_interval = max(0, heartbeat)
    heartbeat_at = asyncio.get_running_loop().time()
    last_event_id = since

    try:
        while True:
            events = monitor_store.get_events_since(task_id, since_event_id=last_event_id)
            if events:
                for event in events:
                    await websocket.send_text(json.dumps(event, default=str))
                    last_event_id = event.get("event_id")
                heartbeat_at = asyncio.get_running_loop().time()
                continue

            task = monitor_store.get_task(task_id)
            if task is None:
                await websocket.close(code=1008, reason="Task not found.")
                return

            if task["status"] not in (TaskStatus.RUNNING, TaskStatus.WAITING):
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "done",
                            "task_id": task_id,
                            "status": task["status"],
                        }
                    )
                )
                return

            now = asyncio.get_running_loop().time()
            if heartbeat_interval > 0 and now - heartbeat_at >= heartbeat_interval:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "heartbeat",
                            "task_id": task_id,
                            "ts": datetime.now(UTC).isoformat(),
                        }
                    )
                )
                heartbeat_at = now

            await asyncio.sleep(0.6)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001 - a streaming failure closes the socket, not the server
        await websocket.close(code=1011, reason="Internal server error while streaming task events.")
        return


def _serve_frontend_file(relative_path: str) -> FileResponse:
    frontend_dir = _resolve_frontend_dir()
    if relative_path and ".." in Path(relative_path).parts:
        raise HTTPException(status_code=400, detail="Invalid path")
    if relative_path:
        candidate = frontend_dir / relative_path
        if candidate.exists():
            if candidate.is_file():
                return FileResponse(candidate)
            raise HTTPException(status_code=404, detail="Static file does not exist")
    try:
        return FileResponse(_resolve_frontend_index())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Frontend index not found") from exc


def _load_agent_max_steps_config() -> tuple[int, str]:
    env_raw = os.getenv("REACT_MAX_STEPS", str(DEFAULT_MAX_STEPS)).strip()
    try:
        env_steps = int(env_raw)
    except ValueError:
        env_steps = DEFAULT_MAX_STEPS
    env_steps = max(1, min(env_steps, 1000))

    db_steps = monitor_store.get_agent_max_steps()
    if db_steps is None:
        return env_steps, "env"
    return max(1, min(db_steps, 1000)), "database"


def _load_permission_mode_config() -> tuple[PermissionMode, str]:
    env_mode = normalize_mode(os.getenv("PERMISSION_MODE", PermissionMode.ASK.value))
    db_mode = monitor_store.get_permission_mode()
    if not db_mode:
        return env_mode, "env"
    return normalize_mode(db_mode), "database"


def _load_env_file() -> None:
    root_env = ROOT_DIR / ".env"
    if root_env.exists():
        load_dotenv(root_env)


def _get_env_task_retention_days() -> int:
    raw = os.getenv("TASK_RETENTION_DAYS", str(TASK_RETENTION_DEFAULT_DAYS)).strip()
    try:
        days = int(raw)
    except ValueError:
        return TASK_RETENTION_DEFAULT_DAYS
    if days < 0:
        return 0
    return days


def _load_task_retention_config() -> tuple[int, str]:
    env_days = _get_env_task_retention_days()
    db_days = monitor_store.get_task_retention_days()
    if db_days is None:
        return env_days, "env"
    return db_days, "database"


def _get_task_retention_days() -> int:
    return _task_retention_days


def _purge_expired_tasks() -> int:
    return monitor_store.purge_expired_tasks(_get_task_retention_days())


def _purge_expired_tasks_with_log(scope: str) -> int:
    removed = _purge_expired_tasks()
    if removed > 0:
        retention_days = _get_task_retention_days()
        print(f"[Task cleanup] {scope}: TASK_RETENTION_DAYS={retention_days}, removed={removed} expired tasks.")
    return removed


@app.get("/api/admin/retention", response_model=RetentionConfigResponse)
async def get_retention_config() -> RetentionConfigResponse:
    return RetentionConfigResponse(
        retention_days=_task_retention_days,
        retention_source=_task_retention_source,
        removed_tasks=0,
    )


@app.put("/api/admin/retention", response_model=RetentionConfigResponse)
async def set_retention_config(
    payload: RetentionConfigRequest,
) -> RetentionConfigResponse:
    monitor_store.set_task_retention_days(payload.retention_days)
    global _task_retention_days
    global _task_retention_source
    _task_retention_days = max(0, payload.retention_days)
    _task_retention_source = "database"
    removed = _purge_expired_tasks_with_log("Retention config updated")
    return RetentionConfigResponse(
        retention_days=_task_retention_days,
        retention_source=_task_retention_source,
        removed_tasks=removed,
    )


@app.get("/api/admin/max-steps", response_model=MaxStepsConfigResponse)
async def get_max_steps_config() -> MaxStepsConfigResponse:
    return MaxStepsConfigResponse(
        max_steps=_agent_max_steps,
        source=_agent_max_steps_source,
    )


@app.put("/api/admin/max-steps", response_model=MaxStepsConfigResponse)
async def set_max_steps_config(
    payload: MaxStepsConfigRequest,
) -> MaxStepsConfigResponse:
    steps = max(1, min(payload.max_steps, 1000))
    monitor_store.set_agent_max_steps(steps)
    global _agent_max_steps
    global _agent_max_steps_source
    _agent_max_steps = steps
    _agent_max_steps_source = "database"
    return MaxStepsConfigResponse(
        max_steps=_agent_max_steps,
        source=_agent_max_steps_source,
    )


@app.get("/api/admin/permission-mode", response_model=PermissionModeConfigResponse)
async def get_permission_mode_config() -> PermissionModeConfigResponse:
    return PermissionModeConfigResponse(
        mode=_agent_permission_mode.value,
        source=_agent_permission_mode_source,
    )


@app.put("/api/admin/permission-mode", response_model=PermissionModeConfigResponse)
async def set_permission_mode_config(
    payload: PermissionModeConfigRequest,
) -> PermissionModeConfigResponse:
    try:
        mode = PermissionMode(payload.mode)
    except ValueError as exc:
        # Rejected rather than coerced: silently turning a typo into "ask" (or
        # worse, into "auto_approve") is not something an admin API should do.
        raise HTTPException(
            status_code=400,
            detail=f"Unknown permission mode '{payload.mode}'.",
        ) from exc
    monitor_store.set_permission_mode(mode.value)
    global _agent_permission_mode
    global _agent_permission_mode_source
    _agent_permission_mode = mode
    _agent_permission_mode_source = "database"
    return PermissionModeConfigResponse(
        mode=_agent_permission_mode.value,
        source=_agent_permission_mode_source,
    )


@app.get("/api/admin/permission-rules", response_model=PermissionRuleListResponse)
async def list_permission_rules() -> PermissionRuleListResponse:
    """Rules that answer "always allow" without asking again."""
    return PermissionRuleListResponse(
        rules=[PermissionRuleItem(**rule.to_payload()) for rule in permission_rule_store.list()],
        path=permission_rule_store.path.as_posix(),
    )


@app.post("/api/admin/permission-rules", response_model=PermissionRuleItem)
async def add_permission_rule(payload: PermissionRuleRequest) -> PermissionRuleItem:
    tool = payload.tool.strip()
    if not permission_rule_store.add(tool, payload.target):
        raise HTTPException(
            status_code=500, detail="Could not write the permission rule file."
        )
    for rule in permission_rule_store.list():
        if rule.tool == tool and rule.target == payload.target:
            return PermissionRuleItem(**rule.to_payload())
    raise HTTPException(status_code=500, detail="The permission rule was not persisted.")


@app.delete("/api/admin/permission-rules")
async def delete_permission_rule(
    tool: str = Query(min_length=1),
    target: str = Query(min_length=1),
) -> dict[str, Any]:
    # Query parameters rather than a body: DELETE bodies are dropped by some
    # proxies, and a silently dropped body would look like "rule not found".
    if not permission_rule_store.remove(tool, target):
        raise HTTPException(status_code=404, detail="No such permission rule.")
    return {"removed": True, "tool": tool, "target": target}


@app.get("/api/healthz")
async def healthz() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "ngy-py-agent-web-admin",
    }


@app.get("/", response_class=FileResponse, include_in_schema=False)
async def read_frontend() -> FileResponse:
    return _serve_frontend_file("index.html")


@app.get("/{full_path:path}", include_in_schema=False)
async def read_frontend_assets(full_path: str) -> FileResponse:
    if (
        full_path.startswith("api/")
        or full_path.startswith("docs")
        or full_path.startswith("redoc")
        or full_path == "openapi.json"
    ):
        raise HTTPException(status_code=404, detail="API path not found")
    if not full_path:
        raise HTTPException(status_code=404, detail="Path not found")
    return _serve_frontend_file(full_path)


def _resolve_query(cli_query: str | None) -> tuple[str, bool]:
    mode = os.getenv("NGY_PY_AGENT_MODE", "").strip().lower()
    if mode != "dev":
        return cli_query or DEFAULT_USER_QUERY, False

    query_from_env = os.getenv("NGY_PY_AGNET_QUERY", "").strip()
    if query_from_env:
        return query_from_env, True

    return cli_query or DEFAULT_USER_QUERY, False


def _run_web_server(host: str, port: int, reload: bool) -> None:
    try:
        _resolve_frontend_index()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Frontend entry missing: expected web-admin/index.html or web-admin/dist/index.html."
        ) from exc

    _purge_expired_tasks_with_log("Web admin startup")
    uvicorn_run("main:app", host=host, port=port, reload=reload, app_dir=str(ROOT_DIR))


def main() -> None:
    _load_env_file()
    global _task_retention_days
    global _task_retention_source
    _task_retention_days, _task_retention_source = _load_task_retention_config()
    global _agent_max_steps
    global _agent_max_steps_source
    _agent_max_steps, _agent_max_steps_source = _load_agent_max_steps_config()
    global _agent_permission_mode
    global _agent_permission_mode_source
    _agent_permission_mode, _agent_permission_mode_source = _load_permission_mode_config()
    parser = argparse.ArgumentParser(
        description="Run ReAct tasks with optional Web Admin mode.",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Input query content; use default query if omitted.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Force provider (openai-compatible / openai / anthropic / anthropic-compatible).",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=int(os.getenv("REACT_MAX_STEPS", "8")),
        help="Maximum number of ReAct steps.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only output the final answer.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Enable interactive multi-turn mode.",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="In interactive mode, print debug/agent reasoning and tool-call details.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Run Web Admin (API + frontend).",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("WEB_MONITOR_HOST", "127.0.0.1"),
        help="Web Admin host, default 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("WEB_MONITOR_PORT", "8001")),
        help="Web Admin port, default 8001.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable reload in Web Admin mode.",
    )
    args = parser.parse_args()

    if args.web:
        _run_web_server(host=args.host, port=args.port, reload=args.reload)
        return

    query, used_env_query = _resolve_query(args.query)
    if args.interactive and not used_env_query:
        print("Type your question, input exit/quit/q or Ctrl+C to leave.")
        interactive_verbose = (not args.quiet) and args.trace
        messages: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are a ReAct agent. Analyze first, call tools if needed, then output a clear and reproducible answer."
                ),
            }
        ]
        try:
            while True:
                user_input = input("you> ").strip()
                if not user_input:
                    continue
                if user_input.lower() in {"exit", "quit", "q"}:
                    break

                answer = run_react_loop(
                    user_query=user_input,
                    provider_name=args.provider,
                    max_steps=args.steps,
                    verbose=interactive_verbose,
                    initial_messages=messages,
                    base_dir=str(ROOT_DIR),
                )
                if not args.quiet:
                    print(f"assistant> {answer}")
        except KeyboardInterrupt:
            print("\nYou have exited interactive mode.")
        return

    run_react_loop(
        user_query=query,
        provider_name=args.provider,
        max_steps=args.steps,
        verbose=not args.quiet,
        base_dir=str(ROOT_DIR),
    )


if __name__ == "__main__":
    main()

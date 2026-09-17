"""NGY Agent CLI and Web Admin demo with ReAct task persistence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from uvicorn import run as uvicorn_run

from agent.agent_loop import DEFAULT_MAX_STEPS, DEFAULT_USER_QUERY, run_react_loop
from agent.models import (
    EventCategory,
    EventSink,
    TaskEvent,
    TaskStatus,
)
from agent.provider import ProviderConfig, canonicalize_provider
from task_store import TASK_RETENTION_DEFAULT_DAYS, monitor_store
from agent.modes import (
    DEFAULT_MODE,
    MODE_CONFIGS,
    SKILLS,
    VALID_MODES,
)

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
    mode: str = Field(
        default=DEFAULT_MODE,
        description="Agent mode: build / ask / plan. Each mode has its own prompt, tools and skills.",
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


class RetentionConfigResponse(BaseModel):
    """Retention config response."""

    retention_days: int
    retention_source: str
    removed_tasks: int


class SessionCreateRequest(BaseModel):
    """Create session request."""

    name: str = Field(min_length=1, max_length=120, description="Session name.")


class SessionUpdateRequest(BaseModel):
    """Rename session request."""

    name: str = Field(min_length=1, max_length=120, description="Session name.")


class SessionItemResponse(BaseModel):
    """Session list item."""

    session_id: str
    name: str
    created_at: datetime
    updated_at: datetime
    task_count: int = 0
    query_preview: str = ""
    result_preview: str = ""


class SessionListResponse(BaseModel):
    """Session list response."""

    sessions: list[SessionItemResponse]


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
    )


def _get_global_max_steps() -> int:
    """Global ReAct step limit, loaded at startup and editable via the admin API."""
    return _agent_max_steps or DEFAULT_MAX_STEPS


def _resolve_max_steps(request: RunTaskRequest) -> int:
    """Resolve the step limit for one task: explicit override, else global config."""
    if request.max_steps is not None:
        return request.max_steps
    return _get_global_max_steps()


def _run_task(
    task_id: str,
    request: RunTaskRequest,
    model: dict[str, Any] | None = None,
) -> None:
    provider = str((model or {}).get("provider") or request.provider or "openai-compatible")
    provider_config = _build_provider_config(model)
    max_steps = _resolve_max_steps(request)

    def _sink(_: str, event: TaskEvent) -> None:
        monitor_store.append_event(task_id, event)

    _emit_debug(
        _sink,
        task_id,
        "Start task execution",
        {
            "provider": provider,
            "model": (model or {}).get("name"),
            "model_id": (model or {}).get("model_id"),
            "session_id": request.session_id,
            "max_steps": max_steps,
            "query": request.query,
            "mode": request.mode,
            "stream": request.stream,
            "supports_tool_calls": (model or {}).get("supports_tool_calls", True),
            "thinking_mode": (model or {}).get("thinking_mode", False),
            "max_output_tokens": (model or {}).get("max_output_tokens", 0),
        },
    )

    try:
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
        )
        _emit_debug(_sink, task_id, "Task finished", {"result": result})
        monitor_store.finish_task(task_id, success=True, result=result)
    except Exception as exc:
        _emit_debug(
            _sink,
            task_id,
            "Task failed",
            {"error": str(exc), "type": exc.__class__.__name__},
        )
        monitor_store.finish_task(task_id, success=False)


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
    session_id = monitor_store.create_session(payload.name.strip())
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
    mode = payload.mode if payload.mode in VALID_MODES else DEFAULT_MODE
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
        mode=mode,
    )

    request = payload.model_copy(update={"session_id": session_id, "mode": mode})
    threading.Thread(target=_run_task, args=(task_id, request, model), daemon=True).start()

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


@app.get("/api/tasks", response_model=TaskListResponse)
async def list_tasks(
    session_id: str | None = Query(None, description="Only return tasks that belong to this session."),
) -> TaskListResponse:
    tasks = monitor_store.list_tasks(session_id=session_id)
    return TaskListResponse(tasks=[TaskListItemResponse(**item) for item in tasks])


@app.get("/api/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(task_id: str) -> TaskDetailResponse:
    trace = monitor_store.get_task(task_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    result = _extract_task_result(trace.get("events"))
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

        if task["status"] != TaskStatus.RUNNING:
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

            if task["status"] != TaskStatus.RUNNING:
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
    except Exception:
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
    )


if __name__ == "__main__":
    main()

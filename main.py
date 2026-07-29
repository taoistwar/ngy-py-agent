"""NGY Agent CLI and Web Admin demo with ReAct task persistence."""

from __future__ import annotations

import argparse
import sqlite3
import json
import os
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from uvicorn import run as uvicorn_run

from agent.agent_loop import DEFAULT_USER_QUERY, run_react_loop

try:
    from agent.models import (
        EventCategory,
        EventSink,
        TaskEvent,
        TaskStatus,
    )
except ModuleNotFoundError:
    from models import (
        EventCategory,
        EventSink,
        TaskEvent,
        TaskStatus,
    )


ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT_DIR / "web-admin"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
FRONTEND_DIST_INDEX = FRONTEND_DIST_DIR / "index.html"
TASK_DB_PATH = ROOT_DIR / "monitor_tasks.db"
TASK_RETENTION_DEFAULT_DAYS = 36600


def _resolve_frontend_dir() -> Path:
    if FRONTEND_DIST_INDEX.exists():
        return FRONTEND_DIST_DIR
    return FRONTEND_DIR


def _resolve_frontend_index() -> Path:
    frontend_dir = _resolve_frontend_dir()
    index_file = frontend_dir / "index.html"
    if not index_file.exists():
        raise FileNotFoundError(
            "Neither web-admin/index.html nor web-admin/dist/index.html exists."
        )
    return index_file


class _SqliteTaskStore:
    """SQLite-based task and event persistence."""

    def __init__(self, db_path: Path = TASK_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(value)

    @staticmethod
    def _event_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": row["event_id"],
            "task_id": row["task_id"],
            "timestamp": _SqliteTaskStore._parse_datetime(row["timestamp"]),
            "category": row["category"],
            "title": row["title"],
            "source": row["source"],
            "data": json.loads(row["data"] or "{}"),
            "collapsed": bool(row["collapsed"]),
        }

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    data TEXT NOT NULL,
                    collapsed INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_task_id_id ON events(task_id, id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at)"
            )
            self._conn.commit()

    def create_task(self, query: str, provider: str) -> str:
        task_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO tasks (task_id, query, provider, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, query, provider, TaskStatus.RUNNING, now, now),
            )
            self._conn.commit()
        return task_id

    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

    def get_task_retention_days(self) -> int | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            ("task_retention_days",),
        ).fetchone()
        if row is None:
            return None
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return None

    def set_task_retention_days(self, retention_days: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """
                ,
                ("task_retention_days", str(retention_days), now),
            )
            self._conn.commit()

    def purge_expired_tasks(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM tasks WHERE created_at < ?",
                (cutoff.isoformat(),),
            )
            self._conn.commit()
            return int(cursor.rowcount or 0)

    def set_provider(self, task_id: str, provider: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET provider = ?, updated_at = ? WHERE task_id = ?",
                (provider, datetime.now(timezone.utc).isoformat(), task_id),
            )
            self._conn.commit()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._conn.execute(
                """
                SELECT task_id, query, provider, status, created_at, updated_at
                FROM tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if task is None:
                return None

            events = self._conn.execute(
                """
                SELECT event_id, task_id, timestamp, category, title, source, data, collapsed
                FROM events
                WHERE task_id = ?
                ORDER BY id ASC
                """,
                (task_id,),
            ).fetchall()

            return {
                "task_id": task["task_id"],
                "query": task["query"],
                "provider": task["provider"],
                "status": task["status"],
                "created_at": self._parse_datetime(task["created_at"]),
                "updated_at": self._parse_datetime(task["updated_at"]),
                "events": [_SqliteTaskStore._event_to_dict(row) for row in events],
            }

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT t.task_id, t.query, t.status, t.provider, t.created_at, t.updated_at,
                       COUNT(e.event_id) AS event_count
                FROM tasks t
                LEFT JOIN events e ON t.task_id = e.task_id
                GROUP BY t.task_id, t.query, t.status, t.provider, t.created_at, t.updated_at
                ORDER BY t.created_at DESC
                """
            ).fetchall()
            return [
                {
                    "task_id": row["task_id"],
                    "query": row["query"],
                    "status": row["status"],
                    "provider": row["provider"],
                    "created_at": self._parse_datetime(row["created_at"]),
                    "updated_at": self._parse_datetime(row["updated_at"]),
                    "event_count": int(row["event_count"]),
                }
                for row in rows
            ]

    def get_events(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT event_id, task_id, timestamp, category, title, source, data, collapsed
                FROM events
                WHERE task_id = ?
                ORDER BY id ASC
                """,
                (task_id,),
            ).fetchall()
            return [_SqliteTaskStore._event_to_dict(row) for row in rows]

    def get_events_since(
        self,
        task_id: str,
        since_event_id: str | None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if not since_event_id:
                rows = self._conn.execute(
                    """
                    SELECT event_id, task_id, timestamp, category, title, source, data, collapsed
                    FROM events
                    WHERE task_id = ?
                    ORDER BY id ASC
                    """,
                    (task_id,),
                ).fetchall()
                return [_SqliteTaskStore._event_to_dict(row) for row in rows]

            row = self._conn.execute(
                "SELECT id FROM events WHERE task_id = ? AND event_id = ?",
                (task_id, since_event_id),
            ).fetchone()
            since_id = row["id"] if row else 0

            rows = self._conn.execute(
                """
                SELECT event_id, task_id, timestamp, category, title, source, data, collapsed
                FROM events
                WHERE task_id = ? AND id > ?
                ORDER BY id ASC
                """,
                (task_id, since_id),
            ).fetchall()
            return [_SqliteTaskStore._event_to_dict(row) for row in rows]

    def list_events_paginated(
        self,
        task_id: str,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            total_row = self._conn.execute(
                "SELECT COUNT(*) AS total FROM events WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if total_row is None:
                return [], 0
            total = int(total_row["total"])

            if offset < 0:
                offset = 0

            rows = self._conn.execute(
                """
                SELECT event_id, task_id, timestamp, category, title, source, data, collapsed
                FROM events
                WHERE task_id = ?
                ORDER BY id ASC
                LIMIT ? OFFSET ?
                """,
                (task_id, limit, offset),
            ).fetchall()

            start = offset
            if start >= total:
                return [], total

            return (
                [_SqliteTaskStore._event_to_dict(row) for row in rows],
                total,
            )

    def append_event(self, task_id: str, event: TaskEvent) -> None:
        with self._lock:
            task_exists = self._conn.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task_exists is None:
                return

            self._conn.execute(
                """
                INSERT INTO events (
                    event_id, task_id, timestamp, category, title, source, data, collapsed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.task_id,
                    event.timestamp.isoformat(),
                    event.category.value,
                    event.title,
                    event.source,
                    json.dumps(event.data, default=str, ensure_ascii=False),
                    int(event.collapsed),
                ),
            )
            self._conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
                (event.timestamp.isoformat(), task_id),
            )
            self._conn.commit()

    def finish_task(self, task_id: str, success: bool) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (
                    TaskStatus.SUCCESS if success else TaskStatus.FAILED,
                    datetime.now(timezone.utc).isoformat(),
                    task_id,
                ),
            )
            self._conn.commit()


monitor_store = _SqliteTaskStore()
_task_retention_days = TASK_RETENTION_DEFAULT_DAYS
_task_retention_source = "env"

class RunTaskRequest(BaseModel):
    """Create task request."""

    query: str = Field(min_length=1, description="User input")
    provider: str | None = None
    max_steps: int = Field(default=8, ge=1, le=40)
    stream: bool = False


class RunTaskResponse(BaseModel):
    """Create task response."""

    task_id: str
    status: str
    created_at: datetime


class TaskListItemResponse(BaseModel):
    """Task list item."""

    task_id: str
    query: str
    status: str
    provider: str
    created_at: datetime
    updated_at: datetime
    event_count: int


class TaskDetailResponse(BaseModel):
    """Task detail."""

    task_id: str
    query: str
    status: str
    provider: str
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


class RetentionConfigResponse(BaseModel):
    """Retention config response."""

    retention_days: int
    retention_source: str
    removed_tasks: int


app = FastAPI(
    title="NGY Agent Web Admin",
    description="A lightweight ReAct task API plus management frontend for creating and tracking long-running tasks."
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


def _run_task(task_id: str, request: RunTaskRequest) -> None:
    provider = request.provider or "openai-compatible"

    def _sink(_: str, event: TaskEvent) -> None:
        monitor_store.append_event(task_id, event)

    _emit_debug(
        _sink,
        task_id,
        "Start task execution",
        {
            "provider": provider,
            "max_steps": request.max_steps,
            "query": request.query,
            "stream": request.stream,
        },
    )

    try:
        result = run_react_loop(
            user_query=request.query,
            provider_name=provider,
            max_steps=request.max_steps,
            verbose=False,
            task_id=task_id,
            event_sink=_sink,
        )
        _emit_debug(_sink, task_id, "Task finished", {"result": result})
        monitor_store.finish_task(task_id, success=True)
    except Exception as exc:
        _emit_debug(
            _sink,
            task_id,
            "Task failed",
            {"error": str(exc), "type": exc.__class__.__name__},
        )
        monitor_store.finish_task(task_id, success=False)


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


@app.post("/api/tasks", response_model=RunTaskResponse)
async def create_task(payload: RunTaskRequest) -> RunTaskResponse:
    _purge_expired_tasks_with_log("Creating new API task")
    provider = payload.provider or "openai-compatible"
    task_id = monitor_store.create_task(query=payload.query, provider=provider)

    threading.Thread(target=_run_task, args=(task_id, payload), daemon=True).start()

    trace = monitor_store.get_task(task_id)
    if trace is None:
        raise HTTPException(status_code=500, detail="Failed to read created task record.")
    return RunTaskResponse(task_id=task_id, status=str(trace["status"]), created_at=trace["created_at"])


@app.get("/api/tasks", response_model=TaskListResponse)
async def list_tasks() -> TaskListResponse:
    tasks = monitor_store.list_tasks()
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
        created_at=trace["created_at"],
        updated_at=trace["updated_at"],
        result=result,
        events=trace["events"],
    )


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
    since: int | None = Query(None, ge=0, description="Start at this offset instead of the default offset.")
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
                            "ts": datetime.now(timezone.utc).isoformat(),
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
        print(
            f"[Task cleanup] {scope}: TASK_RETENTION_DAYS={retention_days}, removed={removed} expired tasks."
        )
    return removed


@app.get("/api/admin/retention", response_model=RetentionConfigResponse)
async def get_retention_config() -> RetentionConfigResponse:
    return RetentionConfigResponse(
        retention_days=_task_retention_days,
        retention_source=_task_retention_source,
        removed_tasks=0,
    )


@app.put("/api/admin/retention", response_model=RetentionConfigResponse)
async def set_retention_config(payload: RetentionConfigRequest) -> RetentionConfigResponse:
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

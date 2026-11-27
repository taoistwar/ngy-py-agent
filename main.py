"""NGY Agent Web Admin with ReAct task persistence.

This module is the app assembly and the service entry point: it mounts the route modules
on the FastAPI app, serves the built frontend, and starts the server. What it used to
carry lives next door now - ``api_schemas`` (request/response models),
``commons.state`` (the live state), ``agent.runtime`` (what a task is), and one module per
route group in ``routes/`` (``task_api``, ``workspace_api``, ``llm_api``, ``agent_api``,
``tool_api``, ``admin_api``, ``mcp_api``). A single 1700-line module is neither readable
nor safe to edit (``AGENTS.md``).
"""

from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from uvicorn import run as uvicorn_run

from agent.runtime import (
    purge_expired_tasks_with_log,
    start_scheduler,
    stop_scheduler,
)
from agent.telemetry import (
    active_provider,
    init_telemetry,
    is_telemetry_enabled,
    shutdown_telemetry,
)
from commons import state
from routes import (
    admin_api,
    agent_api,
    llm_api,
    memory_api,
    schedule_api,
    task_api,
    tool_api,
    workspace_api,
)
from routes.mcp_api import router as mcp_router
from task_recovery import resume_interrupted_tasks

ROOT_DIR = state.ROOT_DIR
FRONTEND_DIR = ROOT_DIR / "web-admin"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
FRONTEND_DIST_INDEX = FRONTEND_DIST_DIR / "index.html"

_app_instrumented = False

# Paths a trace must not wait on: the two event streams stay open for as long as the
# task runs, and the built frontend is megabytes of static files nobody debugs with
# traces. Everything else under the API is worth an HTTP span.
OTEL_EXCLUDED_URLS = (
    "/api/tasks/[^/]+/events/stream,"
    "/api/tasks/[^/]+/events/ws,"
    "/assets/.*,"
    "/monaco-editor/.*,"
    "/favicon.*"
)

def _load_runtime_config() -> None:
    """Resolve ``.env`` plus the database into ``commons.state`` for the serving process.

    This cannot live in :func:`main`: with ``--reload`` uvicorn imports this module in a
    child process that never runs ``main``, so the persisted settings were silently
    dropped back to their env/default values after every code change. Hooking the app's
    lifespan loads them wherever the app is actually served (the same trap
    ``_configure_telemetry`` documents below).
    """
    admin_api.load_env_file()
    admin_api.load_startup_config()


def _resume_interrupted_tasks() -> None:
    """Pick up the tasks a previous process left running.

    Startup is the only moment at which every stored "running" row is known to have
    no thread: the ones this process would start are not registered yet, and nothing
    else can be mid-run. A recovery failure is logged rather than raised - a task
    that cannot be continued must not stop the server from booting.
    """
    try:
        resume_interrupted_tasks()
    except Exception as exc:  # noqa: BLE001 - recovery is best effort by definition
        print(f"[Task recovery] startup scan failed: {exc.__class__.__name__}: {exc}")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _load_runtime_config()
    _resume_interrupted_tasks()
    # The clock lives with the process, not with a request: started once here and
    # stopped on the way out, so a reload never leaves two threads firing the same
    # schedule.
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(
    title="NGY Agent Web Admin",
    description="A lightweight ReAct task API plus management frontend for creating and tracking long-running tasks.",
    lifespan=_lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# Registration order matters: every router is mounted before the catch-all frontend
# route below, so an API path is never answered with index.html.
app.include_router(mcp_router)
app.include_router(workspace_api.router)
app.include_router(llm_api.router)
app.include_router(agent_api.router)
app.include_router(tool_api.router)
app.include_router(task_api.router)
app.include_router(schedule_api.router)
app.include_router(admin_api.router)
app.include_router(memory_api.router)


def _configure_telemetry() -> None:
    """Initialize tracing and hook the ASGI app; safe to call more than once.

    Called at import time as well as from :func:`main`: with ``--reload`` uvicorn
    imports this module in a child process and never runs ``main`` there, while the
    first process only sees ``.env`` once ``load_env_file`` has run. Both calls are
    cheap when tracing is off.
    """
    global _app_instrumented

    init_telemetry()
    if not is_telemetry_enabled() or _app_instrumented:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # The provider is passed explicitly: the app's HTTP spans must land in the
        # same exporter as the loop's, not in whichever provider won the global slot.
        FastAPIInstrumentor.instrument_app(
            app, excluded_urls=OTEL_EXCLUDED_URLS, tracer_provider=active_provider()
        )
    except Exception:  # noqa: BLE001 - tracing must never stop the server from booting
        return
    _app_instrumented = True


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


def _run_web_server(host: str, port: int, reload: bool) -> None:
    try:
        _resolve_frontend_index()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Frontend entry missing: expected web-admin/index.html or web-admin/dist/index.html."
        ) from exc

    purge_expired_tasks_with_log("Web admin startup")
    try:
        uvicorn_run("main:app", host=host, port=port, reload=reload, app_dir=str(ROOT_DIR))
    finally:
        # A batch processor holds the last few spans; shutdown is what flushes them.
        shutdown_telemetry()


def main() -> None:
    _load_runtime_config()
    _configure_telemetry()
    parser = argparse.ArgumentParser(
        description="Run the Web Admin server (API + frontend).",
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
        help="Restart the server when source files change.",
    )
    args = parser.parse_args()

    _run_web_server(host=args.host, port=args.port, reload=args.reload)


# Import-time setup serves ``uvicorn --reload``: the child process imports this
# module (with the parent's ``.env`` already in its environment) and never runs main.
_configure_telemetry()


if __name__ == "__main__":
    main()

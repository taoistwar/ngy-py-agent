"""NGY Agent CLI and Web Admin demo with ReAct task persistence.

This module is the app assembly and the CLI: it mounts the route modules on the FastAPI
app, serves the built frontend, and runs the ReAct loop from the command line. What it
used to carry lives next door now - ``api_schemas`` (request/response models),
``app_state`` (the live state), ``task_runtime`` (what a task is), and one module per
route group (``task_api``, ``workspace_api``, ``agent_api``, ``admin_api``). A single
1700-line module is neither readable nor safe to edit (``AGENTS.md``).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from uvicorn import run as uvicorn_run

import admin_api
import agent_api
import app_state
import task_api
import workspace_api
from agent.agent_loop import DEFAULT_USER_QUERY, run_react_loop
from mcp_api import router as mcp_router
from task_runtime import purge_expired_tasks_with_log

ROOT_DIR = app_state.ROOT_DIR
FRONTEND_DIR = ROOT_DIR / "web-admin"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
FRONTEND_DIST_INDEX = FRONTEND_DIST_DIR / "index.html"

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
# Registration order matters: every router is mounted before the catch-all frontend
# route below, so an API path is never answered with index.html.
app.include_router(mcp_router)
app.include_router(workspace_api.router)
app.include_router(agent_api.router)
app.include_router(task_api.router)
app.include_router(admin_api.router)


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

    purge_expired_tasks_with_log("Web admin startup")
    uvicorn_run("main:app", host=host, port=port, reload=reload, app_dir=str(ROOT_DIR))


def main() -> None:
    admin_api.load_env_file()
    admin_api.load_startup_config()
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

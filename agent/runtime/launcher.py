"""Starting one task: the resolution, the record and the thread every caller shares.

Two callers start tasks - the HTTP route and the scheduler - and both have to resolve
an agent, a model, a session and the conversation that came before in exactly the same
way. Keeping that here is what stops a scheduled run from quietly becoming a second,
slightly different task-creation path.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent.history import build_session_history
from agent.modes import DEFAULT_MODE, VALID_MODES
from agent.runtime.config import agent_runtime_config, resolve_session_base_dir
from agent.runtime.runner import run_task
from agent.telemetry import end_task_span, start_task_span
from commons import state
from commons.schemas import RunTaskRequest


class TaskLaunchError(Exception):
    """A request that cannot become a task, carrying the status a route should answer."""

    def __init__(self, detail: str, status_code: int = 404) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class LaunchedTask:
    """What a caller needs to answer with: the id and the record already stored."""

    task_id: str
    status: str
    mode: str
    created_at: datetime


def launch_task(
    *,
    query: str,
    session_id: str | None = None,
    model_id: str | None = None,
    provider: str | None = None,
    agent_id: str | None = None,
    mode: str = DEFAULT_MODE,
    stream: bool = True,
    permission_mode: str | None = None,
    max_steps: int | None = None,
) -> LaunchedTask:
    """Create the task row and start its thread; returns once the thread is running.

    Raises :class:`TaskLaunchError` before anything is created when the referenced
    model or session does not exist - the same order the route always used, so a
    broken reference fails the request instead of a task that has already started.
    """
    agent_key = (agent_id or "").strip() or (mode if mode in VALID_MODES else DEFAULT_MODE)
    agent = state.monitor_store.get_agent(agent_key)
    if agent is None:
        agent_key = mode if mode in VALID_MODES else DEFAULT_MODE
        agent = state.monitor_store.get_agent(agent_key)

    # A model names what to ask for; the provider record it points at says where and
    # how often (ADR 0014).
    model = state.monitor_store.llm.get_model(model_id) if model_id else None
    if model_id and model is None:
        raise TaskLaunchError("Model not found.")
    provider_record = (
        state.monitor_store.llm.get_provider(model["provider_id"])
        if model and model.get("provider_id")
        else None
    )

    if session_id and state.monitor_store.get_session(session_id) is None:
        raise TaskLaunchError("Session not found.")
    if not session_id:
        session_id = state.monitor_store.ensure_default_session()

    provider_name = str(
        (provider_record or {}).get("protocol")
        or (model or {}).get("protocol")
        or provider
        or "openai-compatible"
    )
    # Read the transcript before the task exists, so the task itself can never be
    # part of its own context. A task in the same session continues that conversation.
    history_messages = build_session_history(session_id)
    task_id = state.monitor_store.create_task(
        query=query,
        provider=provider_name,
        session_id=session_id,
        model_id=model_id,
        mode=agent_key,
    )

    request = RunTaskRequest(
        query=query,
        provider=provider,
        model_id=model_id,
        session_id=session_id,
        max_steps=max_steps,
        agent_id=agent_id,
        mode=agent_key,
        permission_mode=permission_mode,
        stream=stream,
    )
    agent_config = agent_runtime_config(agent)
    base_dir = resolve_session_base_dir(session_id)
    stop_event = state.register_task_stop(task_id)
    # Started on the calling thread so the task's spans join its trace. The worker
    # attaches it: ``contextvars`` do not cross ``threading.Thread``.
    otel_handle = start_task_span(
        task_id,
        {
            "task.mode": agent_key,
            "task.provider": provider_name,
            "task.model": (model or {}).get("name"),
        },
    )
    worker = threading.Thread(
        target=run_task,
        args=(task_id, request, model, provider_record, base_dir, agent_config, stop_event),
        kwargs={"otel_handle": otel_handle, "history_messages": history_messages},
        daemon=True,
    )
    try:
        worker.start()
    except Exception:
        # A thread that never ran would leave its span open for the process lifetime.
        end_task_span(otel_handle)
        raise

    trace: dict[str, Any] | None = state.monitor_store.get_task(task_id)
    if trace is None:
        raise TaskLaunchError("Failed to read created task record.", status_code=500)
    return LaunchedTask(
        task_id=task_id,
        status=str(trace["status"]),
        mode=str(trace["mode"]),
        created_at=trace["created_at"],
    )

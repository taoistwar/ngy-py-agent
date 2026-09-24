"""What a task is: the resolution helpers, the session-title writer, and the run itself.

This is the piece that turns a request into concrete things - which provider, which
workspace root, which step limit, which confirmation mode - and then runs the ReAct
loop under brokers the API can reach. ``task_api.py`` calls :func:`run_task` on a thread
and answers the request immediately.

It reads and writes the app's live state through :mod:`app_state`, never through
``main``: the routes import this module, so this module must not import them back.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, Optional

import app_state
from agent.agent_loop import DEFAULT_MAX_STEPS, run_react_loop
from agent.models import EventCategory, EventSink, TaskEvent, TaskStatus
from agent.provider import ProviderConfig, build_provider, canonicalize_provider
from agent.tools.permissions import PermissionBroker, PermissionMode, normalize_mode
from agent.tools.user_question import UserQuestionBroker
from api_schemas import RunTaskRequest

# ------------------------------------------------------------------ events


def build_event(
    task_id: str,
    category: EventCategory,
    title: str,
    data: dict[str, Any],
    collapsed: bool = True,
) -> TaskEvent:
    return TaskEvent(task_id=task_id, category=category, title=title, data=data, collapsed=collapsed)


def emit_debug(
    event_sink: EventSink | None, task_id: str, title: str, data: dict[str, Any]
) -> None:
    if event_sink is None:
        return
    event_sink(task_id, build_event(task_id, EventCategory.DEBUG, title, data))


def extract_task_result(events: list[dict[str, Any]] | None) -> str | None:
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


# ------------------------------------------------------------------ resolution


def build_provider_config(model: dict[str, Any] | None) -> Optional[ProviderConfig]:
    if not model:
        return None
    return ProviderConfig(
        provider=canonicalize_provider(str(model.get("provider") or "openai-compatible")),
        model=str(model.get("name") or ""),
        api_key=str(model.get("api_key") or ""),
        base_url=(str(model.get("base_url")).strip() or None) if model.get("base_url") else None,
        max_input_tokens=int(model.get("max_input_tokens") or 0),
    )


def global_max_steps() -> int:
    """Global ReAct step limit, loaded at startup and editable via the admin API."""
    return app_state.agent_max_steps or DEFAULT_MAX_STEPS


def resolve_max_steps(request: RunTaskRequest) -> int:
    """Resolve the step limit for one task: explicit override, else global config."""
    if request.max_steps is not None:
        return request.max_steps
    return global_max_steps()


def resolve_permission_mode(request: RunTaskRequest) -> PermissionMode:
    """Resolve the confirmation mode for one task: explicit override, else global."""
    if request.permission_mode:
        return normalize_mode(request.permission_mode)
    return app_state.permission_mode


def resolve_session_base_dir(session_id: str | None) -> str | None:
    """Return the workspace root path bound to a session, if any."""
    if not session_id:
        return None
    session = app_state.monitor_store.get_session(session_id)
    workspace_id = (session or {}).get("workspace_id")
    if not workspace_id:
        return None
    workspace = app_state.monitor_store.get_workspace(workspace_id)
    root_path = str((workspace or {}).get("root_path") or "").strip()
    return root_path or None


def agent_runtime_config(agent: dict[str, Any] | None) -> dict[str, Any] | None:
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


def resolve_skills_root() -> str:
    """Shared skills root folder: database setting, else env, else the repo ``skills`` folder."""
    stored = app_state.monitor_store.get_skills_root()
    if stored is not None and stored.strip():
        return stored.strip()
    env_root = os.getenv("SKILLS_ROOT", "").strip()
    if env_root:
        return env_root
    return str(app_state.ROOT_DIR / "skills")


# ------------------------------------------------------- session title (LLM)


_SESSION_TITLE_MAX_LENGTH = 60
_SESSION_TITLE_PROMPT = (
    "You generate a very short session title for a task list. "
    "Summarize the user's task into a concise title using the same language as the request. "
    "Reply with the title only, without quotes, and keep it under 20 characters when possible."
)


def default_session_name() -> str:
    """Time-based session name used when the user does not provide one."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fallback_session_title(query: str) -> str:
    """Fallback title derived from the raw query when the LLM is unavailable."""
    collapsed = " ".join(str(query or "").split())
    if not collapsed:
        return default_session_name()
    return collapsed[:_SESSION_TITLE_MAX_LENGTH]


def _summarize_session_title(
    provider_name: str,
    provider_config: Optional[ProviderConfig],
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
        content = (
            message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        )
    except Exception:  # noqa: BLE001 - a title is a convenience; fall back to the query
        return _fallback_session_title(query)

    title = str(content or "").strip().strip('"').strip("'").strip()
    if not title:
        return _fallback_session_title(query)
    return title[:_SESSION_TITLE_MAX_LENGTH]


def update_session_title(
    session_id: str | None,
    provider_name: str,
    provider_config: Optional[ProviderConfig],
    query: str,
) -> None:
    """Rename a session with an LLM-generated title derived from the task query."""
    if not session_id:
        return
    title = _summarize_session_title(provider_name, provider_config, query)
    if title:
        app_state.monitor_store.rename_session(session_id, title)


# ------------------------------------------------------------ retention purge


def purge_expired_tasks() -> int:
    """Drop task detail older than the configured retention window."""
    return app_state.monitor_store.purge_expired_tasks(app_state.task_retention_days)


def purge_expired_tasks_with_log(scope: str) -> int:
    removed = purge_expired_tasks()
    if removed > 0:
        print(
            f"[Task cleanup] {scope}: TASK_RETENTION_DAYS={app_state.task_retention_days}, "
            f"removed={removed} expired tasks."
        )
    return removed


# ---------------------------------------------------------------- the run


def run_task(
    task_id: str,
    request: RunTaskRequest,
    model: dict[str, Any] | None = None,
    base_dir: str | None = None,
    agent_config: dict[str, Any] | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    """Run one task to completion under its brokers; called on the task's own thread."""
    provider = str((model or {}).get("provider") or request.provider or "openai-compatible")
    provider_config = build_provider_config(model)
    max_steps = resolve_max_steps(request)

    def _sink(_: str, event: TaskEvent) -> None:
        app_state.monitor_store.append_event(task_id, event)
        status = app_state.status_for_event(event.category)
        if status is not None:
            app_state.monitor_store.set_task_status(task_id, status)

    def _broker_event(category: str, title: str, data: dict[str, Any]) -> None:
        """Bridge a broker's audit events onto this task's event sink.

        One bridge for both brokers: each emits the same ``(category, title, data)``
        shape and the category is what tells them apart, so a second copy of this
        would only be a second place for the two to drift.
        """
        _sink(task_id, build_event(task_id, EventCategory(category), title, data))

    emit_debug(
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
        target=update_session_title,
        args=(request.session_id, provider, provider_config, request.query),
        daemon=True,
    ).start()

    try:
        permission_broker = PermissionBroker(
            task_id=task_id,
            emit=_broker_event,
            mode=resolve_permission_mode(request),
            base_dir=base_dir,
            should_stop=stop_event.is_set if stop_event is not None else None,
            # One shared store, so the management API and every task agree on
            # which rules exist.
            rules=app_state.permission_rule_store,
        )
        # Its own broker, not the permission one: a question is not a gate, and the
        # two must not be able to answer for each other (ADR 0010 D1).
        question_broker = UserQuestionBroker(
            task_id=task_id,
            emit=_broker_event,
            should_stop=stop_event.is_set if stop_event is not None else None,
        )
        app_state.register_task_permission(task_id, permission_broker)
        app_state.register_task_questions(task_id, question_broker)
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
            user_question_broker=question_broker,
        )
        if stop_event is not None and stop_event.is_set():
            emit_debug(_sink, task_id, "Task stopped", {"result": result})
            app_state.monitor_store.finish_task(
                task_id, success=False, result=result, status=TaskStatus.STOPPED
            )
        else:
            emit_debug(_sink, task_id, "Task finished", {"result": result})
            app_state.monitor_store.finish_task(task_id, success=True, result=result)
    except Exception as exc:  # noqa: BLE001 - a failed task must still be recorded as failed
        emit_debug(
            _sink,
            task_id,
            "Task failed",
            {"error": str(exc), "type": exc.__class__.__name__},
        )
        app_state.monitor_store.finish_task(task_id, success=False)
    finally:
        active_broker = app_state.get_task_permission_broker(task_id)
        if active_broker is not None:
            # Release anything still waiting, so no thread stays blocked until the
            # timeout after the run is already over.
            active_broker.cancel_all()
        active_questions = app_state.get_task_question_broker(task_id)
        if active_questions is not None:
            active_questions.cancel_all()
        app_state.clear_task_permission(task_id)
        app_state.clear_task_questions(task_id)
        app_state.clear_task_stop(task_id)

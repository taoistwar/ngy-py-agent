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
from typing import Any, Callable, Optional

import app_state
from agent.agent_loop import DEFAULT_MAX_STEPS, run_react_loop
from agent.agents_md import AgentsMdSettings
from agent.checkpoints import CheckpointStore
from agent.models import EventCategory, EventSink, TaskEvent, TaskStatus
from agent.provider import ProviderConfig, build_provider, canonicalize_provider
from agent.telemetry import (
    TaskSpanHandle,
    attach_task_span,
    current_trace_ids,
    detach_task_span,
    end_task_span,
)
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


def build_provider_config(
    model: dict[str, Any] | None,
    provider: dict[str, Any] | None = None,
) -> Optional[ProviderConfig]:
    """Combine a model with the endpoint it runs on into one wire config.

    The model carries the name and the flags that describe it; the provider carries the
    protocol, the URL and the key (ADR 0014). Without a provider record the model is not
    buildable, but a caller that passes only a model keeps working through the adapter's
    own defaults.
    """
    if not model:
        return None
    protocol = str((provider or {}).get("protocol") or model.get("protocol") or "openai-compatible")
    base_url = str((provider or {}).get("base_url") or "").strip()
    return ProviderConfig(
        provider=canonicalize_provider(protocol),
        model=str(model.get("name") or ""),
        api_key=str((provider or {}).get("api_key") or ""),
        base_url=base_url or None,
        max_input_tokens=int(model.get("max_input_tokens") or 0),
        supports_image_input=bool(model.get("supports_image_input")),
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


def resolve_agents_md_settings() -> AgentsMdSettings:
    """AGENTS.md reading rules for one task: on/off and byte cap, already resolved."""
    return AgentsMdSettings(
        enabled=app_state.agents_md_enabled,
        max_bytes=app_state.agents_md_max_bytes,
    )


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


def checkpoint_store_for_task(trace: dict[str, Any] | None) -> CheckpointStore | None:
    """The undo history a stored task belongs to, or ``None`` when it has none.

    Resolved through the task's session: the session names the workspace, and the
    workspace is the directory the task actually wrote into. The task record itself
    only says which session it ran in (ADR 0020 D2).
    """
    if not trace:
        return None
    task_id = str(trace.get("task_id") or "").strip()
    if not task_id:
        return None
    return CheckpointStore.for_run(resolve_session_base_dir(trace.get("session_id")), task_id)


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


# ------------------------------------------------- task and session names (LLM)


_SESSION_TITLE_MAX_LENGTH = 60
_SESSION_TITLE_PROMPT = (
    "You generate a very short session title for a task list. "
    "Summarize the user's task into a concise title using the same language as the request. "
    "Reply with the title only, without quotes, and keep it under 20 characters when possible."
)

# The task list shows this name on one line, so it stays short.
_TASK_NAME_MAX_LENGTH = 20
_TASK_NAME_PROMPT = (
    "You name tasks for a task list. Summarize the user's task as a very short name "
    "in the same language as the request. Reply with the name only, without quotes, "
    "and keep it within 20 characters."
)


def default_session_name() -> str:
    """Time-based session name used when the user does not provide one."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _collapsed(query: str) -> str:
    """One-line form of the query: names are labels, not quotes."""
    return " ".join(str(query or "").split())


def _fallback_session_title(query: str) -> str:
    """Fallback title derived from the raw query when the LLM is unavailable."""
    collapsed = _collapsed(query)
    if not collapsed:
        return default_session_name()
    return collapsed[:_SESSION_TITLE_MAX_LENGTH]


def _fallback_task_name(query: str) -> str:
    """Task name used when the LLM is unavailable."""
    return _collapsed(query)[:_TASK_NAME_MAX_LENGTH]


def _summarize(
    prompt: str,
    max_length: int,
    provider_name: str,
    provider_config: Optional[ProviderConfig],
    query: str,
    fallback: Callable[[str], str],
) -> str:
    """Ask the LLM for a short label, falling back to a query-derived one."""
    try:
        provider = build_provider(provider_name, provider_config)
        response = provider.chat_completion(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": str(query or "")},
            ]
        )
        message = response.choices[0].message
        content = (
            message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        )
    except Exception:  # noqa: BLE001 - a label is a convenience; fall back to the query
        return fallback(query)

    label = str(content or "").strip().strip('"').strip("'").strip()
    if not label:
        return fallback(query)
    return label[:max_length]


def _summarize_session_title(
    provider_name: str,
    provider_config: Optional[ProviderConfig],
    query: str,
) -> str:
    """Ask the LLM for a short session title, falling back to the raw query."""
    return _summarize(
        _SESSION_TITLE_PROMPT,
        _SESSION_TITLE_MAX_LENGTH,
        provider_name,
        provider_config,
        query,
        _fallback_session_title,
    )


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


def update_task_name(
    task_id: str,
    provider_name: str,
    provider_config: Optional[ProviderConfig],
    query: str,
) -> None:
    """Name a task the way the list shows it.

    A query that already fits in the name length is its own name - asking the model
    to shorten three words can only lose them - so the model is only used when the
    query is longer than the name may be.
    """
    collapsed = _collapsed(query)
    if not collapsed:
        return
    if len(collapsed) <= _TASK_NAME_MAX_LENGTH:
        app_state.monitor_store.set_task_name(task_id, collapsed)
        return
    name = _summarize(
        _TASK_NAME_PROMPT,
        _TASK_NAME_MAX_LENGTH,
        provider_name,
        provider_config,
        query,
        _fallback_task_name,
    )
    app_state.monitor_store.set_task_name(task_id, name)


def is_first_task_in_session(session_id: str | None) -> bool:
    """Whether the task being named is the one that opened its session.

    The current task is already stored when this runs, so a session holding only
    that task is a session started by it.
    """
    if not session_id:
        return True
    session = app_state.monitor_store.get_session(session_id)
    if session is None:
        return True
    return int(session.get("task_count") or 0) <= 1


def name_task_and_session(
    task_id: str,
    session_id: str | None,
    provider_name: str,
    provider_config: Optional[ProviderConfig],
    query: str,
) -> None:
    """Both naming steps in one background thread.

    Each one calls the model, so running them one after the other keeps a local
    model from being asked twice at the same time while the task itself is running.

    Only the session's first task renames it: a follow-up continues the thread the
    earlier task opened, so it names itself and leaves the session label alone.
    """
    update_task_name(task_id, provider_name, provider_config, query)
    if is_first_task_in_session(session_id):
        update_session_title(session_id, provider_name, provider_config, query)


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
    provider: dict[str, Any] | None = None,
    base_dir: str | None = None,
    agent_config: dict[str, Any] | None = None,
    stop_event: threading.Event | None = None,
    otel_handle: TaskSpanHandle | None = None,
    history_messages: list[dict[str, Any]] | None = None,
    resume_messages: list[dict[str, Any]] | None = None,
    resume_step: int = 1,
) -> None:
    """Run one task to completion under its brokers; called on the task's own thread.

    ``model`` and ``provider`` are the two stored records the request resolved to: the
    model names what to ask for, the provider says where and how (ADR 0014).

    ``otel_handle`` is started by the caller on the request thread, which is what
    makes the task a child of its HTTP span; ``contextvars`` do not cross
    ``threading.Thread``, so the handle is attached here and the span ended here,
    after the closing event, so the event can still name it.

    ``history_messages`` is the conversation the session had before this task, read
    by the caller so this thread never guesses at it (see ``session_history``).

    ``resume_messages`` is the conversation a previous process rebuilt from the
    event log after a crash (see ``task_recovery``). When it is given, that transcript
    replaces both the system prompt and the history: it is the exact list the last
    request sent, and ``resume_step`` is the step that request belonged to.
    """
    token = attach_task_span(otel_handle)
    try:
        _execute_task(
            task_id,
            request,
            model,
            provider,
            base_dir,
            agent_config,
            stop_event,
            history_messages=history_messages,
            resume_messages=resume_messages,
            resume_step=resume_step,
        )
    finally:
        detach_task_span(token)
        end_task_span(otel_handle)


def _execute_task(
    task_id: str,
    request: RunTaskRequest,
    model: dict[str, Any] | None,
    provider_record: dict[str, Any] | None,
    base_dir: str | None,
    agent_config: dict[str, Any] | None,
    stop_event: threading.Event | None,
    history_messages: list[dict[str, Any]] | None = None,
    resume_messages: list[dict[str, Any]] | None = None,
    resume_step: int = 1,
) -> None:
    provider = str(
        (provider_record or {}).get("protocol")
        or (model or {}).get("protocol")
        or request.provider
        or "openai-compatible"
    )
    provider_config = build_provider_config(model, provider_record)
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

    if resume_messages is not None:
        # The rebuilt transcript already carries the earlier conversation, so the
        # session history would insert it a second time. The task also already has
        # a name: asking a model to name it again is work with no reader.
        history_messages = None

    emit_debug(
        _sink,
        task_id,
        "Resume task execution" if resume_messages is not None else "Start task execution",
        {
            "provider": provider,
            "provider_id": (provider_record or {}).get("provider_id"),
            # Which endpoint the requests go to: provider plus base URL is the unit of
            # both identification and the RPM budget (ADR 0014).
            "base_url": (provider_record or {}).get("base_url") or "",
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
            # How much of the session's earlier conversation this task continues
            # from: zero means it started a fresh conversation.
            "history_messages": len(history_messages or []),
            # A resumed run says so in its own event: the log then reads as "the
            # process restarted here and continued from step N".
            "resumed": resume_messages is not None,
            "first_step": resume_step,
            "resume_messages": len(resume_messages or []),
            **current_trace_ids(),
        },
    )

    if resume_messages is None:
        threading.Thread(
            target=name_task_and_session,
            args=(task_id, request.session_id, provider, provider_config, request.query),
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
            history_messages=history_messages,
            initial_messages=resume_messages,
            # A rebuilt transcript already ends with this task's query, and its step
            # numbering continues the run that died.
            append_user_query=resume_messages is None,
            first_step=resume_step if resume_messages is not None else 1,
            provider_name=provider,
            provider_config=provider_config,
            enable_tools=bool((model or {}).get("supports_tool_calls", True)),
            max_output_tokens=int((model or {}).get("max_output_tokens") or 0) or None,
            thinking_mode=bool((model or {}).get("thinking_mode", False)),
            stream=bool(request.stream),
            max_steps=max_steps,
            verbose=False,
            task_id=task_id,
            event_sink=_sink,
            mode=request.mode,
            base_dir=base_dir,
            agent_config=agent_config,
            agents_md_settings=resolve_agents_md_settings(),
            should_stop=stop_event.is_set if stop_event is not None else None,
            permission_broker=permission_broker,
            user_question_broker=question_broker,
        )
        if stop_event is not None and stop_event.is_set():
            emit_debug(_sink, task_id, "Task stopped", {"result": result, **current_trace_ids()})
            app_state.monitor_store.finish_task(
                task_id, success=False, result=result, status=TaskStatus.STOPPED
            )
        else:
            emit_debug(_sink, task_id, "Task finished", {"result": result, **current_trace_ids()})
            app_state.monitor_store.finish_task(task_id, success=True, result=result)
    except Exception as exc:  # noqa: BLE001 - a failed task must still be recorded as failed
        emit_debug(
            _sink,
            task_id,
            "Task failed",
            {"error": str(exc), "type": exc.__class__.__name__, **current_trace_ids()},
        )
        # An error raised after the user stopped the task is a consequence of the
        # stop (the request in flight was abandoned): the row stays stopped.
        stopped = stop_event is not None and stop_event.is_set()
        app_state.monitor_store.finish_task(
            task_id,
            success=False,
            status=TaskStatus.STOPPED if stopped else None,
        )
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

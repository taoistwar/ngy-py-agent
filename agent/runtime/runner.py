"""Running one task: the brokers the API can reach, the loop, and the record left behind."""

from __future__ import annotations

import threading
from typing import Any

from agent.agent_loop import run_react_loop
from agent.models import EventCategory, EventSink, TaskEvent, TaskStatus
from agent.runtime.board import board_for_run
from agent.runtime.config import (
    build_provider_config,
    resolve_agents_md_settings,
    resolve_max_steps,
    resolve_permission_mode,
)
from agent.runtime.events import build_event, emit_debug
from agent.runtime.memories import memory_book_for_run
from agent.runtime.memory_extract import extract_after_task
from agent.runtime.naming import name_task_and_session
from agent.runtime.todos import MonitorTodoStore
from agent.telemetry import (
    TaskSpanHandle,
    attach_task_span,
    current_trace_ids,
    detach_task_span,
    end_task_span,
)
from agent.tools.permissions import PermissionBroker
from agent.tools.todo_store import TodoBoard
from agent.tools.user_question import UserQuestionBroker
from commons import state
from commons.schemas import RunTaskRequest


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
    by the caller so this thread never guesses at it (see ``agent.history``).

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


def _extract_memories_after_task(
    task_id: str,
    query: str,
    result: str,
    provider_name: str,
    provider_config: Any,
    sink: EventSink,
) -> None:
    """Keep what this task learned on a thread of its own (ADR 0035).

    Started after ``finish_task`` rather than before it: the answer is already complete,
    and nobody should wait on an extraction they did not ask for. A failure in here is
    invisible by design - memory is a convenience, and the task it came from is already
    recorded.
    """
    # Read defensively: this layer is also called from tests and embedders whose state
    # object predates the feature, and "no switches" has to mean "do not extract".
    if not (
        getattr(state, "memories_enabled", False)
        and getattr(state, "memories_auto_extract", False)
    ):
        return

    def _emit(title: str, data: dict[str, Any]) -> None:
        emit_debug(sink, task_id, title, data)

    threading.Thread(
        target=extract_after_task,
        args=(task_id, query, result, provider_name, provider_config),
        kwargs={"emit": _emit},
        daemon=True,
    ).start()


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
        state.monitor_store.append_event(task_id, event)
        status = state.status_for_event(event.category)
        if status is not None:
            state.monitor_store.set_task_status(task_id, status)

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

    # The answer this task produced, kept for the memory extractor. Set only on the
    # success path, so the extraction below cannot run for a failed or stopped task.
    learned = ""
    try:
        permission_broker = PermissionBroker(
            task_id=task_id,
            emit=_broker_event,
            mode=resolve_permission_mode(request),
            base_dir=base_dir,
            should_stop=stop_event.is_set if stop_event is not None else None,
            # One shared store, so the management API and every task agree on
            # which rules exist.
            rules=state.permission_rule_store,
        )
        # Its own broker, not the permission one: a question is not a gate, and the
        # two must not be able to answer for each other (ADR 0010 D1).
        question_broker = UserQuestionBroker(
            task_id=task_id,
            emit=_broker_event,
            should_stop=stop_event.is_set if stop_event is not None else None,
        )
        state.register_task_permission(task_id, permission_broker)
        state.register_task_questions(task_id, question_broker)
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
            # The conversation's plan, kept in the database so the next task in this
            # session continues it and the web admin can render it (``dao.todos``).
            # Built here because the session id is this layer's knowledge, not the
            # loop's: the tool only ever sees its own board.
            todo_board=TodoBoard(MonitorTodoStore(), request.session_id or "", task_id),
            # The project's task board: the workspace's, shared by every conversation
            # in it, with this conversation recorded as the claimant (``task_*``).
            task_board=board_for_run(request.session_id, task_id),
            # What earlier conversations learned: the index goes into the prompt and
            # ``memory_save`` / ``memory_search`` write and read through the same book.
            # Built here because the deployment's on/off switch lives in this layer.
            memory_book=memory_book_for_run(task_id),
        )
        if stop_event is not None and stop_event.is_set():
            emit_debug(_sink, task_id, "Task stopped", {"result": result, **current_trace_ids()})
            state.monitor_store.finish_task(
                task_id, success=False, result=result, status=TaskStatus.STOPPED
            )
        else:
            emit_debug(_sink, task_id, "Task finished", {"result": result, **current_trace_ids()})
            state.monitor_store.finish_task(task_id, success=True, result=result)
            learned = result
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
        state.monitor_store.finish_task(
            task_id,
            success=False,
            status=TaskStatus.STOPPED if stopped else None,
        )
    finally:
        active_broker = state.get_task_permission_broker(task_id)
        if active_broker is not None:
            # Release anything still waiting, so no thread stays blocked until the
            # timeout after the run is already over.
            active_broker.cancel_all()
        active_questions = state.get_task_question_broker(task_id)
        if active_questions is not None:
            active_questions.cancel_all()
        state.clear_task_permission(task_id)
        state.clear_task_questions(task_id)
        state.clear_task_stop(task_id)

    # After the cleanup and outside the try: memory is a convenience, and an extraction
    # that failed to start must not turn a finished task into a failed one (ADR 0035).
    if learned:
        _extract_memories_after_task(
            task_id, request.query, learned, provider, provider_config, _sink
        )

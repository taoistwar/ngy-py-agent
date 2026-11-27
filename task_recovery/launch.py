"""Find the tasks a previous process left running and start them again.

A task's thread dies with the process, but its row keeps saying ``running``: the
only writer of a final status is the thread itself. On startup this module is the
one that notices, asks :mod:`task_recovery.transcript` what the task had actually
done, and either continues it, settles it from the log, or marks it failed with
the reason it could not be picked up.

Every path here is idempotent: a task is claimed once per process, and a task that
keeps dying is retried a bounded number of times before it is given up on.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from agent import runtime
from agent.models import EventCategory, TaskEvent, TaskStatus
from commons import state
from commons.schemas import RunTaskRequest
from task_recovery.transcript import ResumeMode, ResumePlan, build_resume_plan

# How many restarts one task may be resumed through *without making progress*. A
# task that takes the process down on every attempt would otherwise be relaunched
# forever; one that moves forward on each attempt is doing exactly what it should,
# however many times the operator restarts the server.
DEFAULT_MAX_ATTEMPTS = 3
_MAX_ATTEMPTS_ENV = "TASK_RESUME_MAX_ATTEMPTS"

_RESUMED_TITLE = "Task resumed after restart"
# What counts as progress: the model answered, or a tool produced a recorded result.
_PROGRESS_CATEGORIES = ("llm_response", "tool_result")

# The sweep runs once per process. It can be reached twice (uvicorn reloads, a test
# that builds the app more than once), and a second thread for the same task is
# exactly the duplicate work this package exists to prevent.
_claimed: set[str] = set()
_claim_lock = threading.Lock()


def resume_interrupted_tasks(store: Any | None = None) -> list[str]:
    """Continue every task a previous process left unfinished.

    Returns the ids that were actually started, which is also what makes the call
    testable without inspecting threads.
    """
    target = store or state.monitor_store
    started: list[str] = []
    for task in target.list_unfinished_tasks():
        task_id = str(task.get("task_id") or "")
        if not task_id or not _claim(task_id):
            continue
        try:
            if _resume_one(task_id, target):
                started.append(task_id)
        except Exception as exc:  # noqa: BLE001 - one bad row must not stop the sweep
            _settle(
                task_id,
                target,
                TaskStatus.FAILED,
                title="Task recovery failed",
                reason=f"{exc.__class__.__name__}: {exc}",
            )
    if started:
        print(f"[Task recovery] resumed {len(started)} interrupted task(s): {', '.join(started)}")
    return started


# ------------------------------------------------------------------- per task


def _resume_one(task_id: str, store: Any) -> bool:
    """Resume, settle or abandon one task; ``True`` only when a thread was started."""
    trace = store.get_task(task_id)
    if trace is None:
        return False

    plan = build_resume_plan(
        trace.get("events"),
        str(trace.get("query") or ""),
        default_max_steps=runtime.global_max_steps(),
        provider=str(trace.get("provider") or ""),
    )
    if plan is None:
        _settle(
            task_id,
            store,
            TaskStatus.FAILED,
            title="Task recovery failed",
            reason="the event log does not describe a conversation that can be continued",
        )
        return False

    if plan.mode is ResumeMode.SETTLE:
        _record(task_id, store, "Task recovery settled", {**plan.to_payload()})
        _settle(
            task_id,
            store,
            plan.status or TaskStatus.SUCCESS,
            result=plan.result,
            title=None,
        )
        return False

    if _made_progress(trace.get("events")):
        # The previous resume moved the task forward before the process died again,
        # so the retry budget is for *stuck* tasks, not for a busy developer.
        store.reset_resume_count(task_id)
    attempts = store.increase_resume_count(task_id)
    if attempts > _max_attempts():
        _settle(
            task_id,
            store,
            TaskStatus.FAILED,
            title="Task recovery gave up",
            reason=f"the task was already resumed {attempts - 1} time(s)",
        )
        return False

    return _start(task_id, trace, plan, store, attempts)


def _start(
    task_id: str,
    trace: dict[str, Any],
    plan: ResumePlan,
    store: Any,
    attempts: int,
) -> bool:
    """Start the task's thread with the rebuilt conversation."""
    model, provider_record = _resolve_model(trace, store)
    if model is None and trace.get("model_id"):
        # The model the task was bound to is gone; guessing another one would run
        # the remaining steps against a different provider than the log describes.
        _settle(
            task_id,
            store,
            TaskStatus.FAILED,
            title="Task recovery failed",
            reason=f"model {trace.get('model_id')} no longer exists",
        )
        return False

    agent_id = str(trace.get("mode") or "build")
    request = RunTaskRequest(
        query=str(trace.get("query") or ""),
        provider=str(trace.get("provider") or "") or None,
        model_id=trace.get("model_id"),
        session_id=trace.get("session_id"),
        max_steps=plan.max_steps,
        agent_id=agent_id,
        stream=True,
    )
    agent_config = runtime.agent_runtime_config(store.get_agent(agent_id))
    base_dir = runtime.resolve_session_base_dir(trace.get("session_id"))

    _record(
        task_id,
        store,
        _RESUMED_TITLE,
        {
            **plan.to_payload(),
            "resume_count": attempts,
            "session_id": trace.get("session_id"),
            "model_id": trace.get("model_id"),
            "base_dir": base_dir,
        },
    )

    stop_event = state.register_task_stop(task_id)
    worker = threading.Thread(
        target=runtime.run_task,
        args=(task_id, request, model, provider_record, base_dir, agent_config, stop_event),
        kwargs={
            "resume_messages": plan.messages if plan.mode is ResumeMode.CONTINUE else None,
            "resume_step": plan.next_step,
        },
        daemon=True,
    )
    try:
        _spawn(worker)
    except Exception:
        state.clear_task_stop(task_id)
        raise
    return True


def _spawn(worker: threading.Thread) -> None:
    """Start one task's thread. A seam: tests run it inline to stay deterministic."""
    worker.start()


def _resolve_model(
    trace: dict[str, Any],
    store: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The stored model and the endpoint it runs on, as the original request resolved them."""
    model_id = trace.get("model_id")
    if not model_id:
        return None, None
    model = store.llm.get_model(model_id)
    if not model:
        return None, None
    provider_id = model.get("provider_id")
    provider_record = store.llm.get_provider(provider_id) if provider_id else None
    return model, provider_record


# ---------------------------------------------------------------------- settle


def _settle(
    task_id: str,
    store: Any,
    status: TaskStatus,
    title: str | None = None,
    reason: str = "",
    result: str = "",
) -> None:
    """Write the task's final state, with the reason as an event when there is one."""
    if title:
        _record(
            task_id,
            store,
            title,
            {"status": status.value, "reason": reason, **({"result": result} if result else {})},
            category=EventCategory.ERROR if status is TaskStatus.FAILED else EventCategory.DEBUG,
        )
    store.finish_task(
        task_id,
        success=status is TaskStatus.SUCCESS,
        result=result,
        status=None if status is TaskStatus.SUCCESS else status,
    )


def _record(
    task_id: str,
    store: Any,
    title: str,
    data: dict[str, Any],
    category: EventCategory = EventCategory.DEBUG,
) -> None:
    store.append_event(task_id, TaskEvent(task_id=task_id, category=category, title=title, data=data))


# ---------------------------------------------------------------------- helpers


def _made_progress(events: list[dict[str, Any]] | None) -> bool:
    """Whether the last resume got anywhere before the process died again.

    Measured from the log so it survives the restart: anything the model or a tool
    produced after the resume marker is progress, and a task that keeps producing it
    must not be counted as stuck.
    """
    ordered = list(events or [])
    marker = -1
    for index, event in enumerate(ordered):
        if str(event.get("title") or "") == _RESUMED_TITLE:
            marker = index
    if marker < 0:
        return False
    for event in ordered[marker + 1 :]:
        category = str(event.get("category") or "").strip().lower()
        if category in _PROGRESS_CATEGORIES:
            return True
    return False


def _claim(task_id: str) -> bool:
    """Mark one task as this process's to resume; ``False`` when it already is."""
    with _claim_lock:
        if task_id in _claimed:
            return False
        if state.is_task_active(task_id):
            # A live thread owns it: the row is running because it *is* running.
            return False
        _claimed.add(task_id)
        return True


def _max_attempts() -> int:
    raw = os.getenv(_MAX_ATTEMPTS_ENV, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS
    return max(value, 0)


__all__ = ["DEFAULT_MAX_ATTEMPTS", "resume_interrupted_tasks"]

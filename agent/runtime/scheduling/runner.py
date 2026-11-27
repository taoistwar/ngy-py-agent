"""Turning one due schedule into a session, a task, and a run record.

The order is the contract: **a session first, then a task**. A scheduled run is a
conversation of its own - the next fire must not continue the previous one's transcript
as if they were the same thread of work - and creating the session first is also what
gives the task a workspace to run in.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from agent.runtime.launcher import TaskLaunchError, launch_task
from commons import state
from dao.scheduled import RUN_FAILED, RUN_SKIPPED, RUN_STARTED, TRIGGER_CRON

# One fire at a time: the guard below ("is a previous run still in flight") and the
# session+task pair it protects have to be decided together.
_FIRE_LOCK = threading.Lock()


def fire_schedule(schedule: dict[str, Any], trigger: str = TRIGGER_CRON) -> dict[str, Any]:
    """Run one schedule now and record the attempt; never raises for a bad reference.

    A schedule that points at a deleted model must not stop the scheduler thread, and
    it must not disappear silently either: both cases land in the run history.
    """
    with _FIRE_LOCK:
        return _fire_locked(schedule, trigger)


def _fire_locked(schedule: dict[str, Any], trigger: str) -> dict[str, Any]:
    schedule_id = str(schedule["schedule_id"])
    store = state.monitor_store

    if store.has_active_schedule_run(schedule_id):
        return store.create_schedule_run(
            schedule_id,
            trigger,
            status=RUN_SKIPPED,
            error="The previous run is still in flight; this one was skipped.",
        )

    session_id = _create_session(schedule)
    try:
        launched = launch_task(
            query=str(schedule["prompt"]),
            session_id=session_id,
            model_id=schedule.get("model_id"),
            agent_id=schedule.get("agent_id"),
        )
    except TaskLaunchError as exc:
        return store.create_schedule_run(
            schedule_id,
            trigger,
            session_id=session_id,
            status=RUN_FAILED,
            error=exc.detail,
        )
    except Exception as exc:  # noqa: BLE001 - one broken schedule must not stop the clock
        return store.create_schedule_run(
            schedule_id,
            trigger,
            session_id=session_id,
            status=RUN_FAILED,
            error=f"{exc.__class__.__name__}: {exc}",
        )

    run = store.create_schedule_run(
        schedule_id,
        trigger,
        session_id=session_id,
        task_id=launched.task_id,
        status=RUN_STARTED,
    )
    if not schedule.get("recurring", True):
        # A one-shot schedule has done its job; pausing it keeps the record without
        # arranging a second run.
        store.update_schedule(schedule_id, enabled=False)
    return run


def _create_session(schedule: dict[str, Any]) -> str:
    """Open the conversation this run belongs to, in the schedule's workspace."""
    store = state.monitor_store
    workspace_id = schedule.get("workspace_id") or None
    # A workspace deleted since the schedule was written must not leave a dangling id
    # on the new session; the run simply happens without a workspace.
    if workspace_id and store.get_workspace(workspace_id) is None:
        workspace_id = None
    return store.create_session(_session_name(schedule), workspace_id)


def _session_name(schedule: dict[str, Any]) -> str:
    """A readable placeholder title.

    The naming thread renames the session from the task's answer anyway; this is what
    the sidebar shows until then, and what a run leaves behind when naming fails.
    """
    label = " ".join(str(schedule.get("name") or "").split())
    if not label:
        label = " ".join(str(schedule.get("prompt") or "").split())[:40]
    return f"{label or 'Scheduled run'} {datetime.now().strftime('%m-%d %H:%M')}"

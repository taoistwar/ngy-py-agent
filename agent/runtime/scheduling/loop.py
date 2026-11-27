"""The thread that watches the clock: which schedules are due, and fire them.

Two pieces of state make a fire happen exactly once per minute: ``last_fired`` in the
database (so a restart inside the same minute does not re-fire) and an atomic claim
before firing (so a second tick cannot slip in between the read and the write).
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from agent.runtime.scheduling.cron import CronError, cron_matches
from agent.runtime.scheduling.runner import fire_schedule
from commons import state

# Waiting is cheap and nothing here is latency sensitive: a minute-granularity
# schedule is never late by more than this, and an idle process wakes twice a second.
POLL_SECONDS = 2.0

_stop = threading.Event()
_thread: threading.Thread | None = None
_guard = threading.Lock()


def start_scheduler() -> bool:
    """Start the clock thread; returns whether it actually started one.

    Idempotent so a reloaded app cannot end up with two threads firing the same
    schedule - the database claim would save the task from running twice, but only
    after one of the two had already done the work.
    """
    global _thread
    with _guard:
        if _thread is not None and _thread.is_alive():
            return False
        _stop.clear()
        _thread = threading.Thread(target=_run, name="schedule-scheduler", daemon=True)
        _thread.start()
        return True


def stop_scheduler(timeout: float = 5.0) -> None:
    """Ask the thread to finish and wait for it, so shutdown leaves nothing running."""
    global _thread
    with _guard:
        thread = _thread
        _thread = None
        _stop.set()
    if thread is not None:
        thread.join(timeout=timeout)


def is_running() -> bool:
    thread = _thread
    return thread is not None and thread.is_alive()


def tick(now: datetime | None = None) -> list[dict[str, Any]]:
    """Fire every schedule due at ``now``; returns the run records it created.

    ``now`` is injectable so a test can ask "what happens at 09:00" without waiting
    for 09:00, and it is naive local time - the same clock the cron expression is
    written against.
    """
    moment = now or datetime.now()
    marker = moment.strftime("%Y-%m-%d %H:%M")
    fired: list[dict[str, Any]] = []

    for schedule in state.monitor_store.list_enabled_schedules():
        # A row the scheduler already handled this minute (another tick, or the same
        # minute after a restart) is not due again.
        if schedule.get("last_fired") == marker:
            continue
        try:
            due = cron_matches(schedule["cron"], moment)
        except CronError:
            # The write path refuses invalid expressions, so this is a hand-edited
            # row: skipping it keeps the other schedules firing.
            continue
        if not due:
            continue
        if not state.monitor_store.claim_schedule_fire(schedule["schedule_id"], marker):
            continue
        fired.append(fire_schedule(schedule))
    return fired


def _run() -> None:
    while not _stop.is_set():
        try:
            tick()
        except Exception as exc:  # noqa: BLE001 - the clock must survive one bad row
            print(f"[Scheduler] tick failed: {exc.__class__.__name__}: {exc}")
        _stop.wait(POLL_SECONDS)

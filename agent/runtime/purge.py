"""Retention: dropping task detail older than the configured window.

The sweep is periodic, not request-driven: a daemon thread runs it once when the app
starts and then every hour, so a busy API never pays for the check and an idle one
still drops expired rows. ``agent/runtime/purge.py`` is the only place that decides
when retention runs.
"""

from __future__ import annotations

import threading

from commons import state

# The window is measured in days, so hourly is frequent enough for "yesterday's task
# is gone" without a per-request check.
PURGE_INTERVAL_SECONDS = 60 * 60

_stop = threading.Event()
_thread: threading.Thread | None = None
_guard = threading.Lock()


def purge_expired_tasks() -> int:
    """Drop task detail older than the configured retention window."""
    return state.monitor_store.purge_expired_tasks(state.task_retention_days)


def purge_expired_tasks_with_log(scope: str) -> int:
    removed = purge_expired_tasks()
    if removed > 0:
        print(
            f"[Task cleanup] {scope}: retention_days={state.task_retention_days}, "
            f"removed={removed} expired tasks."
        )
    return removed


def start_retention_sweeper() -> bool:
    """Start the hourly sweep thread; returns whether it actually started one.

    Idempotent for the same reason as the schedule clock: a reloaded app must not end
    up with two threads purging the same rows.
    """
    global _thread
    with _guard:
        if _thread is not None and _thread.is_alive():
            return False
        _stop.clear()
        _thread = threading.Thread(target=_run, name="retention-sweeper", daemon=True)
        _thread.start()
        return True


def stop_retention_sweeper(timeout: float = 5.0) -> None:
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


def _run() -> None:
    while not _stop.is_set():
        try:
            purge_expired_tasks_with_log("Hourly retention sweep")
        except Exception as exc:  # noqa: BLE001 - one bad sweep must not kill the timer
            print(f"[Task cleanup] sweep failed: {exc.__class__.__name__}: {exc}")
        _stop.wait(PURGE_INTERVAL_SECONDS)

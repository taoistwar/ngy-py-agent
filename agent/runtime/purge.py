"""Retention: dropping task detail older than the configured window."""

from __future__ import annotations

from commons import state


def purge_expired_tasks() -> int:
    """Drop task detail older than the configured retention window."""
    return state.monitor_store.purge_expired_tasks(state.task_retention_days)


def purge_expired_tasks_with_log(scope: str) -> int:
    removed = purge_expired_tasks()
    if removed > 0:
        print(
            f"[Task cleanup] {scope}: TASK_RETENTION_DAYS={state.task_retention_days}, "
            f"removed={removed} expired tasks."
        )
    return removed

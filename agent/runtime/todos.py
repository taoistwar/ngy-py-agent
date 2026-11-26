"""The session's plan as the database keeps it, bound into the run's tools.

``agent.tools`` must not import ``commons``/``dao`` (ADR 0019), while this package is
allowed to read live state - so the store ``todo_write`` edits is injected here. It
is a thin adapter, not a second store: the SQL stays in :mod:`dao.todos`, and a test
that swaps ``commons.state.monitor_store`` reaches this adapter on its next call.
"""

from __future__ import annotations

from typing import Any, Dict, List

from commons import state


class MonitorTodoStore:
    """``TodoStore`` over this process's task store."""

    def load(self, session_id: str) -> List[Dict[str, Any]]:
        record = state.monitor_store.get_session_todos(session_id)
        if not record:
            return []
        return list(record.get("todos") or [])

    def save(self, session_id: str, todos: List[Dict[str, Any]], task_id: str) -> None:
        state.monitor_store.set_session_todos(session_id, todos, task_id)


__all__ = ["MonitorTodoStore"]

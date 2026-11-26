"""Where a session's plan lives, and the run-scoped view the tool edits.

The plan is **session** scoped, not task scoped: a follow-up task in the same
conversation continues the checklist the previous task left behind, and the web
admin keeps showing it after the task that wrote it finished.

Persistence is a contract rather than an implementation because ``agent.tools``
must not import ``commons``/``dao`` (ADR 0019): the layer allowed to read live state
injects a store (``agent.runtime.todos`` binds the database one), and a run with no
store bound keeps the plan in memory, which is what tests and library callers get.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol


class TodoStore(Protocol):
    """The persistence a session's plan needs: read it back, replace it whole."""

    def load(self, session_id: str) -> List[Dict[str, Any]]:
        """The session's current plan, oldest first; ``[]`` when there is none."""

    def save(self, session_id: str, todos: List[Dict[str, Any]], task_id: str) -> None:
        """Replace the session's plan with ``todos``."""


class MemoryTodoStore:
    """A store with no persistence: one process, one dictionary.

    The fallback for a run nobody bound a database to. The list still works inside
    the run (the model can plan), it just does not outlive the process.
    """

    def __init__(self) -> None:
        self._items: Dict[str, List[Dict[str, Any]]] = {}

    def load(self, session_id: str) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._items.get(session_id or "", [])]

    def save(self, session_id: str, todos: List[Dict[str, Any]], task_id: str) -> None:
        self._items[session_id or ""] = [dict(item) for item in todos]


class TodoBoard:
    """One session's plan as this run sees it.

    The tool package receives this instead of a store, so it never has to know what
    a session is keyed by or which task is writing; ``None`` is a valid configuration
    and degrades to an in-memory plan rather than to a tool that refuses to work.
    """

    def __init__(
        self,
        store: Optional[TodoStore] = None,
        session_id: str = "",
        task_id: str = "",
    ) -> None:
        # ``MemoryTodoStore`` rather than ``None``: a run without a database still
        # gets a working plan, it just is not shared with anything else.
        self.store: TodoStore = store if store is not None else MemoryTodoStore()
        self.session_id = session_id or ""
        self.task_id = task_id or ""

    def snapshot(self) -> List[Dict[str, Any]]:
        """The stored plan, without raising.

        Read once per run to put the plan in front of the model (see
        ``agent.agent_loop.todo_context``): a failing read must cost the run its
        memory of the plan, not the run itself.
        """
        try:
            items = self.store.load(self.session_id)
        # Deliberately broad: the store may be a caller-supplied object.
        except Exception:  # noqa: BLE001
            return []
        return [dict(item) for item in items if isinstance(item, dict)]

    def replace(self, todos: List[Dict[str, Any]]) -> None:
        """Replace the plan; a store that cannot write raises to the caller."""
        self.store.save(self.session_id, todos, self.task_id)

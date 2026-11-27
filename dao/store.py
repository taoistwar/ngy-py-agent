"""The store itself: one connection and one lock over the mixins that use them.

Each concern (schema, sessions, agents, settings, tasks) lives in its own module so a
reader only loads the part they need; the class below is what the rest of the app
constructs and shares.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from dao.agents import _AgentMixin
from dao.base import TASK_DB_PATH, _TaskStoreBase
from dao.board_tasks import _BoardTaskMixin
from dao.forks import _ForkMixin
from dao.llm import LlmStore
from dao.scheduled import _ScheduleMixin
from dao.schema import _SchemaMixin
from dao.sessions import _SessionMixin
from dao.settings import _SettingsMixin
from dao.tasks import _TaskMixin
from dao.todos import _TodoMixin


class _SqliteTaskStore(
    _TaskStoreBase,
    _SchemaMixin,
    _SessionMixin,
    _ForkMixin,
    _AgentMixin,
    _SettingsMixin,
    _BoardTaskMixin,
    _TaskMixin,
    _TodoMixin,
    _ScheduleMixin,
):
    """SQLite-based task and event persistence."""

    def __init__(self, db_path: Path = TASK_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self.llm = LlmStore(self._conn, self._lock)
        self._init_schema()

    def close(self) -> None:
        """Release the SQLite handle.

        The process keeps one store for its whole life, so this exists for tests
        that point the store at a temporary database and then want to delete the
        directory (Windows refuses to unlink an open file).
        """
        with self._lock:
            self._conn.close()

"""The store itself: one connection and one lock over the mixins that use them.

Each concern (schema, sessions, agents, settings, tasks) lives in its own module so a
reader only loads the part they need; the class below is what the rest of the app
constructs and shares.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from llm_store import LlmStore
from task_store.agents import _AgentMixin
from task_store.base import TASK_DB_PATH, _TaskStoreBase
from task_store.forks import _ForkMixin
from task_store.schema import _SchemaMixin
from task_store.sessions import _SessionMixin
from task_store.settings import _SettingsMixin
from task_store.tasks import _TaskMixin


class _SqliteTaskStore(
    _TaskStoreBase,
    _SchemaMixin,
    _SessionMixin,
    _ForkMixin,
    _AgentMixin,
    _SettingsMixin,
    _TaskMixin,
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

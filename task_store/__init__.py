"""SQLite persistence for tasks, sessions, events and global settings.

Provider endpoints and their models live in :mod:`llm_store`, which shares this module's
connection (and lock) through ``self.llm``: same file, one schema owner per concern.

The implementation is split by concern inside this package; the public surface stays
``task_store``: callers import ``_SqliteTaskStore`` and ``monitor_store`` from here.
"""

from task_store.base import ROOT_DIR, TASK_DB_PATH, TASK_RETENTION_DEFAULT_DAYS
from task_store.store import _SqliteTaskStore

monitor_store = _SqliteTaskStore()

__all__ = [
    "ROOT_DIR",
    "TASK_DB_PATH",
    "TASK_RETENTION_DEFAULT_DAYS",
    "_SqliteTaskStore",
    "monitor_store",
]

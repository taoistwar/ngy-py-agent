"""SQLite persistence: every table the web admin reads or writes lives in this package.

One module per concern: tasks, sessions, events, settings, the session-scoped plan
(:mod:`dao.todos`), the workspace's task board (:mod:`dao.board_tasks`) and scheduled
tasks with their runs (:mod:`dao.scheduled`) in :mod:`dao.store` (split across mixins),
provider endpoints and their models in :mod:`dao.llm` (which shares the connection and
lock through ``self.llm``), and MCP server presets in :mod:`dao.mcp`.
Same database file, one schema owner per concern.

The public surface is the store singleton: callers import ``_SqliteTaskStore`` and
``monitor_store`` from here, and nothing in this package imports the application layer.
"""

from dao.base import ROOT_DIR, TASK_DB_PATH, TASK_RETENTION_DEFAULT_DAYS
from dao.store import _SqliteTaskStore

monitor_store = _SqliteTaskStore()

__all__ = [
    "ROOT_DIR",
    "TASK_DB_PATH",
    "TASK_RETENTION_DEFAULT_DAYS",
    "_SqliteTaskStore",
    "monitor_store",
]

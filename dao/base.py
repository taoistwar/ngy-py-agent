"""What every part of the task store shares: constants, paths and row helpers.

The store is one SQLite file split across mixins by concern (see ``store.py``). They
all use the same connection and the same lock, and they all turn rows into the dicts
the API returns, so those two pieces live here instead of in one of the parts.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.models import TaskStatus

ROOT_DIR = Path(__file__).resolve().parents[1]
TASK_DB_PATH = ROOT_DIR / "monitor_tasks.db"
TASK_RETENTION_DEFAULT_DAYS = 36600

# Statuses the *user* settles, which a thread still unwinding must not overwrite:
# a stop click is the decision (ADR 0019 D6: the in-flight model request can outlive
# it) and a revert already put the files back (ADR 0020).
_USER_SETTLED_STATUSES = frozenset({TaskStatus.STOPPED.value, TaskStatus.REVERTED.value})


class _TaskStoreBase:
    """Row helpers shared by the store's mixins."""

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime:
        if not value:
            return datetime.now(UTC)
        return datetime.fromisoformat(value)

    @staticmethod
    def _event_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": row["event_id"],
            "task_id": row["task_id"],
            "timestamp": _TaskStoreBase._parse_datetime(row["timestamp"]),
            "category": row["category"],
            "title": row["title"],
            "source": row["source"],
            "data": json.loads(row["data"] or "{}"),
            "collapsed": bool(row["collapsed"]),
        }

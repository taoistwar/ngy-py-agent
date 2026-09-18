"""SQLite persistence for the MCP server marketplace.

An MCP server is a reusable connection preset (transport + command/URL) that
agents pick from when they are created or edited. The table lives in the same
database file as the task store but is managed by this module so the MCP
feature stays self-contained.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from task_store import TASK_DB_PATH

MCP_TRANSPORTS = ["stdio", "sse"]
DEFAULT_MCP_TRANSPORT = "stdio"


class _SqliteMcpServerStore:
    """CRUD store for MCP server presets."""

    def __init__(self, db_path: Path = TASK_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_servers (
                    mcp_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    transport TEXT NOT NULL DEFAULT 'stdio',
                    target TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime:
        if not value:
            return datetime.now(UTC)
        return datetime.fromisoformat(value)

    @staticmethod
    def _server_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "mcp_id": row["mcp_id"],
            "name": row["name"],
            "description": row["description"] or "",
            "transport": row["transport"] or DEFAULT_MCP_TRANSPORT,
            "target": row["target"] or "",
            "created_at": _SqliteMcpServerStore._parse_datetime(row["created_at"]),
            "updated_at": _SqliteMcpServerStore._parse_datetime(row["updated_at"]),
        }

    def list_servers(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM mcp_servers ORDER BY created_at ASC, rowid ASC"
            ).fetchall()
        return [_SqliteMcpServerStore._server_to_dict(row) for row in rows]

    def get_server(self, mcp_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM mcp_servers WHERE mcp_id = ?",
                (mcp_id,),
            ).fetchone()
        if row is None:
            return None
        return _SqliteMcpServerStore._server_to_dict(row)

    def create_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        mcp_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO mcp_servers (
                    mcp_id, name, description, transport, target, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mcp_id,
                    payload["name"],
                    payload.get("description") or "",
                    payload.get("transport") or DEFAULT_MCP_TRANSPORT,
                    payload.get("target") or "",
                    now,
                    now,
                ),
            )
            self._conn.commit()
        created = self.get_server(mcp_id)
        assert created is not None
        return created

    def update_server(self, mcp_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_server(mcp_id)
        if current is None:
            return None
        merged = {**current, **{key: value for key, value in payload.items() if value is not None}}
        with self._lock:
            self._conn.execute(
                """
                UPDATE mcp_servers
                SET name = ?, description = ?, transport = ?, target = ?, updated_at = ?
                WHERE mcp_id = ?
                """,
                (
                    merged["name"],
                    merged.get("description") or "",
                    merged.get("transport") or DEFAULT_MCP_TRANSPORT,
                    merged.get("target") or "",
                    datetime.now(UTC).isoformat(),
                    mcp_id,
                ),
            )
            self._conn.commit()
        return self.get_server(mcp_id)

    def delete_server(self, mcp_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM mcp_servers WHERE mcp_id = ?", (mcp_id,))
            self._conn.commit()
            return (cursor.rowcount or 0) > 0


mcp_store = _SqliteMcpServerStore()

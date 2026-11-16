"""Configured agents: the presets a task can run as."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


class _AgentMixin:
    """Agent configuration persistence."""

    @staticmethod
    def _load_json(raw: str | None, default: Any) -> Any:
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return default

    def _agent_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        raw_tools = row["tool_names"]
        tool_names = None if raw_tools is None else self._load_json(raw_tools, None)
        return {
            "agent_id": row["agent_id"],
            "name": row["name"],
            "icon": row["icon"] or "",
            "description": row["description"] or "",
            "system_prompt": row["system_prompt"] or "",
            "tool_names": tool_names,
            "skill_names": self._load_json(row["skill_names"], []) or [],
            "mcp_servers": self._load_json(row["mcp_servers"], []) or [],
            "is_builtin": bool(row["is_builtin"]),
            "created_at": self._parse_datetime(row["created_at"]),
            "updated_at": self._parse_datetime(row["updated_at"]),
        }

    def list_agents(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agents ORDER BY created_at ASC, rowid ASC"
            ).fetchall()
        return [self._agent_to_dict(row) for row in rows]

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        if row is None:
            return None
        return self._agent_to_dict(row)

    def create_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        tool_names = payload.get("tool_names")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO agents (
                    agent_id, name, icon, description, system_prompt,
                    tool_names, skill_names, mcp_servers, is_builtin,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    payload.get("name") or "",
                    payload.get("icon") or "",
                    payload.get("description") or "",
                    payload.get("system_prompt") or "",
                    json.dumps(list(tool_names)) if tool_names is not None else None,
                    json.dumps(list(payload.get("skill_names") or [])),
                    json.dumps(list(payload.get("mcp_servers") or [])),
                    0,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        created = self.get_agent(agent_id)
        assert created is not None
        return created

    def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_agent(agent_id)
        if current is None:
            return None
        merged = {**current, **payload}
        tool_names = merged.get("tool_names")
        with self._lock:
            self._conn.execute(
                """
                UPDATE agents
                SET name = ?, icon = ?, description = ?, system_prompt = ?,
                    tool_names = ?, skill_names = ?, mcp_servers = ?, updated_at = ?
                WHERE agent_id = ?
                """,
                (
                    merged.get("name") or "",
                    merged.get("icon") or "",
                    merged.get("description") or "",
                    merged.get("system_prompt") or "",
                    json.dumps(list(tool_names)) if tool_names is not None else None,
                    json.dumps(list(merged.get("skill_names") or [])),
                    json.dumps(list(merged.get("mcp_servers") or [])),
                    datetime.now(UTC).isoformat(),
                    agent_id,
                ),
            )
            self._conn.commit()
        return self.get_agent(agent_id)

    def delete_agent(self, agent_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

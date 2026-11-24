"""Global settings kept in the same database as the records they govern."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


class _SettingsMixin:
    """Key/value settings: retention, step limit, permission mode and friends."""

    def _get_setting(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()
        return None if row is None else str(row["value"])

    def _set_setting(self, key: str, value: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )
        self._conn.commit()

    def get_task_retention_days(self) -> int | None:
        value = self._get_setting("task_retention_days")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def set_task_retention_days(self, retention_days: int) -> None:
        self._set_setting("task_retention_days", str(retention_days))

    def get_agent_max_steps(self) -> int | None:
        value = self._get_setting("agent_max_steps")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def set_agent_max_steps(self, max_steps: int) -> None:
        self._set_setting("agent_max_steps", str(max_steps))

    def get_agents_md_config(self) -> dict[str, Any] | None:
        value = self._get_setting("agents_md_config")
        if value is None:
            return None
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def set_agents_md_config(self, enabled: bool, max_bytes: int) -> None:
        # One row for both fields: "where did this setting come from" then has exactly
        # one answer, which a pair of rows would not (ADR 0022 D9).
        payload = json.dumps({"enabled": bool(enabled), "max_bytes": int(max_bytes)})
        self._set_setting("agents_md_config", payload)

    def get_permission_mode(self) -> str | None:
        text = str(self._get_setting("permission_mode") or "").strip()
        return text or None

    def set_permission_mode(self, mode: str) -> None:
        self._set_setting("permission_mode", str(mode))

    def get_skills_root(self) -> str | None:
        value = self._get_setting("skills_root")
        return None if value is None else str(value)

    def set_skills_root(self, skills_root: str) -> None:
        self._set_setting("skills_root", skills_root)

    def get_web_search_config(self) -> dict[str, Any] | None:
        value = self._get_setting("web_search_config")
        if value is None:
            return None
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def set_web_search_config(self, provider: str, api_key: str, base_url: str) -> None:
        # One row for the whole backend: "which source is in force" then has one
        # answer, and switching provider cannot leave a stale key behind.
        payload = json.dumps(
            {
                "provider": str(provider),
                "api_key": str(api_key),
                "base_url": str(base_url),
            }
        )
        self._set_setting("web_search_config", payload)

"""SQLite persistence for provider endpoints and the models served by them.

A **provider** is one place a request can go: a wire protocol, a base URL, an API key
and the requests-per-minute budget of that endpoint. A **model** is one model name on
one provider, plus the flags that describe it (tool calls, image input, thinking, token
limits).

The split is what makes the rate limit sit on the endpoint instead of on the model
(ADR 0014): two models behind one provider share one quota, and one protocol pointed at
two URLs is two quotas. It also means a key or a URL is edited once, not once per model.

This store shares the task store's connection and lock rather than opening a second one:
both halves are the same SQLite file, and task queries join ``models`` for the display
name. ``task_store`` owns the connection; this module owns what the two tables mean.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agent.provider import canonicalize_provider

PROVIDERS_TABLE = """
CREATE TABLE IF NOT EXISTS providers (
    provider_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    protocol TEXT NOT NULL,
    base_url TEXT NOT NULL DEFAULT '',
    api_key TEXT NOT NULL DEFAULT '',
    rpm_limit INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

MODELS_TABLE = """
CREATE TABLE IF NOT EXISTS models (
    model_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    supports_tool_calls INTEGER NOT NULL DEFAULT 1,
    supports_image_input INTEGER NOT NULL DEFAULT 0,
    thinking_mode INTEGER NOT NULL DEFAULT 0,
    max_input_tokens INTEGER NOT NULL DEFAULT 0,
    max_output_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(value)


def _provider_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "provider_id": row["provider_id"],
        "name": row["name"],
        "protocol": row["protocol"],
        "base_url": row["base_url"] or "",
        "api_key": row["api_key"] or "",
        "rpm_limit": int(row["rpm_limit"] or 0),
        "model_count": int(row["model_count"]) if "model_count" in row.keys() else 0,
        "created_at": _parse_datetime(row["created_at"]),
        "updated_at": _parse_datetime(row["updated_at"]),
    }


def _model_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    keys = row.keys()
    return {
        "model_id": row["model_id"],
        "name": row["name"],
        "provider_id": row["provider_id"],
        # Denormalised on read: the model list shows where its requests go, and a
        # client should not have to join two endpoints to render one row.
        "provider_name": row["provider_name"] if "provider_name" in keys else "",
        "protocol": row["protocol"] if "protocol" in keys else "",
        "base_url": (row["base_url"] or "") if "base_url" in keys else "",
        "supports_tool_calls": bool(row["supports_tool_calls"]),
        "supports_image_input": bool(row["supports_image_input"]),
        "thinking_mode": bool(row["thinking_mode"]),
        "max_input_tokens": int(row["max_input_tokens"] or 0),
        "max_output_tokens": int(row["max_output_tokens"] or 0),
        "created_at": _parse_datetime(row["created_at"]),
        "updated_at": _parse_datetime(row["updated_at"]),
    }


class LlmStore:
    """Provider endpoints and their models, on the task store's connection."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock

    # ------------------------------------------------------------------ schema

    def ensure_schema(self) -> None:
        """Create both tables, upgrading a database that stored endpoints on models."""
        with self._lock:
            self._conn.execute(PROVIDERS_TABLE)
            existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(models)")}
            if existing and "provider_id" not in existing:
                self._migrate_endpoints_onto_providers()
            else:
                self._conn.execute(MODELS_TABLE)
            self._conn.commit()

    def _migrate_endpoints_onto_providers(self) -> None:
        """Split a legacy ``models`` table into providers + models.

        Models used to carry their own ``provider`` / ``base_url`` / ``api_key``. One
        provider row is created per distinct triple, which is exactly the new unit of
        the rate limit: rows that shared an endpoint now share a budget again instead
        of each getting their own.
        """
        rows = self._conn.execute("SELECT * FROM models ORDER BY created_at ASC").fetchall()
        now = datetime.now(UTC).isoformat()
        provider_ids: Dict[tuple[str, str, str], str] = {}
        for row in rows:
            triple = (
                canonicalize_provider(row["provider"]),
                row["base_url"] or "",
                row["api_key"] or "",
            )
            if triple in provider_ids:
                continue
            provider_id = str(uuid4())
            provider_ids[triple] = provider_id
            self._conn.execute(
                """
                INSERT INTO providers (
                    provider_id, name, protocol, base_url, api_key, rpm_limit,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    provider_id,
                    _legacy_provider_name(triple[0], triple[1]),
                    triple[0],
                    triple[1],
                    triple[2],
                    now,
                    now,
                ),
            )

        self._conn.execute("ALTER TABLE models RENAME TO models_legacy")
        self._conn.execute(MODELS_TABLE)
        for row in rows:
            triple = (
                canonicalize_provider(row["provider"]),
                row["base_url"] or "",
                row["api_key"] or "",
            )
            self._conn.execute(
                """
                INSERT INTO models (
                    model_id, name, provider_id, supports_tool_calls,
                    supports_image_input, thinking_mode, max_input_tokens,
                    max_output_tokens, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["model_id"],
                    row["name"],
                    provider_ids[triple],
                    int(bool(row["supports_tool_calls"])),
                    int(bool(row["supports_image_input"])),
                    int(bool(row["thinking_mode"])),
                    int(row["max_input_tokens"] or 0),
                    int(row["max_output_tokens"] or 0),
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        self._conn.execute("DROP TABLE models_legacy")
        if rows:
            print(
                f"[Provider migration] split {len(rows)} model(s) across "
                f"{len(provider_ids)} provider endpoint(s)."
            )

    # --------------------------------------------------------------- providers

    def create_provider(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO providers (
                    provider_id, name, protocol, base_url, api_key, rpm_limit,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider_id,
                    payload["name"],
                    canonicalize_provider(payload.get("protocol")),
                    payload.get("base_url") or "",
                    payload.get("api_key") or "",
                    int(payload.get("rpm_limit") or 0),
                    now,
                    now,
                ),
            )
            self._conn.commit()
        created = self.get_provider(provider_id)
        assert created is not None
        return created

    def list_providers(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT p.*, (
                    SELECT COUNT(*) FROM models m WHERE m.provider_id = p.provider_id
                ) AS model_count
                FROM providers p
                ORDER BY p.created_at ASC
                """
            ).fetchall()
        return [_provider_to_dict(row) for row in rows]

    def get_provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT p.*, (
                    SELECT COUNT(*) FROM models m WHERE m.provider_id = p.provider_id
                ) AS model_count
                FROM providers p
                WHERE p.provider_id = ?
                """,
                (provider_id,),
            ).fetchone()
        if row is None:
            return None
        return _provider_to_dict(row)

    def update_provider(
        self, provider_id: str, payload: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        current = self.get_provider(provider_id)
        if current is None:
            return None
        merged = {**current, **{key: value for key, value in payload.items() if value is not None}}
        with self._lock:
            self._conn.execute(
                """
                UPDATE providers
                SET name = ?, protocol = ?, base_url = ?, api_key = ?, rpm_limit = ?,
                    updated_at = ?
                WHERE provider_id = ?
                """,
                (
                    merged["name"],
                    canonicalize_provider(merged.get("protocol")),
                    merged.get("base_url") or "",
                    merged.get("api_key") or "",
                    int(merged.get("rpm_limit") or 0),
                    datetime.now(UTC).isoformat(),
                    provider_id,
                ),
            )
            self._conn.commit()
        return self.get_provider(provider_id)

    def delete_provider(self, provider_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM providers WHERE provider_id = ?", (provider_id,)
            )
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

    def model_count(self, provider_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS total FROM models WHERE provider_id = ?", (provider_id,)
            ).fetchone()
        return int(row["total"] if row is not None else 0)

    # ------------------------------------------------------------------ models

    def create_model(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        model_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO models (
                    model_id, name, provider_id, supports_tool_calls,
                    supports_image_input, thinking_mode, max_input_tokens,
                    max_output_tokens, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    payload["name"],
                    payload["provider_id"],
                    int(bool(payload.get("supports_tool_calls", True))),
                    int(bool(payload.get("supports_image_input", False))),
                    int(bool(payload.get("thinking_mode", False))),
                    int(payload.get("max_input_tokens") or 0),
                    int(payload.get("max_output_tokens") or 0),
                    now,
                    now,
                ),
            )
            self._conn.commit()
        created = self.get_model(model_id)
        assert created is not None
        return created

    def list_models(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT m.*, p.name AS provider_name, p.protocol AS protocol,
                       p.base_url AS base_url
                FROM models m
                LEFT JOIN providers p ON p.provider_id = m.provider_id
                ORDER BY m.created_at ASC
                """
            ).fetchall()
        return [_model_to_dict(row) for row in rows]

    def get_model(self, model_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT m.*, p.name AS provider_name, p.protocol AS protocol,
                       p.base_url AS base_url
                FROM models m
                LEFT JOIN providers p ON p.provider_id = m.provider_id
                WHERE m.model_id = ?
                """,
                (model_id,),
            ).fetchone()
        if row is None:
            return None
        return _model_to_dict(row)

    def update_model(
        self, model_id: str, payload: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        current = self.get_model(model_id)
        if current is None:
            return None
        merged = {**current, **{key: value for key, value in payload.items() if value is not None}}
        with self._lock:
            self._conn.execute(
                """
                UPDATE models
                SET name = ?, provider_id = ?, supports_tool_calls = ?,
                    supports_image_input = ?, thinking_mode = ?, max_input_tokens = ?,
                    max_output_tokens = ?, updated_at = ?
                WHERE model_id = ?
                """,
                (
                    merged["name"],
                    merged["provider_id"],
                    int(bool(merged.get("supports_tool_calls", True))),
                    int(bool(merged.get("supports_image_input", False))),
                    int(bool(merged.get("thinking_mode", False))),
                    int(merged.get("max_input_tokens") or 0),
                    int(merged.get("max_output_tokens") or 0),
                    datetime.now(UTC).isoformat(),
                    model_id,
                ),
            )
            self._conn.commit()
        return self.get_model(model_id)

    def delete_model(self, model_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM models WHERE model_id = ?", (model_id,))
            self._conn.commit()
            return (cursor.rowcount or 0) > 0


def _legacy_provider_name(protocol: str, base_url: str) -> str:
    """A readable name for a provider row created by the migration."""
    return f"{protocol} · {base_url}" if base_url else protocol

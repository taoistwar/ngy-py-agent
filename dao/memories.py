"""Cross-session memories: notes an earlier conversation kept on purpose.

Not to be confused with ``tasks``/``events`` (what happened) or ``session_todos`` (the
plan of one conversation). A memory is knowledge that outlives the conversation that
learned it: one row per note, keyed by a slug ``name`` that saving again replaces, so
correcting a note and writing it are the same call (ADR 0035).

The row keeps the ``type`` the model declared (``user`` / ``feedback`` / ``project`` /
``reference``) as plain text: a new kind is a prompt and UI change, not a migration, and
the tools validate the set before writing (``agent/tools/memory_notes.py``).
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import UTC, datetime
from typing import Any


class _MemoryMixin:
    """Memory persistence: one library for the whole installation."""

    def _memory_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "memory_id": row["memory_id"],
            "name": row["name"],
            "type": row["type"],
            "description": row["description"],
            "body": row["body"],
            "source_task_id": row["source_task_id"] or "",
            "created_at": self._parse_datetime(row["created_at"]),
            "updated_at": self._parse_datetime(row["updated_at"]),
        }

    def list_memories(self) -> list[dict[str, Any]]:
        """Every stored memory, by name.

        Ordered by name rather than by age: the prompt index is built from this list,
        and a stable order is what stops the same library from producing different
        system prompts for identical requests.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT memory_id, name, type, description, body, source_task_id, "
                "created_at, updated_at FROM memories ORDER BY name"
            ).fetchall()
        return [self._memory_to_dict(row) for row in rows]

    def count_memories(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS total FROM memories").fetchone()
        return int(row["total"] or 0) if row is not None else 0

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        if not memory_id:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT memory_id, name, type, description, body, source_task_id, "
                "created_at, updated_at FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return None if row is None else self._memory_to_dict(row)

    def get_memory_by_name(self, name: str) -> dict[str, Any] | None:
        if not name:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT memory_id, name, type, description, body, source_task_id, "
                "created_at, updated_at FROM memories WHERE name = ?",
                (name,),
            ).fetchone()
        return None if row is None else self._memory_to_dict(row)

    def upsert_memory(
        self,
        name: str,
        memory_type: str,
        description: str,
        body: str,
        source_task_id: str = "",
    ) -> dict[str, Any]:
        """Store one memory under ``name``, replacing what that name held.

        ``created_at`` survives a replacement on purpose: the note was learned then, and
        ``updated_at`` is what says when it was last corrected.
        """
        now = datetime.now(UTC).isoformat()
        memory_id = secrets.token_hex(8)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memories (
                    memory_id, name, type, description, body, source_task_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    type = excluded.type,
                    description = excluded.description,
                    body = excluded.body,
                    source_task_id = excluded.source_task_id,
                    updated_at = excluded.updated_at
                """,
                (memory_id, name, memory_type, description, body, source_task_id or "", now, now),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT memory_id, name, type, description, body, source_task_id, "
                "created_at, updated_at FROM memories WHERE name = ?",
                (name,),
            ).fetchone()
        # The insert above just wrote this row; a missing one would be a database fault,
        # not a state the caller can act on.
        if row is None:
            raise RuntimeError(f"memory {name!r} vanished right after it was written")
        return self._memory_to_dict(row)

    def update_memory(
        self,
        memory_id: str,
        *,
        name: str | None = None,
        memory_type: str | None = None,
        description: str | None = None,
        body: str | None = None,
    ) -> dict[str, Any] | None:
        """Change fields of one memory; ``None`` when the id does not exist.

        ``name`` is the key a later save replaces, so renaming has to be allowed here:
        otherwise a typo in a slug could only be fixed by deleting the note.
        """
        current = self.get_memory(memory_id)
        if current is None:
            return None
        with self._lock:
            self._conn.execute(
                """
                UPDATE memories SET name = ?, type = ?, description = ?, body = ?, updated_at = ?
                WHERE memory_id = ?
                """,
                (
                    name or current["name"],
                    memory_type or current["type"],
                    current["description"] if description is None else description,
                    current["body"] if body is None else body,
                    datetime.now(UTC).isoformat(),
                    memory_id,
                ),
            )
            self._conn.commit()
        return self.get_memory(memory_id)

    def delete_memory(self, memory_id: str) -> bool:
        if not memory_id:
            return False
        with self._lock:
            cursor = self._conn.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

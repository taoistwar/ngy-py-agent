"""Reasoning translations: a translated copy of one turn's trace, per language.

The events themselves stay untouched: the trace is what the model produced, and a
translation is a second rendering for the reader. Storing it beside the event instead
of inside its ``data`` keeps the original available for the side-by-side switch and
avoids rewriting a row the log is streaming (``dao/tasks.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Dict


class _TranslationMixin:
    """The translated copies of ``llm_response`` reasoning traces."""

    def save_reasoning_translation(
        self,
        event_id: str,
        locale: str,
        text: str,
        model_id: str = "",
    ) -> None:
        """Store (or replace) one trace's translation for one language."""
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO event_translations (event_id, locale, text, model_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id, locale) DO UPDATE SET
                    text = excluded.text,
                    model_id = excluded.model_id,
                    created_at = excluded.created_at
                """,
                (event_id, locale, text, model_id, now),
            )
            self._conn.commit()

    def list_reasoning_translations(self, task_id: str, locale: str) -> Dict[str, str]:
        """``event_id -> text`` for one task and one language; empty when none exist."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT t.event_id, t.text
                FROM event_translations t
                JOIN events e ON e.event_id = t.event_id
                WHERE e.task_id = ? AND t.locale = ?
                """,
                (task_id, locale),
            ).fetchall()
        return {str(row["event_id"]): str(row["text"]) for row in rows}

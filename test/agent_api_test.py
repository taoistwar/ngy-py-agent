"""Tests for the agent configuration endpoints and the agent ``icon`` field.

Run from the repository root::

    uv run python test/agent_api_test.py -v

The process-wide task store is swapped for a temporary one so the built-in agent
configurations (build / ask / plan) are seeded from scratch.
"""

import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402


class AgentApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._root = Path(self._tmp.name)
        self._previous_store = state.monitor_store
        self.store = _SqliteTaskStore(self._root / "tasks.db")
        state.monitor_store = self.store
        self.client = TestClient(main.app)

    def tearDown(self):
        state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    def create_agent(self, **overrides):
        payload = {"name": "Reviewer", "description": "Reviews diffs."}
        payload.update(overrides)
        response = self.client.post("/api/agents", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_builtin_agents_expose_default_icons(self):
        response = self.client.get("/api/agents")
        self.assertEqual(response.status_code, 200)
        icons = {item["agent_id"]: item["icon"] for item in response.json()["agents"]}
        self.assertEqual(icons["build"], "wrench")
        self.assertEqual(icons["ask"], "message")
        self.assertEqual(icons["plan"], "clipboard")

    def test_created_agent_keeps_icon(self):
        created = self.create_agent(icon="rocket")
        self.assertEqual(created["icon"], "rocket")

        listed = {item["agent_id"]: item for item in self.client.get("/api/agents").json()["agents"]}
        self.assertEqual(listed[created["agent_id"]]["icon"], "rocket")

    def test_icon_defaults_to_empty(self):
        created = self.create_agent()
        self.assertEqual(created["icon"], "")

    def test_update_icon(self):
        created = self.create_agent(icon="bot")
        response = self.client.put(f"/api/agents/{created['agent_id']}", json={"icon": "sparkles"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["icon"], "sparkles")

        reloaded = self.store.get_agent(created["agent_id"])
        self.assertEqual(reloaded["icon"], "sparkles")

    def test_invalid_icon_is_rejected(self):
        response = self.client.post("/api/agents", json={"name": "Bad", "icon": "Not An Icon"})
        self.assertEqual(response.status_code, 422)
        response = self.client.post("/api/agents", json={"name": "Bad", "icon": "x" * 40})
        self.assertEqual(response.status_code, 422)


class AgentTableMigrationTest(unittest.TestCase):
    """An ``agents`` table created before icons existed must be upgraded in place."""

    def test_legacy_table_gains_icon_column(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = Path(tmp) / "legacy.db"
            now = datetime.now(UTC).isoformat()
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE agents (
                    agent_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    system_prompt TEXT NOT NULL DEFAULT '',
                    tool_names TEXT,
                    skill_names TEXT NOT NULL DEFAULT '[]',
                    mcp_servers TEXT NOT NULL DEFAULT '[]',
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, name, description, system_prompt,
                    tool_names, skill_names, mcp_servers, is_builtin,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("custom", "Custom", "", "", None, "[]", "[]", 0, now, now),
            )
            # A built-in row written before icons existed must be backfilled from
            # MODE_CONFIGS instead of staying blank.
            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, name, description, system_prompt,
                    tool_names, skill_names, mcp_servers, is_builtin,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("build", "Build", "", "", None, "[]", "[]", 1, now, now),
            )
            conn.commit()
            conn.close()

            store = _SqliteTaskStore(db_path)
            try:
                self.assertEqual(store.get_agent("custom")["icon"], "")
                self.assertEqual(store.get_agent("build")["icon"], "wrench")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()

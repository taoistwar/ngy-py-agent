"""The global AGENTS.md setting: the loop's view, the database row, and the API.

On/off and the byte cap are one setting in the settings table (ADR 0022 D9). There is no
environment variable behind them: without a stored row the code defaults apply (on,
32 KiB), and the admin API is how the Web Admin「全局配置」page writes them.

Run from the repository root::

    uv run python test/agents_md_config_test.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import app_state  # noqa: E402
import main  # noqa: E402
import task_runtime  # noqa: E402
from agent import agents_md  # noqa: E402
from routes import admin_api  # noqa: E402
from task_store import _SqliteTaskStore  # noqa: E402


class AgentsMdSettingsTest(unittest.TestCase):
    """What the loop does with the settings object it is handed."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name)
        self.write("AGENTS.md", "Root rule.")

    def write(self, name: str, text: str) -> None:
        (self.workspace / name).write_text(text, encoding="utf-8")

    def test_the_setting_can_turn_the_read_off(self):
        instructions = agents_md.load_instructions(
            str(self.workspace), agents_md.AgentsMdSettings(enabled=False)
        )
        self.assertIsNone(instructions)

    def test_the_setting_carries_the_byte_cap(self):
        self.write("AGENTS.md", "字" * 200)
        instructions = agents_md.load_instructions(
            str(self.workspace), agents_md.AgentsMdSettings(max_bytes=100)
        )
        self.assertTrue(instructions.root.truncated)

    def test_without_a_setting_object_the_code_defaults_decide(self):
        # A leftover .env entry must not turn the read off; the default is on.
        with patch.dict(os.environ, {"AGENTS_MD_ENABLED": "0"}):
            instructions = agents_md.load_instructions(str(self.workspace))
        self.assertIsNotNone(instructions)
        self.assertFalse(instructions.root.truncated)


class AgentsMdConfigApiTest(unittest.TestCase):
    """The startup loader, the store round trip and the two admin routes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = app_state.monitor_store
        self._previous = (
            app_state.agents_md_enabled,
            app_state.agents_md_max_bytes,
            app_state.agents_md_source,
        )
        # ``load_startup_config`` resolves every setting, so the restart test has to put
        # the other three back as well.
        self._previous_others = (
            app_state.permission_mode,
            app_state.permission_mode_source,
            app_state.agent_max_steps,
            app_state.agent_max_steps_source,
            app_state.task_retention_days,
            app_state.task_retention_source,
        )
        # The routes read ``app_state``, so that is where a test swaps the store.
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        app_state.monitor_store = self.store
        self.client = TestClient(main.app)

    def tearDown(self):
        app_state.monitor_store = self._previous_store
        (
            app_state.agents_md_enabled,
            app_state.agents_md_max_bytes,
            app_state.agents_md_source,
        ) = self._previous
        (
            app_state.permission_mode,
            app_state.permission_mode_source,
            app_state.agent_max_steps,
            app_state.agent_max_steps_source,
            app_state.task_retention_days,
            app_state.task_retention_source,
        ) = self._previous_others
        self.store.close()
        self._tmp.cleanup()

    def load(self):
        return admin_api._load_agents_md_config()

    def test_the_code_defaults_apply_without_a_stored_value(self):
        self.assertEqual(
            (agents_md.AgentsMdSettings(), "default"),
            self.load(),
        )

    def test_leftover_environment_variables_are_ignored(self):
        # Regression pin: the setting used to be read from the environment, so a
        # leftover .env entry must not override (or appear as) the source.
        with patch.dict(
            os.environ,
            {"AGENTS_MD_ENABLED": "0", "AGENTS_MD_MAX_BYTES": "2048"},
        ):
            settings, source = self.load()

        self.assertEqual(agents_md.AgentsMdSettings(), settings)
        self.assertEqual("default", source)

    def test_a_stored_value_wins(self):
        self.store.set_agents_md_config(False, 4096)

        settings, source = self.load()

        self.assertFalse(settings.enabled)
        self.assertEqual(4096, settings.max_bytes)
        self.assertEqual("database", source)

    def test_a_stored_cap_outside_the_range_is_clamped(self):
        # An older build (or a hand-edited row) must not be able to disable the cap.
        self.store.set_agents_md_config(True, 10)

        settings, source = self.load()

        self.assertEqual(agents_md.MIN_MAX_BYTES, settings.max_bytes)
        self.assertEqual("database", source)

    def test_the_store_round_trips_both_fields(self):
        self.store.set_agents_md_config(False, 2048)

        self.assertEqual({"enabled": False, "max_bytes": 2048}, self.store.get_agents_md_config())

    def test_the_api_writes_and_reads_the_setting(self):
        updated = self.client.put(
            "/api/admin/agents-md", json={"enabled": False, "max_bytes": 4096}
        )

        self.assertEqual(200, updated.status_code)
        expected = {"enabled": False, "max_bytes": 4096, "source": "database"}
        self.assertEqual(expected, updated.json())
        self.assertEqual(expected, self.client.get("/api/admin/agents-md").json())

    def test_a_cap_outside_the_accepted_range_is_rejected(self):
        for value in (0, agents_md.MIN_MAX_BYTES - 1, agents_md.MAX_BYTES_LIMIT + 1):
            response = self.client.put(
                "/api/admin/agents-md", json={"enabled": True, "max_bytes": value}
            )
            self.assertEqual(422, response.status_code, value)

    def test_the_saved_setting_reaches_the_next_task(self):
        self.client.put("/api/admin/agents-md", json={"enabled": False, "max_bytes": 2048})

        settings = task_runtime.resolve_agents_md_settings()

        self.assertEqual(agents_md.AgentsMdSettings(enabled=False, max_bytes=2048), settings)

    def test_a_restart_reads_the_saved_value_back(self):
        self.client.put("/api/admin/agents-md", json={"enabled": True, "max_bytes": 8192})
        # A fresh process starts from the code defaults and then loads the database.
        app_state.agents_md_enabled = True
        app_state.agents_md_max_bytes = agents_md.DEFAULT_MAX_BYTES
        app_state.agents_md_source = "default"

        admin_api.load_startup_config()

        self.assertTrue(app_state.agents_md_enabled)
        self.assertEqual(8192, app_state.agents_md_max_bytes)
        self.assertEqual("database", app_state.agents_md_source)


if __name__ == "__main__":
    unittest.main()

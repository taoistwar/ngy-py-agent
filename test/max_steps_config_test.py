"""The global ReAct step limit: the database value, else the code default of 9.

There is deliberately no environment variable (see ``agent/agent_loop/config.py``): a
second source would mean "not configured" has two answers. These tests pin all three
cases - nothing configured, a stored value, an out-of-range row - plus the API's view of
the source label.

Run from the repository root::

    uv run python test/max_steps_config_test.py -v
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

import main  # noqa: E402
from agent.agent_loop import DEFAULT_MAX_STEPS  # noqa: E402
from commons import state  # noqa: E402
from commons.schemas import MAX_STEPS_LIMIT  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402
from routes import admin_api  # noqa: E402


class MaxStepsConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = state.monitor_store
        self._previous = (state.agent_max_steps, state.agent_max_steps_source)
        # The routes read ``commons.state``, so that is where a test swaps the store.
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        state.monitor_store = self.store
        self.client = TestClient(main.app)

    def tearDown(self):
        state.monitor_store = self._previous_store
        state.agent_max_steps, state.agent_max_steps_source = self._previous
        self.store.close()
        self._tmp.cleanup()

    def load(self):
        return admin_api._load_agent_max_steps_config()

    def test_the_code_default_is_nine(self):
        self.assertEqual(9, DEFAULT_MAX_STEPS)
        self.assertEqual((DEFAULT_MAX_STEPS, "default"), self.load())

    def test_the_environment_variable_is_ignored(self):
        # Regression pin: ``REACT_MAX_STEPS`` no longer exists, so a leftover ``.env``
        # entry must not silently change the step limit.
        with patch.dict(os.environ, {"REACT_MAX_STEPS": "20"}):
            self.assertEqual((DEFAULT_MAX_STEPS, "default"), self.load())

    def test_a_database_value_wins(self):
        self.store.set_agent_max_steps(42)

        self.assertEqual((42, "database"), self.load())

    def test_a_stored_value_outside_the_range_is_clamped(self):
        self.store.set_agent_max_steps(0)
        self.assertEqual((1, "database"), self.load())

        self.store.set_agent_max_steps(MAX_STEPS_LIMIT + 1)
        self.assertEqual((MAX_STEPS_LIMIT, "database"), self.load())

    def test_the_api_reports_the_default_before_anything_is_saved(self):
        self.assertEqual(
            {"max_steps": DEFAULT_MAX_STEPS, "source": "default"},
            self.client.get("/api/admin/max-steps").json(),
        )

    def test_saving_turns_the_source_into_database(self):
        updated = self.client.put("/api/admin/max-steps", json={"max_steps": 12})

        self.assertEqual(200, updated.status_code)
        expected = {"max_steps": 12, "source": "database"}
        self.assertEqual(expected, updated.json())
        self.assertEqual(expected, self.client.get("/api/admin/max-steps").json())

    def test_a_value_outside_the_accepted_range_is_rejected(self):
        for value in (0, MAX_STEPS_LIMIT + 1):
            response = self.client.put("/api/admin/max-steps", json={"max_steps": value})
            self.assertEqual(422, response.status_code, value)


if __name__ == "__main__":
    unittest.main()

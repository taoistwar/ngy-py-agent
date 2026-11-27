"""Task retention: the stored row, else the code default of 36600 days.

Retention has no environment variable: a leftover ``TASK_RETENTION_DAYS`` in ``.env``
must not change what the purge uses. These tests pin the code default, the stored value,
the ignored env entry and the API's source label.

Run from the repository root::

    uv run python test/retention_config_test.py -v
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
from commons import state  # noqa: E402
from dao import TASK_RETENTION_DEFAULT_DAYS, _SqliteTaskStore  # noqa: E402
from routes import admin_api  # noqa: E402


class RetentionConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = state.monitor_store
        self._previous = (state.task_retention_days, state.task_retention_source)
        # The routes read ``commons.state``, so that is where a test swaps the store.
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        state.monitor_store = self.store
        self.client = TestClient(main.app)

    def tearDown(self):
        state.monitor_store = self._previous_store
        state.task_retention_days, state.task_retention_source = self._previous
        self.store.close()
        self._tmp.cleanup()

    def load(self):
        return admin_api._load_task_retention_config()

    def test_the_code_default_is_about_hundred_years(self):
        self.assertEqual(36600, TASK_RETENTION_DEFAULT_DAYS)
        self.assertEqual((TASK_RETENTION_DEFAULT_DAYS, "default"), self.load())

    def test_the_environment_variable_is_ignored(self):
        # Regression pin: ``TASK_RETENTION_DAYS`` no longer exists, so a leftover
        # ``.env`` entry must not silently change the retention window.
        with patch.dict(os.environ, {"TASK_RETENTION_DAYS": "7"}):
            self.assertEqual((TASK_RETENTION_DEFAULT_DAYS, "default"), self.load())

    def test_a_database_value_wins(self):
        self.store.set_task_retention_days(30)

        self.assertEqual((30, "database"), self.load())

    def test_the_api_reports_the_default_before_anything_is_saved(self):
        self.assertEqual(
            {
                "retention_days": TASK_RETENTION_DEFAULT_DAYS,
                "retention_source": "default",
                "removed_tasks": 0,
            },
            self.client.get("/api/admin/retention").json(),
        )

    def test_saving_turns_the_source_into_database(self):
        updated = self.client.put("/api/admin/retention", json={"retention_days": 30})

        self.assertEqual(200, updated.status_code)
        expected = {
            "retention_days": 30,
            "retention_source": "database",
            "removed_tasks": 0,
        }
        self.assertEqual(expected, updated.json())
        self.assertEqual(expected, self.client.get("/api/admin/retention").json())

    def test_a_negative_value_is_rejected(self):
        response = self.client.put("/api/admin/retention", json={"retention_days": -1})

        self.assertEqual(422, response.status_code)


if __name__ == "__main__":
    unittest.main()

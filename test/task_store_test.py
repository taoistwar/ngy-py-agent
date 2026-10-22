"""Ordering tests for the task list.

The web admin renders the list top to bottom, so the store hands the tasks back
oldest first. That is a contract the UI depends on, which is why it is pinned
here instead of being left to whatever order the query happens to produce.

Run from the repository root::

    uv run python test/task_store_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from task_store import _SqliteTaskStore  # noqa: E402


class TaskListOrderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")

    def tearDown(self):
        self._tmp.cleanup()

    def _create_task(self, query: str, created_at: str) -> str:
        """Create a task and pin its creation time, so the order is not wall-clock luck."""
        task_id = self.store.create_task(query, "openai")
        self.store._conn.execute(
            "UPDATE tasks SET created_at = ? WHERE task_id = ?",
            (created_at, task_id),
        )
        self.store._conn.commit()
        return task_id

    def test_the_list_is_oldest_first(self):
        newer = self._create_task("second", "2026-10-22T06:00:00+00:00")
        older = self._create_task("first", "2026-10-22T04:00:00+00:00")

        order = [task["task_id"] for task in self.store.list_tasks()]

        self.assertEqual([older, newer], order)

    def test_the_session_scoped_list_is_oldest_first(self):
        newer = self._create_task("second", "2026-10-22T06:00:00+00:00")
        older = self._create_task("first", "2026-10-22T04:00:00+00:00")
        session_id = self.store.ensure_default_session()

        order = [
            task["task_id"]
            for task in self.store.list_tasks(session_id=session_id)
        ]

        self.assertEqual([older, newer], order)


class TaskNameTest(unittest.TestCase):
    """The list shows a task name; the raw query stays available for the detail view."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_new_task_has_no_name_yet(self):
        task_id = self.store.create_task("build a report", "openai")

        self.assertEqual("", self.store.get_task(task_id)["name"])
        self.assertEqual("", self.store.list_tasks()[0]["name"])

    def test_the_name_survives_in_both_read_paths(self):
        task_id = self.store.create_task("build a report", "openai")

        self.store.set_task_name(task_id, "report draft")

        self.assertEqual("report draft", self.store.get_task(task_id)["name"])
        self.assertEqual("report draft", self.store.list_tasks()[0]["name"])
        self.assertEqual("build a report", self.store.get_task(task_id)["query"])

    def test_naming_a_missing_task_is_a_no_op(self):
        self.assertFalse(self.store.set_task_name("missing-task", "name"))


if __name__ == "__main__":
    unittest.main()

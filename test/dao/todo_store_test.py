"""Task store contracts for the session-scoped plan (``todo_write``).

The plan is what the web admin shows as "what this conversation is doing", so the
parts the UI depends on are pinned here: one row per session, replaced whole, gone
with its session, and never shared between sessions.

Run from the repository root::

    uv run python test/dao/todo_store_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dao import _SqliteTaskStore  # noqa: E402

PLAN = [
    {"content": "Read the parser", "status": "completed"},
    {"content": "Fix the parser", "status": "in_progress"},
]


class SessionTodoStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        self.session_id = self.store.create_session("Plan session")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_a_session_without_a_plan_reads_as_none(self):
        self.assertIsNone(self.store.get_session_todos(self.session_id))
        self.assertIsNone(self.store.get_session_todos(""))
        self.assertIsNone(self.store.get_session_todos("no-such-session"))

    def test_the_plan_round_trips_with_the_task_that_wrote_it(self):
        self.store.set_session_todos(self.session_id, PLAN, "task-1")

        record = self.store.get_session_todos(self.session_id)

        self.assertEqual(record["todos"], PLAN)
        self.assertEqual(record["task_id"], "task-1")
        self.assertIsNotNone(record["updated_at"])

    def test_a_second_write_replaces_the_plan_instead_of_appending(self):
        self.store.set_session_todos(self.session_id, PLAN, "task-1")

        self.store.set_session_todos(
            self.session_id, [{"content": "Only step", "status": "pending"}], "task-2"
        )

        record = self.store.get_session_todos(self.session_id)
        self.assertEqual(record["todos"], [{"content": "Only step", "status": "pending"}])
        self.assertEqual(record["task_id"], "task-2")

    def test_sessions_do_not_see_each_other_plan(self):
        other = self.store.create_session("Other session")

        self.store.set_session_todos(self.session_id, PLAN, "task-1")

        self.assertIsNone(self.store.get_session_todos(other))

    def test_deleting_a_session_takes_its_plan_with_it(self):
        self.store.set_session_todos(self.session_id, PLAN, "task-1")

        self.store.delete_session(self.session_id)

        self.assertIsNone(self.store.get_session_todos(self.session_id))

    def test_an_unreadable_row_reads_as_an_empty_plan(self):
        self.store.set_session_todos(self.session_id, PLAN, "task-1")
        with self.store._lock:
            self.store._conn.execute(
                "UPDATE session_todos SET items = ? WHERE session_id = ?",
                ("not json", self.session_id),
            )
            self.store._conn.commit()

        record = self.store.get_session_todos(self.session_id)

        self.assertEqual(record["todos"], [])


if __name__ == "__main__":
    unittest.main()

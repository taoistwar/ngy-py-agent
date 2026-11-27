"""Task store contracts for the workspace's task board (``task_*``).

The parts the tools and the panel depend on are pinned here: generated ids look like
``task_xxxxxxxx``, a board only ever shows its own tasks, an update writes the columns
it was given and leaves the others alone, and deleting a workspace takes its board with
it - a board nobody can reach is a leak, not a record.

Run from the repository root::

    uv run python test/dao/board_tasks_test.py -v
"""

import re
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

BOARD = "workspace:board-1"
TASK_ID_PATTERN = re.compile(r"^task_[0-9a-f]{8}$")


class BoardTaskStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_an_empty_board_reads_as_an_empty_list(self):
        self.assertEqual(self.store.list_board_tasks(BOARD), [])
        self.assertEqual(self.store.list_board_tasks(""), [])
        self.assertIsNone(self.store.get_board_task(BOARD, "task_00000000"))

    def test_a_created_task_is_pending_unowned_and_gets_a_readable_id(self):
        task = self.store.create_board_task(BOARD, "setup schema", "tables first")

        self.assertRegex(task["task_id"], TASK_ID_PATTERN)
        self.assertEqual(task["status"], "pending")
        self.assertIsNone(task["owner"])
        self.assertEqual(task["blocked_by"], [])
        self.assertEqual(task["description"], "tables first")
        self.assertEqual(
            self.store.get_board_task(BOARD, task["task_id"])["subject"], "setup schema"
        )

    def test_created_tasks_keep_their_order_and_their_ids_are_unique(self):
        ids = [
            self.store.create_board_task(BOARD, f"task {index}")["task_id"]
            for index in range(12)
        ]

        listed = self.store.list_board_tasks(BOARD)

        self.assertEqual(len(set(ids)), 12)
        self.assertEqual([task["task_id"] for task in listed], ids)

    def test_boards_do_not_see_each_others_tasks(self):
        self.store.create_board_task(BOARD, "mine")

        self.assertEqual(self.store.list_board_tasks("session:elsewhere"), [])

    def test_an_update_writes_the_columns_it_was_given_and_leaves_the_rest(self):
        task = self.store.create_board_task(BOARD, "setup schema")
        task_id = task["task_id"]

        self.store.update_board_task(BOARD, task_id, status="in_progress", owner="s1")
        self.store.update_board_task(BOARD, task_id, blocked_by=["task_deadbeef"])

        updated = self.store.get_board_task(BOARD, task_id)
        self.assertEqual(updated["status"], "in_progress")
        self.assertEqual(updated["owner"], "s1")
        self.assertEqual(updated["blocked_by"], ["task_deadbeef"])

    def test_an_update_can_clear_the_owner(self):
        task_id = self.store.create_board_task(BOARD, "setup schema")["task_id"]
        self.store.update_board_task(BOARD, task_id, owner="s1")

        self.store.update_board_task(BOARD, task_id, owner=None)

        self.assertIsNone(self.store.get_board_task(BOARD, task_id)["owner"])

    def test_updating_a_task_that_is_not_on_the_board_reports_nothing(self):
        self.assertIsNone(
            self.store.update_board_task(BOARD, "task_00000000", status="completed")
        )

    def test_deleting_a_workspace_takes_its_board_with_it(self):
        workspace_id = self.store.create_workspace("Project", str(Path(self._tmp.name)))
        board_id = f"workspace:{workspace_id}"
        self.store.create_board_task(board_id, "setup schema")

        self.store.delete_workspace(workspace_id)

        self.assertEqual(self.store.list_board_tasks(board_id), [])


if __name__ == "__main__":
    unittest.main()

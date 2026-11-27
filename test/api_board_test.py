"""The task board as the web admin reads it: ``GET /api/tasks/{id}`` carries ``board``.

What the unit tests cannot reach: the board is resolved through the task's **workspace**,
one level above the session, so every conversation of the project sees the same graph -
and a project's board never leaks into another project's tasks.

Run from the repository root::

    uv run python test/api_board_test.py -v
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

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402


class BoardApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        # The live state is ``commons.state``'s, not ``main``'s: the routes read it
        # there, so that is where a test has to swap it.
        self._previous_store = state.monitor_store
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        state.monitor_store = self.store
        self.client = TestClient(main.app)

        self.workspace_id = self.store.create_workspace(
            "Project", str(Path(self._tmp.name) / "project")
        )
        self.session_id = self.store.create_session("Plan session", self.workspace_id)
        self.board_id = f"workspace:{self.workspace_id}"

    def tearDown(self):
        state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    def create_task(self, session_id=None):
        return self.store.create_task(
            query="Refactor the parser",
            provider="openai",
            session_id=session_id or self.session_id,
        )

    def detail(self, task_id):
        response = self.client.get(f"/api/tasks/{task_id}")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_a_task_detail_carries_the_board_of_its_workspace(self):
        task_id = self.create_task()
        schema = self.store.create_board_task(self.board_id, "setup schema")
        endpoints = self.store.create_board_task(self.board_id, "create API endpoints")
        self.store.update_board_task(
            self.board_id, endpoints["task_id"], blocked_by=[schema["task_id"]]
        )

        board = self.detail(task_id)["board"]

        self.assertEqual([item["task_id"] for item in board], [schema["task_id"], endpoints["task_id"]])
        self.assertTrue(board[0]["ready"])
        self.assertFalse(board[1]["ready"])
        self.assertEqual(board[1]["blocked_by_subjects"], ["setup schema"])

    def test_a_second_conversation_in_the_same_project_sees_the_same_board(self):
        other_session = self.store.create_session("Second session", self.workspace_id)
        other_task = self.create_task(other_session)
        self.store.create_board_task(self.board_id, "setup schema")

        self.assertEqual(len(self.detail(other_task)["board"]), 1)

    def test_another_project_does_not_see_the_board(self):
        other_workspace = self.store.create_workspace(
            "Other", str(Path(self._tmp.name) / "other")
        )
        other_session = self.store.create_session("Other session", other_workspace)
        other_task = self.create_task(other_session)
        self.store.create_board_task(self.board_id, "setup schema")

        self.assertEqual(self.detail(other_task)["board"], [])

    def test_a_conversation_without_a_workspace_keeps_its_own_board(self):
        loose_session = self.store.create_session("Loose session")
        loose_task = self.create_task(loose_session)
        self.store.create_board_task(f"session:{loose_session}", "local step")
        self.store.create_board_task(self.board_id, "project step")

        board = self.detail(loose_task)["board"]

        self.assertEqual([item["subject"] for item in board], ["local step"])

    def test_the_owner_is_resolved_to_the_conversation_name(self):
        task_id = self.create_task()
        claimed = self.store.create_board_task(self.board_id, "setup schema")
        self.store.update_board_task(
            self.board_id,
            claimed["task_id"],
            status="in_progress",
            owner=self.session_id,
        )

        board = self.detail(task_id)["board"]

        self.assertEqual(board[0]["owner"], self.session_id)
        self.assertEqual(board[0]["owner_name"], "Plan session")


if __name__ == "__main__":
    unittest.main()

"""The plan as the web admin reads it: ``GET /api/tasks/{id}`` carries ``todos``.

What the unit tests cannot reach: the plan is resolved through the task's **session**,
so every task of the conversation shows the same list - that is what lets the existing
one-second task poll keep the panel in sync without an endpoint of its own.

Run from the repository root::

    uv run python test/todo_api_test.py -v
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
from agent.runtime.todos import MonitorTodoStore  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402

PLAN = [
    {"content": "Read the parser", "status": "completed"},
    {"content": "Fix the parser", "status": "in_progress"},
]


class TodoApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        # The live state is ``commons.state``'s, not ``main``'s: the routes read it
        # there, so that is where a test has to swap it.
        self._previous_store = state.monitor_store
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        state.monitor_store = self.store
        self.client = TestClient(main.app)
        self.session_id = self.store.create_session("Plan session")

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

    def test_a_task_detail_carries_the_plan_of_its_session(self):
        task_id = self.create_task()
        self.store.set_session_todos(self.session_id, PLAN, task_id)

        self.assertEqual(self.detail(task_id)["todos"], PLAN)

    def test_every_task_of_the_conversation_shows_the_same_plan(self):
        first = self.create_task()
        second = self.create_task()
        self.store.set_session_todos(self.session_id, PLAN, first)

        self.assertEqual(self.detail(second)["todos"], PLAN)

    def test_the_store_the_tool_writes_through_is_the_one_the_api_reads(self):
        task_id = self.create_task()
        board_store = MonitorTodoStore()

        board_store.save(self.session_id, PLAN, task_id)

        self.assertEqual(board_store.load(self.session_id), PLAN)
        self.assertEqual(self.detail(task_id)["todos"], PLAN)

    def test_a_session_without_a_plan_reports_an_empty_list(self):
        task_id = self.create_task()

        self.assertEqual(self.detail(task_id)["todos"], [])

    def test_another_sessions_plan_is_not_leaked(self):
        other = self.store.create_session("Other session")
        task_id = self.create_task()
        self.store.set_session_todos(other, PLAN, "elsewhere")

        self.assertEqual(self.detail(task_id)["todos"], [])


if __name__ == "__main__":
    unittest.main()

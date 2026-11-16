"""The API wiring: a created task is handed the session's earlier conversation.

``agent.history`` decides *what* the context is and the loop decides *where* it
goes; this test pins the part in between - ``POST /api/tasks`` reads the history
of the target session and gives it to the worker thread, before its own task row
can appear in that history.

Run from the repository root::

    uv run python test/task_history_test.py -v
"""

import asyncio
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from commons import state  # noqa: E402
from commons.schemas import RunTaskRequest  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402
from routes import task_api  # noqa: E402


class TaskHistoryApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        self._previous_store = state.monitor_store
        state.monitor_store = self.store
        self.session_id = self.store.create_session("conversation")

    def tearDown(self):
        state.monitor_store = self._previous_store
        self._tmp.cleanup()

    def _finished_task(self, query: str, result: str) -> None:
        task_id = self.store.create_task(query, "openai", session_id=self.session_id)
        self.store.finish_task(task_id, success=True, result=result)

    def _create_task(self, query: str) -> dict:
        """Run the route with the worker replaced by a recorder."""
        recorded: dict = {}
        recorded_in_thread = threading.Event()

        def fake_run_task(*args, **kwargs):
            recorded.update(kwargs)
            recorded_in_thread.set()

        with patch.object(task_api, "run_task", fake_run_task):
            response = asyncio.run(
                task_api.create_task(
                    RunTaskRequest(
                        query=query,
                        session_id=self.session_id,
                        agent_id="build",
                    )
                )
            )

        self.assertTrue(recorded_in_thread.wait(5), "the task worker was never started")
        self.assertTrue(response.task_id)
        return recorded

    def test_a_first_task_has_no_history(self):
        recorded = self._create_task("create add()")

        self.assertEqual([], recorded["history_messages"])

    def test_a_new_task_continues_the_sessions_finished_tasks(self):
        self._finished_task("create add()", "created add()")

        recorded = self._create_task("add tests for that")

        self.assertEqual(
            [
                {"role": "user", "content": "create add()"},
                {"role": "assistant", "content": "created add()"},
            ],
            recorded["history_messages"],
        )

    def test_the_new_task_does_not_appear_in_its_own_history(self):
        self._finished_task("create add()", "created add()")

        recorded = self._create_task("second task")

        contents = [message["content"] for message in recorded["history_messages"]]
        self.assertEqual(["create add()", "created add()"], contents)


if __name__ == "__main__":
    unittest.main()

"""Stopping a task: the click settles the record, not the thread's way out.

The stop *signal* is cooperative (ADR 0019): a thread parked inside a model request
only reads it when that request returns, which can be a minute later. What this file
pins is the other half - the click itself has to be visible immediately. Otherwise
the row keeps saying "running", and a second click looks exactly as dead as the
first, because the flag it sets was already set.

Run from the repository root::

    uv run python test/task_stop_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to the
# import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import app_state  # noqa: E402
import main  # noqa: E402
from agent.models import TaskStatus  # noqa: E402
from task_store import _SqliteTaskStore  # noqa: E402


class TaskStopApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        self._previous_store = app_state.monitor_store
        app_state.monitor_store = self.store
        self.client = TestClient(main.app)
        self.session_id = self.store.create_session("conversation")

    def tearDown(self):
        with app_state._task_stop_lock:
            app_state._task_stop_events.clear()
        app_state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    # ------------------------------------------------------------------ helpers

    def _task(self, status: TaskStatus = TaskStatus.RUNNING) -> str:
        task_id = self.store.create_task("do something", "openai", session_id=self.session_id)
        if status != TaskStatus.RUNNING:
            self.store.set_task_status(task_id, status)
        return task_id

    def _status(self, task_id: str) -> str:
        return str(self.store.get_task(task_id)["status"])

    def _result(self, task_id: str) -> str:
        for item in self.store.list_tasks(session_id=self.session_id):
            if item["task_id"] == task_id:
                return str(item["result"])
        self.fail(f"task {task_id} is not in the list")

    # -------------------------------------------------------------------- tests

    def test_a_running_task_is_settled_by_the_click(self):
        task_id = self._task()
        # The live thread's flag, as ``POST /api/tasks`` registers it.
        app_state.register_task_stop(task_id)

        response = self.client.post(f"/api/tasks/{task_id}/stop")

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()["stopped"])
        self.assertEqual(TaskStatus.STOPPED.value, self._status(task_id))

    def test_a_waiting_task_is_settled_by_the_click(self):
        """Parked on a confirmation is still in flight, so a stop still ends it."""
        task_id = self._task(TaskStatus.WAITING)
        app_state.register_task_stop(task_id)

        self.client.post(f"/api/tasks/{task_id}/stop")

        self.assertEqual(TaskStatus.STOPPED.value, self._status(task_id))

    def test_a_second_click_does_not_change_anything(self):
        task_id = self._task()
        app_state.register_task_stop(task_id)
        self.client.post(f"/api/tasks/{task_id}/stop")

        second = self.client.post(f"/api/tasks/{task_id}/stop")

        self.assertFalse(second.json()["stopped"])
        self.assertEqual(TaskStatus.STOPPED.value, self._status(task_id))

    def test_a_finished_task_is_not_touched(self):
        task_id = self._task()
        self.store.finish_task(task_id, success=True, result="all done")

        response = self.client.post(f"/api/tasks/{task_id}/stop")

        self.assertFalse(response.json()["stopped"])
        self.assertEqual(TaskStatus.SUCCESS.value, self._status(task_id))
        self.assertEqual("all done", self._result(task_id))

    def test_a_late_worker_cannot_undo_the_stop(self):
        """The model request in flight may still answer at the very end."""
        task_id = self._task()
        app_state.register_task_stop(task_id)
        self.client.post(f"/api/tasks/{task_id}/stop")

        self.store.finish_task(task_id, success=True, result="answered anyway")

        self.assertEqual(TaskStatus.STOPPED.value, self._status(task_id))
        # The answer is still worth keeping: the status is what the user decided.
        self.assertEqual("answered anyway", self._result(task_id))

    def test_a_revert_is_not_undone_by_a_late_worker_either(self):
        """Same shape, other way round: undoing the files also outlives the thread."""
        task_id = self._task()
        app_state.register_task_stop(task_id)
        self.client.post(f"/api/tasks/{task_id}/stop")
        self.store.set_task_status(task_id, TaskStatus.REVERTED)

        self.store.finish_task(task_id, success=False, status=TaskStatus.STOPPED)

        self.assertEqual(TaskStatus.REVERTED.value, self._status(task_id))

    def test_an_unknown_task_is_a_404(self):
        response = self.client.post("/api/tasks/missing/stop")

        self.assertEqual(404, response.status_code)


if __name__ == "__main__":
    unittest.main()

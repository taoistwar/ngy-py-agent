"""The startup hook is what makes recovery happen at all.

Without it the whole feature is a library nobody calls: a task whose process died
stays ``running`` forever, because the only writer of a final status is the thread
that died. This file drives the real app lifespan and checks that a leftover row is
picked up exactly once.

Run from the repository root::

    uv run python test/task_recovery/startup_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import app_state  # noqa: E402
import main  # noqa: E402
import task_recovery.launch as launch  # noqa: E402
from agent.models import EventCategory, TaskEvent, TaskStatus  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402

SYSTEM = {"role": "system", "content": "you are an agent"}
QUERY = {"role": "user", "content": "rename the file"}


class StartupResumeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        self._previous_store = app_state.monitor_store
        app_state.monitor_store = self.store
        launch._claimed.clear()
        self.session_id = self.store.create_session("conversation")

    def tearDown(self):
        launch._claimed.clear()
        app_state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    def _task(self):
        return self.store.create_task(
            "rename the file", "openai-compatible", session_id=self.session_id
        )

    def _append(self, task_id, category, title, data):
        self.store.append_event(
            task_id, TaskEvent(task_id=task_id, category=category, title=title, data=data)
        )

    def _result(self, task_id):
        for item in self.store.list_tasks(session_id=self.session_id):
            if item["task_id"] == task_id:
                return str(item["result"])
        self.fail(f"task {task_id} is not in the list")

    def test_startup_settles_a_task_that_had_already_finished(self):
        """The crash window between the closing event and the row update."""
        task_id = self._task()
        self._append(task_id, EventCategory.DEBUG, "Task finished", {"result": "all done"})

        with TestClient(main.app):
            pass

        trace = self.store.get_task(task_id)
        self.assertEqual(TaskStatus.SUCCESS.value, str(trace["status"]))
        self.assertEqual("all done", self._result(task_id))

    def test_startup_starts_the_thread_once_for_a_resumable_task(self):
        task_id = self._task()
        self._append(
            task_id,
            EventCategory.DEBUG,
            "Starting ReAct loop",
            {"max_steps": 8, "initial_messages": [SYSTEM, QUERY]},
        )
        self._append(
            task_id,
            EventCategory.LLM_REQUEST,
            "LLM request Step 1",
            {"step": 1, "provider": "openai-compatible", "raw_request": {"messages": [SYSTEM, QUERY]}},
        )

        with mock.patch.object(launch, "_spawn") as spawn:
            with TestClient(main.app):
                pass
            with TestClient(main.app):
                pass

        # Started once even though the lifespan ran twice: the sweep claims a task
        # per process, and a second thread would be the duplicated work itself.
        self.assertEqual(1, spawn.call_count)
        worker = spawn.call_args.args[0]
        self.assertEqual(task_id, worker._args[0])
        self.assertEqual([SYSTEM, QUERY], worker._kwargs["resume_messages"])
        self.assertEqual(1, worker._kwargs["resume_step"])


if __name__ == "__main__":
    unittest.main()

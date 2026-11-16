"""What startup does with the rows a dead process left behind.

Two behaviours matter here. A task that can be continued must be started exactly
once, with the conversation rebuilt from its log; and a task that cannot be
continued must be *settled with a reason* instead of sitting in ``running``
forever, which is what the old code did.

Run from the repository root::

    uv run python test/task_recovery/launch_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import task_recovery.launch as launch  # noqa: E402
from agent.models import EventCategory, TaskEvent, TaskStatus  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402

SYSTEM = {"role": "system", "content": "you are an agent"}
QUERY = {"role": "user", "content": "rename the file"}


class LaunchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        self._previous_store = state.monitor_store
        state.monitor_store = self.store
        launch._claimed.clear()
        self.session_id = self.store.create_session("conversation")
        # Every test drives the worker inline: a background thread would make the
        # assertions race against the very call they check.
        self.spawned = []
        self._spawn_patch = mock.patch.object(launch, "_spawn", side_effect=self._spawn_inline)
        self._spawn_patch.start()
        self._run_patch = mock.patch.object(launch.runtime, "run_task")
        self.run_task = self._run_patch.start()

    def tearDown(self):
        self._run_patch.stop()
        self._spawn_patch.stop()
        launch._claimed.clear()
        state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    def _spawn_inline(self, worker):
        self.spawned.append(worker)
        worker.run()

    # ----------------------------------------------------------------- helpers

    def _task(self, status=TaskStatus.RUNNING, model_id=None):
        task_id = self.store.create_task(
            "rename the file", "openai-compatible", session_id=self.session_id, model_id=model_id
        )
        if status != TaskStatus.RUNNING:
            self.store.set_task_status(task_id, status)
        return task_id

    def _append(self, task_id, category, title, data):
        self.store.append_event(
            task_id, TaskEvent(task_id=task_id, category=category, title=title, data=data)
        )

    def _starting(self, task_id, initial_messages=None, max_steps=8):
        data = {"max_steps": max_steps}
        if initial_messages is not None:
            data["initial_messages"] = initial_messages
        self._append(task_id, EventCategory.DEBUG, "Starting ReAct loop", data)

    def _request(self, task_id, step, messages, provider="openai-compatible"):
        self._append(
            task_id,
            EventCategory.LLM_REQUEST,
            f"LLM request Step {step}",
            {"step": step, "provider": provider, "raw_request": {"messages": messages}},
        )

    def _response(self, task_id, step, message):
        self._append(
            task_id,
            EventCategory.LLM_RESPONSE,
            f"LLM response Step {step}",
            {
                "step": step,
                "content": message.get("content", ""),
                "raw_response": {"choices": [{"index": 0, "message": message}]},
            },
        )

    def _tool_result(self, task_id, step, name, call_id, result):
        self._append(
            task_id,
            EventCategory.TOOL_RESULT,
            f"Tool result: {name}",
            {"step": step, "name": name, "tool_call_id": call_id, "result": result},
        )

    def _status(self, task_id):
        return str(self.store.get_task(task_id)["status"])

    def _events(self, task_id):
        return self.store.get_events(task_id)

    # ------------------------------------------------------------------- tests

    def test_a_task_that_can_be_continued_is_started_once(self):
        task_id = self._task()
        self._starting(task_id, initial_messages=[SYSTEM, QUERY])
        self._request(task_id, 1, [SYSTEM, QUERY])

        started = launch.resume_interrupted_tasks(self.store)

        self.assertEqual([task_id], started)
        self.assertEqual(1, self.run_task.call_count)
        kwargs = self.run_task.call_args.kwargs
        self.assertEqual(1, kwargs["resume_step"])
        self.assertEqual([SYSTEM, QUERY], kwargs["resume_messages"])

    def test_a_recorded_tool_result_is_handed_over_not_re_executed(self):
        task_id = self._task()
        messages = [SYSTEM, QUERY]
        call = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-1", "type": "function", "function": {"name": "edit_file", "arguments": "{}"}}
            ],
        }
        self._starting(task_id, initial_messages=messages)
        self._request(task_id, 1, messages)
        self._response(task_id, 1, call)
        self._tool_result(task_id, 1, "edit_file", "call-1", "renamed")

        launch.resume_interrupted_tasks(self.store)

        resumed = self.run_task.call_args.kwargs["resume_messages"]
        self.assertEqual("renamed", resumed[-1]["content"])
        self.assertEqual(2, self.run_task.call_args.kwargs["resume_step"])

    def test_a_second_sweep_does_not_start_the_task_again(self):
        task_id = self._task()
        self._starting(task_id, initial_messages=[SYSTEM, QUERY])
        self._request(task_id, 1, [SYSTEM, QUERY])

        launch.resume_interrupted_tasks(self.store)
        launch.resume_interrupted_tasks(self.store)

        self.assertEqual(1, self.run_task.call_count)

    def test_a_concluded_task_is_settled_without_running_it(self):
        task_id = self._task()
        self._starting(task_id, initial_messages=[SYSTEM, QUERY])
        self._append(task_id, EventCategory.DEBUG, "Task finished", {"result": "all done"})

        started = launch.resume_interrupted_tasks(self.store)

        self.assertEqual([], started)
        self.assertEqual(0, self.run_task.call_count)
        self.assertEqual(TaskStatus.SUCCESS.value, self._status(task_id))

    def test_a_task_without_any_request_is_restarted_from_the_query(self):
        """Nothing was executed, so re-running it from the top repeats no work."""
        task_id = self._task()
        self._starting(task_id)

        launch.resume_interrupted_tasks(self.store)

        self.assertIsNone(self.run_task.call_args.kwargs["resume_messages"])
        self.assertEqual(1, self.run_task.call_args.kwargs["resume_step"])

    def test_a_task_without_a_usable_log_is_marked_failed_with_a_reason(self):
        task_id = self._task()
        self._request(task_id, 1, [QUERY], provider="anthropic")

        started = launch.resume_interrupted_tasks(self.store)

        self.assertEqual([], started)
        self.assertEqual(TaskStatus.FAILED.value, self._status(task_id))
        titles = [event["title"] for event in self._events(task_id)]
        self.assertIn("Task recovery failed", titles)

    def test_a_task_that_keeps_dying_is_given_up_on(self):
        task_id = self._task()
        self._starting(task_id, initial_messages=[SYSTEM, QUERY])
        value = int(launch.os.getenv(launch._MAX_ATTEMPTS_ENV, launch.DEFAULT_MAX_ATTEMPTS))
        for _ in range(value):
            self.store.increase_resume_count(task_id)

        started = launch.resume_interrupted_tasks(self.store)

        self.assertEqual([], started)
        self.assertEqual(0, self.run_task.call_count)
        self.assertEqual(TaskStatus.FAILED.value, self._status(task_id))
        titles = [event["title"] for event in self._events(task_id)]
        self.assertIn("Task recovery gave up", titles)

    def test_a_resume_that_made_progress_does_not_use_up_the_budget(self):
        """A task that keeps moving forward must survive repeated restarts."""
        task_id = self._task()
        messages = [SYSTEM, QUERY]
        call = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
            ],
        }
        after_call = messages + [
            call,
            {"role": "tool", "tool_call_id": "call-1", "name": "read_file", "content": "v1"},
        ]
        self._starting(task_id, initial_messages=messages)
        self._request(task_id, 1, messages)
        # A previous resume, then the work it started actually produced something.
        self._append(task_id, EventCategory.DEBUG, "Task resumed after restart", {})
        self._response(task_id, 1, call)
        self._tool_result(task_id, 1, "read_file", "call-1", "v1")
        self._request(task_id, 2, after_call)
        for _ in range(launch.DEFAULT_MAX_ATTEMPTS):
            self.store.increase_resume_count(task_id)

        started = launch.resume_interrupted_tasks(self.store)

        self.assertEqual([task_id], started)
        self.assertEqual(2, self.run_task.call_args.kwargs["resume_step"])
        self.assertEqual(1, self.store.list_unfinished_tasks()[0]["resume_count"])

    def test_a_task_whose_model_vanished_is_marked_failed(self):
        task_id = self._task(model_id="model-that-is-gone")
        self._starting(task_id, initial_messages=[SYSTEM, QUERY])
        self._request(task_id, 1, [SYSTEM, QUERY])

        started = launch.resume_interrupted_tasks(self.store)

        self.assertEqual([], started)
        self.assertEqual(TaskStatus.FAILED.value, self._status(task_id))

    def test_a_task_owned_by_a_live_thread_is_left_alone(self):
        task_id = self._task()
        self._starting(task_id, initial_messages=[SYSTEM, QUERY])
        self._request(task_id, 1, [SYSTEM, QUERY])
        state.register_task_stop(task_id)
        try:
            launch.resume_interrupted_tasks(self.store)
        finally:
            state.clear_task_stop(task_id)

        self.assertEqual(0, self.run_task.call_count)
        self.assertEqual(TaskStatus.RUNNING.value, self._status(task_id))

    def test_finished_tasks_are_not_scanned(self):
        stopped = self._task()
        self.store.finish_task(stopped, success=False, status=TaskStatus.STOPPED)
        succeeded = self._task()
        self.store.finish_task(succeeded, success=True, result="done")

        started = launch.resume_interrupted_tasks(self.store)

        self.assertEqual([], started)
        self.assertEqual(0, self.run_task.call_count)


class UnfinishedTaskQueryTest(unittest.TestCase):
    def test_only_running_and_waiting_rows_are_returned(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            store = _SqliteTaskStore(Path(folder) / "tasks.db")
            try:
                session_id = store.create_session("conversation")
                running = store.create_task("a", "openai", session_id=session_id)
                waiting = store.create_task("b", "openai", session_id=session_id)
                store.set_task_status(waiting, TaskStatus.WAITING)
                done = store.create_task("c", "openai", session_id=session_id)
                store.finish_task(done, success=True, result="done")

                ids = [task["task_id"] for task in store.list_unfinished_tasks()]

                self.assertEqual([running, waiting], ids)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()

"""What one scheduled fire creates, and what the clock does on each tick.

The contract these tests pin down: a run opens **a session first and a task second**,
the run record names both, an attempt that cannot start a task is recorded instead of
raised, and a schedule whose previous run is still going does not stack a second one.

Run from the repository root::

    uv run python test/agent/scheduling/runner_test.py -v
"""

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.runtime import launcher  # noqa: E402
from agent.runtime.scheduling import loop, runner  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402
from dao.scheduled import RUN_FAILED, RUN_SKIPPED, RUN_STARTED  # noqa: E402

PROMPT = "run the test suite and report failures"


class FireScheduleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = state.monitor_store
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        state.monitor_store = self.store
        self.existing_session = self.store.create_session("existing conversation")

        # The worker thread would call a model; every test only cares about the
        # records, so the run itself is a no-op that leaves the task "running".
        self._run_patch = mock.patch.object(launcher, "run_task")
        self.run_task = self._run_patch.start()

        # Record the order the two records are created in: session before task is the
        # whole point of the feature.
        self.order = []
        real_launch = launcher.launch_task

        def recording_launch(**kwargs):
            self.order.append("task")
            return real_launch(**kwargs)

        real_create_session = self.store.create_session

        def recording_create_session(name, workspace_id=None):
            self.order.append("session")
            return real_create_session(name, workspace_id)

        self.store.create_session = recording_create_session
        self._launch_patch = mock.patch.object(runner, "launch_task", side_effect=recording_launch)
        self._launch_patch.start()

    def tearDown(self):
        self._launch_patch.stop()
        self._run_patch.stop()
        state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    def make_schedule(self, **overrides):
        payload = {
            "cron": "0 9 * * *",
            "prompt": PROMPT,
            "name": "Nightly tests",
            "agent_id": "build",
        }
        payload.update(overrides)
        schedule_id = self.store.create_schedule(**payload)
        return self.store.get_schedule(schedule_id)

    def test_a_run_opens_a_session_before_it_creates_the_task(self):
        schedule = self.make_schedule()

        run = runner.fire_schedule(schedule)

        self.assertEqual(["session", "task"], self.order)
        self.assertEqual(RUN_STARTED, run["status"])
        task = self.store.get_task(run["task_id"])
        self.assertEqual(run["session_id"], task["session_id"])
        self.assertEqual(PROMPT, task["query"])

    def test_every_run_gets_its_own_session(self):
        schedule = self.make_schedule()

        first = runner.fire_schedule(schedule)
        # Finish the first task, otherwise the second fire is (correctly) skipped.
        self.store.finish_task(first["task_id"], success=True, result="done")
        second = runner.fire_schedule(self.store.get_schedule(schedule["schedule_id"]))

        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertNotEqual(self.existing_session, first["session_id"])

    def test_a_run_while_the_previous_one_is_in_flight_is_skipped(self):
        schedule = self.make_schedule()

        runner.fire_schedule(schedule)
        second = runner.fire_schedule(self.store.get_schedule(schedule["schedule_id"]))

        self.assertEqual(RUN_SKIPPED, second["status"])
        self.assertEqual("", second["task_id"])
        self.assertEqual(1, self.run_task.call_count)

    def test_a_manual_run_is_recorded_with_its_trigger(self):
        schedule = self.make_schedule()

        run = runner.fire_schedule(schedule, "manual")

        self.assertEqual("manual", run["trigger"])

    def test_a_one_shot_schedule_pauses_itself_after_firing(self):
        schedule = self.make_schedule(recurring=False)

        runner.fire_schedule(schedule)

        self.assertFalse(self.store.get_schedule(schedule["schedule_id"])["enabled"])

    def test_a_run_that_cannot_start_a_task_is_recorded_instead_of_raised(self):
        schedule = self.make_schedule(model_id="model-that-is-gone")

        run = runner.fire_schedule(schedule)

        self.assertEqual(RUN_FAILED, run["status"])
        self.assertIn("Model not found", run["error"])
        self.assertEqual("", run["task_id"])
        # The session was still opened first - that is the order the feature promises -
        # and the failure is what kept the task from existing.
        self.assertEqual("session", self.order[0])
        self.assertEqual(0, len(self.store.list_tasks()))

    def test_the_run_uses_the_schedules_workspace(self):
        workspace_id = self.store.create_workspace("Project", str(_REPO_ROOT))
        schedule = self.make_schedule(workspace_id=workspace_id)

        run = runner.fire_schedule(schedule)

        self.assertEqual(workspace_id, self.store.get_session(run["session_id"])["workspace_id"])

    def test_a_deleted_workspace_does_not_leave_a_dangling_session_reference(self):
        workspace_id = self.store.create_workspace("Project", str(_REPO_ROOT))
        schedule = self.make_schedule(workspace_id=workspace_id)
        self.store.delete_workspace(workspace_id)

        run = runner.fire_schedule(schedule)

        self.assertIsNone(self.store.get_session(run["session_id"])["workspace_id"])


class TickTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = state.monitor_store
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        state.monitor_store = self.store
        self._run_patch = mock.patch.object(launcher, "run_task")
        self.run_task = self._run_patch.start()

    def tearDown(self):
        self._run_patch.stop()
        state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    def make_schedule(self, **overrides):
        payload = {"cron": "0 9 * * *", "prompt": PROMPT, "name": "Nightly"}
        payload.update(overrides)
        return self.store.create_schedule(**payload)

    def finish_all_tasks(self):
        for task in self.store.list_tasks():
            self.store.finish_task(task["task_id"], success=True, result="done")

    def test_a_due_schedule_fires_and_reports_the_run(self):
        self.make_schedule()

        fired = loop.tick(datetime(2026, 11, 27, 9, 0))

        self.assertEqual(1, len(fired))
        self.assertEqual(RUN_STARTED, fired[0]["status"])

    def test_the_same_minute_does_not_fire_twice(self):
        self.make_schedule()

        loop.tick(datetime(2026, 11, 27, 9, 0))
        self.assertEqual([], loop.tick(datetime(2026, 11, 27, 9, 0)))

    def test_a_minute_that_does_not_match_does_nothing(self):
        self.make_schedule()

        self.assertEqual([], loop.tick(datetime(2026, 11, 27, 9, 1)))

    def test_the_next_day_fires_again(self):
        self.make_schedule()
        loop.tick(datetime(2026, 11, 27, 9, 0))
        self.finish_all_tasks()

        self.assertEqual(1, len(loop.tick(datetime(2026, 11, 28, 9, 0))))

    def test_a_paused_schedule_is_never_due(self):
        schedule_id = self.make_schedule()
        self.store.update_schedule(schedule_id, enabled=False)

        self.assertEqual([], loop.tick(datetime(2026, 11, 27, 9, 0)))

    def test_a_hand_edited_expression_is_skipped_not_fatal(self):
        """The write path refuses these; a row edited by hand must not stop the clock."""
        self.make_schedule(cron="not a cron")

        self.assertEqual([], loop.tick(datetime(2026, 11, 27, 9, 0)))


if __name__ == "__main__":
    unittest.main()

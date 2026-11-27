"""The scheduled task API: definitions, the pause switch, run history and live runs.

The interesting parts are the ones a UI depends on: an invalid cron is refused before
it is stored, pausing takes effect on the next read, "run now" produces a session, a
task and a run record, and the live list only shows work that is actually in flight.

Run from the repository root::

    uv run python test/schedule_api_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agent.runtime import launcher  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402

PROMPT = "summarise the open issues and post the digest"


class ScheduleApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = state.monitor_store
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        state.monitor_store = self.store
        # The scheduler thread is not started (the app's lifespan is not run here),
        # and a launched task must not call a model: the tests assert on records.
        self._run_patch = mock.patch.object(launcher, "run_task")
        self.run_task = self._run_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self._run_patch.stop()
        state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    # ----------------------------------------------------------------- helpers

    def create(self, **overrides):
        payload = {"cron": "0 9 * * *", "prompt": PROMPT, "name": "Morning digest"}
        payload.update(overrides)
        return self.client.post("/api/schedules", json=payload)

    def created(self, **overrides):
        response = self.create(**overrides)
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    # -------------------------------------------------------------- definitions

    def test_a_schedule_is_created_with_a_computed_next_run(self):
        body = self.created()

        self.assertEqual("0 9 * * *", body["cron"])
        self.assertTrue(body["enabled"])
        self.assertTrue(body["recurring"])
        self.assertIsNotNone(body["next_run_at"])
        self.assertEqual("build", body["agent_id"])
        self.assertEqual(body["schedule_id"], self.client.get("/api/schedules").json()["schedules"][0]["schedule_id"])

    def test_an_invalid_cron_is_refused_before_it_is_stored(self):
        response = self.create(cron="0 25 * * *")

        self.assertEqual(400, response.status_code)
        self.assertIn("cron", response.json()["detail"].lower())
        self.assertEqual([], self.client.get("/api/schedules").json()["schedules"])

    def test_an_empty_prompt_is_refused(self):
        response = self.create(prompt="   ")

        self.assertEqual(400, response.status_code)

    def test_an_unknown_agent_model_or_workspace_is_refused(self):
        self.assertEqual(400, self.create(agent_id="nope").status_code)
        self.assertEqual(400, self.create(model_id="nope").status_code)
        self.assertEqual(400, self.create(workspace_id="nope").status_code)

    def test_an_empty_name_falls_back_to_the_prompt(self):
        body = self.created(name="")

        self.assertEqual(PROMPT[:40], body["name"])

    def test_pausing_and_resuming_takes_effect_on_the_next_read(self):
        schedule_id = self.created()["schedule_id"]

        paused = self.client.put(f"/api/schedules/{schedule_id}", json={"enabled": False}).json()
        self.assertFalse(paused["enabled"])
        # A paused schedule has no next run; leaving one on screen would be a lie.
        self.assertIsNone(paused["next_run_at"])

        resumed = self.client.put(f"/api/schedules/{schedule_id}", json={"enabled": True}).json()
        self.assertTrue(resumed["enabled"])
        self.assertIsNotNone(resumed["next_run_at"])

    def test_a_partial_update_leaves_the_rest_of_the_definition_alone(self):
        body = self.created()

        updated = self.client.put(
            f"/api/schedules/{body['schedule_id']}", json={"name": "Renamed"}
        ).json()

        self.assertEqual("Renamed", updated["name"])
        self.assertEqual(body["cron"], updated["cron"])
        self.assertEqual(body["prompt"], updated["prompt"])

    def test_an_update_with_a_bad_cron_is_refused(self):
        body = self.created()

        response = self.client.put(f"/api/schedules/{body['schedule_id']}", json={"cron": "* * *"})

        self.assertEqual(400, response.status_code)

    def test_deleting_removes_the_schedule_and_its_runs(self):
        body = self.created()
        self.client.post(f"/api/schedules/{body['schedule_id']}/run")

        self.assertEqual(200, self.client.delete(f"/api/schedules/{body['schedule_id']}").status_code)
        self.assertEqual(404, self.client.get(f"/api/schedules/{body['schedule_id']}").status_code)
        self.assertEqual([], self.client.get("/api/schedules/running").json()["tasks"])

    def test_an_unknown_schedule_answers_404(self):
        self.assertEqual(404, self.client.get("/api/schedules/missing").status_code)
        self.assertEqual(404, self.client.delete("/api/schedules/missing").status_code)
        self.assertEqual(404, self.client.post("/api/schedules/missing/run").status_code)

    # --------------------------------------------------------------------- runs

    def test_run_now_creates_a_session_then_a_task_and_records_the_attempt(self):
        body = self.created()

        run = self.client.post(f"/api/schedules/{body['schedule_id']}/run").json()

        self.assertEqual("manual", run["trigger"])
        self.assertEqual("started", run["status"])
        self.assertEqual("running", run["task_status"])
        self.assertNotEqual("", run["session_id"])
        # The run's session owns exactly the task the run created: session first.
        session = self.store.get_session(run["session_id"])
        self.assertEqual(1, session["task_count"])
        self.assertEqual(PROMPT, self.store.get_task(run["task_id"])["query"])

    def test_a_paused_schedule_can_still_be_run_by_hand(self):
        body = self.created()
        self.client.put(f"/api/schedules/{body['schedule_id']}", json={"enabled": False})

        run = self.client.post(f"/api/schedules/{body['schedule_id']}/run").json()

        self.assertEqual("started", run["status"])

    def test_the_run_history_is_newest_first(self):
        body = self.created()
        first = self.client.post(f"/api/schedules/{body['schedule_id']}/run").json()
        self.store.finish_task(first["task_id"], success=True, result="done")
        second = self.client.post(f"/api/schedules/{body['schedule_id']}/run").json()

        runs = self.client.get(f"/api/schedules/{body['schedule_id']}/runs").json()["runs"]

        self.assertEqual([second["run_id"], first["run_id"]], [run["run_id"] for run in runs])
        self.assertEqual(["running", "success"], [run["task_status"] for run in runs])

    def test_a_run_that_could_not_start_a_task_is_visible_in_the_history(self):
        # Written straight to the store: the create path refuses an unknown model,
        # so "the model was deleted afterwards" is how a real schedule gets here.
        broken_id = self.store.create_schedule(
            cron="* * * * *", prompt=PROMPT, model_id="model-that-is-gone"
        )

        run = self.client.post(f"/api/schedules/{broken_id}/run").json()

        self.assertEqual("failed", run["status"])
        self.assertIn("Model not found", run["error"])
        history = self.client.get(f"/api/schedules/{broken_id}/runs").json()["runs"]
        self.assertEqual(["failed"], [item["status"] for item in history])

    def test_the_running_list_shows_only_work_in_flight(self):
        body = self.created()

        self.assertEqual([], self.client.get("/api/schedules/running").json()["tasks"])

        run = self.client.post(f"/api/schedules/{body['schedule_id']}/run").json()
        running = self.client.get("/api/schedules/running").json()["tasks"]
        self.assertEqual([run["run_id"]], [item["run_id"] for item in running])

        self.store.finish_task(run["task_id"], success=True, result="done")
        self.assertEqual([], self.client.get("/api/schedules/running").json()["tasks"])

    def test_a_schedule_that_has_a_run_in_flight_reports_itself_as_running(self):
        body = self.created()
        self.client.post(f"/api/schedules/{body['schedule_id']}/run")

        listed = self.client.get("/api/schedules").json()["schedules"][0]

        self.assertTrue(listed["running"])
        self.assertEqual("started", listed["last_run_status"])


class SchedulerLifecycleTest(unittest.TestCase):
    """The clock is the app's, not a request's: started by the lifespan, stopped by it.

    Without this the feature would still pass every other test and never fire, because
    nothing else calls ``start_scheduler``.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = state.monitor_store
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        state.monitor_store = self.store

    def tearDown(self):
        state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    def test_the_lifespan_starts_and_stops_the_scheduler(self):
        from agent.runtime.scheduling import loop

        self.assertFalse(loop.is_running())
        with TestClient(main.app):
            self.assertTrue(loop.is_running())
        self.assertFalse(loop.is_running())


if __name__ == "__main__":
    unittest.main()

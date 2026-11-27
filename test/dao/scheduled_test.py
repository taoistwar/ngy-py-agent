"""The scheduled-task store: what a row holds, what an update may touch, and how an
existing database picks up a column added later.

Run from the repository root::

    uv run python test/dao/scheduled_test.py -v
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dao import _SqliteTaskStore  # noqa: E402
from dao.scheduled import RUN_FAILED, RUN_STARTED, TRIGGER_MANUAL  # noqa: E402


class ScheduleStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = Path(self._tmp.name) / "tasks.db"
        self.store = _SqliteTaskStore(self._db_path)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def create(self, **overrides):
        payload = {"cron": "0 9 * * *", "prompt": "summarise the inbox", "name": "Inbox"}
        payload.update(overrides)
        return self.store.create_schedule(**payload)

    def test_a_new_schedule_follows_the_global_permission_mode(self):
        schedule = self.store.get_schedule(self.create())

        self.assertEqual("", schedule["permission_mode"])
        self.assertTrue(schedule["enabled"])
        self.assertTrue(schedule["recurring"])
        self.assertEqual("", schedule["last_fired"])

    def test_the_pinned_permission_mode_round_trips(self):
        schedule = self.store.get_schedule(self.create(permission_mode="auto_approve"))

        self.assertEqual("auto_approve", schedule["permission_mode"])

    def test_an_update_can_pin_and_unpin_the_mode(self):
        schedule_id = self.create()

        self.store.update_schedule(schedule_id, permission_mode="deny_all")
        self.assertEqual("deny_all", self.store.get_schedule(schedule_id)["permission_mode"])

        self.store.update_schedule(schedule_id, permission_mode="")
        self.assertEqual("", self.store.get_schedule(schedule_id)["permission_mode"])

    def test_an_update_cannot_write_the_fire_marker(self):
        schedule_id = self.create()

        self.store.update_schedule(schedule_id, last_fired="2026-11-27 09:00")

        self.assertEqual("", self.store.get_schedule(schedule_id)["last_fired"])

    def test_the_fire_marker_is_claimed_once_per_minute(self):
        schedule_id = self.create()

        self.assertTrue(self.store.claim_schedule_fire(schedule_id, "2026-11-27 09:00"))
        self.assertFalse(self.store.claim_schedule_fire(schedule_id, "2026-11-27 09:00"))
        self.assertTrue(self.store.claim_schedule_fire(schedule_id, "2026-11-27 09:01"))

    def test_a_paused_schedule_is_not_in_the_due_list(self):
        paused = self.create()
        due = self.create(name="Due")
        self.store.update_schedule(paused, enabled=False)

        self.assertEqual([due], [item["schedule_id"] for item in self.store.list_enabled_schedules()])

    def test_a_run_records_the_launch_outcome_and_reads_the_task_status_back(self):
        schedule_id = self.create()
        session_id = self.store.create_session("run")
        task_id = self.store.create_task("summarise the inbox", "openai", session_id=session_id)

        run = self.store.create_schedule_run(
            schedule_id, TRIGGER_MANUAL, session_id=session_id, task_id=task_id
        )

        self.assertEqual(RUN_STARTED, run["status"])
        self.assertEqual("running", run["task_status"])
        self.assertEqual("summarise the inbox", run["task_query"])
        self.assertEqual("Inbox", run["schedule_name"])

    def test_a_failed_run_has_no_task_and_keeps_its_error(self):
        schedule_id = self.create()

        run = self.store.create_schedule_run(
            schedule_id, TRIGGER_MANUAL, status=RUN_FAILED, error="Model not found."
        )

        self.assertEqual("", run["task_id"])
        self.assertIsNone(run["task_status"])
        self.assertEqual("Model not found.", run["error"])

    def test_deleting_a_schedule_keeps_the_tasks_its_runs_created(self):
        schedule_id = self.create()
        session_id = self.store.create_session("run")
        task_id = self.store.create_task("do it", "openai", session_id=session_id)
        self.store.create_schedule_run(schedule_id, TRIGGER_MANUAL, task_id=task_id)

        self.store.delete_schedule(schedule_id)

        self.assertEqual([], self.store.list_schedule_runs(schedule_id))
        self.assertIsNotNone(self.store.get_task(task_id))


class ScheduleMigrationTest(unittest.TestCase):
    """A database written before ``permission_mode`` existed must keep working."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = Path(self._tmp.name) / "tasks.db"
        connection = sqlite3.connect(self._db_path)
        connection.execute(
            """
            CREATE TABLE schedules (
                schedule_id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                cron TEXT NOT NULL,
                prompt TEXT NOT NULL,
                agent_id TEXT NOT NULL DEFAULT 'build',
                model_id TEXT,
                workspace_id TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                recurring INTEGER NOT NULL DEFAULT 1,
                last_fired TEXT,
                last_run_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO schedules (
                schedule_id, name, cron, prompt, agent_id, enabled, recurring,
                created_at, updated_at
            ) VALUES ('old-row', 'Old', '0 9 * * *', 'do it', 'build', 1, 1,
                      '2026-11-01T00:00:00+00:00', '2026-11-01T00:00:00+00:00')
            """
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_column_is_added_and_the_existing_row_follows_the_global_mode(self):
        store = _SqliteTaskStore(self._db_path)
        self.addCleanup(store.close)

        schedule = store.get_schedule("old-row")

        self.assertEqual("Old", schedule["name"])
        self.assertEqual("", schedule["permission_mode"])


if __name__ == "__main__":
    unittest.main()

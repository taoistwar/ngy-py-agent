"""Forking a session at one of its tasks.

A fork copies the chosen task and every task before it into a new session, so the
branch continues from the same conversation while the original session keeps its
own turns. The tests pin the copy (order, names, events, results), the fact that the
original is untouched, and the API's refusals.

Run from the repository root::

    uv run python test/task_fork_test.py -v
"""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import HTTPException  # noqa: E402

import session_history  # noqa: E402
from agent.models import EventCategory, TaskEvent, TaskStatus  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402
from routes import task_api  # noqa: E402


class ForkSessionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        self._previous_store = state.monitor_store
        state.monitor_store = self.store
        self.session_id = self.store.create_session("original")

    def tearDown(self):
        state.monitor_store = self._previous_store
        self._tmp.cleanup()

    def _task(self, query: str, created_at: str, result: str = "") -> str:
        """Create a finished task with a pinned creation time (order is not luck)."""
        task_id = self.store.create_task(query, "openai", session_id=self.session_id)
        self.store._conn.execute(
            "UPDATE tasks SET created_at = ? WHERE task_id = ?",
            (created_at, task_id),
        )
        self.store._conn.commit()
        self.store.finish_task(task_id, success=True, result=result)
        return task_id

    def _three_tasks(self) -> list[str]:
        return [
            self._task("first", "2026-11-16T01:00:00+00:00", "did the first"),
            self._task("second", "2026-11-16T02:00:00+00:00", "did the second"),
            self._task("third", "2026-11-16T03:00:00+00:00", "did the third"),
        ]

    def test_the_branch_copies_the_task_and_every_earlier_one(self):
        _, second, _ = self._three_tasks()

        forked = self.store.fork_session_through_task(second)

        branch = self.store.list_tasks(session_id=forked["session_id"])
        self.assertEqual(["first", "second"], [task["query"] for task in branch])
        self.assertEqual(second, forked["source_task_id"])
        self.assertEqual(2, forked["copied_task_count"])

    def test_the_original_session_keeps_all_its_tasks(self):
        _, second, _ = self._three_tasks()

        self.store.fork_session_through_task(second)

        self.assertEqual(
            ["first", "second", "third"],
            [task["query"] for task in self.store.list_tasks(session_id=self.session_id)],
        )

    def test_the_branch_is_named_after_the_task_it_branches_at(self):
        _, second, _ = self._three_tasks()
        self.store.set_task_name(second, "second task")

        forked = self.store.fork_session_through_task(second)

        self.assertEqual("second task", self.store.get_session(forked["session_id"])["name"])

    def test_an_unnamed_task_falls_back_to_its_query(self):
        _, second, _ = self._three_tasks()

        forked = self.store.fork_session_through_task(second)

        self.assertEqual("second", forked["name"])

    def test_the_branch_carries_the_conversation_as_history(self):
        _, second, _ = self._three_tasks()

        forked = self.store.fork_session_through_task(second)

        self.assertEqual(
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "did the first"},
                {"role": "user", "content": "second"},
                {"role": "assistant", "content": "did the second"},
            ],
            session_history.build_session_history(forked["session_id"]),
        )

    def test_the_forked_task_is_the_branch_tip(self):
        _, second, _ = self._three_tasks()

        forked = self.store.fork_session_through_task(second)

        branch = self.store.list_tasks(session_id=forked["session_id"])
        self.assertEqual(forked["task_id"], branch[-1]["task_id"])
        self.assertEqual("second", branch[-1]["query"])

    def test_events_are_copied_with_new_ids(self):
        first, second, _ = self._three_tasks()
        self.store.append_event(
            first,
            TaskEvent(
                task_id=first,
                category=EventCategory.DEBUG,
                title="first step",
                data={"step": 1},
            ),
        )

        forked = self.store.fork_session_through_task(second)

        branch = self.store.list_tasks(session_id=forked["session_id"])
        copied = self.store.get_task(branch[0]["task_id"])
        original = self.store.get_task(first)
        self.assertEqual(1, len(copied["events"]))
        self.assertEqual("first step", copied["events"][0]["title"])
        self.assertEqual({"step": 1}, copied["events"][0]["data"])
        self.assertNotEqual(original["events"][0]["event_id"], copied["events"][0]["event_id"])

    def test_a_running_copy_is_not_left_in_flight(self):
        # The startup recovery scan resumes running/waiting rows; a copy must not be
        # picked up and run a second time.
        task_id = self.store.create_task("in flight", "openai", session_id=self.session_id)
        self.store.set_task_status(task_id, TaskStatus.WAITING)

        forked = self.store.fork_session_through_task(task_id)

        copied = self.store.list_tasks(session_id=forked["session_id"])
        self.assertEqual(TaskStatus.STOPPED.value, copied[0]["status"])
        self.assertEqual(
            [task_id],
            [task["task_id"] for task in self.store.list_unfinished_tasks()],
        )

    def test_forking_a_missing_task_returns_none(self):
        self.assertIsNone(self.store.fork_session_through_task("missing-task"))


class ForkTaskApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        self._previous_store = state.monitor_store
        state.monitor_store = self.store
        self.session_id = self.store.create_session("original")

    def tearDown(self):
        state.monitor_store = self._previous_store
        self._tmp.cleanup()

    def _finished_task(self, query: str) -> str:
        task_id = self.store.create_task(query, "openai", session_id=self.session_id)
        self.store.finish_task(task_id, success=True, result=f"did {query}")
        return task_id

    def test_the_route_returns_the_new_session_and_its_task(self):
        self._finished_task("first")
        second = self._finished_task("second")

        response = asyncio.run(task_api.fork_task(second))

        self.assertEqual(["first", "second"], [t["query"] for t in self.store.list_tasks(response.session_id)])
        self.assertEqual(2, response.copied_task_count)
        self.assertEqual(second, response.source_task_id)
        self.assertEqual("second", response.session.name)
        self.assertEqual(2, response.session.task_count)

    def test_a_running_task_is_refused(self):
        task_id = self.store.create_task("still running", "openai", session_id=self.session_id)

        with self.assertRaises(HTTPException) as caught:
            asyncio.run(task_api.fork_task(task_id))

        self.assertEqual(409, caught.exception.status_code)

    def test_a_missing_task_is_a_404(self):
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(task_api.fork_task("missing-task"))

        self.assertEqual(404, caught.exception.status_code)


if __name__ == "__main__":
    unittest.main()

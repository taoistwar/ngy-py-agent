"""Integration tests for the question endpoints (ADR 0010).

What the unit tests cannot reach: the endpoint that unblocks a parked task thread, the
``pending_question`` field the UI renders from, and the status the two new event
categories put a task in.

Run from the repository root::

    uv run python test/question_api_test.py -v
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import app_state  # noqa: E402
import main  # noqa: E402
from agent.models import EventCategory, TaskStatus  # noqa: E402
from agent.tools.user_question import (  # noqa: E402
    STATUS_ANSWERED,
    UserQuestionBroker,
)
from task_store import _SqliteTaskStore  # noqa: E402

WAIT_SECONDS = 30.0

QUESTIONS = [
    {
        "id": "approach",
        "header": "Approach",
        "question": "Which way should I take?",
        "options": [{"label": "Rewrite (Recommended)"}, {"label": "Patch it"}],
    },
    {
        "id": "scope",
        "header": "Scope",
        "question": "How wide should the change be?",
        "options": [{"label": "Minimal"}],
    },
]


class QuestionApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        # The live state is ``app_state``'s, not ``main``'s: the routes read it there,
        # so that is where a test has to swap it (see app_state's module docstring).
        self._previous_store = app_state.monitor_store
        self.store = _SqliteTaskStore(root / "tasks.db")
        app_state.monitor_store = self.store
        self.client = TestClient(main.app)

    def tearDown(self):
        with app_state._task_question_lock:
            app_state._task_question_brokers.clear()
        app_state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    # ------------------------------------------------------------------ helpers

    def register_broker(self, task_id="task-1"):
        broker = UserQuestionBroker(task_id=task_id, wait_seconds=WAIT_SECONDS)
        app_state.register_task_questions(task_id, broker)
        return broker

    def park(self, broker):
        """Ask in a thread, returning once the request is pending."""
        box = {}

        def runner():
            box["result"] = broker.ask(QUESTIONS)

        thread = threading.Thread(target=runner)
        thread.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            pending = broker.pending()
            if pending is not None:
                return thread, box, pending
            time.sleep(0.01)
        raise AssertionError("the broker never asked")

    def answer(self, task_id, request_id, answers=None):
        body = {"answers": answers if answers is not None else {"approach": {"answers": ["Patch it"]}}}
        return self.client.post(f"/api/tasks/{task_id}/question/{request_id}", json=body)

    # ----------------------------------------------------------------- answers

    def test_unknown_task_is_not_found(self):
        response = self.answer("nope", "abc")

        self.assertEqual(response.status_code, 404)

    def test_answering_unblocks_the_waiting_thread(self):
        broker = self.register_broker()
        thread, box, pending = self.park(broker)

        response = self.answer(
            "task-1",
            pending.request_id,
            {"approach": {"answers": ["Patch it", "only the parser"]}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], STATUS_ANSWERED)
        self.assertEqual(response.json()["answered_count"], 1)
        thread.join(timeout=5.0)
        result = box["result"]
        self.assertEqual(result.status, STATUS_ANSWERED)
        self.assertEqual(
            result.answers, {"approach": {"answers": ["Patch it", "only the parser"]}}
        )
        self.assertIsNone(broker.pending())

    def test_a_skipped_question_may_be_omitted(self):
        broker = self.register_broker()
        thread, box, pending = self.park(broker)

        response = self.answer("task-1", pending.request_id, {})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answered_count"], 0)
        thread.join(timeout=5.0)
        self.assertEqual(box["result"].answers, {})

    def test_an_unknown_question_id_is_refused_rather_than_dropped(self):
        broker = self.register_broker()
        thread, box, pending = self.park(broker)

        response = self.answer("task-1", pending.request_id, {"never-asked": {"answers": ["x"]}})

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown question id", response.json()["detail"])
        # Refused rather than applied: the task is still parked and gets the real answer.
        self.assertIsNotNone(broker.pending())
        self.answer("task-1", pending.request_id)
        thread.join(timeout=5.0)

    def test_a_non_string_answer_is_refused(self):
        broker = self.register_broker()
        thread, _, pending = self.park(broker)

        response = self.answer("task-1", pending.request_id, {"approach": {"answers": [1]}})

        self.assertEqual(response.status_code, 400)
        self.assertIn("only strings", response.json()["detail"])
        self.answer("task-1", pending.request_id)
        thread.join(timeout=5.0)

    def test_answering_twice_is_a_conflict(self):
        broker = self.register_broker()
        thread, _, pending = self.park(broker)
        self.answer("task-1", pending.request_id)
        thread.join(timeout=5.0)

        again = self.answer("task-1", pending.request_id)

        self.assertEqual(again.status_code, 409)

    def test_a_request_id_that_is_not_the_pending_one_is_a_conflict(self):
        broker = self.register_broker()
        thread, _, _ = self.park(broker)

        response = self.answer("task-1", "some-other-request")

        self.assertEqual(response.status_code, 409)
        self.answer("task-1", broker.pending().request_id)
        thread.join(timeout=5.0)

    # --------------------------------------------------------- waiting visibility

    def test_task_detail_and_list_expose_the_pending_question(self):
        task_id = app_state.monitor_store.create_task("do something", "openai-compatible")
        broker = self.register_broker(task_id=task_id)
        thread, _, pending = self.park(broker)

        detail = self.client.get(f"/api/tasks/{task_id}").json()
        self.assertEqual(detail["pending_question"]["request_id"], pending.request_id)
        # The client renders from this, so it has to carry the questions themselves.
        self.assertEqual(
            [item["id"] for item in detail["pending_question"]["questions"]],
            ["approach", "scope"],
        )
        self.assertTrue(detail["pending_question"]["questions"][0]["is_other"])

        listed = self.client.get("/api/tasks").json()["tasks"]
        item = [entry for entry in listed if entry["task_id"] == task_id][0]
        self.assertEqual(item["pending_question"]["request_id"], pending.request_id)

        self.answer(task_id, pending.request_id)
        thread.join(timeout=5.0)
        self.assertIsNone(self.client.get(f"/api/tasks/{task_id}").json()["pending_question"])

    def test_both_channels_flip_the_task_status(self):
        # The mapping both brokers rely on: parked -> waiting, answered -> running.
        self.assertEqual(
            app_state.status_for_event(EventCategory.USER_QUESTION), TaskStatus.WAITING
        )
        self.assertEqual(app_state.status_for_event(EventCategory.USER_ANSWER), TaskStatus.RUNNING)
        self.assertEqual(
            app_state.status_for_event(EventCategory.PERMISSION_REQUEST), TaskStatus.WAITING
        )
        self.assertEqual(
            app_state.status_for_event(EventCategory.PERMISSION_DECISION), TaskStatus.RUNNING
        )
        # Anything else leaves the status alone.
        self.assertIsNone(app_state.status_for_event(EventCategory.TOOL_CALL))


if __name__ == "__main__":
    unittest.main()

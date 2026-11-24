"""Tests for the question channel (ADR 0010).

The properties worth pinning are the ones that differ from the permission gate: the wait
has **no deadline**, a stop releases it, and the two brokers cannot answer for each
other.

Run from the repository root::

    uv run python test/tools/user_question_test.py -v
"""

import sys
import threading
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.user_question import (  # noqa: E402
    STATUS_ANSWERED,
    STATUS_STOPPED,
    UserQuestionBroker,
    UserQuestionRequest,
    validate_answers,
)

QUESTIONS = [
    {
        "id": "approach",
        "header": "Approach",
        "question": "Which way should I take?",
        "options": [{"label": "Rewrite (Recommended)", "description": "Cleaner"}],
    },
    {
        "id": "scope",
        "header": "Scope",
        "question": "How wide should the change be?",
        "options": [{"label": "Minimal", "description": "Small diff"}],
    },
]


def wait_for(predicate, deadline_seconds=5.0) -> bool:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class BrokerTest(unittest.TestCase):
    def setUp(self):
        self.events = []

    def make_broker(self, **kwargs):
        kwargs.setdefault("task_id", "task-1")
        kwargs.setdefault("emit", self.emit)
        return UserQuestionBroker(**kwargs)

    def emit(self, category, title, data):
        self.events.append((category, title, data))

    def park(self, broker, questions=None):
        """Ask in a thread; return the thread and its result box once the ask is pending."""
        box = {}

        def runner():
            box["result"] = broker.ask(questions or QUESTIONS)

        # Daemon: a failed assertion must not leave a thread parked forever and wedge
        # the test process now that the wait has no deadline.
        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        self.assertTrue(wait_for(lambda: broker.pending() is not None), "the broker never asked")
        return thread, box

    # ------------------------------------------------------------------ asking

    def test_the_answer_that_arrives_is_the_answer_that_comes_back(self):
        broker = self.make_broker()
        thread, box = self.park(broker)
        request_id = broker.pending().request_id

        self.assertTrue(broker.resolve(request_id, {"approach": {"answers": ["Rewrite (Recommended)"]}}))
        thread.join(5)

        result = box["result"]
        self.assertEqual(result.status, STATUS_ANSWERED)
        self.assertTrue(result.answered)
        self.assertEqual(result.answers, {"approach": {"answers": ["Rewrite (Recommended)"]}})
        self.assertEqual(result.note(), "")
        self.assertEqual(result.response(), {"answers": result.answers})

    def test_both_events_carry_the_request_and_the_answer(self):
        broker = self.make_broker()
        thread, _ = self.park(broker)
        broker.resolve(broker.pending().request_id, {"scope": {"answers": ["Minimal"]}})
        thread.join(5)

        categories = [category for category, _, _ in self.events]
        self.assertEqual(categories, ["user_question", "user_answer"])

        request_payload = self.events[0][2]
        self.assertEqual(request_payload["task_id"], "task-1")
        self.assertEqual([item["id"] for item in request_payload["questions"]], ["approach", "scope"])
        # The free-form row is the client's to add, so every question advertises it.
        self.assertTrue(all(item["is_other"] for item in request_payload["questions"]))

        answer_payload = self.events[1][2]
        self.assertEqual(answer_payload["status"], STATUS_ANSWERED)
        self.assertEqual(answer_payload["answered_count"], 1)
        self.assertEqual(answer_payload["question_count"], 2)
        self.assertEqual(answer_payload["request_id"], request_payload["request_id"])

    # ------------------------------------------------------------ the long wait

    def test_the_wait_has_no_deadline(self):
        # Longer than any polling tick: the call must still be parked, not answered
        # on the user's behalf by a timer (ADR 0010 D2, revised).
        broker = self.make_broker()
        thread, box = self.park(broker)

        time.sleep(0.6)

        self.assertTrue(thread.is_alive())
        self.assertIsNotNone(broker.pending())
        self.assertNotIn("result", box)

        request_id = broker.pending().request_id
        self.assertTrue(broker.resolve(request_id, {"approach": {"answers": ["Patch it"]}}))
        thread.join(5)

        self.assertEqual(box["result"].status, STATUS_ANSWERED)
        self.assertEqual(box["result"].answers, {"approach": {"answers": ["Patch it"]}})

    def test_a_stop_releases_the_wait(self):
        broker = self.make_broker(should_stop=lambda: True)

        started = time.monotonic()
        result = broker.ask(QUESTIONS)

        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(result.status, STATUS_STOPPED)
        self.assertIn("stopped", result.note())

    def test_cancel_all_releases_the_waiter_without_calling_it_answered(self):
        broker = self.make_broker()
        thread, box = self.park(broker)

        broker.cancel_all()
        thread.join(5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(box["result"].status, STATUS_STOPPED)
        self.assertEqual(box["result"].answers, {})

    def test_resolving_something_that_is_not_pending_is_false(self):
        broker = self.make_broker()

        self.assertFalse(broker.resolve("nope", {}))
        self.assertIsNone(broker.pending())

    # ------------------------------------------------------------- answer body

    def test_answers_are_checked_against_the_questions_that_were_asked(self):
        request = UserQuestionRequest(request_id="r", task_id="t", questions=tuple(QUESTIONS))

        answers, error = validate_answers(request, {"answers": {"approach": {"answers": ["A"]}}})
        self.assertIsNone(error)
        self.assertEqual(answers, {"approach": {"answers": ["A"]}})

        _, error = validate_answers(request, {"answers": {"never-asked": {"answers": ["x"]}}})
        self.assertIn("Unknown question id", error)

        _, error = validate_answers(request, {"answers": {"approach": {"answers": [1]}}})
        self.assertIn("only strings", error)

        _, error = validate_answers(request, {"answers": {"approach": "A"}})
        self.assertIn("must be an object", error)

        _, error = validate_answers(request, "not a body")
        self.assertIn("JSON object", error)

    def test_a_skipped_question_is_allowed_to_be_absent_or_empty(self):
        request = UserQuestionRequest(request_id="r", task_id="t", questions=tuple(QUESTIONS))

        partial, error = validate_answers(request, {"answers": {"approach": {"answers": []}}})
        self.assertIsNone(error)
        self.assertEqual(partial, {"approach": {"answers": []}})

        empty, error = validate_answers(request, {})
        self.assertIsNone(error)
        self.assertEqual(empty, {})


if __name__ == "__main__":
    unittest.main()

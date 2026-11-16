"""What a new task in a session inherits from the tasks already there.

A finished task is one turn: its query is the user message and its result is the
assistant message. Unfinished, failed and stopped tasks are not turns, other
sessions are not context, and a budget too small for everything keeps the newest
turns rather than the oldest.

Run from the repository root::

    uv run python test/session_history_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import session_history  # noqa: E402
from agent.models import TaskStatus  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402


class SessionHistoryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        self._previous_store = state.monitor_store
        state.monitor_store = self.store
        self.session_id = self.store.create_session("conversation")

    def tearDown(self):
        state.monitor_store = self._previous_store
        self._tmp.cleanup()

    def _finished_task(self, query: str, result: str, session_id: str | None = None) -> str:
        task_id = self.store.create_task(
            query, "openai", session_id=session_id or self.session_id
        )
        self.store.finish_task(task_id, success=True, result=result)
        return task_id

    def test_an_empty_session_has_no_history(self):
        self.assertEqual([], session_history.build_session_history(self.session_id))

    def test_no_session_has_no_history(self):
        self._finished_task("create add()", "created add()")

        self.assertEqual([], session_history.build_session_history(None))

    def test_a_finished_task_is_one_user_and_one_assistant_message(self):
        self._finished_task("create add()", "created add()")

        self.assertEqual(
            [
                {"role": "user", "content": "create add()"},
                {"role": "assistant", "content": "created add()"},
            ],
            session_history.build_session_history(self.session_id),
        )

    def test_turns_are_oldest_first(self):
        self._finished_task("first", "answer one")
        self._finished_task("second", "answer two")

        contents = [
            message["content"] for message in session_history.build_session_history(self.session_id)
        ]

        self.assertEqual(["first", "answer one", "second", "answer two"], contents)

    def test_a_running_task_is_not_context(self):
        self.store.create_task("still running", "openai", session_id=self.session_id)

        self.assertEqual([], session_history.build_session_history(self.session_id))

    def test_a_failed_task_is_not_context(self):
        task_id = self.store.create_task("failed", "openai", session_id=self.session_id)
        self.store.finish_task(task_id, success=False)

        self.assertEqual([], session_history.build_session_history(self.session_id))

    def test_a_stopped_task_is_not_context(self):
        task_id = self.store.create_task("stopped", "openai", session_id=self.session_id)
        self.store.finish_task(
            task_id, success=False, result="Task stopped by user.", status=TaskStatus.STOPPED
        )

        self.assertEqual([], session_history.build_session_history(self.session_id))

    def test_a_reverted_task_is_not_context(self):
        """Its files are back to the baseline, so "it built X" is no longer true."""
        task_id = self.store.create_task("reverted", "openai", session_id=self.session_id)
        self.store.finish_task(task_id, success=True, result="Done.")
        self.store.set_task_status(task_id, TaskStatus.REVERTED)

        self.assertEqual([], session_history.build_session_history(self.session_id))

    def test_another_sessions_tasks_are_not_context(self):
        other_session = self.store.create_session("other")
        self._finished_task("elsewhere", "answering elsewhere", session_id=other_session)

        self.assertEqual([], session_history.build_session_history(self.session_id))

    def test_the_newest_turns_win_when_the_budget_is_small(self):
        self._finished_task("old question", "old answer")
        self._finished_task("new question", "new answer")

        history = session_history.build_session_history(self.session_id, max_chars=30)

        self.assertEqual(
            [
                {"role": "user", "content": "new question"},
                {"role": "assistant", "content": "new answer"},
            ],
            history,
        )

    def test_the_newest_turn_survives_a_budget_it_alone_exceeds(self):
        self._finished_task("only question", "only answer")

        history = session_history.build_session_history(self.session_id, max_chars=1)

        self.assertEqual(2, len(history))

    def test_the_message_cap_counts_messages(self):
        self._finished_task("old question", "old answer")
        self._finished_task("new question", "new answer")

        history = session_history.build_session_history(self.session_id, max_messages=2)

        self.assertEqual(["new question", "new answer"], [item["content"] for item in history])

    def test_a_huge_answer_is_clipped_instead_of_swallowing_the_budget(self):
        limit = session_history.MAX_MESSAGE_CHARS
        self._finished_task("long answer", "x" * (limit + 500))

        history = session_history.build_session_history(self.session_id)
        answer = history[1]["content"]

        self.assertLessEqual(len(answer), limit + len(session_history._TRUNCATION_NOTE))
        self.assertTrue(answer.endswith(session_history._TRUNCATION_NOTE))


if __name__ == "__main__":
    unittest.main()

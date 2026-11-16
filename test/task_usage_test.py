"""The price of a task, as the result pane prints it: total tokens and duration.

Both figures are read back from records the task already wrote - the provider's own
``usage`` block in each ``llm_response`` event, and the record's own timestamps - so
these cases pin what is summed (every turn, not the newest one), which events are
skipped (compaction summaries carry no usage), and where the clock comes from.

Run from the repository root::

    uv run python test/task_usage_test.py -v
"""

import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to the
# import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agent.models import EventCategory, TaskEvent  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402
from task_usage import elapsed_ms, sum_token_usage  # noqa: E402


def _response_event(input_tokens: int, output_tokens: int, *, usage: bool = True) -> dict:
    raw_response = {"object": "chat.completion"}
    if usage:
        raw_response["usage"] = {"prompt_tokens": input_tokens, "completion_tokens": output_tokens}
    return {"category": EventCategory.LLM_RESPONSE.value, "data": {"raw_response": raw_response}}


class SumTokenUsageTest(unittest.TestCase):
    def test_every_turn_is_counted_not_only_the_newest(self):
        events = [_response_event(100, 10), _response_event(250, 25)]

        counts = sum_token_usage(events)

        self.assertEqual(350, counts["input_tokens"])
        self.assertEqual(35, counts["output_tokens"])
        self.assertEqual(385, counts["total_tokens"])

    def test_anthropic_style_usage_reads_the_same_way(self):
        events = [
            {
                "category": EventCategory.LLM_RESPONSE.value,
                "data": {"raw_response": {"usage": {"input_tokens": 7, "output_tokens": 9}}},
            }
        ]

        counts = sum_token_usage(events)

        self.assertEqual((7, 9, 16), (counts["input_tokens"], counts["output_tokens"], counts["total_tokens"]))

    def test_other_categories_and_missing_usage_contribute_nothing(self):
        events = [
            {"category": EventCategory.LLM_REQUEST.value, "data": {"raw_response": {"usage": {"prompt_tokens": 5}}}},
            _response_event(0, 0, usage=False),
            {"category": EventCategory.LLM_RESPONSE.value},
            _response_event(12, 3),
        ]

        self.assertEqual(15, sum_token_usage(events)["total_tokens"])

    def test_no_events_read_as_zero(self):
        self.assertEqual(
            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            sum_token_usage(None),
        )


class ElapsedMsTest(unittest.TestCase):
    def test_aware_datetimes_are_differenced_in_milliseconds(self):
        start = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)

        self.assertEqual(2_500, elapsed_ms(start, start + timedelta(seconds=2.5)))

    def test_iso_strings_from_the_store_work_too(self):
        self.assertEqual(1_000, elapsed_ms("2026-11-16T12:00:00+00:00", "2026-11-16T12:00:01+00:00"))

    def test_a_mixed_naive_pair_is_still_differenced(self):
        self.assertEqual(1_000, elapsed_ms("2026-11-16T12:00:00", "2026-11-16T12:00:01+00:00"))

    def test_an_impossible_span_or_a_bad_value_reads_as_zero(self):
        start = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)

        self.assertEqual(0, elapsed_ms(start, start - timedelta(seconds=1)))
        self.assertEqual(0, elapsed_ms(None, start))
        self.assertEqual(0, elapsed_ms("not a time", start))


class TaskDetailApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = state.monitor_store
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        state.monitor_store = self.store
        self.client = TestClient(main.app)
        self.session_id = self.store.create_session("priced")

    def tearDown(self):
        state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    def _task(self) -> str:
        return self.store.create_task("measure me", "openai", session_id=self.session_id)

    def _append(self, task_id: str, category: EventCategory, data: dict, offset: timedelta) -> None:
        created_at = self.store.get_task(task_id)["created_at"]
        self.store.append_event(
            task_id,
            TaskEvent(
                task_id=task_id,
                timestamp=created_at + offset,
                category=category,
                title="event",
                data=data,
            ),
        )

    def test_the_detail_reports_the_runs_tokens_and_wall_clock_time(self):
        task_id = self._task()
        self._append(
            task_id,
            EventCategory.LLM_RESPONSE,
            {"step": 1, "raw_response": {"usage": {"prompt_tokens": 1_200, "completion_tokens": 350}}},
            timedelta(seconds=1),
        )
        self._append(
            task_id,
            EventCategory.LLM_RESPONSE,
            {"step": 2, "raw_response": {"usage": {"prompt_tokens": 1_800, "completion_tokens": 150}}},
            timedelta(seconds=4),
        )

        payload = self.client.get(f"/api/tasks/{task_id}").json()

        self.assertEqual(3_000, payload["input_tokens"])
        self.assertEqual(500, payload["output_tokens"])
        self.assertEqual(3_500, payload["total_tokens"])
        # The last event moved ``updated_at``; the clock runs from creation.
        self.assertEqual(4_000, payload["duration_ms"])

    def test_a_task_that_has_not_answered_yet_reports_zero_tokens(self):
        task_id = self._task()

        payload = self.client.get(f"/api/tasks/{task_id}").json()

        self.assertEqual(0, payload["total_tokens"])
        self.assertGreaterEqual(payload["duration_ms"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

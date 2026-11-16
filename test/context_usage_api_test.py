"""The context meter the composer shows: how full the model's window already is.

The figure is read back from the event log (the provider's own ``usage`` block), not
estimated from the transcript, so these cases pin *which* turn is read, what happens
when the newest turn has not answered yet, and where the denominator comes from.

Run from the repository root::

    uv run python test/context_usage_api_test.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import app_state  # noqa: E402
import main  # noqa: E402
from agent.models import EventCategory, TaskEvent  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402

WINDOW = 262_144
# 200,000 characters / 4, the loop's default budget when the model declares no window.
LOOP_DEFAULT_TOKENS = 50_000


class ContextUsageApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = app_state.monitor_store
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        app_state.monitor_store = self.store
        self.client = TestClient(main.app)
        self.session_id = self.store.create_session("meter")
        provider = self.store.llm.create_provider(
            {"name": "local", "protocol": "openai-compatible", "base_url": "", "api_key": ""}
        )
        self.model = self.store.llm.create_model(
            {
                "name": "big-window",
                "provider_id": provider["provider_id"],
                "max_input_tokens": WINDOW,
            }
        )
        # The default budget is environment-dependent; a test that asserts on it says
        # so instead of inheriting whatever the machine happens to export.
        self._env = patch.dict(os.environ, {"CONTEXT_CHAR_LIMIT": ""})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        app_state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    # ---------------------------------------------------------------- helpers

    def _task(self, query: str, model_id: str | None = None) -> str:
        return self.store.create_task(
            query,
            "openai",
            session_id=self.session_id,
            model_id=model_id if model_id is not None else self.model["model_id"],
        )

    def _usage(
        self,
        task_id: str,
        input_tokens: int,
        output_tokens: int,
        *,
        with_usage: bool = True,
    ) -> None:
        raw_response = {"object": "chat.completion"}
        if with_usage:
            raw_response["usage"] = {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
            }
        self.store.append_event(
            task_id,
            TaskEvent(
                task_id=task_id,
                category=EventCategory.LLM_RESPONSE,
                title="LLM response Step 1",
                data={"step": 1, "raw_response": raw_response},
            ),
        )

    def _get(self, session_id: str | None = None, model_id: str | None = None):
        url = f"/api/sessions/{session_id or self.session_id}/context"
        if model_id is not None:
            url = f"{url}?model_id={model_id}"
        return self.client.get(url)

    # ------------------------------------------------------------------ cases

    def test_a_fresh_session_reports_zero_and_the_model_window(self):
        response = self._get(model_id=self.model["model_id"])

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(0, payload["used_tokens"])
        self.assertEqual(WINDOW, payload["max_tokens"])
        self.assertEqual("model", payload["limit_source"])
        self.assertEqual(0.0, payload["percent"])

    def test_the_reading_comes_from_the_providers_own_token_counts(self):
        task_id = self._task("build the parser")
        self._usage(task_id, 12_000, 800)

        payload = self._get().json()

        self.assertEqual(12_000, payload["input_tokens"])
        self.assertEqual(800, payload["output_tokens"])
        self.assertEqual(12_800, payload["used_tokens"])
        self.assertEqual(4.9, payload["percent"])

    def test_the_newest_turn_wins(self):
        older = self._task("first")
        self._usage(older, 1_000, 100)
        newer = self._task("second")
        self._usage(newer, 40_000, 500)

        payload = self._get().json()

        self.assertEqual(40_500, payload["used_tokens"])

    def test_a_turn_that_has_not_answered_yet_reads_the_previous_turn(self):
        answered = self._task("first")
        self._usage(answered, 5_000, 200)
        # The worker thread has started but the model has not returned yet.
        self._task("second")

        payload = self._get().json()

        self.assertEqual(5_200, payload["used_tokens"])

    def test_a_summary_call_without_token_counts_does_not_hide_the_reading(self):
        task_id = self._task("compact me")
        self._usage(task_id, 7_000, 300)
        # ADR 0017 D9: the compaction summary is an ``llm_response`` with no payload,
        # so it carries no usage even though it is the newest event of that category.
        self._usage(task_id, 0, 0, with_usage=False)

        payload = self._get().json()

        self.assertEqual(7_300, payload["used_tokens"])

    def test_the_denominator_follows_the_model_the_composer_selected(self):
        small = self.store.llm.create_model(
            {
                "name": "small-window",
                "provider_id": self.model["provider_id"],
                "max_input_tokens": 8_192,
            }
        )
        task_id = self._task("build")
        self._usage(task_id, 4_096, 0)

        payload = self._get(model_id=small["model_id"]).json()

        self.assertEqual(8_192, payload["max_tokens"])
        self.assertEqual(50.0, payload["percent"])

    def test_a_model_without_a_window_falls_back_to_the_loops_budget(self):
        headless = self.store.llm.create_model(
            {"name": "no-window", "provider_id": self.model["provider_id"]}
        )
        task_id = self._task("build", model_id=headless["model_id"])
        self._usage(task_id, 5_000, 0)

        payload = self._get().json()

        self.assertEqual(LOOP_DEFAULT_TOKENS, payload["max_tokens"])
        self.assertEqual("loop", payload["limit_source"])
        self.assertEqual(10.0, payload["percent"])

    def test_an_unknown_session_is_a_404(self):
        self.assertEqual(404, self.client.get("/api/sessions/missing/context").status_code)

    def test_an_unknown_model_is_a_404(self):
        self.assertEqual(404, self._get(model_id="missing").status_code)


if __name__ == "__main__":
    unittest.main(verbosity=2)

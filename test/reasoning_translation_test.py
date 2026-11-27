"""Translating a task's reasoning traces into the language the console is read in.

Two behaviours are pinned here. The global setting: no translation model means no
translation at all, and a saved model is what the task endpoints use. The per-task
work: a trace is translated once per language and skipped afterwards, so a second
click (or the automatic pass after a finished task) costs no tokens.

The pass runs on a server thread, so the tests ask the reader endpoint until it says
``running`` is false - the same thing the console does.

The endpoint's RPM budget is the fourth: translation is a batch of model calls, so it
spends the same bucket the task loop does and stops asking when the minute is gone
instead of queueing a long row of waits (ADR 0013).

Run from the repository root::

    uv run python test/reasoning_translation_test.py -v
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agent.models import EventCategory, TaskEvent  # noqa: E402
from agent.rate_limit import RpmLimitError, bucket_key, provider_throttle  # noqa: E402
from agent.runtime import reasoning_translate  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402
from routes import admin_api  # noqa: E402

REASONING_ONE = "I should list the files first, then read test.py."
REASONING_TWO = "The directory looks empty, so the answer is a short note."


class _FakeProvider:
    """Answers every translation request with a recognisable form of the source."""

    def __init__(
        self,
        fail: bool = False,
        rpm_after: int | None = None,
        gate: threading.Event | None = None,
    ) -> None:
        self.calls = []
        self.fail = fail
        # Raises ``RpmLimitError`` from the N-th call on, i.e. the endpoint's minute
        # ran out mid-batch the way a real adapter reports it.
        self.rpm_after = rpm_after
        # Blocks the call until released, so a test can look at the API while the
        # background pass is still working.
        self.gate = gate

    def chat_completion(self, messages, tools=None, **kwargs):
        if self.gate is not None:
            self.gate.wait(5)
        if self.rpm_after is not None and len(self.calls) >= self.rpm_after:
            raise RpmLimitError("openai-compatible", "https://gateway.example/v1", 1, 120.0, 60.0)
        self.calls.append(list(messages))
        if self.fail:
            raise RuntimeError("provider is down")
        source = messages[-1]["content"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=f"[translated] {source}"))]
        )


class _TranslatorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = state.monitor_store
        self._previous_translation = (
            state.translation_model_id,
            state.translation_model_source,
        )
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        state.monitor_store = self.store
        state.translation_model_id = ""
        state.translation_model_source = "default"
        self.client = TestClient(main.app)
        self.provider = _FakeProvider()
        # A per-test base URL keeps this test's RPM bucket apart from the limiter's
        # process-wide memory of earlier tests' requests.
        self.base_url = f"https://gateway-{uuid4().hex}.example/v1"
        self.provider_record = self.store.llm.create_provider(
            {
                "name": "gateway",
                "protocol": "openai-compatible",
                "base_url": self.base_url,
                "api_key": "k",
            }
        )
        self.model = self.store.llm.create_model(
            {"name": "fast", "provider_id": self.provider_record["provider_id"]}
        )

    def tearDown(self):
        state.monitor_store = self._previous_store
        state.translation_model_id, state.translation_model_source = self._previous_translation
        # The limiter is a process-wide singleton; a test that configured a budget must
        # not leave it in force for the next one.
        provider_throttle.configure({})
        self.store.close()
        self._tmp.cleanup()

    def seed_task(self, reasonings):
        task_id = self.store.create_task(query="list files", provider="openai-compatible")
        for index, reasoning in enumerate(reasonings):
            self.store.append_event(
                task_id,
                TaskEvent(
                    task_id=task_id,
                    category=EventCategory.LLM_RESPONSE,
                    title=f"Step {index}",
                    data={"step": index, "reasoning": reasoning, "content": "ok"},
                ),
            )
        return task_id

    def translate(self, task_id, locale="zh-CN"):
        return self.client.post(
            f"/api/tasks/{task_id}/reasoning-translations", json={"locale": locale}
        )

    def read(self, task_id, locale="zh-CN"):
        return self.client.get(
            f"/api/tasks/{task_id}/reasoning-translations", params={"locale": locale}
        )

    def wait(self, task_id, locale="zh-CN", timeout=10.0):
        """The console's poll: read until the background pass reports it is done."""
        deadline = time.monotonic() + timeout
        payload = {}
        while time.monotonic() < deadline:
            payload = self.read(task_id, locale=locale).json()
            if not payload.get("running"):
                return payload
            time.sleep(0.02)
        self.fail(f"translation pass did not finish: {payload}")

    def run_pass(self, task_id, locale="zh-CN", provider=None):
        """Start a pass with the fake provider patched in, then wait for it."""
        with patch.object(
            reasoning_translate, "build_provider", return_value=provider or self.provider
        ):
            response = self.translate(task_id, locale=locale)
            if response.status_code != 200:
                return response, None
            return response, self.wait(task_id, locale=locale)

    def set_endpoint_limit(self, rpm_limit):
        """Give the translation endpoint an RPM budget, as the provider record would."""
        key = bucket_key(self.provider_record["protocol"], self.provider_record["base_url"])
        provider_throttle.configure({key: rpm_limit})
        return key

    def spend_minute(self):
        """Record one request against the endpoint, i.e. the bucket is no longer free."""
        provider_throttle.acquire(
            self.provider_record["protocol"], self.provider_record["base_url"]
        )


class TranslationConfigTest(_TranslatorTestCase):
    def test_nothing_configured_reports_the_default(self):
        self.assertEqual(
            {"model_id": "", "model_name": "", "source": "default"},
            self.client.get("/api/admin/translation").json(),
        )

    def test_saving_a_model_turns_the_source_into_database(self):
        response = self.client.put(
            "/api/admin/translation", json={"model_id": self.model["model_id"]}
        )

        self.assertEqual(200, response.status_code)
        expected = {
            "model_id": self.model["model_id"],
            "model_name": "fast",
            "source": "database",
        }
        self.assertEqual(expected, response.json())
        self.assertEqual(expected, self.client.get("/api/admin/translation").json())
        self.assertEqual(self.model["model_id"], state.translation_model_id)

    def test_an_unknown_model_is_rejected_without_saving(self):
        response = self.client.put("/api/admin/translation", json={"model_id": "missing"})

        self.assertEqual(400, response.status_code)
        self.assertEqual("", self.store.get_translation_model_id())

    def test_an_empty_model_turns_translation_off_again(self):
        self.client.put("/api/admin/translation", json={"model_id": self.model["model_id"]})

        response = self.client.put("/api/admin/translation", json={"model_id": ""})

        self.assertEqual(200, response.status_code)
        self.assertEqual("default", response.json()["source"])
        self.assertEqual("", self.store.get_translation_model_id())

    def test_a_saved_model_is_loaded_at_startup(self):
        self.store.set_translation_model_id(self.model["model_id"])

        self.assertEqual((self.model["model_id"], "database"), admin_api._load_translation_config())

    def test_a_saved_model_that_was_deleted_falls_back_to_off(self):
        self.store.set_translation_model_id("deleted")

        self.assertEqual(("", "default"), admin_api._load_translation_config())


class ReasoningTranslationTest(_TranslatorTestCase):
    def setUp(self):
        super().setUp()
        self.client.put("/api/admin/translation", json={"model_id": self.model["model_id"]})

    def test_without_a_configured_model_the_action_is_rejected(self):
        self.client.put("/api/admin/translation", json={"model_id": ""})
        task_id = self.seed_task([REASONING_ONE])

        response = self.translate(task_id)

        self.assertEqual(400, response.status_code)
        self.assertIn("translation model", response.json()["detail"].lower())
        self.assertEqual([], self.provider.calls)

    def test_an_unknown_task_is_not_found(self):
        self.assertEqual(404, self.translate("nope").status_code)

    def test_an_unknown_language_is_rejected(self):
        task_id = self.seed_task([REASONING_ONE])

        self.assertEqual(400, self.translate(task_id, locale="klingon").status_code)
        self.assertEqual([], self.provider.calls)

    def test_the_click_answers_before_the_traces_are_done(self):
        gate = threading.Event()
        provider = _FakeProvider(gate=gate)
        task_id = self.seed_task([REASONING_ONE])

        with patch.object(reasoning_translate, "build_provider", return_value=provider):
            started = self.translate(task_id)
            # A second click joins the pass that is already running.
            joined = self.translate(task_id)
            gate.set()
            payload = self.wait(task_id)

        self.assertEqual(200, started.status_code)
        body = started.json()
        self.assertTrue(body["started"])
        self.assertTrue(body["running"])
        self.assertEqual({}, body["items"])
        self.assertFalse(joined.json()["started"])
        self.assertTrue(joined.json()["running"])
        self.assertEqual(1, payload["translated"])
        self.assertFalse(payload["running"])
        self.assertEqual(1, len(provider.calls))

    def test_every_trace_is_translated_into_the_requested_language(self):
        task_id = self.seed_task([REASONING_ONE, REASONING_TWO])

        _, payload = self.run_pass(task_id)

        self.assertEqual("zh-CN", payload["locale"])
        self.assertEqual(2, payload["translated"])
        self.assertEqual(0, payload["skipped"])
        self.assertEqual(2, len(payload["items"]))
        self.assertTrue(all(text.startswith("[translated]") for text in payload["items"].values()))
        self.assertIn("Simplified Chinese", self.provider.calls[0][0]["content"])

    def test_the_request_names_the_chosen_language(self):
        task_id = self.seed_task([REASONING_ONE])

        self.run_pass(task_id, locale="zh-TW")

        self.assertIn("Traditional Chinese", self.provider.calls[0][0]["content"])

    def test_a_second_pass_skips_what_is_already_translated(self):
        task_id = self.seed_task([REASONING_ONE])

        self.run_pass(task_id)
        _, second = self.run_pass(task_id)

        self.assertEqual(0, second["translated"])
        self.assertEqual(1, second["skipped"])
        self.assertEqual(1, len(self.provider.calls))

    def test_another_language_is_translated_again(self):
        task_id = self.seed_task([REASONING_ONE])

        self.run_pass(task_id, locale="zh-CN")
        _, other = self.run_pass(task_id, locale="fr")

        self.assertEqual(1, other["translated"])
        self.assertEqual(2, len(self.provider.calls))

    def test_events_without_a_trace_are_ignored(self):
        task_id = self.store.create_task(query="q", provider="openai-compatible")
        self.store.append_event(
            task_id,
            TaskEvent(
                task_id=task_id,
                category=EventCategory.TOOL_CALL,
                title="Tool call",
                data={"step": 0, "name": "glob", "arguments": {}},
            ),
        )

        _, payload = self.run_pass(task_id)

        self.assertEqual(0, payload["translated"])
        self.assertEqual([], self.provider.calls)

    def test_a_long_trace_is_split_into_chunks_and_joined_back(self):
        long_reasoning = "\n\n".join(["word " * 400] * 4)
        task_id = self.seed_task([long_reasoning])

        _, payload = self.run_pass(task_id)

        self.assertEqual(1, payload["translated"])
        self.assertGreater(len(self.provider.calls), 1)
        text = next(iter(payload["items"].values()))
        self.assertEqual(len(self.provider.calls), text.count("[translated]"))

    def test_a_failing_model_is_reported_and_retried_next_time(self):
        task_id = self.seed_task([REASONING_ONE])
        self.provider.fail = True

        _, payload = self.run_pass(task_id)

        self.assertEqual(1, payload["failed"])
        self.assertEqual({}, payload["items"])
        self.assertEqual({}, self.store.list_reasoning_translations(task_id, "zh-CN"))

        self.provider.fail = False
        _, retry = self.run_pass(task_id)

        self.assertEqual(1, retry["translated"])

    def test_stored_translations_can_be_read_without_calling_the_model(self):
        task_id = self.seed_task([REASONING_ONE])
        _, saved = self.run_pass(task_id)

        read_back = self.read(task_id)

        self.assertEqual(200, read_back.status_code)
        self.assertEqual(saved["items"], read_back.json()["items"])
        self.assertEqual(1, len(self.provider.calls))

    def test_a_trace_is_not_started_when_the_endpoint_has_no_slot(self):
        self.set_endpoint_limit(1)
        self.spend_minute()
        task_id = self.seed_task([REASONING_ONE])

        _, payload = self.run_pass(task_id)

        self.assertEqual(0, payload["translated"])
        self.assertEqual(1, payload["deferred"])
        self.assertEqual(0, payload["failed"])
        self.assertEqual([], self.provider.calls)
        self.assertEqual({}, self.store.list_reasoning_translations(task_id, "zh-CN"))

    def test_the_rest_is_deferred_once_the_minute_is_spent(self):
        self.set_endpoint_limit(1)
        task_id = self.seed_task([REASONING_ONE, REASONING_TWO])

        _, payload = self.run_pass(task_id)

        self.assertEqual(1, payload["translated"])
        self.assertEqual(1, payload["deferred"])
        self.assertEqual(1, len(self.provider.calls))

    def test_an_endpoint_without_a_budget_translates_everything(self):
        task_id = self.seed_task([REASONING_ONE, REASONING_TWO])

        _, payload = self.run_pass(task_id)

        self.assertEqual(2, payload["translated"])
        self.assertEqual(0, payload["deferred"])

    def test_a_limit_raised_mid_run_defers_the_rest_instead_of_failing(self):
        task_id = self.seed_task([REASONING_ONE, REASONING_TWO])

        _, payload = self.run_pass(task_id, provider=_FakeProvider(rpm_after=1))

        self.assertEqual(1, payload["translated"])
        self.assertEqual(1, payload["deferred"])
        self.assertEqual(0, payload["failed"])
        self.assertEqual(1, len(self.store.list_reasoning_translations(task_id, "zh-CN")))

    def test_a_deferred_trace_is_translated_on_the_next_call(self):
        self.set_endpoint_limit(1)
        task_id = self.seed_task([REASONING_ONE, REASONING_TWO])

        self.run_pass(task_id)
        # The bucket's minute has passed: the console asks again and picks up the rest.
        provider_throttle.configure({})
        _, payload = self.run_pass(task_id)

        self.assertEqual(1, payload["translated"])
        self.assertEqual(1, payload["skipped"])
        self.assertEqual(0, payload["deferred"])

    def test_a_deleted_task_takes_its_translations_with_it(self):
        task_id = self.seed_task([REASONING_ONE])
        self.run_pass(task_id)

        self.store.delete_task(task_id)

        self.assertEqual({}, self.store.list_reasoning_translations(task_id, "zh-CN"))


if __name__ == "__main__":
    unittest.main()

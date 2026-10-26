"""Integration tests for provider endpoints and their RPM budgets (ADR 0014).

Run from the repository root::

    uv run python test/provider_api_test.py -v

Each case asserts on the store *and* on the process-wide limiter: a saved limit that
never reaches ``provider_throttle`` is configuration that does nothing, which is the
failure mode this API exists to prevent.
"""

import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import app_state  # noqa: E402
import main  # noqa: E402
from agent.rate_limit import provider_throttle  # noqa: E402
from task_store import _SqliteTaskStore  # noqa: E402

LOCAL_URL = "http://127.0.0.1:11434/v1"
GATEWAY_URL = "https://gateway.example.com/v1"


class ProviderApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = app_state.monitor_store
        self._previous_policy = provider_throttle.limits()
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        app_state.monitor_store = self.store
        provider_throttle.configure({})
        self.client = TestClient(main.app)

    def tearDown(self):
        app_state.monitor_store = self._previous_store
        provider_throttle.configure(self._previous_policy)
        self.store.close()
        self._tmp.cleanup()

    def _create(self, **overrides):
        payload = {
            "name": "Local Ollama",
            "protocol": "openai-compatible",
            "base_url": LOCAL_URL,
            "api_key": "k",
            "rpm_limit": 0,
        }
        payload.update(overrides)
        return self.client.post("/api/providers", json=payload)

    def test_a_fresh_install_has_no_provider(self):
        response = self.client.get("/api/providers")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["providers"], [])

    def test_creating_a_provider_stores_the_canonical_protocol(self):
        response = self._create()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual("openai", payload["protocol"])
        self.assertEqual(LOCAL_URL, payload["base_url"])
        self.assertEqual(0, payload["rpm_limit"])
        self.assertEqual(0, payload["model_count"])
        self.assertEqual(1, len(self.store.llm.list_providers()))

    def test_the_rpm_limit_reaches_the_limiter_without_a_restart(self):
        response = self._create(rpm_limit=60)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(60, provider_throttle.limit_for("openai", LOCAL_URL))

    def test_two_urls_of_one_protocol_get_their_own_budgets(self):
        self._create(rpm_limit=60)
        self._create(name="Gateway", base_url=GATEWAY_URL, rpm_limit=5)

        self.assertEqual(60, provider_throttle.limit_for("openai", LOCAL_URL))
        self.assertEqual(5, provider_throttle.limit_for("openai", GATEWAY_URL))

    def test_an_unknown_protocol_is_rejected(self):
        response = self._create(protocol="nope")

        self.assertEqual(response.status_code, 400)
        self.assertEqual([], self.store.llm.list_providers())

    def test_a_base_url_is_required_where_the_adapter_posts_to_it(self):
        response = self._create(protocol="anthropic-compatible", base_url="")

        self.assertEqual(response.status_code, 400)
        self.assertEqual([], self.store.llm.list_providers())

    def test_a_limit_outside_the_range_is_rejected(self):
        response = self._create(rpm_limit=6001)

        self.assertEqual(response.status_code, 400)
        self.assertEqual([], self.store.llm.list_providers())

    def test_a_second_provider_on_the_same_endpoint_is_rejected(self):
        self._create()

        # The limiter is keyed by protocol + URL, so two rows would overwrite each
        # other and nobody could tell which limit is in force.
        response = self._create(name="Same place, other name")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(1, len(self.store.llm.list_providers()))

    def test_updating_a_limit_hot_applies_it(self):
        provider_id = self._create(rpm_limit=10).json()["provider_id"]

        response = self.client.put(f"/api/providers/{provider_id}", json={"rpm_limit": 120})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(120, response.json()["rpm_limit"])
        self.assertEqual(120, provider_throttle.limit_for("openai", LOCAL_URL))

    def test_moving_a_provider_moves_its_budget(self):
        provider_id = self._create(rpm_limit=30).json()["provider_id"]

        response = self.client.put(f"/api/providers/{provider_id}", json={"base_url": GATEWAY_URL})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(0, provider_throttle.limit_for("openai", LOCAL_URL))
        self.assertEqual(30, provider_throttle.limit_for("openai", GATEWAY_URL))

    def test_a_provider_with_models_cannot_be_deleted(self):
        provider_id = self._create().json()["provider_id"]
        self.client.post(
            "/api/models",
            json={"name": "qwen3:0.6b", "provider_id": provider_id},
        )

        response = self.client.delete(f"/api/providers/{provider_id}")

        self.assertEqual(response.status_code, 409)
        self.assertIsNotNone(self.store.llm.get_provider(provider_id))

    def test_deleting_a_provider_lifts_its_budget(self):
        provider_id = self._create(rpm_limit=30).json()["provider_id"]

        response = self.client.delete(f"/api/providers/{provider_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.store.llm.get_provider(provider_id))
        self.assertEqual(0, provider_throttle.limit_for("openai", LOCAL_URL))

    def test_deleting_a_missing_provider_is_a_404(self):
        self.assertEqual(404, self.client.delete("/api/providers/nope").status_code)
        self.assertEqual(404, self.client.put("/api/providers/nope", json={"name": "x"}).status_code)


if __name__ == "__main__":
    unittest.main()

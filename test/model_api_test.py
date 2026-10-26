"""Integration tests for models bound to a provider endpoint (ADR 0014).

Run from the repository root::

    uv run python test/model_api_test.py -v

A model carries the name and its capabilities; the provider carries where the request
goes. These cases pin that split, including the one place it is observable from the
outside: the wire config a task builds.
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
from task_runtime import build_provider_config  # noqa: E402
from task_store import _SqliteTaskStore  # noqa: E402

LOCAL_URL = "http://127.0.0.1:11434/v1"
GATEWAY_URL = "https://gateway.example.com"


class ModelApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = app_state.monitor_store
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        app_state.monitor_store = self.store
        self.client = TestClient(main.app)

    def tearDown(self):
        app_state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    def _provider(self, **overrides):
        payload = {
            "name": "Local Ollama",
            "protocol": "openai",
            "base_url": LOCAL_URL,
            "api_key": "",
            "rpm_limit": 0,
        }
        payload.update(overrides)
        return self.client.post("/api/providers", json=payload).json()

    def _model(self, provider_id, **overrides):
        payload = {"name": "qwen3:0.6b", "provider_id": provider_id}
        payload.update(overrides)
        return self.client.post("/api/models", json=payload)

    def test_a_model_needs_an_existing_provider(self):
        response = self._model("missing-provider")

        self.assertEqual(response.status_code, 400)
        self.assertEqual([], self.store.llm.list_models())

    def test_the_list_shows_the_endpoint_a_model_resolves_to(self):
        provider = self._provider()

        response = self._model(provider["provider_id"])

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(provider["provider_id"], payload["provider_id"])
        self.assertEqual("Local Ollama", payload["provider_name"])
        self.assertEqual("openai", payload["protocol"])
        self.assertEqual(LOCAL_URL, payload["base_url"])

        listed = self.client.get("/api/models").json()["models"]
        self.assertEqual(1, len(listed))
        self.assertEqual("Local Ollama", listed[0]["provider_name"])

    def test_moving_a_model_to_another_provider_changes_its_endpoint(self):
        first = self._provider()
        second = self._provider(name="Gateway", base_url=GATEWAY_URL)
        model_id = self._model(first["provider_id"]).json()["model_id"]

        response = self.client.put(
            f"/api/models/{model_id}", json={"provider_id": second["provider_id"]}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual("openai", response.json()["protocol"])
        self.assertEqual(GATEWAY_URL, response.json()["base_url"])

    def test_updating_to_a_missing_provider_is_rejected(self):
        provider = self._provider()
        model_id = self._model(provider["provider_id"]).json()["model_id"]

        response = self.client.put(f"/api/models/{model_id}", json={"provider_id": "nope"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(provider["provider_id"], self.store.llm.get_model(model_id)["provider_id"])

    def test_the_model_name_and_flags_are_its_own(self):
        provider = self._provider()

        created = self._model(
            provider["provider_id"],
            supports_image_input=True,
            max_input_tokens=131072,
        ).json()

        self.assertEqual("qwen3:0.6b", created["name"])
        self.assertTrue(created["supports_image_input"])
        self.assertEqual(131072, created["max_input_tokens"])

    def test_deleting_a_model_leaves_the_provider_alone(self):
        provider = self._provider()
        model_id = self._model(provider["provider_id"]).json()["model_id"]

        response = self.client.delete(f"/api/models/{model_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(self.store.llm.get_provider(provider["provider_id"]))
        self.assertIsNone(self.store.llm.get_model(model_id))


class ProviderConfigResolutionTest(unittest.TestCase):
    """What a task actually builds out of the two stored records."""

    def test_the_endpoint_comes_from_the_provider(self):
        model = {"name": "qwen3:0.6b", "max_input_tokens": 8192, "supports_image_input": True}
        provider = {
            "protocol": "openai-compatible",
            "base_url": LOCAL_URL,
            "api_key": "secret",
        }

        config = build_provider_config(model, provider)

        self.assertEqual("openai", config.provider)
        self.assertEqual("qwen3:0.6b", config.model)
        self.assertEqual(LOCAL_URL, config.base_url)
        self.assertEqual("secret", config.api_key)
        self.assertEqual(8192, config.max_input_tokens)
        self.assertTrue(config.supports_image_input)

    def test_a_missing_model_builds_nothing(self):
        self.assertIsNone(build_provider_config(None, {"protocol": "openai"}))


if __name__ == "__main__":
    unittest.main()

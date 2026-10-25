"""Integration tests for the per-provider RPM config (ADR 0013).

Run from the repository root::

    uv run python test/rpm_config_api_test.py -v

The live store and the process-wide limiter are swapped in ``setUp`` so nothing here
touches the developer's database or leaves a limit behind for other tests.
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
from agent.provider import SUPPORTED_PROVIDERS  # noqa: E402
from agent.rate_limit import provider_throttle  # noqa: E402
from task_store import _SqliteTaskStore  # noqa: E402


class RpmConfigApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = app_state.monitor_store
        self._previous_limits = app_state.llm_rpm_limits
        self._previous_source = app_state.llm_rpm_limits_source
        self._previous_policy = provider_throttle.limits()
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        app_state.monitor_store = self.store
        app_state.llm_rpm_limits = {}
        app_state.llm_rpm_limits_source = "env"
        provider_throttle.configure({})
        self.client = TestClient(main.app)

    def tearDown(self):
        app_state.monitor_store = self._previous_store
        app_state.llm_rpm_limits = self._previous_limits
        app_state.llm_rpm_limits_source = self._previous_source
        provider_throttle.configure(self._previous_policy)
        self.store.close()
        self._tmp.cleanup()

    def test_the_form_can_render_every_supported_provider(self):
        response = self.client.get("/api/admin/llm-rpm")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["limits"], {})
        self.assertEqual(payload["source"], "env")
        self.assertEqual(payload["providers"], list(SUPPORTED_PROVIDERS))
        self.assertGreater(payload["max_limit"], 0)

    def test_saving_a_limit_applies_it_without_a_restart(self):
        response = self.client.put(
            "/api/admin/llm-rpm", json={"limits": {"openai": 60, "anthropic": 5}}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["limits"], {"openai": 60, "anthropic": 5})
        self.assertEqual(response.json()["source"], "database")
        self.assertEqual(provider_throttle.limit_for("openai"), 60)
        self.assertEqual(provider_throttle.limit_for("anthropic"), 5)
        self.assertEqual(self.store.get_llm_rpm_limits(), {"openai": 60, "anthropic": 5})

    def test_provider_spellings_are_stored_canonically(self):
        response = self.client.put(
            "/api/admin/llm-rpm", json={"limits": {"openai-compatible": 30}}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["limits"], {"openai": 30})

    def test_an_unknown_provider_is_rejected_and_changes_nothing(self):
        self.client.put("/api/admin/llm-rpm", json={"limits": {"openai": 60}})

        response = self.client.put(
            "/api/admin/llm-rpm", json={"limits": {"openai": 10, "nope": 5}}
        )

        self.assertEqual(response.status_code, 400)
        # The rejected request must not have half-applied.
        self.assertEqual(provider_throttle.limit_for("openai"), 60)
        self.assertEqual(self.store.get_llm_rpm_limits(), {"openai": 60})

    def test_a_limit_outside_the_range_is_rejected(self):
        for limits in ({"openai": -1}, {"openai": 6001}):
            with self.subTest(limits=limits):
                response = self.client.put("/api/admin/llm-rpm", json={"limits": limits})
                self.assertEqual(response.status_code, 400)

    def test_omitting_a_provider_lifts_its_limit(self):
        self.client.put("/api/admin/llm-rpm", json={"limits": {"openai": 60, "gemini": 10}})

        response = self.client.put("/api/admin/llm-rpm", json={"limits": {"openai": 60}})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["limits"], {"openai": 60})
        self.assertEqual(provider_throttle.limit_for("gemini"), 0)
        self.assertEqual(provider_throttle.limit_for("openai"), 60)


if __name__ == "__main__":
    unittest.main()

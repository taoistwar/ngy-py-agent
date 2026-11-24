"""Web search backend settings: the page wins over env, and the tool reads it live.

The admin page under System -> Web search owns the backend choice and its
credentials. Environment variables stay a fallback so an existing deployment keeps
working, and a saved row takes over completely - a page that shows a provider but
leaves the key behind in ``.env`` would be a configuration that lies.

Run from the repository root::

    uv run python test/web_search_config_test.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agent.tools.web_search import limits, providers  # noqa: E402
from agent.tools.web_search.tool import _web_search_impl  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402
from routes import admin_api  # noqa: E402

_ENV_KEYS = (limits.PROVIDER_ENV, limits.API_KEY_ENV, limits.BASE_URL_ENV)


class WebSearchConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = state.monitor_store
        # The routes read ``commons.state``, so that is where a test swaps the store.
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        state.monitor_store = self.store
        self.client = TestClient(main.app)
        self._saved_env = {key: os.environ[key] for key in _ENV_KEYS if key in os.environ}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        limits.reset()

    def tearDown(self):
        limits.reset()
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update(self._saved_env)
        state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    def load(self):
        return admin_api._load_web_search_config()

    def test_the_keyless_backend_is_the_default(self):
        backend, source = self.load()

        self.assertEqual(
            ("duckduckgo", "", ""),
            (backend.provider, backend.api_key, backend.base_url),
        )
        self.assertEqual("env", source)

    def test_environment_variables_are_the_fallback(self):
        os.environ.update(
            {
                limits.PROVIDER_ENV: "tavily",
                limits.API_KEY_ENV: "env-key",
                limits.BASE_URL_ENV: "https://gateway.example/search",
            }
        )

        backend, source = self.load()

        self.assertEqual(
            ("tavily", "env-key", "https://gateway.example/search"),
            (backend.provider, backend.api_key, backend.base_url),
        )
        self.assertEqual("env", source)

    def test_a_saved_backend_wins_over_the_environment(self):
        os.environ.update({limits.PROVIDER_ENV: "tavily", limits.API_KEY_ENV: "env-key"})
        self.store.set_web_search_config("serper", "saved-key", "https://internal.example")

        backend, source = self.load()

        self.assertEqual(
            ("serper", "saved-key", "https://internal.example"),
            (backend.provider, backend.api_key, backend.base_url),
        )
        self.assertEqual("database", source)

    def test_an_unknown_saved_provider_falls_back_to_the_keyless_default(self):
        self.store.set_web_search_config("not-a-backend", "", "")

        backend, source = self.load()

        self.assertEqual("duckduckgo", backend.provider)
        self.assertEqual("database", source)

    def test_the_api_reports_the_effective_config_before_anything_is_saved(self):
        response = self.client.get("/api/admin/web-search")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "provider": "duckduckgo",
                "api_key": "",
                "base_url": "",
                "source": "env",
                "supported": list(providers.SUPPORTED),
            },
            response.json(),
        )

    def test_saving_applies_to_the_running_process_immediately(self):
        response = self.client.put(
            "/api/admin/web-search",
            json={
                "provider": "serper",
                "api_key": "secret",
                "base_url": "https://internal.example/search",
            },
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("database", response.json()["source"])
        self.assertEqual(
            ("serper", "secret", "https://internal.example/search"),
            (
                limits.provider_name(),
                limits.api_key(),
                limits.base_url(),
            ),
        )
        self.assertEqual(response.json(), self.client.get("/api/admin/web-search").json())

    def test_the_deepsearch_alias_is_saved_as_deepseek(self):
        response = self.client.put(
            "/api/admin/web-search",
            json={"provider": "deepsearch", "api_key": "saved-key", "base_url": ""},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("deepseek", response.json()["provider"])
        self.assertEqual("deepseek", self.store.get_web_search_config()["provider"])

    def test_the_tool_reads_the_saved_backend_without_explicit_arguments(self):
        self.client.put(
            "/api/admin/web-search",
            json={"provider": "tavily", "api_key": "saved-key", "base_url": ""},
        )

        with patch(
            "agent.tools.web_search.providers.run", return_value=([], 0)
        ) as run:
            result = _web_search_impl("react 19")

        self.assertEqual("tavily", result["provider"])
        self.assertEqual("tavily", run.call_args.args[0].name)

    def test_an_unknown_provider_is_rejected_without_saving(self):
        response = self.client.put(
            "/api/admin/web-search",
            json={"provider": "google", "api_key": "", "base_url": ""},
        )

        self.assertEqual(400, response.status_code)
        self.assertIsNone(self.store.get_web_search_config())

    def test_an_endpoint_that_is_not_http_is_rejected(self):
        response = self.client.put(
            "/api/admin/web-search",
            json={"provider": "tavily", "api_key": "k", "base_url": "ftp://example.com"},
        )

        self.assertEqual(400, response.status_code)
        self.assertIsNone(self.store.get_web_search_config())

    def test_switching_back_to_the_keyless_backend_clears_the_key(self):
        self.client.put(
            "/api/admin/web-search",
            json={"provider": "bing", "api_key": "secret", "base_url": ""},
        )

        self.client.put(
            "/api/admin/web-search",
            json={"provider": "duckduckgo", "api_key": "", "base_url": ""},
        )

        self.assertEqual(("duckduckgo", ""), (limits.provider_name(), limits.api_key()))


if __name__ == "__main__":
    unittest.main()

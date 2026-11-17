"""Tests for the ``web_search`` tool and its backends.

Run from the repository root::

    uv run python test/tools/web_search/web_search_test.py -v

Nothing here touches the network: a throwaway HTTP server on 127.0.0.1 plays
every backend (the DuckDuckGo HTML page and the three JSON APIs), so the suite
stays runnable offline and "what the provider answered" is part of the test
rather than of the internet. The server also records each request, which is how
the tests prove that a key went into the header or the body the provider
documents - the point where an adapter is usually wired wrong.
"""

import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlsplit

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.bindings import ToolBindings  # noqa: E402
from agent.tools.catalog import build_all_specs  # noqa: E402
from agent.tools.permissions import PermissionBroker, PermissionMode  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402
from agent.tools.web_search import make_web_search_tool  # noqa: E402
from agent.tools.web_search.render import FILTERED_OUT_TEXT, NO_RESULTS_TEXT  # noqa: E402

DDG_HTML = """<!DOCTYPE html>
<html><body>
<div class="result results_links">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a"
       href="//duckduckgo.com/l/?uddg=https%3A%2F%2Freact.dev%2Fblog%2Freact-19&amp;rut=abc">React
      <b>19</b> release</a>
  </h2>
  <a class="result__snippet" href="#">The latest <b>React</b> is 19.2.</a>
</div>
<div class="result results_links">
  <h2 class="result__title"><a class="result__a" href="https://docs.example.com/guide">Docs</a></h2>
  <a class="result__snippet" href="#">Guide text</a>
</div>
<h2><a class="result__a" href="javascript:void(0)">Sponsored</a></h2>
</body></html>
"""

EMPTY_HTML = '<html><body><div class="no-results">No results.</div></body></html>'

CHALLENGE_HTML = (
    '<html><body><div class="anomaly-modal">'
    "Unfortunately, bots use DuckDuckGo too.</div></body></html>"
)


def _many_html(count):
    blocks = []
    for index in range(count):
        blocks.append(
            f'<div class="result"><h2 class="result__title">'
            f'<a class="result__a" href="https://example.com/item/{index}">Item {index}</a>'
            f'</h2><a class="result__snippet" href="#">Snippet number {index} with enough '
            f"words to fill some space in the rendered list.</a></div>"
        )
    return "<html><body>" + "".join(blocks) + "</body></html>"


MANY_HTML = _many_html(25)

TAVILY_JSON = {
    "results": [
        {"title": "Tavily One", "url": "https://tavily.example/one", "content": "First"},
        {"title": "Second", "url": "https://second.example/two", "content": "Second"},
    ]
}
SERPER_JSON = {
    "organic": [{"title": "Serper One", "link": "https://serper.example/one", "snippet": "Serper"}]
}
BING_JSON = {
    "webPages": {"value": [{"name": "Bing One", "url": "https://bing.example/one", "snippet": "Bing"}]}
}


class _Handler(BaseHTTPRequestHandler):
    """Every backend, one route table; the answers are literals above."""

    protocol_version = "HTTP/1.1"
    calls: ClassVar[list] = []

    def do_GET(self):  # noqa: N802 - the base class names it
        parts = urlsplit(self.path)
        self._record("GET", parts, b"")
        if parts.path == "/ddg/":
            return self._send(200, "text/html; charset=utf-8", DDG_HTML.encode("utf-8"))
        if parts.path == "/ddg/empty":
            return self._send(200, "text/html; charset=utf-8", EMPTY_HTML.encode("utf-8"))
        if parts.path == "/ddg/many":
            return self._send(200, "text/html; charset=utf-8", MANY_HTML.encode("utf-8"))
        if parts.path == "/ddg/challenge":
            return self._send(200, "text/html; charset=utf-8", CHALLENGE_HTML.encode("utf-8"))
        if parts.path == "/ddg/broken":
            return self._send(500, "text/plain; charset=utf-8", b"upstream failed")
        if parts.path == "/bing/v7.0/search":
            if self.headers.get("Ocp-Apim-Subscription-Key") != "bing-key":
                return self._send(401, "application/json", b'{"error": "bad key"}')
            return self._json(200, BING_JSON)
        return self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self):  # noqa: N802 - the base class names it
        parts = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self._record("POST", parts, body)
        if parts.path == "/tavily/search":
            payload = json.loads(body or b"{}")
            if payload.get("api_key") != "tavily-key":
                return self._send(401, "application/json", b'{"error": "bad key"}')
            return self._json(200, TAVILY_JSON)
        if parts.path == "/tavily/badjson":
            return self._send(200, "text/html; charset=utf-8", b"<html>not json</html>")
        if parts.path == "/serper/search":
            if self.headers.get("X-API-KEY") != "serper-key":
                return self._send(401, "application/json", b'{"error": "bad key"}')
            return self._json(200, SERPER_JSON)
        return self._send(404, "text/plain; charset=utf-8", b"not found")

    def _record(self, method, parts, body):
        type(self).calls.append(
            {"method": method, "path": parts.path, "query": parts.query, "body": body}
        )

    def _json(self, status, payload):
        return self._send(
            status, "application/json; charset=utf-8", json.dumps(payload).encode("utf-8")
        )

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_one_request(self):
        # ``requests`` closes keep-alive connections between tests; without this the
        # server thread prints a traceback for every one of them.
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    def log_message(self, *args):  # keep the test output readable
        return


class _ServerCase(unittest.TestCase):
    """A local server plus a tool whose endpoint points at one of its routes."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.outputs = Path(self._tmp.name)
        _Handler.calls.clear()

    def tearDown(self):
        self._tmp.cleanup()

    def tool(self, path="/ddg/", *, provider="duckduckgo", api_key=""):
        return make_web_search_tool(
            max_tokens=25000,
            output_directory=self.outputs,
            timeout=5,
            search_provider=provider,
            api_key=api_key,
            base_url=self.base + path,
        )


class WebSearchToolTest(_ServerCase):
    def test_the_keyless_backend_returns_a_citable_list(self):
        result = self.tool()("react 19")

        self.assertNotIn("error", result, result)
        self.assertEqual(result["provider"], "duckduckgo")
        self.assertEqual(result["query"], "react 19")
        self.assertEqual(result["result_count"], 2)
        self.assertEqual(
            [hit["url"] for hit in result["results"]],
            ["https://react.dev/blog/react-19", "https://docs.example.com/guide"],
        )
        self.assertEqual(result["results"][0]["title"], "React 19 release")
        self.assertEqual(result["results"][0]["snippet"], "The latest React is 19.2.")
        self.assertIn(
            "[React 19 release](https://react.dev/blog/react-19)", result["content"]
        )
        self.assertIn("Cite the sources", result["content"])
        self.assertFalse(result["context_truncated"])
        self.assertFalse(result["content_truncated"])
        self.assertIsNone(result["persisted_path"])
        self.assertGreaterEqual(result["duration_ms"], 0)
        self.assertFalse(result["search_type_applied"])

    def test_the_query_reaches_the_backend(self):
        self.tool()("react 19")

        self.assertEqual(_Handler.calls[0]["path"], "/ddg/")
        self.assertIn("q=react+19", _Handler.calls[0]["query"])

    def test_an_empty_result_set_is_an_answer(self):
        result = self.tool("/ddg/empty")("nothing at all")

        self.assertNotIn("error", result, result)
        self.assertEqual(result["result_count"], 0)
        self.assertEqual(result["results"], [])
        self.assertEqual(result["content"], NO_RESULTS_TEXT)

    def test_a_query_too_short_is_refused_before_any_request(self):
        tool = self.tool()

        for value, reason in {
            "": "invalid_query",
            "a": "invalid_query",
            "   ": "invalid_query",
            None: "invalid_argument",
            123: "invalid_argument",
        }.items():
            with self.subTest(query=value):
                result = tool(value)
                self.assertEqual(result["reason"], reason)
                self.assertIn("error", result)

        self.assertEqual(_Handler.calls, [])

    def test_allowed_and_blocked_domains_cannot_be_combined(self):
        result = self.tool()(
            "react 19",
            allowed_domains=["react.dev"],
            blocked_domains=["example.com"],
        )

        self.assertEqual(result["reason"], "conflicting_domain_filters")
        self.assertEqual(_Handler.calls, [])

    def test_an_allowed_domain_also_covers_its_subdomains(self):
        result = self.tool()("react 19", allowed_domains=["https://example.com/docs"])

        self.assertEqual(
            [hit["url"] for hit in result["results"]], ["https://docs.example.com/guide"]
        )

    def test_a_blocked_domain_removes_the_site_and_its_subdomains(self):
        result = self.tool()("react 19", blocked_domains=["example.com"])

        self.assertEqual(
            [hit["url"] for hit in result["results"]], ["https://react.dev/blog/react-19"]
        )

    def test_a_filter_that_removes_every_result_says_so(self):
        result = self.tool()("react 19", allowed_domains=["nowhere.test"])

        self.assertEqual(result["result_count"], 0)
        self.assertEqual(result["filtered_out"], 2)
        self.assertEqual(result["content"], FILTERED_OUT_TEXT)

    def test_num_results_is_clamped_to_the_limit(self):
        many = self.tool("/ddg/many")

        self.assertEqual(many("items")["result_count"], 8)
        self.assertEqual(many("items", num_results=1)["result_count"], 1)
        self.assertEqual(many("items", num_results=100)["result_count"], 20)
        self.assertEqual(many("items", num_results="3")["result_count"], 3)

    def test_an_invalid_search_type_is_refused(self):
        result = self.tool()("react 19", search_type="sideways")

        self.assertEqual(result["reason"], "invalid_argument")
        self.assertEqual(result["argument"], "search_type")

    def test_an_unknown_provider_is_refused(self):
        result = self.tool(provider="altavista")("react 19")

        self.assertEqual(result["reason"], "unsupported_provider")
        self.assertIn("duckduckgo", result["supported"])

    def test_a_keyed_provider_without_a_key_is_refused(self):
        result = self.tool("/tavily/search", provider="tavily")("react 19")

        self.assertEqual(result["reason"], "missing_api_key")
        self.assertEqual(result["env"], "WEB_SEARCH_API_KEY")
        self.assertEqual(_Handler.calls, [])

    def test_tavily_is_called_with_its_key_and_depth(self):
        result = self.tool("/tavily/search", provider="tavily", api_key="tavily-key")(
            "react 19", search_type="deep"
        )

        self.assertNotIn("error", result, result)
        self.assertEqual(result["provider"], "tavily")
        self.assertTrue(result["search_type_applied"])
        self.assertEqual(
            [hit["url"] for hit in result["results"]],
            ["https://tavily.example/one", "https://second.example/two"],
        )
        self.assertEqual(result["results"][0]["snippet"], "First")
        body = json.loads(_Handler.calls[0]["body"])
        self.assertEqual(body["search_depth"], "advanced")
        self.assertEqual(body["query"], "react 19")

    def test_serper_sends_its_key_as_a_header(self):
        result = self.tool("/serper/search", provider="serper", api_key="serper-key")(
            "react 19"
        )

        self.assertNotIn("error", result, result)
        self.assertEqual(
            [hit["url"] for hit in result["results"]], ["https://serper.example/one"]
        )

    def test_bing_reads_the_webpages_shape(self):
        result = self.tool("/bing/v7.0/search", provider="bing", api_key="bing-key")(
            "react 19"
        )

        self.assertNotIn("error", result, result)
        self.assertEqual(result["results"][0]["title"], "Bing One")
        self.assertEqual(result["results"][0]["snippet"], "Bing")

    def test_a_wrong_key_is_reported_as_an_http_error(self):
        result = self.tool("/tavily/search", provider="tavily", api_key="wrong")(
            "react 19"
        )

        self.assertEqual(result["reason"], "http_error")
        self.assertEqual(result["code"], 401)

    def test_a_server_error_is_reported_with_its_status(self):
        result = self.tool("/ddg/broken")("react 19")

        self.assertEqual(result["reason"], "http_error")
        self.assertEqual(result["code"], 500)
        self.assertIn("upstream failed", result["body"])

    def test_an_answer_that_is_not_json_is_a_bad_response(self):
        result = self.tool("/tavily/badjson", provider="tavily", api_key="tavily-key")(
            "react 19"
        )

        self.assertEqual(result["reason"], "bad_response")
        self.assertIn("not json", result["body"])

    def test_a_bot_check_is_reported_instead_of_an_empty_list(self):
        result = self.tool("/ddg/challenge")("react 19")

        self.assertEqual(result["reason"], "provider_blocked")
        self.assertIn("WEB_SEARCH_PROVIDER", result["error"])

    def test_context_max_characters_drops_the_tail_and_says_how_many(self):
        result = self.tool("/ddg/many")(
            "items", num_results=20, context_max_characters=500
        )

        self.assertTrue(result["context_truncated"])
        self.assertGreater(result["dropped_results"], 0)
        self.assertLess(result["result_count"], 20)
        self.assertIn("context_max_characters", result["content"])

    def test_the_registry_exposes_it_as_a_gated_read(self):
        registry = ToolRegistry(base_dir=str(self.outputs))

        self.assertIn("web_search", registry.tools)
        self.assertEqual(registry.tools["web_search"]["permission"], "read")
        self.assertEqual(registry.tools["web_search"]["category"], "network")
        schemas = {item["function"]["name"]: item for item in registry.get_tool_schemas("openai")}
        self.assertEqual(schemas["web_search"]["function"]["parameters"]["required"], ["query"])

    def test_the_catalog_lists_it_before_web_fetch(self):
        names = [spec.name for spec in build_all_specs(ToolBindings())]

        self.assertLess(names.index("grep"), names.index("web_search"))
        self.assertLess(names.index("web_search"), names.index("web_fetch"))


class PermissionTargetTest(unittest.TestCase):
    """A search is approved once per task, and the dialog shows the query."""

    def broker(self):
        events = []
        broker = PermissionBroker(
            mode=PermissionMode.ASK,
            wait_seconds=0.05,
            emit=lambda category, title, data: events.append((category, data)),
        )
        return broker, events

    def test_the_question_names_the_tool_and_shows_the_query(self):
        broker, events = self.broker()

        broker.check("web_search", "read", {"query": "react 19"})

        request = [data for category, data in events if category == "permission_request"][0]
        self.assertEqual(request["target"], "web_search")
        self.assertEqual(request["details"]["query"], "react 19")
        self.assertEqual(request["details"]["reason"], "network_search")
        self.assertEqual(request["kind"], "read")
        self.assertIn("react 19", request["summary"])

    def test_a_session_rule_covers_later_searches(self):
        events = []

        def emit(category, title, data):
            events.append((category, data))
            if category == "permission_request":
                broker.resolve(data["request_id"], True, "session")

        broker = PermissionBroker(mode=PermissionMode.ASK, wait_seconds=1.0, emit=emit)

        self.assertIsNone(broker.check("web_search", "read", {"query": "first question"}))
        self.assertIsNone(broker.check("web_search", "read", {"query": "second question"}))

        asked = [data for category, data in events if category == "permission_request"]
        self.assertEqual(len(asked), 1)

    def test_a_search_without_a_query_is_not_asked_about(self):
        broker, events = self.broker()

        broker.check("web_search", "read", {})

        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()

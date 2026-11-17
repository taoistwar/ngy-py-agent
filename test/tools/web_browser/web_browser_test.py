"""Tests for the ``web_browser`` tool.

Run from the repository root::

    uv run python test/tools/web_browser/web_browser_test.py -v

Nothing here touches the network: a throwaway HTTP server is started on
127.0.0.1 for the length of one test class, and every response it serves is
defined in ``_Handler`` below. That keeps the suite runnable offline and makes
"what the server answered" part of the test rather than of the internet.
"""

import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.modes import MODE_CONFIGS  # noqa: E402
from agent.tools.permissions import (  # noqa: E402
    NETWORK_READ_TOOLS,
    PermissionBroker,
    PermissionMode,
)
from agent.tools.registry import ToolRegistry  # noqa: E402
from agent.tools.web_browser import make_web_browser_tool  # noqa: E402
from agent.tools.web_browser.tool import EMPTY_PAGE_TEXT, SNAPSHOT_NOTICE  # noqa: E402

PAGE_HTML = b"""<!DOCTYPE html>
<html>
<head>
  <title>Example Domain</title>
  <style>body { color: red; }</style>
  <script>alert('not content')</script>
</head>
<body>
  <nav><a href="/">Home</a></nav>
  <h1>Example Domain</h1>
  <p>This domain is for <b>examples</b> and <a href="/docs">docs</a>.</p>
  <ul>
    <li>first</li>
    <li>second</li>
  </ul>
  <pre>def add(a, b):
    return a + b</pre>
  <div hidden>secret-token</div>
  <footer>footer text</footer>
</body>
</html>
"""

LATIN_HTML = "<html><head><title>Kaffee</title></head><body><p>café</p></body></html>"

# Comfortably over the 50,000-character cap, and still under the default token
# budget, so the two bounds can be asserted separately.
HUGE_TEXT = ("0123456789" * 20 + "\n") * 400

BINARY_BODY = b"\x00\x01\x02BINARY"


class _Handler(BaseHTTPRequestHandler):
    """One route table for the whole module; no state, no files."""

    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 - the base class names it
        path = self.path.split("?", 1)[0]
        if path == "/page.html":
            return self._send(200, "text/html; charset=utf-8", PAGE_HTML)
        if path == "/latin.html":
            return self._send(
                200, "text/html; charset=iso-8859-1", LATIN_HTML.encode("iso-8859-1")
            )
        if path == "/plain.txt":
            return self._send(200, "text/plain; charset=utf-8", b"line one\nline two\n")
        if path == "/data.json":
            return self._send(200, "application/json", b'{"ok": true}')
        if path == "/binary.bin":
            return self._send(200, "application/octet-stream", BINARY_BODY)
        if path == "/huge.txt":
            return self._send(200, "text/plain; charset=utf-8", HUGE_TEXT.encode("utf-8"))
        if path == "/empty.html":
            return self._send(200, "text/html; charset=utf-8", b"<html><body></body></html>")
        if path == "/redirect-same":
            return self._redirect("/page.html")
        if path == "/redirect-other":
            return self._redirect("http://example.invalid/page.html")
        if path == "/redirect-loop":
            return self._redirect("/redirect-loop")
        return self._send(404, "text/plain; charset=utf-8", b"not found")

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

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
    """A local server plus a tool bound to a throwaway output directory."""

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
        self.tool = make_web_browser_tool(
            max_tokens=25000, output_directory=self.outputs, timeout=5
        )

    def tearDown(self):
        self._tmp.cleanup()

    def browse(self, path, **arguments):
        return self.tool(self.base + path, **arguments)


class WebBrowserToolTest(_ServerCase):
    def test_a_page_comes_back_as_title_address_and_plain_text(self):
        result = self.browse("/page.html")

        self.assertNotIn("error", result, result)
        self.assertEqual(result["title"], "Example Domain")
        self.assertEqual(result["url"], self.base + "/page.html")
        self.assertEqual(result["action"], "navigate")
        self.assertFalse(result["truncated"])

        text = result["content"]
        self.assertIn("This domain is for examples and docs.", text)
        self.assertIn("- first", text)
        self.assertIn("- second", text)
        self.assertIn("    return a + b", text)
        # Plain text, not Markdown: web_fetch is the tool that keeps structure.
        self.assertNotIn("**", text)
        self.assertNotIn("](", text)
        self.assertNotIn("```", text)

    def test_what_the_browser_would_not_show_is_dropped(self):
        text = self.browse("/page.html")["content"]

        self.assertNotIn("alert", text)
        self.assertNotIn("color: red", text)
        self.assertNotIn("secret-token", text)
        # Site chrome: the menu and the footer are not the page's content.
        self.assertNotIn("Home", text)
        self.assertNotIn("footer text", text)

    def test_the_title_is_absent_when_the_page_has_none(self):
        result = self.browse("/plain.txt")

        self.assertEqual(result["content"], "line one\nline two\n")
        self.assertEqual(result["title"], "")

    def test_json_is_shown_as_text(self):
        result = self.browse("/data.json")

        self.assertEqual(result["content"], '{"ok": true}')

    def test_the_charset_from_the_header_is_used(self):
        result = self.browse("/latin.html")

        self.assertEqual(result["title"], "Kaffee")
        self.assertIn("café", result["content"])

    def test_the_screenshot_action_is_a_text_snapshot_and_says_so(self):
        result = self.browse("/page.html", action="screenshot")

        self.assertEqual(result["action"], "screenshot")
        self.assertTrue(result["content"].startswith(SNAPSHOT_NOTICE))
        self.assertIn("This domain is for examples and docs.", result["content"])

    def test_an_unknown_action_is_refused_before_any_request(self):
        result = self.browse("/page.html", action="download")

        self.assertEqual(result["reason"], "invalid_argument")
        self.assertEqual(result["allowed"], ["navigate", "screenshot"])

    def test_a_same_host_redirect_is_followed(self):
        result = self.browse("/redirect-same")

        self.assertNotIn("error", result, result)
        self.assertEqual(result["url"], self.base + "/page.html")
        self.assertEqual(result["title"], "Example Domain")

    def test_a_cross_host_redirect_is_reported_instead_of_followed(self):
        result = self.browse("/redirect-other")

        self.assertEqual(result["reason"], "cross_host_redirect")
        self.assertEqual(result["redirect_to"], "http://example.invalid/page.html")
        self.assertEqual(result["code"], 302)
        self.assertIn("REDIRECT DETECTED", result["error"])

    def test_a_redirect_loop_ends_in_an_error(self):
        self.assertEqual(self.browse("/redirect-loop")["reason"], "too_many_redirects")

    def test_a_missing_page_names_the_status_in_the_title(self):
        result = self.browse("/missing")

        self.assertEqual(result["reason"], "http_error")
        self.assertEqual(result["code"], 404)
        self.assertEqual(result["title"], "HTTP 404")
        self.assertEqual(result["url"], self.base + "/missing")

    def test_an_unreachable_host_is_a_connection_error(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        result = self.tool(f"http://127.0.0.1:{port}/")

        self.assertEqual(result["reason"], "connection_failed")
        self.assertEqual(result["title"], "Error")

    def test_a_binary_body_is_not_shown_as_text(self):
        result = self.browse("/binary.bin")

        self.assertEqual(result["reason"], "not_text")
        self.assertEqual(result["media_type"], "application/octet-stream")
        self.assertEqual(result["bytes"], len(BINARY_BODY))

    def test_a_page_without_text_says_so(self):
        self.assertEqual(self.browse("/empty.html")["content"], EMPTY_PAGE_TEXT)

    def test_a_page_over_the_character_cap_is_marked_truncated(self):
        result = self.browse("/huge.txt")

        self.assertTrue(result["truncated"])
        self.assertFalse(result["content_truncated"])
        self.assertTrue(result["content"].endswith("[truncated]"))
        self.assertLessEqual(len(result["content"]), 50_000)

    def test_a_page_over_the_token_budget_is_persisted_with_a_preview(self):
        tool = make_web_browser_tool(max_tokens=200, output_directory=self.outputs, timeout=5)

        result = tool(self.base + "/huge.txt")

        self.assertTrue(result["content_truncated"])
        self.assertIn("--- preview ---", result["content"])
        saved = Path(result["persisted_path"])
        self.assertTrue(saved.is_file())
        self.assertGreater(len(saved.read_text(encoding="utf-8")), len(result["content"]))

    def test_invalid_urls_are_refused_before_any_request(self):
        cases = {
            "": "invalid_argument",
            "   ": "invalid_argument",
            "example.com": "invalid_url",
            "http://": "invalid_url",
            "ftp://example.com/x": "unsupported_scheme",
            "file:///etc/passwd": "unsupported_scheme",
            "http://user:pw@example.com/": "credentials_in_url",
            "http://example.com/a\nb": "invalid_url",
        }
        for value, reason in cases.items():
            with self.subTest(url=value):
                result = self.tool(value)
                self.assertEqual(result["reason"], reason)
                self.assertIn("error", result)

        for value in (None, 123):
            with self.subTest(url=value):
                self.assertEqual(self.tool(value)["reason"], "invalid_argument")


class WebBrowserPermissionTest(_ServerCase):
    def test_it_is_a_gated_read_of_a_host(self):
        events = []

        def emit(category, title, data):
            events.append((category, data))

        broker = PermissionBroker(
            task_id="task-1",
            mode=PermissionMode.ASK,
            emit=emit,
            wait_seconds=0.02,
        )

        denial = broker.check("web_browser", "read", {"url": self.base + "/page.html"})

        self.assertIsNotNone(denial)
        self.assertEqual(denial.details["reason"], "timeout")
        request = next(data for category, data in events if category == "permission_request")
        self.assertEqual(request["target"], "127.0.0.1")
        self.assertEqual(request["summary"], "Browse 127.0.0.1")
        self.assertEqual(request["details"]["reason"], "network_browse")
        self.assertEqual(request["details"]["url"], self.base + "/page.html")

    def test_an_unusable_url_is_not_asked_about(self):
        broker = PermissionBroker(mode=PermissionMode.ASK, wait_seconds=0.02)

        self.assertIsNone(broker.check("web_browser", "read", {"url": "not a url"}))

    def test_it_is_registered_as_a_network_reader_in_every_relevant_place(self):
        registry = ToolRegistry(base_dir=str(self.outputs))

        self.assertIn("web_browser", NETWORK_READ_TOOLS)
        self.assertIn("web_browser", registry.tools)
        self.assertEqual(registry.tools["web_browser"]["permission"], "read")
        self.assertEqual(registry.tools["web_browser"]["category"], "network")
        self.assertIn("web_browser", MODE_CONFIGS["ask"]["tool_names"])

        schema = {item["function"]["name"]: item for item in registry.get_tool_schemas("openai")}
        parameters = schema["web_browser"]["function"]["parameters"]
        self.assertEqual(parameters["required"], ["url"])
        self.assertEqual(parameters["properties"]["action"]["enum"], ["navigate", "screenshot"])


if __name__ == "__main__":
    unittest.main()

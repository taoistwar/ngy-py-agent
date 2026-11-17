"""Tests for the ``web_fetch`` tool and its HTML converter.

Run from the repository root::

    uv run python test/tools/web_fetch/web_fetch_test.py -v

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

from agent.tools.bindings import ToolBindings  # noqa: E402
from agent.tools.catalog import build_all_specs  # noqa: E402
from agent.tools.permissions import PermissionBroker, PermissionMode  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402
from agent.tools.web_fetch import make_web_fetch_tool  # noqa: E402
from agent.tools.web_fetch.html_text import html_to_text  # noqa: E402
from agent.tools.web_fetch.tool import EMPTY_PAGE_TEXT  # noqa: E402
from agent.tools.web_urls import UrlError, parse_url  # noqa: E402

PAGE_HTML = b"""<!DOCTYPE html>
<html>
<head>
  <title>Example Domain</title>
  <style>body { color: red; }</style>
  <script>alert('not content')</script>
</head>
<body>
  <h1>Example Domain</h1>
  <p>This domain is for <b>examples</b> and <a href="/docs">docs</a>.</p>
  <ul>
    <li>first</li>
    <li>second
      <ul><li>nested</li></ul>
    </li>
  </ul>
  <pre>def add(a, b):
    return a + b</pre>
  <table>
    <tr><th>Name</th><th>Value</th></tr>
    <tr><td>a</td><td>1</td></tr>
  </table>
  <div hidden>secret-token</div>
</body>
</html>
"""

LATIN_HTML = "<html><head><title>Kaffee</title></head><body><p>café</p></body></html>"

LARGE_TEXT = ("0123456789" * 20 + "\n") * 300

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
        if path == "/large.txt":
            return self._send(200, "text/plain; charset=utf-8", LARGE_TEXT.encode("utf-8"))
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
        self.tool = make_web_fetch_tool(
            max_tokens=25000, output_directory=self.outputs, timeout=5
        )

    def tearDown(self):
        self._tmp.cleanup()

    def fetch(self, path):
        return self.tool(self.base + path)


class WebFetchToolTest(_ServerCase):
    def test_an_html_page_becomes_readable_text(self):
        result = self.fetch("/page.html")

        self.assertNotIn("error", result, result)
        text = result["content"]
        self.assertIn("# Example Domain", text)
        self.assertIn("**examples**", text)
        self.assertIn(f"[docs]({self.base}/docs)", text)
        self.assertIn("- first", text)
        self.assertIn("  - nested", text)
        self.assertIn("```\ndef add(a, b):\n    return a + b\n```", text)
        self.assertIn("| Name | Value |", text)
        self.assertIn("| a | 1 |", text)
        # What the page tells the browser to run or hide is not page text.
        self.assertNotIn("alert", text)
        self.assertNotIn("secret-token", text)
        self.assertNotIn("color: red", text)

    def test_the_receipt_reports_status_size_and_timing(self):
        result = self.fetch("/page.html")

        self.assertEqual(result["code"], 200)
        self.assertEqual(result["code_text"], "OK")
        self.assertEqual(result["url"], self.base + "/page.html")
        self.assertEqual(result["requested_url"], self.base + "/page.html")
        self.assertIn("text/html", result["content_type"])
        self.assertEqual(result["encoding"], "utf-8")
        self.assertEqual(result["bytes"], len(PAGE_HTML))
        self.assertGreaterEqual(result["duration_ms"], 0)
        self.assertFalse(result["redirected"])
        self.assertFalse(result["content_truncated"])
        self.assertIsNone(result["persisted_path"])

    def test_a_same_host_redirect_is_followed(self):
        result = self.fetch("/redirect-same")

        self.assertTrue(result["redirected"])
        self.assertEqual(result["code"], 200)
        self.assertEqual(result["url"], self.base + "/page.html")
        self.assertIn("# Example Domain", result["content"])

    def test_a_cross_host_redirect_is_reported_instead_of_followed(self):
        result = self.fetch("/redirect-other")

        self.assertEqual(result["code"], 302)
        self.assertTrue(result["redirected"])
        self.assertEqual(result["redirect_to"], "http://example.invalid/page.html")
        self.assertEqual(result["bytes"], 0)
        self.assertIn("REDIRECT DETECTED", result["content"])
        self.assertIn("http://example.invalid/page.html", result["content"])

    def test_a_redirect_loop_ends_in_an_error(self):
        result = self.fetch("/redirect-loop")

        self.assertEqual(result["reason"], "too_many_redirects")

    def test_the_charset_from_the_header_is_used(self):
        result = self.fetch("/latin.html")

        self.assertIn("café", result["content"])
        self.assertEqual(result["encoding"], "iso8859-1")

    def test_plain_text_is_returned_unchanged(self):
        result = self.fetch("/plain.txt")

        self.assertEqual(result["content"], "line one\nline two\n")

    def test_json_is_returned_unchanged(self):
        result = self.fetch("/data.json")

        self.assertEqual(result["content"], '{"ok": true}')
        self.assertEqual(result["media_type"], "application/json")

    def test_binary_content_is_saved_unchanged(self):
        result = self.fetch("/binary.bin")

        saved = Path(result["persisted_path"])
        self.assertTrue(saved.is_file())
        self.assertEqual(saved.read_bytes(), BINARY_BODY)
        self.assertEqual(result["bytes"], len(BINARY_BODY))
        self.assertEqual(result["media_type"], "application/octet-stream")
        self.assertIn(saved.as_posix(), result["content"])

    def test_a_large_page_is_persisted_with_a_preview(self):
        tool = make_web_fetch_tool(max_tokens=200, output_directory=self.outputs, timeout=5)

        result = tool(self.base + "/large.txt")

        self.assertTrue(result["content_truncated"])
        saved = Path(result["persisted_path"])
        self.assertEqual(saved.read_text(encoding="utf-8"), LARGE_TEXT)
        self.assertIn("--- preview ---", result["content"])
        self.assertLess(len(result["content"]), len(LARGE_TEXT))

    def test_a_page_without_text_says_so(self):
        result = self.fetch("/empty.html")

        self.assertEqual(result["content"], EMPTY_PAGE_TEXT)

    def test_a_missing_page_is_an_http_error(self):
        result = self.fetch("/missing")

        self.assertEqual(result["reason"], "http_error")
        self.assertEqual(result["code"], 404)
        self.assertIn("404", result["error"])

    def test_an_unreachable_host_is_a_connection_error(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        result = self.tool(f"http://127.0.0.1:{port}/")

        self.assertEqual(result["reason"], "connection_failed")

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

    def test_registry_exposes_it_as_a_gated_read_of_the_web(self):
        registry = ToolRegistry(base_dir=str(self.outputs))

        self.assertIn("web_fetch", registry.tools)
        self.assertEqual(registry.tools["web_fetch"]["permission"], "read")
        self.assertEqual(registry.tools["web_fetch"]["category"], "network")
        schemas = {item["function"]["name"]: item for item in registry.get_tool_schemas("openai")}
        self.assertEqual(schemas["web_fetch"]["function"]["parameters"]["required"], ["url"])

    def test_the_catalog_lists_it_between_grep_and_read_file(self):
        names = [spec.name for spec in build_all_specs(ToolBindings())]

        self.assertLess(names.index("grep"), names.index("web_fetch"))
        self.assertLess(names.index("web_fetch"), names.index("read_file"))


class HtmlToTextTest(unittest.TestCase):
    def test_headings_paragraphs_and_rules_are_separated(self):
        text = html_to_text("<h2>Title</h2><p>One</p><p>Two</p><hr>").text

        self.assertEqual(text, "## Title\n\nOne\n\nTwo\n\n---")

    def test_nested_lists_keep_their_indent_and_numbering(self):
        text = html_to_text(
            "<ol><li>one</li><li>two<ul><li>two-a</li></ul></li></ol>"
        ).text

        self.assertEqual(text, "1. one\n2. two\n  - two-a")

    def test_links_resolve_against_the_page_url(self):
        text = html_to_text(
            '<p><a href="/docs">Docs</a> and <a href="guide">Guide</a></p>',
            base_url="https://example.com/a/b",
        ).text

        self.assertEqual(
            text, "[Docs](https://example.com/docs) and [Guide](https://example.com/a/guide)"
        )

    def test_links_that_cannot_be_fetched_keep_only_their_text(self):
        text = html_to_text(
            '<p><a href="mailto:x@example.com">mail</a> '
            '<a href="#top">top</a> <a href="javascript:void(0)">js</a></p>'
        ).text

        self.assertEqual(text, "mail top js")

    def test_code_blocks_keep_their_whitespace(self):
        text = html_to_text("<pre>if x:\n    y()</pre>").text

        self.assertEqual(text, "```\nif x:\n    y()\n```")

    def test_inline_code_uses_backticks(self):
        self.assertEqual(html_to_text("<p>call <code>f()</code> now</p>").text, "call `f()` now")

    def test_empty_emphasis_is_dropped(self):
        self.assertEqual(html_to_text("<p>a<b></b> b</p>").text, "a b")

    def test_hidden_and_scripted_content_is_dropped(self):
        text = html_to_text(
            "<body><script>var x = 1;</script><div hidden>nope</div>"
            '<p aria-hidden="true">nope</p><p>kept</p></body>'
        ).text

        self.assertEqual(text, "kept")

    def test_site_chrome_is_dropped(self):
        text = html_to_text(
            "<body><nav><a href='/a'>Menu</a></nav>"
            '<div role="navigation">Sidebar</div>'
            "<main><p>Article</p></main>"
            "<footer>© 2026 Example</footer></body>"
        ).text

        self.assertEqual(text, "Article")

    def test_table_rows_become_pipe_rows(self):
        text = html_to_text("<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>").text

        self.assertEqual(text, "| A | B |\n| 1 | 2 |")

    def test_entities_are_decoded(self):
        self.assertEqual(html_to_text("<p>a &amp; b &lt;c&gt; &#8212; d</p>").text, "a & b <c> — d")

    def test_the_title_becomes_the_first_heading_when_the_body_has_none(self):
        text = html_to_text("<html><head><title>My Page</title></head><body><p>Body</p></body></html>")

        self.assertEqual(text.title, "My Page")
        self.assertEqual(text.text, "# My Page\n\nBody")

    def test_an_existing_heading_is_not_duplicated_by_the_title(self):
        text = html_to_text(
            "<html><head><title>Example Domain</title></head>"
            "<body><h1>Example Domain</h1></body></html>"
        ).text

        self.assertEqual(text, "# Example Domain")

    def test_an_svg_title_does_not_end_the_skip_early(self):
        text = html_to_text("<body><svg><title>icon</title><path/></svg><p>after</p></body>").text

        self.assertEqual(text, "after")

    def test_unclosed_markup_still_yields_text(self):
        text = html_to_text("<div><p>one<p>two").text

        self.assertIn("one", text)
        self.assertIn("two", text)

    def test_empty_markup_yields_empty_text(self):
        self.assertEqual(html_to_text("").text, "")
        self.assertEqual(html_to_text("").title, "")


class UrlRulesTest(unittest.TestCase):
    def test_whitespace_around_a_url_is_trimmed(self):
        self.assertEqual(parse_url("  https://example.com/a  ").url, "https://example.com/a")

    def test_the_fragment_is_dropped(self):
        self.assertEqual(parse_url("https://example.com/a#section").url, "https://example.com/a")

    def test_spaces_in_a_pasted_url_are_percent_encoded(self):
        self.assertEqual(
            parse_url("https://example.com/search?q=hello world").url,
            "https://example.com/search?q=hello%20world",
        )

    def test_an_empty_path_becomes_the_root(self):
        self.assertEqual(parse_url("https://example.com").url, "https://example.com/")

    def test_the_host_is_lowercased_and_loses_its_trailing_dot(self):
        self.assertEqual(parse_url("https://Example.COM./a").host, "example.com")

    def test_the_default_port_is_dropped_but_a_custom_one_is_kept(self):
        self.assertEqual(parse_url("https://example.com:443/a").url, "https://example.com/a")
        self.assertEqual(parse_url("https://example.com:8443/a").url, "https://example.com:8443/a")

    def test_an_ipv6_literal_keeps_its_brackets(self):
        self.assertEqual(parse_url("http://[::1]:8080/a").url, "http://[::1]:8080/a")
        self.assertEqual(parse_url("http://[::1]:8080/a").host, "::1")

    def test_an_over_long_url_is_refused(self):
        with self.assertRaises(UrlError):
            parse_url("https://example.com/" + "a" * 5000)


class PermissionTargetTest(unittest.TestCase):
    """The gate asks about the host, not about every page of a site."""

    def broker(self):
        events = []
        broker = PermissionBroker(
            mode=PermissionMode.ASK,
            wait_seconds=0.05,
            emit=lambda category, title, data: events.append((category, data)),
        )
        return broker, events

    def test_the_question_names_the_host_and_shows_the_url(self):
        broker, events = self.broker()

        broker.check("web_fetch", "read", {"url": "https://example.com/a?x=1"})

        request = [data for category, data in events if category == "permission_request"][0]
        self.assertEqual(request["target"], "example.com")
        self.assertEqual(request["details"]["url"], "https://example.com/a?x=1")
        self.assertEqual(request["details"]["reason"], "network_fetch")
        self.assertEqual(request["kind"], "read")

    def test_a_session_rule_covers_later_pages_from_the_same_host(self):
        events = []

        def emit(category, title, data):
            events.append((category, data))
            if category == "permission_request":
                broker.resolve(data["request_id"], True, "session")

        broker = PermissionBroker(mode=PermissionMode.ASK, wait_seconds=1.0, emit=emit)

        self.assertIsNone(broker.check("web_fetch", "read", {"url": "https://example.com/a"}))
        self.assertIsNone(broker.check("web_fetch", "read", {"url": "https://example.com/b"}))

        asked = [data for category, data in events if category == "permission_request"]
        self.assertEqual(len(asked), 1)

    def test_a_different_host_is_asked_about_again(self):
        events = []

        def emit(category, title, data):
            events.append((category, data))
            if category == "permission_request":
                broker.resolve(data["request_id"], True, "session")

        broker = PermissionBroker(mode=PermissionMode.ASK, wait_seconds=1.0, emit=emit)

        broker.check("web_fetch", "read", {"url": "https://example.com/a"})
        broker.check("web_fetch", "read", {"url": "https://evil.example.net/a"})

        asked = [data for category, data in events if category == "permission_request"]
        self.assertEqual([data["target"] for data in asked], ["example.com", "evil.example.net"])

    def test_a_url_the_tool_would_refuse_is_not_asked_about(self):
        broker, events = self.broker()

        broker.check("web_fetch", "read", {"url": "ftp://example.com/x"})

        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()

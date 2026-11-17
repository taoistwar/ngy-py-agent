"""Tests for MCP over HTTP: Streamable HTTP, the legacy SSE transport, and headers.

Run from the repository root::

    uv run python test/agent/mcp/mcp_http_transport_test.py -v

Every test talks to a real local HTTP server, because what these transports can get
wrong is the wire - where the answer arrives, which header a server insists on, what
happens when nothing ever comes back - and a mock would answer the way this client
already expects.
"""

import json
import os
import queue
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import patch

# ``test/`` is intentionally not a package, so the repository root is added to the
# import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.mcp.probe import probe_server  # noqa: E402
from agent.mcp.stdio import McpSessionError  # noqa: E402
from agent.mcp.transport import open_session, resolve_headers  # noqa: E402

TOOL = {
    "name": "echo",
    "description": "Echo the text back",
    "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
}


def _answer(payload: Dict[str, Any]) -> Dict[str, Any]:
    """What the fake server says to one JSON-RPC message."""
    method = payload.get("method")
    request_id = payload.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "http-fake", "version": "2.0.0"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [TOOL]}}
    if method == "tools/call":
        arguments = (payload.get("params") or {}).get("arguments") or {}
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"content": [{"type": "text", "text": f"http: {arguments.get('text', '')}"}]},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": {}}


class _Handler(BaseHTTPRequestHandler):
    """One server with the routes each test needs; ``/sse`` keeps a stream open."""

    protocol_version = "HTTP/1.1"
    outbox: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()

    def log_message(self, *args: Any) -> None:
        return  # a test server has nothing to say

    # -- helpers -----------------------------------------------------------

    def _read(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def _write(self, body: bytes) -> None:
        try:
            self.wfile.write(body)
        except OSError:
            # The client hung up first (the timeout test does exactly that).
            return

    def _respond(self, payload: Any, status: int = 200, headers: Optional[Dict[str, str]] = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self._write(body)

    def _text(self, text: str, status: int = 200) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._write(body)

    # -- POST --------------------------------------------------------------

    def do_POST(self) -> None:
        if self.path.startswith("/boom"):
            self._text("exploded", status=500)
            return
        if self.path.startswith("/hang"):
            payload = self._read()
            time.sleep(3)
            self._respond(_answer(payload))
            return
        if self.path.startswith("/auth"):
            if self.headers.get("Authorization") != "Bearer test-token":
                self._text("missing token", status=401)
                return
        if self.path.startswith("/session"):
            if getattr(self.server, "initialized", False):
                if self.headers.get("Mcp-Session-Id") != "sess-1":
                    self._text("missing session", status=400)
                    return
            payload = self._read()
            self.server.initialized = True
            self._respond(_answer(payload), headers={"Mcp-Session-Id": "sess-1"})
            return
        if self.path.startswith("/sse/messages"):
            self.outbox.put(_answer(self._read()))
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        payload = self._read()
        if self.path.startswith("/stream"):
            self._stream_answer(payload)
            return
        self._respond(_answer(payload))

    def _stream_answer(self, payload: Dict[str, Any]) -> None:
        """Answer one POST with an event stream instead of a JSON body."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        data = json.dumps(_answer(payload))
        self._write(f"event: message\ndata: {data}\n\n".encode("utf-8"))
        self.close_connection = True

    # -- GET ---------------------------------------------------------------

    def do_GET(self) -> None:
        if not self.path.startswith("/sse"):
            self._text("not found", status=404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if "/no-endpoint" not in self.path:
            # The announcement the SSE transport needs before it can post anything.
            self._write(b"event: endpoint\ndata: /sse/messages\n\n")
            while True:
                message = self.outbox.get()
                if message is None:
                    break
                data = json.dumps(message)
                self._write(f"event: message\ndata: {data}\n\n".encode("utf-8"))
        self.close_connection = True


class _Server(ThreadingHTTPServer):
    """A test server: a client hanging up (the timeout test) is not worth a traceback."""

    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        return


class _FakeHttpServer:
    """A throwaway HTTP server on a free port, with the handler above."""

    def __init__(self) -> None:
        _Handler.outbox = queue.Queue()
        self.httpd = _Server(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.initialized = False
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self) -> "_FakeHttpServer":
        self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        _Handler.outbox.put(None)
        self.httpd.shutdown()
        self.httpd.server_close()


class HttpTransportTest(unittest.TestCase):
    def setUp(self):
        self.server = _FakeHttpServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)

    def probe(self, path: str, **overrides):
        preset = {"transport": "http", "target": f"{self.server.base}{path}"}
        preset.update(overrides)
        return probe_server(preset)

    def test_a_json_answer_is_used(self):
        result = self.probe("/json")

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.transport, "http")
        self.assertEqual(result.server_name, "http-fake")
        self.assertEqual(result.server_version, "2.0.0")
        self.assertEqual(result.protocol_version, "2025-06-18")
        self.assertEqual([tool.name for tool in result.tools], ["echo"])

    def test_an_event_stream_answer_is_used(self):
        result = self.probe("/stream")

        self.assertTrue(result.ok, result.error)
        self.assertEqual([tool.name for tool in result.tools], ["echo"])

    def test_the_session_id_from_the_handshake_is_sent_again(self):
        # The server refuses the second request without the id it handed out, so a green
        # result means the header really travelled.
        result = self.probe("/session")

        self.assertTrue(result.ok, result.error)
        self.assertEqual([tool.name for tool in result.tools], ["echo"])

    def test_preset_headers_are_sent(self):
        result = self.probe(
            "/auth", headers=[{"name": "Authorization", "value": "Bearer test-token"}]
        )

        self.assertTrue(result.ok, result.error)

    def test_a_missing_header_is_reported_as_the_servers_refusal(self):
        result = self.probe("/auth")

        self.assertFalse(result.ok)
        self.assertIn("401", result.error)
        self.assertIn("missing token", result.error)

    def test_a_server_error_body_is_reported(self):
        result = self.probe("/boom")

        self.assertFalse(result.ok)
        self.assertIn("HTTP 500", result.error)
        self.assertIn("exploded", result.error)

    def test_a_server_that_never_answers_times_out(self):
        result = probe_server(
            {"transport": "http", "target": f"{self.server.base}/hang"}, timeout=0.3
        )

        self.assertFalse(result.ok)
        self.assertIn("did not answer", result.error)

    def test_the_older_sse_transport_connects_and_lists_tools(self):
        result = probe_server(
            {"transport": "sse", "target": f"{self.server.base}/sse"}, timeout=10
        )

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.transport, "sse")
        self.assertEqual([tool.name for tool in result.tools], ["echo"])

    def test_an_sse_endpoint_that_announces_nothing_is_reported(self):
        result = probe_server(
            {"transport": "sse", "target": f"{self.server.base}/sse/no-endpoint"}, timeout=0.5
        )

        self.assertFalse(result.ok)
        self.assertIn("did not announce", result.error)


class HeadersTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.vault = self.root / "vault.json"
        self.vault.write_text(
            json.dumps({"secrets": {"mcp-token": "Bearer test-token"}}), encoding="utf-8"
        )
        self.addCleanup(self._tmp.cleanup)

    def test_a_vault_reference_is_resolved_at_connect_time(self):
        with patch.dict(os.environ, {"VAULT_SECRETS_PATH": str(self.vault)}):
            headers = resolve_headers([{"name": "Authorization", "value": "vault:mcp-token"}])

        self.assertEqual(headers, {"Authorization": "Bearer test-token"})

    def test_a_missing_vault_key_names_the_problem(self):
        with patch.dict(os.environ, {"VAULT_SECRETS_PATH": str(self.vault)}):
            with self.assertRaises(McpSessionError) as caught:
                resolve_headers([{"name": "Authorization", "value": "vault:nope"}])

        self.assertIn("could not be filled from the vault", str(caught.exception))

    def test_a_literal_value_is_passed_through(self):
        headers = resolve_headers({"X-Tenant": "acme"})

        self.assertEqual(headers, {"X-Tenant": "acme"})

    def test_an_empty_value_is_dropped(self):
        self.assertEqual(resolve_headers([{"name": "X-Empty", "value": "  "}]), {})

    def test_a_header_name_that_is_not_a_token_is_refused(self):
        with self.assertRaises(McpSessionError) as caught:
            resolve_headers([{"name": "Bad Header", "value": "x"}])

        self.assertIn("not a usable HTTP header name", str(caught.exception))

    def test_headers_on_a_stdio_preset_are_refused(self):
        with self.assertRaises(McpSessionError) as caught:
            open_session({"transport": "stdio", "target": "npx -y x", "headers": {"A": "b"}})

        self.assertIn("only apply to the sse and http transports", str(caught.exception))

    def test_an_unknown_transport_names_the_supported_ones(self):
        with self.assertRaises(McpSessionError) as caught:
            open_session({"transport": "websocket", "target": "ws://example.com"})

        self.assertIn("stdio, sse or http", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)

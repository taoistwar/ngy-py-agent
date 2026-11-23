"""Tests for one hand-run tool call against a real MCP server process.

Run from the repository root::

    uv run python test/agent/mcp/mcp_tool_call_test.py -v

The fake server is written to a temporary file and run by this same interpreter,
so the tests need no network and no npm package. What is pinned here is the
conversation the marketplace's tool form depends on: handshake, ``tools/call``,
and how a tool that reports its own failure comes back.
"""

import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to the
# import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.mcp import call_server_tool  # noqa: E402

# Echoes its arguments as text, and fails on purpose for the tool named "fail".
CALL_SERVER = r'''
import json
import sys


def send(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    message = json.loads(raw)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-call", "version": "1.0.0"},
            },
        })
        continue
    if method == "tools/call":
        params = message.get("params") or {}
        if params.get("name") == "fail":
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": "the tool blew up"}],
                },
            })
        else:
            arguments = json.dumps(params.get("arguments") or {}, sort_keys=True)
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": "echo " + arguments}]},
            })
        continue
    if request_id is not None:
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
'''


class _FakeServer:
    """Writes one fake server script and names the command that runs it."""

    def __init__(self, root: Path, source: str) -> None:
        self.script = root / "fake_call_server.py"
        self.script.write_text(source, encoding="utf-8")

    def preset(self, transport: str = "stdio") -> dict:
        parts = [sys.executable, str(self.script)]
        # Windows resolves the command line through cmd.exe, so the interpreter path
        # has to be quoted by hand; POSIX gets a properly escaped argv line.
        target = " ".join(f'"{part}"' for part in parts) if os.name == "nt" else shlex.join(parts)
        return {"transport": transport, "target": target}


class CallServerToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.server = _FakeServer(self.root, CALL_SERVER)

    def tearDown(self):
        self._tmp.cleanup()

    def test_returns_the_text_the_server_answered(self):
        result = call_server_tool(self.server.preset(), "echo", {"text": "hi"})

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.tool, "echo")
        self.assertEqual(result.result, 'echo {"text": "hi"}')
        self.assertEqual(result.error, "")
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_empty_arguments_are_sent_as_an_empty_object(self):
        result = call_server_tool(self.server.preset(), "echo", None)

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.result, "echo {}")

    def test_tool_that_reports_a_failure_is_a_failed_result(self):
        result = call_server_tool(self.server.preset(), "fail", {})

        self.assertFalse(result.ok)
        self.assertEqual(result.tool, "fail")
        self.assertIn("the tool blew up", result.error)
        self.assertEqual(result.result, "")

    def test_empty_tool_name_is_refused_without_connecting(self):
        result = call_server_tool(self.server.preset(), "   ", {})

        self.assertFalse(result.ok)
        self.assertIn("empty", result.error)

    def test_an_unknown_transport_is_refused(self):
        result = call_server_tool({"transport": "websocket", "target": "ws://x"}, "echo", {})

        self.assertFalse(result.ok)
        self.assertIn("is not supported", result.error)

    def test_empty_target_is_refused(self):
        result = call_server_tool({"transport": "stdio", "target": "  "}, "echo", {})

        self.assertFalse(result.ok)
        self.assertIn("empty", result.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Tests for the MCP stdio probe.

Run from the repository root::

    uv run python test/agent/mcp/mcp_probe_test.py -v

Every test spawns a real child process speaking newline-delimited JSON-RPC, because
the framing, the timeout and the shutdown path are the parts worth pinning. The fake
servers are written to a temporary file and run by this same interpreter, so the
tests need no network and no npm package.
"""

import json
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

from agent.mcp import probe_server  # noqa: E402
from agent.mcp.jsonrpc import (  # noqa: E402
    McpProtocolError,
    decode_message,
    encode_notification,
    encode_request,
)
from agent.mcp.stdio import _child_env  # noqa: E402

# A well-behaved server: identity on ``initialize``, two tools across two pages of
# ``tools/list``, and an empty result for anything else it is asked.
TOOL_SERVER = r'''
import json
import sys


def send(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


TOOLS = [
    {"name": "echo", "description": "Echo the text back", "inputSchema": {"type": "object"}},
    {"name": "sum", "description": "Add two numbers", "inputSchema": {"type": "object"}},
]


def handle(message):
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-tools", "version": "9.9.9"},
            },
        })
        return
    if method == "tools/list":
        cursor = (message.get("params") or {}).get("cursor")
        if cursor:
            send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS[1:]}})
        else:
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": TOOLS[:1], "nextCursor": "page-2"},
            })
        return
    if request_id is not None:
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})


for raw in sys.stdin:
    raw = raw.strip()
    if raw:
        handle(json.loads(raw))
'''

# Correct handshake, then a JSON-RPC error where the tool list should be.
ERROR_SERVER = r'''
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
    if message.get("method") == "initialize":
        send({
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-error", "version": "1.0.0"},
            },
        })
    elif message.get("method") == "tools/list":
        send({
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {"code": -32601, "message": "Method not found"},
        })
'''

# Writes something that is not JSON-RPC, then stays alive so the failure is the
# protocol error rather than an early exit.
GARBAGE_SERVER = r'''
import sys


sys.stdout.write("this is not json\n")
sys.stdout.flush()
for _ in sys.stdin:
    pass
'''

# Starts, says nothing, never exits: the timeout is what has to end the probe.
SILENT_SERVER = r'''
import time


time.sleep(60)
'''

# Dies before the handshake, with an explanation on stderr.
CRASH_SERVER = r'''
import sys


sys.stderr.write("fake server crashed\n")
sys.stderr.flush()
sys.exit(7)
'''


class _FakeServers:
    """Writes fake server scripts into one temporary directory and names their command."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._counter = 0

    def command(self, source: str) -> str:
        self._counter += 1
        script = self._root / f"fake_server_{self._counter}.py"
        script.write_text(source, encoding="utf-8")
        parts = [sys.executable, str(script)]
        # Windows resolves the command line through cmd.exe, so the interpreter path
        # has to be quoted by hand; POSIX gets a properly escaped argv line.
        if os.name == "nt":
            return " ".join(f'"{part}"' for part in parts)
        return shlex.join(parts)


class ProbeServerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.servers = _FakeServers(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_reads_server_identity_and_every_tool_page(self):
        result = probe_server({"transport": "stdio", "target": self.servers.command(TOOL_SERVER)})

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.transport, "stdio")
        self.assertEqual(result.server_name, "fake-tools")
        self.assertEqual(result.server_version, "9.9.9")
        self.assertEqual(result.protocol_version, "2024-11-05")
        self.assertEqual([tool.name for tool in result.tools], ["echo", "sum"])
        self.assertEqual(result.tools[0].description, "Echo the text back")
        self.assertEqual(result.tools[0].input_schema, {"type": "object"})
        self.assertEqual(result.error, "")
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_server_error_is_reported_as_a_failed_probe(self):
        result = probe_server({"transport": "stdio", "target": self.servers.command(ERROR_SERVER)})

        self.assertFalse(result.ok)
        self.assertIn("Method not found", result.error)
        self.assertEqual(result.tools, ())

    def test_non_json_output_is_reported(self):
        result = probe_server({"transport": "stdio", "target": self.servers.command(GARBAGE_SERVER)})

        self.assertFalse(result.ok)
        self.assertIn("not JSON", result.error)

    def test_silent_server_times_out(self):
        result = probe_server(
            {"transport": "stdio", "target": self.servers.command(SILENT_SERVER)},
            timeout=0.5,
        )

        self.assertFalse(result.ok)
        self.assertIn("did not answer", result.error)

    def test_crash_on_start_reports_what_it_printed(self):
        result = probe_server({"transport": "stdio", "target": self.servers.command(CRASH_SERVER)})

        self.assertFalse(result.ok)
        self.assertIn("exited before answering", result.error)
        self.assertIn("fake server crashed", result.error)

    def test_transport_other_than_stdio_is_refused(self):
        result = probe_server({"transport": "sse", "target": "https://example.com/sse"})

        self.assertFalse(result.ok)
        self.assertIn("only stdio is supported", result.error)

    def test_empty_target_is_refused(self):
        result = probe_server({"transport": "stdio", "target": "   "})

        self.assertFalse(result.ok)
        self.assertIn("empty", result.error)


class ChildEnvTest(unittest.TestCase):
    def test_program_folder_goes_first_on_path(self):
        program = os.path.join(os.sep, "tools", "node", "npx.cmd")
        env = _child_env(f'"{program}" -y @modelcontextprotocol/server-everything')

        self.assertIsNotNone(env)
        self.assertTrue(env["PATH"].startswith(os.path.dirname(program)))

    def test_bare_command_inherits_the_environment(self):
        self.assertIsNone(_child_env("npx -y @modelcontextprotocol/server-everything"))


class JsonRpcTest(unittest.TestCase):
    def test_request_without_params_omits_the_key(self):
        message = json.loads(encode_request(1, "tools/list"))

        self.assertNotIn("params", message)
        self.assertEqual(message["id"], 1)

    def test_notification_has_no_id(self):
        message = json.loads(encode_notification("notifications/initialized"))

        self.assertNotIn("id", message)
        self.assertEqual(message["method"], "notifications/initialized")

    def test_non_json_line_is_a_protocol_error(self):
        with self.assertRaises(McpProtocolError):
            decode_message("not json")

    def test_non_object_json_is_a_protocol_error(self):
        with self.assertRaises(McpProtocolError):
            decode_message("[1, 2]")

    def test_wrong_jsonrpc_version_is_a_protocol_error(self):
        with self.assertRaises(McpProtocolError):
            decode_message('{"jsonrpc": "1.0", "id": 1, "result": {}}')


if __name__ == "__main__":
    unittest.main(verbosity=2)

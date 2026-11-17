"""Tests for the MCP tool bridge: what a selected server adds to one run.

Run from the repository root::

    uv run python test/agent/mcp/mcp_bridge_test.py -v

The fake servers are real child processes (same interpreter, temporary file) because
the bridge's job is a conversation, not a dictionary lookup. What is pinned here is the
contract the loop depends on: names that cannot collide, the permission kind, a call
that reaches the remote tool, a remote failure that fails the step, one broken preset
that does not take the others down, and a close that really stops the process.
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

from agent.mcp import live  # noqa: E402
from agent.mcp.bridge import McpBridge  # noqa: E402
from agent.mcp.names import MAX_TOOL_NAME, server_of, tool_name  # noqa: E402
from agent.mcp.session import McpToolError  # noqa: E402
from agent.mcp.stdio import McpSessionError  # noqa: E402
from agent.tools.permissions import PERMISSION_MCP  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402

# A server with a normal tool, a tool that reports its own failure, and pagination on
# ``tools/list`` so the bridge is exercised through the same path a real server uses.
TOOL_SERVER = r'''
import json
import sys


def send(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


TOOLS = [
    {
        "name": "echo",
        "description": "Echo the text back",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
    {
        "name": "fail",
        "description": "Always fails",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "no-schema",
        "description": "",
    },
]


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
                "serverInfo": {"name": "fake-tools", "version": "1.0.0"},
            },
        })
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        if name == "echo":
            text = (params.get("arguments") or {}).get("text", "")
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": "echo: " + str(text)}]},
            })
        elif name == "fail":
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": "it broke"}], "isError": True},
            })
        else:
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "Unknown tool"},
            })
    elif request_id is not None:
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
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


class NamingTest(unittest.TestCase):
    def test_name_is_prefixed_with_the_server(self):
        self.assertEqual(tool_name("filesystem", "read_file"), "mcp__filesystem__read_file")

    def test_free_text_is_reduced_to_a_function_name(self):
        name = tool_name("@org/filesystem server!", "read file (recursive)")

        self.assertRegex(name, r"^[A-Za-z0-9_-]+$")
        self.assertEqual(name, "mcp__org_filesystem_server__read_file_recursive")
        self.assertLessEqual(len(name), MAX_TOOL_NAME)

    def test_long_names_are_cut_to_the_provider_limit(self):
        name = tool_name("filesystem", "x" * 200)

        self.assertLessEqual(len(name), MAX_TOOL_NAME)

    def test_collisions_get_a_suffix_instead_of_overwriting(self):
        first = tool_name("filesystem", "read_file")
        second = tool_name("filesystem", "read_file", {first})

        self.assertNotEqual(first, second)
        self.assertLessEqual(len(second), MAX_TOOL_NAME)

    def test_server_is_readable_back_out_of_a_name(self):
        self.assertEqual(server_of("mcp__filesystem__read_file"), "filesystem")
        self.assertIsNone(server_of("read_file"))
        self.assertIsNone(server_of("mcp__"))


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.servers = _FakeServers(self.root)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.bridges = []

    def tearDown(self):
        for bridge in self.bridges:
            bridge.close()
        live.stop_task("task-bridge")
        self._tmp.cleanup()

    def preset(self, name="filesystem", source=TOOL_SERVER, **overrides):
        preset = {"name": name, "transport": "stdio", "target": self.servers.command(source)}
        preset.update(overrides)
        return preset

    def open_bridge(self, *presets):
        bridge = McpBridge(list(presets))
        self.bridges.append(bridge)
        bridge.open()
        return bridge

    def registry(self, **options):
        settings = {"base_dir": str(self.workspace), "enabled_tools": []}
        settings.update(options)
        return ToolRegistry(**settings)

    def test_connected_tools_are_registered_under_the_server(self):
        bridge = self.open_bridge(self.preset())
        registry = self.registry()

        added = bridge.register(registry)

        self.assertEqual(added, 3)
        self.assertEqual(bridge.statuses[0]["tool_count"], 3)
        tool = registry.tools["mcp__filesystem__echo"]
        self.assertEqual(tool["permission"], PERMISSION_MCP)
        self.assertIn("MCP server filesystem", tool["description"])
        self.assertIn("Echo the text back", tool["description"])
        self.assertEqual(
            tool["parameters"],
            {"type": "object", "properties": {"text": {"type": "string"}}},
        )
        # A tool that ships no schema still has to look like an object to a provider.
        self.assertEqual(
            registry.tools["mcp__filesystem__no-schema"]["parameters"],
            {"type": "object", "properties": {}},
        )

    def test_a_call_reaches_the_remote_tool(self):
        bridge = self.open_bridge(self.preset())
        registry = self.registry()
        bridge.register(registry)

        self.assertEqual(
            registry.execute_tool("mcp__filesystem__echo", {"text": "hi"}), "echo: hi"
        )

    def test_a_remote_failure_fails_the_step(self):
        bridge = self.open_bridge(self.preset())
        registry = self.registry()
        bridge.register(registry)

        with self.assertRaises(McpToolError) as caught:
            registry.execute_tool("mcp__filesystem__fail", {})
        self.assertIn("it broke", str(caught.exception))

    def test_an_unsupported_transport_is_reported_and_skipped(self):
        bridge = self.open_bridge(self.preset(transport="sse", target="https://example.com/sse"))
        registry = self.registry()

        added = bridge.register(registry)

        self.assertEqual(added, 0)
        self.assertFalse(bridge.statuses[0]["ok"])
        self.assertIn("only stdio", bridge.statuses[0]["error"])
        self.assertEqual(registry.tools, {})

    def test_a_broken_preset_does_not_cost_the_other_servers(self):
        broken = {"name": "broken", "transport": "stdio", "target": "ngy-no-such-command-xyz"}
        bridge = self.open_bridge(broken, self.preset(name="working"))
        registry = self.registry()

        bridge.register(registry)

        by_name = {status["name"]: status for status in bridge.statuses}
        self.assertFalse(by_name["broken"]["ok"])
        self.assertTrue(by_name["working"]["ok"])
        self.assertIn("mcp__working__echo", registry.tools)

    def test_two_servers_with_the_same_name_keep_both_tools(self):
        bridge = self.open_bridge(self.preset(), self.preset())
        registry = self.registry()

        bridge.register(registry)

        names = [name for name in registry.tools if name.startswith("mcp__filesystem__echo")]
        self.assertEqual(len(names), 2)
        self.assertEqual(len(set(names)), 2)

    def test_closing_stops_the_servers(self):
        bridge = self.open_bridge(self.preset())
        registry = self.registry()
        bridge.register(registry)

        bridge.close()

        self.assertEqual(bridge.connected, [])
        with self.assertRaises(McpSessionError):
            registry.execute_tool("mcp__filesystem__echo", {"text": "hi"})


class LiveTest(unittest.TestCase):
    """The run-scoped registry the loop's teardown closes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.servers = _FakeServers(self.root)
        self.preset = {
            "name": "filesystem",
            "transport": "stdio",
            "target": self.servers.command(TOOL_SERVER),
        }

    def tearDown(self):
        live.stop_task("task-live")
        live.stop_task("")
        self._tmp.cleanup()

    def test_a_run_without_servers_allocates_nothing(self):
        self.assertIsNone(live.start_for_task("task-live", []))
        self.assertEqual(live.active("task-live"), [])

    def test_start_opens_and_stop_closes(self):
        bridge = live.start_for_task("task-live", [self.preset])

        self.assertIsNotNone(bridge)
        self.assertEqual(live.active("task-live"), [bridge])
        self.assertEqual(bridge.statuses[0]["tool_count"], 3)

        live.stop_task("task-live")

        self.assertEqual(live.active("task-live"), [])
        self.assertEqual(bridge.connected, [])

    def test_an_empty_key_is_a_key_too(self):
        # A CLI run has no task id; it still must not leak a server per turn.
        live.start_for_task(None, [self.preset])

        self.assertEqual(len(live.active("")), 1)

        live.stop_task("")

        self.assertEqual(live.active(""), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

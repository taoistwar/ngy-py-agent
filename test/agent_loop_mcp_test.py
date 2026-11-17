"""How a run's selected MCP servers reach the tool registry, and leave it.

Run from the repository root::

    uv run python test/agent_loop_mcp_test.py -v

The loop builds its registry in ``_build_runtime``, one step before the provider
schemas: a tool registered later would never be offered to the model. The teardown is
the other half - the loop has several exits, so the servers are closed by the same
decorator that already stops background sessions, and this pins that it still does.
"""

import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to the
# import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.agent_loop.runtime import _build_runtime, _reaps_task_sessions  # noqa: E402
from agent.mcp import live  # noqa: E402

ECHO_SERVER = r'''
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
                "serverInfo": {"name": "fake-tools", "version": "1.0.0"},
            },
        })
    elif method == "tools/list":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [{
                    "name": "echo",
                    "description": "Echo the text back",
                    "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
                }],
            },
        })
    elif request_id is not None:
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
'''


class AgentLoopMcpTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        script = self.root / "fake_server.py"
        script.write_text(ECHO_SERVER, encoding="utf-8")
        parts = [sys.executable, str(script)]
        command = (
            " ".join(f'"{part}"' for part in parts) if os.name == "nt" else shlex.join(parts)
        )
        self.preset = {"name": "filesystem", "transport": "stdio", "target": command}

    def tearDown(self):
        live.stop_task("task-mcp")
        live.stop_task("")
        self._tmp.cleanup()

    def build(self, **overrides):
        options = {
            "provider_name": "openai",
            "mode": "build",
            "base_dir": str(self.workspace),
            "task_id": "task-mcp",
            "agent_config": {"tool_names": None, "mcp_servers": [self.preset]},
        }
        options.update(overrides)
        return _build_runtime(**options)

    def test_selected_servers_become_registered_tools(self):
        _, registry, _provider, schemas = self.build()

        self.assertIn("mcp__filesystem__echo", registry.tools)
        names = [schema["function"]["name"] for schema in schemas]
        self.assertIn("mcp__filesystem__echo", names)
        self.assertEqual(
            registry.mcp_status,
            [{"name": "filesystem", "ok": True, "tool_count": 1, "error": ""}],
        )
        self.assertEqual(len(live.active("task-mcp")), 1)

    def test_without_selected_servers_nothing_is_opened(self):
        self.build(agent_config={"tool_names": None, "mcp_servers": []})

        self.assertEqual(live.active("task-mcp"), [])

    def test_a_mode_run_has_no_mcp_tools(self):
        # No agent config means the built-in mode registry, which knows no presets.
        _, registry, _provider, _schemas = self.build(agent_config=None)

        self.assertEqual([name for name in registry.tools if name.startswith("mcp__")], [])

    def test_tools_disabled_means_no_servers_are_spawned(self):
        _, registry, _provider, _schemas = self.build(enable_tools=False)

        self.assertEqual(registry.tools, {})
        self.assertEqual(live.active("task-mcp"), [])

    def test_a_broken_preset_does_not_fail_the_run(self):
        broken = {"name": "broken", "transport": "stdio", "target": "ngy-no-such-command-xyz"}

        _, registry, _provider, schemas = self.build(
            agent_config={"tool_names": None, "mcp_servers": [broken]}
        )

        self.assertEqual([name for name in registry.tools if name.startswith("mcp__")], [])
        self.assertFalse(registry.mcp_status[0]["ok"])
        self.assertIn("broken", registry.mcp_status[0]["name"])
        # The built-ins are untouched, so the run still has its normal tools.
        self.assertIn("read_file", registry.tools)
        self.assertNotIn("mcp__broken__echo", [schema["function"]["name"] for schema in schemas])

    def test_the_run_teardown_closes_the_servers(self):
        @_reaps_task_sessions
        def fake_run(task_id=None):
            live.start_for_task(task_id, [self.preset])
            return "done"

        self.assertEqual(fake_run(task_id="task-mcp"), "done")

        self.assertEqual(live.active("task-mcp"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

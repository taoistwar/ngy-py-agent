"""Tests for the tool catalog endpoint behind the tool management page.

Run from the repository root::

    uv run python test/tool_api_test.py -v

The process-wide task store is swapped for a temporary one so the built-in agent
configurations (build / ask / plan) are seeded from scratch and nothing here reads
or writes the developer's data.
"""

import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import app_state  # noqa: E402
import main  # noqa: E402
from agent.tools.permissions import PERMISSION_KINDS, SCOPES  # noqa: E402
from task_store import _SqliteTaskStore  # noqa: E402


class ToolApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        # The routes read the live state from ``app_state``, so that is where a
        # test has to swap it (see app_state's module docstring).
        self._previous_store = app_state.monitor_store
        self.store = _SqliteTaskStore(root / "tasks.db")
        app_state.monitor_store = self.store
        self.client = TestClient(main.app)

    def tearDown(self):
        app_state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    def fetch_tools(self):
        response = self.client.get("/api/tools")
        self.assertEqual(response.status_code, 200)
        return {item["name"]: item for item in response.json()["tools"]}

    # -------------------------------------------------------------------- tests

    def test_lists_every_builtin_tool(self):
        tools = self.fetch_tools()

        self.assertGreater(len(tools), 0)
        for name in ("read_file", "write_file", "exec_command", "get_current_time"):
            self.assertIn(name, tools)
        for name, item in tools.items():
            self.assertEqual(item["name"], name)
            self.assertTrue(item["description"], f"{name} has no description")
            self.assertIsInstance(item["parameters"], dict)

    def test_reports_permission_gate_and_implementation_file(self):
        tools = self.fetch_tools()

        self.assertEqual(tools["exec_command"]["permission"], "exec")
        self.assertEqual(tools["write_file"]["permission"], "write")
        self.assertEqual(tools["get_current_time"]["permission"], "none")

        for name, item in tools.items():
            self.assertIn(item["permission"], PERMISSION_KINDS, name)
            self.assertLessEqual(set(item["scopes"]), set(SCOPES), name)
            self.assertTrue(item["source"].startswith("agent/tools/"), name)
            self.assertTrue(item["source"].endswith(".py"), name)

    def test_reports_which_agents_enable_each_tool(self):
        tools = self.fetch_tools()

        # build allows every tool; ask only reads; plan has no tools at all.
        self.assertIn("build", tools["exec_command"]["agent_ids"])
        self.assertNotIn("ask", tools["exec_command"]["agent_ids"])
        self.assertNotIn("plan", tools["exec_command"]["agent_ids"])

        self.assertIn("ask", tools["read_file"]["agent_ids"])
        self.assertIn("build", tools["read_file"]["agent_ids"])
        self.assertNotIn("plan", tools["read_file"]["agent_ids"])
        self.assertEqual(tools["read_file"]["agent_ids"][0], "build")

        self.assertEqual(tools["exec_command"]["agent_ids"], ["build"])

    def test_new_agent_shows_up_as_a_user_of_its_tools(self):
        created = self.store.create_agent(
            {"name": "Reader", "tool_names": ["get_current_time"]}
        )
        tools = self.fetch_tools()

        self.assertIn(created["agent_id"], tools["get_current_time"]["agent_ids"])
        self.assertNotIn(created["agent_id"], tools["read_file"]["agent_ids"])

    # ------------------------------------------------------------------ running

    def run_tool(self, name, arguments):
        return self.client.post(f"/api/tools/{name}/test", json={"arguments": arguments})

    def test_runs_a_tool_with_the_given_arguments(self):
        response = self.run_tool("get_current_time", {"timezone": "UTC"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["tool"], "get_current_time")
        self.assertTrue(body["result"])
        self.assertEqual(body["error"], "")
        self.assertGreaterEqual(body["duration_ms"], 0)

    def test_tool_failure_comes_back_as_a_result(self):
        # ``read_file`` has a required argument, so calling it without one raises
        # inside the handler - which is what the caller is testing for.
        response = self.run_tool("read_file", {})
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(body["ok"])
        self.assertIn("read_file", body["error"])
        self.assertEqual(body["result"], "")

    def test_unknown_tool_is_a_404(self):
        response = self.run_tool("no_such_tool", {})

        self.assertEqual(response.status_code, 404)

    def test_tool_errors_are_returned_as_text_not_status_codes(self):
        # A path the file policy or the filesystem rejects is the tool reporting,
        # not the route failing: the dialog must be able to show it.
        body = self.run_tool("read_file", {"file_path": "does-not-exist.txt"}).json()

        self.assertTrue(body["ok"])
        self.assertIn("does-not-exist.txt", body["result"])


if __name__ == "__main__":
    unittest.main()

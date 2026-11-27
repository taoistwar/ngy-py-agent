"""Tests for the tool catalog endpoint behind the tool management page.

Run from the repository root::

    uv run python test/tool_api_test.py -v

The process-wide task store is swapped for a temporary one so the built-in agent
configurations (build / ask / plan) are seeded from scratch and nothing here reads
or writes the developer's data.
"""

import json
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

import main  # noqa: E402
from agent.tools.permissions import PERMISSION_KINDS, SCOPES  # noqa: E402
from agent.tools.spec import CATEGORY_KINDS, TRANSLATED_LOCALES  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402


class ToolApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        # The routes read the live state from ``commons.state``, so that is where a
        # test has to swap it (see commons.state's module docstring).
        self._previous_store = state.monitor_store
        self.store = _SqliteTaskStore(root / "tasks.db")
        state.monitor_store = self.store
        self.client = TestClient(main.app)

    def tearDown(self):
        state.monitor_store = self._previous_store
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
        for name in ("read_file", "write_file", "exec_command", "ask_user_question"):
            self.assertIn(name, tools)
        for name, item in tools.items():
            self.assertEqual(item["name"], name)
            self.assertTrue(item["description"], f"{name} has no description")
            self.assertIsInstance(item["parameters"], dict)

    def test_reports_permission_gate_and_implementation_file(self):
        tools = self.fetch_tools()

        self.assertEqual(tools["exec_command"]["permission"], "exec")
        self.assertEqual(tools["write_file"]["permission"], "write")
        self.assertEqual(tools["ask_user_question"]["permission"], "none")

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
            {"name": "Reader", "tool_names": ["glob"]}
        )
        tools = self.fetch_tools()

        self.assertIn(created["agent_id"], tools["glob"]["agent_ids"])
        self.assertNotIn(created["agent_id"], tools["read_file"]["agent_ids"])

    # ----------------------------------------------------------------- grouping

    def test_reports_a_known_category_per_tool(self):
        tools = self.fetch_tools()

        self.assertEqual(tools["read_file"]["category"], "file")
        self.assertEqual(tools["exec_command"]["category"], "shell")
        self.assertEqual(tools["computer_control"]["category"], "computer")
        self.assertEqual(tools["code_interpreter"]["category"], "compute")
        self.assertEqual(tools["ask_user_question"]["category"], "interaction")
        for name, item in tools.items():
            self.assertIn(item["category"], CATEGORY_KINDS, name)

    def test_the_planning_tools_share_the_task_group(self):
        # The admin page renders one section per category, and these seven are one
        # idea (this conversation's checklist, the project's board): listing them
        # under "other" would hide the set among the leftovers.
        tools = self.fetch_tools()
        planning = (
            "todo_write",
            "task_create",
            "task_update",
            "task_list",
            "task_get",
            "task_claim",
            "task_complete",
        )

        for name in planning:
            self.assertEqual(tools[name]["category"], "task", name)
        self.assertNotEqual(tools["read_file"]["category"], "task")

    # --------------------------------------------------------------- languages

    def test_ships_chinese_text_beside_the_english(self):
        read_file = self.fetch_tools()["read_file"]

        chinese = read_file["description_i18n"]["zh-CN"]
        self.assertTrue(chinese["description"])
        self.assertNotEqual(chinese["description"], read_file["description"])
        self.assertTrue(chinese["parameters"]["file_path"])

    def test_every_tool_ships_every_supported_locale(self):
        # The admin page picks a bundle by tag, so a tool that forgot one locale is
        # an English-only row on that language's page. Asserted per tool rather than
        # per locale so the failure names the tool that drifted.
        for name, item in self.fetch_tools().items():
            self.assertEqual(sorted(item["description_i18n"]), sorted(TRANSLATED_LOCALES), name)

    def test_every_parameter_has_text_in_every_locale(self):
        # A missing translation shows up as an English-only row, which is exactly the
        # drift this asserts against.
        for name, item in self.fetch_tools().items():
            for locale in TRANSLATED_LOCALES:
                text = item["description_i18n"].get(locale) or {}
                self.assertTrue(text.get("description"), f"{name} has no {locale} description")
                self.assertNotEqual(
                    text["description"], item["description"], f"{name} {locale} is still English"
                )
                for param in item["parameters"].get("properties") or {}:
                    self.assertTrue(
                        text.get("parameters", {}).get(param),
                        f"{name}.{param} has no {locale} text",
                    )

    def test_translations_stay_out_of_the_model_schema(self):
        # The model gets English only: a translation inside the schema would be
        # sent to the provider on every request.
        for name, item in self.fetch_tools().items():
            model_text = json.dumps(item["parameters"]) + item["description"]
            for locale in TRANSLATED_LOCALES:
                text = item["description_i18n"][locale]
                self.assertNotIn(text["description"], model_text, f"{name} leaks {locale}")
                for param_text in text["parameters"].values():
                    self.assertNotIn(param_text, model_text, f"{name} leaks {locale} parameters")

    # ------------------------------------------------------------------ running

    def run_tool(self, name, arguments):
        return self.client.post(f"/api/tools/{name}/test", json={"arguments": arguments})

    def test_runs_a_tool_with_the_given_arguments(self):
        response = self.run_tool("code_interpreter", {"code": "result = 2 + 2"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["tool"], "code_interpreter")
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

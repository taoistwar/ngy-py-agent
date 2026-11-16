"""Integration tests for the deny-list endpoints (ADR 0024).

Run from the repository root::

    uv run python test/denylist_api_test.py -v

These cover what the unit tests cannot reach: the admin page's create/delete
round trip, validation of a posted rule through the same parser the file uses,
and the running task noticing a new rule without a restart.

The process-wide store is swapped for a temporary file in ``setUp``, so nothing
here reads or writes the developer's data.
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

import main  # noqa: E402
from agent.tools.denylist import ToolDenyList  # noqa: E402
from commons import state  # noqa: E402

ENDPOINT = "/api/admin/denylist"


class DenyListApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self._previous = state.denylist_store
        self.denylist = ToolDenyList(self.root / "denylist.json")
        state.denylist_store = self.denylist
        self.client = TestClient(main.app)

    def tearDown(self):
        state.denylist_store = self._previous
        self._tmp.cleanup()

    def create(self, **payload):
        return self.client.post(ENDPOINT, json=payload)

    def rules(self):
        return self.client.get(ENDPOINT).json()["rules"]

    # ---------------------------------------------------------------- listing

    def test_an_empty_file_is_an_empty_list_with_its_path(self):
        body = self.client.get(ENDPOINT).json()

        self.assertEqual(body["rules"], [])
        self.assertEqual(body["problems"], [])
        self.assertTrue(body["path"].endswith("denylist.json"))

    # --------------------------------------------------------------- creating

    def test_a_fixed_rule_round_trips(self):
        created = self.create(
            id="no-rm",
            tool="exec_command",
            args=[{"field": "command", "match": "fixed", "value": "rm -rf /"}],
            reason="no",
        )

        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["id"], "no-rm")
        self.assertEqual(created.json()["tool"], {"match": "fixed", "value": "exec_command"})
        self.assertEqual(self.rules()[0]["reason"], "no")
        self.assertTrue((self.root / "denylist.json").exists())

    def test_a_regex_rule_keeps_the_pattern(self):
        created = self.create(
            tool="exec_command",
            tool_match="fixed",
            args=[{"field": "command", "match": "regex", "value": r"git\s+push.*--force"}],
        )

        self.assertEqual(created.status_code, 200)
        argument = created.json()["args"][0]
        self.assertEqual(argument["match"], "regex")
        self.assertEqual(argument["pattern"], r"git\s+push.*--force")

    def test_a_rule_without_arguments_blocks_the_whole_tool(self):
        created = self.create(tool="computer_control")

        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["args"], [])

    def test_a_missing_id_is_generated(self):
        created = self.create(tool="exec_command")

        self.assertTrue(created.json()["id"].startswith("ui-"))

    def test_posting_the_same_id_replaces_the_rule(self):
        self.create(id="one", tool="exec_command", reason="first")
        self.create(id="one", tool="read_file", reason="second")

        rules = self.rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["tool"], {"match": "fixed", "value": "read_file"})
        self.assertEqual(rules[0]["reason"], "second")

    def test_a_bad_pattern_is_rejected_and_nothing_is_written(self):
        response = self.create(
            tool="exec_command",
            args=[{"field": "command", "match": "regex", "value": "["}],
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.rules(), [])

    def test_an_unknown_match_kind_is_rejected(self):
        response = self.create(tool="exec_command", tool_match="glob")

        self.assertEqual(response.status_code, 400)

    def test_an_empty_value_is_rejected(self):
        response = self.create(
            tool="exec_command",
            args=[{"field": "command", "match": "fixed", "value": "   "}],
        )

        self.assertEqual(response.status_code, 400)

    def test_an_empty_field_name_is_rejected(self):
        response = self.create(
            tool="exec_command",
            args=[{"field": "  ", "match": "fixed", "value": "x"}],
        )

        self.assertEqual(response.status_code, 400)

    # --------------------------------------------------------------- deleting

    def test_delete_removes_the_rule(self):
        self.create(id="one", tool="exec_command")

        removed = self.client.delete(ENDPOINT, params={"id": "one"})

        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.rules(), [])

    def test_deleting_an_unknown_rule_is_not_found(self):
        response = self.client.delete(ENDPOINT, params={"id": "nope"})

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------- enforcement

    def test_a_running_task_sees_a_new_rule_on_its_next_call(self):
        # A task that started before the rule existed: it holds its own list over
        # the same file and has already read it once (that is what fills the cache).
        running = ToolDenyList(self.root / "denylist.json")
        self.assertIsNone(running.match("exec_command", {"command": "rm -rf /"}))

        self.create(
            id="no-rm",
            tool="exec_command",
            args=[{"field": "command", "match": "fixed", "value": "rm -rf /"}],
        )

        self.assertIsNotNone(running.match("exec_command", {"command": "rm -rf /"}))

    def test_a_rule_removed_from_the_page_stops_blocking(self):
        self.create(
            id="no-rm",
            tool="exec_command",
            args=[{"field": "command", "match": "fixed", "value": "rm -rf /"}],
        )
        running = ToolDenyList(self.root / "denylist.json")
        self.assertIsNotNone(running.match("exec_command", {"command": "rm -rf /"}))

        self.client.delete(ENDPOINT, params={"id": "no-rm"})

        self.assertIsNone(running.match("exec_command", {"command": "rm -rf /"}))


if __name__ == "__main__":
    unittest.main()

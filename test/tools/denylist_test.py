"""Tests for the tool deny-list (ADR 0024).

Run from the repository root::

    uv run python test/tools/denylist_test.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.models import EventCategory, ToolOutcome  # noqa: E402
from agent.tools.denylist import (  # noqa: E402
    DENYLIST_ENV,
    MATCH_FIXED,
    MATCH_REGEX,
    REASON_DENYLIST,
    REASON_DENYLIST_ERROR,
    MatchSpec,
    ToolDenyList,
    default_denylist_path,
    parse_rules,
)
from agent.tools.registry import ToolRegistry  # noqa: E402


def build_list(rules):
    """A deny-list whose rules came through the parser, like the file's would."""
    parsed, problems = parse_rules({"rules": rules})
    return ToolDenyList(rules=parsed), problems


class MatchSpecTest(unittest.TestCase):
    def test_fixed_matches_the_whole_value_only(self):
        spec = MatchSpec(MATCH_FIXED, "rm -rf /")

        self.assertTrue(spec.matches("rm -rf /"))
        self.assertFalse(spec.matches("rm -rf / --no-preserve-root"))
        self.assertFalse(spec.matches("echo rm -rf /"))

    def test_regex_searches_anywhere_in_the_value(self):
        spec = MatchSpec(MATCH_REGEX, r"git\s+push\b.*--force")

        self.assertTrue(spec.matches("git push origin main --force"))
        self.assertFalse(spec.matches("git push origin main"))

    def test_payload_keeps_the_match_kind(self):
        self.assertEqual(
            MatchSpec(MATCH_FIXED, "x").to_payload(), {"match": "fixed", "value": "x"}
        )
        self.assertEqual(
            MatchSpec(MATCH_REGEX, "^x").to_payload(), {"match": "regex", "pattern": "^x"}
        )


class ParseRulesTest(unittest.TestCase):
    def test_a_bare_string_is_a_fixed_match(self):
        rules, problems = parse_rules(
            {"rules": [{"tool": "exec_command", "args": {"command": "rm -rf /"}}]}
        )

        self.assertEqual(problems, ())
        self.assertEqual(rules[0].tool.kind, MATCH_FIXED)
        self.assertEqual(rules[0].arguments[0].spec.kind, MATCH_FIXED)

    def test_a_rule_without_args_blocks_the_whole_tool(self):
        rules, _ = parse_rules({"rules": [{"id": "no-desktop", "tool": "computer_control"}]})

        self.assertEqual(rules[0].rule_id, "no-desktop")
        self.assertEqual(rules[0].arguments, ())

    def test_missing_id_falls_back_to_the_index(self):
        rules, _ = parse_rules({"rules": [{"tool": "exec_command"}]})

        self.assertEqual(rules[0].rule_id, "rule[0]")

    def test_argument_list_form_is_accepted(self):
        rules, problems = parse_rules(
            {
                "rules": [
                    {
                        "tool": "exec_command",
                        "args": [{"field": "command", "match": "regex", "pattern": "^git push"}],
                    }
                ]
            }
        )

        self.assertEqual(problems, ())
        self.assertEqual(rules[0].arguments[0].field, "command")
        self.assertEqual(rules[0].arguments[0].spec.kind, MATCH_REGEX)

    def test_a_broken_rule_is_dropped_and_reported(self):
        rules, problems = parse_rules(
            {
                "rules": [
                    {"tool": "exec_command", "args": {"command": {"match": "regex", "pattern": "["}}},
                    {"tool": "exec_command", "args": {"command": {"match": "glob", "value": "x"}}},
                    {"args": {"command": "x"}},
                    {"tool": "exec_command", "args": {"command": {"match": "fixed", "value": ""}}},
                    {"tool": "exec_command", "args": {"command": "ok"}},
                ]
            }
        )

        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].arguments[0].spec.text, "ok")
        self.assertEqual(len(problems), 4)

    def test_a_non_list_payload_is_reported_not_guessed(self):
        rules, problems = parse_rules({"rules": "everything"})

        self.assertEqual(rules, ())
        self.assertEqual(len(problems), 1)


class RuleMatchingTest(unittest.TestCase):
    def test_all_argument_matchers_must_hold(self):
        denylist, _ = build_list(
            [
                {
                    "id": "no-recursive-delete",
                    "tool": "exec_command",
                    "args": {
                        "command": {"match": "regex", "pattern": "^rm "},
                        "description": {"match": "regex", "pattern": "cleanup"},
                    },
                }
            ]
        )

        both = denylist.match("exec_command", {"command": "rm -rf build", "description": "cleanup"})
        only_command = denylist.match("exec_command", {"command": "rm -rf build"})
        only_description = denylist.match("exec_command", {"description": "cleanup"})

        self.assertIsNotNone(both)
        self.assertEqual(both.rule_id, "no-recursive-delete")
        self.assertEqual(both.fields, ("command", "description"))
        self.assertIsNone(only_command)
        self.assertIsNone(only_description)

    def test_a_missing_argument_never_matches(self):
        denylist, _ = build_list([{"tool": "write_file", "args": {"file_path": ".env"}}])

        self.assertIsNone(denylist.match("write_file", {}))

    def test_a_scalar_literal_matches_its_json_form(self):
        denylist, _ = build_list([{"tool": "exec_command", "args": {"timeout": 30}}])

        self.assertIsNotNone(denylist.match("exec_command", {"timeout": 30}))
        self.assertIsNone(denylist.match("exec_command", {"timeout": 31}))

    def test_the_fixed_object_accepts_a_non_string_value(self):
        denylist, _ = build_list(
            [{"tool": "exec_command", "args": {"timeout": {"match": "fixed", "value": 30}}}]
        )

        self.assertIsNotNone(denylist.match("exec_command", {"timeout": 30}))
        self.assertIsNone(denylist.match("exec_command", {"timeout": 31}))

    def test_list_values_match_their_json_form(self):
        denylist, _ = build_list(
            [
                {
                    "tool": "computer_control",
                    "args": {
                        "urls": ["https://example.com"],
                        "action": {"match": "regex", "pattern": "launch"},
                    },
                }
            ]
        )

        self.assertIsNotNone(
            denylist.match(
                "computer_control",
                {"urls": ["https://example.com"], "action": "launch_app"},
            )
        )
        self.assertIsNone(
            denylist.match(
                "computer_control",
                {"urls": ["https://other.test"], "action": "launch_app"},
            )
        )

    def test_a_dotted_field_reaches_into_nested_arguments(self):
        denylist, _ = build_list([{"tool": "computer_control", "args": {"target.name": "cmd"}}])

        self.assertIsNotNone(denylist.match("computer_control", {"target": {"name": "cmd"}}))
        self.assertIsNone(denylist.match("computer_control", {"target": {"name": "other"}}))

    def test_a_regex_tool_matcher_covers_a_family_of_tools(self):
        denylist, _ = build_list(
            [{"id": "no-desktop", "tool": {"match": "regex", "pattern": "^computer_"}}]
        )

        self.assertIsNotNone(denylist.match("computer_control", {}))
        self.assertIsNotNone(denylist.match("computer_observe", {}))
        self.assertIsNone(denylist.match("exec_command", {}))

    def test_the_rule_reason_travels_with_the_match(self):
        denylist, _ = build_list(
            [{"id": "no-force", "tool": "exec_command", "args": {"command": "--force"}, "reason": "no"}]
        )

        self.assertEqual(denylist.match("exec_command", {"command": "--force"}).reason, "no")


class FileBackedDenyListTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "denylist.json"

    def write(self, payload):
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def test_a_missing_file_means_no_rules(self):
        denylist = ToolDenyList(path=self.path)

        self.assertIsNone(denylist.match("exec_command", {"command": "rm -rf /"}))
        self.assertEqual(denylist.problems, [])

    def test_a_corrupt_file_is_reported_and_blocks_nothing(self):
        self.path.write_text("{not json", encoding="utf-8")
        denylist = ToolDenyList(path=self.path)

        self.assertIsNone(denylist.match("exec_command", {}))
        self.assertEqual(len(denylist.problems), 1)

    def test_an_edit_takes_effect_on_the_next_call(self):
        self.write({"rules": []})
        denylist = ToolDenyList(path=self.path)
        self.assertIsNone(denylist.match("exec_command", {"command": "rm -rf /"}))

        self.write({"rules": [{"tool": "exec_command", "args": {"command": "rm -rf /"}}]})

        self.assertIsNotNone(denylist.match("exec_command", {"command": "rm -rf /"}))

    def test_list_exposes_the_parsed_rules(self):
        self.write({"rules": [{"id": "a", "tool": "exec_command"}]})
        rules = ToolDenyList(path=self.path).list()

        self.assertEqual([rule.rule_id for rule in rules], ["a"])

    def test_the_default_path_can_be_relocated(self):
        with mock.patch.dict(os.environ, {DENYLIST_ENV: "custom/denylist.json"}):
            self.assertEqual(default_denylist_path(), Path("custom/denylist.json"))


class RegistryDenylistTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.calls = []

    def build(self, rules, permission="none"):
        denylist, _ = build_list(rules)
        registry = ToolRegistry(
            base_dir=str(self.root), enabled_tools=[], denylist=denylist
        )
        registry.register_tool(
            name="exec_command",
            function=lambda **kwargs: self.calls.append(kwargs) or {"ok": True},
            description="",
            parameters={},
            permission=permission,
        )
        return registry

    def test_a_deny_listed_call_never_reaches_the_tool(self):
        registry = self.build([{"id": "no-rm", "tool": "exec_command", "args": {"command": "rm -rf /"}}])

        outcome = registry.execute_tool("exec_command", {"command": "rm -rf /"})

        self.assertIsInstance(outcome, ToolOutcome)
        self.assertEqual(outcome.event_category, EventCategory.PERMISSION_DECISION)
        self.assertIn("no-rm", outcome.model_text)
        self.assertEqual(outcome.details["reason"], REASON_DENYLIST)
        self.assertEqual(outcome.details["rule"], "no-rm")
        self.assertEqual(self.calls, [])

    def test_a_call_outside_the_rule_still_runs(self):
        registry = self.build([{"tool": "exec_command", "args": {"command": "rm -rf /"}}])

        registry.execute_tool("exec_command", {"command": "ls"})

        self.assertEqual(self.calls, [{"command": "ls"}])

    def test_the_deny_list_wins_over_the_permission_gate(self):
        asked = []

        class Broker:
            def check(self, *args, **kwargs):
                asked.append(args[0])
                return None

        registry = self.build(
            [{"tool": "exec_command", "args": {"command": "rm -rf /"}}], permission="exec"
        )
        registry.permission_broker = Broker()

        outcome = registry.execute_tool("exec_command", {"command": "rm -rf /"})

        self.assertIsInstance(outcome, ToolOutcome)
        self.assertEqual(asked, [])
        self.assertEqual(self.calls, [])

    def test_a_registry_without_an_explicit_list_uses_the_configured_file(self):
        rules_path = self.root / "denylist.json"
        rules_path.write_text(
            json.dumps({"rules": [{"tool": "exec_command", "args": {"command": "rm -rf /"}}]}),
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {DENYLIST_ENV: str(rules_path)}):
            registry = ToolRegistry(base_dir=str(self.root), enabled_tools=[])
        registry.register_tool(
            name="exec_command",
            function=lambda **kwargs: self.calls.append(kwargs),
            description="",
            parameters={},
        )

        outcome = registry.execute_tool("exec_command", {"command": "rm -rf /"})

        self.assertIsInstance(outcome, ToolOutcome)
        self.assertEqual(outcome.details["reason"], REASON_DENYLIST)
        self.assertEqual(self.calls, [])

    def test_a_deny_list_that_raises_blocks_the_call(self):
        class Broken:
            def match(self, tool, arguments):
                raise RuntimeError("rules unreadable")

        registry = ToolRegistry(
            base_dir=str(self.root), enabled_tools=[], denylist=Broken()
        )
        registry.register_tool(
            name="exec_command",
            function=lambda **kwargs: self.calls.append(kwargs),
            description="",
            parameters={},
        )

        outcome = registry.execute_tool("exec_command", {"command": "ls"})

        self.assertIsInstance(outcome, ToolOutcome)
        self.assertEqual(outcome.details["reason"], REASON_DENYLIST_ERROR)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()

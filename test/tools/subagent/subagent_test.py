"""Tests for the ``subagent`` tool contract.

The tool is the thin half: it validates the brief and hands it to the run's runner.
What it must get right is the "nobody can delegate here" answer, because a run without
a runner (a library caller, a test) must tell the model so rather than raise.

Run from the repository root::

    uv run python test/tools/subagent/subagent_test.py -v
"""

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tool_registry import ToolRegistry  # noqa: E402
from agent.tools.bindings import ToolBindings  # noqa: E402
from agent.tools.subagent import (  # noqa: E402
    NO_RUNNER_TEXT,
    SubagentError,
    make_subagent_tool,
)
from agent.tools.subagent.spec import build_spec  # noqa: E402


class SubagentToolTest(unittest.TestCase):
    def test_returns_the_runner_report(self):
        tool = make_subagent_tool(lambda prompt: f"report: {prompt}")

        self.assertEqual(tool("check a.txt"), "report: check a.txt")

    def test_says_so_when_no_runner_is_bound(self):
        tool = make_subagent_tool(None)

        self.assertEqual(tool("check a.txt"), NO_RUNNER_TEXT)

    def test_a_runner_that_answers_none_also_means_unavailable(self):
        tool = make_subagent_tool(lambda prompt: None)

        self.assertEqual(tool("check a.txt"), NO_RUNNER_TEXT)

    def test_blank_prompt_is_refused(self):
        tool = make_subagent_tool(lambda prompt: "never runs")

        with self.assertRaises(SubagentError):
            tool("   ")

    def test_the_spec_leaves_permissions_to_the_child_tools(self):
        spec = build_spec(ToolBindings())

        self.assertEqual(spec.name, "subagent")
        # Delegating is not itself privileged: every tool the child calls passes its
        # own gate, which is where the confirmation belongs.
        self.assertEqual(spec.permission, "none")
        self.assertEqual(spec.parameters["required"], ["prompt"])
        self.assertEqual(spec.category, "other")


class RegistryBindingTest(unittest.TestCase):
    def test_a_registry_without_a_runner_answers_unavailable(self):
        registry = ToolRegistry(enabled_tools=["subagent"])

        result = registry.execute_tool("subagent", {"prompt": "check a.txt"})

        self.assertEqual(result, NO_RUNNER_TEXT)

    def test_a_registry_runs_the_injected_runner(self):
        registry = ToolRegistry(enabled_tools=["subagent"])
        seen = []
        registry.subagent_runner = lambda prompt: seen.append(prompt) or "final report"

        result = registry.execute_tool("subagent", {"prompt": "check a.txt"})

        self.assertEqual(result, "final report")
        self.assertEqual(seen, ["check a.txt"])


if __name__ == "__main__":
    unittest.main()

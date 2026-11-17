"""Tests for the prompt section that reports a run's MCP servers.

Run from the repository root::

    uv run python test/agent/mcp/mcp_prompt_test.py -v
"""

import sys
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to the
# import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.mcp.prompt import append_server_status  # noqa: E402


class AppendServerStatusTest(unittest.TestCase):
    def test_a_run_without_servers_keeps_its_prompt_byte_for_byte(self):
        self.assertEqual(append_server_status("base prompt", []), "base prompt")

    def test_a_connected_server_is_named_with_its_tool_count(self):
        prompt = append_server_status(
            "base", [{"name": "filesystem", "ok": True, "tool_count": 2, "error": ""}]
        )

        self.assertTrue(prompt.startswith("base\n"))
        self.assertIn("## MCP servers", prompt)
        self.assertIn("- filesystem: connected, 2 tools available.", prompt)

    def test_a_failed_server_says_why_and_that_its_tools_are_missing(self):
        prompt = append_server_status(
            "base",
            [{"name": "filesystem", "ok": False, "tool_count": 0, "error": "npm 404"}],
        )

        self.assertIn("- filesystem: not connected, its tools are unavailable (npm 404)", prompt)

    def test_the_section_explains_how_the_tools_are_named(self):
        prompt = append_server_status("base", [{"name": "fs", "ok": True, "tool_count": 1}])

        self.assertIn("mcp__<server>__<tool>", prompt)

    def test_a_multiline_error_is_kept_on_one_line(self):
        prompt = append_server_status(
            "base",
            [{"name": "fs", "ok": False, "error": "first line\nstderr:\nsecond"}],
        )

        self.assertNotIn("stderr:\nsecond", prompt)
        self.assertIn("first line stderr: second", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)

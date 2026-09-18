"""Tests for tool dispatch error handling.

Run from the repository root::

    uv run python test/tools/registry_test.py -v
"""

import json
import sys
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.registry import ToolRegistry  # noqa: E402


class ExecuteToolTest(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry(enabled_tools=[])

    def test_serializes_dict_result(self):
        self.registry.register_tool(
            name="echo", function=lambda value: {"value": value}, description="", parameters={}
        )

        self.assertEqual(json.loads(self.registry.execute_tool("echo", {"value": 1})), {"value": 1})

    def test_tool_exception_propagates(self):
        def boom():
            raise RuntimeError("upstream unavailable")

        self.registry.register_tool(name="boom", function=boom, description="", parameters={})

        with self.assertRaises(RuntimeError):
            self.registry.execute_tool("boom", {})

    def test_unknown_tool_reports_error_payload(self):
        payload = json.loads(self.registry.execute_tool("nope", {}))

        self.assertIn("not found", payload["error"])


if __name__ == "__main__":
    unittest.main()

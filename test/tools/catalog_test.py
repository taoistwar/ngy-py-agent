"""Tests for the built-in tool catalog.

The catalog is the one place that answers "which tools exist, and in what order": it
is what the model's tool list is built from, so a tool that silently drops out of the
list (or moves) should fail here rather than in production.

Run from the repository root::

    uv run python test/tools/catalog_test.py -v
"""

import sys
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.bindings import ToolBindings  # noqa: E402
from agent.tools.catalog import build_all_specs  # noqa: E402

EXPECTED_ORDER = (
    "get_current_temperature",
    "get_current_time",
    "convert_currency",
    "code_interpreter",
    "read_file",
    "edit_file",
    "write_file",
    "exec_command",
    "write_stdin",
)


class CatalogTest(unittest.TestCase):
    def test_every_built_in_tool_is_listed_once_in_a_stable_order(self):
        specs = build_all_specs(ToolBindings())

        self.assertEqual(tuple(spec.name for spec in specs), EXPECTED_ORDER)

    def test_each_spec_declares_a_usable_contract(self):
        for spec in build_all_specs(ToolBindings()):
            with self.subTest(tool=spec.name):
                self.assertTrue(spec.description.strip())
                self.assertEqual(spec.parameters["type"], "object")
                self.assertTrue(callable(spec.handler))
                self.assertTrue(spec.scopes)

    def test_each_run_gets_its_own_handlers(self):
        # ``build_spec`` is a factory per call, so two runs cannot share a bound
        # workspace or a task id through the catalog.
        first = {spec.name: spec for spec in build_all_specs(ToolBindings(task_id="task-1"))}
        second = {spec.name: spec for spec in build_all_specs(ToolBindings(task_id="task-2"))}

        self.assertIsNot(first["exec_command"].handler, second["exec_command"].handler)
        self.assertIsNot(first["write_stdin"].handler, second["write_stdin"].handler)


if __name__ == "__main__":
    unittest.main()

"""The six ``task_*`` tools, from the model's point of view.

Each tool is a single step of the same story, so the story is what is tested here: a
model creates the nodes, sequences them, is refused when it tries to start blocked
work, completes the first one, is told what that unblocked, and cannot finish a task
another conversation claimed.

Run from the repository root::

    uv run python test/tools/task_tools_test.py -v
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
from agent.tools.permissions import PERMISSION_NONE  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402
from agent.tools.task_claim import spec as task_claim  # noqa: E402
from agent.tools.task_complete import spec as task_complete  # noqa: E402
from agent.tools.task_create import spec as task_create  # noqa: E402
from agent.tools.task_get import spec as task_get  # noqa: E402
from agent.tools.task_list import spec as task_list  # noqa: E402
from agent.tools.task_store import MemoryBoardStore, TaskBoard  # noqa: E402
from agent.tools.task_update import spec as task_update  # noqa: E402

SPECS = (task_create, task_update, task_list, task_get, task_claim, task_complete)
NAMES = (
    "task_create",
    "task_update",
    "task_list",
    "task_get",
    "task_claim",
    "task_complete",
)


class DeclarationTest(unittest.TestCase):
    def test_every_tool_declares_an_object_schema_and_asks_for_nothing(self):
        self.assertEqual(tuple(spec.NAME for spec in SPECS), NAMES)
        for spec in SPECS:
            with self.subTest(tool=spec.NAME):
                built = spec.build_spec(ToolBindings())
                self.assertEqual(built.name, spec.NAME)
                self.assertEqual(built.parameters["type"], "object")
                self.assertTrue(built.description.strip())
                # A board row is a note in our own database: nothing to confirm.
                self.assertEqual(built.permission, PERMISSION_NONE)

    def test_the_two_writes_require_their_identifiers(self):
        update = task_update.build_spec(ToolBindings()).parameters
        claim = task_claim.build_spec(ToolBindings()).parameters

        self.assertEqual(update["required"], ["task_id", "add_blocked_by"])
        self.assertEqual(claim["required"], ["task_id"])


class BoardFlowTest(unittest.TestCase):
    """One conversation building a graph, in the order the model would."""

    def setUp(self):
        self.registry = ToolRegistry(
            task_board=TaskBoard(MemoryBoardStore(), "workspace:ws1", "session-1")
        )

    def call(self, name, **arguments):
        return self.registry.execute_tool(name, arguments)

    def create(self, subject, description=""):
        outcome = self.call("task_create", subject=subject, description=description)
        self.assertTrue(outcome.details["success"], outcome.model_text)
        return outcome.details["task"]["task_id"]

    def board(self):
        return {item["task_id"]: item for item in self.call("task_list").details["tasks"]}

    def test_a_created_task_reports_its_id_and_starts_unowned(self):
        task_id = self.create("setup database schema", "tables first")

        stored = self.registry.task_board.get(task_id)
        self.assertRegex(task_id, r"^task_[0-9a-f]{8}$")
        self.assertEqual(stored["status"], "pending")
        self.assertIsNone(stored["owner"])
        self.assertEqual(stored["description"], "tables first")

    def test_an_empty_subject_is_refused_and_nothing_is_created(self):
        outcome = self.call("task_create", subject="   ")

        self.assertFalse(outcome.details["success"])
        self.assertIn("subject", outcome.model_text)
        self.assertEqual(self.registry.task_board.list(), [])

    def test_edges_sequence_the_board_and_blocked_work_cannot_be_claimed(self):
        schema = self.create("setup schema")
        endpoints = self.create("create API endpoints")
        tests = self.create("write tests")

        self.call("task_update", task_id=endpoints, add_blocked_by=[schema])
        self.call("task_update", task_id=tests, add_blocked_by=[endpoints])

        refused = self.call("task_claim", task_id=tests)
        self.assertFalse(refused.details["success"])
        self.assertEqual(refused.details["reason"], "blocked")
        self.assertIn(endpoints, refused.model_text)

        self.assertTrue(self.call("task_claim", task_id=schema).details["success"])
        self.assertEqual(self.board()[schema]["owner"], "session-1")

    def test_completing_reports_what_it_unblocked(self):
        schema = self.create("setup schema")
        endpoints = self.create("create API endpoints")
        docs = self.create("write docs")
        self.call("task_update", task_id=endpoints, add_blocked_by=[schema])
        self.call("task_update", task_id=docs, add_blocked_by=[schema])
        self.call("task_claim", task_id=schema)

        outcome = self.call("task_complete", task_id=schema)

        self.assertTrue(outcome.details["success"])
        self.assertEqual(set(outcome.details["unblocked"]), {endpoints, docs})
        self.assertIn("Unblocked:", outcome.model_text)
        self.assertEqual(self.board()[schema]["status"], "completed")

    def test_another_conversation_cannot_complete_a_claimed_task(self):
        task_id = self.create("setup schema")
        self.call("task_claim", task_id=task_id)
        # Same board (same workspace), different conversation: the claim is not theirs.
        other = ToolRegistry(task_board=TaskBoard(self.registry.task_board.store, "workspace:ws1", "session-2"))

        outcome = other.execute_tool("task_complete", {"task_id": task_id})

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "owner_mismatch")
        self.assertEqual(self.registry.task_board.get(task_id)["status"], "in_progress")

    def test_a_task_read_back_carries_the_description_a_follow_up_needs(self):
        task_id = self.create("create API endpoints", "CRUD over the schema")

        outcome = self.call("task_get", task_id=task_id)

        self.assertTrue(outcome.details["success"])
        self.assertIn("CRUD over the schema", outcome.model_text)
        self.assertIn("pending", outcome.model_text)

    def test_an_unknown_id_is_an_error_with_a_reason(self):
        for name in ("task_get", "task_claim", "task_complete"):
            with self.subTest(tool=name):
                outcome = self.call(name, task_id="task_00000000")
                self.assertFalse(outcome.details["success"])
                self.assertEqual(outcome.details["reason"], "not_found")

    def test_the_list_reports_the_board_and_its_derived_state(self):
        schema = self.create("setup schema")
        endpoints = self.create("create API endpoints")
        self.call("task_update", task_id=endpoints, add_blocked_by=[schema])

        outcome = self.call("task_list")

        counts = outcome.details["counts"]
        self.assertEqual(counts, {"total": 2, "pending": 2, "in_progress": 0, "completed": 0})
        self.assertTrue(outcome.details["tasks"][0]["ready"])
        self.assertEqual(outcome.details["tasks"][1]["blocked_by_subjects"], ["setup schema"])


if __name__ == "__main__":
    unittest.main()

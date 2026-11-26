"""Tests for the ``todo_write`` tool: declaration, validation, rendering, binding.

Three decisions are pinned here because a future reader could "fix" them by accident:

* a call **replaces** the whole list, so the stored plan is always what the model
  sent last - completed steps included;
* the plan is **session** scoped: two runs bound to the same session see the same
  list, which is what makes a follow-up task continue the checklist;
* the limits (20 items, one step in progress) are enforced, unlike the style
  numbers in ``ask_user_question``: a plan the UI cannot render is a bad plan.

Run from the repository root::

    uv run python test/tools/todo_write/todo_write_test.py -v
"""

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.bindings import ToolBindings  # noqa: E402
from agent.tools.permissions import PERMISSION_NONE  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402
from agent.tools.todo_store import MemoryTodoStore, TodoBoard  # noqa: E402
from agent.tools.todo_write import (  # noqa: E402
    MAX_TODOS,
    STATUSES,
    TODO_WRITE_DESCRIPTION,
    TODO_WRITE_PARAMETERS,
    TODO_WRITE_TOOL_NAME,
    make_todo_write_tool,
)
from agent.tools.todo_write import spec as todo_write_spec  # noqa: E402

PLAN = [
    {"content": "Read the parser", "status": "completed"},
    {"content": "Write the failing test", "status": "in_progress"},
    {"content": "Fix the parser", "status": "pending"},
]


class FakeStore:
    """Records what was saved and replays it, like the database store does."""

    def __init__(self, items: List[Dict[str, Any]] | None = None) -> None:
        self.items = list(items or [])
        self.saves: List[Tuple[str, List[Dict[str, Any]], str]] = []

    def load(self, session_id: str) -> List[Dict[str, Any]]:
        return list(self.items)

    def save(self, session_id: str, todos: List[Dict[str, Any]], task_id: str) -> None:
        self.saves.append((session_id, list(todos), task_id))
        self.items = list(todos)


class BrokenStore:
    def load(self, session_id: str) -> List[Dict[str, Any]]:
        raise RuntimeError("database is closed")

    def save(self, session_id: str, todos: List[Dict[str, Any]], task_id: str) -> None:
        raise RuntimeError("database is closed")


class DeclarationTest(unittest.TestCase):
    def test_the_tool_is_named_after_what_the_model_calls(self):
        self.assertEqual(TODO_WRITE_TOOL_NAME, "todo_write")

    def test_the_schema_describes_the_three_statuses(self):
        todos = TODO_WRITE_PARAMETERS["properties"]["todos"]

        self.assertEqual(TODO_WRITE_PARAMETERS["required"], ["todos"])
        self.assertEqual(todos["type"], "array")
        self.assertEqual(todos["items"]["required"], ["content", "status"])
        self.assertEqual(todos["items"]["properties"]["status"]["enum"], list(STATUSES))

    def test_the_description_states_the_contract(self):
        for clause in (
            "replaces the whole list",
            "exactly one step in progress",
            "belongs to the conversation",
            "At most 20",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, TODO_WRITE_DESCRIPTION)


class SpecTest(unittest.TestCase):
    def test_the_spec_never_asks_for_confirmation(self):
        spec = todo_write_spec.build_spec(ToolBindings())

        self.assertEqual(spec.name, TODO_WRITE_TOOL_NAME)
        # A plan is a note to itself: no machine, no network, nothing to confirm.
        self.assertEqual(spec.permission, PERMISSION_NONE)
        self.assertEqual(spec.parameters, TODO_WRITE_PARAMETERS)
        self.assertEqual(len(spec.description_i18n), 5)

    def test_two_runs_bound_to_one_session_continue_the_same_plan(self):
        store = MemoryTodoStore()
        first = todo_write_spec.build_spec(
            ToolBindings(session_id="s1", task_id="t1", todo_board=TodoBoard(store, "s1", "t1"))
        )
        second = todo_write_spec.build_spec(
            ToolBindings(session_id="s1", task_id="t2", todo_board=TodoBoard(store, "s1", "t2"))
        )

        first.handler(todos=PLAN)
        # The second task sees the plan the first one wrote: the list is the
        # conversation's, not the call's.
        second.handler(todos=[{"content": "Next step", "status": "in_progress"}])

        self.assertEqual(store.load("s1"), [{"content": "Next step", "status": "in_progress"}])

    def test_two_sessions_do_not_share_a_plan(self):
        store = MemoryTodoStore()
        one = TodoBoard(store, "s1", "t1")
        two = TodoBoard(store, "s2", "t2")

        make_todo_write_tool(one)(todos=PLAN)

        self.assertEqual(two.snapshot(), [])


class ValidationTest(unittest.TestCase):
    CASES = (
        (None, "must be an array"),
        ("not json at all", "neither valid JSON"),
        ([{"content": "  ", "status": "pending"}], "non-empty 'content'"),
        ([{"status": "pending"}], "non-empty 'content'"),
        (["just a string"], "must be an object"),
        ([{"content": "x", "status": "doing"}], "unknown status"),
        (
            [
                {"content": "a", "status": "in_progress"},
                {"content": "b", "status": "in_progress"},
            ],
            "at most one step in progress",
        ),
        ([{"content": f"step {n}", "status": "pending"} for n in range(MAX_TODOS + 1)], "at most"),
    )

    def test_what_cannot_be_rendered_is_refused(self):
        store = FakeStore()
        tool = make_todo_write_tool(TodoBoard(store, "s1", "t1"))

        for todos, expected in self.CASES:
            with self.subTest(todos=todos):
                outcome = tool(todos=todos)

                self.assertFalse(outcome.details["success"])
                self.assertEqual(outcome.details["reason"], "invalid_argument")
                self.assertIn(expected, outcome.model_text)

        self.assertEqual(store.saves, [], "a rejected plan must not replace the stored one")

    def test_an_empty_list_clears_the_plan(self):
        store = FakeStore(PLAN)
        outcome = make_todo_write_tool(TodoBoard(store, "s1", "t1"))(todos=[])

        self.assertTrue(outcome.details["success"])
        self.assertEqual(store.items, [])
        self.assertIn("empty", outcome.model_text)

    def test_a_missing_status_counts_as_pending(self):
        store = FakeStore()
        make_todo_write_tool(TodoBoard(store, "s1", "t1"))(todos=[{"content": "later"}])

        self.assertEqual(store.items, [{"content": "later", "status": "pending"}])

    def test_a_string_payload_is_parsed_as_json_or_a_list_literal(self):
        store = FakeStore()
        tool = make_todo_write_tool(TodoBoard(store, "s1", "t1"))

        json_call = tool(todos=json.dumps(PLAN))
        literal_call = tool(todos="[{'content': 'literal', 'status': 'pending'}]")

        self.assertTrue(json_call.details["success"])
        self.assertTrue(literal_call.details["success"])
        self.assertEqual(store.items, [{"content": "literal", "status": "pending"}])


class OutputContractTest(unittest.TestCase):
    def test_the_model_reads_back_the_plan_with_markers_and_a_count(self):
        outcome = make_todo_write_tool(TodoBoard(FakeStore(), "s1", "t1"))(todos=PLAN)

        self.assertEqual(
            outcome.model_text.splitlines(),
            [
                "Todo list (1/3 completed)",
                "[x] Read the parser",
                "[>] Write the failing test",
                "[ ] Fix the parser",
            ],
        )
        self.assertEqual(
            outcome.details["counts"],
            {"total": 3, "pending": 1, "in_progress": 1, "completed": 1},
        )
        self.assertEqual(outcome.details["todos"], PLAN)
        # The timeline already shows the tool result; a second event would be a
        # second place for the same list to drift.
        self.assertIsNone(outcome.event_category)

    def test_a_store_failure_is_reported_instead_of_swallowed(self):
        outcome = make_todo_write_tool(TodoBoard(BrokenStore(), "s1", "t1"))(todos=PLAN)

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "store_error")
        self.assertIn("could not be saved", outcome.model_text)

    def test_a_broken_read_only_costs_the_run_the_plan(self):
        board = TodoBoard(BrokenStore(), "s1", "t1")

        self.assertEqual(board.snapshot(), [])


class RegistryBindingTest(unittest.TestCase):
    def test_the_registry_hands_the_tool_the_board_it_was_given(self):
        store = MemoryTodoStore()
        registry = ToolRegistry(todo_board=TodoBoard(store, "s1", "t1"))
        other = ToolRegistry(todo_board=TodoBoard(store, "s2", "t2"))

        registry.execute_tool("todo_write", {"todos": PLAN})

        self.assertEqual(store.load("s1"), PLAN)
        self.assertEqual(other.todo_board.snapshot(), [])
        self.assertIn("todo_write", registry.tools)

    def test_a_registry_without_a_board_still_plans_in_memory(self):
        registry = ToolRegistry()

        outcome = registry.execute_tool("todo_write", {"todos": PLAN})

        self.assertIn("[>] Write the failing test", outcome.model_text)


if __name__ == "__main__":
    unittest.main()

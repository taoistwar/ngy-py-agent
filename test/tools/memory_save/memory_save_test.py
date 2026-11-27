"""Tests for the ``memory_save`` tool: declaration, gates, writing, binding.

Three decisions are pinned here because a future reader could "fix" them by accident:

* a candidate scoped to ``current_task`` is **refused**, not silently stored - that is
  the whole difference between a preference and an instruction for one task;
* the name is the identity of a note, so saving it again **replaces** it instead of
  growing the library;
* a store failure is reported to the model, because a note it believes it saved and did
  not is worse than no note at all.

Run from the repository root::

    uv run python test/tools/memory_save/memory_save_test.py -v
"""

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.bindings import ToolBindings  # noqa: E402
from agent.tools.memory_notes import MAX_BODY_CHARS, MAX_MEMORIES  # noqa: E402
from agent.tools.memory_save import (  # noqa: E402
    MEMORY_SAVE_DESCRIPTION,
    MEMORY_SAVE_PARAMETERS,
    MEMORY_SAVE_TOOL_NAME,
    make_memory_save_tool,
)
from agent.tools.memory_save import spec as memory_save_spec  # noqa: E402
from agent.tools.memory_store import InMemoryMemoryStore, MemoryBook  # noqa: E402
from agent.tools.permissions import PERMISSION_NONE  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402

NOTE = {
    "name": "user-prefers-tabs",
    "type": "user",
    "description": "User prefers tabs for indentation",
    "body": "Use tabs, not spaces, for indentation in Python files.",
    "scope": "persistent",
}


class BrokenStore:
    def list_memories(self) -> List[Dict[str, Any]]:
        raise RuntimeError("database is closed")

    def upsert_memory(self, name, memory_type, description, body, source_task_id=""):
        raise RuntimeError("database is closed")

    def delete_memory(self, memory_id: str) -> bool:
        raise RuntimeError("database is closed")


def book(**kwargs: Any) -> MemoryBook:
    return MemoryBook(InMemoryMemoryStore(), **kwargs)


class DeclarationTest(unittest.TestCase):
    def test_the_tool_is_named_after_what_the_model_calls(self):
        self.assertEqual(MEMORY_SAVE_TOOL_NAME, "memory_save")

    def test_the_schema_requires_the_scope(self):
        self.assertEqual(
            MEMORY_SAVE_PARAMETERS["required"],
            ["name", "type", "description", "body", "scope"],
        )
        self.assertEqual(
            MEMORY_SAVE_PARAMETERS["properties"]["scope"]["enum"], ["persistent", "current_task"]
        )

    def test_the_description_states_the_contract(self):
        for clause in ("current_task", "memory_search", "replaces", "scope"):
            with self.subTest(clause=clause):
                self.assertIn(clause, MEMORY_SAVE_DESCRIPTION)


class SpecTest(unittest.TestCase):
    def test_the_spec_never_asks_for_confirmation(self):
        spec = memory_save_spec.build_spec(ToolBindings())

        self.assertEqual(spec.name, MEMORY_SAVE_TOOL_NAME)
        # A memory is a note to itself, like a plan: nothing to confirm.
        self.assertEqual(spec.permission, PERMISSION_NONE)
        self.assertEqual(spec.parameters, MEMORY_SAVE_PARAMETERS)
        self.assertEqual(len(spec.description_i18n), 5)

    def test_the_tool_writes_into_the_book_it_was_bound_to(self):
        store = InMemoryMemoryStore()

        memory_save_spec.build_spec(ToolBindings(memory_book=MemoryBook(store))).handler(**NOTE)

        self.assertEqual([record["name"] for record in store.list_memories()], ["user-prefers-tabs"])


class ValidationTest(unittest.TestCase):
    CASES = (
        ({**NOTE, "name": "  "}, "name is required"),
        ({**NOTE, "type": "gut-feeling"}, "type must be one of"),
        ({**NOTE, "description": "   "}, "description is required"),
        ({**NOTE, "body": ""}, "body is required"),
        ({**NOTE, "body": "x" * (MAX_BODY_CHARS + 1)}, "keep a memory under"),
        ({**NOTE, "scope": ""}, "scope must be"),
        ({**NOTE, "scope": "forever"}, "scope must be"),
        ({**NOTE, "scope": "current_task"}, "only facts that still matter"),
    )

    def test_what_cannot_be_stored_is_refused(self):
        store = InMemoryMemoryStore()
        tool = make_memory_save_tool(MemoryBook(store))

        for payload, expected in self.CASES:
            with self.subTest(payload=payload):
                outcome = tool(**payload)

                self.assertFalse(outcome.details["success"])
                self.assertEqual(outcome.details["reason"], "invalid_argument")
                self.assertIn(expected, outcome.model_text)

        self.assertEqual(store.list_memories(), [], "a rejected note must not be stored")

    def test_a_rule_for_this_task_only_is_refused_even_without_a_scope(self):
        # The second gate: a model that says "persistent" while describing something
        # that only constrains this conversation is still refused, with the phrase named.
        outcome = make_memory_save_tool(book())(
            **{
                **NOTE,
                "name": "no-files",
                "description": "Do not create files in this session",
                "body": "The user asked not to create files in this session.",
            }
        )

        self.assertFalse(outcome.details["success"])
        self.assertIn("this session", outcome.model_text)


class WritingTest(unittest.TestCase):
    def test_a_note_is_stored_and_echoed_back(self):
        store = InMemoryMemoryStore()

        outcome = make_memory_save_tool(MemoryBook(store))(**NOTE)

        self.assertTrue(outcome.details["success"])
        self.assertFalse(outcome.details["replaced"])
        self.assertIn("Saved memory 'user-prefers-tabs' (user)", outcome.model_text)
        self.assertEqual(store.list_memories()[0]["body"], NOTE["body"])

    def test_the_same_name_replaces_instead_of_duplicating(self):
        store = InMemoryMemoryStore()
        tool = make_memory_save_tool(MemoryBook(store))

        tool(**NOTE)
        outcome = tool(**{**NOTE, "body": "Tabs everywhere, including YAML."})

        self.assertTrue(outcome.details["replaced"])
        self.assertIn("Replaced memory", outcome.model_text)
        self.assertEqual(len(store.list_memories()), 1)
        self.assertEqual(store.list_memories()[0]["body"], "Tabs everywhere, including YAML.")

    def test_the_same_body_under_another_name_is_not_stored_twice(self):
        store = InMemoryMemoryStore()
        tool = make_memory_save_tool(MemoryBook(store))
        tool(**NOTE)

        outcome = tool(**{**NOTE, "name": "tabs-again"})

        self.assertTrue(outcome.details["success"])
        self.assertFalse(outcome.details["saved"])
        self.assertEqual(outcome.details["reason"], "duplicate")
        self.assertIn("already stored as 'user-prefers-tabs'", outcome.model_text)
        self.assertEqual(len(store.list_memories()), 1)

    def test_the_task_id_that_wrote_the_note_is_recorded(self):
        store = InMemoryMemoryStore()

        make_memory_save_tool(MemoryBook(store, task_id="task-7"))(**NOTE)

        self.assertEqual(store.list_memories()[0]["source_task_id"], "task-7")


class RefusalTest(unittest.TestCase):
    def test_a_disabled_library_says_so_instead_of_pretending(self):
        outcome = make_memory_save_tool(book(enabled=False))(**NOTE)

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "disabled")
        self.assertIn("disabled", outcome.model_text)

    def test_a_full_library_asks_for_a_deletion(self):
        store = InMemoryMemoryStore()
        for index in range(MAX_MEMORIES):
            store.upsert_memory(f"note-{index}", "project", f"note {index}", f"body {index}")

        outcome = make_memory_save_tool(MemoryBook(store))(**NOTE)

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "full")
        self.assertIn("delete an obsolete one", outcome.model_text)

    def test_a_store_failure_is_reported_instead_of_swallowed(self):
        outcome = make_memory_save_tool(MemoryBook(BrokenStore()))(**NOTE)

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "store_error")
        self.assertIn("could not be saved", outcome.model_text)

    def test_a_broken_read_only_costs_the_run_the_library(self):
        self.assertEqual(MemoryBook(BrokenStore()).snapshot(), [])


class RegistryBindingTest(unittest.TestCase):
    def test_the_registry_hands_the_tool_the_book_it_was_given(self):
        store = InMemoryMemoryStore()
        registry = ToolRegistry(memory_book=MemoryBook(store))
        other = ToolRegistry(memory_book=MemoryBook(InMemoryMemoryStore()))

        registry.execute_tool("memory_save", dict(NOTE))

        self.assertEqual([record["name"] for record in store.list_memories()], ["user-prefers-tabs"])
        self.assertEqual(other.memory_book.snapshot(), [])
        self.assertIn("memory_save", registry.tools)

    def test_a_registry_without_a_book_still_keeps_memories_for_the_run(self):
        registry = ToolRegistry()

        outcome = registry.execute_tool("memory_save", dict(NOTE))

        self.assertIn("Saved memory", outcome.model_text)
        self.assertEqual(len(registry.memory_book.snapshot()), 1)


if __name__ == "__main__":
    unittest.main()

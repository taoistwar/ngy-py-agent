"""Tests for the ``memory_search`` tool: what it reads back, and what it says when empty.

The results are pinned because a silent empty string reads as a broken tool: every path
that finds nothing has to say *why* - no library yet, or nothing matching - and a call
that matches several notes has to stay inside one result budget.

Run from the repository root::

    uv run python test/tools/memory_search/memory_search_test.py -v
"""

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.bindings import ToolBindings  # noqa: E402
from agent.tools.memory_search import (  # noqa: E402
    MEMORY_SEARCH_DESCRIPTION,
    MEMORY_SEARCH_PARAMETERS,
    MEMORY_SEARCH_TOOL_NAME,
    make_memory_search_tool,
)
from agent.tools.memory_search import spec as memory_search_spec  # noqa: E402
from agent.tools.memory_search.description import MAX_RESULT_CHARS  # noqa: E402
from agent.tools.memory_store import InMemoryMemoryStore, MemoryBook  # noqa: E402
from agent.tools.permissions import PERMISSION_NONE  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402


def book_with(*records: Dict[str, Any]) -> MemoryBook:
    store = InMemoryMemoryStore()
    for record in records:
        store.upsert_memory(
            record["name"],
            record.get("type", "project"),
            record.get("description", ""),
            record["body"],
        )
    return MemoryBook(store)


class DeclarationTest(unittest.TestCase):
    def test_the_tool_is_named_after_what_the_model_calls(self):
        self.assertEqual(MEMORY_SEARCH_TOOL_NAME, "memory_search")

    def test_the_schema_takes_a_query_and_an_optional_limit(self):
        properties = MEMORY_SEARCH_PARAMETERS["properties"]

        self.assertEqual(MEMORY_SEARCH_PARAMETERS["required"], ["query"])
        self.assertEqual(properties["limit"]["maximum"], 10)

    def test_the_description_states_the_contract(self):
        for clause in ("already in your system prompt", "keywords", "background knowledge"):
            with self.subTest(clause=clause):
                self.assertIn(clause, MEMORY_SEARCH_DESCRIPTION)


class SpecTest(unittest.TestCase):
    def test_the_spec_never_asks_for_confirmation(self):
        spec = memory_search_spec.build_spec(ToolBindings())

        self.assertEqual(spec.name, MEMORY_SEARCH_TOOL_NAME)
        self.assertEqual(spec.permission, PERMISSION_NONE)
        self.assertEqual(spec.parameters, MEMORY_SEARCH_PARAMETERS)
        self.assertEqual(len(spec.description_i18n), 5)


class ReadingTest(unittest.TestCase):
    def test_an_empty_library_says_so_rather_than_returning_nothing(self):
        outcome = make_memory_search_tool(MemoryBook(InMemoryMemoryStore()))(query="tabs")

        self.assertTrue(outcome.details["success"])
        self.assertEqual(outcome.details["matches"], 0)
        self.assertIn("No memories have been stored yet", outcome.model_text)

    def test_a_miss_names_the_library_size(self):
        book = book_with({"name": "auth-rewrite", "body": "Compliance drove the rewrite."})

        outcome = make_memory_search_tool(book)(query="indentation")

        self.assertIn("No stored memory matches 'indentation'", outcome.model_text)
        self.assertIn("holds 1 note(s)", outcome.model_text)

    def test_a_hit_returns_the_description_and_the_body(self):
        book = book_with(
            {
                "name": "user-prefers-tabs",
                "type": "user",
                "description": "User prefers tabs for indentation",
                "body": "Use tabs, not spaces, in Python files.",
            }
        )

        outcome = make_memory_search_tool(book)(query="indentation")

        self.assertEqual(outcome.details["matches"], 1)
        self.assertEqual(outcome.details["names"], ["user-prefers-tabs"])
        self.assertIn("### [user] user-prefers-tabs", outcome.model_text)
        self.assertIn("User prefers tabs for indentation", outcome.model_text)
        self.assertIn("Use tabs, not spaces, in Python files.", outcome.model_text)

    def test_a_name_hit_outranks_a_body_hit(self):
        book = book_with(
            {"name": "zeta", "body": "alpha is mentioned once in this body."},
            {"name": "alpha-tabs", "body": "nothing relevant here."},
        )

        outcome = make_memory_search_tool(book)(query="alpha")

        self.assertEqual(outcome.details["names"], ["alpha-tabs", "zeta"])

    def test_a_missing_query_is_refused_instead_of_matching_everything(self):
        outcome = make_memory_search_tool(book_with({"name": "a", "body": "b"}))(query="  ")

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "invalid_argument")

    def test_limit_is_clamped_between_one_and_ten(self):
        book = book_with(*[{"name": f"note-{n}", "body": f"tab number {n}"} for n in range(12)])
        tool = make_memory_search_tool(book)

        many = tool(query="tab", limit=99)
        one = tool(query="tab", limit=0)
        nonsense = tool(query="tab", limit="not a number")

        self.assertEqual(len(many.details["names"]), 10)
        self.assertEqual(len(one.details["names"]), 1)
        self.assertEqual(len(nonsense.details["names"]), 5)


class BudgetTest(unittest.TestCase):
    def test_a_long_result_is_capped_and_says_so(self):
        body = "tab " * 1000
        book = book_with(
            *[{"name": f"note-{n}", "body": f"tab {n} {body}"} for n in range(5)]
        )

        outcome = make_memory_search_tool(book)(query="tab", limit=5)

        self.assertEqual(outcome.details["matches"], 5)
        self.assertLessEqual(len(outcome.model_text), MAX_RESULT_CHARS + 400)
        self.assertIn("further match(es) not shown", outcome.model_text)


class RefusalTest(unittest.TestCase):
    def test_a_disabled_library_says_so_instead_of_returning_nothing(self):
        outcome = make_memory_search_tool(
            MemoryBook(InMemoryMemoryStore(), enabled=False)
        )(query="tabs")

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "disabled")
        self.assertIn("disabled", outcome.model_text)

    def test_a_broken_store_is_reported(self):
        class BrokenStore:
            def list_memories(self) -> List[Dict[str, Any]]:
                raise RuntimeError("database is closed")

            def upsert_memory(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
                raise RuntimeError("database is closed")

            def delete_memory(self, memory_id: str) -> bool:
                raise RuntimeError("database is closed")

        outcome = make_memory_search_tool(MemoryBook(BrokenStore()))(query="tabs")

        # A read failure degrades to "no library": the search is not the thing to fail.
        self.assertIn("No memories have been stored yet", outcome.model_text)


class RegistryBindingTest(unittest.TestCase):
    def test_the_registry_search_reads_the_book_it_was_given(self):
        book = book_with({"name": "auth-rewrite", "body": "Compliance drove the rewrite."})
        registry = ToolRegistry(memory_book=book)

        outcome = registry.execute_tool("memory_search", {"query": "compliance"})

        self.assertIn("auth-rewrite", outcome.model_text)
        self.assertIn("memory_search", registry.tools)

    def test_the_ask_mode_may_read_but_not_write(self):
        from agent.modes import get_mode_config

        tools = get_mode_config("ask")["tool_names"]

        self.assertIn("memory_search", tools)
        self.assertNotIn("memory_save", tools)


if __name__ == "__main__":
    unittest.main()

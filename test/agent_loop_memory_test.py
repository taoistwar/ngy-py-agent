"""What earlier conversations remembered, as a new task's system prompt sees it.

The split pinned here is the whole design (ADR 0035): the **index** goes into the
prompt and the **bodies** never do - they are read with ``memory_search``. A change
that started inlining bodies would look like an improvement and would quietly make the
prompt grow with the library.

Run from the repository root::

    uv run python test/agent_loop_memory_test.py -v
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.agent_loop import run_react_loop  # noqa: E402
from agent.agent_loop.memory_context import append_memory_context  # noqa: E402
from agent.tools.memory_notes import render_memory_index  # noqa: E402
from agent.tools.memory_store import InMemoryMemoryStore, MemoryBook  # noqa: E402

BODY = "Use tabs, not spaces, in every Python file this project touches."


def book_with(*records: Dict[str, Any], **kwargs: Any) -> MemoryBook:
    store = InMemoryMemoryStore()
    for record in records:
        store.upsert_memory(
            record["name"],
            record.get("type", "user"),
            record.get("description", ""),
            record["body"],
        )
    return MemoryBook(store, **kwargs)


class _Registry:
    base_dir = None
    read_only_roots = ()
    permission_broker = None
    user_question_broker = None

    def __init__(self, memory_book: Any = None) -> None:
        self.memory_book = memory_book

    def get_tool_schemas(self, provider):
        return []

    def execute_tool(self, name, arguments):
        raise AssertionError("this test drives no tools")


class _Message:
    role = "assistant"

    def __init__(self, content=""):
        self.content = content
        self.tool_calls = []


class _Response:
    def __init__(self, message):
        self.choices = [SimpleNamespace(message=message, finish_reason="stop")]


class _FakeProvider:
    wire_compatible_with_openai = True

    def __init__(self):
        self.config = SimpleNamespace(provider="openai", model="fake-model")
        self.requests = []

    def build_request_payload(self, messages, tools=None, **kwargs):
        self.requests.append([dict(message) for message in messages])
        return {"messages": messages, "tools": tools or []}

    def chat_completion(self, messages, tools=None, **kwargs):
        return _Response(_Message(content="final answer"))


class LoopInjectionTest(unittest.TestCase):
    def run_loop(self, memory_book, **kwargs):
        provider = _FakeProvider()
        with patch(
            "agent.agent_loop.loop._build_runtime",
            return_value=("openai", _Registry(memory_book), provider, []),
        ):
            run_react_loop(
                task_id="task-memory",
                max_steps=1,
                verbose=False,
                user_query="how should I indent this?",
                **kwargs,
            )
        return provider.requests[0][0]["content"]

    def test_the_index_reaches_the_prompt_and_the_body_does_not(self):
        system = self.run_loop(
            book_with(
                {
                    "name": "user-prefers-tabs",
                    "type": "user",
                    "description": "User prefers tabs for indentation",
                    "body": BODY,
                }
            )
        )

        self.assertIn("## Remembered from earlier conversations", system)
        self.assertIn("- [user] user-prefers-tabs: User prefers tabs for indentation", system)
        self.assertIn("memory_search", system)
        self.assertNotIn(BODY, system)

    def test_an_empty_library_adds_nothing(self):
        system = self.run_loop(book_with())

        self.assertNotIn("Remembered from earlier conversations", system)

    def test_a_disabled_library_adds_nothing(self):
        system = self.run_loop(
            book_with({"name": "user-prefers-tabs", "body": BODY}, enabled=False)
        )

        self.assertNotIn("Remembered from earlier conversations", system)

    def test_a_caller_composed_prompt_is_used_verbatim(self):
        provider = _FakeProvider()
        with patch(
            "agent.agent_loop.loop._build_runtime",
            return_value=(
                "openai",
                _Registry(book_with({"name": "user-prefers-tabs", "body": BODY})),
                provider,
                [],
            ),
        ):
            run_react_loop(
                task_id="task-memory",
                max_steps=1,
                verbose=False,
                user_query="continue",
                initial_messages=[{"role": "system", "content": "custom prompt"}],
            )

        self.assertEqual("custom prompt", provider.requests[0][0]["content"])

    def test_which_notes_were_recalled_is_reported_in_the_task_log(self):
        events: List[Any] = []
        book = book_with({"name": "user-prefers-tabs", "body": BODY})

        self.run_loop(book, event_sink=lambda task_id, event: events.append(event))

        recalled = [event for event in events if event.title == "Recalled memories"]
        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0].data["count"], 1)
        self.assertEqual(recalled[0].data["names"], ["user-prefers-tabs"])


class IndexRenderingTest(unittest.TestCase):
    def test_the_index_is_capped_and_says_how_many_were_left_out(self):
        records = [
            {"name": f"note-{index}", "type": "project", "description": "x" * 150}
            for index in range(40)
        ]

        index = render_memory_index(records, max_chars=400)

        self.assertLessEqual(len(index), 600)
        self.assertIn("more memories are not shown", index)
        self.assertNotIn("note-39", index)

    def test_a_small_library_lists_every_note(self):
        index = render_memory_index(
            [{"name": "a", "type": "user", "description": "first"}], max_chars=400
        )

        self.assertEqual(index, "- [user] a: first")

    def test_appending_twice_is_a_no_op_for_an_empty_library(self):
        self.assertEqual("base", append_memory_context("base", []))
        self.assertEqual("base", append_memory_context("base", [{"not": "a record"}]))


if __name__ == "__main__":
    unittest.main()

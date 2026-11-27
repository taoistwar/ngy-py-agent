"""Tests for the post-task extractor (``agent/runtime/memory_extract.py``, ADR 0035).

The extractor is the half of the write side that runs without being asked: nobody says
"remember that". What is pinned here is therefore what it is *not* allowed to do - store
something scoped to the task, store a duplicate, or take the finished task down when the
model misbehaves.

Run from the repository root::

    uv run python test/memory_extract_test.py -v
"""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.runtime.memory_extract import (  # noqa: E402
    MAX_CANDIDATES,
    extract_after_task,
    extract_memories,
    parse_candidates,
    save_candidates,
)
from agent.tools.memory_notes import parse_record  # noqa: E402
from agent.tools.memory_store import InMemoryMemoryStore, MemoryBook  # noqa: E402
from commons import state  # noqa: E402

CANDIDATE = {
    "name": "user-prefers-tabs",
    "type": "user",
    "description": "User prefers tabs for indentation",
    "body": "Use tabs, not spaces, in Python files.",
    "scope": "persistent",
}


class _Response:
    def __init__(self, content):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")]


class _FakeProvider:
    def __init__(self, content: Any, fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.requests: List[List[Dict[str, Any]]] = []

    def chat_completion(self, messages, tools=None, **kwargs):
        self.requests.append(list(messages))
        if self.fail:
            raise RuntimeError("provider is down")
        return _Response(self.content)


class ParseCandidatesTest(unittest.TestCase):
    def test_a_plain_array_becomes_records(self):
        records = parse_candidates(json.dumps([CANDIDATE]))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "user-prefers-tabs")
        self.assertEqual(records[0]["body"], CANDIDATE["body"])

    def test_prose_and_fences_around_the_array_do_not_stop_it(self):
        raw = f"Sure, here you go:\n```json\n{json.dumps([CANDIDATE])}\n```\nHope that helps."

        self.assertEqual(len(parse_candidates(raw)), 1)

    def test_what_should_not_become_a_standing_rule_is_dropped(self):
        payload = [
            {**CANDIDATE, "scope": "current_task"},
            {**CANDIDATE, "name": "temp", "description": "Do not touch files in this session"},
            {**CANDIDATE, "name": "bad-type", "type": "guess"},
            {**CANDIDATE, "name": "no-body", "body": ""},
            CANDIDATE,
        ]

        records = parse_candidates(json.dumps(payload))

        self.assertEqual([record["name"] for record in records], ["user-prefers-tabs"])

    def test_at_most_three_candidates_are_kept(self):
        payload = [{**CANDIDATE, "name": f"note-{index}"} for index in range(6)]

        self.assertEqual(len(parse_candidates(json.dumps(payload))), MAX_CANDIDATES)

    def test_an_answer_that_is_not_json_yields_nothing(self):
        for raw in ("no idea", "[]", "{", None, 42):
            with self.subTest(raw=raw):
                self.assertEqual(parse_candidates(raw), [])


class SaveCandidatesTest(unittest.TestCase):
    def test_a_candidate_is_written_once(self):
        book = MemoryBook(InMemoryMemoryStore())
        record, _ = parse_record(CANDIDATE, require_scope=True)

        saved = save_candidates([record, record], book)

        self.assertEqual(len(saved), 1)
        self.assertEqual(len(book.snapshot()), 1)

    def test_a_note_that_is_already_stored_is_not_written_again(self):
        book = MemoryBook(InMemoryMemoryStore())
        book.store.upsert_memory("other-name", "user", "same", CANDIDATE["body"])

        record, _ = parse_record(CANDIDATE, require_scope=True)

        self.assertEqual(save_candidates([record], book), [])
        self.assertEqual(len(book.snapshot()), 1)


class ExtractMemoriesTest(unittest.TestCase):
    def test_the_model_is_shown_the_existing_library_and_the_finished_exchange(self):
        provider = _FakeProvider(json.dumps([CANDIDATE]))
        existing = [
            {"name": "auth-rewrite", "type": "project", "description": "why the rewrite", "body": "x"}
        ]

        with patch("agent.runtime.memory_extract.build_provider", return_value=provider):
            extract_memories("I prefer tabs", "Noted.", "openai", None, existing=existing)

        user_message = provider.requests[0][-1]["content"]
        self.assertIn("auth-rewrite", user_message)
        self.assertIn("I prefer tabs", user_message)
        self.assertIn("Noted.", user_message)

    def test_a_provider_failure_reads_as_nothing_to_remember(self):
        with patch(
            "agent.runtime.memory_extract.build_provider",
            return_value=_FakeProvider("", fail=True),
        ):
            self.assertEqual(extract_memories("q", "r", "openai", None), [])


class ExtractAfterTaskTest(unittest.TestCase):
    def setUp(self):
        self._previous = (
            state.memories_enabled,
            state.memories_auto_extract,
            state.memories_max_prompt_chars,
            state.memories_source,
        )
        state.memories_enabled = True
        state.memories_auto_extract = True

    def tearDown(self):
        (
            state.memories_enabled,
            state.memories_auto_extract,
            state.memories_max_prompt_chars,
            state.memories_source,
        ) = self._previous

    def test_a_durable_note_is_stored_and_reported(self):
        book = MemoryBook(InMemoryMemoryStore())
        events: List[Any] = []
        provider = _FakeProvider(json.dumps([CANDIDATE]))

        with patch("agent.runtime.memory_extract.build_provider", return_value=provider):
            extract_after_task(
                "task-1",
                "I prefer tabs",
                "Noted, tabs it is.",
                "openai",
                None,
                emit=lambda title, data: events.append((title, data)),
                book=book,
            )

        self.assertEqual([record["name"] for record in book.snapshot()], ["user-prefers-tabs"])
        self.assertEqual(events[0][0], "Memories updated")
        self.assertEqual(events[0][1]["names"], ["user-prefers-tabs"])

    def test_switched_off_memory_never_calls_the_model(self):
        book = MemoryBook(InMemoryMemoryStore())
        provider = _FakeProvider(json.dumps([CANDIDATE]))
        state.memories_auto_extract = False

        with patch("agent.runtime.memory_extract.build_provider", return_value=provider):
            extract_after_task("task-1", "q", "r", "openai", None, book=book)

        self.assertEqual(provider.requests, [])
        self.assertEqual(book.snapshot(), [])

    def test_a_state_object_without_the_switches_does_not_extract(self):
        # The runner is also driven by tests and embedders whose ``state`` predates the
        # feature: "no switches" has to mean "do not extract", not "raise after the task
        # already succeeded".
        from agent.runtime import runner

        started: List[Any] = []

        class _Thread:
            def __init__(self, **kwargs):
                started.append(kwargs)

            def start(self):
                started.append("started")

        with (
            patch.object(runner, "threading", SimpleNamespace(Thread=_Thread)),
            patch.object(runner, "state", SimpleNamespace()),
        ):
            runner._extract_memories_after_task("task-1", "q", "r", "openai", None, lambda *a: None)

        self.assertEqual(started, [])

    def test_switched_on_extraction_runs_off_the_task_thread(self):
        from agent.runtime import runner

        started: List[Any] = []

        class _Thread:
            def __init__(self, **kwargs):
                started.append(kwargs)

            def start(self):
                started.append("started")

        with (
            patch.object(runner, "threading", SimpleNamespace(Thread=_Thread)),
            patch.object(
                runner,
                "state",
                SimpleNamespace(memories_enabled=True, memories_auto_extract=True),
            ),
        ):
            runner._extract_memories_after_task("task-1", "q", "r", "openai", None, lambda *a: None)

        self.assertEqual(started[-1], "started")
        self.assertEqual(started[0]["args"], ("task-1", "q", "r", "openai", None))
        self.assertTrue(started[0]["daemon"])

    def test_nothing_durable_means_no_event(self):
        book = MemoryBook(InMemoryMemoryStore())
        events: List[Any] = []

        with patch(
            "agent.runtime.memory_extract.build_provider", return_value=_FakeProvider("[]")
        ):
            extract_after_task(
                "task-1", "q", "r", "openai", None, emit=lambda *a: events.append(a), book=book
            )

        self.assertEqual(events, [])
        self.assertEqual(book.snapshot(), [])


if __name__ == "__main__":
    unittest.main()

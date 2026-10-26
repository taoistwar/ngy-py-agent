"""micro_compact: shrink what the model has already read, keep what it has not.

Run from the repository root::

    uv run python test/micro_compact_test.py -v

The third step of the compaction pipeline runs only when the estimated context size
is over the limit. It touches **consumed** tool results (the model has seen them in a
request already), keeps the most recent ones whole, and turns older ones into a path
it can read back with ``read_file``.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.agent_loop import micro_compact  # noqa: E402
from agent.agent_loop.micro_compact import (  # noqa: E402
    DEFAULT_CONTEXT_CHAR_LIMIT,
    IMAGE_CHAR_COST,
    KEEP_RECENT_RESULTS,
    MIN_SHRINK_CHARS,
    apply_micro_compact,
    estimate_chars,
    fit_tool_results,
    mark_seen,
    prepare_context,
    resolve_context_limit,
)
from agent.models import EventCategory  # noqa: E402
from agent.tools import file_access  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402


def _system(text="system"):
    return {"role": "system", "content": text}


def _user(text="question"):
    return {"role": "user", "content": text}


def _assistant(text="answer", call_ids=()):
    message = {"role": "assistant", "content": text}
    if call_ids:
        message["tool_calls"] = [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
            for call_id in call_ids
        ]
    return message


def _tool(call_id, text="result"):
    return {"role": "tool", "tool_call_id": call_id, "name": "read_file", "content": text}


def _results(sizes, start=0):
    """``[system, user]`` plus one assistant/tool pair per size."""
    messages = [_system(), _user("start")]
    for offset, size in enumerate(sizes):
        call_id = f"c{start + offset}"
        messages.append(_assistant("", call_ids=(call_id,)))
        messages.append(_tool(call_id, "x" * size))
    return messages


def _all_seen(sizes, start=0):
    return {f"c{start + offset}" for offset in range(len(sizes))}


def _tool_index(messages, call_id):
    for index, message in enumerate(messages):
        if message.get("role") == "tool" and message.get("tool_call_id") == call_id:
            return index
    raise AssertionError(f"no tool message for {call_id}")


class _Collector:
    def __init__(self):
        self.events = []

    def __call__(self, task_id, event):
        self.events.append(event)


class EstimateCharsTest(unittest.TestCase):
    def test_an_empty_conversation_is_free(self):
        self.assertEqual(estimate_chars([]), 0)

    def test_text_counts(self):
        self.assertGreaterEqual(estimate_chars([_user("q" * 1000)]), 1000)

    def test_tool_arguments_count(self):
        short = [_assistant("", call_ids=("call-1",))]
        long = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "a" * 5000},
                    }
                ],
            }
        ]

        self.assertGreater(estimate_chars(long) - estimate_chars(short), 4000)

    def test_an_image_costs_a_fixed_amount_not_its_payload(self):
        small_payload = "data:image/png;base64," + "A" * 10_000
        large_payload = "data:image/png;base64," + "A" * 500_000
        small = [_user(["screenshot", {"type": "image_url", "image_url": {"url": small_payload}}])]
        large = [_user(["screenshot", {"type": "image_url", "image_url": {"url": large_payload}}])]

        self.assertEqual(estimate_chars(small), estimate_chars(large))
        self.assertGreaterEqual(estimate_chars(small), IMAGE_CHAR_COST)


class ResolveContextLimitTest(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop(micro_compact.CONTEXT_LIMIT_ENV, None)

    def tearDown(self):
        self._env.stop()

    def test_the_model_window_wins_over_the_default(self):
        self.assertEqual(
            resolve_context_limit(model_max_input_tokens=8000), 8000 * micro_compact.CHARS_PER_TOKEN
        )

    def test_the_default_applies_when_nothing_is_configured(self):
        self.assertEqual(resolve_context_limit(), DEFAULT_CONTEXT_CHAR_LIMIT)

    def test_the_environment_overrides_the_model_window(self):
        with patch.dict(os.environ, {micro_compact.CONTEXT_LIMIT_ENV: "1234"}):
            self.assertEqual(resolve_context_limit(model_max_input_tokens=8000), 1234)

    def test_an_explicit_value_overrides_everything(self):
        with patch.dict(os.environ, {micro_compact.CONTEXT_LIMIT_ENV: "1234"}):
            self.assertEqual(resolve_context_limit(configured=99, model_max_input_tokens=8000), 99)

    def test_zero_disables_the_step(self):
        self.assertEqual(resolve_context_limit(configured=0), 0)
        with patch.dict(os.environ, {micro_compact.CONTEXT_LIMIT_ENV: "-5"}):
            self.assertEqual(resolve_context_limit(model_max_input_tokens=8000), 0)


class MicroCompactTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self.sink = _Collector()

    def tearDown(self):
        self._tmp.cleanup()

    def compact(self, messages, seen, target=0, **kwargs):
        kwargs.setdefault("base_dir", str(self.workspace))
        kwargs.setdefault("event_sink", self.sink)
        kwargs.setdefault("task_id", "task-micro")
        kwargs.setdefault("step", 1)
        return apply_micro_compact(messages, seen, target, **kwargs)

    def result_dir(self) -> Path:
        return self.workspace / ".task_outputs" / "tool-results"

    def test_the_oldest_consumed_results_become_paths(self):
        sizes = [5000] * 6
        messages = _results(sizes)

        summary = self.compact(messages, _all_seen(sizes), target=0)

        self.assertEqual(len(summary["replaced"]), 3)
        for call_id in ("c0", "c1", "c2"):
            content = messages[_tool_index(messages, call_id)]["content"]
            self.assertTrue(content.startswith("[Earlier tool result saved at "))
            self.assertIn(self.result_dir().as_posix(), content)
        for call_id in ("c3", "c4", "c5"):
            self.assertEqual(messages[_tool_index(messages, call_id)]["content"], "x" * 5000)
        self.assertEqual(
            (self.result_dir() / "c0.txt").read_text(encoding="utf-8"), "x" * 5000
        )

    def test_it_stops_once_the_target_is_reached(self):
        sizes = [5000] * 6
        messages = _results(sizes)
        target = estimate_chars(messages) - 100

        summary = self.compact(messages, _all_seen(sizes), target=target)

        self.assertEqual(len(summary["replaced"]), 1)
        self.assertLessEqual(estimate_chars(messages), target)

    def test_the_most_recent_results_are_kept(self):
        sizes = [5000] * 6
        messages = _results(sizes)

        self.compact(messages, _all_seen(sizes), target=0)

        untouched = [
            message
            for message in messages
            if message.get("role") == "tool" and not str(message["content"]).startswith("[")
        ]
        self.assertEqual(len(untouched), KEEP_RECENT_RESULTS)

    def test_unseen_results_are_never_touched(self):
        sizes = [5000] * 6
        messages = _results(sizes)
        seen = {"c0", "c1", "c2", "c3"}  # c4 and c5 are still unread

        summary = self.compact(messages, seen, target=0)

        self.assertEqual([item["tool_call_id"] for item in summary["replaced"]], ["c0"])
        self.assertEqual(messages[_tool_index(messages, "c4")]["content"], "x" * 5000)
        self.assertEqual(messages[_tool_index(messages, "c5")]["content"], "x" * 5000)

    def test_short_results_are_left_alone(self):
        sizes = [MIN_SHRINK_CHARS] * 6
        messages = _results(sizes)

        summary = self.compact(messages, _all_seen(sizes), target=0)

        self.assertEqual(summary["replaced"], [])
        self.assertFalse(self.result_dir().exists())

    def test_a_persisted_pointer_is_not_shrunk_again(self):
        sizes = [5000] * 6
        messages = _results(sizes)
        pointer = "<persisted-output>\nFull output: /somewhere/c0.txt\n" + "p" * 400
        messages[_tool_index(messages, "c0")]["content"] = pointer

        summary = self.compact(messages, _all_seen(sizes), target=0)

        self.assertNotIn("c0", [item["tool_call_id"] for item in summary["replaced"]])
        self.assertEqual(messages[_tool_index(messages, "c0")]["content"], pointer)

    def test_an_existing_file_is_reused(self):
        sizes = [5000] * 6
        messages = _results(sizes)
        # result_budget may have written this result already: same id, same name.
        self.result_dir().mkdir(parents=True)
        (self.result_dir() / "c0.txt").write_text("x" * 5000, encoding="utf-8")

        summary = self.compact(messages, _all_seen(sizes), target=0)

        self.assertIn("c0", [item["tool_call_id"] for item in summary["replaced"]])
        self.assertEqual(len(list(self.result_dir().glob("*.txt"))), 3)
        self.assertEqual((self.result_dir() / "c0.txt").read_text(encoding="utf-8"), "x" * 5000)

    def test_a_failed_write_keeps_the_content_and_reports(self):
        sizes = [5000] * 6
        messages = _results(sizes)

        with patch.object(micro_compact, "persist_text", side_effect=OSError("disk full")):
            summary = self.compact(messages, _all_seen(sizes), target=0)

        self.assertEqual(summary["replaced"], [])
        self.assertEqual(len(summary["failed"]), 3)
        self.assertEqual(messages[_tool_index(messages, "c0")]["content"], "x" * 5000)
        errors = [event for event in self.sink.events if event.category == EventCategory.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].data["count"], 3)
        self.assertIn("disk full", errors[0].data["problems"][0])


class FitToolResultsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self.sink = _Collector()

    def tearDown(self):
        self._tmp.cleanup()

    def fit(self, messages, seen, target, **kwargs):
        kwargs.setdefault("base_dir", str(self.workspace))
        kwargs.setdefault("event_sink", self.sink)
        kwargs.setdefault("task_id", "task-micro")
        kwargs.setdefault("step", 1)
        return fit_tool_results(messages, seen, target, **kwargs)

    def test_the_largest_unread_result_gets_a_preview(self):
        sizes = [50_000, 10_000]
        messages = _results(sizes)
        target = estimate_chars(messages) - 10_000

        summary = self.fit(messages, set(), target)

        self.assertEqual([item["tool_call_id"] for item in summary["replaced"]], ["c0"])
        content = messages[_tool_index(messages, "c0")]["content"]
        self.assertTrue(content.startswith("<persisted-output>"))
        self.assertIn("c0.txt", content)
        self.assertIn("x" * 1000, content)
        self.assertNotIn("x" * 1001, content)
        self.assertEqual(messages[_tool_index(messages, "c1")]["content"], "x" * 10_000)

    def test_only_unread_results_are_fitted(self):
        sizes = [50_000, 10_000]
        messages = _results(sizes)

        summary = self.fit(messages, {"c0"}, target=0)

        self.assertEqual([item["tool_call_id"] for item in summary["replaced"]], ["c1"])


class PrepareContextTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self.sink = _Collector()
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop(micro_compact.CONTEXT_LIMIT_ENV, None)

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def prepare(self, messages, seen, **kwargs):
        kwargs.setdefault("base_dir", str(self.workspace))
        kwargs.setdefault("event_sink", self.sink)
        kwargs.setdefault("task_id", "task-micro")
        kwargs.setdefault("step", 1)
        return prepare_context(messages, seen, **kwargs)

    def test_under_the_limit_changes_nothing(self):
        sizes = [5000] * 6
        messages = _results(sizes)
        before = [dict(message) for message in messages]

        summary = self.prepare(messages, _all_seen(sizes), context_limit=10**9)

        self.assertEqual(messages, before)
        self.assertEqual(summary["micro"]["replaced"], [])
        self.assertFalse((self.workspace / ".task_outputs").exists())

    def test_micro_runs_before_fit(self):
        messages = _results([5000] * 4)
        messages.append(_assistant("", call_ids=("unread",)))
        messages.append(_tool("unread", "u" * 50_000))
        seen = {"c0", "c1", "c2", "c3"}

        summary = self.prepare(messages, seen, context_limit=20_000)

        self.assertEqual([item["tool_call_id"] for item in summary["micro"]["replaced"]], ["c0"])
        self.assertEqual([item["tool_call_id"] for item in summary["fit"]["replaced"]], ["unread"])
        self.assertFalse(summary["still_over"])

    def test_still_over_the_limit_is_reported(self):
        sizes = [5000] * 6
        messages = _results(sizes)
        for call_id in ("c3", "c4", "c5"):
            messages[_tool_index(messages, call_id)]["content"] = (
                "<persisted-output>\nFull output: /elsewhere\n" + "p" * 3000
            )

        summary = self.prepare(messages, _all_seen(sizes), context_limit=2000)

        self.assertTrue(summary["still_over"])
        reports = [event for event in self.sink.events if event.category == EventCategory.DEBUG]
        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0].data["still_over"])

    def test_a_disabled_limit_returns_immediately(self):
        messages = _results([5000] * 6)

        summary = self.prepare(messages, _all_seen([5000] * 6), context_limit=0)

        self.assertEqual(summary["reason"], "context limit disabled")
        self.assertEqual(summary["micro"]["replaced"], [])


class MarkSeenTest(unittest.TestCase):
    def test_it_collects_the_tool_call_ids_of_the_request(self):
        messages = [_user("q"), _assistant("", call_ids=("c0", "c1")), _tool("c0"), _tool("c1")]
        seen = set()

        mark_seen(seen, messages)

        self.assertEqual(seen, {"c0", "c1"})


class ResultDirectoryIsReadOnlyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_shortened_result_can_be_read_back_but_not_rewritten(self):
        size = 5000
        # Four results: the three most recent stay whole, so ``c0`` is the one that
        # becomes a path (ADR 0016).
        messages = _results([size] * 4)
        micro_compact.apply_micro_compact(
            messages,
            {f"c{index}" for index in range(4)},
            0,
            base_dir=str(self.workspace),
        )
        registry = ToolRegistry(enabled_tools=[], base_dir=str(self.workspace))
        target = ".task_outputs/tool-results/c0.txt"

        resolved, _ = file_access.resolve_read_path(
            target, base_dir=str(self.workspace), extra_read_roots=registry.read_only_roots
        )
        self.assertEqual(resolved.stat().st_size, size)

        with self.assertRaises(file_access.AccessDenied) as caught:
            file_access.resolve_write_path(
                target, base_dir=str(self.workspace), extra_read_roots=registry.read_only_roots
            )
        self.assertEqual(caught.exception.reason, file_access.REASON_READ_ONLY_ROOT)


class _Message:
    role = "assistant"

    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _Choice:
    def __init__(self, message):
        self.message = message
        self.finish_reason = "tool_calls" if message.tool_calls else "stop"


class _Response:
    def __init__(self, message):
        self.choices = [_Choice(message)]


class _SteppingProvider:
    wire_compatible_with_openai = True

    def __init__(self, tool_steps=5, result="r" * 2000):
        self.config = SimpleNamespace(provider="openai", model="fake-model")
        self.requests = []
        self.tool_steps = tool_steps
        self.result = result

    def build_request_payload(self, messages, tools=None, **kwargs):
        self.requests.append([dict(message) for message in messages])
        return {"messages": messages, "tools": tools or []}

    def chat_completion(self, messages, tools=None, **kwargs):
        if len(self.requests) <= self.tool_steps:
            call_id = f"call-{len(self.requests)}"
            return _Response(
                _Message(
                    tool_calls=[
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ]
                )
            )
        return _Response(_Message(content="done"))


class _SteppingRegistry:
    read_only_roots = ()
    permission_broker = None
    user_question_broker = None

    def __init__(self, base_dir):
        self.base_dir = base_dir

    def get_tool_schemas(self, provider):
        return []

    def execute_tool(self, name, arguments):
        return "r" * 2000


class LoopWiringTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self._env = patch.dict(
            os.environ,
            {
                micro_compact.CONTEXT_LIMIT_ENV: "4000",
                "TRANSCRIPT_MAX_MESSAGES": "0",
            },
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_the_loop_shortens_what_the_model_already_read(self):
        from agent.agent_loop import run_react_loop

        provider = _SteppingProvider(tool_steps=5)
        registry = _SteppingRegistry(str(self.workspace))

        with patch(
            "agent.agent_loop.loop._build_runtime",
            return_value=("openai", registry, provider, []),
        ):
            result = run_react_loop(
                user_query="keep going",
                task_id="task-micro",
                max_steps=7,
                verbose=False,
            )

        self.assertEqual(result, "done")
        shortcuts = [
            message["content"]
            for request in provider.requests
            for message in request
            if message.get("role") == "tool"
            and str(message.get("content", "")).startswith("[Earlier tool result saved at ")
        ]
        self.assertTrue(shortcuts, "no tool result was ever shortened")
        files = list((self.workspace / ".task_outputs" / "tool-results").glob("*.txt"))
        self.assertTrue(files)


if __name__ == "__main__":
    unittest.main()

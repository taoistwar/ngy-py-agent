"""Result budget: a batch of tool results that is too large leaves the context.

Run from the repository root::

    uv run python test/agent_loop_result_budget_test.py -v

The budget runs right after a ReAct step's tool calls, on the messages that step
appended. Anything above the large-result limit is written to
``<workspace>/.task_outputs/tool-results/<tool_call_id>.txt`` and replaced by a
path plus a preview, so the model can read it back instead of carrying it.
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

from agent.agent_loop import result_budget, run_react_loop  # noqa: E402
from agent.models import EventCategory  # noqa: E402
from agent.tools import file_access  # noqa: E402
from agent.tools.read_file.tool import make_read_file_tool  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402

WORKSPACE = Path("<workspace>")


def _tool_message(call_id: str, content: str, name: str = "read_file"):
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}


class _Collector:
    def __init__(self):
        self.events = []

    def __call__(self, task_id, event):
        self.events.append(event)


class ResultBudgetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop(result_budget.BUDGET_CHARS_ENV, None)
        os.environ.pop(result_budget.LARGE_LIMIT_ENV, None)
        self.sink = _Collector()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def run_budget(self, messages, batch_start=0, **kwargs):
        kwargs.setdefault("base_dir", str(self.workspace))
        kwargs.setdefault("event_sink", self.sink)
        kwargs.setdefault("task_id", "task-budget")
        kwargs.setdefault("step", 1)
        return result_budget.apply_result_budget(messages, batch_start, **kwargs)

    def result_path(self, call_id: str) -> Path:
        return self.workspace / ".task_outputs" / "tool-results" / f"{call_id}.txt"

    def test_results_within_budget_are_left_alone(self):
        messages = [_tool_message("call-a", "a" * 1000), _tool_message("call-b", "b" * 2000)]

        summary = self.run_budget(messages)

        self.assertEqual(messages[0]["content"], "a" * 1000)
        self.assertEqual(messages[1]["content"], "b" * 2000)
        self.assertEqual(summary["persisted"], [])

    def test_the_largest_result_leaves_the_context_first(self):
        big = "a" * 120_000
        middle = "b" * 100_000
        small = "c" * 5_000
        messages = [
            _tool_message("call-small", small),
            _tool_message("call-big", big),
            _tool_message("call-middle", middle),
        ]

        summary = self.run_budget(messages)

        # Persisting the 120k result is enough to get back under 200k.
        self.assertEqual([item["tool_call_id"] for item in summary["persisted"]], ["call-big"])
        self.assertEqual(self.result_path("call-big").read_text(encoding="utf-8"), big)
        self.assertIn(self.result_path("call-big").as_posix(), messages[1]["content"])
        # The preview is capped at 2000 characters; the rest only exists on disk.
        self.assertIn("a" * 2000, messages[1]["content"])
        self.assertNotIn("a" * 2001, messages[1]["content"])
        self.assertEqual(messages[0]["content"], small)
        self.assertEqual(messages[2]["content"], middle)

    def test_small_results_are_persisted_when_the_batch_is_still_too_large(self):
        messages = [_tool_message(f"call-{index}", str(index) * 29_000) for index in range(8)]

        summary = self.run_budget(messages)

        # No single result exceeds the large-result limit, so the first pass does
        # nothing; the fallback pass has to make the budget hold anyway.
        self.assertEqual(len(summary["persisted"]), 2)
        self.assertLessEqual(summary["after_chars"], summary["max_chars"])
        self.assertEqual(messages[7]["content"], "7" * 29_000)

    def test_persisted_file_is_byte_exact(self):
        content = "line\r\n" + "中文内容" * 50_000
        messages = [_tool_message("call-crlf", content)]

        self.run_budget(messages)

        self.assertEqual(self.result_path("call-crlf").read_bytes(), content.encode("utf-8"))

    def test_placeholder_names_the_full_output_and_the_preview(self):
        messages = [_tool_message("call-format", "x" * 250_000)]

        self.run_budget(messages)

        content = messages[0]["content"]
        self.assertTrue(content.startswith("<persisted-output>"))
        self.assertTrue(content.rstrip().endswith("</persisted-output>"))
        self.assertIn("250,000 chars", content)
        self.assertIn("Preview (first 2,000 chars):", content)
        self.assertIn(self.result_path("call-format").as_posix(), content)

    def test_the_placeholder_says_how_to_read_the_file_back(self):
        content = "line\r\n" * 60_000
        messages = [_tool_message("call-lines", content)]

        self.run_budget(messages)

        text = messages[0]["content"]
        # Line count first: read_file wants an offset/limit, and guessing at it is
        # how a read-back turns into two more steps.
        self.assertIn("60,000 lines", text)
        self.assertIn("offset/limit", text)
        self.assertIn("256 KB", text)
        self.assertIn("line numbers, not file content", text)

    def test_nul_bytes_do_not_leave_an_unreadable_file(self):
        content = ("A" * 100) + "\x00" + ("B" * 250_000)
        messages = [_tool_message("call-nul", content)]

        self.run_budget(messages)

        # read_file refuses anything that sniffs as binary, so a NUL left in the file
        # would break the promise the message just made.
        self.assertNotIn(b"\x00", self.result_path("call-nul").read_bytes())
        self.assertNotIn("\x00", messages[0]["content"])
        self.assertIn("\ufffd", messages[0]["content"])

    def test_a_result_shorter_than_its_placeholder_is_left_alone(self):
        content = "t" * 1200
        messages = [_tool_message("call-tiny", content)]

        summary = self.run_budget(messages, max_chars=500)

        # A path plus a 2000-character preview is longer than the result itself.
        self.assertEqual(messages[0]["content"], content)
        self.assertEqual(summary["persisted"], [])
        self.assertFalse(self.result_path("call-tiny").exists())

    def test_the_result_directory_keeps_itself_out_of_git(self):
        messages = [_tool_message("call-git", "g" * 250_000)]

        self.run_budget(messages)

        ignore = self.workspace / ".task_outputs" / "tool-results" / ".gitignore"
        self.assertEqual(ignore.read_text(encoding="utf-8"), "*\n")

    def test_a_failed_write_keeps_the_full_result(self):
        content = "y" * 250_000
        messages = [_tool_message("call-fail", content)]

        with patch.object(result_budget, "persist_text", side_effect=OSError("disk full")):
            summary = self.run_budget(messages)

        self.assertEqual(messages[0]["content"], content)
        self.assertEqual(summary["persisted"], [])
        self.assertEqual(len(summary["failed"]), 1)
        errors = [event for event in self.sink.events if event.category == EventCategory.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("disk full", errors[0].data["error"])

    def test_a_non_positive_budget_disables_the_step(self):
        content = "z" * 250_000
        messages = [_tool_message("call-off", content)]

        with patch.dict(os.environ, {result_budget.BUDGET_CHARS_ENV: "0"}):
            summary = self.run_budget(messages)

        self.assertEqual(messages[0]["content"], content)
        self.assertEqual(summary["persisted"], [])

    def test_an_unbound_session_writes_under_the_default_workspace(self):
        default_root = Path(self._tmp.name) / "default_workspace"
        messages = [_tool_message("call-unbound", "u" * 250_000)]

        with patch.dict(os.environ, {"DEFAULT_WORKSPACE_DIR": str(default_root)}):
            self.run_budget(messages, base_dir=None)

        expected = default_root / ".task_outputs" / "tool-results" / "call-unbound.txt"
        self.assertTrue(expected.exists())
        self.assertIn(expected.as_posix(), messages[0]["content"])

    def test_a_debug_event_reports_what_moved(self):
        messages = [_tool_message("call-report", "r" * 250_000)]

        self.run_budget(messages, step=3)

        reports = [event for event in self.sink.events if event.category == EventCategory.DEBUG]
        self.assertEqual(len(reports), 1)
        data = reports[0].data
        self.assertEqual(data["step"], 3)
        self.assertEqual([item["tool_call_id"] for item in data["persisted"]], ["call-report"])
        self.assertEqual(data["before_chars"], 250_000)
        self.assertLess(data["after_chars"], data["before_chars"])

    def test_only_the_latest_batch_is_considered(self):
        history = _tool_message("call-history", "h" * 250_000)
        messages = [history, _tool_message("call-new", "n" * 1000)]

        summary = self.run_budget(messages, batch_start=1)

        self.assertEqual(messages[0]["content"], "h" * 250_000)
        self.assertEqual(summary["persisted"], [])


class ResultDirectoryIsReadOnlyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_file_tools_can_read_but_not_rewrite_persisted_results(self):
        registry = ToolRegistry(enabled_tools=[], base_dir=str(self.workspace))
        target = ".task_outputs/tool-results/call-a.txt"

        resolved, _ = file_access.resolve_read_path(
            target, base_dir=str(self.workspace), extra_read_roots=registry.read_only_roots
        )
        self.assertEqual(resolved, self.workspace / target)

        with self.assertRaises(file_access.AccessDenied) as caught:
            file_access.resolve_write_path(
                target, base_dir=str(self.workspace), extra_read_roots=registry.read_only_roots
            )
        self.assertEqual(caught.exception.reason, file_access.REASON_READ_ONLY_ROOT)


class PersistedResultReadBackTest(unittest.TestCase):
    """Round trip through the real tool: the point of persisting is that it can be read.

    The read-only-root test below only covers path resolution; without this one, a
    change to either the placeholder or ``read_file``'s limits could make every
    persisted result unreadable and the suite would stay green.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_read_file_reads_a_slice_of_a_persisted_result(self):
        registry = ToolRegistry(enabled_tools=[], base_dir=str(self.workspace))
        content = "".join(f"line {index}\n" for index in range(80_000))
        messages = [_tool_message("call-read", content)]

        result_budget.apply_result_budget(messages, 0, base_dir=str(self.workspace))

        stored = self.workspace / ".task_outputs" / "tool-results" / "call-read.txt"
        self.assertTrue(stored.exists())
        read_file = make_read_file_tool(
            base_dir=str(self.workspace), extra_read_roots=registry.read_only_roots
        )
        payload = read_file(file_path=stored.as_posix(), encoding="utf-8", limit=3)

        self.assertEqual(payload["path"], ".task_outputs/tool-results/call-read.txt")
        self.assertTrue(payload["token_budget"]["ok"])
        self.assertTrue(payload["truncated"])
        self.assertTrue(payload["content"].startswith("1\tline 0"))


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


class _BigResultProvider:
    wire_compatible_with_openai = True

    def __init__(self):
        self.config = SimpleNamespace(provider="openai", model="fake-model")
        self.requests = []

    def build_request_payload(self, messages, tools=None, **kwargs):
        self.requests.append([dict(message) for message in messages])
        return {"messages": messages, "tools": tools or []}

    def chat_completion(self, messages, tools=None, **kwargs):
        if len(self.requests) == 1:
            tool_calls = [
                {
                    "id": "call-loop",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ]
            return _Response(_Message(tool_calls=tool_calls))
        return _Response(_Message(content="done"))


class _BigResultRegistry:
    read_only_roots = ()
    permission_broker = None
    user_question_broker = None
    result = "L" * 250_000

    def __init__(self, base_dir):
        self.base_dir = base_dir

    def get_tool_schemas(self, provider):
        return []

    def execute_tool(self, name, arguments):
        return self.result


class LoopWiringTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_next_request_carries_the_path_instead_of_the_result(self):
        provider = _BigResultProvider()
        registry = _BigResultRegistry(str(self.workspace))

        with patch(
            "agent.agent_loop.loop._build_runtime",
            return_value=("openai", registry, provider, []),
        ):
            result = run_react_loop(
                user_query="read everything",
                task_id="task-budget",
                max_steps=2,
                verbose=False,
            )

        self.assertEqual(result, "done")
        self.assertEqual(len(provider.requests), 2)
        tool_messages = [
            message for message in provider.requests[1] if message.get("role") == "tool"
        ]
        self.assertEqual(len(tool_messages), 1)
        self.assertIn("<persisted-output>", tool_messages[0]["content"])
        self.assertNotIn("L" * 2001, tool_messages[0]["content"])
        self.assertEqual(
            (self.workspace / ".task_outputs" / "tool-results" / "call-loop.txt").read_text(
                encoding="utf-8"
            ),
            registry.result,
        )


if __name__ == "__main__":
    unittest.main()

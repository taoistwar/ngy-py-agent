"""compact_history: the fourth compaction step, and the only one that calls a model.

Run from the repository root::

    uv run python test/compact_history_test.py -v

When ``micro_compact`` + ``fit_tool_results`` still leave the conversation over the
limit, the old history is archived, summarized as factual state, and replaced by one
``[Compacted]`` message. The most recent messages stay verbatim: they are the work in
progress.
"""

import json
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

from agent.agent_loop import compact_history as module  # noqa: E402
from agent.agent_loop.compact_history import (  # noqa: E402
    KEEP_RECENT_MESSAGES,
    SUMMARY_CHAR_ESTIMATE,
    SUMMARY_MESSAGE_CHAR_LIMIT,
    compact_history,
    summary_enabled,
)
from agent.agent_loop.micro_compact import estimate_chars  # noqa: E402
from agent.models import EventCategory  # noqa: E402


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


def _old_and_tail(old_size=3000, old_count=3, tail_size=100):
    """``[system, user] + old assistants + a five-message tail``."""
    messages = [_system(), _user("start")]
    for _ in range(old_count):
        messages.append(_assistant("o" * old_size))
    for index in range(KEEP_RECENT_MESSAGES):
        messages.append(_user(f"recent-{index}-{'-' * tail_size}"))
    return messages


class _Message:
    role = "assistant"

    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _Choice:
    def __init__(self, message):
        self.message = message
        self.finish_reason = "stop"


class _Response:
    def __init__(self, message):
        self.choices = [_Choice(message)]


class _Provider:
    """Records every call; the summary call is the one without ``tools``."""

    provider_name = "openai"
    wire_compatible_with_openai = True

    def __init__(self, reply="Goal: ship it\nRemaining: nothing", error=None, name="openai"):
        self.provider_name = name
        self.config = SimpleNamespace(provider=name, model="fake-model")
        self.reply = reply
        self.error = error
        self.calls = []

    def chat_completion(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})
        if self.error is not None:
            raise self.error
        return _Response(_Message(content=self.reply))


class _Collector:
    def __init__(self):
        self.events = []

    def __call__(self, task_id, event):
        self.events.append(event)

    def categories(self, category):
        return [event for event in self.events if event.category == category]


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self.sink = _Collector()
        self.provider = _Provider()

    def tearDown(self):
        self._tmp.cleanup()

    def transcript_dir(self) -> Path:
        return self.workspace / ".ngy-agent" / ".transcripts"

    def compact(self, messages, **kwargs):
        kwargs.setdefault("provider", self.provider)
        kwargs.setdefault("active_request", "do the thing")
        kwargs.setdefault("base_dir", str(self.workspace))
        kwargs.setdefault("event_sink", self.sink)
        kwargs.setdefault("task_id", "task-compact")
        kwargs.setdefault("step", 1)
        kwargs.setdefault("target_chars", 10**9)
        return compact_history(messages, **kwargs)


class SplitTest(_Base):
    def test_system_messages_stay_at_the_head(self):
        messages = [_system("one"), _system("two")]
        for index in range(6):
            messages.append(_user(f"q{index}") if index % 2 == 0 else _assistant("a"))

        head, old, tail = module._split(messages)

        self.assertEqual(head, messages[:2])
        self.assertEqual(old, messages[2:3])
        self.assertEqual(len(tail), KEEP_RECENT_MESSAGES)

    def test_the_tail_keeps_five_messages(self):
        messages = _old_and_tail(old_count=3, tail_size=10)

        _head, _old, tail = module._split(messages)

        self.assertEqual(len(tail), KEEP_RECENT_MESSAGES)

    def test_a_tool_cut_widens_to_its_assistant_call(self):
        messages = [_system(), _user("q")]
        for _index in range(6):
            messages.append(_assistant("a" * 3000))
        # A five-call batch: the cut lands inside it, so the tail has to grow past
        # ``KEEP_RECENT_MESSAGES`` to keep the calls and their results together.
        messages.append(_assistant("", call_ids=tuple(f"c{index}" for index in range(5))))
        for index in range(5):
            messages.append(_tool(f"c{index}", "r" * 3000))

        _head, old, tail = module._split(messages)

        self.assertNotEqual(tail[0].get("role"), "tool")
        self.assertTrue(tail[0].get("tool_calls"))
        self.assertEqual(len(tail), 6)
        self.assertNotIn("tool", [message.get("role") for message in old])

    def test_nothing_to_summarize_when_only_the_tail_exists(self):
        messages = [_system(), _user("q"), _assistant("a")]

        summary = self.compact(messages)

        self.assertEqual(summary["reason"], "nothing to summarize")
        self.assertEqual(self.provider.calls, [])
        self.assertFalse(self.transcript_dir().exists())
        self.assertEqual(len(messages), 3)


class ProjectionTest(_Base):
    def test_it_skips_when_the_summary_cannot_help(self):
        messages = [_system(), _user("q"), _assistant("a")]
        for index in range(KEEP_RECENT_MESSAGES):
            messages.append(_assistant("t" * 5000, call_ids=("c0",) if index == 0 else ()))
        before = [dict(message) for message in messages]

        summary = self.compact(messages, target_chars=1000)

        self.assertIn("would not reach the target", summary["reason"])
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(messages, before)
        self.assertFalse(self.transcript_dir().exists())

    def test_it_proceeds_when_the_summary_helps(self):
        messages = _old_and_tail(old_size=5000, old_count=3, tail_size=10)

        summary = self.compact(messages, target_chars=10_000)

        self.assertEqual(summary["reason"], "compacted")
        self.assertEqual(len(self.provider.calls), 1)


class SummaryInputTest(unittest.TestCase):
    def test_each_message_is_capped(self):
        text = module._summary_input([_tool("c0", "x" * 20_000)], context_limit=0)

        self.assertLessEqual(len(text), SUMMARY_MESSAGE_CHAR_LIMIT + 200)
        self.assertIn("truncated", text)
        self.assertNotIn("x" * (SUMMARY_MESSAGE_CHAR_LIMIT + 1), text)

    def test_the_middle_is_dropped_and_marked(self):
        messages = [_user(f"message-{index}-" + "y" * 100) for index in range(40)]

        text = module._summary_input(messages, context_limit=4000)

        self.assertIn("middle omitted", text)
        self.assertIn("message-0-", text)
        self.assertIn("message-39-", text)
        self.assertLessEqual(len(text), 2200)

    def test_an_image_becomes_a_placeholder(self):
        payload = "data:image/png;base64," + "A" * 5000
        messages = [_user(["screenshot", {"type": "image_url", "image_url": {"url": payload}}])]

        text = module._summary_input(messages, context_limit=0)

        self.assertIn("[image]", text)
        self.assertNotIn("A" * 100, text)

    def test_tool_calls_are_rendered(self):
        messages = [_assistant("", call_ids=("c0",))]

        text = module._summary_input(messages, context_limit=0)

        self.assertIn("read_file({})", text)


class SummaryFailureTest(_Base):
    def test_a_provider_error_keeps_the_history(self):
        messages = _old_and_tail()
        before = [dict(message) for message in messages]
        self.provider.error = RuntimeError("provider down")

        summary = self.compact(messages)

        self.assertIn("provider down", summary["reason"])
        self.assertEqual(messages, before)
        errors = self.sink.categories(EventCategory.ERROR)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].data["action"], "kept the full history")
        # Archive first: even a failed summary leaves the evidence on disk.
        self.assertEqual(len(list(self.transcript_dir().glob("*.jsonl"))), 1)

    def test_an_empty_summary_is_a_failure(self):
        messages = _old_and_tail()
        before = [dict(message) for message in messages]
        self.provider = _Provider(reply="   ")

        summary = self.compact(messages)

        self.assertIn("empty summary", summary["reason"])
        self.assertEqual(messages, before)

    def test_the_summary_is_truncated_to_the_budget(self):
        messages = _old_and_tail()
        self.provider = _Provider(reply="s" * (SUMMARY_CHAR_ESTIMATE * 3))

        summary = self.compact(messages)

        marker = messages[1]["content"]
        self.assertLessEqual(summary["summary_chars"], SUMMARY_CHAR_ESTIMATE + 40)
        self.assertIn("summary truncated", marker)


class CompactHistoryTest(_Base):
    def test_the_old_history_becomes_one_marker(self):
        messages = _old_and_tail()
        identity = id(messages)
        before = estimate_chars(messages)
        kept = KEEP_RECENT_MESSAGES

        summary = self.compact(messages)

        self.assertEqual(id(messages), identity)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertTrue(messages[1]["content"].startswith("[Compacted:"))
        self.assertEqual(len(messages), 2 + kept)
        self.assertEqual(summary["kept_messages"], kept)
        self.assertGreater(summary["compacted_messages"], 0)
        self.assertLess(estimate_chars(messages), before)
        self.assertEqual(summary["after_chars"], estimate_chars(messages))

    def test_the_marker_carries_the_request_and_the_transcript(self):
        messages = _old_and_tail()

        summary = self.compact(messages, active_request="fix the failing test")

        marker = messages[1]["content"]
        self.assertIn("Current user request:\nfix the failing test", marker)
        self.assertIn("Conversation summary (reference only", marker)
        self.assertIn("Goal: ship it", marker)
        self.assertIn(summary["transcript"], marker)
        self.assertIn("read_file (offset/limit)", marker)

    def test_the_transcript_is_jsonl_with_images_redacted(self):
        payload = "data:image/png;base64," + "A" * 5000
        messages = _old_and_tail()
        messages.insert(2, _user(["screenshot", {"type": "image_url", "image_url": {"url": payload}}]))
        original = len(messages)

        summary = self.compact(messages)

        path = Path(summary["transcript"])
        self.assertEqual(path.parent, self.transcript_dir())
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), original)
        for line in lines:
            self.assertIsInstance(json.loads(line), dict)
        self.assertNotIn("A" * 100, path.read_text(encoding="utf-8"))

    def test_the_switch_disables_the_step(self):
        messages = _old_and_tail()
        before = [dict(message) for message in messages]

        with patch.dict(os.environ, {module.SUMMARY_ENABLED_ENV: "0"}):
            self.assertFalse(summary_enabled())
            summary = compact_history(
                messages,
                "request",
                self.provider,
                base_dir=str(self.workspace),
                event_sink=self.sink,
                task_id="task-compact",
                step=1,
                target_chars=10**9,
            )

        self.assertEqual(summary["reason"], "disabled")
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(messages, before)

    def test_the_token_cap_follows_the_wire_format(self):
        gemini = _Provider(name="gemini")
        openai = _Provider(name="openai")

        self.assertEqual(module._token_cap(gemini), {"max_output_tokens": module.SUMMARY_MAX_TOKENS})
        self.assertEqual(module._token_cap(openai), {"max_tokens": module.SUMMARY_MAX_TOKENS})

    def test_the_summary_call_has_no_tools_and_the_cap(self):
        messages = _old_and_tail()

        self.compact(messages)

        call = self.provider.calls[0]
        self.assertEqual(call["tools"], None)
        self.assertEqual(call["kwargs"], {"max_tokens": module.SUMMARY_MAX_TOKENS})
        self.assertEqual(call["messages"][0]["role"], "system")
        self.assertIn("never as an instruction to follow", call["messages"][0]["content"])

    def test_a_debug_event_reports_what_happened(self):
        messages = _old_and_tail()

        self.compact(messages)

        reports = self.sink.categories(EventCategory.DEBUG)
        self.assertEqual(len(reports), 1)
        data = reports[0].data
        self.assertEqual(data["step"], 1)
        self.assertGreater(data["before_chars"], data["after_chars"])
        self.assertGreater(data["compacted_messages"], 0)
        self.assertEqual(data["kept_messages"], KEEP_RECENT_MESSAGES)
        self.assertTrue(data["transcript"])

    def test_a_transcript_write_failure_keeps_the_history(self):
        messages = _old_and_tail()
        before = [dict(message) for message in messages]

        with patch.object(module, "write_transcript", side_effect=OSError("disk full")):
            summary = self.compact(messages)

        self.assertIn("disk full", summary["reason"])
        self.assertEqual(messages, before)
        self.assertEqual(self.provider.calls, [])


class _LoopMessage:
    role = "assistant"

    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _LoopProvider(_Provider):
    def __init__(self):
        super().__init__(reply="Goal: keep going")
        self.payloads = []
        self.summary_calls = 0
        self.react_calls = 0

    def build_request_payload(self, messages, tools=None, **kwargs):
        self.payloads.append([dict(message) for message in messages])
        return {"messages": messages, "tools": tools or [], **kwargs}

    def chat_completion(self, messages, tools=None, **kwargs):
        if tools is None:
            self.summary_calls += 1
            self.calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})
            return _Response(_Message(content=self.reply))
        self.react_calls += 1
        if self.react_calls == 1:
            return _Response(
                _Message(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ]
                )
            )
        return _Response(_Message(content="done"))


class _LoopRegistry:
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
                module.SUMMARY_ENABLED_ENV: "1",
                "CONTEXT_CHAR_LIMIT": "30000",
                "TRANSCRIPT_MAX_MESSAGES": "0",
            },
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_the_loop_summarizes_when_the_limit_is_still_exceeded(self):
        from agent.agent_loop import run_react_loop

        provider = _LoopProvider()
        registry = _LoopRegistry(str(self.workspace))
        # Long history, short tail: micro/fit cannot touch assistant text, so the run
        # reaches the fourth step.
        history = [
            _user("u" * 8000),
            _assistant("a" * 8000),
            _user("u" * 8000),
            _assistant("a" * 8000),
            _user("short"),
            _assistant("short"),
        ]

        with patch(
            "agent.agent_loop.loop._build_runtime",
            return_value=("openai", registry, provider, []),
        ):
            result = run_react_loop(
                user_query="keep going",
                task_id="task-compact",
                max_steps=4,
                verbose=False,
                initial_messages=[_system("sys")],
                history_messages=history,
            )

        self.assertEqual(result, "done")
        self.assertEqual(provider.summary_calls, 1)
        compacted = [
            message
            for payload in provider.payloads
            for message in payload
            if message.get("role") == "user"
            and str(message.get("content", "")).startswith("[Compacted:")
        ]
        self.assertTrue(compacted, "the summary marker never reached a request")
        transcripts = list(
            (self.workspace / ".ngy-agent" / ".transcripts").glob("*.jsonl")
        )
        self.assertEqual(len(transcripts), 1)


class ReadOnlyTranscriptTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_summarized_history_can_be_read_back(self):
        from agent.tools.registry import ToolRegistry

        messages = _old_and_tail()
        summary = compact_history(
            messages,
            "request",
            _Provider(),
            base_dir=str(self.workspace),
            target_chars=10**9,
        )
        registry = ToolRegistry(enabled_tools=[], base_dir=str(self.workspace))

        path = Path(summary["transcript"])
        self.assertIn(
            path.parent.as_posix(),
            registry.read_only_roots,
            "the transcript directory must be a readable root",
        )
        self.assertGreater(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()

"""snip_compact: a long run keeps a bounded message window, the rest goes to disk.

Run from the repository root::

    uv run python test/snip_compact_test.py -v

The interesting part is not the slicing - it is never slicing *through* a tool turn.
An assistant message with tool calls and the tool messages that answer it are one
unit: cut between them and the next request carries an orphan ``tool_use`` (or an
orphan ``tool_result``), which providers reject.
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

from agent.agent_loop import snip_compact, transcript  # noqa: E402
from agent.agent_loop.snip_compact import apply_snip_compact  # noqa: E402
from agent.models import EventCategory  # noqa: E402
from agent.provider import AnthropicProvider  # noqa: E402
from agent.tools import file_access  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402

MAX = 50
HEAD = 3


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


def _alternating(count):
    """``count`` messages of user/assistant chatter, starting with a user."""
    messages = []
    for index in range(count):
        messages.append(_user(f"q{index}") if index % 2 == 0 else _assistant(f"a{index}"))
    return messages


class _Collector:
    def __init__(self):
        self.events = []

    def __call__(self, task_id, event):
        self.events.append(event)


class SnipCompactTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop(snip_compact.MAX_MESSAGES_ENV, None)
        self.sink = _Collector()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def compact(self, messages, **kwargs):
        kwargs.setdefault("base_dir", str(self.workspace))
        kwargs.setdefault("event_sink", self.sink)
        kwargs.setdefault("task_id", "task-snip")
        kwargs.setdefault("step", 1)
        return apply_snip_compact(messages, **kwargs)

    def transcript_dir(self) -> Path:
        return self.workspace / ".transcripts"

    def only_transcript(self) -> Path:
        files = sorted(self.transcript_dir().glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        return files[0]

    def test_a_short_conversation_is_left_untouched(self):
        messages = [_system(), _user()] + _alternating(20)
        before = [dict(message) for message in messages]

        summary = self.compact(messages)

        self.assertEqual(messages, before)
        self.assertEqual(summary["archived"], 0)
        self.assertFalse(self.transcript_dir().exists())

    def test_the_window_keeps_the_head_and_the_tail(self):
        messages = [_system(), _user("the question")] + _alternating(58)
        head = [dict(message) for message in messages[:HEAD]]
        tail = [dict(message) for message in messages[14:]]

        summary = self.compact(messages)

        self.assertEqual(len(messages), MAX)
        self.assertEqual(messages[:HEAD], head)
        self.assertEqual(messages[HEAD + 1 :], tail)
        self.assertEqual(summary["before_count"], 60)
        self.assertEqual(summary["after_count"], MAX)
        self.assertEqual(summary["archived"], 11)
        self.assertIn("11 messages archived to", messages[HEAD]["content"])
        self.assertEqual(messages[HEAD]["role"], "user")

    def test_the_marker_says_the_file_is_line_numbered(self):
        messages = [_system(), _user()] + _alternating(58)

        self.compact(messages)

        marker = messages[HEAD]["content"]
        self.assertIn("read_file", marker)
        self.assertIn("token budget", marker)

    def test_a_snapshot_waits_for_a_batch_worth_archiving(self):
        # 53 messages: only 4 would be archived. A full snapshot for four messages
        # costs more than it saves, so the window is allowed to drift instead.
        short = [_system(), _user()] + _alternating(51)

        summary = self.compact(short)

        self.assertEqual(summary["archived"], 0)
        self.assertIn("4 messages", summary["reason"])
        self.assertFalse(self.transcript_dir().exists())

        batch = [_system(), _user()] + _alternating(52)

        summary = self.compact(batch)

        self.assertEqual(summary["archived"], 5)
        self.assertEqual(len(batch), MAX)

    def test_an_orphan_result_is_reported_after_compaction(self):
        messages = [_system(), _user()] + _alternating(48)
        messages += [_tool("ghost")]
        messages += _alternating(9)
        self.assertEqual(len(messages), 60)

        summary = self.compact(messages)

        # The compaction still happens - the check only says the result is suspect.
        self.assertEqual(len(messages), MAX)
        self.assertEqual(summary["archived"], 11)
        errors = [event for event in self.sink.events if event.category == EventCategory.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("ghost", errors[0].data["problems"][0])
        self.assertIn("no call", errors[0].data["problems"][0])

    def test_a_paired_window_reports_nothing(self):
        messages = [
            _system(),
            _user("go"),
            _assistant("", call_ids=("c1", "c2")),
            _tool("c1"),
            _tool("c2"),
        ] + _alternating(54)

        self.compact(messages)

        errors = [event for event in self.sink.events if event.category == EventCategory.ERROR]
        self.assertEqual(errors, [])

    def test_the_transcript_holds_the_whole_conversation(self):
        messages = [_system(), _user()] + _alternating(58)
        before = [dict(message) for message in messages]

        self.compact(messages)

        lines = self.only_transcript().read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), len(before))
        self.assertEqual([json.loads(line) for line in lines], before)

    def test_the_head_keeps_a_tool_turn_whole(self):
        messages = [
            _system(),
            _user("go"),
            _assistant("", call_ids=("c1", "c2", "c3")),
            _tool("c1"),
            _tool("c2"),
            _tool("c3"),
        ]
        messages += _alternating(54)

        summary = self.compact(messages)

        # The assistant that owns c1..c3 plus all three results stay in the head.
        self.assertEqual(messages[:6], [
            _system(),
            _user("go"),
            _assistant("", call_ids=("c1", "c2", "c3")),
            _tool("c1"),
            _tool("c2"),
            _tool("c3"),
        ])
        self.assertEqual(messages[6]["role"], "user")
        self.assertIn("messages archived to", messages[6]["content"])
        # Head growth is taken out of the tail: the window still lands on the limit.
        self.assertEqual(summary["after_count"], MAX)

    def test_the_tail_never_starts_with_an_orphan_tool_result(self):
        messages = [_system(), _user("go")] + _alternating(9)
        messages += [_assistant("", call_ids=("c1", "c2", "c3"))]
        messages += [_tool("c1"), _tool("c2"), _tool("c3")]
        messages += _alternating(45)
        self.assertEqual(len(messages), 60)

        summary = self.compact(messages)

        # The cut would have landed on ``c3``; it moved back to the assistant so the
        # tool results still answer a call that is inside the window.
        self.assertEqual(messages[HEAD + 1]["role"], "assistant")
        self.assertEqual(messages[HEAD + 1]["tool_calls"][0]["id"], "c1")
        # A tool turn cannot be cut in half, so the window may overshoot by its size.
        self.assertEqual(summary["after_count"], 53)

    def test_anthropic_gets_no_orphan_tool_use_or_result(self):
        messages = [_system(), _user("go")] + _alternating(9)
        messages += [_assistant("", call_ids=("c1", "c2", "c3"))]
        messages += [_tool("c1"), _tool("c2"), _tool("c3")]
        messages += _alternating(45)

        self.compact(messages)

        provider = object.__new__(AnthropicProvider)
        _, converted = AnthropicProvider._to_anthropic_messages(provider, messages)
        uses, results = set(), set()
        for message in converted:
            if not isinstance(message["content"], list):
                continue
            for block in message["content"]:
                if block.get("type") == "tool_use":
                    uses.add(block["id"])
                elif block.get("type") == "tool_result":
                    results.add(block["tool_use_id"])
        self.assertEqual(uses, results)

    def test_images_are_redacted_in_the_transcript_only(self):
        image_message = {
            "role": "user",
            "content": [
                {"type": "text", "text": "screenshot"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }
        messages = [_system(), _user("go"), image_message] + _alternating(57)

        self.compact(messages)

        stored = self.only_transcript().read_text(encoding="utf-8")
        self.assertNotIn("base64,AAAA", stored)
        self.assertIn("<image data omitted>", stored)
        # The conversation still carries the real payload.
        self.assertIn("data:image/png;base64,AAAA", json.dumps(messages[2]))

    def test_a_failed_write_keeps_every_message(self):
        messages = [_system(), _user()] + _alternating(58)
        before = len(messages)

        # The write seam now lives in the shared transcript writer (ADR 0017 D10).
        with patch.object(transcript, "persist_text", side_effect=OSError("disk full")):
            summary = self.compact(messages)

        self.assertEqual(len(messages), before)
        self.assertEqual(summary["archived"], 0)
        self.assertIn("transcript", summary["reason"])
        errors = [event for event in self.sink.events if event.category == EventCategory.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("disk full", errors[0].data["error"])

    def test_the_callers_list_is_rewritten_in_place(self):
        messages = [_system(), _user()] + _alternating(58)
        original = messages

        self.compact(messages)

        self.assertIs(messages, original)  # the REPL in main.py holds this list
        self.assertEqual(len(messages), MAX)

    def test_one_tool_turn_that_fills_the_window_is_not_cut(self):
        messages = [_system(), _user("go"), _assistant("", call_ids=tuple(f"c{i}" for i in range(60)))]
        messages += [_tool(f"c{i}") for i in range(60)]
        before = [dict(message) for message in messages]

        summary = self.compact(messages, max_messages=10)

        self.assertEqual(messages, before)
        self.assertEqual(summary["archived"], 0)
        self.assertIn("tool turn", summary["reason"])

    def test_zero_disables_the_step(self):
        messages = [_system(), _user()] + _alternating(58)
        before = len(messages)

        with patch.dict(os.environ, {snip_compact.MAX_MESSAGES_ENV: "0"}):
            summary = self.compact(messages)

        self.assertEqual(len(messages), before)
        self.assertEqual(summary["archived"], 0)

    def test_an_unbound_session_writes_under_the_default_workspace(self):
        default_root = Path(self._tmp.name) / "default_workspace"
        messages = [_system(), _user()] + _alternating(58)

        with patch.dict(os.environ, {"DEFAULT_WORKSPACE_DIR": str(default_root)}):
            self.compact(messages, base_dir=None)

        self.assertEqual(len(list((default_root / ".transcripts").glob("*.jsonl"))), 1)
        self.assertIn((default_root / ".transcripts").as_posix(), messages[HEAD]["content"])

    def test_each_compaction_keeps_its_own_snapshot(self):
        messages = [_system(), _user()] + _alternating(58)
        self.compact(messages)
        messages += _alternating(10)

        self.compact(messages)

        self.assertEqual(len(list(self.transcript_dir().glob("*.jsonl"))), 2)


class TranscriptDirectoryIsReadOnlyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_file_tools_can_read_but_not_rewrite_transcripts(self):
        registry = ToolRegistry(enabled_tools=[], base_dir=str(self.workspace))
        target = ".transcripts/transcript-1.jsonl"

        resolved, _ = file_access.resolve_read_path(
            target, base_dir=str(self.workspace), extra_read_roots=registry.read_only_roots
        )
        self.assertEqual(resolved, self.workspace / target)

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

    def __init__(self, tool_steps=4):
        self.config = SimpleNamespace(provider="openai", model="fake-model")
        self.requests = []
        self.tool_steps = tool_steps

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
        return "ok"


class LoopWiringTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self._env = patch.dict(os.environ, {snip_compact.MAX_MESSAGES_ENV: "6"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_the_loop_compacts_between_steps(self):
        from agent.agent_loop import run_react_loop

        provider = _SteppingProvider(tool_steps=3)
        registry = _SteppingRegistry(str(self.workspace))

        with patch(
            "agent.agent_loop.loop._build_runtime",
            return_value=("openai", registry, provider, []),
        ):
            result = run_react_loop(
                user_query="keep going",
                task_id="task-snip",
                max_steps=6,
                verbose=False,
            )

        self.assertEqual(result, "done")
        markers = [
            message["content"]
            for request in provider.requests
            for message in request
            if message.get("role") == "user"
            and isinstance(message.get("content"), str)
            and "messages archived to" in message["content"]
        ]
        self.assertTrue(markers, "no compaction marker reached the model")
        self.assertEqual(len(list((self.workspace / ".transcripts").glob("*.jsonl"))), 1)


if __name__ == "__main__":
    unittest.main()

"""The subagent runs a nested loop with its own messages and reports one result.

What has to hold: the child's tool calls happen in the same workspace but never enter
the parent's conversation, the child cannot delegate further, and the timeline gets one
``subagent`` event per phase (started / tool / done or failed).

Run from the repository root::

    uv run python test/agent_subagent_test.py -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.agent_loop import run_react_loop  # noqa: E402
from agent.agent_loop.model_turn import ModelTurn  # noqa: E402
from agent.agent_loop.subagent import _build_child_registry, make_subagent_runner  # noqa: E402
from agent.models import EventCategory  # noqa: E402
from agent.tool_registry import ToolRegistry  # noqa: E402


def _turn(content="", calls=None):
    return ModelTurn(
        assistant_content=content,
        tool_calls=list(calls or []),
        response_payload={},
    )


class SubagentRunnerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "notes.txt").write_text("hello subagent\n", encoding="utf-8")
        self.events = []
        self.registry = ToolRegistry(base_dir=str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def make_runner(self, *, should_stop=None, max_steps=12):
        provider = SimpleNamespace(config=SimpleNamespace(provider="openai", model="fake"))
        return make_subagent_runner(
            registry=self.registry,
            provider=provider,
            event_sink=lambda task_id, event: self.events.append(event),
            task_id="task-1",
            should_stop=should_stop,
            max_steps=max_steps,
        )

    def run_turns(self, turns, *, should_stop=None, max_steps=12):
        """Run the subagent against a scripted sequence of model turns."""
        sequence = list(turns)
        steps = []

        def fake_turn(provider, step, messages, tools, kwargs, sink, task_id, stream=True):
            steps.append(step)
            # The child must never pass the parent's event sink to the model turn: the
            # parent sees one summary event, not a second copy of the child's traffic.
            self.assertIsNone(sink)
            self.assertIsNone(task_id)
            if not sequence:
                raise AssertionError("the subagent asked for more turns than scripted")
            return sequence.pop(0)

        runner = self.make_runner(should_stop=should_stop, max_steps=max_steps)
        with patch("agent.agent_loop.subagent.run_model_turn", side_effect=fake_turn):
            report = runner("Summarize notes.txt")
        return report, steps

    def phases(self):
        return [
            event.data.get("phase")
            for event in self.events
            if event.category == EventCategory.SUBAGENT
        ]

    # ------------------------------------------------------------------ tests

    def test_returns_the_child_report_and_runs_its_tools_in_the_same_workspace(self):
        report, steps = self.run_turns(
            [
                _turn(
                    calls=[
                        ("read_file", {"file_path": "notes.txt", "encoding": "utf-8"}, "call-1")
                    ]
                ),
                _turn(content="The file says hello."),
            ]
        )

        self.assertEqual(report, "The file says hello.")
        self.assertEqual(steps, [1, 2])
        self.assertEqual(self.phases(), ["started", "tool", "done"])

        tool_event = self.events[1]
        self.assertEqual(tool_event.data["name"], "read_file")
        self.assertIn("hello subagent", tool_event.data["result"])
        self.assertFalse(tool_event.data["is_error"])
        for event in self.events:
            self.assertTrue(event.data.get("subagent_id"))
            self.assertEqual(event.task_id, "task-1")

        done = self.events[-1]
        self.assertEqual(done.data["steps_used"], 2)
        self.assertEqual(done.data["tool_calls"], 1)
        self.assertIn("The file says hello.", done.data["result"])

    def test_the_child_does_not_receive_the_subagent_tool(self):
        report, _ = self.run_turns(
            [
                _turn(calls=[("subagent", {"prompt": "nested"}, "call-1")]),
                _turn(content="stopped"),
            ]
        )

        self.assertEqual(report, "stopped")
        tool_event = self.events[1]
        self.assertEqual(tool_event.data["name"], "subagent")
        # Not "not found" as an error event: the child registry simply has no such
        # tool, and the child model reads the refusal as a tool result.
        self.assertIn("not found", tool_event.data["result"])

    def test_the_step_limit_becomes_a_failed_report(self):
        report, _ = self.run_turns(
            [
                _turn(calls=[("read_file", {"file_path": "notes.txt", "encoding": "utf-8"}, "c1")]),
                _turn(calls=[("read_file", {"file_path": "notes.txt", "encoding": "utf-8"}, "c2")]),
            ],
            max_steps=2,
        )

        self.assertIn("2 turns", report)
        self.assertEqual(self.phases()[-1], "failed")
        self.assertEqual(self.events[-1].data["reason"], "step_limit")
        self.assertEqual(self.events[-1].data["tool_calls"], 2)

    def test_a_stop_request_ends_the_child_before_the_model_call(self):
        report, steps = self.run_turns([], should_stop=lambda: True)

        self.assertIn("stopped", report.lower())
        self.assertEqual(steps, [])
        self.assertEqual(self.phases(), ["started", "failed"])
        self.assertEqual(self.events[-1].data["reason"], "stopped")

    def test_a_model_failure_is_reported_not_raised(self):
        runner = self.make_runner()

        with patch(
            "agent.agent_loop.subagent.run_model_turn", side_effect=RuntimeError("boom")
        ):
            report = runner("do it")

        self.assertEqual(report, "Error: boom")
        self.assertEqual(self.phases()[-1], "failed")
        self.assertEqual(self.events[-1].data["reason"], "model_error")

    def test_a_failing_child_tool_becomes_text_the_child_can_read(self):
        report, _ = self.run_turns(
            [
                _turn(calls=[("read_file", {}, "call-1")]),
                _turn(content="read_file needs a path."),
            ]
        )

        self.assertEqual(report, "read_file needs a path.")
        tool_event = self.events[1]
        self.assertTrue(tool_event.data["is_error"])
        self.assertIn("Error:", tool_event.data["result"])


class _OneShotProvider:
    """An adapter with no stream mode: enough to drive one loop turn."""

    wire_compatible_with_openai = True
    supports_streaming = False

    def __init__(self):
        self.config = SimpleNamespace(provider="openai", model="fake-model")

    def build_request_payload(self, messages, tools=None, **kwargs):
        return {"messages": messages, "tools": tools or []}

    def chat_completion(self, messages, tools=None, **kwargs):
        message = SimpleNamespace(
            role="assistant", content="done", tool_calls=[], reasoning=""
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def _scripted_provider(turns):
    """A provider that answers from a fixed sequence of turns."""

    class _Provider:
        wire_compatible_with_openai = True
        supports_streaming = False

        def __init__(self):
            self.config = SimpleNamespace(provider="openai", model="fake-model")

        def build_request_payload(self, messages, tools=None, **kwargs):
            return {"messages": messages, "tools": tools or []}

        def chat_completion(self, messages, tools=None, **kwargs):
            turn = turns.pop(0)
            message = SimpleNamespace(
                role="assistant",
                content=turn.get("content", ""),
                tool_calls=[
                    SimpleNamespace(
                        id=call_id,
                        type="function",
                        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
                    )
                    for name, args, call_id in turn.get("calls", [])
                ],
                reasoning="",
            )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=message,
                        finish_reason="tool_calls" if turn.get("calls") else "stop",
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

    return _Provider()


class LoopWiringTest(unittest.TestCase):
    def _run(self, tool_names):
        registry = ToolRegistry(enabled_tools=tool_names)
        with patch(
            "agent.agent_loop.loop._build_runtime",
            return_value=("openai", registry, _OneShotProvider(), []),
        ):
            run_react_loop("hello", task_id="", verbose=False)
        return registry

    def test_the_loop_installs_a_runner_when_the_tool_is_enabled(self):
        registry = self._run(["subagent"])

        self.assertTrue(callable(registry.subagent_runner))

    def test_a_run_without_the_tool_gets_no_runner(self):
        registry = self._run(["read_file"])

        self.assertIsNone(registry.subagent_runner)

    def test_the_parent_timeline_records_the_delegation(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "notes.txt").write_text("hello subagent\n", encoding="utf-8")
            provider = _scripted_provider(
                [
                    {
                        "calls": [
                            (
                                "subagent",
                                {"prompt": "Read notes.txt and report"},
                                "call-parent-1",
                            )
                        ]
                    },
                    {
                        "calls": [
                            (
                                "read_file",
                                {"file_path": "notes.txt", "encoding": "utf-8"},
                                "call-child-1",
                            )
                        ]
                    },
                    {"content": "The notes say hello."},
                    {"content": "Parent done."},
                ]
            )
            registry = ToolRegistry(base_dir=tmp)
            events = []
            with patch(
                "agent.agent_loop.loop._build_runtime",
                return_value=("openai", registry, provider, []),
            ):
                result = run_react_loop(
                    "delegate the reading",
                    task_id="",
                    verbose=False,
                    event_sink=lambda task_id, event: events.append(event),
                )

        self.assertEqual(result, "Parent done.")
        phases = [
            event.data["phase"]
            for event in events
            if event.category == EventCategory.SUBAGENT
        ]
        self.assertEqual(phases, ["started", "tool", "done"])
        done = [event for event in events if event.category == EventCategory.SUBAGENT][-1]
        self.assertIn("The notes say hello.", done.data["result"])

        # The parent only ever sees the subagent tool pair; the child's read_file
        # never becomes a tool_result of this conversation.
        tool_names = [
            event.data["name"]
            for event in events
            if event.category == EventCategory.TOOL_CALL
        ]
        self.assertEqual(tool_names, ["subagent"])


class ChildToolListTest(unittest.TestCase):
    """What the child may call: the parent's tools minus delegation and the board.

    A subagent's context is thrown away when it returns, so the project's plan stays
    with the conversation that keeps it: creating, sequencing and claiming tasks there
    would be overreach, and the six schemas are tokens spent on a job nobody can finish.
    """

    def setUp(self):
        self.registry = ToolRegistry()

    def test_the_child_cannot_delegate_further(self):
        self.assertNotIn("subagent", _build_child_registry(self.registry).tools)

    def test_the_child_gets_no_board_tools(self):
        child = _build_child_registry(self.registry)

        self.assertEqual([name for name in child.tools if name.startswith("task_")], [])

    def test_the_child_keeps_the_tools_its_brief_needs(self):
        child = _build_child_registry(self.registry)

        for name in ("todo_write", "exec_command", "read_file", "write_file"):
            self.assertIn(name, child.tools)

    def test_the_board_tools_stay_on_the_parent(self):
        for name in ("task_create", "task_list", "task_claim", "task_complete"):
            self.assertIn(name, self.registry.tools)


if __name__ == "__main__":
    unittest.main()

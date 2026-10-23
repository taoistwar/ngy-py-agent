"""The loop's spans must mirror the call tree, and the event stream must point at it.

Run from the repository root::

    uv run python test/telemetry/agent_loop_tracing_test.py -v
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from agent.agent_loop import run_react_loop  # noqa: E402
from agent.telemetry.config import TelemetryConfig  # noqa: E402
from agent.telemetry.setup import init_telemetry, shutdown_telemetry  # noqa: E402


class _Registry:
    base_dir = None
    read_only_roots = ()
    permission_broker = None
    user_question_broker = None

    def get_tool_schemas(self, provider):
        return []

    def execute_tool(self, name, arguments):
        return f"ran {name}"


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

    def model_dump(self):
        return {
            "usage": {"prompt_tokens": 9, "completion_tokens": 4},
            "choices": [{"finish_reason": self.choices[0].finish_reason}],
        }


class _Provider:
    wire_compatible_with_openai = True

    def __init__(self):
        self.config = SimpleNamespace(
            provider="openai", model="test-model", supports_image_input=False
        )
        self.calls = 0

    def build_request_payload(self, messages, tools=None, **kwargs):
        return {"messages": messages, "tools": tools or []}

    def chat_completion(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _Response(
                _Message(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "echo", "arguments": '{"text": "hi"}'},
                        }
                    ]
                )
            )
        return _Response(_Message(content="done"))


class LoopTracingTest(unittest.TestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        init_telemetry(
            TelemetryConfig(enabled=True, exporter="none"),
            span_exporter=self.exporter,
            batch=False,
        )
        self.addCleanup(shutdown_telemetry)

    def run_loop(self):
        events = []
        with patch(
            "agent.agent_loop.loop._build_runtime",
            return_value=("openai", _Registry(), _Provider(), []),
        ):
            result = run_react_loop(
                user_query="echo hi",
                task_id="task-trace",
                max_steps=2,
                verbose=False,
                event_sink=lambda task_id, event: events.append(event),
            )
        return result, events

    def test_the_spans_mirror_task_step_model_and_tool(self):
        result, _ = self.run_loop()

        spans = self.exporter.get_finished_spans()
        by_name = {}
        for span in spans:
            by_name.setdefault(span.name, []).append(span)

        self.assertEqual(result, "done")
        self.assertEqual(len(by_name["task"]), 1)
        self.assertEqual(len(by_name["react.step"]), 2)
        self.assertEqual(len(by_name["chat test-model"]), 2)
        self.assertEqual(len(by_name["execute_tool echo"]), 1)

        task = by_name["task"][0]
        first_step = by_name["react.step"][0]
        self.assertIsNone(task.parent)
        self.assertEqual(first_step.parent.span_id, task.context.span_id)
        self.assertEqual(by_name["chat test-model"][0].parent.span_id, first_step.context.span_id)
        self.assertEqual(by_name["execute_tool echo"][0].parent.span_id, first_step.context.span_id)

    def test_the_model_span_carries_usage_and_the_tool_span_its_arguments(self):
        self.run_loop()

        spans = {span.name: span for span in reversed(self.exporter.get_finished_spans())}
        chat = spans["chat test-model"]
        self.assertEqual(chat.attributes["gen_ai.usage.input_tokens"], 9)
        self.assertEqual(chat.attributes["gen_ai.usage.output_tokens"], 4)
        self.assertEqual(chat.attributes["gen_ai.response.finish_reasons"], ("tool_calls",))
        tool = spans["execute_tool echo"]
        self.assertEqual(tool.attributes["gen_ai.tool.name"], "echo")
        self.assertIn("hi", tool.attributes["gen_ai.tool.call.arguments"])

    def test_events_carry_the_trace_and_span_they_belong_to(self):
        _, events = self.run_loop()

        spans = {span.name: span for span in reversed(self.exporter.get_finished_spans())}
        task = spans["task"]
        chat = spans["chat test-model"]
        tool = spans["execute_tool echo"]

        by_title = {event.title: event for event in events}
        self.assertEqual(by_title["Starting ReAct loop"].data["trace_id"], format(task.context.trace_id, "032x"))
        self.assertEqual(by_title["Starting ReAct loop"].data["span_id"], format(task.context.span_id, "016x"))
        self.assertEqual(by_title["LLM request Step 1"].data["span_id"], format(chat.context.span_id, "016x"))
        self.assertEqual(by_title["Tool call: echo"].data["span_id"], format(tool.context.span_id, "016x"))
        self.assertEqual(by_title["Tool call: echo"].data["trace_id"], format(task.context.trace_id, "032x"))
        # The closing event is emitted after the step span ends, so it belongs to the
        # task span; the trace still leads back to the whole call tree.
        self.assertEqual(by_title["ReAct run completed"].data["span_id"], format(task.context.span_id, "016x"))
        # The direct answer arrives on the second step, so that is the span it names.
        steps = [span for span in self.exporter.get_finished_spans() if span.name == "react.step"]
        self.assertEqual(by_title["ReAct finished"].data["span_id"], format(steps[1].context.span_id, "016x"))


class DisabledLoopTracingTest(unittest.TestCase):
    def setUp(self):
        init_telemetry(TelemetryConfig(enabled=False), batch=False)
        self.addCleanup(shutdown_telemetry)

    def test_turning_tracing_off_leaves_the_events_untouched(self):
        events = []
        with patch(
            "agent.agent_loop.loop._build_runtime",
            return_value=("openai", _Registry(), _Provider(), []),
        ):
            run_react_loop(
                user_query="echo hi",
                task_id="task-trace",
                max_steps=1,
                verbose=False,
                event_sink=lambda task_id, event: events.append(event),
            )

        self.assertTrue(events)
        for event in events:
            self.assertNotIn("trace_id", event.data)


if __name__ == "__main__":
    unittest.main()

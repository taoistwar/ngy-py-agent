"""Span helpers must nest, stay quiet when disabled, and never swallow errors.

Run from the repository root::

    uv run python test/telemetry/spans_test.py -v
"""

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode  # noqa: E402

from agent.telemetry import spans  # noqa: E402
from agent.telemetry.config import TelemetryConfig  # noqa: E402
from agent.telemetry.setup import init_telemetry, shutdown_telemetry  # noqa: E402


class _TracingTestCase(unittest.TestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        init_telemetry(
            TelemetryConfig(enabled=True, exporter="none"),
            span_exporter=self.exporter,
            batch=False,
        )
        self.addCleanup(shutdown_telemetry)

    def finished(self):
        return {span.name: span for span in self.exporter.get_finished_spans()}


class DisabledTracingTest(unittest.TestCase):
    def setUp(self):
        init_telemetry(TelemetryConfig(enabled=False), batch=False)
        self.addCleanup(shutdown_telemetry)

    def test_every_helper_is_a_no_op(self):
        self.assertFalse(spans.is_tracing_active())
        with spans.task_span("task-1") as task:
            with spans.react_step_span(1, 2) as step:
                with spans.llm_span("openai", "gpt", 1, 2) as llm:
                    with spans.tool_span("exec_command", {"command": "ls"}, 1) as tool:
                        self.assertIsNone(tool)
                    self.assertIsNone(llm)
                self.assertIsNone(step)
            self.assertIsNone(task)

        self.assertEqual(spans.current_trace_ids(), {})

    def test_starting_a_task_span_without_tracing_returns_nothing(self):
        self.assertIsNone(spans.start_task_span("task-1"))


class SpanNestingTest(_TracingTestCase):
    def test_task_step_and_tool_spans_form_one_tree(self):
        with spans.task_span("task-1", {"react.mode": "build"}):
            with spans.react_step_span(1, 2):
                with spans.tool_span("exec_command", {"command": "ls"}, 1):
                    pass

        task = self.finished()["task"]
        step = self.finished()["react.step"]
        tool = self.finished()["execute_tool exec_command"]
        self.assertEqual(task.parent, None)
        self.assertEqual(step.parent.span_id, task.context.span_id)
        self.assertEqual(tool.parent.span_id, step.context.span_id)
        self.assertEqual(
            {span.context.trace_id for span in (task, step, tool)},
            {task.context.trace_id},
        )
        self.assertEqual(task.attributes["task.id"], "task-1")
        self.assertEqual(task.attributes["react.mode"], "build")
        self.assertEqual(step.attributes["react.step"], 1)
        self.assertEqual(step.attributes["react.max_steps"], 2)

    def test_tool_arguments_are_summarized_without_secrets(self):
        with spans.task_span("task-1"):
            with spans.tool_span(
                "exec_command", {"command": "ls", "api_key": "sk-live"}, 1
            ):
                pass

        attributes = self.finished()["execute_tool exec_command"].attributes
        self.assertEqual(attributes["gen_ai.tool.name"], "exec_command")
        self.assertIn("ls", attributes["gen_ai.tool.call.arguments"])
        self.assertNotIn("sk-live", attributes["gen_ai.tool.call.arguments"])

    def test_a_llm_span_carries_the_gen_ai_attributes(self):
        with spans.task_span("task-1"):
            with spans.llm_span("openai", "qwen3:0.6b", 2, 7) as span:
                spans.record_llm_response(
                    span,
                    {"usage": {"prompt_tokens": 11, "completion_tokens": 5}},
                    finish_reason="stop",
                )

        attributes = self.finished()["chat qwen3:0.6b"].attributes
        self.assertEqual(attributes["gen_ai.system"], "openai")
        self.assertEqual(attributes["gen_ai.request.model"], "qwen3:0.6b")
        self.assertEqual(attributes["gen_ai.request.message_count"], 7)
        self.assertEqual(attributes["gen_ai.usage.input_tokens"], 11)
        self.assertEqual(attributes["gen_ai.usage.output_tokens"], 5)
        self.assertEqual(attributes["gen_ai.response.finish_reasons"], ("stop",))


class TaskSpanHandleTest(_TracingTestCase):
    def test_an_attached_handle_is_reused_instead_of_starting_a_second_root(self):
        handle = spans.start_task_span("task-1")
        token = spans.attach_task_span(handle)
        try:
            with spans.task_span("task-1") as inner:
                self.assertEqual(inner.get_span_context().span_id, handle.span.get_span_context().span_id)
            with spans.react_step_span(1, 1):
                pass
        finally:
            spans.detach_task_span(token)

        names = [span.name for span in self.exporter.get_finished_spans()]
        self.assertEqual(names, ["react.step"])
        spans.end_task_span(handle)
        self.assertEqual(
            [span.name for span in self.exporter.get_finished_spans()], ["react.step", "task"]
        )

    def test_current_trace_ids_report_the_active_span(self):
        with spans.task_span("task-1"):
            with spans.react_step_span(1, 1):
                ids = spans.current_trace_ids()

        self.assertEqual(len(ids["trace_id"]), 32)
        self.assertEqual(len(ids["span_id"]), 16)


class FailureHandlingTest(_TracingTestCase):
    def test_an_exception_marks_the_span_failed_and_propagates(self):
        with self.assertRaises(RuntimeError):
            with spans.task_span("task-1"):
                with spans.tool_span("exec_command", {"command": "ls"}, 1):
                    raise RuntimeError("tool exploded")

        span = self.finished()["execute_tool exec_command"]
        self.assertEqual(span.status.status_code, StatusCode.ERROR)
        self.assertEqual(len(span.events), 1)


if __name__ == "__main__":
    unittest.main()

"""A task runs on a worker thread; its span must still be the request's child.

Run from the repository root::

    uv run python test/telemetry/task_tracing_test.py -v
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

import task_runtime  # noqa: E402
from agent.telemetry import spans  # noqa: E402
from agent.telemetry.config import TelemetryConfig  # noqa: E402
from agent.telemetry.setup import init_telemetry, shutdown_telemetry  # noqa: E402
from commons.schemas import RunTaskRequest  # noqa: E402


class _Store:
    def __init__(self):
        self.events = []
        self.finished = []

    def append_event(self, task_id, event):
        self.events.append(event)

    def set_task_status(self, task_id, status):
        return

    def finish_task(self, *args, **kwargs):
        self.finished.append((args, kwargs))


def _fake_state(store):
    return SimpleNamespace(
        monitor_store=store,
        agent_max_steps=8,
        agents_md_enabled=True,
        agents_md_max_bytes=32768,
        permission_mode="auto_approve",
        status_for_event=lambda category: None,
        permission_rule_store=None,
        register_task_permission=lambda *args, **kwargs: None,
        register_task_questions=lambda *args, **kwargs: None,
        get_task_permission_broker=lambda *args, **kwargs: None,
        get_task_question_broker=lambda *args, **kwargs: None,
        clear_task_permission=lambda *args, **kwargs: None,
        clear_task_questions=lambda *args, **kwargs: None,
        clear_task_stop=lambda *args, **kwargs: None,
    )


class RunTaskTracingTest(unittest.TestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        init_telemetry(
            TelemetryConfig(enabled=True, exporter="none"),
            span_exporter=self.exporter,
            batch=False,
        )
        self.addCleanup(shutdown_telemetry)

    def test_run_task_attaches_the_handle_and_ends_it(self):
        store = _Store()
        seen = {}

        def fake_loop(**kwargs):
            seen["recording"] = trace.get_current_span().is_recording()
            seen["ids"] = spans.current_trace_ids()
            return "ok"

        handle = spans.start_task_span("task-1", {"task.mode": "build"})
        self.assertIsNotNone(handle)

        with (
            patch.object(task_runtime, "state", _fake_state(store)),
            patch.object(task_runtime, "run_react_loop", fake_loop),
            patch.object(task_runtime, "name_task_and_session", lambda *args: None),
        ):
            task_runtime.run_task("task-1", RunTaskRequest(query="hi"), otel_handle=handle)

        self.assertTrue(seen["recording"])
        task = {span.name: span for span in self.exporter.get_finished_spans()}["task"]
        self.assertEqual(task.attributes["task.id"], "task-1")
        self.assertEqual(task.attributes["task.mode"], "build")
        self.assertIsNotNone(task.end_time)

        start_event = store.events[0]
        self.assertEqual(start_event.title, "Start task execution")
        self.assertEqual(start_event.data["trace_id"], format(task.context.trace_id, "032x"))
        self.assertEqual(start_event.data["span_id"], format(task.context.span_id, "016x"))

    def test_a_failing_task_still_closes_its_span(self):
        store = _Store()

        def exploding_loop(**kwargs):
            raise RuntimeError("model exploded")

        handle = spans.start_task_span("task-2")

        with (
            patch.object(task_runtime, "state", _fake_state(store)),
            patch.object(task_runtime, "run_react_loop", exploding_loop),
            patch.object(task_runtime, "name_task_and_session", lambda *args: None),
        ):
            task_runtime.run_task("task-2", RunTaskRequest(query="hi"), otel_handle=handle)

        self.assertEqual([span.name for span in self.exporter.get_finished_spans()], ["task"])
        failure = [event for event in store.events if event.title == "Task failed"]
        self.assertEqual(len(failure), 1)
        self.assertIn("trace_id", failure[0].data)

    def test_no_handle_means_no_extra_span(self):
        store = _Store()

        with (
            patch.object(task_runtime, "state", _fake_state(store)),
            patch.object(task_runtime, "run_react_loop", lambda **kwargs: "ok"),
            patch.object(task_runtime, "name_task_and_session", lambda *args: None),
        ):
            task_runtime.run_task("task-3", RunTaskRequest(query="hi"))

        self.assertEqual(list(self.exporter.get_finished_spans()), [])
        self.assertNotIn("trace_id", store.events[0].data)


if __name__ == "__main__":
    unittest.main()

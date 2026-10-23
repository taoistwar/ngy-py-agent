"""Span attributes must stay small and free of secrets.

Run from the repository root::

    uv run python test/telemetry/attributes_test.py -v
"""

import json
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode  # noqa: E402

from agent.telemetry.attributes import (  # noqa: E402
    MAX_ATTRIBUTE_TEXT,
    preview_text,
    safe_attributes,
    set_error_status,
    summarize_arguments,
)


class PreviewTextTest(unittest.TestCase):
    def test_short_text_is_kept_verbatim(self):
        self.assertEqual(preview_text("hello"), "hello")

    def test_long_text_is_truncated_with_an_ellipsis(self):
        text = "a" * (MAX_ATTRIBUTE_TEXT + 100)

        preview = preview_text(text)

        self.assertLessEqual(len(preview), MAX_ATTRIBUTE_TEXT + 1)
        self.assertTrue(preview.endswith("…"))

    def test_none_becomes_an_empty_string(self):
        self.assertEqual(preview_text(None), "")


class SummarizeArgumentsTest(unittest.TestCase):
    def test_arguments_are_rendered_as_compact_json(self):
        summary = summarize_arguments({"path": "a.txt", "line": 3})

        self.assertEqual(json.loads(summary), {"line": 3, "path": "a.txt"})

    def test_secrets_are_replaced_before_they_reach_the_trace(self):
        summary = summarize_arguments(
            {
                "api_key": "sk-live-123",
                "Authorization": "Bearer abc",
                "nested": {"password": "hunter2", "safe": "keep"},
            }
        )

        self.assertNotIn("sk-live-123", summary)
        self.assertNotIn("Bearer abc", summary)
        self.assertNotIn("hunter2", summary)
        self.assertIn("keep", summary)
        self.assertIn("***", summary)

    def test_long_values_are_truncated(self):
        summary = summarize_arguments({"content": "x" * 5000})

        self.assertLess(len(summary), 1000)

    def test_non_mapping_arguments_are_summarized_as_text(self):
        self.assertEqual(summarize_arguments("plain text"), "plain text")
        self.assertEqual(summarize_arguments(None), "")


class SafeAttributesTest(unittest.TestCase):
    def test_primitives_pass_through_and_others_are_stringified(self):
        attributes = safe_attributes(
            {
                "text": "ok",
                "count": 2,
                "ratio": 0.5,
                "flag": True,
                "path": Path("a/b.txt"),
            }
        )

        self.assertEqual(attributes["text"], "ok")
        self.assertEqual(attributes["count"], 2)
        self.assertEqual(attributes["ratio"], 0.5)
        self.assertIs(attributes["flag"], True)
        self.assertEqual(attributes["path"], str(Path("a/b.txt")))

    def test_secret_keys_are_redacted(self):
        attributes = safe_attributes({"api_key": "sk-1", "model": "gpt"})

        self.assertEqual(attributes["api_key"], "***")
        self.assertEqual(attributes["model"], "gpt")


class ErrorStatusTest(unittest.TestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = provider.get_tracer("attributes-test")

    def test_error_status_records_the_exception(self):
        with self.tracer.start_as_current_span("execute_tool") as span:
            set_error_status(span, RuntimeError("boom"))

        finished = self.exporter.get_finished_spans()[0]
        self.assertEqual(finished.status.status_code, StatusCode.ERROR)
        self.assertIn("boom", finished.status.description)
        self.assertEqual(len(finished.events), 1)
        self.assertEqual(finished.events[0].name, "exception")


if __name__ == "__main__":
    unittest.main()

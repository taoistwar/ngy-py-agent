"""The local JSONL exporter must write one readable line per finished span.

Run from the repository root::

    uv run python test/telemetry/exporters_test.py -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.trace import Status, StatusCode  # noqa: E402

from agent.telemetry.exporters import JsonlSpanExporter  # noqa: E402


class _RecordedSpans:
    """Build real finished spans through a provider wired to the exporter."""

    def __init__(self, path: Path) -> None:
        self.exporter = JsonlSpanExporter(path)
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("telemetry-test")

    def emit(self) -> None:
        with self.tracer.start_as_current_span(
            "task", attributes={"task.id": "task-1", "gen_ai.system": "openai"}
        ) as parent:
            with self.tracer.start_as_current_span(
                "execute_tool exec_command", attributes={"tool.name": "exec_command"}
            ):
                pass
            parent.set_status(Status(StatusCode.OK))


class JsonlSpanExporterTest(unittest.TestCase):
    def test_export_writes_one_json_object_per_span(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "spans.jsonl"
            spans = _RecordedSpans(path)

            spans.emit()

            lines = path.read_text(encoding="utf-8").splitlines()
            records = [json.loads(line) for line in lines]
            self.assertEqual([record["name"] for record in records], ["execute_tool exec_command", "task"])
            self.assertEqual(records[1]["attributes"]["task.id"], "task-1")

    def test_a_record_carries_the_identifiers_needed_to_rebuild_the_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spans.jsonl"
            _RecordedSpans(path).emit()

            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            child, parent = records
            self.assertEqual(len(parent["trace_id"]), 32)
            self.assertEqual(len(parent["span_id"]), 16)
            self.assertEqual(child["trace_id"], parent["trace_id"])
            self.assertEqual(child["parent_span_id"], parent["span_id"])
            self.assertEqual(parent["status"]["code"], "OK")
            self.assertGreaterEqual(parent["duration_ms"], 0)
            self.assertEqual(parent["start_time"], int(parent["start_time_ns"] / 1_000_000))
            self.assertEqual(parent["end_time"], int(parent["end_time_ns"] / 1_000_000))

    def test_appending_keeps_earlier_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spans.jsonl"
            spans = _RecordedSpans(path)

            spans.emit()
            first_pass = len(path.read_text(encoding="utf-8").splitlines())
            spans.emit()
            second_pass = len(path.read_text(encoding="utf-8").splitlines())

            self.assertEqual(first_pass, 2)
            self.assertEqual(second_pass, 4)

    def test_an_unwritable_path_is_reported_instead_of_raised(self):
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "spans.jsonl"
            blocker.mkdir()
            spans = _RecordedSpans(blocker)

            # The exporter's contract is a result code, not an exception: a broken
            # trace file must never take the task down with it.
            spans.emit()

            self.assertTrue(blocker.is_dir())

    def test_flush_and_shutdown_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            exporter = JsonlSpanExporter(Path(directory) / "spans.jsonl")

            self.assertTrue(exporter.force_flush())
            self.assertTrue(exporter.force_flush())
            exporter.shutdown()
            exporter.shutdown()


if __name__ == "__main__":
    unittest.main()

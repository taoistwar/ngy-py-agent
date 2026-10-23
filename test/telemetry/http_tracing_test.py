"""An HTTP request must produce a span, and the streaming routes must be excluded.

Run from the repository root::

    uv run python test/telemetry/http_tracing_test.py -v
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

from agent.telemetry.config import TelemetryConfig  # noqa: E402
from agent.telemetry.setup import init_telemetry, shutdown_telemetry  # noqa: E402

try:  # TestClient needs httpx; it ships with the dev toolchain, not the runtime.
    from fastapi.testclient import TestClient
except Exception:  # noqa: BLE001 - a missing test client skips the module
    TestClient = None


@unittest.skipIf(TestClient is None, "httpx is required for the FastAPI test client")
class HttpTracingTest(unittest.TestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        init_telemetry(
            TelemetryConfig(enabled=True, exporter="none"),
            span_exporter=self.exporter,
            batch=False,
        )
        self.addCleanup(shutdown_telemetry)

    def test_a_request_is_recorded_and_the_streams_are_excluded(self):
        import main

        main._configure_telemetry()
        client = TestClient(main.app)

        self.assertEqual(client.get("/api/healthz").status_code, 200)

        names = [span.name for span in self.exporter.get_finished_spans()]
        self.assertTrue(
            any("healthz" in name for name in names), f"no HTTP span in {names}"
        )
        # The two long-lived routes would hold a span open for the task's lifetime.
        self.assertIn("/api/tasks/[^/]+/events/stream", main.OTEL_EXCLUDED_URLS)
        self.assertIn("/api/tasks/[^/]+/events/ws", main.OTEL_EXCLUDED_URLS)


if __name__ == "__main__":
    unittest.main()

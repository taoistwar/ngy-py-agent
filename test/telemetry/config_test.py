"""The telemetry switch is read from the environment, with safe fallbacks.

Run from the repository root::

    uv run python test/telemetry/config_test.py -v
"""

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.telemetry.config import (  # noqa: E402
    DEFAULT_JSONL_RELATIVE_PATH,
    TelemetryConfig,
    load_config,
    resolve_jsonl_path,
)


class TelemetryConfigTest(unittest.TestCase):
    def test_disabled_by_default_and_exports_nothing(self):
        config = load_config({})

        self.assertFalse(config.enabled)
        self.assertEqual(config.exporter, "jsonl")
        self.assertEqual(config.sample_ratio, 1.0)
        self.assertEqual(config.service_name, "ngy-py-agent")
        self.assertEqual(config.jsonl_path, _REPO_ROOT / DEFAULT_JSONL_RELATIVE_PATH)

    def test_truthy_env_values_enable_tracing(self):
        for raw in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(raw=raw):
                self.assertTrue(load_config({"OTEL_TRACING_ENABLED": raw}).enabled)

    def test_every_other_value_keeps_tracing_off(self):
        for raw in ("", "0", "false", "no", "off", "enabled"):
            with self.subTest(raw=raw):
                self.assertFalse(load_config({"OTEL_TRACING_ENABLED": raw}).enabled)

    def test_known_exporters_are_kept_and_unknown_ones_fall_back_to_jsonl(self):
        for raw in ("console", "jsonl", "none"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    load_config({"OTEL_TRACES_EXPORTER": raw}).exporter, raw
                )

        self.assertEqual(load_config({"OTEL_TRACES_EXPORTER": "s3"}).exporter, "jsonl")

    def test_sample_ratio_accepts_fractions_and_clamps_the_range(self):
        self.assertEqual(load_config({"OTEL_TRACES_SAMPLER_ARG": "0.25"}).sample_ratio, 0.25)
        self.assertEqual(load_config({"OTEL_TRACES_SAMPLER_ARG": "5"}).sample_ratio, 1.0)
        self.assertEqual(load_config({"OTEL_TRACES_SAMPLER_ARG": "-1"}).sample_ratio, 0.0)
        self.assertEqual(load_config({"OTEL_TRACES_SAMPLER_ARG": "many"}).sample_ratio, 1.0)

    def test_service_name_can_be_overridden(self):
        config = load_config({"OTEL_SERVICE_NAME": "agent-canary"})

        self.assertEqual(config.service_name, "agent-canary")

    def test_relative_jsonl_path_resolves_against_the_repository(self):
        config = load_config({"OTEL_TRACES_JSONL_PATH": "tmp/spans.jsonl"})

        self.assertEqual(config.jsonl_path, _REPO_ROOT / "tmp" / "spans.jsonl")

    def test_absolute_jsonl_path_is_kept_as_is(self):
        absolute = _REPO_ROOT / "var" / "trace.jsonl"

        self.assertEqual(resolve_jsonl_path(str(absolute)), absolute)

    def test_config_is_immutable_so_a_reader_cannot_flip_the_switch(self):
        config = TelemetryConfig()

        with self.assertRaises(Exception):
            config.enabled = True  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()

"""Telemetry settings, resolved once from the environment.

Tracing is off unless ``OTEL_TRACING_ENABLED`` says otherwise: the loop already has
its own event stream, so collecting traces is an opt-in diagnostic, not a default.
Invalid values fall back to the documented default instead of raising, because a typo
in ``.env`` must not stop the agent from starting.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

DEFAULT_SERVICE_NAME = "ngy-py-agent"
DEFAULT_JSONL_RELATIVE_PATH = Path("data") / "traces" / "spans.jsonl"
EXPORTERS = ("console", "jsonl", "none")
DEFAULT_EXPORTER = "jsonl"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def repository_root() -> Path:
    """The repository root, which is also the base for relative output paths."""
    return Path(__file__).resolve().parents[2]


def default_jsonl_path() -> Path:
    return repository_root() / DEFAULT_JSONL_RELATIVE_PATH


def resolve_jsonl_path(raw: str | None, root: Path | None = None) -> Path:
    """Resolve the configured path; a relative one lives under the repository."""
    text = (raw or "").strip()
    if not text:
        return default_jsonl_path()
    path = Path(text)
    if path.is_absolute():
        return path
    return (root or repository_root()) / path


@dataclass(frozen=True)
class TelemetryConfig:
    enabled: bool = False
    exporter: str = DEFAULT_EXPORTER
    jsonl_path: Path = field(default_factory=default_jsonl_path)
    sample_ratio: float = 1.0
    service_name: str = DEFAULT_SERVICE_NAME


def _as_bool(raw: str | None) -> bool:
    return (raw or "").strip().lower() in _TRUTHY


def _as_exporter(raw: str | None) -> str:
    text = (raw or "").strip().lower()
    if not text:
        return DEFAULT_EXPORTER
    if text in EXPORTERS:
        return text
    print(f"[telemetry] unknown OTEL_TRACES_EXPORTER='{raw}', using {DEFAULT_EXPORTER}")
    return DEFAULT_EXPORTER


def _as_ratio(raw: str | None) -> float:
    text = (raw or "").strip()
    if not text:
        return 1.0
    try:
        ratio = float(text)
    except ValueError:
        print(f"[telemetry] unknown OTEL_TRACES_SAMPLER_ARG='{raw}', using 1.0")
        return 1.0
    return min(1.0, max(0.0, ratio))


def load_config(env: Mapping[str, str] | None = None) -> TelemetryConfig:
    values = os.environ if env is None else env
    return TelemetryConfig(
        enabled=_as_bool(values.get("OTEL_TRACING_ENABLED")),
        exporter=_as_exporter(values.get("OTEL_TRACES_EXPORTER")),
        jsonl_path=resolve_jsonl_path(values.get("OTEL_TRACES_JSONL_PATH")),
        sample_ratio=_as_ratio(values.get("OTEL_TRACES_SAMPLER_ARG")),
        service_name=(values.get("OTEL_SERVICE_NAME") or "").strip() or DEFAULT_SERVICE_NAME,
    )

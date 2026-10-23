"""Process-wide tracer wiring.

Initialization is idempotent and opt-in. When tracing is off nothing is registered,
so ``agent.telemetry.spans`` degrades to plain ``with`` blocks that yield ``None``.
"""

import atexit
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from agent.telemetry.config import TelemetryConfig, load_config
from agent.telemetry.exporters import JsonlSpanExporter

INSTRUMENTATION_NAME = "ngy-py-agent"

_provider: TracerProvider | None = None
_initialized = False
_global_provider_set = False


def is_telemetry_enabled() -> bool:
    """True once a provider is registered and spans are being recorded."""
    return _provider is not None


def active_tracer() -> Any | None:
    """The tracer this process exports through, or ``None`` when tracing is off."""
    if _provider is None:
        return None
    return _provider.get_tracer(INSTRUMENTATION_NAME)


def build_span_exporter(config: TelemetryConfig) -> SpanExporter | None:
    if config.exporter == "console":
        return ConsoleSpanExporter()
    if config.exporter == "jsonl":
        return JsonlSpanExporter(config.jsonl_path)
    return None


def _install_global_provider(provider: TracerProvider) -> None:
    """Publish the provider once.

    OpenTelemetry allows ``set_tracer_provider`` a single time per process, and it
    refuses silently afterwards. Re-running under ``--reload`` (or in tests) must not
    depend on it, so spans go through :func:`active_tracer` instead.
    """
    global _global_provider_set
    if _global_provider_set:
        return
    try:
        trace.set_tracer_provider(provider)
    except Exception:  # noqa: BLE001 - a library may already own the global slot
        return
    _global_provider_set = True


def init_telemetry(
    config: TelemetryConfig | None = None,
    span_exporter: SpanExporter | None = None,
    batch: bool = True,
) -> bool:
    """Register the tracer provider; returns whether tracing is now active."""
    global _provider, _initialized

    if _initialized:
        return is_telemetry_enabled()
    _initialized = True

    settings = config or load_config()
    if not settings.enabled:
        return False

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.service_name}),
        sampler=ParentBased(TraceIdRatioBased(settings.sample_ratio)),
    )
    exporter = span_exporter if span_exporter is not None else build_span_exporter(settings)
    if exporter is not None:
        processor = BatchSpanProcessor(exporter) if batch else SimpleSpanProcessor(exporter)
        provider.add_span_processor(processor)

    _provider = provider
    _install_global_provider(provider)
    atexit.register(shutdown_telemetry)
    return True


def shutdown_telemetry() -> None:
    """Flush and close the provider; safe to call when tracing is off or twice."""
    global _provider, _initialized

    provider = _provider
    _provider = None
    _initialized = False
    if provider is None:
        return
    try:
        provider.shutdown()
    except Exception:  # noqa: BLE001 - shutdown runs at exit; it must not raise
        return

"""OpenTelemetry tracing for the ReAct loop.

The package is deliberately boring: business code only names a span and keeps its
existing ``try``/``except`` behaviour, while configuration, export and failure
handling live here. Import ``init_telemetry``/``shutdown_telemetry`` from the entry
point and one of the span helpers from the loop.
"""

from agent.telemetry.config import TelemetryConfig, load_config
from agent.telemetry.setup import (
    active_tracer,
    init_telemetry,
    is_telemetry_enabled,
    shutdown_telemetry,
)

__all__ = [
    "TelemetryConfig",
    "active_tracer",
    "init_telemetry",
    "is_telemetry_enabled",
    "load_config",
    "shutdown_telemetry",
]

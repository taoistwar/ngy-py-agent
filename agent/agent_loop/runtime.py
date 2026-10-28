"""Loop runtime: provider/tool wiring, event emission and session reaping."""

import functools
import inspect
import json
from typing import Any, Callable, Dict, List, Optional

from agent.agent_loop.config import TOOL_SCHEMA_PROVIDER
from agent.checkpoints import CheckpointStore
from agent.models import EventSink, TaskEvent
from agent.modes import (
    build_tool_registry,
    build_tool_registry_from_names,
)
from agent.provider import (
    ProviderConfig,
    build_provider,
    canonicalize_provider,
    resolve_tool_provider_for_schemas,
)
from agent.telemetry import task_span
from agent.tool_registry import ToolRegistry
from agent.tools import process_store


def _emit(
    event_sink: EventSink | None,
    task_id: str | None,
    event: TaskEvent,
) -> None:
    if event_sink is None or task_id is None:
        return
    # Deliberately broad: the sink is caller-supplied, and a failing listener must not
    # be the thing that aborts the run.
    try:
        event_sink(task_id, event)
    except Exception:  # noqa: BLE001
        # Event emission failures should not interrupt main flow.
        return


def _execute_tool(registry: ToolRegistry, name: str, arguments: Any) -> Any:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    return registry.execute_tool(name, arguments)


def _build_runtime(
    provider_name: Optional[str] = None,
    provider_config: Optional[ProviderConfig] = None,
    enable_tools: bool = True,
    mode: str = "build",
    base_dir: Optional[str] = None,
    agent_config: Optional[Dict[str, Any]] = None,
    task_id: str = "",
    should_stop: Optional[Callable[[], bool]] = None,
) -> tuple[str, ToolRegistry, Any, Optional[List[Dict[str, Any]]]]:
    provider_name = canonicalize_provider(provider_name or TOOL_SCHEMA_PROVIDER)
    registry_options = {
        "base_dir": base_dir,
        "max_tokens": int(getattr(provider_config, "max_input_tokens", 0) or 0),
        "provider": provider_name,
        "model": getattr(provider_config, "model", "") or "",
        "task_id": task_id,
        # Handed to the tools that can block, so a stop interrupts the tool itself
        # rather than waiting for it to return (ADR 0019).
        "should_stop": should_stop,
        # The undo history for this run. Built here rather than inside the registry
        # so which directory a run may record stays a decision of the loop (ADR 0020).
        "checkpoint_store": CheckpointStore.for_run(base_dir, task_id),
    }
    if not enable_tools:
        registry = ToolRegistry(enabled_tools=[], **registry_options)
    elif agent_config is not None:
        registry = build_tool_registry_from_names(
            agent_config.get("tool_names"), **registry_options
        )
    else:
        registry = build_tool_registry(mode, **registry_options)
    tool_schemas: Optional[List[Dict[str, Any]]] = None
    if enable_tools:
        try:
            request_provider = resolve_tool_provider_for_schemas(provider_name)
            tool_schemas = registry.get_tool_schemas(request_provider)
        except ValueError:
            print(
                f"Unsupported TOOL_SCHEMA_PROVIDER='{provider_name}', fallback to openai schema"
            )
            provider_name = "openai"
            tool_schemas = registry.get_tool_schemas("openai")

    provider = build_provider(provider_name, provider_config)
    return provider_name, registry, provider, tool_schemas


def _traced_run(func):
    """Open the task span for a whole loop run.

    A decorator rather than a ``with`` in the body: the body already carries four
    exits and re-indenting it would bury the change. The span reuses one an outer
    caller (the API worker) already started, so a run is traced once either way.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        # Defaults matter here: a CLI run passes neither ``mode`` nor ``max_steps``,
        # and a span without them says less than the run did.
        bound.apply_defaults()
        arguments = bound.arguments
        task_id = str(arguments.get("task_id") or "")
        attributes: dict[str, Any] = {
            "react.mode": arguments.get("mode"),
            "react.max_steps": arguments.get("max_steps"),
        }
        if task_id:
            # A CLI run has no task record; an empty id would only look like one.
            attributes["task.id"] = task_id
        with task_span(task_id, attributes):
            return func(*args, **kwargs)

    return wrapper


def _reaps_task_sessions(func):
    """Stop the loop's live sessions when it returns, however it returns.

    The loop has several exits (a final answer, the step limit, a stop request), so
    the reaping cannot be bolted onto one of them, and a ``finally`` inside would
    mean re-indenting the whole body. A wrapper keeps the change local and, because
    it sits here, every caller gets it: the API server, both CLI entry points and
    any library driving the loop directly (ADR 0008: sessions are task scoped).
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            bound = inspect.signature(func).bind_partial(*args, **kwargs)
            task_id = str(bound.arguments.get("task_id") or "")
            if task_id:
                process_store.stop_task(task_id)

    return wrapper

"""Run-scoped MCP servers: opened when a run starts, closed when it returns.

The loop has several exits (a final answer, the step limit, a stop request), and the
bridge is built below ``run_react_loop``, where that function's own ``finally`` cannot
reach it. So this is the choice ``process_store`` already made for background sessions:
a module-level registry keyed by task, plus a ``stop_task`` the loop's teardown calls
however the loop returns.

An empty task key is a CLI run; it is a key like any other, and stopping it after the
run is what keeps a REPL from accumulating one server set per turn.
"""

from __future__ import annotations

import threading
from typing import Any, Iterable, List, Mapping, Optional

from agent.mcp.bridge import McpBridge

_lock = threading.Lock()
_bridges: dict[str, List[McpBridge]] = {}


def _key(task_key: Optional[str]) -> str:
    return str(task_key or "")


def start_for_task(
    task_key: Optional[str],
    presets: Iterable[Mapping[str, Any]],
    **options: Any,
) -> Optional[McpBridge]:
    """Open every preset for one run.

    Returns ``None`` when the run selected no servers at all, which is the common case
    and must not allocate anything. A server that fails to start is reported in
    ``bridge.statuses`` and simply contributes no tools.
    """
    configured = [preset for preset in presets or [] if isinstance(preset, Mapping)]
    if not configured:
        return None
    bridge = McpBridge(configured, **options)
    bridge.open()
    with _lock:
        _bridges.setdefault(_key(task_key), []).append(bridge)
    return bridge


def stop_task(task_key: Optional[str]) -> None:
    """Close every bridge this run opened, child processes included."""
    key = _key(task_key)
    with _lock:
        bridges = _bridges.pop(key, [])
    for bridge in bridges:
        bridge.close()


def active(task_key: Optional[str]) -> List[McpBridge]:
    """Bridges still open for one run; empty once ``stop_task`` has run."""
    with _lock:
        return list(_bridges.get(_key(task_key), []))

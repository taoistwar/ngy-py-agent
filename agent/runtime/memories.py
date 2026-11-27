"""The memory library as the database keeps it, bound into the run's tools.

``agent.tools`` must not import ``commons``/``dao`` (ADR 0019), while this package is
allowed to read live state - so the store the memory tools write is injected here. It is
a thin adapter, not a second store: the SQL stays in :mod:`dao.memories`, and a test that
swaps ``commons.state.monitor_store`` reaches this adapter on its next call.

The book also carries the two decisions this layer owns: where the library is and whether
this deployment has memory switched on (``commons.state``, written by the admin API).
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent.tools.memory_store import MemoryBook
from commons import state


class MonitorMemoryStore:
    """``MemoryStore`` over this process's task store."""

    def list_memories(self) -> List[Dict[str, Any]]:
        return list(state.monitor_store.list_memories())

    def upsert_memory(
        self,
        name: str,
        memory_type: str,
        description: str,
        body: str,
        source_task_id: str = "",
    ) -> Dict[str, Any]:
        return state.monitor_store.upsert_memory(
            name, memory_type, description, body, source_task_id
        )

    def delete_memory(self, memory_id: str) -> bool:
        return bool(state.monitor_store.delete_memory(memory_id))


def memory_book_for_run(task_id: str = "") -> MemoryBook:
    """The library one run reads and writes, with this deployment's settings applied."""
    return MemoryBook(
        MonitorMemoryStore(),
        task_id=task_id,
        max_prompt_chars=state.memories_max_prompt_chars,
        enabled=state.memories_enabled,
    )


__all__ = ["MonitorMemoryStore", "memory_book_for_run"]

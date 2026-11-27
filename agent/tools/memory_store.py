"""Where memories live, and the run-scoped view the tools and the loop share.

Persistence is a contract rather than an implementation because ``agent.tools`` must
not import ``commons``/``dao`` (ADR 0019): the app layer injects the database store
(``agent.runtime.memories``), and a run with nothing bound keeps its memories in the
process, which is what library callers and tests get.

A :class:`MemoryBook` is what tools and the loop actually receive, so neither has to
know how the store is keyed or whether a database exists:

- ``snapshot()`` is the index read once per run to put memories in front of the model;
- ``save()`` is the write path, and the only place the library size limit is enforced;
- ``search()`` reads bodies on demand, which is what keeps them out of the prompt;
- ``enabled = False`` is a deployment that switched memory off: the tools still exist
  in the schema (dropping them would mean rebuilding the tool list per run) and answer
  that memory is disabled instead of silently pretending to save.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from agent.tools.memory_notes import (
    DEFAULT_MAX_PROMPT_CHARS,
    MAX_MEMORIES,
    rank_memories,
)


class MemoryStore(Protocol):
    """The persistence a memory library needs: list it, write one, remove one."""

    def list_memories(self) -> List[Dict[str, Any]]:
        """Every stored memory, oldest first; ``[]`` when there is none."""

    def upsert_memory(
        self,
        name: str,
        memory_type: str,
        description: str,
        body: str,
        source_task_id: str = "",
    ) -> Dict[str, Any]:
        """Store one record under ``name``, replacing what that name held."""

    def delete_memory(self, memory_id: str) -> bool:
        """Remove one memory by id; ``False`` when it was already gone."""


class MemoryDisabled(RuntimeError):
    """Memory is switched off for this deployment; nothing was written."""


class MemoryFull(RuntimeError):
    """The library already holds ``MAX_MEMORIES`` notes under other names."""


class InMemoryMemoryStore:
    """A store with no persistence: one process, one dictionary.

    The fallback for a run nobody bound a database to. Memories still work inside the
    run, they just do not outlive the process - which is exactly what a test or a
    library caller wants.
    """

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {}

    def list_memories(self) -> List[Dict[str, Any]]:
        return [dict(record) for record in self._records.values()]

    def upsert_memory(
        self,
        name: str,
        memory_type: str,
        description: str,
        body: str,
        source_task_id: str = "",
    ) -> Dict[str, Any]:
        record = {
            "memory_id": name,
            "name": name,
            "type": memory_type,
            "description": description,
            "body": body,
            "source_task_id": source_task_id,
        }
        self._records[name] = record
        return dict(record)

    def delete_memory(self, memory_id: str) -> bool:
        for name, record in list(self._records.items()):
            if memory_id in (name, record.get("memory_id")):
                del self._records[name]
                return True
        return False


class MemoryBook:
    """The memory library as one run sees it.

    ``store`` is ``None`` in a run nobody bound one: an in-memory library rather than a
    broken tool, the same fallback ``TodoBoard`` uses.
    """

    def __init__(
        self,
        store: Optional[MemoryStore] = None,
        task_id: str = "",
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
        enabled: bool = True,
    ) -> None:
        self.store: MemoryStore = store if store is not None else InMemoryMemoryStore()
        # Stamped on every memory this run writes, so a bad note can be traced back to
        # the task that produced it.
        self.task_id = task_id or ""
        # How much of the index may enter the system prompt (ADR 0035 D3).
        self.max_prompt_chars = max(0, int(max_prompt_chars or 0)) or DEFAULT_MAX_PROMPT_CHARS
        self.enabled = bool(enabled)

    def snapshot(self) -> List[Dict[str, Any]]:
        """The whole library as the index, without raising.

        Read once per run: a failing read must cost the run its memory of what it
        learned, not the run itself.
        """
        if not self.enabled:
            return []
        try:
            records = self.store.list_memories()
        # Deliberately broad: the store may be a caller-supplied object.
        except Exception:  # noqa: BLE001
            return []
        return [dict(record) for record in records if isinstance(record, dict)]

    def save(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Store one validated record; a store that cannot write raises to the caller."""
        if not self.enabled:
            raise MemoryDisabled("memory is disabled for this deployment.")
        existing = self.snapshot()
        known = {item.get("name") for item in existing}
        if len(existing) >= MAX_MEMORIES and record["name"] not in known:
            raise MemoryFull(
                f"the memory library already holds {MAX_MEMORIES} notes; delete an "
                "obsolete one from the Memory page before adding another."
            )
        return self.store.upsert_memory(
            record["name"],
            record["type"],
            record["description"],
            record["body"],
            self.task_id,
        )

    def search(self, query: Any, limit: int = 5) -> List[Dict[str, Any]]:
        """The stored notes matching ``query``, best first (bodies included)."""
        if not self.enabled:
            return []
        return rank_memories(self.snapshot(), query, limit)

    def delete(self, memory_id: str) -> bool:
        if not self.enabled:
            raise MemoryDisabled("memory is disabled for this deployment.")
        return bool(self.store.delete_memory(memory_id))

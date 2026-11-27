"""Cross-session memory: the library the agent keeps, and the page a person edits it on.

Two callers write here and they are deliberately the same store: the agent through
``memory_save`` (or the post-task extractor) and a person through this API. Anything the
model learned can therefore be corrected or deleted by hand, which is what makes a
wrong note recoverable (ADR 0035).

Validation is the same rules as the tool path (``agent/tools/memory_notes.py``); this
module only adds the two things HTTP has to decide - which status an id that does not
exist gets, and what happens when a rename collides with another note.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from agent.tools.memory_notes import (
    MAX_MEMORIES,
    memory_slug,
    one_line,
)
from commons import state
from commons.schemas import (
    MemoryConfigRequest,
    MemoryConfigResponse,
    MemoryCreateRequest,
    MemoryItemResponse,
    MemoryListResponse,
    MemoryUpdateRequest,
)

router = APIRouter()


def _config_response(total: int) -> MemoryConfigResponse:
    return MemoryConfigResponse(
        enabled=state.memories_enabled,
        auto_extract=state.memories_auto_extract,
        max_prompt_chars=state.memories_max_prompt_chars,
        source=state.memories_source,
        total=total,
    )


@router.get("/api/memories", response_model=MemoryListResponse)
async def list_memories() -> MemoryListResponse:
    """Every stored memory, plus the switches the page renders beside the list."""
    records = state.monitor_store.list_memories()
    return MemoryListResponse(
        memories=[MemoryItemResponse(**record) for record in records],
        total=len(records),
        enabled=state.memories_enabled,
        auto_extract=state.memories_auto_extract,
        max_prompt_chars=state.memories_max_prompt_chars,
        source=state.memories_source,
    )


@router.post("/api/memories", response_model=MemoryItemResponse)
async def save_memory(payload: MemoryCreateRequest) -> MemoryItemResponse:
    """Add a memory, or replace the note its name already holds.

    Replace rather than 409: the name *is* the identity of a note, and "save this again
    with a correction" is the normal way a memory is fixed - the same rule the tool
    follows, so the page and the agent cannot disagree about what a name means.
    """
    name = memory_slug(payload.name)
    if not name:
        raise HTTPException(status_code=400, detail="Name must contain letters, digits or dashes.")
    existing = state.monitor_store.get_memory_by_name(name)
    if existing is None and state.monitor_store.count_memories() >= MAX_MEMORIES:
        raise HTTPException(
            status_code=409,
            detail=f"The library already holds {MAX_MEMORIES} memories; delete one first.",
        )
    record = state.monitor_store.upsert_memory(
        name,
        payload.type,
        one_line(payload.description),
        payload.body,
        source_task_id="",
    )
    return MemoryItemResponse(**record)


@router.put("/api/memories/{memory_id}", response_model=MemoryItemResponse)
async def update_memory(memory_id: str, payload: MemoryUpdateRequest) -> MemoryItemResponse:
    """Change one memory; omitted fields stay as they are."""
    changes: dict[str, Any] = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if not state.monitor_store.get_memory(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found.")
    if "name" in changes:
        name = memory_slug(changes["name"])
        if not name:
            raise HTTPException(
                status_code=400, detail="Name must contain letters, digits or dashes."
            )
        clash = state.monitor_store.get_memory_by_name(name)
        if clash is not None and clash["memory_id"] != memory_id:
            raise HTTPException(status_code=409, detail=f"Memory {name!r} already exists.")
        changes["name"] = name
    if "description" in changes:
        changes["description"] = one_line(changes["description"])
    updated = state.monitor_store.update_memory(
        memory_id,
        name=changes.get("name"),
        memory_type=changes.get("type"),
        description=changes.get("description"),
        body=changes.get("body"),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return MemoryItemResponse(**updated)


@router.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: str) -> dict[str, Any]:
    if not state.monitor_store.delete_memory(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"memory_id": memory_id, "deleted": True}


# --------------------------------------------------------------------- configuration


@router.get("/api/admin/memory-config", response_model=MemoryConfigResponse)
async def get_memory_config() -> MemoryConfigResponse:
    return _config_response(state.monitor_store.count_memories())


@router.put("/api/admin/memory-config", response_model=MemoryConfigResponse)
async def set_memory_config(payload: MemoryConfigRequest) -> MemoryConfigResponse:
    """Write the switches, then make them live for the next run.

    Database first and state second, like every other admin write: a task reads
    ``commons.state`` on its next run, so the panel's change must not need a restart.
    """
    state.monitor_store.set_memory_config(
        payload.enabled, payload.auto_extract, payload.max_prompt_chars
    )
    state.memories_enabled = payload.enabled
    state.memories_auto_extract = payload.auto_extract
    state.memories_max_prompt_chars = payload.max_prompt_chars
    state.memories_source = "database"
    return _config_response(state.monitor_store.count_memories())

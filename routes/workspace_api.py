"""Sessions and workspaces.

These two are the context a task runs in - who owns it and which folder it starts in - so
they share one module rather than two that would each be a handful of thin routes over
the same store. Which model and endpoint it talks to lives in :mod:`llm_api`, because
providers and models are configuration in their own right (ADR 0014).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

import app_state
from api_schemas import (
    ContextUsageResponse,
    SessionCreateRequest,
    SessionItemResponse,
    SessionListResponse,
    SessionUpdateRequest,
    WorkspaceCreateRequest,
    WorkspaceItemResponse,
    WorkspaceListResponse,
    WorkspaceUpdateRequest,
)
from context_usage import session_context_usage
from task_runtime import default_session_name

router = APIRouter()


# --------------------------------------------------------------------- sessions


@router.get("/api/sessions", response_model=SessionListResponse)
async def list_sessions() -> SessionListResponse:
    sessions = app_state.monitor_store.list_sessions()
    items = []
    for item in sessions:
        tasks = app_state.monitor_store.list_tasks(session_id=item["session_id"])
        query_preview = " ".join(str(task.get("query", "")) for task in tasks)
        result_preview = " ".join(
            str(task.get("result", "")) for task in tasks if task.get("result")
        )
        items.append(
            SessionItemResponse(
                **item,
                query_preview=query_preview,
                result_preview=result_preview,
            )
        )
    return SessionListResponse(sessions=items)


@router.post("/api/sessions", response_model=SessionItemResponse)
async def create_session(payload: SessionCreateRequest) -> SessionItemResponse:
    name = (payload.name or "").strip() or default_session_name()
    workspace_id = (payload.workspace_id or "").strip() or None
    if workspace_id and app_state.monitor_store.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    session_id = app_state.monitor_store.create_session(name, workspace_id)
    session = app_state.monitor_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=500, detail="Failed to read created session.")
    return SessionItemResponse(**session)


@router.put("/api/sessions/{session_id}", response_model=SessionItemResponse)
async def rename_session(session_id: str, payload: SessionUpdateRequest) -> SessionItemResponse:
    if not app_state.monitor_store.rename_session(session_id, payload.name.strip()):
        raise HTTPException(status_code=404, detail="Session not found.")
    session = app_state.monitor_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return SessionItemResponse(**session)


@router.get("/api/sessions/{session_id}/context", response_model=ContextUsageResponse)
async def session_context(
    session_id: str,
    model_id: str | None = Query(
        None, description="Model the composer has selected; its window is the denominator."
    ),
) -> ContextUsageResponse:
    """How full the context window of this session already is.

    Read back after every turn, so the composer can say how much room is left before
    a task is started rather than after the provider refuses one.
    """
    if app_state.monitor_store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if model_id and app_state.monitor_store.llm.get_model(model_id) is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    return ContextUsageResponse(**session_context_usage(session_id, model_id))


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    existing = app_state.monitor_store.list_sessions()
    if len(existing) <= 1:
        raise HTTPException(status_code=400, detail="At least one session must be kept.")
    if not app_state.monitor_store.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"session_id": session_id, "deleted": True}


# ------------------------------------------------------------------- workspaces


@router.get("/api/workspaces", response_model=WorkspaceListResponse)
async def list_workspaces() -> WorkspaceListResponse:
    workspaces = app_state.monitor_store.list_workspaces()
    return WorkspaceListResponse(workspaces=[WorkspaceItemResponse(**item) for item in workspaces])


@router.post("/api/workspaces", response_model=WorkspaceItemResponse)
async def create_workspace(payload: WorkspaceCreateRequest) -> WorkspaceItemResponse:
    workspace_id = app_state.monitor_store.create_workspace(
        payload.name.strip(), payload.root_path.strip()
    )
    workspace = app_state.monitor_store.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=500, detail="Failed to read created workspace.")
    return WorkspaceItemResponse(**workspace)


@router.put("/api/workspaces/{workspace_id}", response_model=WorkspaceItemResponse)
async def update_workspace(
    workspace_id: str, payload: WorkspaceUpdateRequest
) -> WorkspaceItemResponse:
    name = payload.name.strip() if payload.name is not None else None
    root_path = payload.root_path.strip() if payload.root_path is not None else None
    updated = app_state.monitor_store.update_workspace(
        workspace_id, name=name, root_path=root_path
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return WorkspaceItemResponse(**updated)


@router.delete("/api/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str) -> dict[str, Any]:
    if not app_state.monitor_store.delete_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return {"workspace_id": workspace_id, "deleted": True}




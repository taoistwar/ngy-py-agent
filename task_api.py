"""Task routes: create, list, inspect, stop, delete, stream - and answer.

The two answer endpoints are the inbound half of the two blocking channels. In both, a
tool call is parked inside the task thread until the answer arrives, the deadline passes,
or the task is stopped; the gate fails closed on silence (ADR 0006) while a question does
not (ADR 0010 D2), and the difference shows up in what the tool gets back, not here.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

import app_state
from agent.models import TaskStatus
from agent.modes import DEFAULT_MODE, VALID_MODES
from agent.tools.permissions import SCOPES
from agent.tools.user_question import STATUS_ANSWERED, validate_answers
from api_schemas import (
    EventPageResponse,
    PermissionDecisionRequest,
    PermissionDecisionResponse,
    QuestionAnswerRequest,
    QuestionAnswerResponse,
    RunTaskRequest,
    RunTaskResponse,
    TaskDetailResponse,
    TaskListItemResponse,
    TaskListResponse,
)
from task_runtime import (
    agent_runtime_config,
    extract_task_result,
    purge_expired_tasks_with_log,
    resolve_session_base_dir,
    run_task,
)

router = APIRouter()


@router.post("/api/tasks", response_model=RunTaskResponse)
async def create_task(payload: RunTaskRequest) -> RunTaskResponse:
    purge_expired_tasks_with_log("Creating new API task")
    agent_id = (payload.agent_id or "").strip() or (
        payload.mode if payload.mode in VALID_MODES else DEFAULT_MODE
    )
    agent = app_state.monitor_store.get_agent(agent_id)
    if agent is None:
        agent_id = payload.mode if payload.mode in VALID_MODES else DEFAULT_MODE
        agent = app_state.monitor_store.get_agent(agent_id)
    model = app_state.monitor_store.get_model(payload.model_id) if payload.model_id else None
    if payload.model_id and model is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    session_id = payload.session_id
    if session_id and app_state.monitor_store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if not session_id:
        session_id = app_state.monitor_store.ensure_default_session()

    provider = str((model or {}).get("provider") or payload.provider or "openai-compatible")
    task_id = app_state.monitor_store.create_task(
        query=payload.query,
        provider=provider,
        session_id=session_id,
        model_id=payload.model_id,
        mode=agent_id,
    )

    request = payload.model_copy(update={"session_id": session_id, "mode": agent_id})
    agent_config = agent_runtime_config(agent)
    base_dir = resolve_session_base_dir(session_id)
    stop_event = app_state.register_task_stop(task_id)
    threading.Thread(
        target=run_task,
        args=(task_id, request, model, base_dir, agent_config, stop_event),
        daemon=True,
    ).start()

    trace = app_state.monitor_store.get_task(task_id)
    if trace is None:
        raise HTTPException(status_code=500, detail="Failed to read created task record.")
    return RunTaskResponse(
        task_id=task_id,
        status=str(trace["status"]),
        mode=trace["mode"],
        created_at=trace["created_at"],
    )


@router.get("/api/tasks", response_model=TaskListResponse)
async def list_tasks(
    session_id: str | None = Query(
        None, description="Only return tasks that belong to this session."
    ),
) -> TaskListResponse:
    tasks = app_state.monitor_store.list_tasks(session_id=session_id)
    return TaskListResponse(
        tasks=[
            TaskListItemResponse(
                **{
                    **item,
                    "pending_permission": app_state.pending_permission(item["task_id"]),
                    "pending_question": app_state.pending_question(item["task_id"]),
                }
            )
            for item in tasks
        ]
    )


@router.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str) -> dict[str, Any]:
    """Request a running task to stop; marks stale running tasks as stopped."""
    trace = app_state.monitor_store.get_task(task_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    stopped = app_state.signal_task_stop(task_id)
    if not stopped and str(trace.get("status")) == TaskStatus.RUNNING.value:
        app_state.monitor_store.finish_task(task_id, success=False, status=TaskStatus.STOPPED)
        stopped = True
    return {"task_id": task_id, "stopped": stopped}


@router.post(
    "/api/tasks/{task_id}/permission/{request_id}",
    response_model=PermissionDecisionResponse,
)
async def answer_permission(
    task_id: str,
    request_id: str,
    payload: PermissionDecisionRequest,
) -> PermissionDecisionResponse:
    """Answer a pending confirmation, unblocking the task's waiting thread.

    This is the other half of the gate: the tool call is parked inside the task
    thread until this arrives, the deadline passes, or the task is stopped.
    """
    broker = app_state.get_task_permission_broker(task_id)
    if broker is None:
        raise HTTPException(status_code=404, detail="Task not found or not running.")
    # Rejected rather than coerced: mapping an unknown scope onto "once" would
    # silently turn "always allow" into a one-off without telling anyone.
    if payload.scope not in SCOPES:
        raise HTTPException(
            status_code=400, detail=f"Unknown permission scope '{payload.scope}'."
        )
    # A tool may offer fewer answers than the global set (``write_stdin`` cannot take
    # a standing rule). Refuse the answer it does not accept rather than downgrading.
    offered = broker.request_scopes(request_id)
    if offered is not None and payload.scope not in offered:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This tool does not accept the '{payload.scope}' scope; "
                f"choose one of: {', '.join(offered)}."
            ),
        )
    if not broker.resolve(request_id, payload.allowed, payload.scope):
        raise HTTPException(status_code=409, detail="Permission request is no longer pending.")
    return PermissionDecisionResponse(
        task_id=task_id,
        request_id=request_id,
        allowed=payload.allowed,
        scope=payload.scope,
    )


@router.post(
    "/api/tasks/{task_id}/question/{request_id}",
    response_model=QuestionAnswerResponse,
)
async def answer_question(
    task_id: str,
    request_id: str,
    payload: QuestionAnswerRequest,
) -> QuestionAnswerResponse:
    """Answer a pending question batch, unblocking the task's waiting thread.

    The other half of the question channel: the tool call is parked inside the task
    thread until this arrives, the deadline passes, or the task is stopped. Unlike a
    permission answer, this one carries **data**, so a malformed body is refused
    rather than coerced - an id nobody asked about, or a non-string answer, would
    otherwise reach the model as an answer to a question it never asked.
    """
    broker = app_state.get_task_question_broker(task_id)
    if broker is None:
        raise HTTPException(status_code=404, detail="Task not found or not running.")
    pending = broker.pending()
    if pending is None or pending.request_id != request_id:
        raise HTTPException(status_code=409, detail="Question request is no longer pending.")
    answers, error = validate_answers(pending, payload.model_dump())
    if error is not None:
        raise HTTPException(status_code=400, detail=error)
    if not broker.resolve(request_id, answers or {}):
        raise HTTPException(status_code=409, detail="Question request is no longer pending.")
    return QuestionAnswerResponse(
        task_id=task_id,
        request_id=request_id,
        status=STATUS_ANSWERED,
        answered_count=len(answers or {}),
    )


@router.get("/api/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(task_id: str) -> TaskDetailResponse:
    trace = app_state.monitor_store.get_task(task_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    result = extract_task_result(trace.get("events"))
    broker = app_state.get_task_permission_broker(task_id)
    pending = broker.pending() if broker is not None else None
    return TaskDetailResponse(
        task_id=trace["task_id"],
        query=trace["query"],
        status=trace["status"],
        provider=trace["provider"],
        session_id=trace.get("session_id"),
        model_id=trace.get("model_id"),
        model_name=trace.get("model_name"),
        mode=trace.get("mode", DEFAULT_MODE),
        created_at=trace["created_at"],
        updated_at=trace["updated_at"],
        result=result,
        pending_permission=pending.to_payload() if pending is not None else None,
        pending_question=app_state.pending_question(task_id),
        events=trace["events"],
    )


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str) -> dict[str, Any]:
    removed = app_state.monitor_store.delete_task(task_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"task_id": task_id, "deleted": True}


@router.get("/api/tasks/{task_id}/events", response_model=EventPageResponse)
async def get_task_events(
    task_id: str,
    offset: int = Query(0, ge=0, description="Start position in the event list."),
    limit: int = Query(30, ge=1, le=100, description="Number of events to return, 1-100."),
    since: int | None = Query(
        None, ge=0, description="Start at this offset instead of the default offset."
    ),
) -> EventPageResponse:
    if app_state.monitor_store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    real_offset = offset if since is None else max(0, since)
    items, total = app_state.monitor_store.list_events_paginated(
        task_id=task_id,
        offset=real_offset,
        limit=limit,
    )
    next_offset = real_offset + len(items)
    return EventPageResponse(
        items=items,
        offset=real_offset,
        limit=limit,
        next_offset=next_offset,
        total=total,
        has_more=next_offset < total,
    )


async def _iter_task_events(task_id: str):
    seen = 0
    while True:
        task = app_state.monitor_store.get_task(task_id)
        if task is None:
            return
        events = app_state.monitor_store.get_events(task_id)

        while seen < len(events):
            yield events[seen]
            seen += 1

        # WAITING is still in flight: if the stream stopped here, the client would
        # never receive the confirmation request it is supposed to answer.
        if task["status"] not in (TaskStatus.RUNNING, TaskStatus.WAITING):
            return

        await asyncio.sleep(0.6)


@router.get("/api/tasks/{task_id}/events/stream")
async def stream_task_events(task_id: str) -> StreamingResponse:
    if app_state.monitor_store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    async def _generator() -> Any:
        async for event in _iter_task_events(task_id):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(_generator(), media_type="text/event-stream")


@router.websocket("/api/tasks/{task_id}/events/ws")
async def stream_task_events_ws(
    websocket: WebSocket,
    task_id: str,
    since: str | None = None,
    heartbeat: int = 0,
) -> None:
    await websocket.accept()
    if app_state.monitor_store.get_task(task_id) is None:
        await websocket.close(code=1008, reason="Task not found.")
        return

    heartbeat_interval = max(0, heartbeat)
    heartbeat_at = asyncio.get_running_loop().time()
    last_event_id = since

    try:
        while True:
            events = app_state.monitor_store.get_events_since(task_id, since_event_id=last_event_id)
            if events:
                for event in events:
                    await websocket.send_text(json.dumps(event, default=str))
                    last_event_id = event.get("event_id")
                heartbeat_at = asyncio.get_running_loop().time()
                continue

            task = app_state.monitor_store.get_task(task_id)
            if task is None:
                await websocket.close(code=1008, reason="Task not found.")
                return

            if task["status"] not in (TaskStatus.RUNNING, TaskStatus.WAITING):
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "done",
                            "task_id": task_id,
                            "status": task["status"],
                        }
                    )
                )
                return

            now = asyncio.get_running_loop().time()
            if heartbeat_interval > 0 and now - heartbeat_at >= heartbeat_interval:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "heartbeat",
                            "task_id": task_id,
                            "ts": datetime.now(UTC).isoformat(),
                        }
                    )
                )
                heartbeat_at = now

            await asyncio.sleep(0.6)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001 - a streaming failure closes the socket, not the server
        await websocket.close(code=1011, reason="Internal server error while streaming task events.")
        return

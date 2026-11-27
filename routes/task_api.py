"""Task routes: create, list, inspect, stop, delete, stream - and answer.

The two answer endpoints are the inbound half of the two blocking channels. In both, a
tool call is parked inside the task thread until the answer arrives or the task is
stopped - the gate also gives up at its deadline, a question never does (ADR 0010 D2).
The gate fails closed on silence (ADR 0006) while a question does not, and the
difference shows up in what the tool gets back, not here.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from agent.models import EventCategory, TaskStatus
from agent.modes import DEFAULT_MODE
from agent.runtime import (
    board_view,
    build_event,
    checkpoint_store_for_task,
    extract_task_result,
    purge_expired_tasks_with_log,
)
from agent.runtime.launcher import TaskLaunchError, launch_task
from agent.tools.permissions import SCOPES
from agent.tools.user_question import STATUS_ANSWERED, validate_answers
from agent.usage import task_usage_summary
from commons import state
from commons.schemas import (
    EventPageResponse,
    ForkTaskResponse,
    PermissionDecisionRequest,
    PermissionDecisionResponse,
    QuestionAnswerRequest,
    QuestionAnswerResponse,
    RevertTaskRequest,
    RunTaskRequest,
    RunTaskResponse,
    SessionItemResponse,
    TaskDetailResponse,
    TaskListItemResponse,
    TaskListResponse,
)

router = APIRouter()


@router.post("/api/tasks", response_model=RunTaskResponse)
async def create_task(payload: RunTaskRequest) -> RunTaskResponse:
    purge_expired_tasks_with_log("Creating new API task")
    # The resolution and the thread live in ``agent.runtime.launcher``: the scheduler
    # starts tasks the same way, and two copies of this would drift.
    try:
        launched = launch_task(
            query=payload.query,
            session_id=payload.session_id,
            model_id=payload.model_id,
            provider=payload.provider,
            agent_id=payload.agent_id,
            mode=payload.mode,
            stream=payload.stream,
            permission_mode=payload.permission_mode,
            max_steps=payload.max_steps,
        )
    except TaskLaunchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return RunTaskResponse(
        task_id=launched.task_id,
        status=launched.status,
        mode=launched.mode,
        created_at=launched.created_at,
    )


@router.get("/api/tasks", response_model=TaskListResponse)
async def list_tasks(
    session_id: str | None = Query(
        None, description="Only return tasks that belong to this session."
    ),
) -> TaskListResponse:
    tasks = state.monitor_store.list_tasks(session_id=session_id)
    return TaskListResponse(
        tasks=[
            TaskListItemResponse(
                **{
                    **item,
                    "pending_permission": state.pending_permission(item["task_id"]),
                    "pending_question": state.pending_question(item["task_id"]),
                }
            )
            for item in tasks
        ]
    )


# Statuses a stop request has nothing left to do for: the task is settled, and
# rewriting it would only replace a result somebody may still be reading.
_SETTLED_STATUSES = frozenset(
    {
        TaskStatus.SUCCESS.value,
        TaskStatus.FAILED.value,
        TaskStatus.STOPPED.value,
        TaskStatus.REVERTED.value,
    }
)


# A fork copies a turn's log, so a turn that is still writing is not history yet.
_IN_FLIGHT_STATUSES = frozenset({TaskStatus.RUNNING.value, TaskStatus.WAITING.value})


@router.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str) -> dict[str, Any]:
    """Stop a task: signal its thread, and settle the record on the spot.

    The signal is cooperative (ADR 0019): the loop reads it at a step boundary, and
    a thread parked inside a model request only reads it when that request returns -
    seconds to minutes later. Waiting for that to change the record made the click
    look broken: the row kept saying "running", and clicking again did nothing
    because the flag was already set. So the click is the decision and is recorded
    here; the thread unwinding afterwards fills in its result but cannot flip the
    status back (see ``_SqliteTaskStore.finish_task``).
    """
    trace = _stored_task(task_id)
    if str(trace.get("status")) in _SETTLED_STATUSES:
        return {"task_id": task_id, "stopped": False}
    state.signal_task_stop(task_id)
    state.monitor_store.finish_task(task_id, success=False, status=TaskStatus.STOPPED)
    return {"task_id": task_id, "stopped": True}


def _stored_task(task_id: str) -> dict[str, Any]:
    """The task record, or the 404 every per-task route answers with."""
    trace = state.monitor_store.get_task(task_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return trace


def _undo_store(task_id: str, trace: dict[str, Any]) -> Any:
    """The undo history for a task, or the 409 explaining why there is none.

    "No history" is not "no changes": a machine without git, a task from before this
    feature, and a workspace that no longer exists all land here, and the answer has
    to say which one it was rather than offering an undo that cannot work (ADR 0020 D7).
    """
    store = checkpoint_store_for_task(trace)
    if store is None:
        raise HTTPException(status_code=409, detail="Checkpointing is disabled for this run.")
    if not store.enable():
        raise HTTPException(
            status_code=409, detail=store.unavailable_reason or "Checkpointing is unavailable."
        )
    return store


@router.get("/api/tasks/{task_id}/changes")
async def task_changes(task_id: str) -> dict[str, Any]:
    """What this task changed, per file, so the UI can offer an undo."""
    trace = _stored_task(task_id)
    store = checkpoint_store_for_task(trace)
    if store is None or not store.enable():
        return {
            "task_id": task_id,
            "available": False,
            "reason": (
                store.unavailable_reason
                if store is not None
                else "Checkpointing is disabled for this run."
            ),
            "files": [],
        }
    return {
        "task_id": task_id,
        "available": True,
        "reason": "",
        "files": [item.to_dict() for item in store.changes(task_id)],
    }


@router.get("/api/tasks/{task_id}/changes/diff")
async def task_change_diff(task_id: str, path: str = Query(..., min_length=1)) -> dict[str, Any]:
    """One file's diff. Fetched on demand: a task can touch enough files to matter.

    ``before``/``after`` are the full texts the UI renders side by side; ``diff`` is
    the patch, kept for the fallback and for callers that only want the hunks.
    """
    store = _undo_store(task_id, _stored_task(task_id))
    sides = store.sides(task_id, path)
    return {
        "task_id": task_id,
        "path": path,
        "diff": store.diff(task_id, path),
        "before": sides["before"],
        "after": sides["after"],
    }


@router.post("/api/tasks/{task_id}/revert")
async def revert_task(task_id: str, payload: RevertTaskRequest) -> dict[str, Any]:
    """Undo this task's changes, per file, and record what happened."""
    store = _undo_store(task_id, _stored_task(task_id))
    result = store.revert(task_id, payload.paths, payload.force)
    payload_out = {"task_id": task_id, **result.to_dict()}
    state.monitor_store.append_event(
        task_id,
        build_event(task_id, EventCategory.DEBUG, "Task reverted", payload_out),
    )
    # Only a revert that leaves nothing behind makes the task "reverted". A partial
    # undo, or one with conflicts, leaves the task as it was: its changes are still
    # on disk, so the turn is still part of what the workspace contains.
    completed = bool(result.restored) and result.clean and not store.changes(task_id)
    if completed:
        # ``set_task_status`` rather than ``finish_task``: the result is still worth
        # reading, and only the status changes (see its docstring).
        state.monitor_store.set_task_status(task_id, TaskStatus.REVERTED)
    payload_out["status"] = (
        TaskStatus.REVERTED.value
        if completed
        else str(_stored_task(task_id).get("status"))
    )
    return payload_out


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
    broker = state.get_task_permission_broker(task_id)
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
    thread until this arrives or the task is stopped - there is no deadline to outlast
    (ADR 0010 D2, revised). Unlike a permission answer, this one carries **data**, so a
    malformed body is refused rather than coerced - an id nobody asked about, or a
    non-string answer, would otherwise reach the model as an answer to a question it
    never asked.
    """
    broker = state.get_task_question_broker(task_id)
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
    trace = state.monitor_store.get_task(task_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    result = extract_task_result(trace.get("events"))
    usage = task_usage_summary(trace)
    # The plan belongs to the session, so every task of the conversation shows the
    # same list - including the one that has not touched it.
    session_todos = state.monitor_store.get_session_todos(trace.get("session_id"))
    # The board belongs to the workspace, one level up: every conversation of the
    # project shows the same graph, which is what lets them coordinate through it.
    board = board_view(trace.get("session_id"))
    broker = state.get_task_permission_broker(task_id)
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
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        total_tokens=usage["total_tokens"],
        duration_ms=usage["duration_ms"],
        result=result,
        pending_permission=pending.to_payload() if pending is not None else None,
        pending_question=state.pending_question(task_id),
        todos=list((session_todos or {}).get("todos") or []),
        board=board,
        events=trace["events"],
    )


@router.post("/api/tasks/{task_id}/fork", response_model=ForkTaskResponse)
async def fork_task(task_id: str) -> ForkTaskResponse:
    """Branch a new session at this task.

    The new session carries a copy of this task and of every task before it in the
    same session, so the branch continues from the same transcript while the original
    conversation keeps its own turns untouched.

    A task that is still in flight is refused: its event log is still being written,
    so a copy of it would be a snapshot of half a turn.
    """
    trace = _stored_task(task_id)
    if str(trace.get("status")) in _IN_FLIGHT_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Task is still running; wait for it to settle before forking.",
        )
    session_id = trace.get("session_id")
    if not session_id:
        raise HTTPException(status_code=409, detail="Task has no session to fork.")
    forked = state.monitor_store.fork_session_through_task(task_id)
    if forked is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    session = state.monitor_store.get_session(forked["session_id"])
    if session is None:
        raise HTTPException(status_code=500, detail="Failed to read forked session.")
    return ForkTaskResponse(
        session_id=forked["session_id"],
        session=SessionItemResponse(**session),
        task_id=forked["task_id"],
        source_session_id=forked["source_session_id"],
        source_task_id=forked["source_task_id"],
        copied_task_count=forked["copied_task_count"],
        event_count=forked["event_count"],
    )


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str) -> dict[str, Any]:
    # Read the task before deleting it: the checkpoint refs are keyed by it, and once
    # the row is gone there is no way to find the workspace they belong to.
    trace = state.monitor_store.get_task(task_id)
    removed = state.monitor_store.delete_task(task_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Task not found.")
    store = checkpoint_store_for_task(trace)
    if store is not None:
        store.forget(task_id)
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
    if state.monitor_store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    real_offset = offset if since is None else max(0, since)
    items, total = state.monitor_store.list_events_paginated(
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
        task = state.monitor_store.get_task(task_id)
        if task is None:
            return
        events = state.monitor_store.get_events(task_id)

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
    if state.monitor_store.get_task(task_id) is None:
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
    if state.monitor_store.get_task(task_id) is None:
        await websocket.close(code=1008, reason="Task not found.")
        return

    heartbeat_interval = max(0, heartbeat)
    heartbeat_at = asyncio.get_running_loop().time()
    last_event_id = since

    try:
        while True:
            events = state.monitor_store.get_events_since(task_id, since_event_id=last_event_id)
            if events:
                for event in events:
                    await websocket.send_text(json.dumps(event, default=str))
                    last_event_id = event.get("event_id")
                heartbeat_at = asyncio.get_running_loop().time()
                continue

            task = state.monitor_store.get_task(task_id)
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

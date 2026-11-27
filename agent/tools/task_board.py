"""The rules of the task board: dependencies, claims, completion.

A **board task** is a unit of work with an id, an owner and a list of prerequisites
(``blocked_by``). It is deliberately dumber than a workflow engine: three states, two
transitions (claim, complete) and one rule - a task may start only when everything it
waits for is completed. That is enough to sequence a project's work and to let a later
conversation pick up where an earlier one stopped (ADR 0033).

Everything here is pure: it takes a board's records as a list and returns what to
write, or why the write is refused. Persistence is ``task_store`` (a protocol the app
layer fills in) and the database lives in ``dao/board_tasks.py``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from agent.models import ToolOutcome

STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"

STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_COMPLETED)

# Limits that a rendered board cannot live without: a subject that wraps into ten
# lines is unreadable in the panel, and a description that long is a file, not a task.
MAX_SUBJECT_CHARS = 200
MAX_DESCRIPTION_CHARS = 4000
MAX_DEPENDENCIES = 50

# Who a claim is recorded as when the run is not bound to a conversation (a library
# caller, a test): the reference's single-agent default.
DEFAULT_OWNER = "agent"

_MARKERS = {
    STATUS_PENDING: "[ ]",
    STATUS_IN_PROGRESS: "[>]",
    STATUS_COMPLETED: "[x]",
}


class TaskBoardError(ValueError):
    """A board edit that must be refused; the message is the whole answer.

    ``reason`` is the machine-readable half (``not_found``, ``conflict``, ``blocked``,
    ``owner_mismatch``, ``invalid_argument``), so the UI can tell "you looked up the
    wrong id" from "this task is not yours to finish".
    """

    def __init__(self, message: str, reason: str = "invalid_argument") -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


# -- reading a board -------------------------------------------------------


def index_by_id(tasks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(task.get("task_id")): task for task in tasks}


def incomplete_blockers(
    task: Dict[str, Any], index: Dict[str, Dict[str, Any]]
) -> List[str]:
    """Prerequisite ids that are not completed yet.

    A missing prerequisite counts as incomplete: a task whose blocker was deleted is
    not "unblocked", it is unattributable, and starting it would be a guess.
    """
    return [
        dependency
        for dependency in task.get("blocked_by") or []
        if (index.get(dependency) or {}).get("status") != STATUS_COMPLETED
    ]


def is_ready(task: Dict[str, Any], index: Dict[str, Dict[str, Any]]) -> bool:
    """Whether the task can be claimed right now."""
    return (
        task.get("status") == STATUS_PENDING
        and not task.get("owner")
        and not incomplete_blockers(task, index)
    )


def board_state(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The tasks plus the derived state a reader needs, all computed in one pass.

    Returned by the task detail endpoint, so the panel does not have to re-derive
    "blocked by what" from ids it cannot resolve.
    """
    index = index_by_id(tasks)
    view: List[Dict[str, Any]] = []
    for task in tasks:
        blockers = list(task.get("blocked_by") or [])
        view.append(
            {
                **task,
                "blocked_by_subjects": [
                    str((index.get(dependency) or {}).get("subject") or dependency)
                    for dependency in blockers
                ],
                "incomplete_blockers": incomplete_blockers(task, index),
                "ready": is_ready(task, index),
            }
        )
    return view


def counts(tasks: List[Dict[str, Any]]) -> Dict[str, int]:
    result = {"total": len(tasks)}
    for status in STATUSES:
        result[status] = sum(1 for task in tasks if task.get("status") == status)
    return result


# -- validating an edit ----------------------------------------------------


def validate_subject(subject: Any) -> str:
    text = str(subject or "").strip()
    if not text:
        raise TaskBoardError("a task needs a non-empty 'subject'")
    if len(text) > MAX_SUBJECT_CHARS:
        raise TaskBoardError(
            f"subject is {len(text)} characters; keep it under {MAX_SUBJECT_CHARS}"
        )
    return text


def validate_description(description: Any) -> str:
    text = str(description or "").strip()
    if len(text) > MAX_DESCRIPTION_CHARS:
        raise TaskBoardError(
            f"description is {len(text)} characters; move the detail to a file and "
            f"keep the task under {MAX_DESCRIPTION_CHARS}"
        )
    return text


def _require(tasks: List[Dict[str, Any]], task_id: Any) -> Dict[str, Any]:
    wanted = str(task_id or "").strip()
    if not wanted:
        raise TaskBoardError("task_id is required")
    task = index_by_id(tasks).get(wanted)
    if task is None:
        raise TaskBoardError(f"no task {wanted} on this board", "not_found")
    return task


def _depends_on(
    index: Dict[str, Dict[str, Any]], start: str, target: str
) -> bool:
    """Whether ``start`` already waits on ``target``, directly or transitively."""
    pending = [start]
    seen = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend((index.get(current) or {}).get("blocked_by") or [])
    return False


def merged_dependencies(
    tasks: List[Dict[str, Any]], task_id: Any, add: Any
) -> List[str]:
    """The task's prerequisites plus ``add``, validated as a whole.

    Edges are only added while the target is pending and unclaimed: rewriting the
    prerequisites of work someone already started would silently change what "done"
    means for them.
    """
    task = _require(tasks, task_id)
    if task.get("status") != STATUS_PENDING or task.get("owner"):
        raise TaskBoardError(
            f"{task['task_id']} is {task.get('status')}; prerequisites can only change "
            "while it is pending and unclaimed",
            "conflict",
        )
    if not isinstance(add, list) or not add:
        raise TaskBoardError("add_blocked_by must be a non-empty list of task ids")
    if len(add) > MAX_DEPENDENCIES:
        raise TaskBoardError(f"at most {MAX_DEPENDENCIES} prerequisites per call")

    index = index_by_id(tasks)
    merged = list(task.get("blocked_by") or [])
    for raw in add:
        dependency = str(raw or "").strip()
        if not dependency:
            raise TaskBoardError("task ids cannot be empty")
        if dependency == task["task_id"]:
            raise TaskBoardError("a task cannot depend on itself", "conflict")
        if dependency not in index:
            raise TaskBoardError(f"no task {dependency} on this board", "not_found")
        if dependency in merged:
            # Re-adding an edge is a no-op rather than an error: a model that lost
            # track of the board should not have to read it before fixing it.
            continue
        if _depends_on(index, dependency, task["task_id"]):
            raise TaskBoardError(
                f"cycle: {dependency} already depends on {task['task_id']}", "conflict"
            )
        merged.append(dependency)
    return merged


def plan_claim(
    tasks: List[Dict[str, Any]], task_id: Any, owner: str
) -> Dict[str, Any]:
    """The columns to write when ``owner`` claims ``task_id``."""
    task = _require(tasks, task_id)
    if task.get("status") != STATUS_PENDING:
        raise TaskBoardError(
            f"{task['task_id']} is {task.get('status')}; only a pending task can be "
            "claimed",
            "conflict",
        )
    if task.get("owner"):
        raise TaskBoardError(
            f"{task['task_id']} is already claimed by {task.get('owner')}", "conflict"
        )
    blockers = incomplete_blockers(task, index_by_id(tasks))
    if blockers:
        raise TaskBoardError(
            f"{task['task_id']} is blocked by {', '.join(blockers)}", "blocked"
        )
    return {"status": STATUS_IN_PROGRESS, "owner": owner}


def plan_complete(
    tasks: List[Dict[str, Any]], task_id: Any, owner: str
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """The columns to write on completion, plus the tasks this completion unblocked.

    "Unblocked" is a diff of the board before and after: a task that was already
    ready was not waiting for this one, and reporting it would make every completion
    look like it released the whole board.
    """
    task = _require(tasks, task_id)
    if task.get("status") != STATUS_IN_PROGRESS:
        raise TaskBoardError(
            f"{task['task_id']} is {task.get('status')}; only an in_progress task can "
            "be completed",
            "conflict",
        )
    if (task.get("owner") or "") != (owner or ""):
        raise TaskBoardError(
            f"{task['task_id']} is owned by {task.get('owner') or 'nobody'}, not by "
            "this conversation; it cannot be completed here",
            "owner_mismatch",
        )

    before = index_by_id(tasks)
    ready_before = {
        candidate["task_id"]
        for candidate in tasks
        if candidate.get("blocked_by") and is_ready(candidate, before)
    }
    after = {**before, task["task_id"]: {**task, "status": STATUS_COMPLETED}}
    unblocked = [
        candidate
        for candidate in tasks
        if candidate["task_id"] != task["task_id"]
        and candidate.get("blocked_by")
        and candidate["task_id"] not in ready_before
        and is_ready(candidate, after)
    ]
    return {"status": STATUS_COMPLETED}, unblocked


# -- rendering for the model ----------------------------------------------


def _owner_label(task: Dict[str, Any], owner: str) -> str:
    if not task.get("owner"):
        return ""
    if task["owner"] == (owner or DEFAULT_OWNER):
        return "owner: this conversation"
    return "owner: another conversation"


def render_list(tasks: List[Dict[str, Any]], owner: str = "") -> str:
    if not tasks:
        return "Task board is empty. Use task_create to add work."
    index = index_by_id(tasks)
    summary = counts(tasks)
    lines = [f"Task board ({summary[STATUS_COMPLETED]}/{summary['total']} completed)"]
    for task in tasks:
        parts = [
            f"{_MARKERS.get(task.get('status'), '[?]')} {task['task_id']}: "
            f"{task.get('subject', '')}"
        ]
        owner_label = _owner_label(task, owner)
        if owner_label:
            parts.append(owner_label)
        if task.get("status") == STATUS_PENDING:
            blockers = incomplete_blockers(task, index)
            if blockers:
                parts.append(
                    "blocked by "
                    + ", ".join(str(dependency) for dependency in blockers)
                )
            else:
                parts.append("ready to claim")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def render_task(task: Dict[str, Any], owner: str = "") -> str:
    """One task in full, for a run that has to resume someone else's work."""
    lines = [f"Task {task['task_id']}: {task.get('subject', '')}"]
    status = str(task.get("status") or "")
    owner_label = _owner_label(task, owner)
    lines.append(f"status: {status}" + (f" ({owner_label})" if owner_label else ""))
    blocked_by = list(task.get("blocked_by") or [])
    lines.append(f"blocked by: {', '.join(blocked_by) if blocked_by else 'none'}")
    description = str(task.get("description") or "").strip()
    if description:
        lines.extend(["", description])
    return "\n".join(lines)


# -- tool results ----------------------------------------------------------


def run_board_action(action: Callable[[], ToolOutcome]) -> ToolOutcome:
    """Run one board edit, turning a refusal into an answer the model can act on.

    A refusal is not a failed step: "you cannot claim this yet, it is blocked by X" is
    information. Only an unexpected failure (a store that cannot be read) is reported
    as an error, and it says so.
    """
    try:
        return action()
    except TaskBoardError as exc:
        return ToolOutcome(
            model_text=f"Error: {exc.message}",
            details={"success": False, "reason": exc.reason, "error": exc.message},
        )
    except Exception as exc:  # noqa: BLE001 - a store failure must reach the model
        return ToolOutcome(
            model_text=f"Error: the task board could not be read or written: {exc}",
            details={"success": False, "reason": "store_error", "error": str(exc)},
        )


def success(text: str, **details: Any) -> ToolOutcome:
    return ToolOutcome(model_text=text, details={"success": True, **details})

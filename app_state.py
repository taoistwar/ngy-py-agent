"""The app's live state: the stores the routes read, the config the admin API writes,
and the registries a running task owns.

It gets its own module so the API modules and the task runtime can share this state
without importing ``main`` - which imports them. Every reader goes through *this*
module (``app_state.monitor_store``, not a direct import of the name), so a test can
swap a store in one place and every route picks the swap up.

Nothing here decides anything; it holds what the process knows while it runs.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Optional

import task_store
from agent.agent_loop import DEFAULT_MAX_STEPS
from agent.models import EventCategory, TaskStatus
from agent.tools.permission_rules import PermissionRuleStore
from agent.tools.permissions import PermissionBroker, PermissionMode
from agent.tools.user_question import UserQuestionBroker
from task_store import TASK_RETENTION_DEFAULT_DAYS

# The repository root. Defined once because two modules need it (the frontend paths and
# the default skills folder) and two answers to "where is the repo" is one too many.
ROOT_DIR = Path(__file__).resolve().parent

# The live task store. ``task_store`` builds it at import; keeping the reference here is
# what makes ``app_state.monitor_store = temporary`` reach every reader.
monitor_store = task_store.monitor_store

# Persisted "always allow" rules, shared by every task (ADR 0006 D8).
permission_rule_store = PermissionRuleStore()

# Config resolved at startup from env + database, and rewritten by the admin API.
task_retention_days: int = TASK_RETENTION_DEFAULT_DAYS
task_retention_source: str = "env"
agent_max_steps: int = DEFAULT_MAX_STEPS
agent_max_steps_source: str = "env"
permission_mode: PermissionMode = PermissionMode.ASK
permission_mode_source: str = "env"

# Cooperative stop flags, one per running task.
_task_stop_events: Dict[str, threading.Event] = {}
_task_stop_lock = threading.Lock()

# Live permission brokers, one per running task, so the API can answer the questions
# they are blocked on. The broker lives exactly as long as the task's thread
# (see ADR 0006 D1).
_task_permission_brokers: Dict[str, PermissionBroker] = {}
_task_permission_lock = threading.Lock()

# Live question brokers, one per running task, with the same lifecycle as the
# permission pair and for the same reason: the task's thread parks inside the broker,
# so only a task-scoped, thread-safe handle lets the API hand it the answer
# (ADR 0010 D1).
_task_question_brokers: Dict[str, UserQuestionBroker] = {}
_task_question_lock = threading.Lock()


# --------------------------------------------------------------------- task stop


def register_task_stop(task_id: str) -> threading.Event:
    """Register a cooperative stop flag for a running task."""
    event = threading.Event()
    with _task_stop_lock:
        _task_stop_events[task_id] = event
    return event


def signal_task_stop(task_id: str) -> bool:
    """Request a running task to stop; returns whether it was registered."""
    with _task_stop_lock:
        event = _task_stop_events.get(task_id)
    if event is None:
        return False
    event.set()
    return True


def clear_task_stop(task_id: str) -> None:
    with _task_stop_lock:
        _task_stop_events.pop(task_id, None)


# ------------------------------------------------------------------- broker lookup


def register_task_permission(task_id: str, broker: PermissionBroker) -> None:
    """Track a running task's broker so a decision can reach its waiting thread."""
    with _task_permission_lock:
        _task_permission_brokers[task_id] = broker


def get_task_permission_broker(task_id: str) -> Optional[PermissionBroker]:
    with _task_permission_lock:
        return _task_permission_brokers.get(task_id)


def pending_permission(task_id: str) -> Optional[Dict[str, Any]]:
    """The confirmation this task is currently blocked on, if any."""
    broker = get_task_permission_broker(task_id)
    if broker is None:
        return None
    pending = broker.pending()
    return pending.to_payload() if pending is not None else None


def clear_task_permission(task_id: str) -> None:
    with _task_permission_lock:
        _task_permission_brokers.pop(task_id, None)


def register_task_questions(task_id: str, broker: UserQuestionBroker) -> None:
    """Track a running task's question broker so an answer can reach its waiting thread."""
    with _task_question_lock:
        _task_question_brokers[task_id] = broker


def get_task_question_broker(task_id: str) -> Optional[UserQuestionBroker]:
    with _task_question_lock:
        return _task_question_brokers.get(task_id)


def pending_question(task_id: str) -> Optional[Dict[str, Any]]:
    """The question batch this task is currently blocked on, if any."""
    broker = get_task_question_broker(task_id)
    if broker is None:
        return None
    pending = broker.pending()
    return pending.to_payload() if pending is not None else None


def clear_task_questions(task_id: str) -> None:
    with _task_question_lock:
        _task_question_brokers.pop(task_id, None)


# ------------------------------------------------------------------------ status


def status_for_event(category: EventCategory) -> Optional[TaskStatus]:
    """The status an event puts its task in, or ``None`` to leave it alone.

    A task parked on a confirmation **or** on an answer is still in flight, but it must
    not look like it is thinking: the UI shows "waiting for you", and the stream stays
    open because the client is the one who has to answer (ADR 0006 D10). Both channels
    park the task thread the same way, so both flip the status back when they resume.
    """
    if category in (EventCategory.PERMISSION_REQUEST, EventCategory.USER_QUESTION):
        return TaskStatus.WAITING
    if category in (EventCategory.PERMISSION_DECISION, EventCategory.USER_ANSWER):
        return TaskStatus.RUNNING
    return None

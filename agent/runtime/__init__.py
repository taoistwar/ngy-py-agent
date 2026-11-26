"""What a task is: its resolution helpers, its names, its retention and its run.

This package turns a request into concrete things - which endpoint, which workspace
root, which step limit, which confirmation mode - and then runs the ReAct loop under
brokers the API can reach. ``routes/task_api.py`` calls :func:`run_task` on a thread and
answers the request immediately.

Since the split, this package is the one place in ``agent/`` allowed to read the live
state: ``agent.tools`` and ``agent.agent_loop`` still must not import ``commons``
(ADR 0019), while ``agent.runtime``, ``agent.history`` and ``agent.usage`` do (ADR 0025).
"""

from agent.runtime.config import (
    agent_runtime_config,
    build_provider_config,
    checkpoint_store_for_task,
    global_max_steps,
    resolve_agents_md_settings,
    resolve_max_steps,
    resolve_permission_mode,
    resolve_session_base_dir,
    resolve_skills_root,
)
from agent.runtime.events import build_event, emit_debug, extract_task_result
from agent.runtime.naming import (
    default_session_name,
    is_first_task_in_session,
    name_task_and_session,
    update_session_title,
    update_task_name,
)
from agent.runtime.purge import purge_expired_tasks, purge_expired_tasks_with_log
from agent.runtime.runner import run_task
from agent.runtime.todos import MonitorTodoStore

__all__ = [
    "MonitorTodoStore",
    "agent_runtime_config",
    "build_event",
    "build_provider_config",
    "checkpoint_store_for_task",
    "default_session_name",
    "emit_debug",
    "extract_task_result",
    "global_max_steps",
    "is_first_task_in_session",
    "name_task_and_session",
    "purge_expired_tasks",
    "purge_expired_tasks_with_log",
    "resolve_agents_md_settings",
    "resolve_max_steps",
    "resolve_permission_mode",
    "resolve_session_base_dir",
    "resolve_skills_root",
    "run_task",
    "update_session_title",
    "update_task_name",
]

"""What a task is: its resolution helpers, its names, its retention and its run.

This package turns a request into concrete things - which endpoint, which workspace
root, which step limit, which confirmation mode - and then runs the ReAct loop under
brokers the API can reach. ``routes/task_api.py`` calls :func:`run_task` on a thread and
answers the request immediately.

Since the split, this package is the one place in ``agent/`` allowed to read the live
state: ``agent.tools`` and ``agent.agent_loop`` still must not import ``commons``
(ADR 0019), while ``agent.runtime``, ``agent.history`` and ``agent.usage`` do (ADR 0025).
"""

from agent.runtime.board import (
    MonitorBoardStore,
    board_for_run,
    board_view,
    resolve_board_id,
)
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
from agent.runtime.launcher import LaunchedTask, TaskLaunchError, launch_task
from agent.runtime.memories import MonitorMemoryStore, memory_book_for_run
from agent.runtime.memory_extract import extract_after_task, extract_memories
from agent.runtime.naming import (
    default_session_name,
    is_first_task_in_session,
    name_task_and_session,
    update_session_title,
    update_task_name,
)
from agent.runtime.purge import (
    PURGE_INTERVAL_SECONDS,
    purge_expired_tasks,
    purge_expired_tasks_with_log,
    start_retention_sweeper,
    stop_retention_sweeper,
)
from agent.runtime.reasoning_translate import (
    TranslationNotConfigured,
    is_supported_locale,
    start_reasoning_translation,
    translate_missing_reasoning,
    translation_status,
)
from agent.runtime.runner import run_task
from agent.runtime.scheduling import (
    cron_matches,
    fire_schedule,
    next_fire_after,
    start_scheduler,
    stop_scheduler,
    tick,
    validate_cron,
)
from agent.runtime.todos import MonitorTodoStore

__all__ = [
    "LaunchedTask",
    "MonitorBoardStore",
    "MonitorMemoryStore",
    "MonitorTodoStore",
    "PURGE_INTERVAL_SECONDS",
    "TaskLaunchError",
    "TranslationNotConfigured",
    "agent_runtime_config",
    "board_for_run",
    "board_view",
    "build_event",
    "build_provider_config",
    "checkpoint_store_for_task",
    "cron_matches",
    "default_session_name",
    "emit_debug",
    "extract_after_task",
    "extract_memories",
    "extract_task_result",
    "fire_schedule",
    "global_max_steps",
    "is_first_task_in_session",
    "is_supported_locale",
    "launch_task",
    "start_reasoning_translation",
    "memory_book_for_run",
    "name_task_and_session",
    "next_fire_after",
    "purge_expired_tasks",
    "purge_expired_tasks_with_log",
    "resolve_agents_md_settings",
    "resolve_board_id",
    "resolve_max_steps",
    "resolve_permission_mode",
    "resolve_session_base_dir",
    "resolve_skills_root",
    "run_task",
    "start_retention_sweeper",
    "start_scheduler",
    "stop_retention_sweeper",
    "stop_scheduler",
    "tick",
    "translate_missing_reasoning",
    "translation_status",
    "update_session_title",
    "update_task_name",
    "validate_cron",
]

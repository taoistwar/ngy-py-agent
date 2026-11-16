"""The names the task list shows: a short task name and a session title.

Both come from the model when it is reachable and from the query when it is not; both
run off the task's own thread so a slow model cannot delay the answer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from agent.provider import ProviderConfig, build_provider
from commons import state

_SESSION_TITLE_MAX_LENGTH = 60
_SESSION_TITLE_PROMPT = (
    "You generate a very short session title for a task list. "
    "Summarize the user's task into a concise title using the same language as the request. "
    "Reply with the title only, without quotes, and keep it under 20 characters when possible."
)

# The task list shows this name on one line, so it stays short.
_TASK_NAME_MAX_LENGTH = 20
_TASK_NAME_PROMPT = (
    "You name tasks for a task list. Summarize the user's task as a very short name "
    "in the same language as the request. Reply with the name only, without quotes, "
    "and keep it within 20 characters."
)


def default_session_name() -> str:
    """Time-based session name used when the user does not provide one."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _collapsed(query: str) -> str:
    """One-line form of the query: names are labels, not quotes."""
    return " ".join(str(query or "").split())


def _fallback_session_title(query: str) -> str:
    """Fallback title derived from the raw query when the LLM is unavailable."""
    collapsed = _collapsed(query)
    if not collapsed:
        return default_session_name()
    return collapsed[:_SESSION_TITLE_MAX_LENGTH]


def _fallback_task_name(query: str) -> str:
    """Task name used when the LLM is unavailable."""
    return _collapsed(query)[:_TASK_NAME_MAX_LENGTH]


def _summarize(
    prompt: str,
    max_length: int,
    provider_name: str,
    provider_config: Optional[ProviderConfig],
    query: str,
    fallback: Callable[[str], str],
) -> str:
    """Ask the LLM for a short label, falling back to a query-derived one."""
    try:
        provider = build_provider(provider_name, provider_config)
        response = provider.chat_completion(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": str(query or "")},
            ]
        )
        message = response.choices[0].message
        content = (
            message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        )
    except Exception:  # noqa: BLE001 - a label is a convenience; fall back to the query
        return fallback(query)

    label = str(content or "").strip().strip('"').strip("'").strip()
    if not label:
        return fallback(query)
    return label[:max_length]


def _summarize_session_title(
    provider_name: str,
    provider_config: Optional[ProviderConfig],
    query: str,
) -> str:
    """Ask the LLM for a short session title, falling back to the raw query."""
    return _summarize(
        _SESSION_TITLE_PROMPT,
        _SESSION_TITLE_MAX_LENGTH,
        provider_name,
        provider_config,
        query,
        _fallback_session_title,
    )


def update_session_title(
    session_id: str | None,
    provider_name: str,
    provider_config: Optional[ProviderConfig],
    query: str,
) -> None:
    """Rename a session with an LLM-generated title derived from the task query."""
    if not session_id:
        return
    title = _summarize_session_title(provider_name, provider_config, query)
    if title:
        state.monitor_store.rename_session(session_id, title)


def update_task_name(
    task_id: str,
    provider_name: str,
    provider_config: Optional[ProviderConfig],
    query: str,
) -> None:
    """Name a task the way the list shows it.

    A query that already fits in the name length is its own name - asking the model
    to shorten three words can only lose them - so the model is only used when the
    query is longer than the name may be.
    """
    collapsed = _collapsed(query)
    if not collapsed:
        return
    if len(collapsed) <= _TASK_NAME_MAX_LENGTH:
        state.monitor_store.set_task_name(task_id, collapsed)
        return
    name = _summarize(
        _TASK_NAME_PROMPT,
        _TASK_NAME_MAX_LENGTH,
        provider_name,
        provider_config,
        query,
        _fallback_task_name,
    )
    state.monitor_store.set_task_name(task_id, name)


def is_first_task_in_session(session_id: str | None) -> bool:
    """Whether the task being named is the one that opened its session.

    The current task is already stored when this runs, so a session holding only
    that task is a session started by it.
    """
    if not session_id:
        return True
    session = state.monitor_store.get_session(session_id)
    if session is None:
        return True
    return int(session.get("task_count") or 0) <= 1


def name_task_and_session(
    task_id: str,
    session_id: str | None,
    provider_name: str,
    provider_config: Optional[ProviderConfig],
    query: str,
) -> None:
    """Both naming steps in one background thread.

    Each one calls the model, so running them one after the other keeps a local
    model from being asked twice at the same time while the task itself is running.

    Only the session's first task renames it: a follow-up continues the thread the
    earlier task opened, so it names itself and leaves the session label alone.
    """
    update_task_name(task_id, provider_name, provider_config, query)
    if is_first_task_in_session(session_id):
        update_session_title(session_id, provider_name, provider_config, query)

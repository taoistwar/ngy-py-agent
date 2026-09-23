"""Live commands that are still open, keyed by a short session id.

``exec_command`` may leave a command running in the background. That command is a
terminal that is still connected: its stdin is a pipe we can type into, and its
output keeps appending to a log file. :mod:`agent.tools.write_stdin_tool` needs both
halves, so this store is the single place that remembers, per session id:

* the :class:`~agent.tools.process_group.RunningCommand`, which owns the process
  tree handle used to stop it and the stdin pipe used to feed it;
* the log path plus how many bytes of it have already been returned to the model,
  so a poll returns only what is new.

Ownership is part of the contract, not a nicety. A session belongs to the task and
workspace that started it, and ``session_id`` is treated as a capability: a lookup
that does not match both is answered exactly like "no such session", so one task
cannot type into another task's terminal (see ``docs/decisions/0008-write-stdin-tool.md``).

Three naming notes. The model-facing parameter is ``session_id`` (matching the
``write_stdin`` contract); internally the key is called a ``process_id`` because
``session_id`` already means the run/task scope used for output directories. "Live"
is best effort: a stored process may have exited between two calls, which is exactly
what ``poll`` reports. And a session is *task scoped*: the loop stops a task's
sessions when the task ends, with a TTL and an ``atexit`` sweep as backstops for
callers that never reach a task boundary.
"""

from __future__ import annotations

import atexit
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.tools import process_group

# 4 bytes -> 8 hex characters, short enough to read in a prompt but still unique.
SESSION_ID_BYTES = 4

# A task may hold at most this many sessions at once. Past it, starting another one
# is refused: silently killing an older session would destroy an interaction the
# model may still be in the middle of.
MAX_LIVE_SESSIONS_PER_TASK = 8

# Backstop for callers that never reach a task boundary (a library that simply stops
# calling, a crash path). Sessions older than this are stopped and forgotten.
SESSION_TTL_SECONDS = 30 * 60

_LOCK = threading.Lock()
_SESSIONS: Dict[str, "Session"] = {}


class SessionLimitReached(Exception):
    """Raised when a task already holds the maximum number of live sessions."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"this task already holds {limit} live sessions")
        self.limit = limit


@dataclass
class Session:
    """One background command, still reachable by its id."""

    process_id: str
    command: process_group.RunningCommand
    log_path: Path
    task_id: str = ""
    workspace: str = ""
    read_offset: int = 0
    created_at: float = field(default_factory=time.monotonic)
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def pid(self) -> int:
        return self.command.pid

    def running(self) -> bool:
        return self.command.poll() is None


def new_process_id() -> str:
    return uuid.uuid4().hex[: SESSION_ID_BYTES * 2]


def register(
    command: process_group.RunningCommand,
    log_path: Path,
    task_id: str = "",
    workspace: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> Session:
    """Remember a live command and return its session record.

    Raises :class:`SessionLimitReached` when the owning task is already at its
    limit; finished sessions are swept first so a forgotten poll cannot consume a
    slot. A refused start is the caller's to report, not something to paper over by
    killing someone else's session.
    """
    sweep()
    session = Session(
        process_id=new_process_id(),
        command=command,
        log_path=Path(log_path),
        task_id=str(task_id or ""),
        workspace=str(workspace or ""),
        meta=dict(meta or {}),
    )
    with _LOCK:
        owned = [item for item in _SESSIONS.values() if item.task_id == session.task_id]
        if len(owned) >= MAX_LIVE_SESSIONS_PER_TASK:
            raise SessionLimitReached(MAX_LIVE_SESSIONS_PER_TASK)
        _SESSIONS[session.process_id] = session
    return session


def get(
    process_id: str,
    task_id: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Optional[Session]:
    """The session for ``process_id``, or ``None``.

    ``task_id``/``workspace`` are a capability check, not a filter: when they are
    given and do not match, the answer is the same as "no such session", so a probe
    cannot even learn that the id exists. ``None`` means "not checked" and is for
    callers that own the whole process (tests, internal helpers).
    """
    with _LOCK:
        session = _SESSIONS.get(str(process_id or ""))
    if session is None:
        return None
    if task_id is not None and session.task_id != str(task_id):
        return None
    if workspace is not None and session.workspace != str(workspace):
        return None
    return session


def list_sessions() -> List[Session]:
    with _LOCK:
        return list(_SESSIONS.values())


def find_by_pid(pid: int) -> Optional[Session]:
    try:
        wanted = int(pid)
    except (TypeError, ValueError):
        return None
    with _LOCK:
        for session in _SESSIONS.values():
            if session.pid == wanted:
                return session
    return None


def read_new(session: Session) -> bytes:
    """Bytes appended to the log since the last read, advancing the cursor.

    Returns ``b""`` when the file is not there yet or cannot be read: a log that is
    momentarily missing is "no output", never a hard error.
    """
    with _LOCK:
        offset = session.read_offset
        try:
            with session.log_path.open("rb") as handle:
                handle.seek(offset)
                chunk = handle.read()
        except OSError:
            return b""
        session.read_offset += len(chunk)
    return chunk


def forget(process_id: str) -> Optional[Session]:
    with _LOCK:
        return _SESSIONS.pop(str(process_id or ""), None)


def retire(session: Session) -> None:
    """Drop a finished session and release the handles it held.

    Does **not** stop anything: the command is already gone. Closing stdin and the
    process-tree handle is what keeps a long task from leaking one pipe and one job
    handle per background command.
    """
    forget(session.process_id)
    _release(session)


def stop_session(session: Session) -> None:
    """Stop a session (Ctrl-C style, escalating) and forget it."""
    forget(session.process_id)
    process_group.interrupt(session.command)
    _release(session)


def stop_task(task_id: str) -> int:
    """Stop and forget every session a task still owns; returns how many.

    An empty ``task_id`` is a no-op: unbound sessions have no task to be reaped
    with, and "stop everything" is not what a task boundary means.
    """
    wanted = str(task_id or "")
    if not wanted:
        return 0
    with _LOCK:
        owned = [session for session in _SESSIONS.values() if session.task_id == wanted]
    for session in owned:
        stop_session(session)
    return len(owned)


def sweep() -> int:
    """Forget finished sessions and stop ones past their TTL.

    Runs before every registration so a model that forgets to poll cannot slowly
    consume the store; it is also the cheap place to enforce the TTL.
    """
    now = time.monotonic()
    with _LOCK:
        stale = [
            session
            for session in _SESSIONS.values()
            if not session.running() or now - session.created_at > SESSION_TTL_SECONDS
        ]
        for session in stale:
            _SESSIONS.pop(session.process_id, None)
    for session in stale:
        if session.running():
            process_group.interrupt(session.command)
        _release(session)
    return len(stale)


def _release(session: Session) -> None:
    _close_stdin(session)
    try:
        session.command.release()
    except Exception:  # noqa: BLE001  # pragma: no cover - defensive
        pass


def _close_stdin(session: Session) -> None:
    stream = session.command.process.stdin
    if stream is None:
        return
    try:
        stream.close()
    except OSError:  # pragma: no cover - platform specific
        pass


def _stop_all_at_exit() -> None:
    """Last resort: nothing this process started may outlive it.

    Hard kill, no grace period: a dying interpreter must not spend three seconds
    per session waiting for politeness. The task boundary already stops sessions
    properly; this only covers paths that bypass it.
    """
    for session in list_sessions():
        try:
            session.command.kill()
        except Exception:  # noqa: BLE001  # pragma: no cover - teardown
            pass


atexit.register(_stop_all_at_exit)

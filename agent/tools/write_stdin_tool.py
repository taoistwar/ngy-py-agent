"""Type into a command that ``exec_command`` left running, and read the reply.

The principle is a telephone that was never hung up (see
``docs/decisions/0008-write-stdin-tool.md``): ``exec_command`` with
``run_in_background`` hands back a ``session_id`` for a command that is still
connected, and this tool finds that command, optionally types into its stdin, then
listens for a while and returns whatever it printed.

An empty ``chars`` is a poll: nothing is typed, only new output is collected. A
``chars`` equal to Ctrl-C (``\\u0003``) interrupts the command instead of being
written. Any other ``chars`` goes to the process's stdin. A result that carries a
``session_id`` means the command is still running; one that carries an ``exit_code``
means it finished and the session is gone.

Two boundaries worth stating. A session belongs to the task and workspace that
started it, so a foreign id is answered exactly like an unknown one. And output
above the token budget is persisted and reported as a path rather than silently
truncated, matching what ``exec_command`` promises for large output.

There is no PTY here: a session runs with a plain pipe, so programs that insist on a
terminal will not behave interactively. That tradeoff is recorded in the ADR.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent.models import EventCategory, ToolOutcome
from agent.tools import process_group, process_store
from agent.tools.output_store import (
    describe_size,
    ensure_dir,
    new_stem,
    persist_text,
    preview,
)
from agent.tools.text_encoding import DecodeError, decode_file_bytes
from agent.tools.token_budget import check_text, resolve_max_tokens

WRITE_STDIN_TOOL_NAME = "write_stdin"

# Defaults and ranges follow the reference design (ADR 0008): a poll waits longer
# than a write, because a write should feel responsive.
DEFAULT_YIELD_MS = 250
POLL_MIN_YIELD_MS = 5_000
POLL_MAX_YIELD_MS = 300_000
WRITE_MAX_YIELD_MS = 30_000
DEFAULT_MAX_OUTPUT_TOKENS = 10_000

# A write of exactly this byte means "interrupt", not "input".
CTRL_C = "\u0003"

# How often the wait loop checks for new output or an exited process.
_POLL_INTERVAL_SECONDS = 0.05

WRITE_STDIN_DESCRIPTION = (
    "Type into a command that exec_command left running, and read what it prints back. "
    "Pass the 'session_id' that exec_command returned for a command still running. Set 'chars' to "
    "write text to the command's stdin (include '\\n' to send a line); leave 'chars' empty to only "
    "poll for new output. A 'chars' equal to Ctrl-C ('\\u0003') interrupts the command instead of "
    "writing it. 'yield_time_ms' bounds how long to wait for output and 'max_output_tokens' bounds "
    "how much is returned. The result says whether the command is still running (it prints a "
    "session_id) or has finished (it prints an exit_code); a finished session cannot be reused."
)

WRITE_STDIN_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": (
                "The session id exec_command returned for a command still running. "
                "A finished session is rejected."
            ),
        },
        "chars": {
            "type": "string",
            "description": (
                "Text to write to the command's stdin. Empty (the default) only polls for new "
                "output. A single Ctrl-C character ('\\u0003') interrupts the command."
            ),
        },
        "yield_time_ms": {
            "type": "integer",
            "minimum": 0,
            "maximum": POLL_MAX_YIELD_MS,
            "description": (
                "How long to wait for output, in MILLISECONDS. A poll (empty 'chars') is raised to "
                "at least 5000 and capped at 300000; a write waits at most 30000. Defaults to 250."
            ),
        },
        "max_output_tokens": {
            "type": "integer",
            "minimum": 1,
            "description": (
                "Token budget for the returned output. Defaults to 10000; a larger request may be "
                "capped by policy. Output above the budget is persisted and its path is returned."
            ),
        },
    },
    "required": ["session_id"],
}


class WriteStdinError(Exception):
    """Raised when the request is malformed or the session cannot be reached."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}


def _as_chars(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise WriteStdinError(
            "'chars' must be a string.", reason="invalid_argument", argument="chars"
        )
    return value


def _effective_yield_ms(value: Any, is_write: bool) -> int:
    """Clamp the wait so a poll is patient and a write stays responsive."""
    if value is None:
        raw = DEFAULT_YIELD_MS
    else:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WriteStdinError(
                "'yield_time_ms' must be a number of milliseconds.",
                reason="invalid_argument",
                argument="yield_time_ms",
            )
        raw = int(value)
    if is_write:
        return max(0, min(raw, WRITE_MAX_YIELD_MS))
    return max(POLL_MIN_YIELD_MS, min(raw, POLL_MAX_YIELD_MS))


def _output_budget(requested: Any, configured: int) -> int:
    if requested is None:
        want = DEFAULT_MAX_OUTPUT_TOKENS
    else:
        if isinstance(requested, bool) or not isinstance(requested, (int, float)):
            raise WriteStdinError(
                "'max_output_tokens' must be a positive number.",
                reason="invalid_argument",
                argument="max_output_tokens",
            )
        want = int(requested)
    if want < 1:
        raise WriteStdinError(
            "'max_output_tokens' must be at least 1.",
            reason="invalid_argument",
            argument="max_output_tokens",
        )
    # A larger request can be pulled back by the run's configured budget.
    return max(1, min(want, resolve_max_tokens(configured)))


def _decode_output(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        return decode_file_bytes(raw, "utf-8").text
    except DecodeError:
        # A live command is not a source file: a mis-decode must not stop the
        # reply, so fall back to a replacement marker instead of raising.
        return raw.decode("utf-8", errors="replace")


def _write_to_session(session: process_store.Session, chars: str) -> None:
    stream = session.command.process.stdin
    if stream is None:
        raise WriteStdinError(
            "This session has no writable stdin.",
            reason="no_stdin",
            session_id=session.process_id,
        )
    try:
        stream.write(chars.encode("utf-8"))
        stream.flush()
    except (OSError, ValueError) as exc:
        raise WriteStdinError(
            f"Could not write to the session: {exc}",
            reason="write_failed",
            session_id=session.process_id,
        ) from exc


def _collect_output(session: process_store.Session, wait_ms: int) -> str:
    """Wait up to ``wait_ms`` for new output, returning as soon as there is some."""
    deadline = time.monotonic() + (wait_ms / 1000)
    chunks: list[bytes] = []
    while True:
        data = process_store.read_new(session)
        if data:
            chunks.append(data)
            break
        if session.command.poll() is not None:
            # Drain whatever the command printed on its way out.
            tail = process_store.read_new(session)
            if tail:
                chunks.append(tail)
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(_POLL_INTERVAL_SECONDS)
    return _decode_output(b"".join(chunks))


def _fit_output(
    text: str,
    budget: int,
    directory: Optional[Path],
) -> Tuple[str, int, bool, Optional[str]]:
    """Return ``(rendered, original_tokens, truncated, persisted_path)``.

    Over budget the whole chunk is written to disk and its path is returned: a
    truncated read with no way back is a dead end, and ``exec_command`` already
    promises the path for the same reason (ADR 0005 D4/D8).
    """
    report = check_text(text, budget)
    if report.ok:
        return text, report.tokens, False, None

    persisted: Optional[str] = None
    path = None
    if directory is not None:
        path = persist_text(ensure_dir(directory), f"{new_stem()}-stdin.txt", text)
        persisted = path.as_posix()

    size = describe_size(text)
    where = (
        f"the full text is at {persisted}. Read it in slices with read_file (offset/limit)."
        if persisted
        else "it could not be persisted, so only this preview survives."
    )
    rendered = (
        f"The output was too large to return and was truncated (original token count: "
        f"{report.tokens}, {size['bytes']} bytes); {where}\n"
        f"--- preview ---\n{preview(text)}"
    )
    return rendered, report.tokens, True, persisted


def _render(
    session: process_store.Session,
    rendered: str,
    tokens: int,
    truncated: bool,
    persisted: Optional[str],
    running: bool,
    exit_code: Any,
    wall_seconds: float,
    chars_sent: str,
    wait_ms: int,
) -> Tuple[str, Dict[str, Any]]:
    status = (
        f"Process running with session ID {session.process_id}"
        if running
        else f"Process exited with code {exit_code}"
    )
    model_text = "\n".join(
        [
            f"Chunk ID: {uuid.uuid4().hex[:6]}",
            f"Wall time: {wall_seconds:.4f} seconds",
            status,
            f"Original token count: {tokens}",
            "Output:",
            rendered,
        ]
    )
    details: Dict[str, Any] = {
        "success": True,
        # A finished session can no longer be typed into, so do not advertise it.
        "session_id": session.process_id if running else None,
        "running": running,
        "exit_code": exit_code,
        "chars_sent": chars_sent,
        "interrupted": chars_sent == CTRL_C,
        "wall_time_seconds": round(wall_seconds, 4),
        "yield_time_ms": wait_ms,
        "original_token_count": tokens,
        "output": rendered,
        "output_truncated": truncated,
        "persistedOutputPath": persisted,
        "output_bytes": len(rendered.encode("utf-8", errors="replace")),
    }
    return model_text, details


def _write_stdin_impl(
    session_id: Any,
    chars: Any,
    yield_time_ms: Any,
    max_output_tokens: Any,
    configured_max_tokens: int,
    task_id: str,
    workspace: str,
    output_directory: Optional[Path],
) -> Tuple[str, Dict[str, Any]]:
    if not isinstance(session_id, str) or not session_id.strip():
        raise WriteStdinError(
            "'session_id' must be the non-empty id exec_command returned.",
            reason="invalid_argument",
            argument="session_id",
        )
    session_id = session_id.strip()
    typed = _as_chars(chars)

    # ``session_id`` is a capability: a session owned by another task or workspace
    # is answered exactly like an unknown one, so a probe learns nothing.
    session = process_store.get(session_id, task_id=task_id, workspace=workspace)
    if session is None:
        raise WriteStdinError(
            f"Unknown session {session_id!r}: it may have already exited. "
            "Start the command again with exec_command to get a new session_id.",
            reason="unknown_session",
            session_id=session_id,
        )

    interrupt = typed == CTRL_C
    if interrupt:
        # Ctrl-C is not input: it asks the command to stop and forces it if it
        # refuses to go.
        process_group.interrupt(session.command)
    elif typed:
        _write_to_session(session, typed)

    wait_ms = _effective_yield_ms(yield_time_ms, is_write=bool(typed) and not interrupt)
    started = time.monotonic()
    output = _collect_output(session, wait_ms)
    wall_seconds = time.monotonic() - started

    exit_code = session.command.poll()
    running = exit_code is None
    budget = _output_budget(max_output_tokens, configured_max_tokens)
    rendered, tokens, truncated, persisted = _fit_output(output, budget, output_directory)

    if not running:
        # The command is gone; release its handles and forget the session.
        process_store.retire(session)

    return _render(
        session,
        rendered,
        tokens,
        truncated,
        persisted,
        running,
        exit_code,
        wall_seconds,
        typed,
        wait_ms,
    )


def make_write_stdin_tool(
    max_tokens: int = 0,
    task_id: str = "",
    workspace: str = "",
    output_directory: Optional[Path] = None,
):
    """Bind ``write_stdin`` to the process store, the run's budget and its workspace.

    ``task_id``/``workspace`` are the ownership half of the contract: they decide
    which sessions this tool is allowed to see at all.
    """

    def write_stdin(
        session_id: Any = None,
        chars: Any = None,
        yield_time_ms: Any = None,
        max_output_tokens: Any = None,
    ) -> ToolOutcome:
        try:
            model_text, details = _write_stdin_impl(
                session_id,
                chars,
                yield_time_ms,
                max_output_tokens,
                max_tokens,
                task_id,
                workspace,
                output_directory,
            )
        except WriteStdinError as exc:
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                event_category=EventCategory.EXEC,
                event_title="write_stdin rejected",
                details={"success": False, **exc.to_dict()},
            )

        return ToolOutcome(
            model_text=model_text,
            event_category=EventCategory.EXEC,
            event_title=f"Session {details.get('session_id') or 'exited'}",
            details=details,
        )

    return write_stdin

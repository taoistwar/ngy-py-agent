"""Background commands this run started, and the notification when one ends.

``exec_command(run_in_background=True)`` already returns a placeholder (pid, session
id, log path) and keeps the command running as a session (ADR 0008). What the tool
cannot do on its own is *tell* the model that the command ended: that call was
answered, and one call gets one result.

So the run keeps this ledger. The tool records every background session when it
starts; at the start of each turn the loop asks the ledger what has ended since the
last check, and the answer travels back as a ``<task_notification>`` message
(ADR 0034).

No thread waits on the process. A waiter per command would have to duplicate the
ownership and cleanup rules ``process_store`` already enforces - a session can be
retired by ``write_stdin`` or swept by the next registration at any moment - and the
loop is going to run again anyway: "sometime before the next turn" is exactly what a
notification promises.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from agent.tools import process_store

# How much of the log travels with the notification. The path alone is not an answer:
# "exit code 1" plus the last line usually is, and a model that has to read the file
# for them has spent a turn learning what this message could have said.
TAIL_CHARS = 600

# Long commands (a one-liner pasted with a heredoc) would push the exit code off the
# notification's first line.
LABEL_CHARS = 120


def _label(command: str, description: str) -> str:
    text = (description or "").strip() or (command or "").strip()
    first = text.splitlines()[0].strip() if text else "(no command)"
    return first[:LABEL_CHARS] + ("..." if len(first) > LABEL_CHARS else "")


def _tail(path: str) -> str:
    """The last ``TAIL_CHARS`` of the log, or ``""`` when it cannot be read."""
    if not path:
        return ""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return ""
    if not raw:
        return ""
    text = raw[-TAIL_CHARS:].decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").strip()


@dataclass
class BackgroundCommand:
    """One command the run started and has not been told about yet."""

    session_id: str
    pid: int
    command: str
    description: str = ""
    log_path: str = ""
    tty: bool = False


@dataclass
class BackgroundResult:
    """One command that has ended, in the shape the model reads."""

    record: BackgroundCommand
    exit_code: Optional[int]
    tail: str

    def as_notification(self) -> str:
        """The message body; the loop wraps a batch of these into one user turn."""
        label = _label(self.record.command, self.record.description)
        exit_text = (
            f"exit code {self.exit_code}"
            if self.exit_code is not None
            else "exit code unknown (the session was already closed)"
        )
        lines = [
            "<task_notification>",
            f"Background command finished: {label} ({exit_text})",
            f"session {self.record.session_id} (pid {self.record.pid}); "
            f"output: {self.record.log_path or '(not recorded)'}",
        ]
        if self.tail:
            lines.extend(["", "Last output:", self.tail])
        else:
            lines.append("It printed nothing.")
        lines.append("</task_notification>")
        return "\n".join(lines)


class BackgroundTasks:
    """The run's ledger: what it started, and what has ended since the last check.

    One per run, created by the loop and handed to the tool layer through the
    registry, so a notification can only ever describe a command this run started.
    """

    def __init__(self, task_id: str = "") -> None:
        self.task_id = task_id or ""
        self._lock = threading.Lock()
        self._tracked: Dict[str, BackgroundCommand] = {}

    def track(
        self,
        session_id: str,
        pid: int,
        command: str,
        description: str = "",
        log_path: str = "",
        tty: bool = False,
    ) -> BackgroundCommand:
        """Start watching one background session (idempotent per session id)."""
        record = BackgroundCommand(
            session_id=str(session_id),
            pid=int(pid or 0),
            command=command or "",
            description=description or "",
            log_path=log_path or "",
            tty=bool(tty),
        )
        with self._lock:
            # A repeated registration (the model started the same id twice, a
            # resumed run) must not produce two notifications for one command.
            existing = self._tracked.get(record.session_id)
            if existing is not None:
                return existing
            self._tracked[record.session_id] = record
        return record

    def collect(self) -> List[BackgroundResult]:
        """Finished commands, each reported once; the ledger forgets them."""
        with self._lock:
            tracked = list(self._tracked.values())

        results: List[BackgroundResult] = []
        for record in tracked:
            session = process_store.get(
                record.session_id, task_id=self.task_id or None
            )
            if session is not None and session.running():
                # Still going: report on a later turn, not now.
                continue
            exit_code = None
            if session is not None:
                # The command is gone, so this is the moment to report it and to let
                # go of the handles - the same cleanup ``write_stdin`` does when it
                # finds the process ended (ADR 0008).
                exit_code = session.command.poll()
                process_store.retire(session)
            with self._lock:
                self._tracked.pop(record.session_id, None)
            results.append(
                BackgroundResult(
                    record=record,
                    exit_code=exit_code,
                    tail=_tail(record.log_path),
                )
            )
        return results

    def pending(self) -> int:
        """How many commands are being watched (running, or not yet reported)."""
        with self._lock:
            return len(self._tracked)

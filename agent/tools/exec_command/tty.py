"""Running a terminal command to completion: the foreground half of ``tty``.

The pipe path waits with ``communicate`` because there are pipes to drain. A terminal
has none: its output is read on :class:`~agent.tools.pty_session.PtyReader`'s thread,
and the read never ends by itself. So the foreground wait is a poll on the child,
followed by a bounded drain - the same two steps a background session gets from
:meth:`~agent.tools.process_group.RunningCommand.release`, which is why this module
just calls it and then reads the sink.

Two shapes of the same output, on purpose (ADR 0009):

- the **model** gets LF line endings, because a terminal ends every line with CRLF and
  that is noise in a prompt;
- the **persisted** copy keeps the bytes the command produced, because a file that
  claims to be the command's output should be exactly that.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from agent.tools import process_group
from agent.tools.exec_command.description import STOP_POLL_SECONDS, STOPPED_BY_TASK, STOPPED_BY_TIMEOUT


@dataclass
class TtyRun:
    """How a foreground terminal command ended."""

    exit_code: Optional[int]
    output: bytes
    interrupted: bool
    # ``""`` when the command ended on its own, else why it was cut short (ADR 0019).
    interrupted_by: str = ""


def normalize_line_endings(text: str) -> str:
    """CRLF -> LF, for text a terminal produced and the model is about to read."""
    return text.replace("\r\n", "\n")


def run_foreground_tty(
    command: process_group.RunningCommand,
    timeout_ms: int,
    grace_seconds: float,
    should_stop: Optional[Callable[[], bool]] = None,
) -> TtyRun:
    """Wait for a terminal command, stop it on timeout or stop request, collect output.

    The wait is a poll in short slices rather than one long ``wait``: a terminal has
    no pipes to drain, so slicing costs nothing and is what lets a stop request land
    mid-command instead of after it (ADR 0019).

    After this returns the command has been released: its terminal is closed and its
    reader thread has finished, so ``command.sink`` holds everything it ever printed.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    interrupted_by = ""
    while True:
        if should_stop is not None and should_stop():
            interrupted_by = STOPPED_BY_TASK
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            interrupted_by = STOPPED_BY_TIMEOUT
            break
        if command.wait(min(STOP_POLL_SECONDS, remaining)):
            break

    if interrupted_by:
        command.stop()
        if not command.wait(grace_seconds):
            command.kill()
            command.wait(grace_seconds)

    exit_code = command.returncode
    # Drains the tail before closing the terminal; reading the sink afterwards is
    # therefore the whole output, not a prefix of it.
    command.release()
    return TtyRun(
        exit_code=exit_code,
        output=command.sink.bytes(),
        interrupted=bool(interrupted_by),
        interrupted_by=interrupted_by,
    )

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

from dataclasses import dataclass
from typing import Optional

from agent.tools import process_group


@dataclass
class TtyRun:
    """How a foreground terminal command ended."""

    exit_code: Optional[int]
    output: bytes
    interrupted: bool


def normalize_line_endings(text: str) -> str:
    """CRLF -> LF, for text a terminal produced and the model is about to read."""
    return text.replace("\r\n", "\n")


def run_foreground_tty(
    command: process_group.RunningCommand,
    timeout_ms: int,
    grace_seconds: float,
) -> TtyRun:
    """Wait for a terminal command, stop it on timeout, and collect its output.

    After this returns the command has been released: its terminal is closed and its
    reader thread has finished, so ``command.sink`` holds everything it ever printed.
    """
    interrupted = not command.wait(timeout_ms / 1000)
    if interrupted:
        command.stop()
        if not command.wait(grace_seconds):
            command.kill()
            command.wait(grace_seconds)

    exit_code = command.returncode
    # Drains the tail before closing the terminal; reading the sink afterwards is
    # therefore the whole output, not a prefix of it.
    command.release()
    return TtyRun(exit_code=exit_code, output=command.sink.bytes(), interrupted=interrupted)

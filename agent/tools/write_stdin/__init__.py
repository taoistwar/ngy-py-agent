"""The ``write_stdin`` tool: type into a command that ``exec_command`` left running.

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

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The waiting rules are in :mod:`~agent.tools.write_stdin.rules`, the session I/O in
:mod:`~agent.tools.write_stdin.session_io`, the rendering in
:mod:`~agent.tools.write_stdin.render`; this module re-exports the public surface.
"""

from agent.tools.write_stdin.description import (
    WRITE_STDIN_DESCRIPTION,
    WRITE_STDIN_PARAMETERS,
    WRITE_STDIN_TOOL_NAME,
)
from agent.tools.write_stdin.errors import WriteStdinError
from agent.tools.write_stdin.tool import make_write_stdin_tool

__all__ = [
    "WRITE_STDIN_DESCRIPTION",
    "WRITE_STDIN_PARAMETERS",
    "WRITE_STDIN_TOOL_NAME",
    "WriteStdinError",
    "make_write_stdin_tool",
]

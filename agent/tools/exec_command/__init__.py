"""The ``exec_command`` tool: run a command in the platform shell.

Containment is layered, and the layers are *not* equivalent (see
``docs/decisions/0005-exec-tool.md``):

1. **Process tree + resource caps.** On Windows a Job Object caps process count and
   job memory and terminates the whole tree in one call; on POSIX the command runs
   in its own session and is stopped with ``killpg``. Always on.
2. **Integrity level.** Dropping the command to a low integrity token so it cannot
   write outside what the low integrity SID has been granted. **Not enabled**: the
   token drop itself is verified to work, but on its own it also blocks ordinary
   temp usage, so turning it on needs ACL grants plus a revert path. Recorded in the
   ADR as the next subproject.

What this is **not**: a security boundary. The command can read and write anywhere
the process user can, and ``code_interpreter`` can already do the same, so nothing
here may be described to a user as "sandboxed".

The model gets a readable text rendering (exit code, stdout, stderr, where the full
output went); the UI gets the structured record through an ``exec`` event. A command
started with ``run_in_background`` hands back a ``session_id`` that ``write_stdin``
can type into.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The run itself is in :mod:`~agent.tools.exec_command.runtime`, the constraint
reporting in :mod:`~agent.tools.exec_command.containment`, the rendering in
:mod:`~agent.tools.exec_command.output`; this module re-exports the public surface.
"""

from agent.tools.exec_command.description import (
    EXEC_PARAMETERS,
    EXEC_TOOL_NAME,
    build_exec_description,
)
from agent.tools.exec_command.errors import ExecError
from agent.tools.exec_command.tool import (
    list_background,
    make_exec_tool,
    stop_background,
)

__all__ = [
    "EXEC_PARAMETERS",
    "EXEC_TOOL_NAME",
    "ExecError",
    "build_exec_description",
    "list_background",
    "make_exec_tool",
    "stop_background",
]

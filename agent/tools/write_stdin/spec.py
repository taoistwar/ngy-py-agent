"""The ``write_stdin`` spec: name, schema, ownership binding and its scopes.

It shares the process store with ``exec_command``, which is what turns the
``session_id`` from a background command into something the model can talk to (see
``docs/decisions/0008-write-stdin-tool.md``). ``task_id``/``base_dir`` bind it to the
one task whose sessions it may touch.
"""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_EXEC, SCOPE_ONCE, SCOPE_SESSION
from agent.tools.spec import ToolSpec
from agent.tools.write_stdin import (
    WRITE_STDIN_DESCRIPTION,
    WRITE_STDIN_PARAMETERS,
    WRITE_STDIN_TOOL_NAME,
    make_write_stdin_tool,
)

NAME = WRITE_STDIN_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the terminal-typing tool to this run's task and workspace."""
    return ToolSpec(
        name=NAME,
        handler=make_write_stdin_tool(
            max_tokens=bindings.max_tokens,
            task_id=bindings.task_id,
            workspace=bindings.base_dir or "",
            output_directory=bindings.output_directory,
        ),
        description=WRITE_STDIN_DESCRIPTION,
        parameters=WRITE_STDIN_PARAMETERS,
        # Typing into a live command is the same class of risk as running one.
        permission=PERMISSION_EXEC,
        # Its target is a random session id, so a persisted "always" rule could
        # never match again: offer once/session only (ADR 0008).
        scopes=(SCOPE_ONCE, SCOPE_SESSION),
    )

"""The ``exec_command`` spec: name, dialect-aware description, schema, binding.

The description is written for the shell this machine actually has, so the model is
told which dialect to write in (see ``docs/decisions/0005-exec-tool.md``). The
``task_id`` binding is stamped on every background session, so the task that owns
them can stop them when it ends (ADR 0008).
"""

from agent.tools.bindings import ToolBindings
from agent.tools.exec_command import (
    EXEC_PARAMETERS,
    EXEC_TOOL_NAME,
    build_exec_description,
    make_exec_tool,
)
from agent.tools.permissions import PERMISSION_EXEC
from agent.tools.spec import ToolSpec

NAME = EXEC_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the shell execution tool to this run."""
    return ToolSpec(
        name=NAME,
        handler=make_exec_tool(
            base_dir=bindings.base_dir,
            session_id=bindings.session_id,
            max_tokens=bindings.max_tokens,
            output_directory=bindings.output_directory,
            task_id=bindings.task_id,
        ),
        description=build_exec_description(),
        parameters=EXEC_PARAMETERS,
        permission=PERMISSION_EXEC,
    )

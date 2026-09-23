"""The ``edit_file`` spec: name, schema, permission kind and its diff preview."""

from agent.tools.bindings import ToolBindings
from agent.tools.edit_file import (
    EDIT_FILE_DESCRIPTION,
    EDIT_FILE_PARAMETERS,
    make_edit_file_tool,
    make_edit_preview,
)
from agent.tools.permissions import PERMISSION_WRITE
from agent.tools.spec import ToolSpec

NAME = "edit_file"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the workspace scoped edit tool to this run."""
    return ToolSpec(
        name=NAME,
        handler=make_edit_file_tool(
            base_dir=bindings.base_dir,
            ledger=bindings.ledger,
            extra_read_roots=bindings.extra_read_roots,
        ),
        description=EDIT_FILE_DESCRIPTION,
        parameters=EDIT_FILE_PARAMETERS,
        permission=PERMISSION_WRITE,
        # Shows the diff before the user decides (ADR 0006 D11).
        preview=make_edit_preview(
            base_dir=bindings.base_dir, extra_read_roots=bindings.extra_read_roots
        ),
    )

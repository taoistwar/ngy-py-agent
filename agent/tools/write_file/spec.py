"""The ``write_file`` spec: name, schema, permission kind and workspace binding."""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_WRITE
from agent.tools.spec import CATEGORY_FILE, LOCALE_ZH_CN, ToolSpec
from agent.tools.write_file import (
    WRITE_FILE_DESCRIPTION,
    WRITE_FILE_PARAMETERS,
    make_write_file_tool,
)
from agent.tools.write_file.i18n import ZH_CN

NAME = "write_file"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the workspace scoped write tool to this run."""
    return ToolSpec(
        name=NAME,
        handler=make_write_file_tool(
            base_dir=bindings.base_dir,
            ledger=bindings.ledger,
            extra_read_roots=bindings.extra_read_roots,
        ),
        description=WRITE_FILE_DESCRIPTION,
        parameters=WRITE_FILE_PARAMETERS,
        permission=PERMISSION_WRITE,
        category=CATEGORY_FILE,
        description_i18n={LOCALE_ZH_CN: ZH_CN},
    )

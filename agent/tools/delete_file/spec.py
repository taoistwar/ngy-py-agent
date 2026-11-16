"""The ``delete_file`` spec: name, schema, permission kind and its scopes.

The permission kind is ``write``: deleting is a modification of the workspace, and the
gate reads ``file_path`` to name the target in the confirmation dialog
(``agent/tools/permissions.py``).
"""

from agent.tools.bindings import ToolBindings
from agent.tools.delete_file import DELETE_FILE_DESCRIPTION, DELETE_FILE_PARAMETERS, make_delete_file_tool
from agent.tools.delete_file.i18n import DE, FR, RU, ZH_CN, ZH_TW
from agent.tools.permissions import PERMISSION_WRITE, SCOPE_ONCE, SCOPE_SESSION
from agent.tools.spec import CATEGORY_FILE, ToolSpec, localized_texts

NAME = "delete_file"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the workspace scoped delete tool to this run."""
    return ToolSpec(
        name=NAME,
        handler=make_delete_file_tool(
            base_dir=bindings.base_dir,
            ledger=bindings.ledger,
            extra_read_roots=bindings.extra_read_roots,
        ),
        description=DELETE_FILE_DESCRIPTION,
        parameters=DELETE_FILE_PARAMETERS,
        permission=PERMISSION_WRITE,
        # A persisted "always" rule outlives the file it was granted for, and would
        # then approve deleting a different file created at the same path (ADR 0026).
        scopes=(SCOPE_ONCE, SCOPE_SESSION),
        category=CATEGORY_FILE,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )

"""The ``read_file`` spec: name, schema, permission kind and workspace binding."""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_READ
from agent.tools.read_file import (
    READ_FILE_DESCRIPTION,
    READ_FILE_PARAMETERS,
    make_read_file_tool,
)
from agent.tools.read_file.i18n import DE, FR, RU, ZH_CN, ZH_TW
from agent.tools.spec import CATEGORY_FILE, ToolSpec, localized_texts

NAME = "read_file"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the workspace scoped read tool to this run."""
    return ToolSpec(
        name=NAME,
        handler=make_read_file_tool(
            base_dir=bindings.base_dir,
            max_tokens=bindings.max_tokens,
            provider=bindings.provider,
            model=bindings.model,
            ledger=bindings.ledger,
            extra_read_roots=bindings.extra_read_roots,
        ),
        description=READ_FILE_DESCRIPTION,
        parameters=READ_FILE_PARAMETERS,
        # Reads are only confirmed for sensitive paths (ADR 0006 D3).
        permission=PERMISSION_READ,
        category=CATEGORY_FILE,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )

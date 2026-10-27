"""The ``glob`` spec: name, schema, permission kind and workspace binding."""

from agent.tools.bindings import ToolBindings
from agent.tools.glob import (
    GLOB_DESCRIPTION,
    GLOB_PARAMETERS,
    make_glob_tool,
)
from agent.tools.glob.i18n import DE, FR, RU, ZH_CN, ZH_TW
from agent.tools.permissions import PERMISSION_READ
from agent.tools.spec import CATEGORY_FILE, ToolSpec, localized_texts

NAME = "glob"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the search tool to this run's workspace and policy."""
    return ToolSpec(
        name=NAME,
        handler=make_glob_tool(
            base_dir=bindings.base_dir,
            extra_read_roots=bindings.extra_read_roots,
        ),
        description=GLOB_DESCRIPTION,
        parameters=GLOB_PARAMETERS,
        # A listing exposes names rather than contents, but it reads the disk, and
        # declaring ``read`` keeps it behind the same gate as ``read_file``: the
        # confirmation dialog can warn about a sensitive or outside-the-workspace
        # location, and ``deny_all`` covers it (ADR 0006).
        permission=PERMISSION_READ,
        category=CATEGORY_FILE,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )

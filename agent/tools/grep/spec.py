"""The ``grep`` spec: name, schema, permission kind and workspace binding."""

from agent.tools.bindings import ToolBindings
from agent.tools.grep import (
    GREP_DESCRIPTION,
    GREP_PARAMETERS,
    make_grep_tool,
)
from agent.tools.grep.i18n import DE, FR, RU, ZH_CN, ZH_TW
from agent.tools.permissions import PERMISSION_READ
from agent.tools.spec import CATEGORY_FILE, ToolSpec, localized_texts

NAME = "grep"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the content search to this run's workspace and policy."""
    return ToolSpec(
        name=NAME,
        handler=make_grep_tool(
            base_dir=bindings.base_dir,
            extra_read_roots=bindings.extra_read_roots,
        ),
        description=GREP_DESCRIPTION,
        parameters=GREP_PARAMETERS,
        # It reads file contents, so it is a read in every sense: the gate can
        # warn about a sensitive or outside-the-workspace search root, and
        # ``deny_all`` covers it (ADR 0006).
        permission=PERMISSION_READ,
        category=CATEGORY_FILE,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )

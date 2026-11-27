"""The ``subagent`` spec: name, schema, permission kind and run binding.

``permission`` stays ``none``: the delegated work is not one privileged action. Every
tool the subagent calls passes through its own registry gate with the same broker, so
the confirmation is asked for the command that will actually run, not for "delegating"
in the abstract.
"""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_NONE
from agent.tools.spec import CATEGORY_OTHER, ToolSpec, localized_texts
from agent.tools.subagent import (
    SUBAGENT_DESCRIPTION,
    SUBAGENT_PARAMETERS,
    SUBAGENT_TOOL_NAME,
    make_subagent_tool,
)
from agent.tools.subagent.i18n import DE, FR, RU, ZH_CN, ZH_TW

NAME = SUBAGENT_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the delegation tool to this run's nested-loop runner."""
    return ToolSpec(
        name=NAME,
        handler=make_subagent_tool(bindings.run_subagent),
        description=SUBAGENT_DESCRIPTION,
        parameters=SUBAGENT_PARAMETERS,
        permission=PERMISSION_NONE,
        category=CATEGORY_OTHER,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )

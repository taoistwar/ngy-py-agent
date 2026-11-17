"""The ``web_search`` spec: name, schema, permission kind and run binding."""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_READ
from agent.tools.spec import CATEGORY_NETWORK, ToolSpec, localized_texts
from agent.tools.web_search import (
    WEB_SEARCH_DESCRIPTION,
    WEB_SEARCH_PARAMETERS,
    make_web_search_tool,
)
from agent.tools.web_search.i18n import DE, FR, RU, ZH_CN, ZH_TW

NAME = "web_search"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the search tool to this run's output budget and scratch directory."""
    return ToolSpec(
        name=NAME,
        handler=make_web_search_tool(
            max_tokens=bindings.max_tokens,
            provider=bindings.provider,
            model=bindings.model,
            output_directory=bindings.output_directory,
        ),
        description=WEB_SEARCH_DESCRIPTION,
        parameters=WEB_SEARCH_PARAMETERS,
        # A search is traffic to a third party, not a file read: the gate asks
        # once per task whether this agent may search at all, which is what
        # ``permissions.NETWORK_READ_TOOLS`` and its search branch implement.
        permission=PERMISSION_READ,
        category=CATEGORY_NETWORK,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )

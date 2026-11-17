"""The ``web_fetch`` spec: name, schema, permission kind and run binding."""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_READ
from agent.tools.spec import CATEGORY_NETWORK, ToolSpec, localized_texts
from agent.tools.web_fetch import (
    WEB_FETCH_DESCRIPTION,
    WEB_FETCH_PARAMETERS,
    make_web_fetch_tool,
)
from agent.tools.web_fetch.i18n import DE, FR, RU, ZH_CN, ZH_TW

NAME = "web_fetch"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the fetch tool to this run's budget, model hints and scratch directory."""
    return ToolSpec(
        name=NAME,
        handler=make_web_fetch_tool(
            max_tokens=bindings.max_tokens,
            provider=bindings.provider,
            model=bindings.model,
            output_directory=bindings.output_directory,
        ),
        description=WEB_FETCH_DESCRIPTION,
        parameters=WEB_FETCH_PARAMETERS,
        # A page is read, not a file, so the gate asks about the host instead of a
        # path: ``permissions.NETWORK_READ_TOOLS`` is what makes that distinction,
        # and the rule it stores covers later pages from the same site (ADR 0027).
        permission=PERMISSION_READ,
        category=CATEGORY_NETWORK,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )

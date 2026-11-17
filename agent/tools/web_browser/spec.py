"""The ``web_browser`` spec: name, schema, permission kind and run binding."""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_READ
from agent.tools.spec import CATEGORY_NETWORK, ToolSpec, localized_texts
from agent.tools.web_browser import (
    WEB_BROWSER_DESCRIPTION,
    WEB_BROWSER_PARAMETERS,
    make_web_browser_tool,
)
from agent.tools.web_browser.i18n import DE, FR, RU, ZH_CN, ZH_TW

NAME = "web_browser"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the browser tool to this run's budget, model hints and scratch directory."""
    return ToolSpec(
        name=NAME,
        handler=make_web_browser_tool(
            max_tokens=bindings.max_tokens,
            provider=bindings.provider,
            model=bindings.model,
            output_directory=bindings.output_directory,
        ),
        description=WEB_BROWSER_DESCRIPTION,
        parameters=WEB_BROWSER_PARAMETERS,
        # A page is read, not a file: the gate asks about the *host* instead of a
        # path, because ``permissions.NETWORK_READ_TOOLS`` names this tool and the
        # stored rule then covers later pages from the same site (ADR 0027 D2).
        permission=PERMISSION_READ,
        category=CATEGORY_NETWORK,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )

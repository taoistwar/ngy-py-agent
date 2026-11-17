"""The ``vault_http`` spec: name, schema, permission kind and run binding."""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_VAULT
from agent.tools.spec import CATEGORY_NETWORK, ToolSpec, localized_texts
from agent.tools.vault_http import (
    VAULT_HTTP_DESCRIPTION,
    VAULT_HTTP_PARAMETERS,
    make_vault_http_tool,
)
from agent.tools.vault_http.i18n import DE, FR, RU, ZH_CN, ZH_TW

NAME = "vault_http"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the tool to this run's budget, model hints and scratch directory.

    The vault itself is not bound: it lives at a fixed path (``data/vault.json``,
    ``VAULT_SECRETS_PATH`` to relocate) and is re-read per call, so a key added in the
    admin's editor works on the next step instead of the next restart.
    """
    return ToolSpec(
        name=NAME,
        handler=make_vault_http_tool(
            max_tokens=bindings.max_tokens,
            provider=bindings.provider,
            model=bindings.model,
            output_directory=bindings.output_directory,
        ),
        description=VAULT_HTTP_DESCRIPTION,
        parameters=VAULT_HTTP_PARAMETERS,
        # A class of its own rather than ``read``: this tool does not read a page, it
        # attaches a credential and may change state on the other side, so the dialog
        # must say so and the rule key is "key@host", not a host (ADR 0030).
        permission=PERMISSION_VAULT,
        category=CATEGORY_NETWORK,
        # The one tool that asks even under ``auto_approve``: a standing "yes" to
        # everything is not a decision about which credential may go to which host.
        always_confirm=True,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )

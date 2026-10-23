"""The ``computer_control`` spec: name, schema, permission kind and scopes.

Every call is gated with ``PERMISSION_COMPUTER``. Only ``once`` and ``session``
are offered: a persistent "always allow" rule for clicking and typing would
outlive the task that justified it, and the rule store's exact-target matching
would make it a standing grant on a whole window.
"""

from agent.tools.bindings import ToolBindings
from agent.tools.computer_control import (
    CONTROL_DESCRIPTION,
    CONTROL_PARAMETERS,
    CONTROL_TOOL_NAME,
    build_preview,
    make_control_tool,
)
from agent.tools.computer_control.i18n import ZH_CN
from agent.tools.permissions import PERMISSION_COMPUTER, SCOPE_ONCE, SCOPE_SESSION
from agent.tools.spec import CATEGORY_COMPUTER, LOCALE_ZH_CN, ToolSpec

NAME = CONTROL_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the desktop-control tool to this run's driver session."""
    return ToolSpec(
        name=NAME,
        handler=make_control_tool(task_id=bindings.task_id),
        description=CONTROL_DESCRIPTION,
        parameters=CONTROL_PARAMETERS,
        permission=PERMISSION_COMPUTER,
        scopes=(SCOPE_ONCE, SCOPE_SESSION),
        preview=build_preview,
        category=CATEGORY_COMPUTER,
        description_i18n={LOCALE_ZH_CN: ZH_CN},
    )

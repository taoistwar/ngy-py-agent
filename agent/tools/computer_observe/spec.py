"""The ``computer_observe`` spec: name, schema and binding.

Read-only, so it declares no permission kind: the confirmation dialog would fire
on every snapshot, and a window listing is not an action. The run's task id is
the driver session, which is what keeps element tokens valid across calls.
"""

from agent.tools.bindings import ToolBindings
from agent.tools.computer_observe import (
    OBSERVE_DESCRIPTION,
    OBSERVE_PARAMETERS,
    OBSERVE_TOOL_NAME,
    make_observe_tool,
)
from agent.tools.computer_observe.i18n import ZH_CN
from agent.tools.spec import CATEGORY_COMPUTER, LOCALE_ZH_CN, ToolSpec

NAME = OBSERVE_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the observation tool to this run's session and scratch directory."""
    return ToolSpec(
        name=NAME,
        handler=make_observe_tool(
            task_id=bindings.task_id,
            max_tokens=bindings.max_tokens,
            provider=bindings.provider,
            model=bindings.model,
            output_directory=bindings.output_directory,
        ),
        description=OBSERVE_DESCRIPTION,
        parameters=OBSERVE_PARAMETERS,
        category=CATEGORY_COMPUTER,
        description_i18n={LOCALE_ZH_CN: ZH_CN},
    )

"""The ``computer_observe`` tool: read the host desktop through cua-driver.

Observation is deliberately its own tool rather than an action of the control
tool: the registry gates per tool, and asking for confirmation before every
``list_windows`` would make the agent unusable. It still emits a ``computer``
event for every call, so the UI keeps a record of what was looked at.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The declaration is in :mod:`~agent.tools.computer_observe.description`, the
adapter in :mod:`~agent.tools.computer_observe.tool`; this module re-exports the
public surface.
"""

from agent.tools.computer_observe.description import (
    OBSERVE_DESCRIPTION,
    OBSERVE_PARAMETERS,
    OBSERVE_TOOL_NAME,
)
from agent.tools.computer_observe.tool import ComputerInputError, make_observe_tool

__all__ = [
    "ComputerInputError",
    "OBSERVE_DESCRIPTION",
    "OBSERVE_PARAMETERS",
    "OBSERVE_TOOL_NAME",
    "make_observe_tool",
]

"""The ``computer_control`` tool: act on the host desktop through cua-driver.

Split from ``computer_observe`` on purpose. The permission gate is per tool, and
observation must stay free while clicking and typing are confirmed; the two
packages also differ in what they are allowed to do, so they do not share a
handler.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The declaration is in :mod:`~agent.tools.computer_control.description`, the
confirmation summary in :mod:`~agent.tools.computer_control.preview`, the call in
:mod:`~agent.tools.computer_control.tool`; this module re-exports the public
surface.
"""

from agent.tools.computer_control.description import (
    CONTROL_ACTIONS,
    CONTROL_DESCRIPTION,
    CONTROL_PARAMETERS,
    CONTROL_TOOL_NAME,
)
from agent.tools.computer_control.preview import build_preview
from agent.tools.computer_control.tool import ComputerInputError, make_control_tool

__all__ = [
    "CONTROL_ACTIONS",
    "CONTROL_DESCRIPTION",
    "CONTROL_PARAMETERS",
    "CONTROL_TOOL_NAME",
    "ComputerInputError",
    "build_preview",
    "make_control_tool",
]

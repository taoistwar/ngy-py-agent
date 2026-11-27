"""The ``subagent`` tool: delegate one self-contained task to a fresh conversation.

The subagent runs a nested ReAct loop in the same process, workspace and permission
gate, but with its own ``messages`` list. Only its final report returns to the parent
conversation; the intermediate tool calls never enter the parent's context. Delegation
is one level deep - the child run's tool set excludes this tool.

The tool package owns the contract (``description.py``), the call
(``tool.py``) and the declaration (``spec.py``). The nested loop lives in
:mod:`agent.agent_loop.subagent`, because it needs the provider and the event channel
that a tool is deliberately not given.
"""

from agent.tools.subagent.description import (
    SUBAGENT_DESCRIPTION,
    SUBAGENT_PARAMETERS,
    SUBAGENT_TOOL_NAME,
)
from agent.tools.subagent.errors import SubagentError
from agent.tools.subagent.tool import NO_RUNNER_TEXT, make_subagent_tool, subagent_impl

__all__ = [
    "NO_RUNNER_TEXT",
    "SUBAGENT_DESCRIPTION",
    "SUBAGENT_PARAMETERS",
    "SUBAGENT_TOOL_NAME",
    "SubagentError",
    "make_subagent_tool",
    "subagent_impl",
]

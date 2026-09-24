"""The ``ask_user_question`` tool: put one to three questions to the user and wait.

It is the only tool that *asks* rather than acts, so its plumbing differs from every
other package here: the questions travel out as a ``user_question`` event and the
answers come back through the API layer, which is why the channel is bound into
``ToolBindings`` instead of being constructed inside the tool (ADR 0010).

Nobody answering is a normal outcome, not a refusal: the result carries an empty answer
set and a sentence telling the model to decide for itself. That is the difference
between this tool and the permission gate, and the reason they are separate objects.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``). The
declaration is in :mod:`~agent.tools.ask_user_question.description`, the argument check
in :mod:`~agent.tools.ask_user_question.questions`, the call in
:mod:`~agent.tools.ask_user_question.tool`; this module re-exports the public surface.
"""

from agent.tools.ask_user_question.description import (
    ASK_USER_QUESTION_DESCRIPTION,
    ASK_USER_QUESTION_PARAMETERS,
    ASK_USER_QUESTION_TOOL_NAME,
)
from agent.tools.ask_user_question.errors import AskUserQuestionError
from agent.tools.ask_user_question.tool import (
    AskUser,
    ask_user_question_impl,
    make_ask_user_question_tool,
)

__all__ = [
    "ASK_USER_QUESTION_DESCRIPTION",
    "ASK_USER_QUESTION_PARAMETERS",
    "ASK_USER_QUESTION_TOOL_NAME",
    "AskUser",
    "AskUserQuestionError",
    "ask_user_question_impl",
    "make_ask_user_question_tool",
]

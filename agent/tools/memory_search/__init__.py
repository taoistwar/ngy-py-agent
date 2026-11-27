"""The ``memory_search`` tool: read remembered notes back, by keyword.

The index is in the system prompt (see ``agent.agent_loop.memory_context``), so this
tool answers the second half of recall: which bodies are worth loading, and what they
say. Bodies never enter the prompt on their own, which is what keeps a growing library
from eating the context window (ADR 0035).

One tool, one package, named after the tool the model sees (see ``AGENTS.md``). The
declaration is in :mod:`~agent.tools.memory_search.description`, the call in
:mod:`~agent.tools.memory_search.tool`, the display translations in
:mod:`~agent.tools.memory_search.i18n`; this module re-exports the public surface.
"""

from agent.tools.memory_search.description import (
    MAX_RESULT_CHARS,
    MEMORY_SEARCH_DESCRIPTION,
    MEMORY_SEARCH_PARAMETERS,
    MEMORY_SEARCH_TOOL_NAME,
)
from agent.tools.memory_search.tool import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    make_memory_search_tool,
    memory_search_impl,
)

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MAX_RESULT_CHARS",
    "MEMORY_SEARCH_DESCRIPTION",
    "MEMORY_SEARCH_PARAMETERS",
    "MEMORY_SEARCH_TOOL_NAME",
    "make_memory_search_tool",
    "memory_search_impl",
]

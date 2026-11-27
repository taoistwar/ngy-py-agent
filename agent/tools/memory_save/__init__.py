"""The ``memory_save`` tool: keep one durable note for later conversations.

Memory is knowledge that outlives a conversation, so this tool writes a *library* rather
than a transcript: one note per idea, keyed by a slug, with an index line that every
later session sees and a body that is read only when it matters (ADR 0035).

One tool, one package, named after the tool the model sees (see ``AGENTS.md``). The
declaration is in :mod:`~agent.tools.memory_save.description`, the call in
:mod:`~agent.tools.memory_save.tool`, the display translations in
:mod:`~agent.tools.memory_save.i18n`; this module re-exports the public surface.
"""

from agent.tools.memory_save.description import (
    MEMORY_SAVE_DESCRIPTION,
    MEMORY_SAVE_PARAMETERS,
    MEMORY_SAVE_TOOL_NAME,
)
from agent.tools.memory_save.tool import (
    MemorySaveError,
    make_memory_save_tool,
    memory_save_impl,
)

__all__ = [
    "MEMORY_SAVE_DESCRIPTION",
    "MEMORY_SAVE_PARAMETERS",
    "MEMORY_SAVE_TOOL_NAME",
    "MemorySaveError",
    "make_memory_save_tool",
    "memory_save_impl",
]

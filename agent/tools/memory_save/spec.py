"""The ``memory_save`` spec: name, description, schema, run binding.

``permission`` stays ``none``: a memory is a note to itself, the same call ``todo_write``
makes. Nothing here touches the machine, the network or the user's files, and a
confirmation dialog in front of "remember that I prefer tabs" would be a question with
no stakes.
"""

from agent.tools.bindings import ToolBindings
from agent.tools.memory_save import (
    MEMORY_SAVE_DESCRIPTION,
    MEMORY_SAVE_PARAMETERS,
    MEMORY_SAVE_TOOL_NAME,
    make_memory_save_tool,
)
from agent.tools.memory_save.i18n import DE, FR, RU, ZH_CN, ZH_TW
from agent.tools.permissions import PERMISSION_NONE
from agent.tools.spec import CATEGORY_OTHER, ToolSpec, localized_texts

NAME = MEMORY_SAVE_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the write tool to this run's memory library."""
    return ToolSpec(
        name=NAME,
        handler=make_memory_save_tool(bindings.memory_book),
        description=MEMORY_SAVE_DESCRIPTION,
        parameters=MEMORY_SAVE_PARAMETERS,
        permission=PERMISSION_NONE,
        category=CATEGORY_OTHER,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )

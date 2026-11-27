"""The ``memory_search`` spec: name, description, schema, run binding.

``permission`` stays ``none``: reading notes this agent wrote is the same kind of
operation as reading its own plan, and the notes never leave the local database.
"""

from agent.tools.bindings import ToolBindings
from agent.tools.memory_search import (
    MEMORY_SEARCH_DESCRIPTION,
    MEMORY_SEARCH_PARAMETERS,
    MEMORY_SEARCH_TOOL_NAME,
    make_memory_search_tool,
)
from agent.tools.memory_search.i18n import DE, FR, RU, ZH_CN, ZH_TW
from agent.tools.permissions import PERMISSION_NONE
from agent.tools.spec import CATEGORY_OTHER, ToolSpec, localized_texts

NAME = MEMORY_SEARCH_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the read tool to this run's memory library."""
    return ToolSpec(
        name=NAME,
        handler=make_memory_search_tool(bindings.memory_book),
        description=MEMORY_SEARCH_DESCRIPTION,
        parameters=MEMORY_SEARCH_PARAMETERS,
        permission=PERMISSION_NONE,
        category=CATEGORY_OTHER,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )

"""The ``todo_write`` tool: keep the conversation's plan, one checklist at a time.

It is the only tool that changes nothing but the plan, which is the point: what it
adds is not execution, it is planning. The list is **session** scoped (``TodoBoard``
in :mod:`agent.tools.todo_store`), so a follow-up task continues the checklist the
previous one left, and the web admin renders it from the task detail response.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``). The
declaration is in :mod:`~agent.tools.todo_write.description`, the checks and the
rendering in :mod:`~agent.tools.todo_write.items`, the call in
:mod:`~agent.tools.todo_write.tool`; this module re-exports the public surface.
"""

from agent.tools.todo_write.description import (
    TODO_WRITE_DESCRIPTION,
    TODO_WRITE_PARAMETERS,
    TODO_WRITE_TOOL_NAME,
)
from agent.tools.todo_write.items import (
    MAX_TODOS,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUSES,
    counts,
    parse_todos,
    render_todos,
)
from agent.tools.todo_write.tool import TodoWriteError, make_todo_write_tool, todo_write_impl

__all__ = [
    "MAX_TODOS",
    "STATUSES",
    "STATUS_COMPLETED",
    "STATUS_IN_PROGRESS",
    "STATUS_PENDING",
    "TODO_WRITE_DESCRIPTION",
    "TODO_WRITE_PARAMETERS",
    "TODO_WRITE_TOOL_NAME",
    "TodoWriteError",
    "counts",
    "make_todo_write_tool",
    "parse_todos",
    "render_todos",
    "todo_write_impl",
]

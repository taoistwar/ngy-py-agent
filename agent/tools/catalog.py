"""The built-in tool list: every tool package's spec builder, in one place.

Adding a tool means adding its package under ``agent/tools/`` and one line in
``_BUILDERS`` below. Everything else about the tool — name, description, schema,
permission kind, scopes — lives in that package's ``spec.py``, so reading one tool
never means leaving its package (see ``agent/tools/__init__.py``).
"""

from __future__ import annotations

from typing import Callable, List, Sequence

from agent.tools.ask_user_question import spec as ask_user_question
from agent.tools.bindings import ToolBindings
from agent.tools.code_interpreter import spec as code_interpreter
from agent.tools.computer_control import spec as computer_control
from agent.tools.computer_observe import spec as computer_observe
from agent.tools.delete_file import spec as delete_file
from agent.tools.edit_file import spec as edit_file
from agent.tools.exec_command import spec as exec_command
from agent.tools.glob import spec as glob
from agent.tools.grep import spec as grep
from agent.tools.memory_save import spec as memory_save
from agent.tools.memory_search import spec as memory_search
from agent.tools.read_file import spec as read_file
from agent.tools.spec import ToolSpec
from agent.tools.subagent import spec as subagent
from agent.tools.task_claim import spec as task_claim
from agent.tools.task_complete import spec as task_complete
from agent.tools.task_create import spec as task_create
from agent.tools.task_get import spec as task_get
from agent.tools.task_list import spec as task_list
from agent.tools.task_update import spec as task_update
from agent.tools.todo_write import spec as todo_write
from agent.tools.vault_http import spec as vault_http
from agent.tools.web_browser import spec as web_browser
from agent.tools.web_fetch import spec as web_fetch
from agent.tools.web_search import spec as web_search
from agent.tools.write_file import spec as write_file
from agent.tools.write_stdin import spec as write_stdin

# The order here is the order the model sees the tools in, so it stays stable.
_BUILDERS: Sequence[Callable[[ToolBindings], ToolSpec]] = (
    # Planning comes before the tools that act, so it is listed first: the model
    # reads the list top down, and ``todo_write`` is what it should reach for before
    # a multi-step task turns into a series of unrelated tool calls.
    todo_write.build_spec,
    # Knowledge from earlier conversations sits next to planning: both are context the
    # conversation keeps for itself, not work done on the machine. Read before write, so
    # a model that is about to record something first sees what it already recorded
    # (ADR 0035).
    memory_search.build_spec,
    memory_save.build_spec,
    # The task board is the same idea one level up: ``todo_write`` orders the steps of
    # *this* conversation, the board orders the project's work across conversations.
    # Their order is create -> sequence -> read -> claim -> finish, which is also the
    # order a model should use them in, so it is listed in that order.
    task_create.build_spec,
    task_update.build_spec,
    task_list.build_spec,
    task_get.build_spec,
    task_claim.build_spec,
    task_complete.build_spec,
    # Delegation sits next to planning: a multi-step task should first be planned, and
    # then the parts that would flood this context are handed off (ADR 0032). The child
    # tool list is this list minus ``CHILD_EXCLUDED_TOOLS``, so the order informs the
    # subagent too.
    subagent.build_spec,
    code_interpreter.build_spec,
    # Find before read: ``glob`` locates a file by name, ``grep`` locates the code
    # inside it, ``web_search`` finds the page that documents it, ``web_fetch``
    # reads that page, and only then does ``read_file`` need to run. ``web_browser``
    # sits next to ``web_fetch`` because both open a URL; theirs is the simple
    # reading view, and it is listed second so the richer contract comes first.
    glob.build_spec,
    grep.build_spec,
    web_search.build_spec,
    web_fetch.build_spec,
    web_browser.build_spec,
    # An authenticated request belongs beside the public readers: same "reach a URL"
    # family, and ``web_fetch``'s description says it cannot log in, so the tool that
    # can is where the model looks next (ADR 0030).
    vault_http.build_spec,
    read_file.build_spec,
    edit_file.build_spec,
    write_file.build_spec,
    # Removal sits next to the tools that produce content, not with the shell: it is
    # the guarded way to make a file go away (ADR 0026).
    delete_file.build_spec,
    exec_command.build_spec,
    write_stdin.build_spec,
    computer_observe.build_spec,
    computer_control.build_spec,
    # Asks rather than acts, so it sits last: it belongs to no family of tools above.
    ask_user_question.build_spec,
)


# Tools a subagent never gets. Delegation is one level deep, and planning belongs to
# the conversation that keeps the plan: the child answers one brief with a context it
# throws away when it returns, so creating, sequencing or claiming project tasks there
# would be both overreach and extra tokens (ADR 0032 D2, ADR 0033). ``memory_save`` is
# excluded for the same reason and one more: what the child learned belongs in its
# report to the parent, which is the run that knows whether it still matters later
# (ADR 0035). ``memory_search`` stays - reading a note is how a brief gets answered.
CHILD_EXCLUDED_TOOLS = frozenset(
    [subagent.NAME, memory_save.NAME]
    + [
        module.NAME
        for module in (task_create, task_update, task_list, task_get, task_claim, task_complete)
    ]
)


def build_all_specs(bindings: ToolBindings) -> List[ToolSpec]:
    """Every built-in tool, bound to one run."""
    return [build(bindings) for build in _BUILDERS]

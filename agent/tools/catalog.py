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
from agent.tools.read_file import spec as read_file
from agent.tools.spec import ToolSpec
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


def build_all_specs(bindings: ToolBindings) -> List[ToolSpec]:
    """Every built-in tool, bound to one run."""
    return [build(bindings) for build in _BUILDERS]

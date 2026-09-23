"""The built-in tool list: every tool package's spec builder, in one place.

Adding a tool means adding its package under ``agent/tools/`` and one line in
``_BUILDERS`` below. Everything else about the tool — name, description, schema,
permission kind, scopes — lives in that package's ``spec.py``, so reading one tool
never means leaving its package (see ``agent/tools/__init__.py``).
"""

from __future__ import annotations

from typing import Callable, List, Sequence

from agent.tools.bindings import ToolBindings
from agent.tools.code_interpreter import spec as code_interpreter
from agent.tools.convert_currency import spec as convert_currency
from agent.tools.edit_file import spec as edit_file
from agent.tools.exec_command import spec as exec_command
from agent.tools.get_current_temperature import spec as get_current_temperature
from agent.tools.get_current_time import spec as get_current_time
from agent.tools.read_file import spec as read_file
from agent.tools.spec import ToolSpec
from agent.tools.write_file import spec as write_file
from agent.tools.write_stdin import spec as write_stdin

# The order here is the order the model sees the tools in, so it stays stable.
_BUILDERS: Sequence[Callable[[ToolBindings], ToolSpec]] = (
    get_current_temperature.build_spec,
    get_current_time.build_spec,
    convert_currency.build_spec,
    code_interpreter.build_spec,
    read_file.build_spec,
    edit_file.build_spec,
    write_file.build_spec,
    exec_command.build_spec,
    write_stdin.build_spec,
)


def build_all_specs(bindings: ToolBindings) -> List[ToolSpec]:
    """Every built-in tool, bound to one run."""
    return [build(bindings) for build in _BUILDERS]

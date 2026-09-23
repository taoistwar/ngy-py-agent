"""The ``code_interpreter`` tool: run Python for calculations and data work.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The implementation lives in :mod:`~agent.tools.code_interpreter.tool`; this module
re-exports the public surface and nothing else.
"""

from agent.tools.code_interpreter.tool import code_interpreter

__all__ = ["code_interpreter"]

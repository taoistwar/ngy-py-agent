"""The ``get_current_time`` tool: the current date and time in a timezone.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The implementation lives in :mod:`~agent.tools.get_current_time.tool`; this module
re-exports the public surface and nothing else.
"""

from agent.tools.get_current_time.tool import TimeToolError, get_current_time

__all__ = ["TimeToolError", "get_current_time"]

"""The ``convert_currency`` tool: convert an amount at the latest rate.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The implementation lives in :mod:`~agent.tools.convert_currency.tool`; this module
re-exports the public surface and nothing else.
"""

from agent.tools.convert_currency.tool import FinanceToolError, convert_currency

__all__ = ["FinanceToolError", "convert_currency"]

"""Backwards compatible import path for the tool registry.

The registry and the tool implementations moved into the :mod:`agent.tools`
package so that each module stays small. This module is kept as a thin
re-export: ``from agent.tool_registry import ToolRegistry`` still works.
"""

from typing import Dict

from agent.tools.registry import ToolRegistry

__all__ = ["ToolRegistry", "format_tool_response"]


def format_tool_response(tool_name: str, tool_result: str) -> Dict:
    """Format tool response for the chat model"""
    return {"role": "tool", "name": tool_name, "content": tool_result}

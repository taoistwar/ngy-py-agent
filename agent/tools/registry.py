"""Tool registry: registration, provider schema adaptation and dispatch."""

import copy
import json
from typing import Any, Callable, Dict, List

from agent.tools import code_tools, finance_tools, time_tools, weather_tools
from agent.tools.specs import DEFAULT_TOOL_SPECS


class ToolRegistry:
    """Registry for managing available tools"""

    _ADAPTERS = {
        "openai": "openai",
        "openai_compatible": "openai",
        "openai-compatible": "openai",
        "anthropic": "anthropic",
        "anthropic_compatible": "anthropic",
        "anthropic-compatible": "anthropic",
        "claude": "anthropic",
        "gemini": "gemini",
        "google": "gemini",
        "google_generative_ai": "gemini",
        "google-generative-ai": "gemini",
        "bedrock": "bedrock",
        "aws": "bedrock",
        "mcp": "mcp",
    }

    @classmethod
    def normalize_provider(cls, provider: str) -> str:
        key = (provider or "openai").strip().lower()
        return cls._ADAPTERS.get(key, key)

    def __init__(self, enabled_tools: list[str] | None = None):
        self.tools = {}
        self._register_default_tools(enabled_tools)

    def _register_default_tools(self, enabled_tools: list[str] | None = None):
        """Register default tools. Pass enabled_tools to restrict the set."""
        for spec in DEFAULT_TOOL_SPECS:
            self.register_tool(
                name=spec.name,
                function=spec.handler,
                description=spec.description,
                parameters=spec.parameters,
            )

        if enabled_tools is not None:
            allowed = set(enabled_tools)
            for name in list(self.tools.keys()):
                if name not in allowed:
                    self.tools.pop(name, None)

    def register_tool(
        self, name: str, function: Callable[..., Any], description: str, parameters: Dict
    ):
        """Register a new tool"""
        self.tools[name] = {
            "function": function,
            "description": description,
            "parameters": parameters,
        }

    def get_tool_schemas(self, provider: str = "openai") -> List[Dict[str, Any]]:
        """Get provider-compatible tool schemas"""
        provider = self.normalize_provider(provider)
        if provider == "openai":
            return self._openai_schemas()
        if provider == "anthropic":
            return self._anthropic_schemas()
        if provider == "gemini":
            return self._gemini_schemas()
        if provider == "bedrock":
            return self._bedrock_schemas()
        if provider == "mcp":
            return self._mcp_schemas()
        raise ValueError(f"Unsupported provider: {provider}")

    def _schema_copy(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        return copy.deepcopy(schema)

    def _openai_schemas(self) -> List[Dict[str, Any]]:
        """OpenAI-compatible function schema."""
        schemas = []
        for name, tool in self.tools.items():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool["description"],
                        "parameters": self._schema_copy(tool["parameters"]),
                        "strict": False,
                    },
                }
            )
        return schemas

    def _anthropic_schemas(self) -> List[Dict[str, Any]]:
        """Anthropic tool schema."""
        schemas = []
        for name, tool in self.tools.items():
            schemas.append(
                {
                    "name": name,
                    "description": tool["description"],
                    "input_schema": self._schema_copy(tool["parameters"]),
                }
            )
        return schemas

    def _gemini_schemas(self) -> List[Dict[str, Any]]:
        """Gemini function declaration schema."""
        schemas = []
        for name, tool in self.tools.items():
            schemas.append(
                {
                    "name": name,
                    "description": tool["description"],
                    "parameters": self._schema_copy(tool["parameters"]),
                }
            )
        return schemas

    def _bedrock_schemas(self) -> List[Dict[str, Any]]:
        """AWS Bedrock ToolSpec-style schema."""
        schemas = []
        for name, tool in self.tools.items():
            schemas.append(
                {
                    "toolSpec": {
                        "name": name,
                        "description": tool["description"],
                        "inputSchema": {
                            "json": self._schema_copy(tool["parameters"]),
                        },
                    }
                }
            )
        return schemas

    def _mcp_schemas(self) -> List[Dict[str, Any]]:
        """MCP-aligned simplified tool descriptors."""
        schemas = []
        for name, tool in self.tools.items():
            parameters = self._schema_copy(tool["parameters"])
            schemas.append(
                {
                    "name": name,
                    "description": tool["description"],
                    "inputSchema": parameters,
                    "annotations": {},
                }
            )
        return schemas

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """Execute a tool by name with given arguments"""
        if name not in self.tools:
            return json.dumps({"error": f"Tool '{name}' not found"})

        try:
            result = self.tools[name]["function"](**arguments)
            return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # Backwards compatible aliases for the previous static-method API.
    get_current_temperature = staticmethod(weather_tools.get_current_temperature)
    get_current_time = staticmethod(time_tools.get_current_time)
    convert_currency = staticmethod(finance_tools.convert_currency)
    code_interpreter = staticmethod(code_tools.code_interpreter)

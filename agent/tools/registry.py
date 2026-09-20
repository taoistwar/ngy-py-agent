"""Tool registry: registration, provider schema adaptation and dispatch."""

import copy
import json
from typing import Any, Callable, Dict, List, Optional

from agent.models import EventCategory, ToolOutcome
from agent.tools import code_tools, finance_tools, time_tools, weather_tools
from agent.tools.output_store import output_root_path
from agent.tools.permissions import (
    PERMISSION_NONE,
    PermissionBroker,
    PermissionDenial,
)
from agent.tools.read_ledger import ReadLedger
from agent.tools.specs import (
    DEFAULT_TOOL_SPECS,
    build_edit_file_spec,
    build_exec_spec,
    build_read_file_spec,
    build_write_file_spec,
)


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

    def __init__(
        self,
        enabled_tools: list[str] | None = None,
        base_dir: str | None = None,
        max_tokens: int = 0,
        provider: str = "",
        model: str = "",
        session_id: str = "",
        permission_broker: Optional[PermissionBroker] = None,
    ):
        self.base_dir = base_dir
        self.max_tokens = max_tokens
        self.provider = provider
        self.model = model
        self.session_id = session_id
        # ``None`` keeps the historical behaviour (everything runs). agent_loop
        # assigns the broker after building the registry, because the registry is
        # built before the task identity exists (see ADR 0006 D1).
        self.permission_broker = permission_broker
        # Shared by read/edit/write, so write_file can tell whether this run has
        # already held the whole content it is about to replace.
        self.read_ledger = ReadLedger()
        # Scratch space for large command output. It is readable but never
        # writable by the file tools (see docs/decisions/0005-exec-tool.md).
        self.output_directory = output_root_path(self.base_dir, self.session_id)
        self.read_only_roots = (self.output_directory.as_posix(),)
        self.tools = {}
        self._register_default_tools(enabled_tools)

    def _register_default_tools(self, enabled_tools: list[str] | None = None):
        """Register default tools. Pass enabled_tools to restrict the set."""
        specs = list(DEFAULT_TOOL_SPECS)
        specs.append(
            build_read_file_spec(
                base_dir=self.base_dir,
                max_tokens=self.max_tokens,
                provider=self.provider,
                model=self.model,
                ledger=self.read_ledger,
                extra_read_roots=self.read_only_roots,
            )
        )
        specs.append(
            build_edit_file_spec(
                base_dir=self.base_dir,
                ledger=self.read_ledger,
                extra_read_roots=self.read_only_roots,
            )
        )
        specs.append(
            build_write_file_spec(
                base_dir=self.base_dir,
                ledger=self.read_ledger,
                extra_read_roots=self.read_only_roots,
            )
        )
        specs.append(
            build_exec_spec(
                base_dir=self.base_dir,
                session_id=self.session_id,
                max_tokens=self.max_tokens,
                output_directory=self.output_directory,
            )
        )

        for spec in specs:
            self.register_tool(
                name=spec.name,
                function=spec.handler,
                description=spec.description,
                parameters=spec.parameters,
                permission=spec.permission,
                preview=spec.preview,
            )

        if enabled_tools is not None:
            allowed = set(enabled_tools)
            for name in list(self.tools.keys()):
                if name not in allowed:
                    self.tools.pop(name, None)

    def register_tool(
        self,
        name: str,
        function: Callable[..., Any],
        description: str,
        parameters: Dict,
        permission: str = PERMISSION_NONE,
        preview: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        """Register a new tool.

        ``permission`` is the confirmation kind (``agent/tools/permissions.py``).
        It defaults to ``none``, i.e. never confirmed, so a tool that touches the
        filesystem must say so explicitly. ``preview`` is an optional side-effect
        free dry run used to fill in the confirmation dialog.
        """
        self.tools[name] = {
            "function": function,
            "description": description,
            "parameters": parameters,
            "permission": permission or PERMISSION_NONE,
            "preview": preview,
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

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a tool by name and return its raw result.

        This is the single choke point every tool call passes through, which is
        why the permission gate lives here rather than inside the tools: coverage
        is then "all of them", including tools added later (ADR 0006 D1).

        ``ToolOutcome`` results are passed through untouched so the caller can
        route the model-facing text and the UI-facing payload separately. Any
        other result is stringified (dict/list -> JSON) because that is what
        gets fed back to the model as the tool message.

        Tool exceptions are deliberately propagated instead of being converted
        into an ``{"error": ...}`` payload: callers rely on them to mark the
        step as failed (see ``agent.agent_loop``), and a "successful" result
        carrying an error key hides the failure from both the model and the UI.
        """
        if name not in self.tools:
            return json.dumps({"error": f"Tool '{name}' not found"})

        denial = self._permission_denial(name, arguments)
        if denial is not None:
            # A refusal is a result, not a failure: no exception, so the step is
            # not marked as failed, and the model gets a reason it can act on.
            return ToolOutcome(
                model_text=denial.model_text,
                event_category=EventCategory.PERMISSION_DECISION,
                event_title=f"Permission denied: {name}",
                details=denial.details,
            )

        result = self.tools[name]["function"](**arguments)
        if isinstance(result, ToolOutcome):
            return result
        return json.dumps(result) if isinstance(result, (dict, list)) else str(result)

    def _permission_denial(
        self, name: str, arguments: Dict[str, Any]
    ) -> Optional[PermissionDenial]:
        """Consult the permission broker, or ``None`` when the call may run.

        Tools declaring ``permission="none"`` never reach the broker, which keeps
        the gate off the hot path for pure lookups and limits a broker bug to the
        tools that are actually gated.

        A broker that raises **denies** the call: this is a safety prompt, so a
        broken gate must fail closed and loudly rather than quietly letting
        everything through.
        """
        broker = self.permission_broker
        if broker is None:
            return None
        kind = self.tools[name].get("permission") or PERMISSION_NONE
        if kind == PERMISSION_NONE:
            return None
        try:
            return broker.check(name, kind, arguments, preview=self.tools[name].get("preview"))
        except Exception as exc:
            return PermissionDenial(
                model_text=(
                    f"Permission check failed for {name}: {exc.__class__.__name__}: {exc}\n"
                    "The call was not approved. This is a defect in the permission layer; "
                    "retrying the same call will not help."
                ),
                details={
                    "reason": "broker_error",
                    "tool": name,
                    "kind": kind,
                    "error": str(exc),
                    "allowed": False,
                },
            )

    # Backwards compatible aliases for the previous static-method API.
    get_current_temperature = staticmethod(weather_tools.get_current_temperature)
    get_current_time = staticmethod(time_tools.get_current_time)
    convert_currency = staticmethod(finance_tools.convert_currency)
    code_interpreter = staticmethod(code_tools.code_interpreter)

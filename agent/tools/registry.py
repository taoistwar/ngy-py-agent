"""Tool registry: registration, provider schema adaptation and dispatch."""

import copy
import json
from typing import Any, Callable, ClassVar, Dict, List, Optional, Sequence

from agent.models import EventCategory, ToolOutcome
from agent.provider import canonicalize_provider
from agent.tools.bindings import ToolBindings
from agent.tools.catalog import build_all_specs
from agent.tools.code_interpreter import code_interpreter as _code_interpreter
from agent.tools.convert_currency import convert_currency as _convert_currency
from agent.tools.get_current_temperature import (
    get_current_temperature as _get_current_temperature,
)
from agent.tools.get_current_time import get_current_time as _get_current_time
from agent.tools.output_store import output_root_path
from agent.tools.permissions import (
    PERMISSION_NONE,
    SCOPES,
    PermissionBroker,
    PermissionDenial,
)
from agent.tools.read_ledger import ReadLedger


class ToolRegistry:
    """Registry for managing available tools"""

    # Which schema shape a provider's tools are rendered in, keyed by canonical
    # provider name (``agent.provider.canonicalize_provider``). Spellings and
    # synonyms are resolved there, so only the shapes appear here. Annotated as a
    # ``ClassVar`` because it is shared, read-only lookup state owned by the class
    # rather than something an instance may set.
    _ADAPTERS: ClassVar[Dict[str, str]] = {
        "openai": "openai",
        "anthropic": "anthropic",
        "anthropic_compatible": "anthropic",
        "gemini": "gemini",
        "bedrock": "bedrock",
        "mcp": "mcp",
    }

    @classmethod
    def normalize_provider(cls, provider: Any) -> str:
        """Map a configured provider name to the adapter serving its tool schema.

        Spelling and synonyms are ``agent.provider``'s business, so this only decides
        which schema shape the canonical name gets. A blank or non-string value means
        "not configured" and keeps the long-standing default of OpenAI; an unknown
        name is returned normalised rather than guessed, so the caller's
        ``ValueError`` names what it got.
        """
        key = canonicalize_provider(provider)
        return cls._ADAPTERS.get(key, key)

    def __init__(
        self,
        enabled_tools: list[str] | None = None,
        base_dir: str | None = None,
        max_tokens: int = 0,
        provider: str = "",
        model: str = "",
        session_id: str = "",
        task_id: str = "",
        permission_broker: Optional[PermissionBroker] = None,
    ):
        self.base_dir = base_dir
        self.max_tokens = max_tokens
        self.provider = provider
        self.model = model
        self.session_id = session_id
        # Stamped on every background session this registry's tools start, and the
        # capability ``write_stdin`` checks before touching one.
        self.task_id = task_id
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
        # One description of what this run is bound to, handed to every tool; each
        # tool takes the parts it needs (see agent/tools/bindings.py).
        bindings = ToolBindings(
            base_dir=self.base_dir,
            session_id=self.session_id,
            task_id=self.task_id,
            max_tokens=self.max_tokens,
            provider=self.provider,
            model=self.model,
            output_directory=self.output_directory,
            ledger=self.read_ledger,
            extra_read_roots=self.read_only_roots,
        )

        for spec in build_all_specs(bindings):
            self.register_tool(
                name=spec.name,
                function=spec.handler,
                description=spec.description,
                parameters=spec.parameters,
                permission=spec.permission,
                scopes=spec.scopes,
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
        scopes: Optional[Sequence[str]] = None,
        preview: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        """Register a new tool.

        ``permission`` is the confirmation kind (``agent/tools/permissions.py``).
        It defaults to ``none``, i.e. never confirmed, so a tool that touches the
        filesystem must say so explicitly. ``scopes`` narrows the answers the
        dialog may offer. ``preview`` is an optional side-effect free dry run used
        to fill in the confirmation dialog.
        """
        self.tools[name] = {
            "function": function,
            "description": description,
            "parameters": parameters,
            "permission": permission or PERMISSION_NONE,
            "scopes": tuple(scopes or SCOPES),
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
            return broker.check(
                name,
                kind,
                arguments,
                preview=self.tools[name].get("preview"),
                scopes=self.tools[name].get("scopes"),
            )
        # Deliberately broad: any broker fault must deny the call, so narrowing this
        # would turn an unexpected error into a silent pass (ADR 0006 D1).
        except Exception as exc:  # noqa: BLE001
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
    get_current_temperature = staticmethod(_get_current_temperature)
    get_current_time = staticmethod(_get_current_time)
    convert_currency = staticmethod(_convert_currency)
    code_interpreter = staticmethod(_code_interpreter)

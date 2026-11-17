"""Tool registry: registration, provider schema adaptation and dispatch."""

import copy
import json
from typing import Any, Callable, ClassVar, Dict, List, Mapping, Optional, Sequence

from agent.models import EventCategory, ToolOutcome
from agent.provider import canonicalize_provider
from agent.tools.bindings import ToolBindings
from agent.tools.catalog import build_all_specs
from agent.tools.code_interpreter import code_interpreter as _code_interpreter
from agent.tools.denylist import (
    REASON_DENYLIST,
    REASON_DENYLIST_ERROR,
    ToolDenyList,
)
from agent.tools.output_store import (
    output_root_path,
    workspace_result_directory,
    workspace_transcript_directory,
)
from agent.tools.permissions import (
    PERMISSION_NONE,
    SCOPES,
    PermissionBroker,
    PermissionDenial,
)
from agent.tools.read_ledger import ReadLedger
from agent.tools.spec import CATEGORY_OTHER, ToolText
from agent.tools.user_question import STATUS_NO_CLIENT, QuestionResult, UserQuestionBroker


def _implementation_source(handler: Callable[..., Any]) -> str:
    """The file a handler is defined in, relative to the repository root.

    Tool handlers are built inside ``agent/tools/<tool>/tool.py`` (closures) or are
    plain functions of that same package, so the module names the implementing
    file. A handler that is not a plain function - a callable object, a partial -
    reports no source instead of guessing one.
    """
    module = getattr(handler, "__module__", "")
    if not isinstance(module, str) or not module.startswith("agent."):
        return ""
    return f"{module.replace('.', '/')}.py"


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
        denylist: Optional[ToolDenyList] = None,
        user_question_broker: Optional[UserQuestionBroker] = None,
        should_stop: Optional[Callable[[], bool]] = None,
        checkpoint_store: Optional[Any] = None,
    ):
        self.base_dir = base_dir
        self.max_tokens = max_tokens
        self.provider = provider
        self.model = model
        self.session_id = session_id
        # Stamped on every background session this registry's tools start, and the
        # capability ``write_stdin`` checks before touching one.
        self.task_id = task_id
        # Read per call by the tools that can block for a long time, so a stop lands
        # in the middle of one instead of after it (ADR 0019).
        self.should_stop = should_stop
        # Records what a mutating call changed, so the task can be undone later
        # (ADR 0020). ``None`` means "nothing to record" - a CLI run, or a test.
        self.checkpoint_store = checkpoint_store
        # ``None`` keeps the historical behaviour (everything runs). agent_loop
        # assigns the broker after building the registry, because the registry is
        # built before the task identity exists (see ADR 0006 D1).
        self.permission_broker = permission_broker
        # Hard denials (ADR 0024): a listed tool + argument combination never runs
        # and the permission gate never sees it. ``None`` means "the file the
        # configuration points at", never "no deny-list", so the layer is only
        # off when a caller passes an explicitly empty list.
        self.denylist = denylist if denylist is not None else ToolDenyList()
        # Same late-binding trick for the question channel, and for the same reason:
        # ``ask_user`` below reads this per call, so a registry built before the task
        # existed still answers through the broker the task installed (ADR 0010 D1).
        self.user_question_broker = user_question_broker
        # Shared by read/edit/write, so write_file can tell whether this run has
        # already held the whole content it is about to replace.
        self.read_ledger = ReadLedger()
        # Scratch space for large command output. It is readable but never
        # writable by the file tools (see docs/decisions/0005-exec-tool.md).
        self.output_directory = output_root_path(self.base_dir, self.session_id)
        # Tool results the loop moved out of the context (ADR 0012). Inside the
        # workspace, but read-only for the same reason as the scratch tree: the
        # model must read the result back, never rewrite what it "saw".
        self.result_directory = workspace_result_directory(self.base_dir)
        # Archived conversations (ADR 0015): same treatment and for the same reason -
        # the archive is the only record of what the model no longer sees, so it must
        # be readable and not editable.
        self.transcript_directory = workspace_transcript_directory(self.base_dir)
        self.read_only_roots = (
            self.output_directory.as_posix(),
            self.result_directory.as_posix(),
            self.transcript_directory.as_posix(),
        )
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
            should_stop=self.should_stop,
            max_tokens=self.max_tokens,
            provider=self.provider,
            model=self.model,
            output_directory=self.output_directory,
            ledger=self.read_ledger,
            extra_read_roots=self.read_only_roots,
            # Bound as a method, not as the broker: the broker may not exist yet, and
            # whether anyone can be asked is a per-call question (ADR 0010 D1).
            ask_user=self.ask_user,
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
                category=spec.category,
                description_i18n=spec.description_i18n,
                always_confirm=spec.always_confirm,
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
        category: str = CATEGORY_OTHER,
        description_i18n: Optional[Mapping[str, ToolText]] = None,
        always_confirm: bool = False,
    ):
        """Register a new tool.

        ``permission`` is the confirmation kind (``agent/tools/permissions.py``).
        It defaults to ``none``, i.e. never confirmed, so a tool that touches the
        filesystem must say so explicitly. ``scopes`` narrows the answers the
        dialog may offer. ``preview`` is an optional side-effect free dry run used
        to fill in the confirmation dialog. ``category`` groups the tool in the
        admin page, and ``description_i18n`` is the display-only text for other
        languages; neither reaches the model. ``always_confirm`` asks even under
        ``auto_approve`` (ADR 0030).
        """
        self.tools[name] = {
            "function": function,
            "description": description,
            "parameters": parameters,
            "permission": permission or PERMISSION_NONE,
            "scopes": tuple(scopes or SCOPES),
            "preview": preview,
            "category": category or CATEGORY_OTHER,
            "description_i18n": dict(description_i18n or {}),
            "always_confirm": bool(always_confirm),
        }

    def describe_tools(self) -> List[Dict[str, Any]]:
        """Metadata for every registered tool, without executing anything.

        This is the admin view rather than the model's view: it carries the
        permission gate and the implementing file, which no provider schema has a
        place for. It deliberately does not reuse :meth:`get_tool_schemas`, which
        speaks a provider's wire format.
        """
        return [
            {
                "name": name,
                "description": tool["description"],
                "parameters": self._schema_copy(tool["parameters"]),
                "permission": tool.get("permission") or PERMISSION_NONE,
                "scopes": list(tool.get("scopes") or ()),
                "has_preview": tool.get("preview") is not None,
                "source": _implementation_source(tool["function"]),
                "category": tool.get("category") or CATEGORY_OTHER,
                "description_i18n": {
                    locale: {
                        "description": text.description,
                        "parameters": dict(text.parameters),
                    }
                    for locale, text in (tool.get("description_i18n") or {}).items()
                },
            }
            for name, tool in self.tools.items()
        ]

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
        why the deny-list (ADR 0024) and the permission gate live here rather
        than inside the tools: coverage is then "all of them", including tools
        added later (ADR 0006 D1).

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

        blocked = self._denylist_denial(name, arguments)
        if blocked is not None:
            # Same shape as a refused confirmation, but a different layer and a
            # different title: this call was never a question.
            return ToolOutcome(
                model_text=blocked.model_text,
                event_category=EventCategory.PERMISSION_DECISION,
                event_title=f"Blocked by deny-list: {name}",
                details=blocked.details,
            )

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

        # Bracketed, not just recorded afterwards: the baseline has to exist before
        # the tool touches anything, and a tool that raises still changed the disk
        # (ADR 0020).
        store = self.checkpoint_store
        recording = store is not None and bool(self.task_id)
        if recording:
            store.begin(self.task_id, name, arguments)
        try:
            result = self.tools[name]["function"](**arguments)
        finally:
            if recording:
                store.end(self.task_id, name, arguments)
        if isinstance(result, ToolOutcome):
            return result
        return json.dumps(result) if isinstance(result, (dict, list)) else str(result)

    def ask_user(self, questions: Any) -> QuestionResult:
        """Ask the user through this run's broker, or say that nobody can be asked.

        The channel tools reach through ``ToolBindings.ask_user``. With no broker bound
        - a library caller, the CLI, a test - the answer is an explicit
        ``no_client`` result rather than an exception or a block: the model has to be
        told that its question went nowhere, but a run without a UI is not a failure
        (ADR 0010 D4).
        """
        broker = self.user_question_broker
        if broker is None:
            return QuestionResult(answers={}, status=STATUS_NO_CLIENT)
        return broker.ask(questions)

    def _denylist_denial(
        self, name: str, arguments: Dict[str, Any]
    ) -> Optional[PermissionDenial]:
        """Refuse a call the operator deny-listed (ADR 0024).

        Deliberately checked before the permission gate: a deny-listed call is
        not a question, so asking would imply "yes" is an answer the user could
        give.

        A deny-list that cannot be evaluated **denies** the call, for the same
        reason a broken permission broker does: this is a safety layer, and
        failing open would turn a configuration mistake into "everything runs".
        """
        try:
            matched = self.denylist.match(name, arguments)
        # Deliberately broad: see the fail-closed rule above.
        except Exception as exc:  # noqa: BLE001
            return PermissionDenial(
                model_text=(
                    f"The tool deny-list could not be evaluated for {name}: "
                    f"{exc.__class__.__name__}: {exc}\n"
                    "The call was blocked. This is a defect in the deny-list layer; "
                    "retrying the same call will not help."
                ),
                details={
                    "reason": REASON_DENYLIST_ERROR,
                    "tool": name,
                    "error": str(exc),
                    "allowed": False,
                },
            )
        if matched is None:
            return None
        reason = matched.reason or "this tool and argument combination is blocked by policy"
        return PermissionDenial(
            model_text=(
                f"Tool call blocked: {name} matches deny rule {matched.rule_id!r}.\n"
                f"reason: {reason}\n"
                "This call is disabled by policy. Do not retry it and do not look for "
                "a way around it; continue without it or ask the user what to do instead."
            ),
            details={
                "reason": REASON_DENYLIST,
                "tool": name,
                "rule": matched.rule_id,
                "matched_fields": list(matched.fields),
                "allowed": False,
            },
        )

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
                always_ask=self.tools[name].get("always_confirm", False),
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
    code_interpreter = staticmethod(_code_interpreter)

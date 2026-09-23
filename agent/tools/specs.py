"""Declarative specifications for the built-in tools.

Each :class:`ToolSpec` binds a model-facing name and JSON schema to the callable
that implements it. ``ToolRegistry`` consumes these specs, so adding a tool means
adding one entry here plus the implementation module next to it.

A new tool must also declare its ``permission`` kind. The default is ``"none"``,
which means "never ask the user" - correct for pure lookups, and a silent hole for
anything that touches the filesystem, so state the kind explicitly.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

from agent.tools import (
    edit_file,
    exec_command,
    read_file,
    write_file,
    write_stdin,
)
from agent.tools.code_interpreter import code_interpreter
from agent.tools.convert_currency import convert_currency
from agent.tools.get_current_temperature import get_current_temperature
from agent.tools.get_current_time import get_current_time
from agent.tools.permissions import (
    PERMISSION_EXEC,
    PERMISSION_NONE,
    PERMISSION_READ,
    PERMISSION_WRITE,
    SCOPE_ONCE,
    SCOPE_SESSION,
    SCOPES,
)
from agent.tools.read_ledger import ReadLedger


@dataclass(frozen=True)
class ToolSpec:
    """A single tool exposed to the language model."""

    name: str
    handler: Callable[..., Any]
    description: str
    parameters: Dict[str, Any]
    # Confirmation kind, see ``agent/tools/permissions.py``. ``none`` means the
    # gate lets the call through without asking.
    permission: str = PERMISSION_NONE
    # Which confirmation answers this tool accepts. A tool whose "always" rule
    # could never match again narrows it, and the dialog follows (ADR 0008).
    scopes: Sequence[str] = SCOPES
    # Optional dry run used to enrich the confirmation dialog: it receives the
    # call arguments and returns extra ``details`` (no side effects). A tool that
    # can cheaply describe what it is about to do should provide one.
    preview: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None


SPEC_GET_CURRENT_TEMPERATURE = ToolSpec(
    name="get_current_temperature",
    handler=get_current_temperature,
    description="Get the current temperature for a specific location",
    parameters={
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "The city and country, e.g., 'Paris, France'",
            },
            "unit": {
                "type": "string",
                "enum": ["celsius", "fahrenheit"],
                "description": "The temperature unit to use (by default, celsius)",
            },
        },
        "required": ["location", "unit"],
    },
)

SPEC_GET_CURRENT_TIME = ToolSpec(
    name="get_current_time",
    handler=get_current_time,
    description="Get the current date and time in a specific timezone",
    parameters={
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": (
                    "Timezone name (e.g., 'America/New_York', 'Europe/London', 'Asia/Tokyo'). "
                    "Use standard IANA timezone names."
                ),
                "default": "UTC",
            }
        },
        "required": [],
    },
)

SPEC_CONVERT_CURRENCY = ToolSpec(
    name="convert_currency",
    handler=convert_currency,
    description=(
        "Convert an amount from one currency to another. You MUST use this tool to convert "
        "currencies in order to get the latest exchange rate."
    ),
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "Amount to convert"},
            "from_currency": {
                "type": "string",
                "description": "Source currency code (e.g., 'USD', 'EUR')",
            },
            "to_currency": {
                "type": "string",
                "description": "Target currency code (e.g., 'USD', 'EUR')",
            },
        },
        "required": ["amount", "from_currency", "to_currency"],
    },
)

SPEC_CODE_INTERPRETER = ToolSpec(
    name="code_interpreter",
    handler=code_interpreter,
    description=(
        "Execute Python code for calculations and data processing. You MUST use this tool to "
        "perform any complex calculations or data processing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Python code to execute. Use Python operators: ** for exponentiation "
                    "(2 ** 10), not ^. In Python, ^ is bitwise XOR."
                ),
            }
        },
        "required": ["code"],
    },
    # Arbitrary code: this is one of the two tools that can reach anything on the
    # machine, which is why it is confirmed (ADR 0006 D2).
    permission=PERMISSION_EXEC,
)

READ_FILE_TOOL_NAME = "read_file"


def build_read_file_spec(
    base_dir: Optional[str] = None,
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
    ledger: Optional[ReadLedger] = None,
    extra_read_roots: Sequence[str] = (),
) -> ToolSpec:
    """Build the workspace scoped read tool, bound to a workspace root."""
    return ToolSpec(
        name=READ_FILE_TOOL_NAME,
        handler=read_file.make_read_file_tool(
            base_dir=base_dir,
            max_tokens=max_tokens,
            provider=provider,
            model=model,
            ledger=ledger,
            extra_read_roots=extra_read_roots,
        ),
        description=read_file.READ_FILE_DESCRIPTION,
        parameters=read_file.READ_FILE_PARAMETERS,
        # Reads are only confirmed for sensitive paths (ADR 0006 D3).
        permission=PERMISSION_READ,
    )


EDIT_FILE_TOOL_NAME = "edit_file"


def build_edit_file_spec(
    base_dir: Optional[str] = None,
    ledger: Optional[ReadLedger] = None,
    extra_read_roots: Sequence[str] = (),
) -> ToolSpec:
    """Build the workspace scoped edit tool, bound to a workspace root."""
    return ToolSpec(
        name=EDIT_FILE_TOOL_NAME,
        handler=edit_file.make_edit_file_tool(
            base_dir=base_dir, ledger=ledger, extra_read_roots=extra_read_roots
        ),
        description=edit_file.EDIT_FILE_DESCRIPTION,
        parameters=edit_file.EDIT_FILE_PARAMETERS,
        permission=PERMISSION_WRITE,
        # Shows the diff before the user decides (ADR 0006 D11).
        preview=edit_file.make_edit_preview(
            base_dir=base_dir, extra_read_roots=extra_read_roots
        ),
    )


WRITE_FILE_TOOL_NAME = "write_file"


def build_write_file_spec(
    base_dir: Optional[str] = None,
    ledger: Optional[ReadLedger] = None,
    extra_read_roots: Sequence[str] = (),
) -> ToolSpec:
    """Build the workspace scoped write tool, bound to a workspace root."""
    return ToolSpec(
        name=WRITE_FILE_TOOL_NAME,
        handler=write_file.make_write_file_tool(
            base_dir=base_dir, ledger=ledger, extra_read_roots=extra_read_roots
        ),
        description=write_file.WRITE_FILE_DESCRIPTION,
        parameters=write_file.WRITE_FILE_PARAMETERS,
        permission=PERMISSION_WRITE,
    )


EXEC_TOOL_NAME = exec_command.EXEC_TOOL_NAME


def build_exec_spec(
    base_dir: Optional[str] = None,
    session_id: str = "",
    max_tokens: int = 0,
    output_directory: Optional[Path] = None,
    task_id: str = "",
) -> ToolSpec:
    """Build the shell execution tool.

    The description is written for the shell this machine actually has, so the
    model is told which dialect to write in (see ``docs/decisions/0005-exec-tool.md``).
    ``task_id`` is stamped on every background session it starts, so the task that
    owns them can stop them when it ends.
    """
    return ToolSpec(
        name=EXEC_TOOL_NAME,
        handler=exec_command.make_exec_tool(
            base_dir=base_dir,
            session_id=session_id,
            max_tokens=max_tokens,
            output_directory=output_directory,
            task_id=task_id,
        ),
        description=exec_command.build_exec_description(),
        parameters=exec_command.EXEC_PARAMETERS,
        permission=PERMISSION_EXEC,
    )


WRITE_STDIN_TOOL_NAME = write_stdin.WRITE_STDIN_TOOL_NAME


def build_write_stdin_spec(
    max_tokens: int = 0,
    task_id: str = "",
    workspace: str = "",
    output_directory: Optional[Path] = None,
) -> ToolSpec:
    """Build the tool that types into a command ``exec_command`` left running.

    It shares the process store with ``exec_command``, which is what turns the
    ``session_id`` from a background command into something the model can talk to
    (see ``docs/decisions/0008-write-stdin-tool.md``). ``task_id``/``workspace`` bind
    it to the one task whose sessions it may touch.
    """
    return ToolSpec(
        name=WRITE_STDIN_TOOL_NAME,
        handler=write_stdin.make_write_stdin_tool(
            max_tokens=max_tokens,
            task_id=task_id,
            workspace=workspace,
            output_directory=output_directory,
        ),
        description=write_stdin.WRITE_STDIN_DESCRIPTION,
        parameters=write_stdin.WRITE_STDIN_PARAMETERS,
        # Typing into a live command is the same class of risk as running one.
        permission=PERMISSION_EXEC,
        # Its target is a random session id, so a persisted "always" rule could
        # never match again: offer once/session only (ADR 0008).
        scopes=(SCOPE_ONCE, SCOPE_SESSION),
    )


DEFAULT_TOOL_SPECS: Sequence[ToolSpec] = (
    SPEC_GET_CURRENT_TEMPERATURE,
    SPEC_GET_CURRENT_TIME,
    SPEC_CONVERT_CURRENCY,
    SPEC_CODE_INTERPRETER,
)

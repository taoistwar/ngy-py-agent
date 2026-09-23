"""The declarative shape of a tool, shared by every tool package.

Each tool contributes one of these from its own ``spec.py``; ``catalog`` collects
them and ``ToolRegistry`` turns them into provider schemas. The type lives here
rather than next to any one tool because a shared type does not belong inside one
of the things that share it (see ``AGENTS.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Sequence

from agent.tools.permissions import PERMISSION_NONE, SCOPES


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

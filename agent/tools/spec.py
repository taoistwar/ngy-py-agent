"""The declarative shape of a tool, shared by every tool package.

Each tool contributes one of these from its own ``spec.py``; ``catalog`` collects
them and ``ToolRegistry`` turns them into provider schemas. The type lives here
rather than next to any one tool because a shared type does not belong inside one
of the things that share it (see ``AGENTS.md``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from agent.tools.permissions import PERMISSION_NONE, SCOPES

# Categories group the tool list in the admin UI. Plain strings rather than an enum,
# so a tool can declare a new one without a migration; the page labels the ones it
# knows and falls back to the raw name for anything else.
CATEGORY_FILE = "file"
CATEGORY_SHELL = "shell"
CATEGORY_COMPUTER = "computer"
CATEGORY_COMPUTE = "compute"
CATEGORY_LOOKUP = "lookup"
CATEGORY_INTERACTION = "interaction"
CATEGORY_OTHER = "other"

CATEGORY_KINDS = (
    CATEGORY_FILE,
    CATEGORY_SHELL,
    CATEGORY_COMPUTER,
    CATEGORY_COMPUTE,
    CATEGORY_LOOKUP,
    CATEGORY_INTERACTION,
    CATEGORY_OTHER,
)

# Locales a tool may ship text for. One at a time, because each one is hand-written
# prose that has to be kept in step with the English source.
LOCALE_ZH_CN = "zh-CN"


@dataclass(frozen=True)
class ToolText:
    """One non-English language's text for a tool, for the admin page only.

    The model always gets the English ``description`` and ``parameters``: a
    translation stored in the schema would be sent to the provider on every
    request, and the model reads English fine. This is display text.
    """

    description: str
    # Parameter name -> text. Names must match ``ToolSpec.parameters``.
    parameters: Mapping[str, str] = field(default_factory=dict)


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
    # Which group the admin page lists the tool under (``CATEGORY_KINDS``).
    category: str = CATEGORY_OTHER
    # Locale -> text, for the admin page. Empty means "English only".
    description_i18n: Mapping[str, ToolText] = field(default_factory=dict)

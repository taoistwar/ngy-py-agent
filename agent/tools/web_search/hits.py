"""The one shape every backend reduces to: a titled, citable link.

Providers disagree about almost everything - key placement, request body, the
name of the results array, whether the snippet is called ``content`` or
``snippet`` - but they all answer the same question. Fixing that answer in one
small type is what lets the adapter layer stay a set of translations instead of
a set of tools: :mod:`agent.tools.web_search.tool` never learns which backend
answered.

Defined outside the adapters because both the adapters and the renderer need it,
and the adapters must not import the dispatcher that imports them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from agent.tools.web_search.limits import MAX_SNIPPET_CHARS, MAX_TITLE_CHARS


def clean_field(value: Any, limit: int) -> str:
    """Collapse whitespace and cap the length - fields come from someone's HTML."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "\u2026"


@dataclass(frozen=True)
class SearchHit:
    """One result: what it is called, where it points, why it matched."""

    title: str
    url: str
    snippet: str = ""

    @classmethod
    def build(cls, title: Any, url: Any, snippet: Any = "") -> Optional["SearchHit"]:
        """Normalize raw provider fields; ``None`` when there is no usable link."""
        target = str(url or "").strip()
        if not target.startswith(("http://", "https://")):
            return None
        return cls(
            title=clean_field(title, MAX_TITLE_CHARS) or target,
            url=target,
            snippet=clean_field(snippet, MAX_SNIPPET_CHARS),
        )

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}

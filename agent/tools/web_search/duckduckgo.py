"""The keyless default backend: DuckDuckGo's HTML endpoint.

It exists so the tool works without anyone signing up for an API: the agent
should be able to answer "what is the latest X" on a fresh checkout. The
endpoint is the no-JavaScript one (``html.duckduckgo.com``), which returns a
plain result list instead of an app shell.

Two things about it are deliberate:

* **The markup is parsed with the standard library**, by class name
  (``result__a`` / ``result__snippet``). No dependency, and the parser stops at
  the parts it needs instead of building a document tree.
* **Links are unwrapped.** DuckDuckGo rewrites every result through
  ``/l/?uddg=<encoded>``, so the URL the model would cite is the encoded one
  unless the wrapper is undone.

Being a scraped page, this backend can break when the markup changes, and it is
the one most likely to answer with a bot-check page. Both end in a reported
reason - never in a silent empty list.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import parse_qs, urlsplit

from agent.tools.web_search import http
from agent.tools.web_search.errors import WebSearchError
from agent.tools.web_search.hits import SearchHit
from agent.tools.web_search.query import SearchRequest

NAME = "duckduckgo"
ENDPOINT = "https://html.duckduckgo.com/html/"
SUPPORTS_DEPTH = False

_TITLE_CLASS = "result__a"
_SNIPPET_CLASS = "result__snippet"
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)
# Markers DuckDuckGo uses when it decides the caller is a robot.
_CHALLENGE_MARKERS = ("anomaly-modal", "anomaly.js", "challenge-form")


def unwrap(href: str) -> str:
    """The real target behind a result link, or ``""`` when it is not a web URL."""
    text = (href or "").strip()
    if text.startswith("//"):
        text = "https:" + text
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    if (parts.hostname or "").lower().endswith("duckduckgo.com") and parts.path.startswith("/l/"):
        target = (parse_qs(parts.query).get("uddg") or [""])[0]
        if target:
            text = target
    return text if text.startswith(("http://", "https://")) else ""


class _ResultParser(HTMLParser):
    """Collect ``(title, url, snippet)`` triples from a DuckDuckGo result page.

    The page lists each hit as an ``<a class="result__a">`` immediately followed
    by an ``<a class="result__snippet">``, so the snippet is attached to the hit
    collected last. Nested inline markup (``<b>`` around the matched words) is
    captured as text rather than ending the field early.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hits: List[SearchHit] = []
        self._kind: Optional[str] = None
        self._parts: List[str] = []
        self._href = ""
        self._depth = 0

    def handle_starttag(self, tag, attrs):  # noqa: N802 - the base class names it
        if self._kind is not None:
            if tag not in _VOID_TAGS:
                self._depth += 1
            return
        if tag != "a":
            return
        classes = (dict(attrs).get("class") or "").split()
        if _TITLE_CLASS in classes:
            self._begin("title", attrs)
        elif _SNIPPET_CLASS in classes:
            self._begin("snippet", attrs)

    def handle_startendtag(self, tag, attrs):  # noqa: N802 - the base class names it
        # ``<br/>`` inside a snippet: no text, no depth change.
        return

    def handle_endtag(self, tag):  # noqa: N802 - the base class names it
        if self._kind is None:
            return
        if self._depth == 0 and tag == "a":
            self._finish()
            return
        self._depth = max(0, self._depth - 1)

    def handle_data(self, data):
        if self._kind is not None:
            self._parts.append(data)

    def _begin(self, kind: str, attrs) -> None:
        self._kind = kind
        self._parts = []
        self._href = dict(attrs).get("href") or ""
        self._depth = 0

    def _finish(self) -> None:
        text = " ".join("".join(self._parts).split())
        kind = self._kind
        self._kind = None
        self._parts = []
        self._depth = 0

        if kind == "title":
            hit = SearchHit.build(text, unwrap(self._href))
            if hit is not None:
                self.hits.append(hit)
        elif kind == "snippet" and self.hits and text:
            last = self.hits[-1]
            self.hits[-1] = SearchHit(title=last.title, url=last.url, snippet=text)


def parse_results(markup: str) -> List[SearchHit]:
    """Every usable hit on the page, in the order DuckDuckGo ranked them."""
    parser = _ResultParser()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # noqa: BLE001 - a broken page yields what was parsed so far
        return parser.hits
    return parser.hits


def looks_like_challenge(markup: str) -> bool:
    """Whether the page is DuckDuckGo's "are you a robot" interstitial."""
    lowered = (markup or "").lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


def search(
    request: SearchRequest, *, endpoint: str, api_key: str, timeout: float
) -> List[SearchHit]:
    """Run one HTML search; ``api_key`` is unused and accepted for the common shape."""
    del api_key  # this backend needs no credentials
    markup = http.get_text(
        endpoint,
        params={"q": request.query, "kl": "wt-wt"},
        timeout=timeout,
    )
    hits = parse_results(markup)
    if not hits and looks_like_challenge(markup):
        raise WebSearchError(
            "DuckDuckGo answered with a bot check instead of results. Set "
            "WEB_SEARCH_PROVIDER and WEB_SEARCH_API_KEY to use an API provider "
            "(tavily, serper or bing) instead of retrying.",
            reason="provider_blocked",
            provider=NAME,
            url=endpoint,
        )
    return hits

"""What the model asked for, validated before any request leaves the machine.

The model is not a careful form filler: it passes a domain as ``https://``, a
port, a wildcard, the empty string, or the number of results as ``"10"``. None of
those deserve a failed step, so this module normalizes what can be normalized
and refuses only what cannot be turned into a sensible request - and the refusal
carries the ``reason`` the model can act on.

Two rules are hard, because a caller that breaks them is asking for something
contradictory rather than something merely untidy:

* ``allowed_domains`` and ``blocked_domains`` together are an error - "only from
  these" and "never from these" cannot both be honoured, and silently picking one
  would be a wrong answer that looks like a right one;
* a query shorter than :data:`~agent.tools.web_search.limits.MIN_QUERY_CHARS` is
  a keystroke, not a question.

Numbers are clamped instead of refused: a request for 100 results is a request
the tool can serve, at its own limit, and the receipt says how many it returned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence, Tuple
from urllib.parse import urlsplit

from agent.tools.web_search import limits
from agent.tools.web_search.errors import WebSearchError
from agent.tools.web_urls import host_of

SEARCH_TYPE_AUTO = "auto"
SEARCH_TYPE_FAST = "fast"
SEARCH_TYPE_DEEP = "deep"
SEARCH_TYPES = (SEARCH_TYPE_AUTO, SEARCH_TYPE_FAST, SEARCH_TYPE_DEEP)

_DOMAIN = re.compile(r"[a-z0-9]([a-z0-9._-]*[a-z0-9])?")


@dataclass(frozen=True)
class SearchRequest:
    """One validated search: the question plus every bound the caller set."""

    query: str
    num_results: int = limits.DEFAULT_NUM_RESULTS
    search_type: str = SEARCH_TYPE_AUTO
    allowed_domains: Tuple[str, ...] = field(default_factory=tuple)
    blocked_domains: Tuple[str, ...] = field(default_factory=tuple)
    context_max_characters: int = limits.DEFAULT_CONTEXT_MAX_CHARACTERS

    def allows(self, url: str) -> bool:
        """Whether a hit's URL survives the domain filters.

        A URL that cannot be parsed as an http(s) address is dropped: a result the
        model cannot open is not a result it can cite.
        """
        host = host_of(url)
        if not host:
            return False
        if self.allowed_domains and not any(
            domain_matches(host, domain) for domain in self.allowed_domains
        ):
            return False
        return not any(domain_matches(host, domain) for domain in self.blocked_domains)


def domain_matches(host: str, domain: str) -> bool:
    """``docs.example.com`` matches ``example.com``; ``notexample.com`` does not."""
    return host == domain or host.endswith("." + domain)


def _as_int(value: Any, *, default: int, maximum: int, argument: str) -> int:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        raise WebSearchError(
            f"'{argument}' must be a number.", reason="invalid_argument", argument=argument
        )
    try:
        number = int(str(value).strip()) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        raise WebSearchError(
            f"'{argument}' must be a number, got {value!r}.",
            reason="invalid_argument",
            argument=argument,
        ) from None
    return max(1, min(maximum, number))


def normalize_domain(value: Any) -> str:
    """Reduce anything that names a site to its bare, lowercase domain."""
    text = str(value or "").strip().lower()
    if "://" in text:
        try:
            text = (urlsplit(text).hostname or "").strip().lower()
        except ValueError:
            text = ""
    text = text.split("/", 1)[0].split(":", 1)[0].strip().strip(".")
    if text.startswith("*."):
        text = text[2:]
    if not text or not _DOMAIN.fullmatch(text):
        raise WebSearchError(
            f"{value!r} is not a domain; pass a bare host name such as 'example.com'.",
            reason="invalid_domain",
            domain=str(value or ""),
        )
    return text


def normalize_domains(value: Any, *, argument: str) -> Tuple[str, ...]:
    """Validate a domain filter argument; ``None``/empty means "no filter"."""
    if value is None:
        return ()
    if isinstance(value, str):
        values: Sequence[Any] = [value] if value.strip() else []
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        raise WebSearchError(
            f"'{argument}' must be a list of domain names.",
            reason="invalid_argument",
            argument=argument,
        )
    domains = []
    for item in values:
        domain = normalize_domain(item)
        if domain not in domains:
            domains.append(domain)
    return tuple(domains)


def _query_text(value: Any) -> str:
    if not isinstance(value, str):
        raise WebSearchError(
            "'query' must be a string.", reason="invalid_argument", argument="query"
        )
    text = " ".join(value.split())
    if len(text) < limits.MIN_QUERY_CHARS:
        raise WebSearchError(
            f"'query' is too short: give at least {limits.MIN_QUERY_CHARS} characters "
            "describing what to search for.",
            reason="invalid_query",
            query=text,
            min_chars=limits.MIN_QUERY_CHARS,
        )
    if len(text) > limits.MAX_QUERY_CHARS:
        raise WebSearchError(
            f"'query' is longer than {limits.MAX_QUERY_CHARS} characters; shorten it to "
            "the words that matter.",
            reason="invalid_query",
            query_length=len(text),
            max_chars=limits.MAX_QUERY_CHARS,
        )
    return text


def _search_type(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return SEARCH_TYPE_AUTO
    if not isinstance(value, str):
        raise WebSearchError(
            "'search_type' must be one of " + ", ".join(SEARCH_TYPES) + ".",
            reason="invalid_argument",
            argument="search_type",
        )
    text = value.strip().lower()
    if text not in SEARCH_TYPES:
        raise WebSearchError(
            f"'search_type' must be one of {', '.join(SEARCH_TYPES)}; got {value!r}.",
            reason="invalid_argument",
            argument="search_type",
            supported=list(SEARCH_TYPES),
        )
    return text


def parse_request(
    query: Any,
    allowed_domains: Any = None,
    blocked_domains: Any = None,
    num_results: Any = None,
    search_type: Any = None,
    context_max_characters: Any = None,
) -> SearchRequest:
    """Validate the model's arguments, or raise :class:`WebSearchError`."""
    text = _query_text(query)
    allowed = normalize_domains(allowed_domains, argument="allowed_domains")
    blocked = normalize_domains(blocked_domains, argument="blocked_domains")
    if allowed and blocked:
        raise WebSearchError(
            "'allowed_domains' and 'blocked_domains' cannot be combined: pass only one "
            "of them.",
            reason="conflicting_domain_filters",
        )

    limit = _as_int(
        num_results,
        default=limits.default_num_results(),
        maximum=limits.MAX_NUM_RESULTS,
        argument="num_results",
    )
    context = _as_int(
        context_max_characters,
        default=limits.DEFAULT_CONTEXT_MAX_CHARACTERS,
        maximum=limits.MAX_CONTEXT_MAX_CHARACTERS,
        argument="context_max_characters",
    )
    context = max(limits.MIN_CONTEXT_MAX_CHARACTERS, context)

    return SearchRequest(
        query=text,
        num_results=limit,
        search_type=_search_type(search_type),
        allowed_domains=allowed,
        blocked_domains=blocked,
        context_max_characters=context,
    )

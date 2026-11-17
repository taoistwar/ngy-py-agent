"""The backend table: pick one, call it, keep the hits that survive the filters.

Choosing a backend is configuration, not a model decision. The tool exposes one
``web_search`` to the model and the operator chooses where it goes with
``WEB_SEARCH_PROVIDER``; a model that had to pick would spend a call guessing
which of four names this deployment happens to have a key for.

The default is the keyless backend, so the tool works on a fresh checkout. A
provider that needs a key but has none is refused *before* a request is made,
with a message that names the variable to set - the alternative is a 401 the
model cannot act on.

Filtering happens here rather than in the adapters because it must be identical
for every backend: two providers support domain filters natively, the other two
ignore them, and "which sites come back" cannot depend on that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from agent.tools.web_search import duckduckgo, limits, search_apis
from agent.tools.web_search.errors import WebSearchError
from agent.tools.web_search.hits import SearchHit
from agent.tools.web_search.query import SearchRequest

SearchCallable = Callable[..., List[SearchHit]]


@dataclass(frozen=True)
class Provider:
    """One backend: where it lives, what it needs, and how it answers."""

    name: str
    endpoint: str
    needs_key: bool
    supports_depth: bool
    search: SearchCallable

    def missing_key_message(self) -> str:
        return (
            f"The '{self.name}' search provider needs an API key: set "
            f"{limits.API_KEY_ENV} (and optionally {limits.PROVIDER_ENV}={self.name}), "
            "or leave the provider unset to use the keyless default."
        )


PROVIDERS: Dict[str, Provider] = {
    duckduckgo.NAME: Provider(
        name=duckduckgo.NAME,
        endpoint=duckduckgo.ENDPOINT,
        needs_key=False,
        supports_depth=duckduckgo.SUPPORTS_DEPTH,
        search=duckduckgo.search,
    ),
    search_apis.TAVILY_NAME: Provider(
        name=search_apis.TAVILY_NAME,
        endpoint=search_apis.TAVILY_ENDPOINT,
        needs_key=True,
        supports_depth=True,
        search=search_apis.search_tavily,
    ),
    search_apis.SERPER_NAME: Provider(
        name=search_apis.SERPER_NAME,
        endpoint=search_apis.SERPER_ENDPOINT,
        needs_key=True,
        supports_depth=False,
        search=search_apis.search_serper,
    ),
    search_apis.BING_NAME: Provider(
        name=search_apis.BING_NAME,
        endpoint=search_apis.BING_ENDPOINT,
        needs_key=True,
        supports_depth=False,
        search=search_apis.search_bing,
    ),
}

SUPPORTED = tuple(PROVIDERS)


def resolve(name: str, api_key: str) -> Provider:
    """The provider to call, or a :class:`WebSearchError` saying why not."""
    text = (name or "").strip().lower()
    if not text:
        text = limits.DEFAULT_PROVIDER
    provider = PROVIDERS.get(text)
    if provider is None:
        raise WebSearchError(
            f"Unknown search provider {text!r}; supported providers are "
            f"{', '.join(SUPPORTED)}.",
            reason="unsupported_provider",
            provider=text,
            supported=list(SUPPORTED),
        )
    if provider.needs_key and not (api_key or "").strip():
        raise WebSearchError(
            provider.missing_key_message(),
            reason="missing_api_key",
            provider=provider.name,
            env=limits.API_KEY_ENV,
        )
    return provider


def run(
    provider: Provider,
    request: SearchRequest,
    *,
    endpoint: str,
    api_key: str,
    timeout: float,
) -> Tuple[List[SearchHit], int]:
    """Search once; return ``(kept, filtered_out)``.

    ``filtered_out`` counts hits the domain filter (or a duplicate URL) removed,
    so the tool can tell "nothing matched the query" from "your filter ate
    everything" - two situations that need different advice.
    """
    hits = provider.search(request, endpoint=endpoint, api_key=api_key, timeout=timeout)
    kept: List[SearchHit] = []
    seen = set()
    filtered = 0
    for hit in hits:
        if not request.allows(hit.url) or hit.url in seen:
            filtered += 1
            continue
        if len(kept) >= request.num_results:
            # Beyond the requested count is a cap, not a filter: do not report it
            # as results the domain filter removed.
            continue
        seen.add(hit.url)
        kept.append(hit)
    return kept, filtered


def endpoint_for(provider: Provider, override: Optional[str]) -> str:
    """The configured endpoint override, or the provider's own."""
    text = (override or "").strip()
    return text or provider.endpoint

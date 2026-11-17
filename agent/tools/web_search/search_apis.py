"""The three keyed backends: Tavily, Serper and Bing Web Search.

They are one module because they are the same thing three times - a documented
JSON API, a key, and a results array - and because keeping them side by side is
what makes the differences obvious (where the key goes, what the snippet field
is called, which one understands a search depth).

Each adapter's only job is translation:

* build the request the provider documents;
* pull ``title`` / ``url`` / ``snippet`` out of the array it documents;
* drop entries without a usable link (ads, "people also ask" blocks, empty rows)
  so the renderer never has to care.

A provider that answers with an unexpected shape yields an empty list rather
than an exception: a missing results array is not a transport failure, and the
tool reports "no results" honestly. A non-JSON body is a transport failure and
:mod:`agent.tools.web_search.http` raises ``bad_response`` for it.
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent.tools.web_search import http
from agent.tools.web_search.hits import SearchHit
from agent.tools.web_search.query import SEARCH_TYPE_DEEP, SearchRequest

TAVILY_NAME = "tavily"
TAVILY_ENDPOINT = "https://api.tavily.com/search"

SERPER_NAME = "serper"
SERPER_ENDPOINT = "https://google.serper.dev/search"

BING_NAME = "bing"
BING_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"


def _entries(payload: Any, key: str) -> List[Dict[str, Any]]:
    """The results array named ``key``, or an empty list on any other shape."""
    if not isinstance(payload, dict):
        return []
    raw = payload.get(key)
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _hits(entries: List[Dict[str, Any]], title: str, url: str, snippet: str) -> List[SearchHit]:
    hits: List[SearchHit] = []
    for entry in entries:
        hit = SearchHit.build(entry.get(title), entry.get(url), entry.get(snippet))
        if hit is not None:
            hits.append(hit)
    return hits


def search_tavily(
    request: SearchRequest, *, endpoint: str, api_key: str, timeout: float
) -> List[SearchHit]:
    """Tavily: the API the reference tool's default path uses (relevance-ranked)."""
    payload: Dict[str, Any] = {
        "api_key": api_key,
        "query": request.query,
        "max_results": request.num_results,
        "search_depth": "advanced" if request.search_type == SEARCH_TYPE_DEEP else "basic",
    }
    if request.allowed_domains:
        payload["include_domains"] = list(request.allowed_domains)
    if request.blocked_domains:
        payload["exclude_domains"] = list(request.blocked_domains)
    answer = http.post_json(endpoint, payload=payload, timeout=timeout)
    return _hits(_entries(answer, "results"), "title", "url", "content")


def search_serper(
    request: SearchRequest, *, endpoint: str, api_key: str, timeout: float
) -> List[SearchHit]:
    """Serper: Google's organic results behind a simple JSON endpoint."""
    payload: Dict[str, Any] = {"q": request.query, "num": request.num_results}
    answer = http.post_json(
        endpoint,
        payload=payload,
        headers={"X-API-KEY": api_key},
        timeout=timeout,
    )
    return _hits(_entries(answer, "organic"), "title", "link", "snippet")


def search_bing(
    request: SearchRequest, *, endpoint: str, api_key: str, timeout: float
) -> List[SearchHit]:
    """Bing Web Search: the key goes in a header and the count in the query string."""
    answer = http.get_json(
        endpoint,
        params={"q": request.query, "count": request.num_results},
        headers={"Ocp-Apim-Subscription-Key": api_key},
        timeout=timeout,
    )
    pages = answer.get("webPages") if isinstance(answer, dict) else None
    entries = pages.get("value") if isinstance(pages, dict) else None
    if not isinstance(entries, list):
        return []
    return _hits([item for item in entries if isinstance(item, dict)], "name", "url", "snippet")

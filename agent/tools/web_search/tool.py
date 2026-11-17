"""The ``web_search`` factory: validate, choose a backend, search, render, report.

The tool returns a **receipt**, because the model needs more than the list:

* ``provider`` and ``search_type_applied`` say how the answer was obtained, so a
  model that asked for ``deep`` knows when it did not get it;
* ``context_truncated`` / ``dropped_results`` say that the list is not everything
  the provider found - a model that assumes otherwise answers from a fraction of
  the evidence it thinks it has;
* ``duration_ms`` is what makes "the provider is slow" observable at all, given
  that the tool layer does not log.

A failure is returned, not raised: :class:`WebSearchError` is the only exception
caught here, and its payload is the same ``{"error", "reason", ...}`` shape the
file tools use, so the loop treats a missing API key like a missing file.

There is deliberately **no live-crawl / page-content option**, although the
reference tool has one. Fetching and extracting page text is ``web_fetch``'s job;
doing it again here would duplicate a whole subsystem (size caps, HTML
conversion, redirect rules) inside a second tool, and every duplicated rule is a
rule that can disagree with the first copy.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from agent.tools.web_search import limits, providers
from agent.tools.web_search.errors import WebSearchError
from agent.tools.web_search.query import SearchRequest, parse_request
from agent.tools.web_search.render import (
    FILTERED_OUT_TEXT,
    NO_RESULTS_TEXT,
    Rendered,
    fit_content,
    render_results,
)


def _base_receipt(
    request: SearchRequest,
    provider_name: str,
    *,
    duration_ms: int,
    filtered_out: int,
    search_type_applied: bool,
) -> Dict[str, Any]:
    return {
        "query": request.query,
        "provider": provider_name,
        "search_type": request.search_type,
        "search_type_applied": search_type_applied,
        "result_count": 0,
        "results": [],
        "filtered_out": filtered_out,
        "context_truncated": False,
        "dropped_results": 0,
        "content_truncated": False,
        "persisted_path": None,
        "duration_ms": duration_ms,
    }


def _empty_receipt(
    request: SearchRequest,
    provider_name: str,
    *,
    duration_ms: int,
    filtered_out: int,
    search_type_applied: bool,
) -> Dict[str, Any]:
    """Nothing to show: distinguish "no such thing" from "your filter ate it"."""
    receipt = _base_receipt(
        request,
        provider_name,
        duration_ms=duration_ms,
        filtered_out=filtered_out,
        search_type_applied=search_type_applied,
    )
    receipt["content"] = FILTERED_OUT_TEXT if filtered_out else NO_RESULTS_TEXT
    return receipt


def _filled_receipt(
    request: SearchRequest,
    provider_name: str,
    rendered: Rendered,
    *,
    duration_ms: int,
    filtered_out: int,
    search_type_applied: bool,
    max_tokens: int,
    token_provider: str,
    model: str,
    output_directory: Optional[Path],
) -> Dict[str, Any]:
    fitted = fit_content(
        rendered.content,
        max_tokens=max_tokens,
        provider=token_provider,
        model=model,
        directory=output_directory,
    )
    receipt = _base_receipt(
        request,
        provider_name,
        duration_ms=duration_ms,
        filtered_out=filtered_out,
        search_type_applied=search_type_applied,
    )
    receipt.update(
        {
            "result_count": len(rendered.hits),
            "results": [hit.to_dict() for hit in rendered.hits],
            "context_truncated": rendered.truncated,
            "dropped_results": rendered.dropped,
            **fitted,
        }
    )
    return receipt


def _web_search_impl(
    query: Any,
    *,
    allowed_domains: Any = None,
    blocked_domains: Any = None,
    num_results: Any = None,
    search_type: Any = None,
    context_max_characters: Any = None,
    max_tokens: int = 0,
    token_provider: str = "",
    model: str = "",
    output_directory: Optional[Path] = None,
    search_provider: str = "",
    api_key: Optional[str] = None,
    base_url: str = "",
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    request = parse_request(
        query,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
        num_results=num_results,
        search_type=search_type,
        context_max_characters=context_max_characters,
    )

    provider = providers.resolve(
        search_provider or limits.provider_name(),
        limits.api_key() if api_key is None else api_key,
    )
    endpoint = providers.endpoint_for(provider, base_url or limits.base_url())

    started = time.monotonic()
    hits, filtered_out = providers.run(
        provider,
        request,
        endpoint=endpoint,
        api_key=limits.api_key() if api_key is None else api_key,
        timeout=timeout if timeout else limits.timeout_seconds(),
    )
    elapsed = int((time.monotonic() - started) * 1000)

    if not hits:
        return _empty_receipt(
            request,
            provider.name,
            duration_ms=elapsed,
            filtered_out=filtered_out,
            search_type_applied=provider.supports_depth,
        )

    rendered = render_results(
        request.query,
        provider.name,
        hits,
        max_characters=request.context_max_characters,
    )
    return _filled_receipt(
        request,
        provider.name,
        rendered,
        duration_ms=elapsed,
        filtered_out=filtered_out,
        search_type_applied=provider.supports_depth,
        max_tokens=max_tokens,
        token_provider=token_provider,
        model=model,
        output_directory=output_directory,
    )


def make_web_search_tool(
    *,
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
    output_directory: Optional[Path] = None,
    timeout: Optional[float] = None,
    search_provider: str = "",
    api_key: Optional[str] = None,
    base_url: str = "",
):
    """Bind the search tool to one run's budget, tokenizer hints and scratch space.

    ``provider`` is the *model* provider (a tokenizer hint, as in ``web_fetch``);
    the search backend is ``search_provider``. The names stay apart because the
    two are unrelated, and a run always has both.
    """

    def web_search(
        query: Any,
        allowed_domains: Any = None,
        blocked_domains: Any = None,
        num_results: Any = None,
        search_type: Any = None,
        context_max_characters: Any = None,
    ) -> Dict[str, Any]:
        try:
            return _web_search_impl(
                query,
                allowed_domains=allowed_domains,
                blocked_domains=blocked_domains,
                num_results=num_results,
                search_type=search_type,
                context_max_characters=context_max_characters,
                max_tokens=max_tokens,
                token_provider=provider,
                model=model,
                output_directory=output_directory,
                search_provider=search_provider,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
            )
        except WebSearchError as exc:
            return exc.to_dict()

    return web_search

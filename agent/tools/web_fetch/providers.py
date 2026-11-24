"""The ``web_fetch`` backends: the local fetcher, or DeepSeek's Fetch API.

Choosing is configuration, not a model decision: the tool exposes one ``web_fetch``
to the model and the operator chooses where it goes. The default is the local
implementation, so a fresh checkout needs no credentials.

The two providers differ in more than transport. The local fetcher follows
same-host redirects itself and refuses to inherit approval for a different host;
DeepSeek fetches server-side, so it may follow redirects the local process cannot
see. That is a documented trade-off, not something an adapter can correct after
the fact.

A provider that needs a key but has none is refused *before* a request is made,
with a message that names the variable to set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from agent.tools.web_fetch import deepseek, limits
from agent.tools.web_fetch.errors import WebFetchError
from agent.tools.web_fetch.fetch import FetchedPage, fetch_page
from agent.tools.web_urls import FetchUrl

BUILTIN_NAME = "builtin"

FetchCallable = Callable[..., FetchedPage]


@dataclass(frozen=True)
class Provider:
    """One backend: where it lives, what it needs, and how it answers."""

    name: str
    endpoint: str
    needs_key: bool
    fetch: FetchCallable

    def missing_key_message(self) -> str:
        return (
            f"The '{self.name}' fetch provider needs an API key: set "
            f"{limits.API_KEY_ENV} (and optionally {limits.PROVIDER_ENV}={self.name}), "
            "or leave the provider unset to use the local fetcher."
        )


def _fetch_builtin(
    target: FetchUrl, *, endpoint: str, api_key: str, timeout: float
) -> FetchedPage:
    """The original implementation: request here, then convert locally."""
    del endpoint, api_key  # the local fetcher has neither
    return fetch_page(target, timeout)


PROVIDERS: Dict[str, Provider] = {
    BUILTIN_NAME: Provider(
        name=BUILTIN_NAME,
        endpoint="",
        needs_key=False,
        fetch=_fetch_builtin,
    ),
    deepseek.NAME: Provider(
        name=deepseek.NAME,
        endpoint=deepseek.ENDPOINT,
        needs_key=True,
        fetch=deepseek.fetch_page,
    ),
}

SUPPORTED = tuple(PROVIDERS)

# Accepted spellings that are not stored as-is: the settings page and the
# environment both funnel into one canonical id.
ALIASES = {deepseek.ALIAS: deepseek.NAME}


def canonical_name(name: Any) -> str:
    """The canonical backend id for ``name``; unknown names pass through unchanged."""
    text = str(name or "").strip().lower()
    return ALIASES.get(text, text)


def endpoint_for(provider: Provider, base_url: str) -> str:
    """The endpoint to call: the saved override, else the backend's own URL."""
    return (base_url or "").strip() or provider.endpoint


def resolve(name: str, api_key: str) -> Provider:
    """The provider to call, or a :class:`WebFetchError` saying why not."""
    text = canonical_name(name)
    if not text:
        text = limits.DEFAULT_PROVIDER
    provider = PROVIDERS.get(text)
    if provider is None:
        raise WebFetchError(
            f"Unknown fetch provider {text!r}; supported providers are "
            f"{', '.join(SUPPORTED)}.",
            reason="unsupported_provider",
            provider=text,
            supported=list(SUPPORTED),
        )
    if provider.needs_key and not (api_key or "").strip():
        raise WebFetchError(
            provider.missing_key_message(),
            reason="missing_api_key",
            provider=provider.name,
            env=limits.API_KEY_ENV,
        )
    return provider

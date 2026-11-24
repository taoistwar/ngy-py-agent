"""DeepSeek's Fetch API: the page is read on DeepSeek's side, returned as Markdown.

The local fetcher in :mod:`agent.tools.web_fetch.fetch` makes the request from
this process, which is what lets it see a cross-host redirect before following it.
A server-side fetch cannot offer that: the API follows redirects on its own, so
the permission decision covers the host that was requested, not wherever the
provider ended up. That trade-off is stated in the guide and ADR 0027 rather than
hidden here.

The API returns ``{"title", "content"}``, where ``content`` is Markdown intended
for a model. The shared pipeline still owns everything that happens next: empty
pages get the fixed message, large text is persisted by the output budget, and
HTTP errors are receipts rather than exceptions.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Tuple

import requests

from agent.tools.web_fetch.errors import WebFetchError
from agent.tools.web_fetch.fetch import FetchedPage, status_text
from agent.tools.web_fetch.limits import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    READ_CHUNK_BYTES,
    USER_AGENT,
)
from agent.tools.web_urls import FetchUrl

NAME = "deepseek"
# The feature is often called "deepsearch"; accept it without storing a second id.
ALIAS = "deepsearch"
ENDPOINT = "https://api.deepseek.com/v1/tools/fetch"

# Enough for the API's JSON error body; the useful sentence is at the start.
ERROR_BODY_BYTES = 4096
MAX_ERROR_CHARS = 400


def _headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def _raise_for_request_error(exc: Exception, url: str, timeout: float) -> None:
    """Translate a ``requests`` exception into a reason the model can act on."""
    if isinstance(exc, requests.exceptions.Timeout):
        raise WebFetchError(
            f"DeepSeek did not answer within {timeout:g} seconds.",
            reason="timeout",
            url=url,
            timeout_seconds=timeout,
            provider=NAME,
        ) from exc
    if isinstance(exc, requests.exceptions.SSLError):
        raise WebFetchError(
            f"The TLS certificate of the DeepSeek endpoint could not be verified: {exc}",
            reason="tls_error",
            url=url,
            provider=NAME,
        ) from exc
    if isinstance(exc, (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema)):
        raise WebFetchError(
            f"The DeepSeek endpoint is not usable: {exc}",
            reason="invalid_url",
            url=url,
            provider=NAME,
        ) from exc
    if isinstance(exc, requests.exceptions.ConnectionError):
        raise WebFetchError(
            f"Could not reach the DeepSeek endpoint: {exc}",
            reason="connection_failed",
            url=url,
            provider=NAME,
        ) from exc
    if isinstance(exc, requests.exceptions.RequestException):
        raise WebFetchError(
            f"The request to DeepSeek failed: {exc}",
            reason="request_failed",
            url=url,
            provider=NAME,
        ) from exc
    raise exc


def _read_body(response: requests.Response, limit: int) -> Tuple[bytes, bool]:
    """Return ``(body, truncated)``, stopping at ``limit`` bytes."""
    chunks = []
    total = 0
    for chunk in response.iter_content(READ_CHUNK_BYTES):
        if not chunk:
            continue
        room = limit - total
        if len(chunk) > room:
            chunks.append(chunk[:room])
            return b"".join(chunks), True
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), False


def _error_message(body: bytes) -> str:
    """The API's ``error.message``, else the raw body, flattened to one line."""
    text = body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                text = message
        elif isinstance(error, str) and error.strip():
            text = error
    return " ".join(text.split())[:MAX_ERROR_CHARS]


def _parse_content(body: bytes, url: str) -> Dict[str, Any]:
    """The decoded ``{"title", "content"}``, or an ``invalid_response`` receipt."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WebFetchError(
            f"DeepSeek returned a response that is not JSON: {exc}",
            reason="invalid_response",
            url=url,
            provider=NAME,
        ) from exc
    if not isinstance(payload, dict):
        raise WebFetchError(
            "DeepSeek returned JSON that is not an object.",
            reason="invalid_response",
            url=url,
            provider=NAME,
        )
    content = payload.get("content")
    if not isinstance(content, str):
        raise WebFetchError(
            "DeepSeek returned no 'content' field.",
            reason="invalid_response",
            url=url,
            provider=NAME,
        )
    title = payload.get("title")
    return {"content": content, "title": title if isinstance(title, str) else ""}


def fetch_page(target: FetchUrl, *, endpoint: str, api_key: str, timeout: float) -> FetchedPage:
    """Ask DeepSeek to fetch ``target`` and wrap the Markdown as a ``FetchedPage``."""
    started = time.monotonic()
    try:
        response = requests.post(
            endpoint,
            json={"url": target.url},
            headers=_headers(api_key),
            timeout=(min(CONNECT_TIMEOUT_SECONDS, timeout), timeout),
            stream=True,
        )
    except Exception as exc:  # noqa: BLE001 - mapped below, unknown types re-raised
        _raise_for_request_error(exc, target.url, timeout)

    with response:
        status = response.status_code
        reason = response.reason or status_text(status)
        if status >= 400:
            detail = _error_message(_read_body(response, ERROR_BODY_BYTES)[0])
            message = f"DeepSeek fetch answered {status} {reason}."
            if detail:
                message = f"{message} {detail}"
            raise WebFetchError(
                message,
                reason="http_error",
                url=target.url,
                code=status,
                code_text=reason,
                provider=NAME,
            )

        body, truncated = _read_body(response, MAX_RESPONSE_BYTES)
        if truncated:
            raise WebFetchError(
                f"The DeepSeek response exceeded the {MAX_RESPONSE_BYTES // (1024 * 1024)} MiB cap.",
                reason="response_too_large",
                url=target.url,
                provider=NAME,
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)

    payload = _parse_content(body, target.url)
    content = payload["content"]
    return FetchedPage(
        requested_url=target.url,
        url=target.url,
        status=status,
        reason=reason,
        content_type="text/markdown; charset=utf-8",
        body=content.encode("utf-8"),
        body_truncated=False,
        elapsed_ms=elapsed_ms,
        redirects=0,
        # A server-side fetch cannot tell us where it landed; the requested URL is
        # the only address we can honestly report.
        title=payload["title"],
        provider=NAME,
    )

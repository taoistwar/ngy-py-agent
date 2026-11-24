"""The HTTP half of ``web_fetch``: one bounded request, reported honestly.

Three rules shape this module:

* **Redirects are followed by hand**, not by ``requests``. The tool has to know
  where a redirect goes *before* it follows, because a hop to another host is a
  different site: it has not been approved by the user, so it is reported as
  ``redirect_to`` and the model fetches it as a second call (ADR 0027). Within one
  host, ``http`` -> ``https`` and ``/old`` -> ``/new`` are followed silently.
* **The body is capped while it is read.** A server that streams forever ends the
  call at :data:`~agent.tools.web_fetch.limits.MAX_RESPONSE_BYTES` with
  ``body_truncated`` set, instead of filling memory.
* **Every failure is a :class:`WebFetchError`** carrying a machine-readable
  ``reason``, so the model can tell "there is no such page" (404) from "the host
  is unreachable" (connection) from "the body was too large" (truncated).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Optional
from urllib.parse import urljoin

import requests

from agent.tools.web_fetch.errors import WebFetchError
from agent.tools.web_fetch.limits import (
    ACCEPT,
    ACCEPT_LANGUAGE,
    CONNECT_TIMEOUT_SECONDS,
    MAX_REDIRECTS,
    MAX_RESPONSE_BYTES,
    READ_CHUNK_BYTES,
    USER_AGENT,
)
from agent.tools.web_urls import FetchUrl, UrlError, parse_url, same_host


@dataclass(frozen=True)
class FetchedPage:
    """What one fetch produced, before the body is turned into text."""

    requested_url: str
    url: str
    status: int
    reason: str
    content_type: str
    body: bytes
    body_truncated: bool
    elapsed_ms: int
    redirects: int
    # Set when the server sent us to a different host; ``body`` is empty then.
    redirect_to: Optional[str] = None
    # A server-side backend may report the title separately from the body.
    title: str = ""
    # Which adapter produced this page, so the receipt can say so.
    provider: str = "builtin"


def status_text(status: int) -> str:
    """``200 -> OK``; an unknown status keeps an empty phrase rather than a guess."""
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return ""


def _headers() -> dict:
    return {
        "User-Agent": USER_AGENT,
        "Accept": ACCEPT,
        "Accept-Language": ACCEPT_LANGUAGE,
    }


def _raise_for_request_error(exc: Exception, url: str, timeout: float) -> None:
    """Translate a ``requests`` exception into a reason the model can act on."""
    if isinstance(exc, requests.exceptions.Timeout):
        raise WebFetchError(
            f"The request timed out after {timeout:g} seconds; the site may be slow or "
            "blocking automated requests.",
            reason="timeout",
            url=url,
            timeout_seconds=timeout,
        ) from exc
    if isinstance(exc, requests.exceptions.SSLError):
        raise WebFetchError(
            f"The TLS certificate could not be verified: {exc}",
            reason="tls_error",
            url=url,
        ) from exc
    if isinstance(exc, (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema)):
        raise WebFetchError(f"The URL is not usable: {exc}", reason="invalid_url", url=url) from exc
    if isinstance(exc, requests.exceptions.ConnectionError):
        raise WebFetchError(
            f"Could not connect to {url}: {exc}",
            reason="connection_failed",
            url=url,
        ) from exc
    if isinstance(exc, requests.exceptions.RequestException):
        raise WebFetchError(
            f"The request failed: {exc}", reason="request_failed", url=url
        ) from exc
    raise exc


def _read_body(response: requests.Response) -> tuple[bytes, bool]:
    """Return ``(body, truncated)``, stopping at the byte cap."""
    chunks: list = []
    total = 0
    for chunk in response.iter_content(READ_CHUNK_BYTES):
        if not chunk:
            continue
        room = MAX_RESPONSE_BYTES - total
        if len(chunk) > room:
            chunks.append(chunk[:room])
            return b"".join(chunks), True
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), False


def _location(response: requests.Response, current: FetchUrl) -> FetchUrl:
    """The target of a redirect, or a ``bad_redirect`` error."""
    raw = (response.headers.get("Location") or "").strip()
    if not raw:
        raise WebFetchError(
            f"The server answered {response.status_code} without a Location header.",
            reason="bad_redirect",
            url=current.url,
            code=response.status_code,
        )
    target = urljoin(response.url or current.url, raw)
    try:
        return parse_url(target)
    except UrlError as exc:
        raise WebFetchError(
            f"The redirect points at a URL this tool cannot fetch: {exc.message}",
            reason="bad_redirect",
            url=current.url,
            location=target,
            code=response.status_code,
        ) from exc


def fetch_page(target: FetchUrl, timeout: float) -> FetchedPage:
    """Fetch ``target``, following same-host redirects only."""
    session = requests.Session()
    current = target
    started = time.monotonic()
    try:
        for hop in range(MAX_REDIRECTS + 1):
            if time.monotonic() - started > timeout:
                raise WebFetchError(
                    f"The fetch did not finish within {timeout:g} seconds.",
                    reason="timeout",
                    url=current.url,
                    timeout_seconds=timeout,
                )
            try:
                response = session.get(
                    current.url,
                    headers=_headers(),
                    timeout=(min(CONNECT_TIMEOUT_SECONDS, timeout), timeout),
                    allow_redirects=False,
                    stream=True,
                )
            except Exception as exc:  # noqa: BLE001 - mapped below, unknown types re-raised
                _raise_for_request_error(exc, current.url, timeout)

            try:
                if response.is_redirect:
                    next_target = _location(response, current)
                    if not same_host(current, next_target):
                        return FetchedPage(
                            requested_url=target.url,
                            url=current.url,
                            status=response.status_code,
                            reason=response.reason or status_text(response.status_code),
                            content_type=response.headers.get("Content-Type", ""),
                            body=b"",
                            body_truncated=False,
                            elapsed_ms=int((time.monotonic() - started) * 1000),
                            # The hop just seen counts, even though it was not taken.
                            redirects=hop + 1,
                            redirect_to=next_target.url,
                        )
                    current = next_target
                    continue

                status = response.status_code
                reason = response.reason or status_text(status)
                if status >= 400:
                    raise WebFetchError(
                        f"The server answered {status} {reason}.",
                        reason="http_error",
                        url=current.url,
                        code=status,
                        code_text=reason,
                        content_type=response.headers.get("Content-Type", ""),
                    )
                try:
                    body, truncated = _read_body(response)
                except requests.exceptions.RequestException as exc:
                    raise WebFetchError(
                        f"The connection dropped while reading the response from {current.url}: {exc}",
                        reason="connection_failed",
                        url=current.url,
                        code=status,
                    ) from exc
                return FetchedPage(
                    requested_url=target.url,
                    url=response.url or current.url,
                    status=status,
                    reason=reason,
                    content_type=response.headers.get("Content-Type", ""),
                    body=body,
                    body_truncated=truncated,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    redirects=hop,
                )
            finally:
                response.close()

        raise WebFetchError(
            f"More than {MAX_REDIRECTS} redirects; the page never settles on a URL.",
            reason="too_many_redirects",
            url=current.url,
            max_redirects=MAX_REDIRECTS,
        )
    finally:
        session.close()

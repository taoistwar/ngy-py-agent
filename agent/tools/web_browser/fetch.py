"""The HTTP half of ``web_browser``: one bounded navigation, reported honestly.

This is a *separate* stack from ``web_fetch``'s on purpose (a tool package may not
import another tool package, see ``agent/tools/__init__.py``), and the rules it
follows are the ones that tool settled:

* **redirects are walked by hand**, so the tool knows where a hop goes *before* it
  follows. A hop to another host is a different site that the user has not approved,
  so it comes back as ``redirect_to`` and the model opens it as a second call;
* **the body is capped while it is read**, so a page that never ends cannot fill
  memory;
* **every failure is a :class:`~agent.tools.web_browser.errors.WebBrowserError`**
  with a machine-readable ``reason``, because "404" and "the host is unreachable"
  call for different next steps.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Optional
from urllib.parse import urljoin

import requests

from agent.tools.web_browser.errors import WebBrowserError
from agent.tools.web_browser.limits import (
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
class BrowsedPage:
    """What one navigation produced, before the body is turned into text."""

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
        raise WebBrowserError(
            f"The page did not answer within {timeout:g} seconds; the site may be slow "
            "or blocking automated requests.",
            reason="timeout",
            url=url,
            timeout_seconds=timeout,
        ) from exc
    if isinstance(exc, requests.exceptions.SSLError):
        raise WebBrowserError(
            f"The TLS certificate could not be verified: {exc}", reason="tls_error", url=url
        ) from exc
    if isinstance(exc, (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema)):
        raise WebBrowserError(f"The URL is not usable: {exc}", reason="invalid_url", url=url) from exc
    if isinstance(exc, requests.exceptions.ConnectionError):
        raise WebBrowserError(
            f"Could not connect to {url}: {exc}", reason="connection_failed", url=url
        ) from exc
    if isinstance(exc, requests.exceptions.RequestException):
        raise WebBrowserError(f"The request failed: {exc}", reason="request_failed", url=url) from exc
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
        raise WebBrowserError(
            f"The server answered {response.status_code} without a Location header.",
            reason="bad_redirect",
            url=current.url,
            code=response.status_code,
        )
    target = urljoin(response.url or current.url, raw)
    try:
        return parse_url(target)
    except UrlError as exc:
        raise WebBrowserError(
            f"The redirect points at a URL this tool cannot open: {exc.message}",
            reason="bad_redirect",
            url=current.url,
            location=target,
            code=response.status_code,
        ) from exc


def open_page(target: FetchUrl, timeout: float) -> BrowsedPage:
    """Open ``target``, following same-host redirects only."""
    session = requests.Session()
    current = target
    started = time.monotonic()
    try:
        for hop in range(MAX_REDIRECTS + 1):
            if time.monotonic() - started > timeout:
                raise WebBrowserError(
                    f"The page did not load within {timeout:g} seconds.",
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
                        return BrowsedPage(
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
                    raise WebBrowserError(
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
                    raise WebBrowserError(
                        f"The connection dropped while reading the page from {current.url}: {exc}",
                        reason="connection_failed",
                        url=current.url,
                        code=status,
                    ) from exc
                return BrowsedPage(
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

        raise WebBrowserError(
            f"More than {MAX_REDIRECTS} redirects; the page never settles on a URL.",
            reason="too_many_redirects",
            url=current.url,
            max_redirects=MAX_REDIRECTS,
        )
    finally:
        session.close()

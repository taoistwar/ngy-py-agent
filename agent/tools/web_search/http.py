"""One bounded HTTP request, with every failure turned into a reason.

The backends differ only in how they are *called* and how their answer is
*shaped*; the request itself is the same everywhere, so it lives here:

* **bounded** - a connect timeout, a total timeout and a body cap, so a wrong
  endpoint cannot hang the loop or stream a gigabyte into memory;
* **decoded here** - a backend hands back text or parsed JSON, never a
  ``requests`` object, so an adapter contains no transport code at all;
* **failures are :class:`WebSearchError`** carrying a machine-readable
  ``reason``: the model can tell "no key" from "429" from "the answer was not
  JSON", and each of those changes what it does next.

Redirects are followed (``requests`` default). Unlike ``web_fetch`` there is no
per-site approval to protect: the endpoint is fixed by configuration, the model
never supplies a URL, and the permission decision covers the service as a whole.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any, Dict, Optional, Tuple

import requests

from agent.tools.text_encoding import canonical_encoding, detect_bom
from agent.tools.web_search.errors import WebSearchError
from agent.tools.web_search.limits import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    READ_CHUNK_BYTES,
    USER_AGENT,
)

ACCEPT = "application/json, text/html;q=0.9, */*;q=0.5"

# How much of a failing response body is worth echoing to the model.
ERROR_BODY_CHARS = 400


def status_text(status: int) -> str:
    """``429 -> Too Many Requests``; an unknown status keeps an empty phrase."""
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return ""


def _headers(extra: Optional[Dict[str, str]]) -> Dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": ACCEPT,
        "Accept-Language": "en-US,en;q=0.9",
    }
    headers.update(extra or {})
    return headers


def _raise_for_request_error(exc: Exception, url: str, timeout: float) -> None:
    """Translate a ``requests`` exception into a reason the model can act on."""
    if isinstance(exc, requests.exceptions.Timeout):
        raise WebSearchError(
            f"The search request timed out after {timeout:g} seconds; the provider "
            "may be slow or unreachable.",
            reason="timeout",
            url=url,
            timeout_seconds=timeout,
        ) from exc
    if isinstance(exc, requests.exceptions.SSLError):
        raise WebSearchError(
            f"The TLS certificate of the search endpoint could not be verified: {exc}",
            reason="tls_error",
            url=url,
        ) from exc
    if isinstance(exc, (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema)):
        raise WebSearchError(
            f"The configured search endpoint is not a usable URL: {exc}",
            reason="invalid_endpoint",
            url=url,
        ) from exc
    if isinstance(exc, requests.exceptions.ConnectionError):
        raise WebSearchError(
            f"Could not reach the search endpoint {url}: {exc}",
            reason="connection_failed",
            url=url,
        ) from exc
    if isinstance(exc, requests.exceptions.RequestException):
        raise WebSearchError(
            f"The search request failed: {exc}", reason="request_failed", url=url
        ) from exc
    raise exc


def _read_body(response: requests.Response) -> Tuple[bytes, bool]:
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


def _decode(body: bytes, content_type: str) -> str:
    """Decode a response body; a wrong guess must not fail an otherwise good answer."""
    bom = detect_bom(body)
    if bom is not None:
        bom_bytes, bom_encoding = bom
        return body[len(bom_bytes) :].decode(bom_encoding, errors="replace")

    hint = ""
    for part in (content_type or "").split(";")[1:]:
        key, _, value = part.partition("=")
        if key.strip().lower() == "charset":
            hint = value.strip().strip('"')
    if hint:
        try:
            return body.decode(canonical_encoding(hint))
        except (LookupError, UnicodeDecodeError):
            pass

    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("latin-1", errors="replace")


def fetch_text(
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float,
) -> str:
    """Perform one request and return its body as text; raise :class:`WebSearchError`."""
    session = requests.Session()
    try:
        try:
            response = session.request(
                method,
                url,
                params=params,
                json=json_body,
                data=data,
                headers=_headers(headers),
                timeout=(min(CONNECT_TIMEOUT_SECONDS, timeout), timeout),
                stream=True,
            )
        except Exception as exc:  # noqa: BLE001 - mapped below, unknown types re-raised
            _raise_for_request_error(exc, url, timeout)

        try:
            body, truncated = _read_body(response)
            text = _decode(body, response.headers.get("Content-Type", ""))
            status = response.status_code
            if status >= 400:
                raise WebSearchError(
                    f"The search provider answered {status} "
                    f"{response.reason or status_text(status)}.",
                    reason="http_error",
                    url=url,
                    code=status,
                    code_text=response.reason or status_text(status),
                    body=clean_error_body(text),
                )
            if truncated:
                # A cut JSON document cannot be parsed; say why instead of
                # reporting a confusing "not JSON" error.
                raise WebSearchError(
                    f"The search provider's answer exceeded {MAX_RESPONSE_BYTES} bytes "
                    "and was cut; check the configured endpoint.",
                    reason="response_too_large",
                    url=url,
                    max_bytes=MAX_RESPONSE_BYTES,
                )
            return text
        finally:
            response.close()
    finally:
        session.close()


def clean_error_body(text: str) -> str:
    """A short, single-line quote of an error page, safe to show the model."""
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= ERROR_BODY_CHARS:
        return collapsed
    return collapsed[: ERROR_BODY_CHARS - 1] + "\u2026"


def get_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float,
) -> Any:
    """GET ``url`` and parse the answer as JSON."""
    return _parse_json(fetch_text("GET", url, params=params, headers=headers, timeout=timeout), url)


def post_json(
    url: str,
    *,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    timeout: float,
) -> Any:
    """POST ``payload`` as JSON and parse the answer."""
    text = fetch_text("POST", url, json_body=payload, headers=headers, timeout=timeout)
    return _parse_json(text, url)


def get_text(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float,
) -> str:
    """GET ``url`` and return the body unchanged (the HTML backend needs this)."""
    return fetch_text("GET", url, params=params, headers=headers, timeout=timeout)


def _parse_json(text: str, url: str) -> Any:
    try:
        return json.loads(text)
    except ValueError as exc:
        raise WebSearchError(
            "The search provider did not answer with JSON; check the configured "
            f"endpoint ({url}).",
            reason="bad_response",
            url=url,
            body=clean_error_body(text),
        ) from exc

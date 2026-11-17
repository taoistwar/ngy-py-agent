"""The HTTP half of ``vault_http``: one request that never leaves the approved host.

Three rules shape this module, and all three are about the credential on board:

* **Redirects are not followed.** ``allow_redirects=False`` is the whole defence: a
  30x from the approved host usually points somewhere else, and following it would
  send the vault key to a host the user never approved. The 3xx is returned as the
  response and the tool explains it; the model can make a second, separately
  approved call.
* **The body is capped while it is read.** A server that streams forever ends the
  call at :data:`MAX_RESPONSE_BYTES` with ``truncated`` set, instead of filling
  memory with someone else's API.
* **Every failure is a :class:`~agent.tools.vault_http.errors.VaultHttpError`** with a
  machine-readable ``reason``, so "the host is unreachable" and "the endpoint said
  401" stay distinguishable.

``transport`` exists so tests can drive the tool without a network or a TLS
certificate; the default is :func:`_send_with_requests`. Its signature is the
protocol below - positional-or-keyword, returning a :class:`VaultResponse`.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Callable, Dict, Optional

import requests

from agent.tools.vault_http.errors import VaultHttpError

# Total wall clock for one request, overridable with VAULT_HTTP_TIMEOUT_SECONDS.
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_SECONDS = 120.0
TIMEOUT_ENV = "VAULT_HTTP_TIMEOUT_SECONDS"
CONNECT_TIMEOUT_SECONDS = 10.0

# Body bytes kept. An authenticated API answer is small; a 1 MiB cap is generous
# and still orders of magnitude below a context window.
MAX_RESPONSE_BYTES = 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024

# Plain and honest: the endpoint's operator can see what called it.
USER_AGENT = "ngy-py-agent-vault-http/0.1"
ACCEPT = "application/json, text/plain;q=0.9, */*;q=0.5"


@dataclass(frozen=True)
class VaultResponse:
    """What one request produced, before scrubbing and formatting."""

    status: int
    status_text: str
    headers: Dict[str, str]
    body: bytes
    truncated: bool
    elapsed_ms: int


Transport = Callable[..., VaultResponse]


def timeout_seconds() -> float:
    """The per-call timeout, overridable by ``VAULT_HTTP_TIMEOUT_SECONDS``."""
    raw = (os.getenv(TIMEOUT_ENV) or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    if value <= 0:
        return DEFAULT_TIMEOUT_SECONDS
    return min(value, MAX_TIMEOUT_SECONDS)


def status_text(status: int) -> str:
    """``200 -> OK``; an unknown status keeps an empty phrase rather than a guess."""
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return ""


def is_redirect(status: int) -> bool:
    return 300 <= int(status) < 400


def _read_body(response: requests.Response) -> tuple:
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


def _raise_for_request_error(exc: Exception, url: str, timeout: float) -> None:
    """Translate a ``requests`` exception into a reason the model can act on."""
    if isinstance(exc, requests.exceptions.Timeout):
        raise VaultHttpError(
            f"The request timed out after {timeout:g} seconds; the endpoint may be slow or "
            "blocking automated requests.",
            reason="timeout",
            url=url,
            timeout_seconds=timeout,
        ) from exc
    if isinstance(exc, requests.exceptions.SSLError):
        raise VaultHttpError(
            f"The TLS certificate could not be verified: {exc}", reason="tls_error", url=url
        ) from exc
    if isinstance(exc, (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema)):
        raise VaultHttpError(f"The URL is not usable: {exc}", reason="invalid_url", url=url) from exc
    if isinstance(exc, requests.exceptions.ConnectionError):
        raise VaultHttpError(
            f"Could not connect to {url}: {exc}", reason="connection_failed", url=url
        ) from exc
    if isinstance(exc, requests.exceptions.RequestException):
        raise VaultHttpError(f"The request failed: {exc}", reason="request_failed", url=url) from exc
    raise exc


def _send_with_requests(
    method: str,
    url: str,
    headers: Dict[str, str],
    body: Optional[bytes],
    timeout: float,
) -> VaultResponse:
    """Default transport: one request, no redirects, body read up to the cap."""
    session = requests.Session()
    started = time.monotonic()
    try:
        try:
            response = session.request(
                method,
                url,
                headers=headers,
                data=body,
                timeout=(min(CONNECT_TIMEOUT_SECONDS, timeout), timeout),
                # The credential is on this request; a followed redirect would hand it
                # to a host the user has not approved.
                allow_redirects=False,
                stream=True,
            )
        except Exception as exc:  # noqa: BLE001 - mapped below, unknown types re-raised
            _raise_for_request_error(exc, url, timeout)

        try:
            status = response.status_code
            text = response.reason or status_text(status)
            try:
                payload, truncated = _read_body(response)
            except requests.exceptions.RequestException as exc:
                raise VaultHttpError(
                    f"The connection dropped while reading the response from {url}: {exc}",
                    reason="connection_failed",
                    url=url,
                    status=status,
                ) from exc
            return VaultResponse(
                status=status,
                status_text=text,
                headers={str(key): str(value) for key, value in response.headers.items()},
                body=payload,
                truncated=truncated,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            response.close()
    finally:
        session.close()


def send_request(
    method: str,
    url: str,
    headers: Dict[str, str],
    body: Optional[bytes],
    *,
    timeout: Optional[float] = None,
    transport: Optional[Transport] = None,
) -> VaultResponse:
    """Send one request through ``transport`` (default: ``requests``)."""
    limit = timeout if timeout else timeout_seconds()
    sender = transport or _send_with_requests
    return sender(method, url, headers, body, limit)

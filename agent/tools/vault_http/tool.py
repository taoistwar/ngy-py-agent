"""The ``vault_http`` factory: validate, fetch the key, send, scrub, report.

The order is the whole design, and it does not change:

1. **Validate first** (:mod:`agent.tools.vault_http.arguments`) - a non-HTTPS URL or
   an unknown argument fails before the vault is even opened.
2. **Read the secret last** and hold it in one local variable. It is never logged,
   never put in a result field, and never kept on the returned closure's attributes.
3. **Send** one request that does not follow redirects
   (:mod:`agent.tools.vault_http.request`).
4. **Scrub** every form of the secret out of the body, the headers and any error text
   (:mod:`agent.tools.vault_http.scrub`).
5. **Report** a receipt: ``status`` / ``status_text`` / ``response_headers`` /
   ``body`` for an answer, ``{"error", "reason", ...}`` for a failure. A failure is
   returned rather than raised, so the loop does not mark the step as broken and
   teach the model to retry.

An HTTP error status (401, 403, 500...) is **not** a tool failure: the endpoint
answered, and its body is usually the explanation the model needs. Only a failure to
get an answer at all (no vault, no such key, no connection, no TLS, timeout) is
reported as ``error``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from agent.tools.vault_http.arguments import VaultCall, parse_call
from agent.tools.vault_http.auth import auth_headers
from agent.tools.vault_http.errors import VaultHttpError
from agent.tools.vault_http.render import decode_body, fit_body
from agent.tools.vault_http.request import (
    ACCEPT,
    USER_AGENT,
    VaultResponse,
    is_redirect,
    send_request,
    status_text,
)
from agent.tools.vault_http.scrub import scrub_headers, scrub_text, variants_of
from agent.tools.vault_store import VaultStore, VaultStoreError

REDIRECT_NOTE = (
    "\n\n[REDIRECT NOT FOLLOWED] The endpoint answered {status} and points at {location}. "
    "This tool never follows redirects, because the vault key would travel to a host "
    "the user has not approved. Make a separate call to the new URL if that is what "
    "you need, so it gets its own permission decision."
)

TRUNCATED_NOTE = (
    "\n\n[The response was cut at the size limit; the endpoint answered with more "
    "bytes than this tool reads.]"
)


def request_headers(call: VaultCall, secret: str) -> Dict[str, str]:
    """The headers of one call: framing, content type, then the credential.

    The credential is applied last on purpose: a ``custom`` header name that happens
    to collide with one of the defaults must win, or the user's configured auth would
    silently not be sent.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": ACCEPT,
    }
    if call.body is not None:
        headers["Content-Type"] = call.body_content_type
    headers.update(auth_headers(call.auth_scheme, secret, call.auth_header_name))
    return headers


def _header(headers: Dict[str, str], name: str) -> str:
    """Case-insensitive header lookup over a plain dict (``requests`` folds case)."""
    wanted = name.lower()
    for key, value in headers.items():
        if str(key).lower() == wanted:
            return str(value)
    return ""


def _receipt(call: VaultCall, response: VaultResponse, **extra: Any) -> Dict[str, Any]:
    receipt: Dict[str, Any] = {
        "url": call.target.url,
        "method": call.method,
        "vault_auth_key": call.vault_auth_key,
        "auth_scheme": call.auth_scheme,
        "status": response.status,
        "status_text": response.status_text or status_text(response.status),
        "bytes": len(response.body),
        "duration_ms": response.elapsed_ms,
        "response_truncated": response.truncated,
    }
    receipt.update(extra)
    return receipt


def _run(
    raw: Dict[str, Any],
    *,
    store: VaultStore,
    max_tokens: int,
    provider: str,
    model: str,
    output_directory: Optional[Path],
    timeout: Optional[float],
    transport: Any,
) -> Dict[str, Any]:
    call = parse_call(raw)
    secret = store.get(call.vault_auth_key)
    variants = variants_of(secret)

    def scrub(text: str) -> str:
        return scrub_text(text, variants)

    body = call.body.encode("utf-8") if call.body is not None else None
    try:
        response = send_request(
            call.method,
            call.target.url,
            request_headers(call, secret),
            body,
            timeout=timeout,
            transport=transport,
        )
    except VaultHttpError as exc:
        # A transport error message can quote the request it was building, so it goes
        # through the same scrubber as the response before the model sees it.
        raise exc.scrubbed(scrub) from None

    headers = scrub_headers(response.headers, variants)
    text, encoding = decode_body(response.body, _header(response.headers, "content-type"))
    text = scrub(text)
    if response.truncated:
        text += TRUNCATED_NOTE

    redirect_to = None
    if is_redirect(response.status):
        location = _header(response.headers, "location")
        # Resolved against the URL that was called, because a relative Location ("/login")
        # alone tells the model nothing it can act on. Resolving is not following.
        redirect_to = scrub(urljoin(call.target.url, location)) if location else None
        text += REDIRECT_NOTE.format(
            status=response.status, location=redirect_to or "(no Location header)"
        )

    fitted = fit_body(
        text,
        max_tokens=max_tokens,
        provider=provider,
        model=model,
        directory=output_directory,
    )
    return _receipt(
        call,
        response,
        response_headers=headers,
        encoding=encoding,
        redirect_to=redirect_to,
        **fitted,
    )


def make_vault_http_tool(
    *,
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
    output_directory: Optional[Path] = None,
    timeout: Optional[float] = None,
    vault: Optional[VaultStore] = None,
    transport: Any = None,
):
    """Bind the tool to one run's budget, tokenizer hints, scratch directory and vault."""
    store = vault if vault is not None else VaultStore()

    def vault_http(**arguments: Any) -> Dict[str, Any]:
        try:
            return _run(
                arguments,
                store=store,
                max_tokens=max_tokens,
                provider=provider,
                model=model,
                output_directory=output_directory,
                timeout=timeout,
                transport=transport,
            )
        except VaultHttpError as exc:
            return exc.to_dict()
        except VaultStoreError as exc:
            return exc.to_dict()

    return vault_http

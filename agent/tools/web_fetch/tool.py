"""The ``web_fetch`` factory: validate the URL, fetch, extract, fit, report.

The tool returns a **receipt** rather than a bare string, because the model needs
more than the text: "the site answered 302 and went to another host" and "the page
was cut at the size limit" are facts that change what it does next, and neither is
visible in the text itself. The layout follows the reference tool's receipt
(``code``, ``code_text``, ``bytes``, ``duration_ms``, ``url``), extended with the
fields this project's contract needs (``content_type``, ``encoding``, the persisted
path, and ``redirect_to``).

A failure is returned, not raised: :class:`WebFetchError` is the only exception
caught here, and its payload is the same ``{"error", "reason", ...}`` shape the
file tools use, so the loop treats a dead host like a missing file.

There is deliberately **no ``prompt`` argument**, although the reference tool has
one. Claude Code answers the prompt with a second, smaller model inside the tool;
here the agent loop already has the page text in its context, and a model call from
inside a tool would bypass the loop's usage accounting, rate limiting and
telemetry. The trade-off is that the model must draw its own conclusion from the
text - which is what it was going to do with the answer anyway. See ADR 0027.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from agent.tools.web_fetch.errors import WebFetchError
from agent.tools.web_fetch.extract import KIND_BINARY, Extracted, extract_content
from agent.tools.web_fetch.fetch import FetchedPage, fetch_page
from agent.tools.web_fetch.limits import timeout_seconds
from agent.tools.web_fetch.render import fit_content, save_binary
from agent.tools.web_urls import UrlError, parse_url

EMPTY_PAGE_TEXT = (
    "The page returned no readable text. It may render its content with JavaScript, "
    "require a login, or be empty; report that to the user instead of retrying."
)


def _receipt(page: FetchedPage, **extra: Any) -> Dict[str, Any]:
    receipt: Dict[str, Any] = {
        "url": page.url,
        "requested_url": page.requested_url,
        "code": page.status,
        "code_text": page.reason,
        "content_type": page.content_type,
        "bytes": len(page.body),
        "duration_ms": page.elapsed_ms,
        "redirected": page.redirects > 0,
        "response_truncated": page.body_truncated,
    }
    receipt.update(extra)
    return receipt


def _redirect_result(page: FetchedPage) -> Dict[str, Any]:
    target = page.redirect_to or ""
    return _receipt(
        page,
        content=(
            f"REDIRECT DETECTED: {page.url} answered {page.status} and points at a "
            f"different host: {target}\n"
            "That host has not been approved for this task, so the redirect was not "
            "followed. Fetch the new URL as a separate call if its content is needed."
        ),
        content_truncated=False,
        persisted_path=None,
        redirect_to=target,
    )


def _binary_result(
    page: FetchedPage,
    extracted: Extracted,
    directory: Optional[Path],
) -> Dict[str, Any]:
    path, error = save_binary(page.body, directory, extracted.media_type)
    size = f"{len(page.body):,} bytes"
    if path:
        content = (
            f"The fetched resource is binary ({extracted.media_type}, {size}) and was "
            f"saved unchanged at {path}. It cannot be shown as text; use "
            "code_interpreter to inspect the bytes, or ask the user how to proceed."
        )
    else:
        content = (
            f"The fetched resource is binary ({extracted.media_type}, {size}) and was "
            f"not saved ({error})."
        )
    return _receipt(
        page,
        content=content,
        content_truncated=False,
        persisted_path=path,
        media_type=extracted.media_type,
    )


def _text_result(
    page: FetchedPage,
    extracted: Extracted,
    *,
    max_tokens: int,
    provider: str,
    model: str,
    directory: Optional[Path],
) -> Dict[str, Any]:
    text = extracted.text
    if page.body_truncated:
        text += (
            "\n\n[The response was cut at the fetch size limit; the page is larger "
            "than this tool reads.]"
        )
    if not text.strip():
        return _receipt(
            page,
            content=EMPTY_PAGE_TEXT,
            content_truncated=False,
            persisted_path=None,
            title=extracted.title,
            media_type=extracted.media_type,
            encoding=extracted.encoding,
        )

    fitted = fit_content(
        text,
        max_tokens=max_tokens,
        provider=provider,
        model=model,
        directory=directory,
    )
    return _receipt(
        page,
        title=extracted.title,
        media_type=extracted.media_type,
        encoding=extracted.encoding,
        **fitted,
    )


def _web_fetch_impl(
    url: Any,
    *,
    max_tokens: int,
    provider: str,
    model: str,
    output_directory: Optional[Path],
    timeout: Optional[float],
) -> Dict[str, Any]:
    try:
        target = parse_url(url)
    except UrlError as exc:
        raise WebFetchError(exc.message, exc.reason, **exc.details) from None

    page = fetch_page(target, timeout=timeout if timeout else timeout_seconds())
    if page.redirect_to:
        return _redirect_result(page)

    extracted = extract_content(page)
    if extracted.kind == KIND_BINARY:
        return _binary_result(page, extracted, output_directory)
    return _text_result(
        page,
        extracted,
        max_tokens=max_tokens,
        provider=provider,
        model=model,
        directory=output_directory,
    )


def make_web_fetch_tool(
    *,
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
    output_directory: Optional[Path] = None,
    timeout: Optional[float] = None,
):
    """Bind the fetch tool to one run's budget, tokenizer hints and scratch directory."""

    def web_fetch(url: Any) -> Dict[str, Any]:
        try:
            return _web_fetch_impl(
                url,
                max_tokens=max_tokens,
                provider=provider,
                model=model,
                output_directory=output_directory,
                timeout=timeout,
            )
        except WebFetchError as exc:
            return exc.to_dict()

    return web_fetch

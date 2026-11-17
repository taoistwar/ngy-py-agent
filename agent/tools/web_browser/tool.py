"""The ``web_browser`` factory: validate, open, strip, cap, report.

The result is the reference tool's shape - ``title``, ``url`` (where the navigation
ended up) and ``content`` - plus the two fields this project insists on:
``truncated`` says the 50,000-character cap was hit, and ``content_truncated`` /
``persisted_path`` say the text was moved to a file to fit the output budget. A
reader that cannot see it is looking at a partial page should never have to guess.

A failed navigation keeps the reference's habit of naming the failure in ``title``
(``HTTP 404``, ``Error``) **and** carries ``error`` / ``reason``, because the loop
and the UI both need a machine-readable failure and a title alone is a guess.

``action`` is the reference's second parameter, kept as-is:

* ``navigate`` - open the page and return its text;
* ``screenshot`` - the same text, prefixed with a line saying that no pixels were
  captured. The reference tool has the same dead end; naming it is better than
  letting the model believe it took a picture.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from agent.tools.web_browser.errors import WebBrowserError
from agent.tools.web_browser.fetch import BrowsedPage, open_page
from agent.tools.web_browser.limits import (
    ACTION_SCREENSHOT,
    ACTIONS,
    DEFAULT_ACTION,
    timeout_seconds,
)
from agent.tools.web_browser.render import clamp, fit_content
from agent.tools.web_browser.snapshot import KIND_BINARY, Snapshot, snapshot_page
from agent.tools.web_urls import UrlError, parse_url

EMPTY_PAGE_TEXT = (
    "The page returned no readable text. It may render its content with JavaScript, "
    "require a login, or be empty; report that to the user instead of retrying."
)

SNAPSHOT_NOTICE = (
    "[Text snapshot: no visual screenshot was taken - this tool has no browser "
    "engine and only returns the page text.]"
)

BINARY_TEXT = (
    "The URL is not a text page ({media_type}, {size:,} bytes), so there is nothing to "
    "open as text. web_fetch saves such a body to disk if its bytes are needed."
)

REDIRECT_TEXT = (
    "REDIRECT DETECTED: {url} answered {code} and points at a different host: {target}. "
    "That host has not been approved for this task, so the redirect was not followed. "
    "Open the new URL as a separate call if its content is needed."
)


def _action_of(raw: Any) -> str:
    """Validate ``action``; an unknown value is a caller mistake, not a default."""
    if raw is None:
        return DEFAULT_ACTION
    if not isinstance(raw, str):
        raise WebBrowserError(
            "'action' must be a string; omit it to navigate.",
            reason="invalid_argument",
            argument="action",
            allowed=list(ACTIONS),
        )
    value = raw.strip().lower()
    if not value:
        return DEFAULT_ACTION
    if value not in ACTIONS:
        raise WebBrowserError(
            f"'action' must be one of {', '.join(ACTIONS)}; got {raw!r}.",
            reason="invalid_argument",
            argument="action",
            allowed=list(ACTIONS),
        )
    return value


def _failure(message: str, reason: str, *, title: str = "Error", url: str = "", **details: Any) -> Dict[str, Any]:
    """The result of a navigation that did not produce a page."""
    return {"error": message, "reason": reason, "title": title, "url": url, **details}


def _failure_from(exc: WebBrowserError, *, url: str = "") -> Dict[str, Any]:
    """A raised failure as a result, with the browser-style title."""
    details = dict(exc.details)
    reported_url = str(details.pop("url", "") or url)
    code = details.get("code")
    title = f"HTTP {code}" if exc.reason == "http_error" and code is not None else "Error"
    return _failure(exc.message, exc.reason, title=title, url=reported_url, **details)


def _redirect_result(page: BrowsedPage) -> Dict[str, Any]:
    target = page.redirect_to or ""
    return _failure(
        REDIRECT_TEXT.format(url=page.url, code=page.status, target=target),
        "cross_host_redirect",
        title="Redirected to another host",
        url=page.url,
        redirect_to=target,
        code=page.status,
    )


def _binary_result(page: BrowsedPage, snapshot: Snapshot) -> Dict[str, Any]:
    return _failure(
        BINARY_TEXT.format(media_type=snapshot.media_type, size=len(page.body)),
        "not_text",
        title=snapshot.media_type,
        url=page.url,
        media_type=snapshot.media_type,
        bytes=len(page.body),
    )


def _page_result(
    page: BrowsedPage,
    snapshot: Snapshot,
    *,
    action: str,
    max_tokens: int,
    provider: str,
    model: str,
    directory: Optional[Path],
) -> Dict[str, Any]:
    text = snapshot.text
    if page.body_truncated:
        text += (
            "\n\n[The response was cut at the fetch size limit; the page is larger "
            "than this tool reads.]"
        )
    if not text.strip():
        return {
            "title": snapshot.title,
            "url": page.url,
            "action": action,
            "content": EMPTY_PAGE_TEXT,
            "truncated": False,
            "content_truncated": False,
            "persisted_path": None,
        }

    if action == ACTION_SCREENSHOT:
        text = f"{SNAPSHOT_NOTICE}\n\n{text}"
    text, capped = clamp(text)
    fitted = fit_content(
        text,
        max_tokens=max_tokens,
        provider=provider,
        model=model,
        directory=directory,
    )
    return {
        "title": snapshot.title,
        "url": page.url,
        "action": action,
        "truncated": capped,
        **fitted,
    }


def _browse_impl(
    url: Any,
    *,
    action: Any,
    max_tokens: int,
    provider: str,
    model: str,
    output_directory: Optional[Path],
    timeout: Optional[float],
) -> Dict[str, Any]:
    chosen = _action_of(action)
    try:
        target = parse_url(url)
    except UrlError as exc:
        raise WebBrowserError(exc.message, exc.reason, **exc.details) from None

    page = open_page(target, timeout=timeout if timeout else timeout_seconds())
    if page.redirect_to:
        return _redirect_result(page)

    snapshot = snapshot_page(page)
    if snapshot.kind == KIND_BINARY:
        return _binary_result(page, snapshot)
    return _page_result(
        page,
        snapshot,
        action=chosen,
        max_tokens=max_tokens,
        provider=provider,
        model=model,
        directory=output_directory,
    )


def make_web_browser_tool(
    *,
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
    output_directory: Optional[Path] = None,
    timeout: Optional[float] = None,
):
    """Bind the browser tool to one run's budget, tokenizer hints and scratch directory."""

    def web_browser(url: Any, action: Any = DEFAULT_ACTION) -> Dict[str, Any]:
        try:
            return _browse_impl(
                url,
                action=action,
                max_tokens=max_tokens,
                provider=provider,
                model=model,
                output_directory=output_directory,
                timeout=timeout,
            )
        except WebBrowserError as exc:
            return _failure_from(exc, url=url if isinstance(url, str) else "")

    return web_browser

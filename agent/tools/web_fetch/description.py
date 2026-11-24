"""What the model is told about ``web_fetch``: its description and parameter schema.

Kept apart from the implementation so the contract can be read on its own. The
description is the place where the tool's omissions are stated out loud - no login,
no cross-host redirect following, no downloading - because a model that guesses
otherwise wastes a call and then a retry.
"""

from typing import Any, Dict

WEB_FETCH_DESCRIPTION = (
    "Fetch a web page and return its text. Only http and https URLs work, and only "
    "pages that need no login: a page behind authentication answers with a login page "
    "or an HTTP error, so report that to the user instead of retrying. "
    "HTML is converted to Markdown-style plain text (headings, lists, links, code "
    "blocks and table rows survive; scripts, styles and hidden elements are dropped). "
    "Plain text, JSON and XML come back unchanged. Any other content type (PDF, image, "
    "archive) is saved to a file in the run's scratch directory and the result names "
    "the path. "
    "Redirects to the same host are followed, at most five. A redirect to a different "
    "host is not followed: the result carries 'redirect_to' and you should fetch that "
    "URL in a separate call, so the new site gets its own permission decision. "
    "The deployment may use a server-side fetcher instead: it returns Markdown, handles "
    "redirects upstream, and does not save binary originals, so 'redirect_to' and a "
    "'persisted_path' for PDFs or images are absent then. "
    "The result reports 'code' and 'code_text' (the HTTP status), 'bytes', "
    "'duration_ms', 'content_type', 'encoding' and 'content'. When the text does not "
    "fit the output token budget it is written to a file and 'content' holds a preview "
    "plus 'persisted_path', which read_file reads back in slices. "
    "The first fetch from a host in a task asks the user for permission; later pages "
    "from the same host do not ask again."
)

WEB_FETCH_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": (
                "Absolute http:// or https:// URL of the page to read. URLs with an "
                "embedded user name or password are refused."
            ),
        },
    },
    "required": ["url"],
}

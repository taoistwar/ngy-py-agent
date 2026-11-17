"""What the model is told about ``web_browser``: its description and parameter schema.

Kept apart from the implementation so the contract can be read on its own. The
description states the omissions out loud - no JavaScript, no clicking, no
screenshot, no login - because a model that assumes otherwise wastes a call and
then a retry. It also names ``web_fetch`` once, so the choice between the two tools
is made from their descriptions instead of from trial and error.
"""

from typing import Any, Dict

WEB_BROWSER_DESCRIPTION = (
    "Open a web page and return its title, its final URL and its text - the way a "
    "text-only browser would show it. Only http and https URLs work, and only pages that "
    "need no login: a page behind authentication answers with a login page or an HTTP "
    "error, so report that to the user instead of retrying. "
    "It is not a real browser: the HTML is downloaded and the markup stripped, so it does "
    "not run JavaScript (a page that builds itself in the browser comes back empty or "
    "partial), and it cannot click, type, scroll or capture a visual screenshot. "
    "'action' is 'navigate' (default) to read the page, or 'screenshot' to get the same "
    "text preceded by a note that no pixels were captured. "
    "Scripts, styles, hidden elements and site chrome (nav/footer) are dropped, and the "
    "result is plain text rather than Markdown: list items keep a '- ' bullet, link "
    "targets and code fences do not survive. Use web_fetch instead when the structure "
    "matters, when the HTTP status / content type / encoding are needed, or when a "
    "non-text body should be saved to disk. "
    "Redirects to the same host are followed, at most five. A redirect to a different "
    "host is not followed: the result carries 'redirect_to' and you should open that URL "
    "in a separate call, so the new site gets its own permission decision. "
    "Text longer than 50,000 characters is cut and the content ends with '[truncated]'. "
    "When the text still does not fit the output token budget it is written to a file and "
    "'content' holds a preview plus 'persisted_path', which read_file reads back in slices. "
    "The result is 'title', 'url' (the final URL), 'action', 'content' and 'truncated'. A "
    "failure is 'error' plus 'reason', with 'title' set to 'HTTP 404' or 'Error'. "
    "The first page from a host in a task asks the user for permission; later pages from "
    "the same host do not ask again."
)

WEB_BROWSER_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": (
                "Absolute http:// or https:// URL of the page to open. URLs with an "
                "embedded user name or password are refused."
            ),
        },
        "action": {
            "type": "string",
            "enum": ["navigate", "screenshot"],
            "default": "navigate",
            "description": (
                "'navigate' (default) opens the page and returns its text. 'screenshot' "
                "returns the same text preceded by a note that this tool cannot capture a "
                "visual screenshot."
            ),
        },
    },
    "required": ["url"],
}

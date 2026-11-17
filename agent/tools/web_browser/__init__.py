"""The ``web_browser`` tool: open one page and show what it says.

The name is the promise and the limit. A caller says "open this URL" and gets the
three things a text-only browser shows: the title, the address it ended up on, and
the page's words. There is no rendering engine behind it - the page is downloaded,
the markup is stripped, and everything that only exists after JavaScript runs is
simply absent.

What it deliberately is **not**:

* not a real browser - no JavaScript, no clicks, no typing, no scrolling, and no
  pixel screenshot (``computer_observe`` is the tool for the desktop, and it does
  not render web pages either);
* not ``web_fetch`` - that tool reports the HTTP receipt (status, content type,
  encoding, byte counts), converts HTML to Markdown-style text with links and code
  fences intact, and saves non-text bodies to disk. This one is the plain reading
  view: title plus plain text, cut at a fixed character cap.

Both exist because the two shapes answer different questions, and a model that has
only the receipt-shaped tool spends a step interpreting fields it did not need.
The permission story is the same for both, though: ``read`` over a *host*, so the
first page from a site in a task asks the user and later pages from that host do
not (:data:`agent.tools.permissions.NETWORK_READ_TOOLS`).

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
Shared infrastructure stays at the package root: the URL rules
(:mod:`agent.tools.web_urls`) are used by the permission gate as well, and the
output budget and scratch directory come from :mod:`agent.tools.output_store` and
:mod:`agent.tools.token_budget`.
"""

from agent.tools.web_browser.description import WEB_BROWSER_DESCRIPTION, WEB_BROWSER_PARAMETERS
from agent.tools.web_browser.errors import WebBrowserError
from agent.tools.web_browser.tool import make_web_browser_tool

__all__ = [
    "WEB_BROWSER_DESCRIPTION",
    "WEB_BROWSER_PARAMETERS",
    "WebBrowserError",
    "make_web_browser_tool",
]

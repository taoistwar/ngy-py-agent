"""The ``web_fetch`` tool: read a web page as text, within bounds.

The model can already run a shell command, so "fetch a URL" is not new capability.
What this tool adds is a *predictable* answer: HTML goes in, Markdown-style text
comes out, and the receipt says what happened - the HTTP status, the size, how long
it took, and whether the text it shows is the whole page.

The bounds, all of them deliberate:

* **http and https only**, no credentials in the URL, no other scheme
  (:mod:`agent.tools.web_urls`);
* **same-host redirects only**, at most five; a hop to another host is reported as
  ``redirect_to`` so the new site needs its own approval
  (:mod:`~agent.tools.web_fetch.fetch`);
* **2 MiB of body**, cut while reading, with ``response_truncated`` saying so;
* **the output token budget**: a page too large for one result is written to the
  run's scratch directory and the model gets a preview plus the path
  (:mod:`~agent.tools.web_fetch.render`).

What it deliberately does not do, because the reference tool does and this project
does not need it: it does not answer a ``prompt`` with a second model (see
:mod:`~agent.tools.web_fetch.tool` and ADR 0027), and it does not follow a redirect
into a different site.

The implementation is configurable (:mod:`agent.tools.web_fetch.providers`): the
local fetcher above is the default, and ``deepseek`` delegates to DeepSeek's
server-side Fetch API, which returns Markdown. The redirect and raw-byte
guarantees describe the local fetcher; a server-side provider handles redirects
upstream and cannot return original PDF/image bytes.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The URL rules are shared with the permission gate and therefore live at the
package root (:mod:`agent.tools.web_urls`). This module re-exports the public
surface.
"""

from agent.tools.web_fetch.description import WEB_FETCH_DESCRIPTION, WEB_FETCH_PARAMETERS
from agent.tools.web_fetch.errors import WebFetchError
from agent.tools.web_fetch.tool import make_web_fetch_tool

__all__ = [
    "WEB_FETCH_DESCRIPTION",
    "WEB_FETCH_PARAMETERS",
    "WebFetchError",
    "make_web_fetch_tool",
]

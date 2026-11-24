"""The ``web_search`` tool: find pages, not read them.

The model can already reach the web two ways: ``exec_command`` (``curl``) and
``code_interpreter`` (``requests``). What neither gives is a *ranked answer* -
"here are the eight pages that discuss this, each with the sentence that matched"
- in one step, with the search service named in the permission dialog and the
result shaped so a citation can be written from it.

The shape of the tool, and why:

* **one backend, chosen by configuration** (:mod:`~agent.tools.web_search.providers`):
  a keyless default that works on a fresh checkout, and DeepSeek Search / Tavily /
  Serper / Bing when an operator sets a key. The model does not pick a provider; a
  parameter it cannot fill correctly is a step wasted.
* **snippets only, no page text** (:mod:`~agent.tools.web_search.tool`): reading a
  page is ``web_fetch``'s job, with its own size caps, HTML conversion and
  redirect rules. Fetching here too would mean two copies of those rules that can
  disagree.
* **every bound is reported** (:mod:`~agent.tools.web_search.render`): results
  dropped by ``context_max_characters``, results dropped by the domain filter, and
  results persisted because the list outgrew the token budget all say so. A model
  that believes it saw everything will answer as if it had.
* **failures are results** (:mod:`~agent.tools.web_search.errors`): a missing key,
  a bot check and a 500 come back as ``{"error", "reason", ...}``, the shape the
  file tools already use.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
This module re-exports the public surface; ``spec.py`` is what ``catalog`` calls.
"""

from agent.tools.web_search.description import WEB_SEARCH_DESCRIPTION, WEB_SEARCH_PARAMETERS
from agent.tools.web_search.errors import WebSearchError
from agent.tools.web_search.query import SearchRequest, parse_request
from agent.tools.web_search.tool import make_web_search_tool

__all__ = [
    "WEB_SEARCH_DESCRIPTION",
    "WEB_SEARCH_PARAMETERS",
    "SearchRequest",
    "WebSearchError",
    "make_web_search_tool",
    "parse_request",
]

"""What the model is told about ``web_search``: its description and parameter schema.

Kept apart from the implementation so the contract can be read on its own. The
description states the two things a model would otherwise get wrong: this tool
returns *links*, not page text (``web_fetch`` reads a page), and a search result
must be cited as a Markdown link when it is used in an answer.

It also says that the provider is configuration rather than a parameter: the
model cannot pick a backend, so there is no point in it trying.
"""

from typing import Any, Dict

WEB_SEARCH_DESCRIPTION = (
    "Search the web and return ranked results: a title, a URL and a snippet for each. "
    "It does not open the pages it finds - call web_fetch on a URL to read one. "
    "The backend is configured for this deployment (a keyless default, or an API "
    "provider such as DeepSeek Search, Tavily, Serper or Bing); it is not a tool argument. "
    "'allowed_domains' keeps only those sites and 'blocked_domains' removes them; the "
    "two cannot be combined and passing both is an error. A domain also covers its "
    "subdomains, so 'example.com' allows 'docs.example.com'. "
    "'num_results' defaults to 8 and is clamped to 20. 'search_type' is 'auto' "
    "(default), 'fast' or 'deep'; only some providers can honour it, and the result "
    "says via 'search_type_applied' whether they could. "
    "'context_max_characters' (default 10000) caps how much of the list is returned; "
    "results beyond it are dropped and 'context_truncated' reports how many. "
    "The result carries 'query', 'provider', 'result_count', 'results' (each with "
    "'title', 'url', 'snippet'), 'duration_ms' and 'content' - the same list as "
    "Markdown with links. A search that finds nothing returns 'result_count': 0 and a "
    "sentence saying so; that is an answer, not an error, and repeating the same query "
    "will not help. "
    "When you use anything from these results, cite the source of each claim as a "
    "Markdown link. "
    "The first search in a task asks the user for permission; later searches in the "
    "same task do not ask again. Searching is read-only and safe to run in parallel."
)

WEB_SEARCH_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "What to search for. At least 2 characters; write it the way you would "
                "type it into a search box."
            ),
        },
        "allowed_domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Return results only from these sites, as bare domains such as "
                "'example.com' (subdomains included). Cannot be combined with "
                "'blocked_domains'."
            ),
        },
        "blocked_domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Never return results from these sites, as bare domains. Cannot be "
                "combined with 'allowed_domains'."
            ),
        },
        "num_results": {
            "type": "integer",
            "description": "How many results to return. Default 8; values above 20 are clamped to 20.",
        },
        "search_type": {
            "type": "string",
            "enum": ["auto", "fast", "deep"],
            "description": (
                "'auto' (default) balances speed and coverage, 'fast' asks for fewer "
                "results quickly, 'deep' asks for a more thorough search. Only the "
                "providers that support a depth setting honour it."
            ),
        },
        "context_max_characters": {
            "type": "integer",
            "description": (
                "Upper bound on the characters of the returned result list. Default "
                "10000; results beyond it are dropped and reported."
            ),
        },
    },
    "required": ["query"],
}

"""What the model is told about ``grep``: its description and parameter schema.

Kept apart from the implementation so the tool's contract can be read on its own.

The numbers here are the tool's whole safety story, so they are stated once and
imported everywhere else:

- ``DEFAULT_HEAD_LIMIT``: how much output one call may produce. ``0`` lifts it,
  which is the caller's explicit choice, not a default.
- ``MAX_COLUMNS``: a single very long line (minified bundle, base64 blob) must
  not become the whole result.
- ``MAX_FILE_BYTES`` / ``MAX_SCANNED_ENTRIES`` / ``MAX_DURATION_SECONDS``: what the
  scan refuses to do, so a search that cannot finish still returns.
"""

from typing import Any, Dict

DEFAULT_HEAD_LIMIT = 250
MAX_COLUMNS = 500
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_SCANNED_ENTRIES = 20_000
MAX_DURATION_SECONDS = 20.0

MODE_CONTENT = "content"
MODE_FILES = "files_with_matches"
MODE_COUNT = "count"
OUTPUT_MODES = (MODE_CONTENT, MODE_FILES, MODE_COUNT)

NO_MATCH_HINT = (
    "No matches found. Files excluded by .gitignore or by the tool's own skip list are not "
    "searched; widen 'path', 'glob' or 'type' (or point 'path' at a skipped directory)."
)
OFFSET_PAST_END_HINT = (
    "There are no results at this 'offset' - the search found fewer than 'offset' results, "
    "not none. Retry with a smaller 'offset'."
)
SKIPPED_ONLY_HINT = (
    "Only credential-like files were skipped (see 'skipped_sensitive'). Use read_file for "
    "them: it asks for confirmation instead of hiding their contents."
)
TRUNCATED_HINT = (
    "Results are truncated. Page with 'offset', raise 'head_limit', or narrow "
    "'path'/'glob'/'type'."
)

GREP_DESCRIPTION = (
    "Search file contents with a regular expression (Python 're' syntax, applied line by "
    "line). Three shapes of answer, chosen with 'output_mode': 'files_with_matches' "
    "(default) lists the files that contain a match, most recently modified first; "
    "'content' returns matching lines as 'path:line:text' plus any context lines "
    "('path-line-text', groups separated by '--'); 'count' returns 'path:count' per file "
    "(matching lines) and the total. Matching is line based unless 'multiline' is set, in "
    "which case the pattern may span lines (and 'context'/'line_numbers' then have no effect). "
    "What gets searched is what the repository calls source: hidden files are included, but "
    "files excluded by a .gitignore (read per directory, from the search root down), VCS "
    "metadata (.git and friends), installed dependencies and build output (node_modules, "
    ".venv, dist, build, target...), binary files, files over 8 MB, and credential-like files "
    "are skipped - the last ones are listed in 'skipped_sensitive' because read_file can still "
    "reach them. There is no switch to search ignored files; point 'path' at the directory "
    "instead. 'glob' and 'type' narrow which files are "
    "searched. At most 250 output lines/paths are returned; page with 'offset'/'head_limit' "
    "('head_limit': 0 means no limit) instead of widening the pattern, and note that long "
    "lines are cut at 500 characters. Paths are relative to the workspace root, so they can "
    "be passed to read_file unchanged. Use glob when you want a file by name, and grep when "
    "you are looking for where something is written."
)

GREP_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": (
                "Regular expression to search for (Python 're' syntax). Special characters "
                "must be escaped: use 'interface\\{\\}' to find 'interface{}'."
            ),
        },
        "path": {
            "type": "string",
            "description": (
                "File or directory to search, relative to the workspace root (absolute "
                "paths are accepted only when they stay inside the workspace). Defaults to "
                "the workspace root."
            ),
        },
        "glob": {
            "type": "string",
            "description": (
                "Only search files matching this pattern, e.g. '*.py' or '*.{ts,tsx}'. "
                "Several patterns may be given separated by commas or spaces."
            ),
        },
        "type": {
            "type": "string",
            "description": (
                "Only search one language's files, e.g. 'py', 'js', 'ts', 'rust', 'go', "
                "'java', 'json', 'yaml', 'markdown', 'sh'. An unknown name is rejected with "
                "the supported list."
            ),
        },
        "output_mode": {
            "type": "string",
            "enum": list(OUTPUT_MODES),
            "description": (
                "'files_with_matches' (default) for paths, 'content' for the matching lines, "
                "'count' for how many lines match in each file."
            ),
        },
        "case_insensitive": {
            "type": "boolean",
            "description": "Ignore case while matching. Defaults to false.",
        },
        "multiline": {
            "type": "boolean",
            "description": (
                "Let the pattern span lines ('.' also matches a newline, so 'struct "
                "\\{[\\s\\S]*?field' style searches work). Defaults to false."
            ),
        },
        "line_numbers": {
            "type": "boolean",
            "description": (
                "Prefix each 'content' line with its 1-based line number. Defaults to true; "
                "the other modes always report file level results, and 'multiline' matches "
                "always carry the line they start on."
            ),
        },
        "context": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "Lines of context before and after each match in 'content' mode. Overrides "
                "'before_context'/'after_context'; ignored when 'multiline' is set."
            ),
        },
        "before_context": {
            "type": "integer",
            "minimum": 0,
            "description": "Lines of context before each match in 'content' mode.",
        },
        "after_context": {
            "type": "integer",
            "minimum": 0,
            "description": "Lines of context after each match in 'content' mode.",
        },
        "head_limit": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "Maximum number of output lines (content), paths (files_with_matches) or "
                "counts (count). Defaults to 250; 0 removes the limit."
            ),
        },
        "offset": {
            "type": "integer",
            "minimum": 0,
            "description": "Skip this many results first, to page through a long answer.",
        },
    },
    "required": ["pattern"],
}

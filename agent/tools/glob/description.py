"""What the model is told about ``glob``: its description and parameter schema.

Kept apart from the implementation so the tool's contract can be read on its own.
"""

from typing import Any, Dict

# Hard ceiling on returned paths. A listing is discovery, not a dump: past this
# the model is better served by a narrower pattern or a deeper ``path`` than by
# more names to read through. The walk's own ceiling is
# ``agent.tools.file_walk.MAX_SCANNED_ENTRIES``, shared with ``grep``.
MAX_RESULTS = 100

# Why the results stop: one text for "more matched than we return", one for "we
# stopped looking". They are different problems and need different fixes.
TRUNCATED_HINT = (
    "Only the newest matches are returned. Use a more specific 'pattern' or a narrower "
    "'path' to see the rest."
)
SCAN_TRUNCATED_HINT = (
    "The search stopped before finishing because the tree is large. Narrow 'path' or use a "
    "more specific 'pattern'."
)

GLOB_DESCRIPTION = (
    "List files by name pattern, recursively. One call searches the whole subtree below "
    "'path': a bare '*' already returns every file at every depth and '**/*' is the same "
    "query, so ask one question per call - never send both '*' and '**/*', and never repeat "
    "a call with a variant of the same pattern. 'path' is a starting point, not a depth "
    "limit; only a pattern that names a level ('src/*') stops at that level. Use it to "
    "answer \"which files are here\", to find a file whose name you know but whose folder "
    "you do not, and before read_file instead of guessing at a path. Only regular files come "
    "back, never directories, so an empty 'filenames' means no matching file - not that the "
    "folder is missing. At most 100 paths are returned: project source first, installed "
    "dependencies and build output last, each group newest first; 'truncated' means the list "
    "is incomplete, so narrow 'path' or make 'pattern' more specific instead of paging. "
    "Patterns follow ripgrep's --glob: '*' matches within one path segment, '**' spans "
    "segments ('a/**/b' also matches 'a/b'), '?' matches one character, '[abc]' is a "
    "character class and '{a,b}' a list of alternatives; a pattern with no '/' matches the "
    "file name at any depth. Hidden files and files excluded by .gitignore are listed on "
    "purpose. Paths resolve against the workspace root and can never escape it; the global "
    "allow/deny policy still hides what it blocks. Returned paths are relative to the "
    "workspace root (absolute when outside it), so pass them to read_file unchanged. An "
    "absolute 'pattern' carries its own root and overrides 'path'."
)

GLOB_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": (
                "Glob pattern for the file names to find: '*' for every file at every depth, "
                "'*.py' for every Python file, 'src/*.py' to stay one level below 'src/'. "
                "'**', '*', '?', '[...]' and '{a,b}' behave as described above, and a "
                "pattern with no '/' is matched against the file name at any depth."
            ),
        },
        "path": {
            "type": "string",
            "description": (
                "Directory to start from, relative to the workspace root (absolute paths are "
                "accepted only when they stay inside the workspace). Defaults to the "
                "workspace root. The search below it is recursive, so a pattern like "
                "'src/*' is how you keep it to one level."
            ),
        },
    },
    "required": ["pattern"],
}

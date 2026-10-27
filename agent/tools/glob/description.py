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
    "Find files by name pattern. Use it when you know what a file is called but not where it "
    "lives, and before read_file when you would otherwise guess at a path. Returns the "
    "matching file paths, at most 100 of them, project source first and installed "
    "dependencies or build output last (each newest first); 'truncated' "
    "means the list is incomplete, so narrow 'path' or make the 'pattern' more specific "
    "instead of trying to page. Patterns follow ripgrep's --glob: '*' matches within one "
    "path segment, '**' spans segments ('a/**/b' also matches 'a/b'), '?' matches one "
    "character, '[abc]' is a character class and '{a,b}' is a list of alternatives. A "
    "pattern without '/' is matched against the file name at any depth, so '*.py' finds "
    "every Python file below the search root. Hidden files and files excluded by "
    ".gitignore are included on purpose, and only regular files are returned - never "
    "directories. Paths resolve against the workspace root and can never escape it; the "
    "global allow/deny policy still hides what it blocks. Returned paths are relative to "
    "the workspace root (or absolute when outside it), so pass them to read_file unchanged. "
    "An absolute 'pattern' carries its own root and overrides 'path'."
)

GLOB_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": (
                "Glob pattern describing the file names to find, e.g. '**/*.ts' or "
                "'src/**/test_*.py'. Support for '**', '*', '?', '[...]' and '{a,b}' as "
                "described above."
            ),
        },
        "path": {
            "type": "string",
            "description": (
                "Directory to search, relative to the workspace root (absolute paths are "
                "accepted only when they stay inside the workspace). Defaults to the "
                "workspace root."
            ),
        },
    },
    "required": ["pattern"],
}

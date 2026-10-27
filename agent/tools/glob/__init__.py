"""The ``glob`` tool: find files by name pattern, workspace scoped.

The model knows what a file is called long before it knows which folder it is in,
and guessing at paths is how a read turns into a "file not found". This tool is
the answer to "where is it": give it a pattern, get back paths that ``read_file``
accepts verbatim.

The bounds are the same kind the read tool uses, for the same reason - a single
call must not be able to flood the context or hang the loop:

- the search root resolves through ``file_access``, so a search is confined
  exactly like a read (workspace, or an extra read root, never past the policy);
- at most ``MAX_RESULTS`` (100) paths come back, with ``truncated`` telling the
  model the list is incomplete;
- the walk stops after ``MAX_SCANNED_ENTRIES`` entries and reports that too.

Nothing is filtered implicitly: hidden files, ``.gitignore``-excluded files and
``node_modules`` are all listed, because "where is this file" has to work for a
vendored file too. What the order does instead is rank project source ahead of
installed dependencies and build output, so a truncated page is still useful.
The rationale is in :mod:`agent.tools.glob.search`; the opposite choice for
content search is in :mod:`agent.tools.grep.ignore`.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The implementation is in :mod:`~agent.tools.glob.tool`, the walk in
:mod:`~agent.tools.glob.search`; the pattern matcher
(:mod:`~agent.tools.glob_pattern`) and the walk itself
(:mod:`~agent.tools.file_walk`) are shared with ``grep`` and therefore live at the
package root. This module re-exports the public surface.
"""

from agent.tools.file_walk import MAX_SCANNED_ENTRIES
from agent.tools.glob.description import (
    GLOB_DESCRIPTION,
    GLOB_PARAMETERS,
    MAX_RESULTS,
)
from agent.tools.glob.errors import GlobError
from agent.tools.glob.tool import make_glob_tool

__all__ = [
    "GLOB_DESCRIPTION",
    "GLOB_PARAMETERS",
    "MAX_RESULTS",
    "MAX_SCANNED_ENTRIES",
    "GlobError",
    "make_glob_tool",
]

"""The ``grep`` tool: search file contents, workspace scoped.

``glob`` answers "where is the file"; this answers "where is it written", which
is the question that actually comes first when reading unfamiliar code.

The shape of the answer is the caller's choice (``output_mode``): the files that
match, the matching lines, or a count per file. All three obey the same bounds:

- the search root resolves through ``file_access``, so a search is confined
  exactly like a read, and entries the policy denies are never opened;
- output is capped (``DEFAULT_HEAD_LIMIT`` rendered lines/paths, long lines cut
  at ``MAX_COLUMNS``) and can be paged with ``offset``/``head_limit``;
- the scan is bounded in files walked (``MAX_SCANNED_FILES``), bytes per file
  (``MAX_FILE_BYTES``) and wall-clock (``MAX_DURATION_SECONDS``), and reports
  ``scan_truncated``/``timed_out`` rather than presenting a partial answer as a
  complete one;
- VCS metadata, binary files and credential-like files are skipped. The last
  group is listed in ``skipped_sensitive``: ``grep`` returns contents, so it must
  not become a way around the confirmation ``read_file`` asks for those files.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The pieces: :mod:`~agent.tools.grep.scan` (candidates and reading),
:mod:`~agent.tools.grep.content` / :mod:`~agent.tools.grep.listing` (the three
output shapes), :mod:`~agent.tools.grep.regex`, :mod:`~agent.tools.grep.types`,
and :mod:`~agent.tools.grep.tool` (validation and orchestration). The glob
pattern matcher and the file walk are shared with ``glob`` and live at the
package root (``agent.tools.glob_pattern``, ``agent.tools.file_walk``).
"""

from agent.tools.grep.description import (
    DEFAULT_HEAD_LIMIT,
    GREP_DESCRIPTION,
    GREP_PARAMETERS,
    MAX_FILE_BYTES,
    MAX_SCANNED_FILES,
)
from agent.tools.grep.errors import GrepError
from agent.tools.grep.tool import make_grep_tool

__all__ = [
    "DEFAULT_HEAD_LIMIT",
    "GREP_DESCRIPTION",
    "GREP_PARAMETERS",
    "MAX_FILE_BYTES",
    "MAX_SCANNED_FILES",
    "GrepError",
    "make_grep_tool",
]

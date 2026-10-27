"""The one place a user supplied pattern becomes a compiled regular expression.

Two deliberate choices:

- **Python ``re`` syntax, not ripgrep's.** The tool is implemented in Python and
  documented that way; pretending to accept Rust regex syntax would fail on
  exactly the constructs a model is most likely to write (lookarounds,
  backreferences).
- **Anchors stay line scoped in every mode.** ``^``/``$`` mean "start/end of the
  line" in this codebase: line mode searches line by line, and multiline mode
  scans the whole file with ``re.MULTILINE`` for the same reason. Without that,
  ``^def`` would only match the first line of a file the moment ``multiline``
  was turned on.
"""

from __future__ import annotations

import re
from typing import Pattern

from agent.tools.grep.errors import GrepError


def compile_pattern(
    pattern: str, case_insensitive: bool = False, multiline: bool = False
) -> Pattern[str]:
    """Compile ``pattern``, turning a bad expression into a model readable error."""
    flags = 0
    if case_insensitive:
        flags |= re.IGNORECASE
    if multiline:
        # DOTALL so ``.`` crosses lines, MULTILINE so the anchors stay per line.
        flags |= re.DOTALL | re.MULTILINE
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        raise GrepError(
            f"Invalid regular expression: {exc}",
            reason="invalid_pattern",
            pattern=pattern,
        ) from exc

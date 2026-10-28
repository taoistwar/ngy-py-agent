"""The one place a user supplied pattern becomes a compiled regular expression.

Three deliberate choices:

- **Python ``re`` syntax, compiled by the ``regex`` module.** Same dialect the
  tool documents, plus the ability to abort a single match. ``regex`` accepts
  everything a model writes for ``re`` (lookarounds, backreferences, named
  groups), so nothing in the documented syntax changes.
- **Anchors stay line scoped in every mode.** ``^``/``$`` mean "start/end of the
  line" in this codebase: line mode searches line by line, and multiline mode
  scans the whole file with ``regex.MULTILINE`` for the same reason. Without
  that, ``^def`` would only match the first line of a file the moment
  ``multiline`` was turned on.
- **Every match has a deadline.** A backtracking expression can take exponential
  time, and a tool call has no other way to be interrupted: the loop awaits the
  handler, so one pathological line would freeze the whole turn with no error to
  show for it. ``regex`` also removes most (not all) of that behaviour -
  ``(a+)+$`` no longer explodes, ``(a|a)+$`` still does - which is exactly why
  the timeout is a second gate rather than the only one.

``Matcher`` exists so no call site can forget the timeout: the raw compiled
pattern is never handed out, and each method below passes ``timeout=`` on the way
in. A caller that adds a new way to match has one obvious place to put it.
"""

from __future__ import annotations

from typing import List, Optional, Pattern, Sequence, Tuple

import regex

from agent.tools.grep.errors import GrepError

# Per-call ceiling. Two seconds is enormous for a single line (a normal one is
# microseconds) and still short enough that a handful of timed-out files cannot
# exhaust the search's own wall-clock budget.
MATCH_TIMEOUT_SECONDS = 2.0


class MatchTimeout(Exception):
    """Raised when one match exceeds :data:`MATCH_TIMEOUT_SECONDS`."""


class Matcher:
    """A compiled pattern whose matches cannot run forever.

    Every method raises :class:`MatchTimeout` instead of returning a partial
    answer, so the caller can drop the file and *say* it was dropped.
    """

    def __init__(
        self,
        pattern: str,
        case_insensitive: bool = False,
        multiline: bool = False,
        timeout: Optional[float] = None,
    ) -> None:
        self.pattern = pattern
        self.multiline = multiline
        # Resolved at construction rather than as a default argument, so the
        # constant can be raised or lowered for a run (and in tests) without
        # having to rebuild the signature.
        self.timeout = MATCH_TIMEOUT_SECONDS if timeout is None else timeout
        flags = 0
        if case_insensitive:
            flags |= regex.IGNORECASE
        if multiline:
            # DOTALL so ``.`` crosses lines, MULTILINE so the anchors stay per line.
            flags |= regex.DOTALL | regex.MULTILINE
        try:
            self._compiled: Pattern[str] = regex.compile(pattern, flags)
        except regex.error as exc:
            raise GrepError(
                f"Invalid regular expression: {exc}",
                reason="invalid_pattern",
                pattern=pattern,
            ) from exc

    def matching_lines(self, lines: Sequence[str]) -> List[int]:
        """Indexes of the lines holding a match."""
        return [index for index, line in enumerate(lines) if self._search(line)]

    def has_line_match(self, lines: Sequence[str]) -> bool:
        """Whether any line matches; stops at the first hit."""
        return any(self._search(line) for line in lines)

    def count_lines(self, lines: Sequence[str]) -> int:
        return sum(1 for line in lines if self._search(line))

    def has_text_match(self, text: str) -> bool:
        return self._search(text)

    def count_text_matches(self, text: str) -> int:
        """Non-empty matches; a zero-width match covers no line worth counting."""
        return len(self.text_matches(text))

    def text_matches(self, text: str) -> List[Tuple[int, str]]:
        """``(start offset, matched text)`` for every non-empty match."""
        matches: List[Tuple[int, str]] = []
        try:
            for match in self._compiled.finditer(text, timeout=self.timeout):
                if match.start() != match.end():
                    matches.append((match.start(), match.group(0)))
        except TimeoutError as exc:  # ``regex`` raises the builtin on timeout
            raise MatchTimeout(self.pattern) from exc
        return matches

    def _search(self, text: str) -> bool:
        try:
            return self._compiled.search(text, timeout=self.timeout) is not None
        except TimeoutError as exc:
            raise MatchTimeout(self.pattern) from exc

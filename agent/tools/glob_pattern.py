"""Glob pattern matching: a shell-style pattern compiled to one regex.

Shared by the two discovery tools: ``glob`` matches file *names* with it, and
``grep`` uses it for its ``glob`` file *filter*. It lives at the package root
rather than inside either tool because a second tool needs it, and a tool
package must not import another one (see ``AGENTS.md``).

``fnmatch`` and ``pathlib.Path.glob`` both look like the obvious choice and both
are wrong here:

- ``fnmatch`` treats ``**`` as ``*`` and lets a wildcard cross ``/``, so
  ``src/*.ts`` would happily match ``src/deep/a.ts``.
- ``Path.glob`` has no ``{a,b}`` alternatives, cannot be told to match the file
  name at any depth, and its matching cannot be case-folded per call on a
  case-insensitive filesystem.

The semantics below follow ripgrep's ``--glob``, because that is the model the
tool's documentation and the model's expectations come from:

- ``*`` matches anything but ``/``, ``?`` matches one character but ``/``;
- ``**`` crosses separators, and ``**/`` also matches *zero* segments, so
  ``src/**/*.ts`` finds ``src/a.ts`` as well as ``src/deep/a.ts``;
- ``[abc]`` / ``[!abc]`` are character classes, ``{a,b}`` is an alternative list;
- a pattern with **no** separator is matched against the file name only, at any
  depth - without that rule ``*.py`` would mean "in the search root", which is
  never what the caller meant.

Case folding follows the filesystem: insensitive on Windows, sensitive
elsewhere (``default_case_sensitive``), overridable per pattern so tests can
exercise both.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

# Characters that make a path segment a *pattern* rather than a literal name.
MAGIC_CHARS = "*?[{"


def has_glob_magic(text: str) -> bool:
    """Whether ``text`` contains a wildcard character."""
    return any(char in text for char in MAGIC_CHARS)


def default_case_sensitive() -> bool:
    """Whether matching should be case sensitive on this platform.

    Windows filesystems are case insensitive, so a model that typed ``SRC/**``
    would otherwise silently get nothing back.
    """
    return os.name != "nt"


def split_absolute_pattern(pattern: str) -> Optional[Tuple[str, str]]:
    """Split an absolute pattern into ``(base_dir, relative_pattern)``.

    An absolute pattern carries its own root (``/w/src/**/*.py`` means "search
    ``/w/src``"), which is why it overrides the ``path`` argument. ``None`` is
    returned for a relative pattern, which is resolved against ``path`` instead.

    A pattern with no wildcard at all is still handled here: it points at one
    concrete file, so its directory becomes the base and its name the pattern.
    """
    normalized = pattern.replace("\\", "/")
    if not Path(normalized).is_absolute():
        return None

    segments = normalized.split("/")
    magic_at = next(
        (index for index, segment in enumerate(segments) if has_glob_magic(segment)), None
    )
    if magic_at is None:
        return _base_dir(segments[:-1]), segments[-1]
    return _base_dir(segments[:magic_at]), "/".join(segments[magic_at:])


def _base_dir(segments: List[str]) -> str:
    """Join the leading segments, keeping a filesystem root a root.

    ``"".join`` of nothing is the POSIX root, and Windows' ``"C:"`` alone is a
    drive-relative path rather than ``C:\\``: both need the separator, or the
    resolved search root would be the process's current directory instead.
    """
    base = "/".join(segments)
    if not base or base.endswith(":"):
        return f"{base}/"
    return base


class GlobPattern:
    """One compiled pattern, matched the way ripgrep's ``--glob`` does."""

    def __init__(
        self,
        pattern: str,
        case_sensitive: Optional[bool] = None,
        anchored: Optional[bool] = None,
    ) -> None:
        self.pattern = pattern
        self.case_sensitive = (
            default_case_sensitive() if case_sensitive is None else bool(case_sensitive)
        )
        # Without a separator the pattern describes a file name, not a location.
        # ``anchored`` overrides that inference for syntaxes that say it out loud:
        # in ``.gitignore`` a leading "/" means "here, not at any depth", which
        # survives stripping the slash only as an explicit flag.
        self.basename_only = ("/" not in pattern) if anchored is None else not anchored
        flags = 0 if self.case_sensitive else re.IGNORECASE
        self._regex = re.compile(f"^(?:{_translate(pattern)})$", flags)

    def matches(self, relative_path: str, name: str) -> bool:
        """Whether a file matches.

        ``relative_path`` is the POSIX style path below the search root, ``name``
        its last segment.
        """
        subject = name if self.basename_only else relative_path
        return self._regex.match(subject) is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"GlobPattern({self.pattern!r}, case_sensitive={self.case_sensitive})"


def _translate(pattern: str) -> str:
    """Translate a glob pattern into regex source, without anchors."""
    out: List[str] = []
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "*":
            index = _translate_star(pattern, index, out)
        elif char == "?":
            out.append("[^/]")
            index += 1
        elif char == "[":
            translated, index = _translate_class(pattern, index)
            out.append(translated)
        elif char == "{":
            translated, index = _translate_braces(pattern, index)
            out.append(translated)
        else:
            out.append(re.escape(char))
            index += 1
    return "".join(out)


def _translate_star(pattern: str, index: int, out: List[str]) -> int:
    """Translate ``*`` or ``**`` at ``index``; return the next index."""
    if not pattern.startswith("**", index):
        out.append("[^/]*")
        return index + 1

    cursor = index + 2
    if cursor < len(pattern) and pattern[cursor] == "/":
        # ``a/**/b`` has to match ``a/b`` too: the separator is part of the match,
        # and "zero or more directories" is exactly ``(?:.*/)?``.
        out.append("(?:.*/)?")
        return cursor + 1
    out.append(".*")
    return cursor


def _translate_class(pattern: str, start: int) -> Tuple[str, int]:
    """Translate a ``[...]`` class at ``start``; an unterminated ``[`` is literal."""
    index = start + 1
    length = len(pattern)
    negated = index < length and pattern[index] in "!^"
    if negated:
        index += 1

    body: List[str] = []
    # A ``]`` right after the opening bracket is a literal member, not the end.
    if index < length and pattern[index] == "]":
        body.append(r"\]")
        index += 1

    while index < length and pattern[index] != "]":
        char = pattern[index]
        if char == "\\":
            body.append("\\\\")
        elif char == "^":
            body.append(r"\^")
        else:
            # ``-`` stays untouched so ``[a-z]`` remains a range.
            body.append(char)
        index += 1

    if index >= length or not body:
        # No closing bracket (or an empty class): not a class after all, so the
        # bracket is matched literally and the rest of the pattern is re-read.
        return re.escape("["), start + 1

    prefix = "^" if negated else ""
    return f"[{prefix}{''.join(body)}]", index + 1


def _translate_braces(pattern: str, start: int) -> Tuple[str, int]:
    """Translate ``{a,b}`` at ``start``; a missing ``}`` means a literal brace."""
    end = _closing_brace(pattern, start)
    if end is None:
        return re.escape("{"), start + 1

    body = pattern[start + 1 : end]
    alternatives = _split_alternatives(body)
    translated = "|".join(_translate(item) for item in alternatives)
    return f"(?:{translated})", end + 1


def _closing_brace(pattern: str, start: int) -> Optional[int]:
    depth = 0
    for index in range(start, len(pattern)):
        char = pattern[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_alternatives(body: str) -> List[str]:
    """Split a brace body on the commas that are not inside a nested brace."""
    parts: List[str] = []
    current: List[str] = []
    depth = 0
    for char in body:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts

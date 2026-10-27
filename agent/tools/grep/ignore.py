"""Per-directory ``.gitignore`` rules: what the repository itself calls source.

A content search should look where the repository says the source is, and the
repository says that in ``.gitignore``. The hand-written directory list
(:data:`agent.tools.file_walk.GENERATED_DIRS`) stays as a floor - plenty of repos
never mention ``node_modules`` - but it can only ever be a guess about names,
while this file is the project's own statement.

The dialect is the useful subset, not all of git:

- ``#`` comments, blank lines;
- ``!pattern`` re-includes (last matching rule wins, as in git);
- ``dir/`` matches directories only;
- ``/pattern`` is anchored to the directory holding the ``.gitignore``;
- ``*``, ``?``, ``[...]``, ``**`` and ``{a,b}`` mean what they mean everywhere
  else in this codebase - the matcher is :class:`agent.tools.glob_pattern.GlobPattern`,
  whose "no separator means file name at any depth" rule is exactly git's.

Two boundaries worth stating because they are choices, not oversights:

- **Rules are read from the search root downwards, never from ancestors.** The
  search root is the model's world; what it points at is what gets searched.
  That keeps the one escape hatch working: ``path="node_modules/react"`` searches
  it even though the workspace ``.gitignore`` excludes ``node_modules``.
- **A file excluded by its own directory's rules cannot be re-included from
  above.** Same as git: an ignored directory is never descended into, so nothing
  below it can bring anything back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from agent.tools.glob_pattern import GlobPattern

GITIGNORE = ".gitignore"


@dataclass(frozen=True)
class Rule:
    """One line of a ``.gitignore``, anchored at the directory that declared it."""

    matcher: GlobPattern
    base: Path
    negated: bool
    dir_only: bool

    @property
    def name_only(self) -> bool:
        """Whether the rule is decided by the file name alone.

        Most rules are (``*.log``, ``node_modules``, ``.venv``), and asking the
        name directly keeps the walk from computing a relative path per rule per
        entry - which is the difference between a search that takes 20 ms and one
        that takes a second on a nine-hundred-file tree.
        """
        return self.matcher.basename_only


class IgnoreRules:
    """The rules in effect for any directory below ``root``, loaded on demand.

    Loaded lazily and memoised per directory: a deep subtree costs one dict lookup
    per entry, and a directory without a ``.gitignore`` inherits its parent's
    tuple instead of rebuilding it.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: Dict[Path, Tuple[Rule, ...]] = {}

    def ignored(self, path: Path, is_dir: bool) -> bool:
        """Whether ``path`` is excluded by the rules that apply to it."""
        ignored = False
        relatives: Dict[Path, Optional[str]] = {}
        for rule in self.rules_for(path.parent):
            if rule.dir_only and not is_dir:
                continue
            if not _applies(rule, path, relatives):
                continue
            # Last match wins: a deeper ``!`` can undo a parent's exclusion.
            ignored = not rule.negated
        return ignored

    def rules_for(self, directory: Path) -> Tuple[Rule, ...]:
        """Ancestor-first rules that apply inside ``directory``."""
        cached = self._cache.get(directory)
        if cached is not None:
            return cached

        inside = directory == self.root or self.root in directory.parents
        inherited: Tuple[Rule, ...] = ()
        if inside and directory != self.root:
            inherited = self.rules_for(directory.parent)
        rules = inherited + tuple(_parse(directory / GITIGNORE, directory))
        self._cache[directory] = rules
        return rules


def _applies(rule: Rule, path: Path, relatives: Dict[Path, Optional[str]]) -> bool:
    """Whether one rule's pattern matches ``path`` (ignoring negation semantics)."""
    if rule.name_only:
        return rule.matcher.matches(path.name, path.name)
    if rule.base not in relatives:
        relatives[rule.base] = _relative(path, rule.base)
    relative = relatives[rule.base]
    if relative is None:
        return False
    return rule.matcher.matches(relative, path.name)


def _relative(path: Path, base: Path) -> Optional[str]:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:  # pragma: no cover - defensive: paths come from the walk
        return None


def _parse(path: Path, base: Path) -> List[Rule]:
    """Rules declared by one ``.gitignore``; an unreadable one declares nothing."""
    text = _read(path)
    if text is None:
        return []

    rules: List[Rule] = []
    for line in text.splitlines():
        rule = _rule(line, base)
        if rule is not None:
            rules.append(rule)
    return rules


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _rule(line: str, base: Path) -> Optional[Rule]:
    """One rule, or ``None`` for a comment, a blank line or a pattern we cannot use."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    negated = stripped.startswith("!")
    pattern = stripped[1:] if negated else stripped
    dir_only = pattern.endswith("/")
    pattern = pattern.rstrip("/")
    anchored = pattern.startswith("/")
    pattern = pattern.lstrip("/")
    if not pattern:
        return None

    try:
        matcher = GlobPattern(pattern, anchored=True if anchored else None)
    except re.error:  # pragma: no cover - a pattern we cannot compile is skipped
        return None
    return Rule(matcher=matcher, base=base, negated=negated, dir_only=dir_only)

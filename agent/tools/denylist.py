"""Hard deny-list: tool calls that never run, whatever anybody answers (ADR 0024).

Three layers can refuse a tool call, and each answers a different question:

* ``file_access`` - "may this path be touched at all?" (inside the file tools)
* ``denylist`` - "is this tool + argument combination dangerous by policy?" (here)
* ``permissions`` - "may this one run?" (asked to the user, ``PermissionBroker``)

The deny-list is evaluated in ``ToolRegistry.execute_tool`` **before** the
permission gate, for the same reason ``file_access`` denials are not questioned
(ADR 0006 D9): the answer is already no, so a dialog whose only useful button is
"deny" teaches the model that persistence pays.

A rule is a **tool matcher** plus zero or more **argument matchers**, all of
which must match. Both sides support two kinds:

* ``fixed`` - the whole value equals the configured text.
* ``regex`` - ``re.search`` over the value, so a substring pattern is enough.

Argument values that are not strings are matched in their JSON form
(``json.dumps(..., ensure_ascii=False, sort_keys=True)``), and a literal matcher
may say so directly (``{"timeout": 30}``, ``{"urls": ["https://example.com"]}``):
a rule about a number or a list is then written exactly the way the value appears
in the call, instead of depending on how Python happens to print it. An object
position is reserved for the matcher form, so a *dict* argument value has to
spell out ``{"match": "fixed", "value": {...}}``.

The rules live in a JSON file (``TOOL_DENYLIST_CONFIG``, default
``data/tool_denylist.json``)::

    {
      "rules": [
        {"id": "no-rm-root", "tool": "exec_command", "args": {"command": "rm -rf /"}},
        {"id": "no-force-push", "tool": "exec_command",
         "args": {"command": {"match": "regex", "pattern": "git\\s+push\\b.*(--force|-f\\b)"}},
         "reason": "Force-pushing rewrites shared history."},
        {"id": "no-computer", "tool": {"match": "regex", "pattern": "^computer_"}}
      ]
    }

The file is read through a stat-based cache, so editing it takes effect on the
next call without a parse per call. A missing or unreadable file means "no
rules"; a **rule that cannot be evaluated is dropped and reported** through
:attr:`ToolDenyList.problems`, because a malformed rule must not quietly turn
into "match everything".
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

DENYLIST_ENV = "TOOL_DENYLIST_CONFIG"
DEFAULT_DENYLIST_PATH = "data/tool_denylist.json"

MATCH_FIXED = "fixed"
MATCH_REGEX = "regex"
MATCH_KINDS = (MATCH_FIXED, MATCH_REGEX)

# Decision reasons, spelled like the permission reasons so one payload field
# tells the UI which layer refused the call.
REASON_DENYLIST = "denylist"
REASON_DENYLIST_ERROR = "denylist_error"

# Fallback id for a rule that does not name itself, so an event can always point
# at one entry in the file.
_RULE_ID_PREFIX = "rule"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_denylist_path() -> Path:
    """Location of the rule file, overridable with ``TOOL_DENYLIST_CONFIG``."""
    override = (os.getenv(DENYLIST_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    return _repo_root() / DEFAULT_DENYLIST_PATH


@lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern:
    """Compile a rule pattern once; the deny-list is checked on every call."""
    return re.compile(pattern)


def _as_text(value: Any) -> str:
    """The text a matcher is applied to.

    Strings match as themselves; everything else matches its JSON form, which is
    how the value also appears in the tool call the model sent.
    """
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _lookup(arguments: Mapping[str, Any], field: str) -> Tuple[bool, Any]:
    """Resolve ``field`` in ``arguments``, following ``a.b`` and list indexes."""
    current: Any = arguments
    for part in field.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return False, None
        else:
            return False, None
    return True, current


@dataclass(frozen=True)
class MatchSpec:
    """One value matcher: an exact string or a regular expression."""

    kind: str
    text: str

    def matches(self, value: str) -> bool:
        if self.kind == MATCH_REGEX:
            return _compile(self.text).search(value) is not None
        return value == self.text

    def to_payload(self) -> Dict[str, Any]:
        if self.kind == MATCH_REGEX:
            return {"match": MATCH_REGEX, "pattern": self.text}
        return {"match": MATCH_FIXED, "value": self.text}


@dataclass(frozen=True)
class ArgumentMatcher:
    """One argument must exist and match; a missing argument never matches."""

    field: str
    spec: MatchSpec

    def matches(self, arguments: Mapping[str, Any]) -> bool:
        found, value = _lookup(arguments, self.field)
        return found and self.spec.matches(_as_text(value))

    def to_payload(self) -> Dict[str, Any]:
        return {"field": self.field, **self.spec.to_payload()}


@dataclass(frozen=True)
class ToolDenyRule:
    """A tool matcher plus argument matchers that must **all** hold."""

    rule_id: str
    tool: MatchSpec
    arguments: Tuple[ArgumentMatcher, ...] = ()
    reason: str = ""

    def matched_fields(
        self, tool: str, arguments: Mapping[str, Any]
    ) -> Optional[Tuple[str, ...]]:
        """The matched argument fields, or ``None`` when this rule does not apply."""
        if not self.tool.matches(tool):
            return None
        fields: List[str] = []
        for matcher in self.arguments:
            if not matcher.matches(arguments):
                return None
            fields.append(matcher.field)
        return tuple(fields)

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"id": self.rule_id, "tool": self.tool.to_payload()}
        if self.arguments:
            payload["args"] = [matcher.to_payload() for matcher in self.arguments]
        if self.reason:
            payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class DenyMatch:
    """The rule that blocked a call, plus what the caller reports about it."""

    rule_id: str
    tool: str
    reason: str
    fields: Tuple[str, ...] = ()


class ToolDenyList:
    """JSON-backed list of hard denials, re-read when the file changes.

    ``rules`` builds an in-memory list instead of reading a file, for callers
    that know the policy they want (tests, embedders) and must not depend on the
    machine's data directory.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        rules: Optional[Sequence[ToolDenyRule]] = None,
    ) -> None:
        self._path = Path(path) if path is not None else default_denylist_path()
        self._embedded: Optional[Tuple[ToolDenyRule, ...]] = (
            tuple(rules) if rules is not None else None
        )
        self._lock = threading.Lock()
        self._cache_key: Optional[Tuple[int, int]] = None
        self._cached: Tuple[ToolDenyRule, ...] = ()
        self._problems: Tuple[str, ...] = ()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def problems(self) -> List[str]:
        """Rules that were dropped, and why; empty when the file is clean."""
        return list(self._load()[1])

    def list(self) -> List[ToolDenyRule]:
        return list(self._load()[0])

    def match(self, tool: str, arguments: Optional[Mapping[str, Any]]) -> Optional[DenyMatch]:
        """The rule blocking this call, or ``None`` when it may run."""
        arguments = arguments or {}
        for rule in self._load()[0]:
            fields = rule.matched_fields(tool, arguments)
            if fields is not None:
                return DenyMatch(
                    rule_id=rule.rule_id,
                    tool=tool,
                    reason=rule.reason,
                    fields=fields,
                )
        return None

    # ----------------------------------------------------------------- private

    def _load(self) -> Tuple[Tuple[ToolDenyRule, ...], Tuple[str, ...]]:
        if self._embedded is not None:
            return self._embedded, self._problems
        try:
            stat = self._path.stat()
        except OSError:
            # No file means no denials. It never means "the policy is gone":
            # nothing here can widen access, only withhold it.
            return (), ()
        key = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if key == self._cache_key:
                return self._cached, self._problems
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            rules: Tuple[ToolDenyRule, ...] = ()
            problems: Tuple[str, ...] = (f"{self._path.as_posix()}: {exc}",)
        else:
            rules, problems = parse_rules(payload)
        with self._lock:
            self._cache_key = key
            self._cached = rules
            self._problems = problems
        return rules, problems


def parse_rules(payload: Any) -> Tuple[Tuple[ToolDenyRule, ...], Tuple[str, ...]]:
    """Parse ``{"rules": [...]}`` (or a bare list) into rules plus dropped ones."""
    if isinstance(payload, Mapping):
        items = payload.get("rules")
        where = "rules"
    else:
        items = payload
        where = "the deny-list"
    if not isinstance(items, list):
        return (), (f"{where}: expected a list of rules",)

    rules: List[ToolDenyRule] = []
    problems: List[str] = []
    for index, item in enumerate(items):
        rule, rule_problems = _parse_rule(item, index)
        problems.extend(rule_problems)
        if rule is not None:
            rules.append(rule)
    return tuple(rules), tuple(problems)


def _parse_rule(raw: Any, index: int) -> Tuple[Optional[ToolDenyRule], Tuple[str, ...]]:
    where = f"rules[{index}]"
    if not isinstance(raw, Mapping):
        return None, (f"{where}: expected an object",)

    tool, problem = _parse_spec(raw.get("tool"), f"{where}.tool")
    if tool is None:
        return None, (problem,)

    # Partial rules are not kept: a rule whose arguments half-parsed would match
    # a *different* set of calls than the one that was written down.
    arguments, argument_problems = _parse_arguments(raw.get("args"), f"{where}.args")
    if argument_problems:
        return None, tuple(argument_problems)

    rule_id = str(raw.get("id") or "").strip() or f"{_RULE_ID_PREFIX}[{index}]"
    return (
        ToolDenyRule(
            rule_id=rule_id,
            tool=tool,
            arguments=arguments,
            reason=str(raw.get("reason") or "").strip(),
        ),
        (),
    )


def _parse_spec(raw: Any, where: str) -> Tuple[Optional[MatchSpec], str]:
    """Parse a matcher: a literal (fixed) or ``{"match": ..., "value"/"pattern": ...}``.

    A literal is written as the value it compares against, so a scalar or a list
    is allowed and compared in its JSON form. An object is always a matcher, which
    is why a *dict* argument value has to spell out ``{"match": "fixed", ...}``.
    """
    if isinstance(raw, Mapping):
        return _parse_spec_object(raw, where)
    if isinstance(raw, (str, int, float, bool, list)):
        text = _as_text(raw)
        if not text:
            return None, f"{where}: empty fixed value"
        return MatchSpec(MATCH_FIXED, text), ""
    return None, f"{where}: expected a literal or an object with match/value/pattern"


def _parse_spec_object(raw: Mapping, where: str) -> Tuple[Optional[MatchSpec], str]:
    kind = str(raw.get("match") or MATCH_FIXED).strip().lower()
    if kind == MATCH_FIXED:
        text = raw.get("value")
        if isinstance(text, Mapping) or text is None:
            return None, f"{where}: a fixed match needs a value"
        body = _as_text(text)
        if not body:
            return None, f"{where}: a fixed match needs a non-empty value"
        return MatchSpec(MATCH_FIXED, body), ""
    if kind == MATCH_REGEX:
        text = raw.get("pattern")
        if not isinstance(text, str) or not text:
            return None, f"{where}: a regex match needs a non-empty pattern"
        try:
            _compile(text)
        except re.error as exc:
            return None, f"{where}: invalid regex {text!r}: {exc}"
        return MatchSpec(MATCH_REGEX, text), ""
    return None, f"{where}: unsupported match kind {kind!r}"


def _parse_arguments(
    raw: Any, where: str
) -> Tuple[Tuple[ArgumentMatcher, ...], Tuple[str, ...]]:
    """Parse ``{"field": matcher}`` or ``[{"field": ..., ...matcher}]``."""
    if raw is None:
        return (), ()
    if isinstance(raw, Mapping):
        pairs = list(raw.items())
    elif isinstance(raw, list):
        pairs = []
        for index, item in enumerate(raw):
            if not isinstance(item, Mapping) or not str(item.get("field") or "").strip():
                return (), (f"{where}[{index}]: expected an object with a field name",)
            field = str(item["field"]).strip()
            pairs.append((field, {key: value for key, value in item.items() if key != "field"}))
    else:
        return (), (f"{where}: expected an object of argument matchers",)

    matchers: List[ArgumentMatcher] = []
    problems: List[str] = []
    for field, value in pairs:
        name = str(field or "").strip()
        if not name:
            problems.append(f"{where}: empty argument field name")
            continue
        spec, problem = _parse_spec(value, f"{where}.{name}")
        if spec is None:
            problems.append(problem)
            continue
        matchers.append(ArgumentMatcher(field=name, spec=spec))
    return tuple(matchers), tuple(problems)

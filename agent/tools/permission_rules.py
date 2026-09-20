"""Persisted "always allow" rules for the permission gate (ADR 0006 D8).

A rule is deliberately **narrow: one tool plus one exact target**. The reference
design eventually wants patterns like ``Bash(git push origin main:*)``, but a
pattern that the user cannot fully see is also a pattern that can silently widen -
so the store only records the exact call the user was shown, keyed on the same
resolved target the dialog displayed. A rule for one command never covers a
different command that merely starts the same way.

The file lives next to the access policy (``data/permission_rules.json``; relocate
with ``PERMISSION_RULES_CONFIG``). A missing or unreadable file means "no rules",
which is why a corrupt file degrades to "ask again" rather than failing open.

Rules are read from disk on every lookup instead of being cached: the API can add
and remove them at any time from another thread, and a stale cache would mean the
user's "remove this rule" silently not taking effect.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.tools.file_bytes import DEFAULT_NEW_FILE_MODE, write_bytes_atomic

RULE_FILE_ENV = "PERMISSION_RULES_CONFIG"
DEFAULT_RULE_PATH = "data/permission_rules.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_rule_path() -> Path:
    """Location of the rule file, overridable with ``PERMISSION_RULES_CONFIG``."""
    override = (os.getenv(RULE_FILE_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    return _repo_root() / DEFAULT_RULE_PATH


@dataclass(frozen=True)
class PermissionRule:
    """One remembered decision: "this tool + this target was approved"."""

    tool: str
    target: str
    kind: str = ""
    created_at: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "target": self.target,
            "kind": self.kind,
            "created_at": self.created_at,
        }


class PermissionRuleStore:
    """JSON-backed list of allow rules."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path is not None else default_rule_path()
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def list(self) -> List[PermissionRule]:
        return self._read()

    def match(self, tool: str, target: str) -> bool:
        """Whether ``(tool, target)`` is already approved."""
        for rule in self._read():
            if rule.tool == tool and rule.target == target:
                return True
        return False

    def add(self, tool: str, target: str, kind: str = "") -> bool:
        """Remember an approval.

        Returns ``True`` when the rule is in place afterwards - including when it
        was already there. ``False`` means it could not be persisted, which the
        caller must report honestly rather than claiming a standing approval.
        """
        tool = str(tool or "").strip()
        target = str(target or "")
        if not tool or not target:
            return False

        with self._lock:
            rules = self._read()
            if any(rule.tool == tool and rule.target == target for rule in rules):
                return True
            rules.append(
                PermissionRule(
                    tool=tool,
                    target=target,
                    kind=str(kind or ""),
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            return self._write(rules)

    def remove(self, tool: str, target: str) -> bool:
        """Forget an approval. Returns whether a rule was actually removed."""
        with self._lock:
            rules = self._read()
            kept = [rule for rule in rules if not (rule.tool == tool and rule.target == target)]
            if len(kept) == len(rules):
                return False
            return self._write(kept)

    # ----------------------------------------------------------------- private

    def _read(self) -> List[PermissionRule]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # No file, or one we cannot parse. Both mean "no rules", i.e. the user
            # gets asked again. Never "allow", which is the whole point of the gate.
            return []
        items = payload.get("rules") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []

        rules: List[PermissionRule] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool") or "").strip()
            target = str(item.get("target") or "")
            if not tool or not target:
                continue
            rules.append(
                PermissionRule(
                    tool=tool,
                    target=target,
                    kind=str(item.get("kind") or ""),
                    created_at=str(item.get("created_at") or ""),
                )
            )
        return rules

    def _write(self, rules: List[PermissionRule]) -> bool:
        body = json.dumps(
            {"rules": [rule.to_payload() for rule in rules]}, indent=2, ensure_ascii=False
        )
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            write_bytes_atomic(self._path, body.encode("utf-8"), DEFAULT_NEW_FILE_MODE)
        except OSError:
            return False
        return True

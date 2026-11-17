"""The local secret store ("vault") the ``vault_http`` tool reads keys from.

The point of the store is that a secret never has to appear in a tool call: the
model names a key, the store hands the value to the request builder, and the value
is scrubbed out of everything that is reported back. That only works if the store
is a plain file next to the other runtime state instead of an argument.

File layout (``data/vault.json`` by default, relocate with ``VAULT_SECRETS_PATH``)::

    {"secrets": {"gh-token": "ghp_...", "billing-api": "..."}}

A bare mapping (no ``secrets`` wrapper) is accepted too, because that is what a user
writes by hand. The file lives under ``data/`` - git-ignored, like the permission
rules - and is re-read on every lookup: adding a key must take effect immediately,
and a secret that was rotated must not be served from a stale cache.

Two deliberate rules:

* **Errors never carry a value.** A message may name the keys that exist (the model
  already knows the names it tried) but never a secret, not even truncated.
* **A missing or unreadable file is an error, not "no secrets".** The caller has to
  be able to tell "the vault is not set up" from "that key does not exist", because
  the two need different fixes. Both are reported as a refusal to run, never as an
  unauthenticated request.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

VAULT_FILE_ENV = "VAULT_SECRETS_PATH"
DEFAULT_VAULT_PATH = "data/vault.json"

REASON_VAULT_UNAVAILABLE = "vault_unavailable"
REASON_SECRET_NOT_FOUND = "secret_not_found"

# Longest key name accepted, matching the tool's ``vault_auth_key`` bound. Kept in
# one place so the store and the schema cannot drift apart.
MAX_KEY_CHARS = 128

# How many existing key names an error message may list. Enough to recover from a
# typo, not enough to turn the error into a full inventory.
MAX_LISTED_NAMES = 20


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_vault_path() -> Path:
    """Location of the secret file, overridable with ``VAULT_SECRETS_PATH``."""
    override = (os.getenv(VAULT_FILE_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    return _repo_root() / DEFAULT_VAULT_PATH


class VaultStoreError(Exception):
    """A lookup that could not be answered, with a reason the model can act on."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}


class VaultStore:
    """Read-only view of the secret file."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path is not None else default_vault_path()

    @property
    def path(self) -> Path:
        return self._path

    def names(self) -> List[str]:
        """The key names that exist, sorted. Never the values."""
        return sorted(self._read().keys())

    def get(self, name: Any) -> str:
        """The secret for ``name``, or :class:`VaultStoreError` when unavailable."""
        key = str(name or "").strip()
        if not key or len(key) > MAX_KEY_CHARS:
            raise VaultStoreError(
                f"'{key}' is not a usable vault key name.",
                reason=REASON_SECRET_NOT_FOUND,
                vault_key=key,
                max_key_chars=MAX_KEY_CHARS,
            )

        secrets = self._read()
        value = secrets.get(key)
        if not isinstance(value, str) or not value:
            raise VaultStoreError(
                f"The vault has no key named {key!r}. {self._hint(secrets)}",
                reason=REASON_SECRET_NOT_FOUND,
                vault_key=key,
                available_keys=self._listed_names(secrets),
            )
        return value

    # ----------------------------------------------------------------- private

    def _hint(self, secrets: Dict[str, str]) -> str:
        names = self._listed_names(secrets)
        if not names:
            return (
                "The vault is empty; add the key to "
                f"{self._path.as_posix()} (or set {VAULT_FILE_ENV}) before retrying."
            )
        return f"Keys that do exist: {', '.join(names)}."

    def _listed_names(self, secrets: Dict[str, str]) -> List[str]:
        return sorted(secrets.keys())[:MAX_LISTED_NAMES]

    def _read(self) -> Dict[str, str]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise VaultStoreError(
                f"The vault file does not exist: {self._path.as_posix()}. Create it with "
                '{"secrets": {"<key name>": "<secret>"}} or point '
                f"{VAULT_FILE_ENV} at an existing file.",
                reason=REASON_VAULT_UNAVAILABLE,
                vault_path=self._path.as_posix(),
            ) from None
        except OSError as exc:
            # The message names the path and the OS error only: it cannot contain a
            # value, the file was never read.
            raise VaultStoreError(
                f"The vault file {self._path.as_posix()} cannot be read: {exc}",
                reason=REASON_VAULT_UNAVAILABLE,
                vault_path=self._path.as_posix(),
            ) from exc

        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise VaultStoreError(
                f"The vault file {self._path.as_posix()} is not valid JSON: {exc}. "
                "Fix it before retrying; do not guess the secret.",
                reason=REASON_VAULT_UNAVAILABLE,
                vault_path=self._path.as_posix(),
            ) from exc

        return _secret_mapping(payload, self._path)


def _secret_mapping(payload: Any, path: Path) -> Dict[str, str]:
    """Normalize the file's JSON into ``{name: secret}``, dropping nothing silently.

    Both shapes are accepted because the wrapper exists for readability while the
    bare mapping is what a user types. Anything else is a configuration error that
    must be reported, not skipped: a vault that half-loads would answer "no such
    key" for a key that is right there in the file.
    """
    items = payload.get("secrets") if isinstance(payload, dict) else None
    if items is None and isinstance(payload, dict):
        items = {key: value for key, value in payload.items() if key != "secrets"}
    if not isinstance(items, dict):
        raise VaultStoreError(
            f"The vault file {path.as_posix()} must hold an object of name/value secrets.",
            reason=REASON_VAULT_UNAVAILABLE,
            vault_path=path.as_posix(),
        )

    secrets: Dict[str, str] = {}
    for name, value in items.items():
        if not isinstance(name, str) or not isinstance(value, str) or not value:
            continue
        key = name.strip()
        if not key or len(key) > MAX_KEY_CHARS:
            continue
        secrets[key] = value
    return secrets

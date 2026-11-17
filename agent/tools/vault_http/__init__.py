"""The ``vault_http`` tool: an HTTPS request that carries a secret it never reveals.

``web_fetch`` deliberately cannot authenticate: it refuses URLs with credentials and
reads public pages only. An endpoint behind a token therefore had no shape in the
toolset - the model would fall back to ``exec_command`` (``curl -H``) or
``code_interpreter`` (``requests``), which puts the secret into the command line, the
tool call arguments, the transcript and the event log.

This tool closes that hole with one rule: **the secret is referenced, never passed**.
The model names a key (``vault_auth_key``), :mod:`agent.tools.vault_store` resolves it
from ``data/vault.json``, the request builder attaches it, and everything that comes
back is scrubbed of every form of it before it is reported. The model can call an
authenticated endpoint and still cannot read the credential - which also means a
transcript, a replay or a shared task log does not leak it.

The bounds, all deliberate (ADR 0030):

* **https only**, checked before the vault is opened;
* **no redirects followed**: the key must not travel to a host the user has not
  approved, so a 30x is reported and must be requested separately;
* **1 MiB of body**, cut while reading, with ``response_truncated`` saying so;
* **the output token budget**: a body too large for one result is written to the
  run's scratch directory and the model gets a preview plus the path;
* **a permission question every time** the (key, host) pair has not been approved,
  even when confirmations are otherwise auto-approved.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``). The
secret store lives at the package root (:mod:`agent.tools.vault_store`) because the
permission gate and the admin surface may both need to list key *names*, and tool
packages do not import each other. This module re-exports the public surface.
"""

from agent.tools.vault_http.description import VAULT_HTTP_DESCRIPTION, VAULT_HTTP_PARAMETERS
from agent.tools.vault_http.errors import VaultHttpError
from agent.tools.vault_http.tool import make_vault_http_tool

__all__ = [
    "VAULT_HTTP_DESCRIPTION",
    "VAULT_HTTP_PARAMETERS",
    "VaultHttpError",
    "make_vault_http_tool",
]

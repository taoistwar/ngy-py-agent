"""Provider-name normalisation and endpoint URL rules.

Provider names arrive as user configuration, so accept the punctuation people
actually write: ``openai-compatible``, ``OpenAI Compatible`` and
``openai.compatible`` all name the same provider. Normalisation happens here, once;
every other module imports it instead of keeping its own table.
"""

from __future__ import annotations

import os
from typing import Any

_SEPARATOR_TO_UNDERSCORE = str.maketrans({"-": "_", ".": "_"})

# What "nothing usable was configured" means, as it always has.
DEFAULT_PROVIDER = "openai"

# The canonical names ``build_provider`` can actually construct. The RPM table in the
# admin UI lists these, so a limit can never be saved for a provider that would not
# be built (and silently ignored).
SUPPORTED_PROVIDERS = (
    "openai",
    "anthropic",
    "anthropic_compatible",
    "gemini",
    "bedrock",
)

# Spellings that mean a provider other than their own name: the runtime names people
# know (``claude``, ``aws``, ``google``) and the OpenAI-compatible shorthand.
PROVIDER_ALIASES = {
    "claude": "anthropic",
    "aws": "bedrock",
    "google": "gemini",
    "openai_compatible": "openai",
    # Ollama serves the OpenAI chat-completions wire format and has no separate
    # client; the model form offers the spelling, so route it to the same provider.
    "ollama": "openai",
}

# Where an OpenAI-compatible provider goes when nothing was configured: the local
# Ollama every other default in this module names.
DEFAULT_OPENAI_BASE_URL = "http://127.0.0.1:12434/v1"


def normalize_provider_name(name: Any) -> str:
    """Normalise a provider spelling to ``lower_snake_case``; ``""`` when unusable."""
    if not isinstance(name, str):
        return ""
    # ``split()`` drops surrounding blanks and collapses inner runs, so tabs and
    # repeated spaces normalise too.
    return "_".join(name.split()).lower().translate(_SEPARATOR_TO_UNDERSCORE)


def canonicalize_provider(name: Any) -> str:
    """Resolve a configured spelling to the provider we build.

    Blank or unusable input means "not configured" and keeps the default of OpenAI;
    an unknown name is returned normalised rather than guessed, so the caller's
    ``ProviderError`` names what it got.
    """
    key = normalize_provider_name(name) or DEFAULT_PROVIDER
    return PROVIDER_ALIASES.get(key, key)


def resolve_tool_provider_for_schemas(name: Any) -> str:
    """Canonical provider name used to pick the tool-schema shape.

    ``ToolRegistry`` canonicalises what it is given, so this exists only to keep the
    spelling rules in one place for callers holding a raw configured name.
    """
    return canonicalize_provider(name)


def read_env(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def normalize_openai_base_url(
    base_url: str, default: str = DEFAULT_OPENAI_BASE_URL
) -> str:
    normalized = (base_url or "").strip()
    if not normalized:
        normalized = default
    normalized = normalized.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


def normalize_base_url(provider: Any, base_url: Any) -> str:
    """The URL a request will actually use for this provider.

    Adapters rewrite what they are handed (an OpenAI-compatible URL always ends in
    ``/v1``), so a rate limit stored against the URL an operator typed has to resolve
    to the same string as the URL the adapter posts to. This is that single
    resolution; ``agent.rate_limit`` builds its buckets on it (ADR 0014).
    """
    name = canonicalize_provider(provider)
    text = str(base_url or "").strip().rstrip("/")
    if name in ("openai", "anthropic_compatible"):
        return normalize_openai_base_url(text)
    return text

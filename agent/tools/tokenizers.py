"""Tokenizer backends used to bound tool output.

Backend selection:

- ``openai`` (and OpenAI-compatible models other than DeepSeek): ``tiktoken``
- ``deepseek``: the HuggingFace tokenizer cached in
  ``data/ds-tokenizer`` (override with ``DEEPSEEK_TOKENIZER_PATH``). It is
  downloaded on first use; set ``DEEPSEEK_TOKENIZER_OFFLINE=1`` to refuse the
  download.
- everything else: the OpenAI count inflated by :data:`FOREIGN_MODEL_PENALTY`

When no tokenizer can be loaded the count degrades to a documented byte
estimate so the agent keeps working offline.
"""

import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

# A single token covers at most this many bytes in practice. Used to derive a
# lower bound on the token count: ``tokens >= bytes / MAX_BYTES_PER_TOKEN``.
MAX_BYTES_PER_TOKEN = 4

# A single byte expands into at most this many tokens in practice. Used to
# derive an upper bound on the token count: ``tokens <= bytes * MAX_TOKENS_PER_BYTE``.
MAX_TOKENS_PER_BYTE = 4

# Foreign models tokenize more aggressively than the OpenAI encodings, so the
# count is inflated before being compared against the budget.
FOREIGN_MODEL_PENALTY = 1.15

# Average bytes covered by one token when no tokenizer is available. Chosen
# pessimistically (roughly one token per 3 UTF-8 bytes).
HEURISTIC_BYTES_PER_TOKEN = 3

DEEPSEEK_TOKENIZER_ENV = "DEEPSEEK_TOKENIZER_PATH"
DEEPSEEK_OFFLINE_ENV = "DEEPSEEK_TOKENIZER_OFFLINE"

# HuggingFace repository that ships the DeepSeek tokenizer files.
DEEPSEEK_TOKENIZER_REPO = "deepseek-ai/DeepSeek-V3"

# Default location of the tokenizer files, relative to the repository root.
DEFAULT_TOKENIZER_DIR = "data/ds-tokenizer"


def estimate_tokens(text: str) -> int:
    """Byte based estimate used when no real tokenizer is available."""
    if not text:
        return 0
    return math.ceil(len(text.encode("utf-8")) / HEURISTIC_BYTES_PER_TOKEN)


def _load_tiktoken_counter(model: str) -> Optional[Callable[[str], int]]:
    try:
        import tiktoken
    except Exception:
        return None

    encoding = None
    if model:
        try:
            encoding = tiktoken.encoding_for_model(model)
        except Exception:
            encoding = None
    if encoding is None:
        try:
            encoding = tiktoken.get_encoding("o200k_base")
        except Exception:
            return None

    return lambda text: len(encoding.encode(text, disallowed_special=()))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def deepseek_tokenizer_dir() -> Path:
    """Directory holding the DeepSeek tokenizer files."""
    override = (os.getenv(DEEPSEEK_TOKENIZER_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    return _repo_root() / DEFAULT_TOKENIZER_DIR


def _load_local_tokenizer_counter() -> Optional[Callable[[str], int]]:
    """Load the DeepSeek tokenizer, downloading it on first use.

    Set ``DEEPSEEK_TOKENIZER_OFFLINE=1`` to forbid the download; the caller then
    falls back to the byte estimate when the files are not present yet.
    """
    directory = deepseek_tokenizer_dir()
    offline_only = (os.getenv(DEEPSEEK_OFFLINE_ENV) or "").strip() == "1"

    try:
        from transformers import AutoTokenizer
    except Exception:
        return None

    downloaded = directory.is_dir() and any(directory.iterdir())
    if offline_only and not downloaded:
        return None

    try:
        directory.mkdir(parents=True, exist_ok=True)
        tokenizer = AutoTokenizer.from_pretrained(
            DEEPSEEK_TOKENIZER_REPO,
            cache_dir=str(directory),
            local_files_only=offline_only,
        )
    except Exception:
        return None

    return lambda text: len(tokenizer.encode(text, add_special_tokens=False))


def is_deepseek(provider: str, model: str) -> bool:
    """Return ``True`` when the provider/model pair looks like a DeepSeek model."""
    haystack = f"{provider or ''} {model or ''}".lower()
    return "deepseek" in haystack


class TokenCounter:
    """Counts tokens offline, degrading to a byte estimate when needed."""

    def __init__(self, provider: str = "", model: str = ""):
        self.provider = provider or ""
        self.model = model or ""
        self._deepseek = is_deepseek(self.provider, self.model)
        self._counter, self.backend = self._select_backend()

    def _select_backend(self) -> tuple[Callable[[str], int], str]:
        if self._deepseek:
            local = _load_local_tokenizer_counter()
            if local is not None:
                return local, "transformers"
            # No local DeepSeek tokenizer: fall through to the byte estimate.
            return estimate_tokens, "heuristic"

        tiktoken_counter = _load_tiktoken_counter(self.model)
        if tiktoken_counter is not None:
            return tiktoken_counter, "tiktoken"
        return estimate_tokens, "heuristic"

    @property
    def applies_penalty(self) -> bool:
        """Foreign models are counted with a safety margin."""
        if self._deepseek:
            return False
        return self.backend == "tiktoken"

    def count(self, text: str) -> int:
        """Return the number of tokens in ``text``."""
        if not text:
            return 0
        tokens = int(self._counter(text))
        if self.applies_penalty:
            tokens = math.ceil(tokens * FOREIGN_MODEL_PENALTY)
        return tokens


@lru_cache(maxsize=8)
def get_token_counter(provider: str = "", model: str = "") -> TokenCounter:
    """Return a cached counter so each tokenizer is loaded at most once."""
    return TokenCounter(provider=provider, model=model)

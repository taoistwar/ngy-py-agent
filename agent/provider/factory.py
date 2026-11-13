"""Build the adapter a configured provider name resolves to."""

from __future__ import annotations

from typing import Optional

from agent.provider.anthropic import AnthropicProvider
from agent.provider.anthropic_compatible import AnthropicOllamaProvider
from agent.provider.base import BaseProvider, ProviderError
from agent.provider.bedrock import BedrockProvider
from agent.provider.config import ProviderConfig
from agent.provider.gemini import GeminiProvider
from agent.provider.naming import (
    DEFAULT_OPENAI_BASE_URL,
    canonicalize_provider,
    normalize_openai_base_url,
    read_env,
)
from agent.provider.openai import OpenAIProvider


def build_provider(provider: str, config: Optional[ProviderConfig] = None) -> BaseProvider:
    provider = canonicalize_provider(provider)

    if provider == "openai":
        if config is None:
            model = read_env("OLLAMA_MODEL", "qwen3:0.6b")
            base_url = normalize_openai_base_url(
                read_env("OLLAMA_BASE_URL", DEFAULT_OPENAI_BASE_URL)
            )
            config = ProviderConfig(
                provider=provider,
                model=model,
                api_key=read_env("OLLAMA_API_KEY", "ollama"),
                base_url=base_url,
            )
        else:
            config = ProviderConfig(
                provider=config.provider,
                model=config.model,
                api_key=config.api_key,
                base_url=normalize_openai_base_url(
                    config.base_url or DEFAULT_OPENAI_BASE_URL
                ),
                supports_image_input=config.supports_image_input,
            )
        return OpenAIProvider(config)

    if provider == "anthropic":
        if config is None:
            config = ProviderConfig(
                provider=provider,
                model=read_env("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
                api_key=read_env("ANTHROPIC_API_KEY", ""),
                base_url=None,
            )
        return AnthropicProvider(config)

    if provider == "anthropic_compatible":
        if config is None:
            model = read_env("ANTHROPIC_MODEL", read_env("OLLAMA_MODEL", "qwen3:0.6b"))
            config = ProviderConfig(
                provider=provider,
                model=model,
                api_key=read_env("ANTHROPIC_API_KEY", read_env("OLLAMA_API_KEY", "ollama")),
                base_url=normalize_openai_base_url(
                    read_env("OLLAMA_BASE_URL", DEFAULT_OPENAI_BASE_URL)
                ),
            )
        else:
            config = ProviderConfig(
                provider=config.provider,
                model=config.model,
                api_key=config.api_key,
                base_url=normalize_openai_base_url(
                    config.base_url or DEFAULT_OPENAI_BASE_URL
                ),
                supports_image_input=config.supports_image_input,
            )
        return AnthropicOllamaProvider(config)

    if provider == "gemini":
        if config is None:
            config = ProviderConfig(
                provider=provider,
                model=read_env("GEMINI_MODEL", "gemini-1.5-flash"),
                api_key=read_env("GEMINI_API_KEY", ""),
                base_url=None,
            )
        return GeminiProvider(config)

    if provider == "bedrock":
        if config is None:
            config = ProviderConfig(
                provider=provider,
                model=read_env("BEDROCK_MODEL", "anthropic.claude-3-5-sonnet"),
                api_key="",
                base_url=None,
            )
        return BedrockProvider(config)

    raise ProviderError(f"Unsupported provider: {provider}")

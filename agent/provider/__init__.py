"""Provider adapters: one chat-completion surface, several wire formats.

The package is split by responsibility rather than by class:

* :mod:`agent.provider.naming` - the spelling and URL rules every other module shares;
* :mod:`agent.provider.config` - what one configured model needs;
* :mod:`agent.provider.wire` - the OpenAI-shaped message, response and stream delta
  every adapter decodes into;
* :mod:`agent.provider.base` - the provider surface and the non-streaming fallback;
* one module per wire format (``openai``, ``anthropic``, ``anthropic_compatible``,
  ``gemini``, ``bedrock``);
* :mod:`agent.provider.factory` - name to adapter.

Callers keep importing from ``agent.provider``; the re-exports below are the public
surface and the only names other modules should depend on.
"""

from agent.provider.anthropic import AnthropicProvider
from agent.provider.anthropic_compatible import AnthropicOllamaProvider
from agent.provider.base import (
    BaseProvider,
    ChatCompletionProtocol,
    ProviderDependencyError,
    ProviderError,
)
from agent.provider.bedrock import BedrockProvider
from agent.provider.config import ProviderConfig
from agent.provider.factory import build_provider
from agent.provider.gemini import GeminiProvider
from agent.provider.naming import (
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_PROVIDER,
    PROVIDER_ALIASES,
    SUPPORTED_PROVIDERS,
    canonicalize_provider,
    normalize_base_url,
    normalize_openai_base_url,
    normalize_provider_name,
    resolve_tool_provider_for_schemas,
)
from agent.provider.openai import OpenAIProvider
from agent.provider.wire import (
    OpenAIStyleChoice,
    OpenAIStyleFunction,
    OpenAIStyleMessage,
    OpenAIStyleResponse,
    OpenAIStyleToolCall,
    StreamDelta,
)
from agent.rate_limit import provider_throttle

__all__ = [
    "AnthropicOllamaProvider",
    "AnthropicProvider",
    "BaseProvider",
    "BedrockProvider",
    "ChatCompletionProtocol",
    "DEFAULT_OPENAI_BASE_URL",
    "DEFAULT_PROVIDER",
    "GeminiProvider",
    "OpenAIStyleChoice",
    "OpenAIStyleFunction",
    "OpenAIStyleMessage",
    "OpenAIStyleResponse",
    "OpenAIStyleToolCall",
    "OpenAIProvider",
    "PROVIDER_ALIASES",
    "ProviderConfig",
    "ProviderDependencyError",
    "ProviderError",
    "SUPPORTED_PROVIDERS",
    "StreamDelta",
    "build_provider",
    "canonicalize_provider",
    "normalize_base_url",
    "normalize_openai_base_url",
    "normalize_provider_name",
    "provider_throttle",
    "resolve_tool_provider_for_schemas",
]

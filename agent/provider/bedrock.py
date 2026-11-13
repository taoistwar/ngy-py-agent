"""AWS Bedrock placeholder: no runtime call is wired up yet."""

from __future__ import annotations

from typing import Any

from agent.provider.base import BaseProvider, ProviderError
from agent.provider.config import ProviderConfig


class BedrockProvider(BaseProvider):
    provider_name = "bedrock"
    schema_key = "bedrock"
    wire_compatible_with_openai = False

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)

    def chat_completion(self, *args: Any, **kwargs: Any) -> Any:
        raise ProviderError("Bedrock runtime call is not implemented in this loop yet.")

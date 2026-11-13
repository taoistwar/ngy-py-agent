"""What one configured model needs in order to be called."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str
    base_url: Optional[str] = None
    max_input_tokens: int = 0
    # The operator's statement that this model accepts image input (Web Admin ->
    # Models -> Image input). ``agent.vision`` combines it with the wire format
    # before attaching a tool screenshot to the conversation.
    supports_image_input: bool = False

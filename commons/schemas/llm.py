"""Provider endpoints and the models they serve (ADR 0014)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProviderCreateRequest(BaseModel):
    """Create a provider endpoint: where requests go and how often they may go."""

    name: str = Field(min_length=1, max_length=120, description="Display name of the endpoint.")
    protocol: str = Field(
        default="openai-compatible",
        description="Wire protocol: openai / anthropic / anthropic-compatible / gemini.",
    )
    base_url: str = Field(
        default="",
        max_length=1024,
        description="Endpoint base URL; empty falls back to the protocol's default endpoint.",
    )
    api_key: str = Field(default="", description="API key sent to this endpoint.")
    rpm_limit: int = Field(
        default=0,
        ge=0,
        description="Requests per minute for this endpoint; 0 means unlimited.",
    )


class ProviderUpdateRequest(BaseModel):
    """Partial update of a provider endpoint."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    protocol: str | None = None
    base_url: str | None = Field(default=None, max_length=1024)
    api_key: str | None = None
    rpm_limit: int | None = Field(default=None, ge=0)


class ProviderItemResponse(BaseModel):
    """One provider endpoint, as the management page shows it."""

    provider_id: str
    name: str
    protocol: str
    base_url: str = ""
    api_key: str = ""
    rpm_limit: int = 0
    model_count: int = 0
    created_at: datetime
    updated_at: datetime


class ProviderListResponse(BaseModel):
    """Configured provider endpoints."""

    providers: list[ProviderItemResponse]


class ModelUpsertRequest(BaseModel):
    """Create a model configuration on an existing provider endpoint."""

    name: str = Field(
        min_length=1,
        max_length=200,
        description="Model name sent to the provider, e.g. qwen3:0.6b.",
    )
    provider_id: str = Field(
        min_length=1,
        description="Provider endpoint this model runs on; its URL, key and RPM apply.",
    )
    supports_tool_calls: bool = Field(default=True, description="Whether tools are enabled.")
    supports_image_input: bool = Field(
        default=False, description="Whether image input is supported."
    )
    thinking_mode: bool = Field(default=False, description="Whether thinking mode is enabled.")
    max_input_tokens: int = Field(default=0, ge=0, description="Input token limit, 0 means unset.")
    max_output_tokens: int = Field(
        default=0, ge=0, description="Output token limit, 0 means unset."
    )


class ModelUpdateRequest(BaseModel):
    """Partial update of a model configuration."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    provider_id: str | None = Field(default=None, min_length=1)
    supports_tool_calls: bool | None = None
    supports_image_input: bool | None = None
    thinking_mode: bool | None = None
    max_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)


class ModelItemResponse(BaseModel):
    """Model configuration item, with the endpoint it resolves to."""

    model_id: str
    name: str
    provider_id: str
    # Resolved from the provider so a client can render one row without a second call.
    provider_name: str = ""
    protocol: str = ""
    base_url: str = ""
    supports_tool_calls: bool = True
    supports_image_input: bool = False
    thinking_mode: bool = False
    max_input_tokens: int = 0
    max_output_tokens: int = 0
    created_at: datetime
    updated_at: datetime


class ModelListResponse(BaseModel):
    """Model list response."""

    models: list[ModelItemResponse]

"""Provider endpoints and the models served by them.

Two resources, one module: a model is meaningless without its provider, and every write
here has the same side effect - the process-wide RPM limiter is re-pointed at the stored
endpoints, so a limit takes effect on the next request instead of the next restart
(ADR 0014).

Validation is done here rather than in the schemas because it needs the store: a
protocol is only usable if an adapter exists for it, a model's provider has to exist,
and two providers must not claim the same endpoint - one endpoint is one budget, and two
rows pointing at it would silently leave whichever configured last in charge.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from agent.provider import SUPPORTED_PROVIDERS, canonicalize_provider
from agent.rate_limit import RPM_LIMIT_MAX, bucket_key, provider_throttle
from commons import state
from commons.schemas import (
    ModelItemResponse,
    ModelListResponse,
    ModelUpdateRequest,
    ModelUpsertRequest,
    ProviderCreateRequest,
    ProviderItemResponse,
    ProviderListResponse,
    ProviderUpdateRequest,
)

router = APIRouter()

# The protocols whose adapter posts to the configured base URL instead of a fixed one,
# so an empty URL is a configuration error rather than "use the default".
BASE_URL_REQUIRED_PROTOCOLS = ("anthropic_compatible",)


def sync_provider_throttle() -> None:
    """Point the process-wide limiter at the stored endpoints; called on every write."""
    provider_throttle.configure_endpoints(state.monitor_store.llm.list_providers())


def _protocol(raw: Any) -> str:
    protocol = canonicalize_provider(raw)
    if protocol not in SUPPORTED_PROVIDERS:
        # Rejected, not dropped: a row saved under a protocol nobody can build would
        # look configured while every task for it failed at build time.
        raise HTTPException(status_code=400, detail=f"Unknown provider protocol '{raw}'.")
    return protocol


def _base_url(raw: Any) -> str:
    return str(raw or "").strip()


def _validate_endpoint(protocol: str, base_url: str, rpm_limit: int) -> None:
    if protocol in BASE_URL_REQUIRED_PROTOCOLS and not base_url:
        raise HTTPException(
            status_code=400,
            detail=f"Provider protocol '{protocol}' requires a base URL.",
        )
    if rpm_limit < 0 or rpm_limit > RPM_LIMIT_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"rpm_limit must be between 0 and {RPM_LIMIT_MAX}.",
        )


def _ensure_endpoint_is_free(protocol: str, base_url: str, ignore_id: str = "") -> None:
    """One endpoint, one budget: refuse a second row for the same protocol + URL.

    The limiter is keyed by exactly that pair, so two rows would overwrite each other
    and the operator would have no way to tell which one is in force.
    """
    key = bucket_key(protocol, base_url)
    for existing in state.monitor_store.llm.list_providers():
        if ignore_id and existing["provider_id"] == ignore_id:
            continue
        if bucket_key(existing["protocol"], existing["base_url"]) == key:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Provider '{existing['name']}' already uses this endpoint; "
                    "one endpoint has one request budget."
                ),
            )


def _require_provider(provider_id: str) -> str:
    if state.monitor_store.llm.get_provider(provider_id) is None:
        # A model without a working endpoint cannot be built, so the reference is
        # refused at write time instead of failing every task that selects it.
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider_id}'.")
    return provider_id


# ------------------------------------------------------------------- providers


@router.get("/api/providers", response_model=ProviderListResponse)
async def list_providers() -> ProviderListResponse:
    providers = state.monitor_store.llm.list_providers()
    return ProviderListResponse(providers=[ProviderItemResponse(**item) for item in providers])


@router.post("/api/providers", response_model=ProviderItemResponse)
async def create_provider(payload: ProviderCreateRequest) -> ProviderItemResponse:
    data = payload.model_dump()
    data["protocol"] = _protocol(data.get("protocol"))
    data["base_url"] = _base_url(data.get("base_url"))
    _validate_endpoint(data["protocol"], data["base_url"], data["rpm_limit"])
    _ensure_endpoint_is_free(data["protocol"], data["base_url"])
    created = state.monitor_store.llm.create_provider(data)
    sync_provider_throttle()
    return ProviderItemResponse(**created)


@router.put("/api/providers/{provider_id}", response_model=ProviderItemResponse)
async def update_provider(
    provider_id: str, payload: ProviderUpdateRequest
) -> ProviderItemResponse:
    current = state.monitor_store.llm.get_provider(provider_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Provider not found.")
    changes = payload.model_dump(exclude_unset=True)
    protocol = _protocol(changes.get("protocol", current["protocol"]))
    base_url = _base_url(changes.get("base_url", current["base_url"]))
    rpm_limit = int(changes.get("rpm_limit", current["rpm_limit"]) or 0)
    _validate_endpoint(protocol, base_url, rpm_limit)
    _ensure_endpoint_is_free(protocol, base_url, ignore_id=provider_id)
    changes.update(protocol=protocol, base_url=base_url)
    updated = state.monitor_store.llm.update_provider(provider_id, changes)
    if updated is None:
        raise HTTPException(status_code=404, detail="Provider not found.")
    sync_provider_throttle()
    return ProviderItemResponse(**updated)


@router.delete("/api/providers/{provider_id}")
async def delete_provider(provider_id: str) -> dict[str, Any]:
    used_by = state.monitor_store.llm.model_count(provider_id)
    if used_by > 0:
        # Refused rather than cascaded: deleting a provider would silently leave its
        # models pointing at nothing, and a task that selects one would fail later.
        raise HTTPException(
            status_code=409,
            detail=f"Provider still has {used_by} model(s); move or delete them first.",
        )
    if not state.monitor_store.llm.delete_provider(provider_id):
        raise HTTPException(status_code=404, detail="Provider not found.")
    sync_provider_throttle()
    return {"provider_id": provider_id, "deleted": True}


# ---------------------------------------------------------------------- models


@router.get("/api/models", response_model=ModelListResponse)
async def list_models() -> ModelListResponse:
    models = state.monitor_store.llm.list_models()
    return ModelListResponse(models=[ModelItemResponse(**item) for item in models])


@router.post("/api/models", response_model=ModelItemResponse)
async def create_model(payload: ModelUpsertRequest) -> ModelItemResponse:
    data = payload.model_dump()
    data["provider_id"] = _require_provider(data["provider_id"])
    created = state.monitor_store.llm.create_model(data)
    return ModelItemResponse(**created)


@router.put("/api/models/{model_id}", response_model=ModelItemResponse)
async def update_model(model_id: str, payload: ModelUpdateRequest) -> ModelItemResponse:
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("provider_id"):
        changes["provider_id"] = _require_provider(changes["provider_id"])
    updated = state.monitor_store.llm.update_model(model_id, changes)
    if updated is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    return ModelItemResponse(**updated)


@router.delete("/api/models/{model_id}")
async def delete_model(model_id: str) -> dict[str, Any]:
    if not state.monitor_store.llm.delete_model(model_id):
        raise HTTPException(status_code=404, detail="Model not found.")
    return {"model_id": model_id, "deleted": True}

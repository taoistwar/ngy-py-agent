"""Turn a failed LLM request into one actionable message.

The model endpoint is user configuration (Model Management in the web admin, ``.env``
for the CLI), so "the service is not running" or "HTTP 401" is an ordinary condition
an operator fixes. The agent process itself is healthy, and the rest of the app must
keep working: the loop therefore wraps a failed request in :class:`LLMCallError`
instead of letting the SDK's exception (and its traceback) escape.

Classification is by exception class name because the provider SDKs and ``httpx`` are
optional at runtime, so their exception modules cannot be imported unconditionally.
"""

from __future__ import annotations

from typing import Any, Set

from agent.provider import ProviderError

# Names as they appear in the MRO of the SDK exceptions. ``openai`` and ``anthropic``
# use the same names for the same failures, which is what lets one table cover both.
_STATUS_ERRORS: Set[str] = {"APIStatusError", "HTTPStatusError"}
# Checked before connection: ``APITimeoutError`` subclasses ``APIConnectionError``.
_TIMEOUT_ERRORS: Set[str] = {"APITimeoutError", "TimeoutException", "ReadTimeout"}
_CONNECTION_ERRORS: Set[str] = {
    "APIConnectionError",
    "ConnectError",
    "ConnectionError",
    "NewConnectionError",
}

_MAX_DETAIL = 300


class LLMCallError(ProviderError):
    """A failed model request, described in terms of what to fix."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        model: str = "",
        endpoint: str = "",
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.endpoint = endpoint
        self.detail = detail


def _config_value(provider: Any, name: str) -> str:
    config = getattr(provider, "config", None)
    return str(getattr(config, name, "") or "")


def _kind(exc: BaseException) -> str:
    names = {cls.__name__ for cls in type(exc).__mro__}
    if names & _STATUS_ERRORS:
        return "status"
    if names & _TIMEOUT_ERRORS:
        return "timeout"
    if names & _CONNECTION_ERRORS:
        return "connection"
    return "unknown"


def _short(text: Any) -> str:
    collapsed = " ".join(str(text or "").split())
    return collapsed[:_MAX_DETAIL]


def _root_cause(exc: BaseException) -> str:
    """Innermost message of the chain: the SDK's wrapper hides the OS error."""
    seen = set()
    current = exc
    while True:
        seen.add(id(current))
        cause = current.__cause__ or current.__context__
        if cause is None or id(cause) in seen:
            break
        current = cause
    return _short(current) or type(current).__name__


def describe_llm_failure(exc: BaseException, provider: Any = None) -> LLMCallError:
    """Phrase a failed request as a fixable model-configuration problem."""
    provider_name = _config_value(provider, "provider")
    model = _config_value(provider, "model")
    endpoint = _config_value(provider, "base_url")
    location = endpoint or "the model service"
    target = f"(provider={provider_name or 'unknown'}, model={model or 'unknown'})"
    kind = _kind(exc)

    if kind == "status":
        status = getattr(exc, "status_code", None)
        code = f"HTTP {status}" if status else "an error status"
        detail = _short(getattr(exc, "message", "")) or _short(exc)
        message = (
            f"{location} returned {code} for {target}. Check the API key, the model "
            f"name and the endpoint in the model configuration. Detail: {detail}"
        )
        return LLMCallError(
            message,
            provider=provider_name,
            model=model,
            endpoint=endpoint,
            detail=detail,
        )

    if kind == "timeout":
        cause = _root_cause(exc)
        message = (
            f"Request to {location} timed out for {target}. The service may be "
            f"overloaded or unreachable. Cause: {cause}"
        )
        return LLMCallError(
            message,
            provider=provider_name,
            model=model,
            endpoint=endpoint,
            detail=cause,
        )

    if kind == "connection":
        cause = _root_cause(exc)
        message = (
            f"Cannot reach {location} for {target}. Check that the model service is "
            f"running and that the endpoint configured in Model Management or .env is "
            f"correct. Cause: {cause}"
        )
        return LLMCallError(
            message,
            provider=provider_name,
            model=model,
            endpoint=endpoint,
            detail=cause,
        )

    detail = _short(exc)
    message = f"Model request failed for {target}: {detail}"
    return LLMCallError(
        message,
        provider=provider_name,
        model=model,
        endpoint=endpoint,
        detail=detail,
    )

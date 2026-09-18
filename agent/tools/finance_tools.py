"""Currency conversion tools backed by live exchange rates.

Rates come from the free, key-less open.er-api.com endpoint:
https://www.exchangerate-api.com/docs/free

Failures raise :class:`FinanceToolError` rather than falling back to built-in
reference numbers, so a returned amount is always a live conversion.
"""

from datetime import datetime, timezone
from typing import Dict

import requests

EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/{base}"
REQUEST_TIMEOUT_SECONDS = 5


class FinanceToolError(RuntimeError):
    """Raised when a live exchange rate cannot be retrieved."""


def convert_currency(amount: float, from_currency: str, to_currency: str) -> Dict:
    """Convert ``amount`` from ``from_currency`` to ``to_currency`` at the live rate."""
    from_code = _normalize_code(from_currency)
    to_code = _normalize_code(to_currency)

    rates = _fetch_rates(from_code)
    if to_code not in rates:
        raise FinanceToolError(f"Unsupported currency: {to_code}")

    rate = rates[to_code]
    if not isinstance(rate, (int, float)):
        raise FinanceToolError(f"Exchange rate for {to_code} is not numeric: {rate!r}")

    return {
        "original_amount": amount,
        "from_currency": from_code,
        "to_currency": to_code,
        "converted_amount": round(amount * rate, 2),
        "exchange_rate": round(rate, 4),
        "source": "open.er-api.com",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _normalize_code(code: str) -> str:
    """Normalize user supplied codes such as ``$``/``S$`` into ISO 4217 codes."""
    normalized = str(code).upper()
    return normalized.replace("S$", "SGD").replace("$", "USD")


def _fetch_rates(base_code: str) -> Dict:
    """Return the exchange-rate table with ``base_code`` as the base currency."""
    try:
        response = requests.get(
            EXCHANGE_RATE_URL.format(base=base_code),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise FinanceToolError(
            f"Exchange rate request failed for {base_code}: {exc}"
        ) from exc
    except ValueError as exc:
        raise FinanceToolError(
            f"Exchange rate response was not valid JSON for {base_code}: {exc}"
        ) from exc

    if not isinstance(payload, dict) or payload.get("result") != "success":
        error_type = payload.get("error-type", "unknown") if isinstance(payload, dict) else "unknown"
        raise FinanceToolError(f"Unsupported currency: {base_code} (API error: {error_type})")

    rates = payload.get("rates")
    if not isinstance(rates, dict):
        raise FinanceToolError(f"Exchange rate response for {base_code} had no rates table")
    return rates

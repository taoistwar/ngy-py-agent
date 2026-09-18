"""Currency conversion tools."""

from datetime import datetime
from typing import Dict


def convert_currency(amount: float, from_currency: str, to_currency: str) -> Dict:
    """
    Convert currency using live exchange rates (simulated)
    """
    # Normalize currency codes
    from_currency = from_currency.upper().replace("S$", "SGD").replace("$", "USD")
    to_currency = to_currency.upper().replace("S$", "SGD").replace("$", "USD")

    # Simulated exchange rates
    exchange_rates = {
        "USD": 1.0,
        "EUR": 0.92,
        "GBP": 0.79,
        "JPY": 149.50,
        "CNY": 7.24,
        "CAD": 1.36,
        "AUD": 1.53,
        "CHF": 0.88,
        "INR": 83.12,
        "SGD": 1.34,
        "KRW": 1330.50,
        "MXN": 17.10,
    }

    if from_currency not in exchange_rates or to_currency not in exchange_rates:
        return {"error": f"Unsupported currency: {from_currency} or {to_currency}"}

    # Convert to USD first, then to target currency
    usd_amount = amount / exchange_rates[from_currency]
    converted_amount = usd_amount * exchange_rates[to_currency]

    return {
        "original_amount": amount,
        "from_currency": from_currency,
        "to_currency": to_currency,
        "converted_amount": round(converted_amount, 2),
        "exchange_rate": round(exchange_rates[to_currency] / exchange_rates[from_currency], 4),
        "timestamp": datetime.now().isoformat(),
    }

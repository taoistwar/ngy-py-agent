"""Tests for the live currency conversion tool.

Run from the repository root::

    uv run python test/tools/convert_currency/convert_currency_test.py -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import requests

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.convert_currency import (  # noqa: E402
    FinanceToolError,
    convert_currency,
)


def _fake_response(payload):
    response = mock.MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _rates_payload(rates):
    return {"result": "success", "base_code": "USD", "rates": rates}


class ConvertCurrencyTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("agent.tools.convert_currency.tool.requests.get")
        self.get = patcher.start()
        self.addCleanup(patcher.stop)

    def test_converts_using_live_rate(self):
        self.get.return_value = _fake_response(_rates_payload({"EUR": 0.92}))

        result = convert_currency(100, "USD", "EUR")

        self.assertEqual(result["converted_amount"], 92.0)
        self.assertEqual(result["exchange_rate"], 0.92)
        self.assertEqual(result["source"], "open.er-api.com")

    def test_queries_api_with_source_currency_as_base(self):
        self.get.return_value = _fake_response(_rates_payload({"USD": 1.2}))

        result = convert_currency(50, "EUR", "USD")

        self.assertEqual(result["converted_amount"], 60.0)
        self.assertIn("/latest/EUR", self.get.call_args.args[0])

    def test_normalizes_dollar_symbols(self):
        self.get.return_value = _fake_response(_rates_payload({"SGD": 1.34}))

        result = convert_currency(100, "$", "S$")

        self.assertEqual(result["from_currency"], "USD")
        self.assertEqual(result["to_currency"], "SGD")

    def test_unsupported_target_currency_raises(self):
        self.get.return_value = _fake_response(_rates_payload({"EUR": 0.92}))

        with self.assertRaises(FinanceToolError) as ctx:
            convert_currency(100, "USD", "XYZ")

        self.assertIn("Unsupported currency: XYZ", str(ctx.exception))

    def test_unsupported_base_currency_raises(self):
        self.get.return_value = _fake_response(
            {"result": "error", "error-type": "unsupported-code"}
        )

        with self.assertRaises(FinanceToolError) as ctx:
            convert_currency(100, "XYZ", "USD")

        self.assertIn("unsupported-code", str(ctx.exception))

    def test_network_failure_raises_instead_of_using_builtin_rates(self):
        self.get.side_effect = requests.ConnectionError("connection refused")

        with self.assertRaises(FinanceToolError) as ctx:
            convert_currency(100, "USD", "EUR")

        self.assertIn("Exchange rate request failed", str(ctx.exception))

    def test_http_error_raises(self):
        response = _fake_response(_rates_payload({"EUR": 0.92}))
        response.raise_for_status.side_effect = requests.HTTPError("503 Service Unavailable")
        self.get.return_value = response

        with self.assertRaises(FinanceToolError):
            convert_currency(100, "USD", "EUR")

    def test_broken_json_raises(self):
        response = mock.MagicMock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("Expecting value")
        self.get.return_value = response

        with self.assertRaises(FinanceToolError) as ctx:
            convert_currency(100, "USD", "EUR")

        self.assertIn("not valid JSON", str(ctx.exception))

    def test_missing_rates_table_raises(self):
        self.get.return_value = _fake_response({"result": "success"})

        with self.assertRaises(FinanceToolError) as ctx:
            convert_currency(100, "USD", "EUR")

        self.assertIn("no rates table", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

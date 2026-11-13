"""Per-endpoint request rate limiting (RPM).

Run from the repository root::

    uv run python test/rate_limit_test.py -v

The clock and the sleep are injected, so the tests describe the policy ("the third
request waits for the window") instead of waiting a real minute for it. The bucket is
the endpoint - provider plus base URL - so every case names both (ADR 0014).
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent import provider as provider_module  # noqa: E402
from agent.provider import ProviderConfig, normalize_base_url  # noqa: E402
from agent.rate_limit import (  # noqa: E402
    ProviderThrottle,
    RpmLimitError,
    bucket_key,
)

LOCAL_URL = "http://127.0.0.1:11434/v1"
GATEWAY_URL = "https://gateway.example.com/v1"


class _FakeClock:
    """A clock that only moves when something sleeps."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds


def _throttle(endpoints=None, wait_cap=60.0):
    """A limiter configured with ``{(provider, base_url): rpm}``."""
    clock = _FakeClock()
    limiter = ProviderThrottle(
        clock=clock.monotonic, sleep=clock.sleep, wait_cap_seconds=wait_cap
    )
    limiter.configure(
        {bucket_key(provider, url): limit for (provider, url), limit in (endpoints or {}).items()}
    )
    return limiter, clock


class ProviderThrottleTest(unittest.TestCase):
    def test_an_unconfigured_endpoint_never_waits(self):
        limiter, clock = _throttle()

        waits = [limiter.acquire("openai", LOCAL_URL) for _ in range(50)]

        self.assertEqual(waits, [0.0] * 50)
        self.assertEqual(clock.sleeps, [])

    def test_requests_over_the_limit_wait_for_the_window(self):
        limiter, clock = _throttle({("openai", LOCAL_URL): 2})

        self.assertEqual(limiter.acquire("openai", LOCAL_URL), 0.0)
        self.assertEqual(limiter.acquire("openai", LOCAL_URL), 0.0)
        waited = limiter.acquire("openai", LOCAL_URL)

        self.assertAlmostEqual(waited, 60.0, places=3)
        self.assertEqual(len(clock.sleeps), 1)
        # The wait pushed the two earlier requests out of the window, so the budget
        # is free again - a sliding window does not make the caller wait twice.
        self.assertEqual(limiter.acquire("openai", LOCAL_URL), 0.0)

    def test_a_window_that_has_passed_frees_the_slot_without_waiting(self):
        limiter, clock = _throttle({("openai", LOCAL_URL): 1})

        limiter.acquire("openai", LOCAL_URL)
        clock.advance(61.0)

        self.assertEqual(limiter.acquire("openai", LOCAL_URL), 0.0)

    def test_a_wait_longer_than_the_cap_is_an_error(self):
        limiter, clock = _throttle({("openai", LOCAL_URL): 1}, wait_cap=5.0)

        limiter.acquire("openai", LOCAL_URL)

        with self.assertRaises(RpmLimitError) as caught:
            limiter.acquire("openai", LOCAL_URL)
        message = str(caught.exception)
        self.assertIn("openai", message)
        # The endpoint, not just the provider, has to be in the message: the same
        # provider name can point at several servers.
        self.assertIn(LOCAL_URL, message)
        self.assertEqual(clock.sleeps, [])

    def test_two_base_urls_of_one_provider_are_two_buckets(self):
        limiter, _ = _throttle({("openai", LOCAL_URL): 1, ("openai", GATEWAY_URL): 1})

        limiter.acquire("openai", LOCAL_URL)

        self.assertEqual(limiter.acquire("openai", GATEWAY_URL), 0.0)

    def test_two_providers_on_one_url_are_two_buckets(self):
        limiter, _ = _throttle({("openai", LOCAL_URL): 1, ("anthropic", LOCAL_URL): 1})

        limiter.acquire("openai", LOCAL_URL)

        self.assertEqual(limiter.acquire("anthropic", LOCAL_URL), 0.0)

    def test_models_on_one_endpoint_share_one_budget(self):
        limiter, _ = _throttle({("openai", LOCAL_URL): 1}, wait_cap=5.0)

        # Both requests come from the same connection, so the second one is the
        # one that has to wait - whichever model name it carries.
        limiter.acquire("openai", LOCAL_URL)

        with self.assertRaises(RpmLimitError):
            limiter.acquire("openai", LOCAL_URL)

    def test_provider_spellings_share_one_bucket(self):
        limiter, _ = _throttle({("openai", LOCAL_URL): 1}, wait_cap=5.0)

        limiter.acquire("openai", LOCAL_URL)

        with self.assertRaises(RpmLimitError):
            # ``openai-compatible`` is the same provider, so the same budget.
            limiter.acquire("openai-compatible", LOCAL_URL)

    def test_a_url_without_the_v1_suffix_is_the_same_bucket(self):
        limiter, _ = _throttle({("openai", "http://127.0.0.1:11434"): 1}, wait_cap=5.0)

        limiter.acquire("openai", LOCAL_URL)

        with self.assertRaises(RpmLimitError):
            # The adapter appends ``/v1``, so a limit saved without it must still
            # apply to the URL the request is actually sent to.
            limiter.acquire("openai", "http://127.0.0.1:11434")

    def test_configure_endpoints_reads_stored_records(self):
        limiter, _ = _throttle()
        limiter.configure_endpoints(
            [
                {"protocol": "openai", "base_url": LOCAL_URL, "rpm_limit": 7},
                {"protocol": "anthropic", "base_url": "", "rpm_limit": 0},
            ]
        )

        self.assertEqual(limiter.limit_for("openai", LOCAL_URL), 7)
        self.assertEqual(limiter.limit_for("anthropic", ""), 0)

    def test_configuring_zero_lifts_the_limit(self):
        limiter, clock = _throttle({("openai", LOCAL_URL): 1})

        limiter.acquire("openai", LOCAL_URL)
        limiter.configure({bucket_key("openai", LOCAL_URL): 0})

        self.assertEqual(limiter.acquire("openai", LOCAL_URL), 0.0)
        self.assertEqual(clock.sleeps, [])

    def test_the_last_wait_is_reported_once_per_request(self):
        limiter, _ = _throttle({("openai", LOCAL_URL): 1})

        limiter.acquire("openai", LOCAL_URL)
        self.assertEqual(limiter.take_last_wait(), 0.0)

        limiter.acquire("openai", LOCAL_URL)
        self.assertAlmostEqual(limiter.take_last_wait(), 60.0, places=3)
        self.assertEqual(limiter.take_last_wait(), 0.0)

    def test_negative_values_are_treated_as_unlimited(self):
        limiter, _ = _throttle({("openai", LOCAL_URL): -5})

        self.assertEqual(limiter.acquire("openai", LOCAL_URL), 0.0)
        self.assertEqual(limiter.limit_for("openai", LOCAL_URL), 0)

    def test_normalize_base_url_keeps_one_form_per_endpoint(self):
        for raw in ("http://127.0.0.1:11434", "http://127.0.0.1:11434/", LOCAL_URL):
            with self.subTest(url=raw):
                self.assertEqual(normalize_base_url("openai", raw), LOCAL_URL)
        # A fixed-endpoint protocol does not rewrite anything.
        self.assertEqual(normalize_base_url("anthropic", " https://api.anthropic.com "), "https://api.anthropic.com")


class ProviderHookTest(unittest.TestCase):
    """Every wire adapter must spend the budget *before* it talks to the network."""

    CASES = (
        ("OpenAIProvider", "openai"),
        ("AnthropicProvider", "anthropic"),
        ("AnthropicOllamaProvider", "anthropic_compatible"),
        ("GeminiProvider", "gemini"),
    )

    def test_the_adapter_throttles_first(self):
        for class_name, provider_name in self.CASES:
            with self.subTest(provider=provider_name):
                adapter_class = getattr(provider_module, class_name)
                adapter = adapter_class.__new__(adapter_class)
                adapter.config = ProviderConfig(
                    provider=provider_name, model="m", api_key="k", base_url="http://localhost"
                )
                with patch.object(
                    provider_module.BaseProvider, "_throttle", autospec=True
                ) as throttle, patch("requests.post") as post:
                    post.side_effect = OSError("no network in tests")
                    try:
                        adapter.chat_completion(messages=[{"role": "user", "content": "hi"}])
                    except Exception:  # noqa: BLE001 - the adapter has no client here
                        pass
                throttle.assert_called_once()

    def test_base_provider_throttle_uses_the_configured_endpoint(self):
        adapter = provider_module.BaseProvider(
            ProviderConfig(
                provider="gemini", model="m", api_key="k", base_url="https://gemini.example"
            )
        )

        with patch.object(provider_module.provider_throttle, "acquire") as acquire:
            adapter._throttle()

        acquire.assert_called_once_with("gemini", "https://gemini.example")


class ThrottleReportTest(unittest.TestCase):
    """The loop has to say when it rationed itself, or it looks like a slow model."""

    def _report(self, waited, limit=6):
        from agent.agent_loop.model_turn import _report_throttle_wait

        events = []
        provider = SimpleNamespace(
            config=SimpleNamespace(provider="openai", model="fake-model", base_url=LOCAL_URL)
        )
        span = MagicMock()
        with patch.object(
            provider_module.provider_throttle, "take_last_wait", return_value=waited
        ), patch.object(
            provider_module.provider_throttle, "limit_for", return_value=limit
        ) as limit_for:
            _report_throttle_wait(
                span, provider, 3, lambda task_id, event: events.append(event), "task-1"
            )
        return span, events, limit_for

    def test_a_wait_becomes_a_debug_event_and_a_span_attribute(self):
        from agent.models import EventCategory

        span, events, limit_for = self._report(2.5)

        span.set_attribute.assert_called_once_with("llm.rpm.wait_ms", 2500)
        limit_for.assert_called_once_with("openai", LOCAL_URL)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].category, EventCategory.DEBUG)
        self.assertEqual(events[0].data["step"], 3)
        self.assertEqual(events[0].data["provider"], "openai")
        self.assertEqual(events[0].data["base_url"], LOCAL_URL)
        self.assertEqual(events[0].data["waited_ms"], 2500)
        self.assertEqual(events[0].data["rpm_limit"], 6)

    def test_no_wait_reports_nothing(self):
        span, events, _ = self._report(0.0)

        span.set_attribute.assert_not_called()
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()

"""Per-provider request rate limiting (RPM).

Run from the repository root::

    uv run python test/rate_limit_test.py -v

The clock and the sleep are injected, so the tests describe the policy ("the third
request waits for the window") instead of waiting a real minute for it.
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
from agent.provider import ProviderConfig  # noqa: E402
from agent.rate_limit import (  # noqa: E402
    ProviderThrottle,
    RpmLimitError,
    parse_rpm_limits,
)


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


def _throttle(limits=None, wait_cap=60.0):
    clock = _FakeClock()
    limiter = ProviderThrottle(
        clock=clock.monotonic, sleep=clock.sleep, wait_cap_seconds=wait_cap
    )
    limiter.configure(limits or {})
    return limiter, clock


class ProviderThrottleTest(unittest.TestCase):
    def test_an_unconfigured_provider_never_waits(self):
        limiter, clock = _throttle()

        waits = [limiter.acquire("openai") for _ in range(50)]

        self.assertEqual(waits, [0.0] * 50)
        self.assertEqual(clock.sleeps, [])

    def test_requests_over_the_limit_wait_for_the_window(self):
        limiter, clock = _throttle({"openai": 2})

        self.assertEqual(limiter.acquire("openai"), 0.0)
        self.assertEqual(limiter.acquire("openai"), 0.0)
        waited = limiter.acquire("openai")

        self.assertAlmostEqual(waited, 60.0, places=3)
        self.assertEqual(len(clock.sleeps), 1)
        # The wait pushed the two earlier requests out of the window, so the budget
        # is free again - a sliding window does not make the caller wait twice.
        self.assertEqual(limiter.acquire("openai"), 0.0)

    def test_a_window_that_has_passed_frees_the_slot_without_waiting(self):
        limiter, clock = _throttle({"openai": 1})

        limiter.acquire("openai")
        clock.advance(61.0)

        self.assertEqual(limiter.acquire("openai"), 0.0)

    def test_a_wait_longer_than_the_cap_is_an_error(self):
        limiter, clock = _throttle({"openai": 1}, wait_cap=5.0)

        limiter.acquire("openai")

        with self.assertRaises(RpmLimitError) as caught:
            limiter.acquire("openai")
        self.assertIn("openai", str(caught.exception))
        self.assertIn("1", str(caught.exception))
        self.assertEqual(clock.sleeps, [])

    def test_each_provider_has_its_own_bucket(self):
        limiter, _ = _throttle({"openai": 1, "anthropic": 1})

        limiter.acquire("openai")

        self.assertEqual(limiter.acquire("anthropic"), 0.0)

    def test_provider_spellings_share_one_bucket(self):
        limiter, _ = _throttle({"openai": 1}, wait_cap=5.0)

        limiter.acquire("openai")

        with self.assertRaises(RpmLimitError):
            # ``openai-compatible`` is the same provider, so the same budget.
            limiter.acquire("openai-compatible")

    def test_configuring_zero_lifts_the_limit(self):
        limiter, clock = _throttle({"openai": 1})

        limiter.acquire("openai")
        limiter.configure({"openai": 0})

        self.assertEqual(limiter.acquire("openai"), 0.0)
        self.assertEqual(clock.sleeps, [])

    def test_the_last_wait_is_reported_once_per_request(self):
        limiter, _ = _throttle({"openai": 1})

        limiter.acquire("openai")
        self.assertEqual(limiter.take_last_wait(), 0.0)

        limiter.acquire("openai")
        self.assertAlmostEqual(limiter.take_last_wait(), 60.0, places=3)
        self.assertEqual(limiter.take_last_wait(), 0.0)

    def test_parse_rpm_limits_reads_pairs_and_ignores_junk(self):
        parsed = parse_rpm_limits("openai=60, anthropic = 20 ,, gemini=x, =5, bedrock=0")

        self.assertEqual(parsed, {"openai": 60, "anthropic": 20, "bedrock": 0})

    def test_negative_values_are_treated_as_unlimited(self):
        limiter, _ = _throttle({"openai": -5})

        self.assertEqual(limiter.acquire("openai"), 0.0)
        self.assertEqual(limiter.limit_for("openai"), 0)


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

    def test_base_provider_throttle_uses_the_configured_provider(self):
        adapter = provider_module.BaseProvider(
            ProviderConfig(provider="gemini", model="m", api_key="k")
        )

        with patch.object(provider_module.provider_throttle, "acquire") as acquire:
            adapter._throttle()

        acquire.assert_called_once_with("gemini")


class ThrottleReportTest(unittest.TestCase):
    """The loop has to say when it rationed itself, or it looks like a slow model."""

    def _report(self, waited, limit=6):
        from agent.agent_loop.steps import _report_throttle_wait

        events = []
        provider = SimpleNamespace(
            config=SimpleNamespace(provider="openai", model="fake-model")
        )
        span = MagicMock()
        with patch.object(
            provider_module.provider_throttle, "take_last_wait", return_value=waited
        ), patch.object(
            provider_module.provider_throttle, "limit_for", return_value=limit
        ):
            _report_throttle_wait(
                span, provider, 3, lambda task_id, event: events.append(event), "task-1"
            )
        return span, events

    def test_a_wait_becomes_a_debug_event_and_a_span_attribute(self):
        from agent.models import EventCategory

        span, events = self._report(2.5)

        span.set_attribute.assert_called_once_with("llm.rpm.wait_ms", 2500)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].category, EventCategory.DEBUG)
        self.assertEqual(events[0].data["step"], 3)
        self.assertEqual(events[0].data["provider"], "openai")
        self.assertEqual(events[0].data["waited_ms"], 2500)
        self.assertEqual(events[0].data["rpm_limit"], 6)

    def test_no_wait_reports_nothing(self):
        span, events = self._report(0.0)

        span.set_attribute.assert_not_called()
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()

"""A failed model request must read as configuration, not as a crash.

The model endpoint is chosen in Model Management (or ``.env`` for the CLI), so "cannot
connect" and "HTTP 401" are ordinary, fixable conditions. These tests pin the
classification and the loop's promise: one actionable line, one error event, no raw
SDK traceback.

Run from the repository root::

    uv run python test/llm_errors_test.py -v
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.agent_loop import run_react_loop  # noqa: E402
from agent.llm_errors import LLMCallError, describe_llm_failure  # noqa: E402
from agent.models import EventCategory  # noqa: E402
from agent.provider import ProviderError  # noqa: E402


# SDK exception shapes, by name: the classification cannot import the optional SDKs
# and matches on the class names in the MRO instead.
class APIConnectionError(Exception):
    pass


class APITimeoutError(APIConnectionError):
    pass


class APIStatusError(Exception):
    def __init__(self, message="bad request", status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


_PROVIDER = SimpleNamespace(
    config=SimpleNamespace(
        provider="openai",
        model="qwen3:0.6b",
        base_url="http://127.0.0.1:12434/v1",
        supports_image_input=False,
    )
)


def _refused_connection() -> APIConnectionError:
    exc = APIConnectionError("Connection error.")
    exc.__cause__ = OSError(
        "[WinError 10061] No connection could be made because the target machine "
        "actively refused it."
    )
    return exc


class DescribeLLMFailureTest(unittest.TestCase):
    def test_a_refused_connection_names_the_endpoint_and_the_os_error(self):
        failure = describe_llm_failure(_refused_connection(), _PROVIDER)

        self.assertIsInstance(failure, ProviderError)
        self.assertIn("http://127.0.0.1:12434/v1", str(failure))
        self.assertIn("qwen3:0.6b", str(failure))
        self.assertIn("10061", str(failure))
        self.assertIn("running", str(failure))

    def test_the_reported_fields_match_the_request(self):
        failure = describe_llm_failure(_refused_connection(), _PROVIDER)

        self.assertEqual(failure.provider, "openai")
        self.assertEqual(failure.model, "qwen3:0.6b")
        self.assertEqual(failure.endpoint, "http://127.0.0.1:12434/v1")

    def test_a_timeout_is_not_reported_as_a_plain_connection_failure(self):
        # ``APITimeoutError`` subclasses ``APIConnectionError``; checking connection
        # first would tell the operator to start a service that is already running.
        failure = describe_llm_failure(APITimeoutError("timed out"), _PROVIDER)

        self.assertIn("timed out", str(failure))
        self.assertNotIn("Cannot reach", str(failure))

    def test_a_status_error_points_at_the_credentials_and_model(self):
        failure = describe_llm_failure(
            APIStatusError("Incorrect API key provided", status_code=401), _PROVIDER
        )

        self.assertIn("HTTP 401", str(failure))
        self.assertIn("API key", str(failure))
        self.assertIn("Incorrect API key provided", failure.detail)

    def test_an_unknown_exception_still_gets_one_readable_line(self):
        failure = describe_llm_failure(ValueError("boom"), _PROVIDER)

        self.assertIn("Model request failed", str(failure))
        self.assertIn("boom", str(failure))

    def test_a_provider_without_config_still_produces_a_message(self):
        failure = describe_llm_failure(APIConnectionError("Connection error."), None)

        self.assertIn("unknown", str(failure))


class _Registry:
    base_dir = None
    read_only_roots = ()
    permission_broker = None
    user_question_broker = None

    def get_tool_schemas(self, provider):
        return []

    def execute_tool(self, name, arguments):
        raise AssertionError("no tool should run when the model call failed")


class _FailingProvider:
    wire_compatible_with_openai = True

    def __init__(self):
        self.config = _PROVIDER.config
        self.calls = 0

    def build_request_payload(self, messages, tools=None, **kwargs):
        return {"messages": messages, "tools": tools or []}

    def chat_completion(self, **kwargs):
        self.calls += 1
        raise _refused_connection()


class LoopFailureHandlingTest(unittest.TestCase):
    def run_loop(self, provider, sink):
        registry = _Registry()
        with patch(
            "agent.agent_loop._build_runtime",
            return_value=("openai", registry, provider, []),
        ):
            return run_react_loop(
                user_query="hello",
                task_id="task-llm-error",
                max_steps=2,
                verbose=False,
                event_sink=sink,
            )

    def test_the_loop_raises_one_actionable_error_and_records_it(self):
        provider = _FailingProvider()
        events = []

        with self.assertRaises(LLMCallError) as caught:
            self.run_loop(provider, lambda task_id, event: events.append(event))

        self.assertEqual(provider.calls, 1)
        self.assertIn("http://127.0.0.1:12434/v1", str(caught.exception))
        error_events = [event for event in events if event.category is EventCategory.ERROR]
        self.assertEqual(len(error_events), 1)
        self.assertIn("LLM request failed", error_events[0].title)
        self.assertIn("qwen3:0.6b", error_events[0].data["model"])


if __name__ == "__main__":
    unittest.main()

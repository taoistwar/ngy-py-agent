"""End-to-end check that a tool screenshot reaches the next LLM request.

Run from the repository root::

    uv run python test/agent_loop_vision_test.py -v

The loop is driven with a fake provider and a fake registry: the first assistant
turn asks for ``computer_observe``, the tool returns a :class:`ToolOutcome` with
an image, and the next request must carry a user message with an ``image_url``
part. That ordering is the part that is easy to break - the image cannot ride on
the ``tool`` message itself.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.agent_loop import run_react_loop  # noqa: E402
from agent.models import ToolImage, ToolOutcome  # noqa: E402


class _Registry:
    base_dir = None
    read_only_roots = ()
    permission_broker = None
    user_question_broker = None

    def __init__(self, image_path: str):
        self.image_path = image_path

    def get_tool_schemas(self, provider):
        return []

    def execute_tool(self, name, arguments):
        return ToolOutcome(
            model_text="window state text",
            details={"screenshot": self.image_path},
            images=[ToolImage(path=self.image_path)],
        )


class _Message:
    role = "assistant"

    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _Choice:
    def __init__(self, message):
        self.message = message
        self.finish_reason = "tool_calls" if message.tool_calls else "stop"


class _Response:
    def __init__(self, message):
        self.choices = [_Choice(message)]


class _FakeProvider:
    wire_compatible_with_openai = True

    def __init__(self, supports_image_input=True):
        self.config = SimpleNamespace(
            provider="openai",
            model="deepseek-v4.1-flash",
            supports_image_input=supports_image_input,
        )
        self.requests = []

    def build_request_payload(self, messages, tools=None, **kwargs):
        self.requests.append(list(messages))
        return {"messages": messages, "tools": tools or []}

    def chat_completion(self, messages, tools=None, **kwargs):
        if len(self.requests) == 1:
            tool_calls = [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "computer_observe", "arguments": "{}"},
                }
            ]
            return _Response(_Message(tool_calls=tool_calls))
        return _Response(_Message(content="done"))


class AgentLoopVisionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.png = Path(self._tmp.name) / "shot.png"
        self.png.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def tearDown(self):
        self._tmp.cleanup()

    def run_loop(self, provider):
        registry = _Registry(str(self.png))
        with patch(
            "agent.agent_loop._build_runtime",
            return_value=("openai", registry, provider, []),
        ):
            result = run_react_loop(
                user_query="look at the window",
                task_id="task-vision",
                max_steps=2,
                verbose=False,
            )
        return result

    def test_the_next_request_carries_the_screenshot_as_an_image_part(self):
        provider = _FakeProvider()

        result = self.run_loop(provider)

        self.assertEqual(result, "done")
        self.assertEqual(len(provider.requests), 2)
        second = provider.requests[1]
        image_messages = [
            message
            for message in second
            if message.get("role") == "user" and isinstance(message.get("content"), list)
        ]
        self.assertEqual(len(image_messages), 1)
        parts = image_messages[0]["content"]
        image_part = next(part for part in parts if part["type"] == "image_url")
        self.assertTrue(image_part["image_url"]["url"].startswith("data:image/png;base64,"))

        tool_messages = [message for message in second if message.get("role") == "tool"]
        self.assertEqual(tool_messages[0]["content"], "window state text")

    def test_a_text_only_model_still_gets_the_tool_result(self):
        provider = _FakeProvider(supports_image_input=False)

        result = self.run_loop(provider)

        self.assertEqual(result, "done")
        second = provider.requests[1]
        self.assertFalse(
            any(
                message.get("role") == "user" and isinstance(message.get("content"), list)
                for message in second
            )
        )
        self.assertTrue(any(message.get("role") == "tool" for message in second))


if __name__ == "__main__":
    unittest.main()

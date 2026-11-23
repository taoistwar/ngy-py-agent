"""Tests for the MCP marketplace API, including the connection probe.

Run from the repository root::

    uv run python test/mcp_api_test.py -v

The marketplace store is swapped for a temporary one, and the probe is stubbed:
spawning a real server is what ``test/agent/mcp/mcp_probe_test.py`` pins, so what is
covered here is the HTTP wiring - the 404, the answer shape, and the fact that a
server that refuses to talk is reported as a result rather than as an API error.
"""

import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to the
# import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import routes.mcp_api as mcp_api  # noqa: E402
from agent.mcp import McpProbeResult, McpToolCallResult, McpToolInfo  # noqa: E402
from dao.mcp import _SqliteMcpServerStore  # noqa: E402


class McpApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._root = Path(self._tmp.name)
        self._previous_store = mcp_api.mcp_store
        self._previous_probe = mcp_api.probe_server
        self._previous_call = mcp_api.call_server_tool
        self.store = _SqliteMcpServerStore(self._root / "mcp.db")
        mcp_api.mcp_store = self.store
        self.client = TestClient(main.app)

    def tearDown(self):
        mcp_api.mcp_store = self._previous_store
        mcp_api.probe_server = self._previous_probe
        mcp_api.call_server_tool = self._previous_call
        self.store.close()
        self._tmp.cleanup()

    def create_server(self, **overrides):
        payload = {
            "name": "everything",
            "description": "",
            "transport": "stdio",
            "target": "npx -y @modelcontextprotocol/everything",
        }
        payload.update(overrides)
        response = self.client.post("/api/mcp-servers", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_created_server_is_listed_and_deleted(self):
        created = self.create_server(name="filesystem", target="npx -y server-filesystem")

        listed = self.client.get("/api/mcp-servers").json()["servers"]
        self.assertEqual([item["name"] for item in listed], ["filesystem"])

        response = self.client.delete(f"/api/mcp-servers/{created['mcp_id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/api/mcp-servers").json()["servers"], [])

    def test_streamable_http_transport_is_stored_and_listed(self):
        created = self.create_server(
            name="remote", transport="http", target="https://example.com/mcp"
        )

        listed = self.client.get("/api/mcp-servers").json()["servers"]
        self.assertEqual([item["transport"] for item in listed], ["http"])
        self.assertEqual(listed[0]["target"], "https://example.com/mcp")
        self.assertEqual(created["transport"], "http")

    def test_an_unknown_transport_is_rejected(self):
        response = self.client.post(
            "/api/mcp-servers",
            json={"name": "weird", "transport": "websocket", "target": "ws://example.com"},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("http", response.json()["detail"])

    def test_probe_returns_the_tools_a_server_offers(self):
        created = self.create_server()
        probed = []

        def fake_probe(preset):
            probed.append(preset)
            return McpProbeResult(
                ok=True,
                transport="stdio",
                server_name="everything",
                server_version="0.1.0",
                protocol_version="2025-06-18",
                tools=(
                    McpToolInfo(name="add", description="Add numbers", input_schema={"type": "object"}),
                ),
                duration_ms=42,
            )

        mcp_api.probe_server = fake_probe
        response = self.client.post(f"/api/mcp-servers/{created['mcp_id']}/probe")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["server_name"], "everything")
        self.assertEqual(body["protocol_version"], "2025-06-18")
        self.assertEqual(body["duration_ms"], 42)
        self.assertEqual(
            body["tools"],
            [{"name": "add", "description": "Add numbers", "input_schema": {"type": "object"}}],
        )
        # The preset the route hands to the client is the stored one, not the request.
        self.assertEqual(probed[0]["transport"], "stdio")
        self.assertEqual(probed[0]["target"], "npx -y @modelcontextprotocol/everything")

    def test_probe_of_unknown_server_is_404(self):
        response = self.client.post("/api/mcp-servers/does-not-exist/probe")

        self.assertEqual(response.status_code, 404, response.text)

    def test_failed_connection_is_a_result_not_an_api_error(self):
        created = self.create_server()

        def fake_probe(preset):
            return McpProbeResult(
                ok=False,
                transport="stdio",
                error="The MCP server exited before answering 'initialize'.",
                duration_ms=7,
            )

        mcp_api.probe_server = fake_probe
        response = self.client.post(f"/api/mcp-servers/{created['mcp_id']}/probe")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("exited before answering", body["error"])
        self.assertEqual(body["tools"], [])

    def test_probe_reports_a_preset_it_cannot_open(self):
        created = self.create_server(transport="stdio", target="")

        response = self.client.post(f"/api/mcp-servers/{created['mcp_id']}/probe")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("empty", body["error"])

    def test_tool_test_returns_the_answer_and_the_arguments(self):
        created = self.create_server()
        calls = []

        def fake_call(preset, tool_name, arguments):
            calls.append((preset, tool_name, arguments))
            return McpToolCallResult(ok=True, tool=tool_name, result="3", duration_ms=12)

        mcp_api.call_server_tool = fake_call
        response = self.client.post(
            f"/api/mcp-servers/{created['mcp_id']}/tools/add/test",
            json={"arguments": {"a": 1, "b": 2}},
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["tool"], "add")
        self.assertEqual(body["result"], "3")
        self.assertEqual(body["duration_ms"], 12)
        self.assertFalse(body["truncated"])
        # The preset the route hands to the client is the stored one, not the request.
        self.assertEqual(calls[0][0]["target"], "npx -y @modelcontextprotocol/everything")
        self.assertEqual(calls[0][1], "add")
        self.assertEqual(calls[0][2], {"a": 1, "b": 2})

    def test_tool_test_without_body_sends_no_arguments(self):
        created = self.create_server()
        seen = []

        def fake_call(preset, tool_name, arguments):
            seen.append(arguments)
            return McpToolCallResult(ok=True, tool=tool_name, result="ok")

        mcp_api.call_server_tool = fake_call
        response = self.client.post(f"/api/mcp-servers/{created['mcp_id']}/tools/ping/test")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(seen, [{}])

    def test_failing_tool_call_is_a_result_not_an_api_error(self):
        created = self.create_server()

        def fake_call(preset, tool_name, arguments):
            return McpToolCallResult(ok=False, tool=tool_name, error="the tool blew up", duration_ms=5)

        mcp_api.call_server_tool = fake_call
        response = self.client.post(
            f"/api/mcp-servers/{created['mcp_id']}/tools/fail/test", json={"arguments": {}}
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("blew up", body["error"])
        self.assertEqual(body["result"], "")

    def test_a_huge_tool_result_is_clipped(self):
        created = self.create_server()
        payload = "x" * (mcp_api.MAX_RESULT_CHARS * 3)

        def fake_call(preset, tool_name, arguments):
            return McpToolCallResult(ok=True, tool=tool_name, result=payload)

        mcp_api.call_server_tool = fake_call
        response = self.client.post(
            f"/api/mcp-servers/{created['mcp_id']}/tools/dump/test", json={"arguments": {}}
        )

        body = response.json()
        self.assertTrue(body["truncated"])
        self.assertLess(len(body["result"]), len(payload))
        self.assertIn("more characters", body["result"])

    def test_tool_test_of_unknown_server_is_404(self):
        response = self.client.post(
            "/api/mcp-servers/does-not-exist/tools/add/test", json={"arguments": {}}
        )

        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Tests for the ``vault_http`` tool.

Run from the repository root::

    uv run python test/tools/vault_http/vault_http_test.py -v

Nothing here touches the network or the developer's vault: the transport is a fake
that records the request and returns a scripted response, and the secret store is a
throwaway JSON file per test. That keeps "what the endpoint answered" and "which
headers were sent" part of the test instead of part of the internet.

What these tests are really pinning down is the secret handling: it arrives in the
request, and it must not come back in the result - not raw, not base64, not
URL-encoded, not inside an error message.
"""

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.vault_http.errors import VaultHttpError  # noqa: E402
from agent.tools.vault_http.request import VaultResponse  # noqa: E402
from agent.tools.vault_http.scrub import REDACTED, variants_of  # noqa: E402
from agent.tools.vault_http.tool import make_vault_http_tool  # noqa: E402
from agent.tools.vault_store import VaultStore  # noqa: E402

SECRET = "ghp_sup3rSecretValue"
KEY = "gh-token"
URL = "https://api.example.com/v1/users"


class FakeTransport:
    """Records the request and returns (or raises) what the test scripted."""

    def __init__(self, response=None, error=None):
        self.response = response or VaultResponse(
            status=200,
            status_text="OK",
            headers={"Content-Type": "application/json"},
            body=b'[{"name": "ada"}]',
            truncated=False,
            elapsed_ms=12,
        )
        self.error = error
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "body": body, "timeout": timeout}
        )
        if self.error is not None:
            raise self.error
        return self.response


class VaultHttpTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.vault_path = self.root / "vault.json"
        self.write_vault({KEY: SECRET})
        self.output = self.root / "output"

    def tearDown(self):
        self._tmp.cleanup()

    def write_vault(self, secrets):
        self.vault_path.write_text(json.dumps({"secrets": secrets}), encoding="utf-8")

    def make_tool(self, transport, **options):
        return make_vault_http_tool(
            vault=VaultStore(self.vault_path),
            transport=transport,
            output_directory=self.output,
            **options,
        )

    def call(self, transport, **arguments):
        options = {"url": URL, "vault_auth_key": KEY, "reason": "list users for the ticket"}
        options.update(arguments)
        return self.make_tool(transport)(**options)

    # ------------------------------------------------------------- the happy path

    def test_a_bearer_call_reports_the_status_headers_and_body(self):
        transport = FakeTransport()

        result = self.call(transport)

        self.assertEqual(result["status"], 200)
        self.assertEqual(result["status_text"], "OK")
        self.assertEqual(result["body"], '[{"name": "ada"}]')
        self.assertEqual(result["response_headers"]["Content-Type"], "application/json")
        self.assertEqual(result["vault_auth_key"], KEY)
        self.assertEqual(result["auth_scheme"], "bearer")
        self.assertEqual(result["method"], "GET")
        self.assertNotIn("error", result)

    def test_the_secret_is_attached_as_the_configured_header(self):
        transport = FakeTransport()

        self.call(transport)

        sent = transport.calls[0]
        self.assertEqual(sent["headers"]["Authorization"], f"Bearer {SECRET}")
        self.assertEqual(sent["method"], "GET")
        self.assertIsNone(sent["body"])

    def test_basic_auth_sends_base64_of_the_stored_pair(self):
        self.write_vault({KEY: "ada:s3cret"})
        transport = FakeTransport()

        self.call(transport, auth_scheme="basic")

        expected = base64.b64encode(b"ada:s3cret").decode("ascii")
        self.assertEqual(transport.calls[0]["headers"]["Authorization"], f"Basic {expected}")

    def test_a_custom_scheme_uses_the_named_header(self):
        transport = FakeTransport()

        self.call(transport, auth_scheme="custom", auth_header_name="X-Tenant-Key")

        self.assertEqual(transport.calls[0]["headers"]["X-Tenant-Key"], SECRET)
        self.assertNotIn("Authorization", transport.calls[0]["headers"])

    def test_the_body_is_sent_utf8_with_its_content_type(self):
        transport = FakeTransport()

        self.call(transport, method="POST", body='{"name": "ada"}', body_content_type="application/json")

        sent = transport.calls[0]
        self.assertEqual(sent["method"], "POST")
        self.assertEqual(sent["body"], b'{"name": "ada"}')
        self.assertEqual(sent["headers"]["Content-Type"], "application/json")

    # ------------------------------------------------------------------ scrubbing

    def test_the_secret_never_comes_back_in_the_result(self):
        echoed = (
            f"raw={SECRET} b64={base64.b64encode(SECRET.encode()).decode()} "
            f"encoded={quote(SECRET, safe='')}"
        ).encode()
        transport = FakeTransport(
            VaultResponse(
                status=401,
                status_text="Unauthorized",
                headers={"Content-Type": "text/plain", "X-Echo": f"Bearer {SECRET}"},
                body=echoed,
                truncated=False,
                elapsed_ms=5,
            )
        )

        result = self.call(transport)

        serialized = json.dumps(result)
        for variant in variants_of(SECRET):
            self.assertNotIn(variant, serialized, f"{variant!r} leaked into the result")
        self.assertIn(REDACTED, result["body"])
        self.assertIn(REDACTED, result["response_headers"]["X-Echo"])
        # The status of a rejected credential is still the answer the model needs.
        self.assertEqual(result["status"], 401)
        self.assertNotIn("error", result)

    def test_a_transport_error_is_scrubbed_before_the_model_sees_it(self):
        error = VaultHttpError(
            f"Could not connect while sending Authorization: Bearer {SECRET}",
            reason="connection_failed",
            url=URL,
            echo=f"Bearer {SECRET}",
        )
        transport = FakeTransport(error=error)

        result = self.call(transport)

        self.assertEqual(result["reason"], "connection_failed")
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertIn(REDACTED, result["error"])

    # ------------------------------------------------------------------ refusals

    def test_only_https_is_accepted_and_the_vault_is_not_opened(self):
        transport = FakeTransport()

        result = self.call(transport, url="http://api.example.com/v1/users")

        self.assertEqual(result["reason"], "https_required")
        self.assertEqual(transport.calls, [], "a plaintext target must not be requested")
        self.assertNotIn(SECRET, json.dumps(result))

    def test_an_unknown_argument_is_refused_rather_than_ignored(self):
        transport = FakeTransport()

        result = self.call(transport, auth_headers={"X-Api-Key": "guess"})

        self.assertEqual(result["reason"], "unknown_argument")
        self.assertIn("auth_headers", result["error"])
        self.assertEqual(transport.calls, [])

    def test_missing_required_arguments_are_named(self):
        transport = FakeTransport()

        result = self.make_tool(transport)(url=URL)

        self.assertEqual(result["reason"], "missing_argument")
        self.assertIn("vault_auth_key", result["error"])
        self.assertEqual(transport.calls, [])

    def test_a_custom_scheme_without_a_header_name_is_refused(self):
        transport = FakeTransport()

        result = self.call(transport, auth_scheme="custom")

        self.assertEqual(result["reason"], "missing_argument")
        self.assertEqual(result["argument"], "auth_header_name")

    def test_a_header_name_is_refused_for_the_builtin_schemes(self):
        transport = FakeTransport()

        result = self.call(transport, auth_header_name="X-Api-Key")

        self.assertEqual(result["reason"], "invalid_argument")
        self.assertEqual(result["argument"], "auth_header_name")

    def test_a_framing_header_cannot_be_used_for_the_secret(self):
        transport = FakeTransport()

        result = self.call(transport, auth_scheme="custom", auth_header_name="host")

        self.assertEqual(result["reason"], "invalid_argument")

    def test_get_cannot_carry_a_body(self):
        transport = FakeTransport()

        result = self.call(transport, body="{}")

        self.assertEqual(result["reason"], "body_not_allowed")
        self.assertEqual(transport.calls, [])

    def test_an_unknown_vault_key_is_an_error_and_names_the_ones_that_exist(self):
        transport = FakeTransport()

        result = self.call(transport, vault_auth_key="billing-api")

        self.assertEqual(result["reason"], "secret_not_found")
        self.assertIn(KEY, result["error"])
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertEqual(transport.calls, [])

    def test_a_missing_vault_file_is_reported_as_the_vault_problem(self):
        transport = FakeTransport()
        self.vault_path.unlink()

        result = self.call(transport)

        self.assertEqual(result["reason"], "vault_unavailable")
        self.assertEqual(transport.calls, [])

    def test_a_malformed_url_is_refused_with_the_url_reason(self):
        transport = FakeTransport()

        result = self.call(transport, url="api.example.com/v1/users")

        self.assertEqual(result["reason"], "invalid_url")
        self.assertEqual(transport.calls, [])

    # ------------------------------------------------------------------ redirects

    def test_a_redirect_is_reported_and_not_followed(self):
        transport = FakeTransport(
            VaultResponse(
                status=302,
                status_text="Found",
                headers={"Location": f"https://evil.example.net/steal?t={SECRET}"},
                body=b"",
                truncated=False,
                elapsed_ms=3,
            )
        )

        result = self.call(transport)

        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(result["status"], 302)
        self.assertIn("evil.example.net", result["redirect_to"])
        self.assertIn("REDIRECT NOT FOLLOWED", result["body"])
        self.assertNotIn(SECRET, json.dumps(result), "the Location header must be scrubbed too")

    def test_a_relative_location_is_resolved_for_the_model(self):
        transport = FakeTransport(
            VaultResponse(
                status=302,
                status_text="Found",
                headers={"Location": "/login"},
                body=b"",
                truncated=False,
                elapsed_ms=2,
            )
        )

        result = self.call(transport)

        self.assertEqual(result["redirect_to"], "https://api.example.com/login")

    # --------------------------------------------------------------------- budget

    def test_a_large_body_is_persisted_and_only_previewed(self):
        big = json.dumps({"items": ["row"] * 5000}).encode()
        transport = FakeTransport(
            VaultResponse(
                status=200,
                status_text="OK",
                headers={"Content-Type": "application/json"},
                body=big,
                truncated=False,
                elapsed_ms=7,
            )
        )

        result = self.make_tool(transport, max_tokens=1)(
            url=URL, vault_auth_key=KEY, reason="list every row"
        )

        self.assertTrue(result["body_truncated"])
        self.assertIn("--- preview ---", result["body"])
        path = Path(result["persisted_path"])
        self.assertTrue(path.exists())
        self.assertIn('"items"', path.read_text(encoding="utf-8"))

    def test_a_truncated_response_says_so(self):
        transport = FakeTransport(
            VaultResponse(
                status=200,
                status_text="OK",
                headers={"Content-Type": "text/plain"},
                body=b"abcdef",
                truncated=True,
                elapsed_ms=1,
            )
        )

        result = self.call(transport)

        self.assertTrue(result["response_truncated"])
        self.assertIn("cut at the size limit", result["body"])


class ScrubVariantsTest(unittest.TestCase):
    def test_the_variants_cover_the_encodings_a_server_can_echo(self):
        variants = variants_of("ada:s3cret")

        self.assertIn("ada:s3cret", variants)
        self.assertIn(base64.b64encode(b"ada:s3cret").decode(), variants)
        self.assertIn(quote("ada:s3cret", safe=""), variants)
        # The halves are scrubbed on their own, because a server that rejects basic
        # auth quotes one of them ("invalid password for user ada").
        self.assertIn("s3cret", variants)

    def test_variants_are_longest_first_so_a_prefix_cannot_win(self):
        variants = variants_of(SECRET)

        self.assertEqual(list(variants), sorted(variants, key=len, reverse=True))


if __name__ == "__main__":
    unittest.main()

"""What the model is told about ``vault_http``: its description and parameter schema.

The omissions are stated out loud, because a model that guesses otherwise wastes a
call and then a retry:

* only ``https`` - the target is refused before the vault is touched;
* redirects are never followed - the 3xx is reported instead, so the key cannot
  travel to an unapproved host;
* the secret is never an argument and never appears in the result - it is scrubbed
  out of the body, the headers and any error text.
"""

from typing import Any, Dict

VAULT_HTTP_DESCRIPTION = (
    "Send one HTTPS request with a secret taken from the local vault. "
    "The secret is referenced by NAME ('vault_auth_key'), never passed in: the vault "
    "holds the value, the tool attaches it to the request and scrubs every form of it "
    "out of the result, so neither the model nor the transcript ever sees it. "
    "Use this for endpoints that need a token, an API key or basic auth; use web_fetch "
    "for public pages. "
    "Rules: only https:// URLs are accepted (plain http is refused); redirects are NOT "
    "followed - a 30x is returned with 'redirect_to' and must be requested as a "
    "separate call, so the new host gets its own approval; a body can be sent with "
    "POST, PUT, PATCH or DELETE but not with GET. "
    "auth_scheme decides where the secret goes: 'bearer' (default) sends "
    "'Authorization: Bearer <secret>', 'basic' sends 'Authorization: Basic "
    "base64(<secret>)' where the stored secret is 'user:password', 'header_x_api_key' "
    "sends 'X-Api-Key: <secret>', and 'custom' sends the secret in the header named by "
    "'auth_header_name'. "
    "Arguments are matched exactly: an unknown or misspelled argument is refused "
    "instead of ignored. "
    "The result reports 'status' and 'status_text' (the HTTP status), "
    "'response_headers' (scrubbed), 'body' (scrubbed; JSON and text as sent), 'bytes', "
    "'duration_ms', 'encoding' and 'redirect_to' when the server redirected. A body "
    "above the output token budget is written to a file and 'body' holds a preview plus "
    "'persisted_path', which read_file reads back in slices. "
    "Every call asks the user for permission first, keyed on the key name plus the "
    "host; a standing approval covers that pair only and this question is asked even "
    "when confirmations are otherwise auto-approved. "
    "A failure is '{\"error\", \"reason\", ...}' with no status or body."
)

VAULT_HTTP_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": (
                "Absolute https:// URL of the endpoint. http:// and other schemes are "
                "refused, as are URLs with an embedded user name or password."
            ),
        },
        "vault_auth_key": {
            "type": "string",
            "description": (
                "Name of the vault entry that holds the secret (1-128 letters, digits, "
                "'.', '_', ':' or '-'), for example 'gh-token'. The secret itself is "
                "never passed as an argument."
            ),
        },
        "reason": {
            "type": "string",
            "description": (
                "Why this request is needed (1-500 characters). Shown in the permission "
                "dialog and in the audit log, so write it for the person approving it."
            ),
        },
        "method": {
            "type": "string",
            "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            "description": "HTTP method. Defaults to GET.",
        },
        "auth_scheme": {
            "type": "string",
            "enum": ["bearer", "basic", "header_x_api_key", "custom"],
            "description": (
                "How the secret is attached. 'bearer' (default) -> 'Authorization: Bearer "
                "<secret>'; 'basic' -> 'Authorization: Basic base64(<secret>)' with the "
                "stored secret written as 'user:password'; 'header_x_api_key' -> "
                "'X-Api-Key: <secret>'; 'custom' -> the header named by "
                "'auth_header_name'."
            ),
        },
        "auth_header_name": {
            "type": "string",
            "description": (
                "Header that carries the secret. Required when auth_scheme is 'custom' and "
                "refused otherwise. 1-64 letters, digits, '_' or '-'; framing headers such "
                "as host or content-length are not allowed."
            ),
        },
        "body": {
            "type": "string",
            "description": (
                "Request body, sent as UTF-8. Allowed with POST, PUT, PATCH and DELETE; "
                "refused with GET."
            ),
        },
        "body_content_type": {
            "type": "string",
            "description": (
                "Content-Type of 'body'. Defaults to 'application/json' (max 128 "
                "characters)."
            ),
        },
    },
    "required": ["url", "vault_auth_key", "reason"],
}

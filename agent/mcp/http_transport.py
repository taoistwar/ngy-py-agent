"""MCP over HTTP, in both shapes a server may offer.

- **Streamable HTTP** (the 2025 revision) is one URL: every message is a POST, and the
  answer arrives either as a JSON body or as an event stream on that same response.
- **The older SSE transport** is two URLs: a long-lived GET stream that announces a
  message endpoint, and POSTs to it whose answers come back on the stream.

Both are written against ``requests`` because it is already a dependency, it handles
chunked reads, and a probe must not drag an async client into a synchronous loop.

Neither session keeps a connection open between calls when it does not have to: the
Streamable one posts per message, the SSE one keeps exactly the stream the server gave
it.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Dict, Iterator, List, Mapping, Optional
from urllib.parse import urljoin

import requests

from agent.mcp.jsonrpc import (
    METHOD_NOT_FOUND,
    McpProtocolError,
    encode_error,
    encode_notification,
    encode_request,
)
from agent.mcp.protocol import PROTOCOL_VERSION
from agent.mcp.sse import parse_events
from agent.mcp.stdio import McpSessionError

# Connecting is quick or it is broken; waiting for the answer is what takes time.
_CONNECT_TIMEOUT_SECONDS = 10.0
# A notification gets the same patience as a call, because the server may answer 202 late.
_NOTIFY_TIMEOUT_SECONDS = 30.0
# Body prefix kept from a failed response: enough for "why", not a whole error page.
_ERROR_BODY_CHARS = 300
_SESSION_HEADER = "Mcp-Session-Id"


def _headers(base: Mapping[str, str], extra: Mapping[str, str]) -> Dict[str, str]:
    """Preset headers first, protocol headers last: a preset must not break framing."""
    return {**base, **extra}


def _iter_lines(response: requests.Response) -> "Iterator[str]":
    """Lines as they arrive, not 512 bytes' worth at a time.

    ``Response.iter_lines()`` reads through ``urllib3``'s fixed-size buffer, which on a
    stream that is not chunked encodes to "wait for a full block or the connection to
    close". An SSE stream must be read as soon as bytes land, and ``read1`` does exactly
    that; the newline splitting is ours because we are reading raw decoded bytes.
    """
    buffer = b""
    raw = response.raw
    read = getattr(raw, "read1", None)
    while True:
        try:
            chunk = read(1024, decode_content=True) if read is not None else raw.read(1024)
        except requests.RequestException:
            raise
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, _, buffer = buffer.partition(b"\n")
            yield line.decode("utf-8", "replace")
    if buffer:
        yield buffer.decode("utf-8", "replace")


def _transport_error(exc: Exception) -> McpSessionError:
    """One sentence for "the network did not cooperate", split by cause."""
    if isinstance(exc, requests.Timeout):
        return McpSessionError(f"The MCP server did not answer in time: {exc}")
    return McpSessionError(f"The MCP server could not be reached: {exc}")


def _describe_error(error: Mapping[str, Any]) -> str:
    code = error.get("code")
    message = str(error.get("message") or "no message").strip()
    return f"{message} (code {code})" if code is not None else message


def _result_of(message: Mapping[str, Any]) -> Dict[str, Any]:
    error = message.get("error")
    if isinstance(error, dict):
        raise McpSessionError(f"The MCP server rejected the request: {_describe_error(error)}")
    result = message.get("result")
    return result if isinstance(result, dict) else {}


def _decode_messages(text: str) -> List[Dict[str, Any]]:
    """JSON-RPC messages in one body, tolerating the batched (array) form."""
    if not text.strip():
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpProtocolError(f"The MCP server sent a body that is not JSON: {text[:200]}") from exc
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise McpProtocolError(f"The MCP server sent JSON that is not a message: {text[:200]}")


class StreamableHttpSession:
    """One URL: POST each message, read the answer from the same response."""

    def __init__(self, url: str, headers: Optional[Mapping[str, str]] = None) -> None:
        self.url = url
        self._preset_headers = dict(headers or {})
        self._session_id = ""
        self._next_id = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Nothing to open: the handshake request is the connection."""
        return

    def close(self) -> None:
        """Nothing held open: each request owns its own connection."""
        return

    # -- messages ----------------------------------------------------------

    def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        self._post(
            json.loads(encode_notification(method, params)),
            timeout=_NOTIFY_TIMEOUT_SECONDS,
        )

    def request(
        self, method: str, params: Optional[Dict[str, Any]], timeout: float
    ) -> Dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        return self._post(
            json.loads(encode_request(request_id, method, params)),
            timeout=timeout,
            request_id=request_id,
        )

    # -- internals ---------------------------------------------------------

    def _post(
        self,
        payload: Mapping[str, Any],
        *,
        timeout: float,
        request_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            response = requests.post(
                self.url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=self._request_headers(),
                timeout=(_CONNECT_TIMEOUT_SECONDS, timeout),
                stream=True,
            )
        except requests.RequestException as exc:
            raise _transport_error(exc) from exc
        try:
            session_id = response.headers.get(_SESSION_HEADER)
            if session_id:
                self._session_id = session_id
            if response.status_code >= 400:
                raise McpSessionError(
                    f"The MCP server answered HTTP {response.status_code}: "
                    f"{response.text[:_ERROR_BODY_CHARS].strip()}"
                )
            content_type = response.headers.get("Content-Type", "")
            if content_type.split(";")[0].strip().lower() == "text/event-stream":
                return self._read_stream(response, request_id)
            return self._read_body(response, request_id)
        except requests.RequestException as exc:
            raise _transport_error(exc) from exc
        finally:
            response.close()

    def _request_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            # Required on everything after initialization by the current revision; sent
            # from the first request as well, which servers accept and it keeps this
            # class from tracking handshake state it does not need.
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self._session_id:
            headers[_SESSION_HEADER] = self._session_id
        return _headers(self._preset_headers, headers)

    def _read_body(self, response: requests.Response, request_id: Optional[int]) -> Dict[str, Any]:
        messages = _decode_messages(response.text)
        if request_id is None:
            return {}
        for message in messages:
            if message.get("id") == request_id:
                return _result_of(message)
        raise McpProtocolError(
            f"The MCP server answered without a message for request {request_id}."
        )

    def _read_stream(
        self, response: requests.Response, request_id: Optional[int]
    ) -> Dict[str, Any]:
        if request_id is None:
            return {}
        for event in parse_events(_iter_lines(response)):
            for message in _decode_messages(event.data):
                if message.get("id") == request_id:
                    return _result_of(message)
        raise McpSessionError("The MCP server closed the event stream without answering.")


class SseSession:
    """Two endpoints: a GET stream for answers, an announced endpoint for messages."""

    def __init__(self, url: str, headers: Optional[Mapping[str, str]] = None) -> None:
        self.url = url
        self._preset_headers = dict(headers or {})
        self._stream: Optional[requests.Response] = None
        self._reader: Optional[threading.Thread] = None
        self._inbox: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()
        self._endpoint_ready = threading.Event()
        self._message_url = ""
        self._next_id = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Open the stream and wait for the server to announce where messages go."""
        headers = _headers(
            self._preset_headers,
            {"Accept": "text/event-stream", "Cache-Control": "no-store"},
        )
        try:
            response = requests.get(
                self.url,
                headers=headers,
                stream=True,
                timeout=(_CONNECT_TIMEOUT_SECONDS, _NOTIFY_TIMEOUT_SECONDS),
            )
        except requests.RequestException as exc:
            raise _transport_error(exc) from exc
        if response.status_code >= 400:
            body = response.text[:_ERROR_BODY_CHARS].strip()
            response.close()
            raise McpSessionError(f"The MCP server answered HTTP {response.status_code}: {body}")
        self._stream = response
        self._reader = threading.Thread(target=self._read, name="mcp-sse", daemon=True)
        self._reader.start()

    def close(self) -> None:
        stream, self._stream = self._stream, None
        self._inbox.put(None)
        if stream is not None:
            stream.close()

    # -- messages ----------------------------------------------------------

    def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        self._post(json.loads(encode_notification(method, params)), timeout=_NOTIFY_TIMEOUT_SECONDS)

    def request(
        self, method: str, params: Optional[Dict[str, Any]], timeout: float
    ) -> Dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._post(json.loads(encode_request(request_id, method, params)), timeout=timeout)
        deadline = time.monotonic() + timeout
        while True:
            message = self._next_message(deadline, method)
            if message.get("id") != request_id:
                self._answer_unsolicited(message)
                continue
            return _result_of(message)

    # -- internals ---------------------------------------------------------

    def _post(self, payload: Mapping[str, Any], *, timeout: float) -> None:
        if not self._endpoint_ready.wait(timeout):
            raise McpSessionError(
                "The MCP server did not announce a message endpoint; check that this "
                "is an SSE endpoint and not a Streamable HTTP one."
            )
        try:
            response = requests.post(
                self._message_url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=_headers(self._preset_headers, {"Content-Type": "application/json"}),
                timeout=(_CONNECT_TIMEOUT_SECONDS, timeout),
            )
        except requests.RequestException as exc:
            raise _transport_error(exc) from exc
        if response.status_code >= 400:
            raise McpSessionError(
                f"The MCP server answered HTTP {response.status_code}: "
                f"{response.text[:_ERROR_BODY_CHARS].strip()}"
            )

    def _next_message(self, deadline: float, method: str) -> Dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise McpSessionError(f"The MCP server did not answer '{method}' in time.")
        try:
            item = self._inbox.get(timeout=remaining)
        except queue.Empty as exc:
            raise McpSessionError(f"The MCP server did not answer '{method}' in time.") from exc
        if item is None:
            raise McpSessionError(
                f"The MCP server closed the event stream before answering '{method}'."
            )
        return item

    def _answer_unsolicited(self, message: Mapping[str, Any]) -> None:
        """Refuse a server-initiated request; drop notifications and late replies."""
        method = message.get("method")
        request_id = message.get("id")
        if method is None or request_id is None:
            return
        try:
            self._post(
                json.loads(
                    encode_error(
                        request_id,
                        METHOD_NOT_FOUND,
                        f"'{method}' is not supported by this client.",
                    )
                ),
                timeout=_NOTIFY_TIMEOUT_SECONDS,
            )
        except McpSessionError:
            # Best effort: the caller is already waiting for its own answer, and a failed
            # courtesy reply must not become the error it reports.
            return

    def _read(self) -> None:
        stream = self._stream
        if stream is None:
            self._inbox.put(None)
            return
        try:
            for event in parse_events(_iter_lines(stream)):
                if event.event == "endpoint":
                    self._message_url = urljoin(self.url, event.data.strip())
                    self._endpoint_ready.set()
                    continue
                for message in _decode_messages(event.data):
                    self._inbox.put(message)
        except (OSError, ValueError, requests.RequestException):
            # The stream died; the EOF marker below is the signal the caller reads.
            pass
        finally:
            self._inbox.put(None)

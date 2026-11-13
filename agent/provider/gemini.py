"""Google Gemini's generateContent wire format."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from agent.provider.base import BaseProvider, ProviderDependencyError, ProviderError
from agent.provider.config import ProviderConfig
from agent.provider.wire import (
    OpenAIStyleFunction,
    OpenAIStyleToolCall,
    iter_tool_call_entries,
    to_content_text,
    to_json_string,
    tool_call_to_name_and_args,
)


class GeminiProvider(BaseProvider):
    provider_name = "gemini"
    schema_key = "gemini"
    wire_compatible_with_openai = False
    # The REST endpoint streams over SSE, but its function calls arrive whole rather
    # than as argument fragments; the one-shot path already carries everything the
    # loop needs, so no adapter for it exists yet.
    supports_streaming = False

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.api_key:
            raise ProviderError(
                "GEMINI_API_KEY is required for gemini provider."
            )

    def _to_gemini_contents(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Gemini supports `system` prompt implicitly via an initial user message prefix.
        system_text = ""
        contents: List[Dict[str, Any]] = []

        for message in messages:
            role = message.get("role")
            content = to_content_text(message.get("content"))

            if role == "system":
                if system_text:
                    system_text += "\n"
                system_text += content
                continue

            if role == "user":
                if content:
                    contents.append({"role": "user", "parts": [{"text": content}]})
                continue

            if role == "assistant":
                if not iter_tool_call_entries(message):
                    if content:
                        contents.append({"role": "model", "parts": [{"text": content}]})
                    continue

                parts: List[Dict[str, Any]] = []
                if content:
                    parts.append({"text": content})
                for call in iter_tool_call_entries(message):
                    item = tool_call_to_name_and_args(call)
                    if item is None:
                        continue
                    name, args, _ = item
                    parts.append({
                        "functionCall": {
                            "name": name,
                            "args": args,
                        }
                    })
                if parts:
                    contents.append({"role": "model", "parts": parts})
                continue

            if role == "tool":
                name = message.get("name")
                if not name:
                    if content:
                        contents.append({"role": "user", "parts": [{"text": content}]})
                    continue

                parsed_content = content
                try:
                    parsed_content = json.loads(content)
                    if not isinstance(parsed_content, dict):
                        parsed_content = {"result": parsed_content}
                except (ValueError, TypeError):
                    # Parsing is best effort: whatever the decoder cannot read is
                    # passed through as opaque text instead of failing the turn.
                    parsed_content = {"result": content}

                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": name,
                            "response": parsed_content,
                        }
                    }]
                })

        if system_text:
            # Gemini does not guarantee dedicated system role across all deployments.
            # Prepend system instructions as a leading user message.
            system_payload = {"role": "user", "parts": [{"text": system_text}]}
            contents.insert(0, system_payload)

        if not contents:
            contents.append({"role": "user", "parts": [{"text": ""}]})
        return contents

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Any:
        self._throttle()
        try:
            import requests
        except Exception as exc:  # pragma: no cover
            raise ProviderDependencyError(
                "requests package is required for gemini runtime. Install requests."
            ) from exc

        request_payload: Dict[str, Any] = {
            "contents": self._to_gemini_contents(messages),
            "generationConfig": {
                "temperature": kwargs.pop("temperature", 0.2),
                "maxOutputTokens": kwargs.pop("max_output_tokens", 1024),
            },
            "toolConfig": {
                "functionCallingConfig": {"mode": kwargs.pop("mode", "AUTO")},
            },
        }

        if tools:
            request_payload["tools"] = [{"functionDeclarations": tools}]

        timeout = kwargs.pop("timeout", 30)
        request_payload.update(kwargs)

        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.config.model}:"
            "generateContent?key="
            f"{self.config.api_key}"
        )
        response = requests.post(endpoint, json=request_payload, timeout=timeout)
        if response.status_code >= 400:
            raise ProviderError(
                f"Gemini request failed: {response.status_code} {response.text}"
            )

        payload = response.json()
        candidates = payload.get("candidates", [])
        if not candidates:
            return self.as_openai_style(content="", tool_calls=[])

        content = candidates[0].get("content") or {}
        parts = content.get("parts", []) or []

        tool_calls: List[OpenAIStyleToolCall] = []
        content_chunks: List[str] = []
        reasoning_chunks: List[str] = []

        for part in parts:
            function_call = part.get("functionCall")
            if function_call:
                name = function_call.get("name", "")
                args = function_call.get("args", {})
                tool_calls.append(
                    OpenAIStyleToolCall(
                        id=str(uuid.uuid4()),
                        function=OpenAIStyleFunction(name=name, arguments=to_json_string(args)),
                    )
                )
                continue
            text = part.get("text")
            if not isinstance(text, str) or not text:
                continue
            # ``thought`` parts carry the model's reasoning when thinking is on.
            if part.get("thought"):
                reasoning_chunks.append(text)
            else:
                content_chunks.append(text)

        usage = payload.get("usageMetadata")
        return self.as_openai_style(
            content="\n".join(content_chunks),
            tool_calls=tool_calls,
            reasoning="\n".join(reasoning_chunks),
            usage=usage,
        )

    def build_request_payload(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        request_payload: Dict[str, Any] = {
            "contents": self._to_gemini_contents(messages),
            "generationConfig": {
                "temperature": kwargs.pop("temperature", 0.2),
                "maxOutputTokens": kwargs.pop("max_output_tokens", 1024),
            },
            "toolConfig": {"functionCallingConfig": {"mode": kwargs.pop("mode", "AUTO")}},
        }
        if tools:
            request_payload["tools"] = [{"functionDeclarations": tools}]
        request_payload.update(kwargs)
        return request_payload

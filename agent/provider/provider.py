from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Protocol


class ProviderError(RuntimeError):
    pass


class ProviderDependencyError(ProviderError):
    pass


def normalize_provider_name(name: str) -> str:
    return (name or "openai").strip().lower().replace(" ", "_")


def canonicalize_provider(name: str) -> str:
    provider = normalize_provider_name(name)
    if provider in {"openai_compatible", "openai-compatible"}:
        return "openai"
    if provider in {"anthropic_compatible", "anthropic-compatible"}:
        return "anthropic_compatible"
    return provider


def resolve_tool_provider_for_schemas(name: str) -> str:
    """Map schema output selection to provider key used by ToolRegistry."""
    provider = canonicalize_provider(name)
    if provider == "openai":
        return "openai"
    return provider


def _read_env(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _normalize_openai_base_url(base_url: str, default: str = "http://127.0.0.1:11434/v1") -> str:
    normalized = (base_url or "").strip()
    if not normalized:
        normalized = default
    normalized = normalized.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


def _to_json_string(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload or {}, ensure_ascii=False)


def _iter_tool_call_entries(message: Any) -> Iterable[Any]:
    tool_calls = None
    if isinstance(message, dict):
        tool_calls = message.get("tool_calls", [])
    else:
        tool_calls = getattr(message, "tool_calls", [])
    if not tool_calls:
        return []
    return list(tool_calls)


def _coerce_tool_call_arguments(arguments: Any) -> Dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _tool_call_to_name_and_args(tool_call: Any) -> Optional[tuple[str, Dict[str, Any], str]]:
    if tool_call is None:
        return None

    call_id = getattr(tool_call, "id", None) or (
        tool_call.get("id") if isinstance(tool_call, dict) else None
    )
    if not call_id:
        call_id = str(uuid.uuid4())

    function = getattr(tool_call, "function", None)
    if function is None and isinstance(tool_call, dict):
        function = tool_call.get("function")

    if function is None:
        return None

    name = getattr(function, "name", None) or (function.get("name") if isinstance(function, dict) else None)
    if not name:
        return None

    arguments = getattr(function, "arguments", None)
    if arguments is None and isinstance(function, dict):
        arguments = function.get("arguments")
    args = _coerce_tool_call_arguments(arguments)
    return name, args, str(call_id)


def _to_content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


@dataclass
class _OpenAIStyleFunction:
    name: str
    arguments: str


@dataclass
class _OpenAIStyleToolCall:
    id: str
    function: _OpenAIStyleFunction


@dataclass
class _OpenAIStyleMessage:
    content: str
    tool_calls: Optional[List[_OpenAIStyleToolCall]] = None


@dataclass
class _OpenAIStyleChoice:
    message: _OpenAIStyleMessage


@dataclass
class _OpenAIStyleResponse:
    choices: List[_OpenAIStyleChoice]


class ChatCompletionProtocol(Protocol):
    def chat_completion(self, *args, **kwargs) -> Any:
        ...

    def build_request_payload(self, *args, **kwargs) -> Dict[str, Any]:
        ...


class BaseProvider(ChatCompletionProtocol):
    provider_name = "base"
    wire_compatible_with_openai = False
    schema_key = "openai"

    def __init__(self, config: "ProviderConfig") -> None:
        self.config = config

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Any:
        raise NotImplementedError

    def _as_openai_style(
        self,
        content: Optional[str] = None,
        tool_calls: Optional[List[_OpenAIStyleToolCall]] = None,
    ) -> _OpenAIStyleResponse:
        message = _OpenAIStyleMessage(
            content=_to_content_text(content),
            tool_calls=tool_calls or [],
        )
        return _OpenAIStyleResponse(choices=[_OpenAIStyleChoice(message=message)])

    def build_request_payload(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": self.config.model, "messages": messages}
        if tools is not None:
            payload["tools"] = tools
        payload.update(kwargs)
        return payload

    def get_tool_schemas(self, registry: Any) -> List[Dict[str, Any]]:
        return registry.get_tool_schemas(self.schema_key)


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str
    base_url: Optional[str] = None


class OpenAIProvider(BaseProvider):
    provider_name = "openai"
    wire_compatible_with_openai = True
    schema_key = "openai"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover
            raise ProviderDependencyError(
                "openai package is required for openai-compatible providers."
            ) from exc

        self._client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Any:
        return self._client.chat.completions.create(**self.build_request_payload(messages, tools=tools, **kwargs))


class AnthropicProvider(BaseProvider):
    provider_name = "anthropic"
    schema_key = "anthropic"
    wire_compatible_with_openai = False

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        try:
            import anthropic
        except Exception as exc:  # pragma: no cover
            raise ProviderDependencyError(
                "anthropic package is required for anthropic provider."
            ) from exc

        if not config.api_key:
            raise ProviderDependencyError(
                "ANTHROPIC_API_KEY is required for anthropic provider."
            )

        self._client = anthropic.Anthropic(api_key=config.api_key)

    def _to_anthropic_messages(self, messages: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
        system_prompt = ""
        anthropic_messages: List[Dict[str, Any]] = []

        for message in messages:
            role = message.get("role")
            content = _to_content_text(message.get("content"))

            if role == "system":
                if system_prompt:
                    system_prompt += "\n"
                system_prompt += content
                continue

            if role == "user":
                anthropic_messages.append({"role": "user", "content": content})
                continue

            if role == "assistant":
                blocks: List[Dict[str, Any]] = []
                for raw_tool_call in _iter_tool_call_entries(message):
                    item = _tool_call_to_name_and_args(raw_tool_call)
                    if item is None:
                        continue
                    name, args, tool_call_id = item
                    blocks.append({
                        "type": "tool_use",
                        "id": tool_call_id,
                        "name": name,
                        "input": args,
                    })
                if not blocks:
                    anthropic_messages.append({"role": "assistant", "content": content})
                else:
                    if content:
                        blocks.insert(0, {"type": "text", "text": content})
                    anthropic_messages.append({"role": "assistant", "content": blocks})
                continue

            if role == "tool":
                tool_id = message.get("tool_call_id")
                tool_name = message.get("name")  # for logs only
                if not tool_id:
                    # Fall back to plain text if tool id is missing.
                    anthropic_messages.append({"role": "user", "content": f"[tool:{tool_name}] {content}"})
                    continue

                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": content,
                    }]
                })

        return system_prompt, anthropic_messages

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Any:
        system_prompt, anthropic_messages = self._to_anthropic_messages(messages)
        kwargs = dict(kwargs)
        request_params: Dict[str, Any] = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.pop("max_tokens", 1024),
        }
        if system_prompt:
            request_params["system"] = system_prompt
        if tools:
            request_params["tools"] = tools
        request_params.update(kwargs)

        response = self._client.messages.create(**request_params)
        tool_calls: List[_OpenAIStyleToolCall] = []
        content_chunks: List[str] = []

        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "tool_use":
                name = getattr(block, "name", "")
                args = _coerce_tool_call_arguments(getattr(block, "input", None))
                call_id = getattr(block, "id", None) or str(uuid.uuid4())
                tool_calls.append(
                    _OpenAIStyleToolCall(
                        id=str(call_id),
                        function=_OpenAIStyleFunction(name=name, arguments=_to_json_string(args)),
                    )
                )
            elif getattr(block, "type", None) == "text":
                text = getattr(block, "text", "")
                if text:
                    content_chunks.append(str(text))

        return self._as_openai_style(
            content="\n".join(content_chunks),
            tool_calls=tool_calls,
        )

    def build_request_payload(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        system_prompt, anthropic_messages = self._to_anthropic_messages(messages)
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.pop("max_tokens", 1024),
        }
        if system_prompt:
            payload["system"] = system_prompt
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)
        return payload


class AnthropicOllamaProvider(BaseProvider):
    provider_name = "anthropic_compatible"
    schema_key = "anthropic"
    wire_compatible_with_openai = False

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        try:
            import requests
        except Exception as exc:  # pragma: no cover
            raise ProviderDependencyError("requests package is required for ollama anthropic compatibility.") from exc

        if not config.base_url:
            raise ProviderError("base_url is required for anthropic-compatible provider.")
        self._requests = requests

    @staticmethod
    def _normalize_tool_choice(tool_choice: Any) -> Optional[Dict[str, Any]]:
        if tool_choice is None:
            return None
        if isinstance(tool_choice, dict):
            return tool_choice
        if isinstance(tool_choice, str):
            tc = str(tool_choice).lower().strip()
            if tc in {"none", "auto"}:
                return {"type": tc}
            if tc in {"required", "any"}:
                return {"type": "any"}
        return {"type": "auto"}

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Any:
        system_prompt, anthropic_messages = AnthropicProvider._to_anthropic_messages(self, messages)  # type: ignore[union-attr]
        if not anthropic_messages:
            anthropic_messages = []

        request_payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.pop("max_tokens", 1024),
        }
        if system_prompt:
            request_payload["system"] = system_prompt
        if tools:
            request_payload["tools"] = tools
        tool_choice = self._normalize_tool_choice(kwargs.pop("tool_choice", "auto"))
        if tool_choice is not None:
            request_payload["tool_choice"] = tool_choice
        request_payload.update(kwargs)

        response = self._requests.post(
            f"{self.config.base_url.rstrip('/')}/messages",
            json=request_payload,
            timeout=kwargs.pop("timeout", 30),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.config.api_key}"},
        )
        if response.status_code >= 400:
            raise ProviderError(f"Anthropic-compatible request failed: {response.status_code}: {response.text}")

        payload = response.json()
        if not isinstance(payload, dict):
            return self._as_openai_style(content=str(payload))

        message_content = payload.get("content", []) or []
        if isinstance(message_content, str):
            return self._as_openai_style(content=message_content)

        tool_calls: List[_OpenAIStyleToolCall] = []
        content_chunks: List[str] = []
        for block in message_content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "tool_use":
                name = block.get("name", "")
                args = _coerce_tool_call_arguments(block.get("input"))
                call_id = block.get("id") or str(uuid.uuid4())
                tool_calls.append(
                    _OpenAIStyleToolCall(
                        id=str(call_id),
                        function=_OpenAIStyleFunction(
                            name=str(name),
                            arguments=_to_json_string(args),
                        ),
                    )
                )
                continue
            if block_type in {"text", "thinking"}:
                text = block.get("text")
                if isinstance(text, str) and text:
                    content_chunks.append(text)

        return self._as_openai_style(
            content="\n".join(content_chunks),
            tool_calls=tool_calls,
        )

    def build_request_payload(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        system_prompt, anthropic_messages = self._to_anthropic_messages(messages)
        request_payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.pop("max_tokens", 1024),
        }
        if system_prompt:
            request_payload["system"] = system_prompt
        if tools:
            request_payload["tools"] = tools
        tool_choice = self._normalize_tool_choice(kwargs.pop("tool_choice", "auto"))
        if tool_choice is not None:
            request_payload["tool_choice"] = tool_choice
        request_payload.update(kwargs)
        return request_payload


class GeminiProvider(BaseProvider):
    provider_name = "gemini"
    schema_key = "gemini"
    wire_compatible_with_openai = False

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
            content = _to_content_text(message.get("content"))

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
                if not _iter_tool_call_entries(message):
                    if content:
                        contents.append({"role": "model", "parts": [{"text": content}]})
                    continue

                parts: List[Dict[str, Any]] = []
                if content:
                    parts.append({"text": content})
                for call in _iter_tool_call_entries(message):
                    item = _tool_call_to_name_and_args(call)
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
                except Exception:
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
            return self._as_openai_style(content="", tool_calls=[])

        content = candidates[0].get("content") or {}
        parts = content.get("parts", []) or []

        tool_calls: List[_OpenAIStyleToolCall] = []
        content_chunks: List[str] = []

        for part in parts:
            function_call = part.get("functionCall")
            if function_call:
                name = function_call.get("name", "")
                args = function_call.get("args", {})
                tool_calls.append(
                    _OpenAIStyleToolCall(
                        id=str(uuid.uuid4()),
                        function=_OpenAIStyleFunction(name=name, arguments=_to_json_string(args)),
                    )
                )
                continue
            text = part.get("text")
            if text:
                content_chunks.append(str(text))

        return self._as_openai_style(
            content="\n".join(content_chunks),
            tool_calls=tool_calls,
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


class BedrockProvider(BaseProvider):
    provider_name = "bedrock"
    schema_key = "bedrock"
    wire_compatible_with_openai = False

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)

    def chat_completion(self, *args: Any, **kwargs: Any) -> Any:
        raise ProviderError("Bedrock runtime call is not implemented in this loop yet.")


def build_provider(provider: str, config: Optional[ProviderConfig] = None) -> BaseProvider:
    provider = canonicalize_provider(provider)

    if provider == "openai":
        if config is None:
            model = _read_env("OLLAMA_MODEL", "qwen3:0.6b")
            base_url = _normalize_openai_base_url(
                _read_env("OLLAMA_BASE_URL", "http://127.0.0.1:12434/v1")
            )
            config = ProviderConfig(
                provider=provider,
                model=model,
                api_key=_read_env("OLLAMA_API_KEY", "ollama"),
                base_url=base_url,
            )
        else:
            config = ProviderConfig(
                provider=config.provider,
                model=config.model,
                api_key=config.api_key,
                base_url=_normalize_openai_base_url(
                    config.base_url or "http://127.0.0.1:12434/v1"
                ),
            )
        return OpenAIProvider(config)

    if provider == "anthropic":
        if config is None:
            config = ProviderConfig(
                provider=provider,
                model=_read_env("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
                api_key=_read_env("ANTHROPIC_API_KEY", ""),
                base_url=None,
            )
        return AnthropicProvider(config)

    if provider == "anthropic_compatible":
        if config is None:
            model = _read_env("ANTHROPIC_MODEL", _read_env("OLLAMA_MODEL", "qwen3:0.6b"))
            config = ProviderConfig(
                provider=provider,
                model=model,
                api_key=_read_env("ANTHROPIC_API_KEY", _read_env("OLLAMA_API_KEY", "ollama")),
                base_url=_normalize_openai_base_url(_read_env("OLLAMA_BASE_URL", "http://127.0.0.1:12434/v1")),
            )
        else:
            config = ProviderConfig(
                provider=config.provider,
                model=config.model,
                api_key=config.api_key,
                base_url=_normalize_openai_base_url(config.base_url or "http://127.0.0.1:12434/v1"),
            )
        return AnthropicOllamaProvider(config)

    if provider == "gemini":
        if config is None:
            config = ProviderConfig(
                provider=provider,
                model=_read_env("GEMINI_MODEL", "gemini-1.5-flash"),
                api_key=_read_env("GEMINI_API_KEY", ""),
                base_url=None,
            )
        return GeminiProvider(config)

    if provider == "bedrock":
        if config is None:
            config = ProviderConfig(
                provider=provider,
                model=_read_env("BEDROCK_MODEL", "anthropic.claude-3-5-sonnet"),
                api_key="",
                base_url=None,
            )
        return BedrockProvider(config)

    raise ProviderError(f"Unsupported provider: {provider}")

import argparse
import json
import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Optional

import requests

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE
PROVIDER_FILE = HERE / "provider.py"
REGISTRY_FILE = AGENT_ROOT / "tool_registry.py"
ENV_PATH = AGENT_ROOT.parent / ".env"


def _load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip().strip('"').strip("'")
        if not key:
            continue
        if key not in os.environ:
            os.environ[key] = value


_load_dotenv_file(ENV_PATH)


def _load_module(module_name: str, file_path: Path):
    spec = spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module from {file_path}")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


def _load_runtime_modules():
    try:
        from agent.provider import build_provider
        from agent.tool_registry import ToolRegistry
        return ToolRegistry, build_provider
    except Exception:
        provider_mod = _load_module("provider_module", PROVIDER_FILE)
        try:
            registry_mod = _load_module("tool_registry_module", REGISTRY_FILE)
            tool_registry_cls = registry_mod.ToolRegistry
        except Exception:
            class _FallbackToolRegistry:
                def __init__(self):
                    self.tools = {
                        "get_current_time": {
                            "description": "Get current time in timezone",
                            "parameters": {
                                "type": "object",
                                "properties": {"timezone": {"type": "string"}},
                                "required": ["timezone"],
                            },
                        },
                        "get_current_temperature": {
                            "description": "Get current temperature in specific location",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "location": {"type": "string", "description": "City, Country"},
                                    "unit": {
                                        "type": "string",
                                        "enum": ["celsius", "fahrenheit"],
                                        "description": "Temperature unit",
                                    },
                                },
                                "required": ["location", "unit"],
                            },
                        },
                        "convert_currency": {
                            "description": "Convert an amount from one currency to another",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "amount": {"type": "number", "description": "Amount to convert"},
                                    "from_currency": {"type": "string", "description": "Source currency"},
                                    "to_currency": {"type": "string", "description": "Target currency"},
                                },
                                "required": ["amount", "from_currency", "to_currency"],
                            },
                        },
                        "code_interpreter": {
                            "description": "Execute Python code for calculations",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "code": {"type": "string", "description": "Python code to execute"},
                                },
                                "required": ["code"],
                            },
                        }
                    }

                def get_tool_schemas(self, provider: str):
                    # Keep output shape provider-specific but stable.
                    if provider in {"anthropic", "gemini"}:
                        return [
                            {
                                "name": name,
                                "description": tool["description"],
                                "input_schema" if provider == "anthropic" else "parameters":
                                tool["parameters"],
                            } for name, tool in self.tools.items()
                        ]
                    if provider == "bedrock":
                        return [
                            {
                                "toolSpec": {
                                    "name": name,
                                    "description": tool["description"],
                                    "inputSchema": {"json": tool["parameters"]},
                                }
                            } for name, tool in self.tools.items()
                        ]
                    return [
                        {
                            "type": "function",
                            "function": {
                                "name": name,
                                "description": tool["description"],
                                "parameters": tool["parameters"],
                            },
                        } for name, tool in self.tools.items()
                    ]

            tool_registry_cls = _FallbackToolRegistry
        return tool_registry_cls, provider_mod.build_provider


ToolRegistry, build_provider = _load_runtime_modules()


def _schema_preview(provider: str) -> tuple[str, str]:
    registry = ToolRegistry()
    schemas = registry.get_tool_schemas(provider)
    count = len(schemas)
    if not schemas:
        return provider, "0 items"

    return provider, f"{count} items, first keys={list(schemas[0].keys())}"


def _normalize_request_provider(provider_name: str) -> str:
    provider_name = provider_name.strip().lower()
    if provider_name in {"openai_compatible", "openai-compatible"}:
        return "openai"
    if provider_name in {"anthropic_compatible", "anthropic-compatible"}:
        return "anthropic_compatible"
    if (
        provider_name == "anthropic"
        and not os.getenv("ANTHROPIC_API_KEY", "").strip()
    ):
        return "anthropic_compatible"
    return provider_name


def _simulate_provider_request(provider_name: str) -> dict[str, Any]:
    # Shared message path; model prompts should encourage tool usage.
    messages = [
        {
            "role": "system",
            "content": "You are a concise assistant. Use the provided tools when needed.",
        },
        {
            "role": "user",
            "content": "Get the current date and time in UTC. Return only tool result."
        },
    ]

    runtime_provider = _normalize_request_provider(provider_name)

    registry = ToolRegistry()
    schema_key = runtime_provider
    if runtime_provider.startswith("openai"):
        schema_key = "openai"
    elif runtime_provider.startswith("anthropic"):
        schema_key = "anthropic"
    tool_schemas = registry.get_tool_schemas(schema_key)
    provider = build_provider(runtime_provider)
    kwargs = {}
    if runtime_provider in {"openai", "openai_compatible", "openai-compatible"}:
        kwargs["tool_choice"] = "required"
        kwargs["max_tokens"] = 512
    elif runtime_provider in {"anthropic", "anthropic_compatible", "anthropic-compatible"}:
        kwargs["tool_choice"] = "required"
        kwargs["max_tokens"] = 512

    response = provider.chat_completion(messages=messages, tools=tool_schemas, **kwargs)
    assistant_message = response.choices[0].message
    content = getattr(assistant_message, "content", "")

    tool_calls = getattr(assistant_message, "tool_calls", []) or []
    tool_call_names = [getattr(tc.function, "name", None) or "" for tc in tool_calls]

    if not tool_calls:
        parsed = _parse_tool_call_from_content(content)
        if parsed is not None:
            tool_calls = [parsed]
            tool_call_names = [parsed.get("name", "")]

    return {
        "provider": runtime_provider,
        "content": content,
        "tool_calls": len(tool_calls),
        "tool_call_names": tool_call_names,
    }


def _parse_tool_call_from_content(content: str) -> Optional[dict[str, Any]]:
    text = (content or "").strip()
    if not text:
        return None

    if not (text.startswith("{") and text.endswith("}")):
        return None

    try:
        payload = json.loads(text)
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    if "name" not in payload or "arguments" not in payload:
        return None

    name = str(payload.get("name") or "").strip()
    if not name:
        return None

    return {"name": name, "arguments": _ensure_mapping(payload.get("arguments"))}


def _ensure_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"arguments": value}


def _normalize_openai_base_url(base_url: str, default: str = "http://127.0.0.1:11434/v1") -> str:
    normalized = (base_url or "").strip() or default
    normalized = normalized.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


def _is_openai_compatible(provider_name: str) -> bool:
    return provider_name in {"openai", "openai_compatible", "openai-compatible"}


def _is_anthropic_compatible(provider_name: str) -> bool:
    return provider_name in {"anthropic_compatible", "anthropic-compatible"}


def _probe_anthropic_like(base_url: str) -> dict[str, Any]:
    normalized = _normalize_openai_base_url(base_url)
    payload = {
        "model": os.getenv("OLLAMA_MODEL", "qwen3:0.6b"),
        "messages": [{"role": "user", "content": "test"}],
        "max_tokens": 32,
    }
    response = requests.post(f"{normalized}/messages", json=payload, timeout=3)
    return {"status": response.status_code, "ok": response.ok}


def _probe_openai_like(base_url: str) -> dict[str, Any]:
    # Quick compatibility probe for local OpenAI-compatible endpoints.
    normalized = _normalize_openai_base_url(base_url)
    response = requests.get(f"{normalized}/models", timeout=3)
    return {"status": response.status_code, "ok": response.ok}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate tool schema adapters and providers")
    parser.add_argument(
        "--provider",
        action="append",
        default=None,
        help="Provider name to validate",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run a live provider call (requires API keys and network)",
    )
    args = parser.parse_args()

    print("=== Tool schema compatibility check ===")
    providers = args.provider or ["openai"]
    providers = list(dict.fromkeys([p.strip().lower() for p in providers if p and p.strip()]))

    for provider_name in providers:
        try:
            provider_name = provider_name.strip().lower()
            schema_provider = provider_name
            if schema_provider in {"openai_compatible", "openai-compatible"}:
                schema_provider = "openai"
            elif schema_provider in {"anthropic_compatible", "anthropic-compatible"}:
                schema_provider = "anthropic"
            provider_name, summary = _schema_preview(schema_provider)
            print(f"[schema] {provider_name}: {summary}")
        except Exception as exc:
            print(f"[schema] {provider_name}: ERROR: {type(exc).__name__}: {exc}")

    if not args.live:
        print("Dry run finished. Use --live to test runtime calls.")
        return

    print("=== Live call check ===")
    for provider_name in providers:
        provider_name = provider_name.strip().lower()
        try:
            runtime_provider = _normalize_request_provider(provider_name)

            if _is_openai_compatible(runtime_provider):
                raw_base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:12434/v1")
                normalized_base_url = _normalize_openai_base_url(raw_base_url)
                if normalized_base_url != raw_base_url.rstrip("/"):
                    os.environ["OLLAMA_BASE_URL"] = normalized_base_url
                    print(
                        f"[live] {provider_name}: OLLAMA_BASE_URL missing '/v1', auto-normalized to '{normalized_base_url}'"
                    )
                probe = _probe_openai_like(
                    normalized_base_url
                )
                print(f"[live] {provider_name}: endpoint probe {probe}")
            elif _is_anthropic_compatible(runtime_provider):
                raw_base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:12434/v1")
                normalized_base_url = _normalize_openai_base_url(raw_base_url)
                if normalized_base_url != raw_base_url.rstrip("/"):
                    os.environ["OLLAMA_BASE_URL"] = normalized_base_url
                    print(
                        f"[live] {provider_name}: OLLAMA_BASE_URL missing '/v1', auto-normalized to '{normalized_base_url}'"
                    )
                probe = _probe_anthropic_like(
                    normalized_base_url
                )
                print(f"[live] {provider_name}: endpoint probe {probe}")

            result = _simulate_provider_request(runtime_provider)
            result["provider"] = provider_name
            print(f"[live] {provider_name}: {json.dumps(result, ensure_ascii=False)}")
        except Exception as exc:
            print(f"[live] {provider_name}: ERROR {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()

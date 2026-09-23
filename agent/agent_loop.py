"""ReAct execution loop."""

import functools
import inspect
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent.models import (
    EventCategory,
    EventSink,
    LLMRequestData,
    LLMResponseData,
    TaskEvent,
    ToolCallData,
    ToolOutcome,
    ToolResultData,
)
from agent.modes import (
    build_system_prompt,
    build_system_prompt_from_config,
    build_tool_registry,
    build_tool_registry_from_names,
)
from agent.provider import (
    ProviderConfig,
    build_provider,
    canonicalize_provider,
    resolve_tool_provider_for_schemas,
)
from agent.tools import process_store
from agent.tools.file_access import default_workspace_root
from agent.tools.permissions import PermissionBroker
from agent.tool_registry import ToolRegistry

DEFAULT_PROVIDER = os.getenv("TOOL_SCHEMA_PROVIDER", "openai")
DEFAULT_USER_QUERY = "What's the current time and weather in Vancouver?"
DEFAULT_MAX_STEPS = int(os.getenv("REACT_MAX_STEPS", "8"))


def _to_content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _to_dict(message: Any) -> Dict[str, Any]:
    if isinstance(message, dict):
        return message

    role = getattr(message, "role", "assistant")
    content = _to_content_text(getattr(message, "content", ""))

    tool_calls_obj = getattr(message, "tool_calls", None)
    tool_calls = []
    for tool_call in tool_calls_obj or []:
        function = getattr(tool_call, "function", None)
        if function is None and isinstance(tool_call, dict):
            function = tool_call.get("function")
        if function is None:
            continue
        name = getattr(function, "name", None) or (
            function.get("name") if isinstance(function, dict) else None
        )
        if not name:
            continue
        arguments = getattr(function, "arguments", None)
        if arguments is None and isinstance(function, dict):
            arguments = function.get("arguments")
        if isinstance(arguments, str):
            function_args = arguments
        else:
            function_args = _to_content_text(arguments)
        tool_calls.append(
            {
                "id": getattr(tool_call, "id", None) or str(_new_id()),
                "type": "function",
                "function": {
                    "name": str(name),
                    "arguments": function_args,
                },
            }
        )

    result = {"role": role, "content": content}
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result


def _new_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _parse_tool_calls(message: Any) -> List[Tuple[str, Dict[str, Any], str]]:
    parsed = []
    raw_tool_calls = getattr(message, "tool_calls", None)
    if raw_tool_calls is None and isinstance(message, dict):
        raw_tool_calls = message.get("tool_calls", [])

    for call in raw_tool_calls or []:
        function = getattr(call, "function", None)
        if function is None and isinstance(call, dict):
            function = call.get("function")
        if function is None:
            continue

        name = getattr(function, "name", None) or (
            function.get("name") if isinstance(function, dict) else None
        )
        if not name:
            continue

        raw_args = getattr(function, "arguments", None)
        if raw_args is None and isinstance(function, dict):
            raw_args = function.get("arguments")

        try:
            args = (
                json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            )
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError:
            args = {}

        call_id = getattr(call, "id", None)
        if call_id is None and isinstance(call, dict):
            call_id = call.get("id")
        parsed.append((str(name), args, str(call_id or _new_id())))
    return parsed


def _tool_fallback_parse(content: str) -> Optional[Tuple[str, Dict[str, Any], str]]:
    """Some providers may return tool calls as JSON in plain text content."""
    text = (content or "").strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        payload = json.loads(text)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    name = str(payload.get("name", "")).strip()
    if not name:
        return None
    args = payload.get("arguments", {})
    if not isinstance(args, dict):
        return None
    return name, args, _new_id()


def _with_base_dir(prompt: str, base_dir: Optional[str]) -> str:
    """Append the working directory so relative paths resolve against that folder."""
    directory = (base_dir or "").strip()
    if not directory:
        # An unbound session still resolves relative paths somewhere, and the model
        # has to know where that is before it writes a file into it.
        return (
            f"{prompt}\n\n## Working directory\n"
            "This session has no workspace bound, so relative file paths resolve against "
            f"{default_workspace_root().as_posix()}. Use an absolute path when you need a "
            "specific location."
        )
    return (
        f"{prompt}\n\n## Working directory\n"
        f"All project tasks run inside the workspace root folder: {directory}\n"
        "Treat this folder as the base for every relative file path and keep all reads "
        "and writes inside it."
    )


def _emit(
    event_sink: EventSink | None,
    task_id: str | None,
    event: TaskEvent,
) -> None:
    if event_sink is None or task_id is None:
        return
    try:
        event_sink(task_id, event)
    except Exception:
        # Event emission failures should not interrupt main flow.
        return


def _execute_tool(registry: ToolRegistry, name: str, arguments: Any) -> Any:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    return registry.execute_tool(name, arguments)


def _build_runtime(
    provider_name: Optional[str] = None,
    provider_config: Optional[ProviderConfig] = None,
    enable_tools: bool = True,
    mode: str = "build",
    base_dir: Optional[str] = None,
    agent_config: Optional[Dict[str, Any]] = None,
    task_id: str = "",
) -> tuple[str, ToolRegistry, Any, Optional[List[Dict[str, Any]]]]:
    provider_name = canonicalize_provider(provider_name or DEFAULT_PROVIDER)
    registry_options = {
        "base_dir": base_dir,
        "max_tokens": int(getattr(provider_config, "max_input_tokens", 0) or 0),
        "provider": provider_name,
        "model": getattr(provider_config, "model", "") or "",
        "task_id": task_id,
    }
    if not enable_tools:
        registry = ToolRegistry(enabled_tools=[], **registry_options)
    elif agent_config is not None:
        registry = build_tool_registry_from_names(
            agent_config.get("tool_names"), **registry_options
        )
    else:
        registry = build_tool_registry(mode, **registry_options)
    tool_schemas: Optional[List[Dict[str, Any]]] = None
    if enable_tools:
        try:
            request_provider = resolve_tool_provider_for_schemas(provider_name)
            tool_schemas = registry.get_tool_schemas(request_provider)
        except ValueError:
            print(
                f"Unsupported TOOL_SCHEMA_PROVIDER='{provider_name}', fallback to openai schema"
            )
            provider_name = "openai"
            tool_schemas = registry.get_tool_schemas("openai")

    provider = build_provider(provider_name, provider_config)
    return provider_name, registry, provider, tool_schemas


def _reaps_task_sessions(func):
    """Stop the loop's live sessions when it returns, however it returns.

    The loop has several exits (a final answer, the step limit, a stop request), so
    the reaping cannot be bolted onto one of them, and a ``finally`` inside would
    mean re-indenting the whole body. A wrapper keeps the change local and, because
    it sits here, every caller gets it: the API server, both CLI entry points and
    any library driving the loop directly (ADR 0008: sessions are task scoped).
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            bound = inspect.signature(func).bind_partial(*args, **kwargs)
            task_id = str(bound.arguments.get("task_id") or "")
            if task_id:
                process_store.stop_task(task_id)

    return wrapper


@_reaps_task_sessions
def run_react_loop(
    user_query: Optional[str] = DEFAULT_USER_QUERY,
    provider_name: Optional[str] = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    verbose: bool = True,
    initial_messages: Optional[List[Dict[str, Any]]] = None,
    task_id: str | None = None,
    event_sink: EventSink | None = None,
    provider_config: Optional[ProviderConfig] = None,
    enable_tools: bool = True,
    max_output_tokens: Optional[int] = None,
    thinking_mode: bool = False,
    mode: str = "build",
    base_dir: Optional[str] = None,
    agent_config: Optional[Dict[str, Any]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    permission_broker: Optional[PermissionBroker] = None,
) -> str:
    _, registry, provider, request_tools = _build_runtime(
        provider_name=provider_name,
        provider_config=provider_config,
        enable_tools=enable_tools,
        mode=mode,
        base_dir=base_dir,
        agent_config=agent_config,
        task_id=task_id or "",
    )

    if permission_broker is not None:
        # The registry owns the workspace root and the exec_command scratch root, and the
        # broker needs both to tell a sensitive read from a scratch-output read
        # (ADR 0006 D3/D9). Handing it over here is what makes the gate cover
        # every tool: this registry is the one the loop dispatches through.
        if not permission_broker.base_dir:
            permission_broker.base_dir = registry.base_dir
        permission_broker.extra_read_roots = tuple(permission_broker.extra_read_roots) + tuple(
            registry.read_only_roots
        )
        registry.permission_broker = permission_broker

    if verbose:
        print(f"Provider: {provider.config.provider}")
        print(f"Provider model: {provider.config.model}")
        print(f"Provider tool schemas: {(request_tools or [])[:1]}")

    if initial_messages is not None:
        messages = initial_messages
    else:
        if agent_config is not None:
            system_prompt = build_system_prompt_from_config(agent_config, enable_tools=enable_tools)
        elif enable_tools:
            system_prompt = build_system_prompt(mode, enable_tools=True)
        else:
            system_prompt = "You are a helpful assistant. Answer the user request directly and clearly."
        system_prompt = _with_base_dir(system_prompt, base_dir)
        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
        ]

    effective_query = user_query if user_query is not None else DEFAULT_USER_QUERY
    messages.append({"role": "user", "content": effective_query})

    _emit(
        event_sink,
        task_id,
        TaskEvent(
            task_id=task_id or "",
            category=EventCategory.DEBUG,
            title="Starting ReAct loop",
            data={
                "provider": provider.config.provider,
                "max_steps": max_steps,
                "query": effective_query,
                "model": provider.config.model,
                "mode": mode,
                "tools_enabled": enable_tools,
                "thinking_mode": thinking_mode,
                "max_output_tokens": max_output_tokens,
                "base_dir": base_dir,
                "agent_id": (agent_config or {}).get("agent_id"),
                "mcp_servers": (agent_config or {}).get("mcp_servers"),
            },
            collapsed=True,
        ),
    )

    final_output: Optional[str] = None
    stopped = False

    for step in range(1, max_steps + 1):
        if should_stop is not None and should_stop():
            stopped = True
            break
        if verbose:
            print(f"\n=== ReAct Step {step}/{max_steps} ===")

        request_kwargs: Dict[str, Any] = {"tool_choice": "auto"}
        if max_output_tokens:
            request_kwargs["max_tokens"] = int(max_output_tokens)
        if thinking_mode and getattr(provider, "wire_compatible_with_openai", False):
            request_kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": True}
            }

        request_data = LLMRequestData(
            step=step,
            model=provider.config.model,
            provider=provider.config.provider,
            tool_count=len(request_tools or []),
            message_count=len(messages),
            tool_choice="auto",
        )
        raw_request_payload = provider.build_request_payload(
            messages=messages,
            tools=request_tools,
            **request_kwargs,
        )
        request_data_dict = request_data.model_dump()
        request_data_dict["raw_request"] = raw_request_payload
        _emit(
            event_sink,
            task_id,
            TaskEvent(
                task_id=task_id or "",
                category=EventCategory.LLM_REQUEST,
                title=f"LLM request Step {step}",
                data=request_data_dict,
                collapsed=True,
            ),
        )

        response = provider.chat_completion(**raw_request_payload)
        assistant_message = response.choices[0].message
        message_dict = _to_dict(assistant_message)
        messages.append(message_dict)

        assistant_content = _to_content_text(message_dict.get("content"))
        if verbose:
            print(f"[assistant] {assistant_content or '(no direct content)'}")

        tool_calls = _parse_tool_calls(assistant_message)

        if not tool_calls:
            tool_call = _tool_fallback_parse(assistant_content)
            if tool_call is not None:
                tool_calls = [tool_call]

        finish_reason = (
            getattr(response, "choices", [{}])[0].finish_reason
            if getattr(response, "choices", None)
            else None
        )
        response_data = LLMResponseData(
            step=step,
            provider=provider.config.provider,
            model=provider.config.model,
            finish_reason=str(finish_reason) if finish_reason else None,
            content=assistant_content,
        )
        response_data.tool_call_count = len(tool_calls)
        response_data_dict = response_data.model_dump()
        if hasattr(response, "model_dump"):
            response_payload = response.model_dump()
        elif hasattr(response, "dict"):
            response_payload = response.dict()
        else:
            response_payload = _to_dict(response)
        response_data_dict["raw_response"] = response_payload

        _emit(
            event_sink,
            task_id,
            TaskEvent(
                task_id=task_id or "",
                category=EventCategory.LLM_RESPONSE,
                title=f"LLM response Step {step}",
                data=response_data_dict,
                collapsed=True,
            ),
        )

        if not tool_calls:
            final_output = assistant_content or ""
            _emit(
                event_sink,
                task_id,
                TaskEvent(
                    task_id=task_id or "",
                    category=EventCategory.DEBUG,
                    title="ReAct finished",
                    data={
                        "reason": "No tool call, returning direct result.",
                        "step": step,
                        "result": final_output,
                    },
                    collapsed=True,
                ),
            )
            break

        for name, args, call_id in tool_calls:
            if should_stop is not None and should_stop():
                stopped = True
                break
            call_data = ToolCallData(
                step=step,
                name=name,
                arguments=args,
                tool_call_id=call_id,
            )
            _emit(
                event_sink,
                task_id,
                TaskEvent(
                    task_id=task_id or "",
                    category=EventCategory.TOOL_CALL,
                    title=f"Tool call: {name}",
                    data=call_data.model_dump(),
                    collapsed=True,
                ),
            )

            outcome: Any = None
            try:
                outcome = _execute_tool(registry, name, args)
                result = outcome.model_text if isinstance(outcome, ToolOutcome) else outcome
                tool_result_payload = ToolResultData(
                    step=step,
                    name=name,
                    tool_call_id=call_id,
                    result=result,
                    is_error=False,
                )
            except Exception as exc:
                result = f"Error: {exc}"
                tool_result_payload = ToolResultData(
                    step=step,
                    name=name,
                    tool_call_id=call_id,
                    result=result,
                    is_error=True,
                )
                _emit(
                    event_sink,
                    task_id,
                    TaskEvent(
                        task_id=task_id or "",
                        category=EventCategory.ERROR,
                        title=f"Tool error: {name}",
                        data={"step": step, "name": name, "error": str(exc)},
                        collapsed=True,
                    ),
                )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": result,
                }
            )
            _emit(
                event_sink,
                task_id,
                TaskEvent(
                    task_id=task_id or "",
                    category=EventCategory.TOOL_RESULT,
                    title=f"Tool result: {name}",
                    data=tool_result_payload.model_dump(),
                    collapsed=True,
                ),
            )

            # Rich tool payloads (for the UI / external consumers) travel on their
            # own event so the model only ever sees the short ``model_text``.
            if isinstance(outcome, ToolOutcome) and outcome.event_category is not None:
                _emit(
                    event_sink,
                    task_id,
                    TaskEvent(
                        task_id=task_id or "",
                        category=outcome.event_category,
                        title=outcome.event_title or f"{name}",
                        data=outcome.details,
                        collapsed=True,
                    ),
                )

            if verbose:
                print(f"[tool:{name}] {result}")

        if stopped:
            break

    if stopped:
        final_output = "Task stopped by user."
        _emit(
            event_sink,
            task_id,
            TaskEvent(
                task_id=task_id or "",
                category=EventCategory.DEBUG,
                title="ReAct stopped",
                data={"reason": final_output},
                collapsed=True,
            ),
        )
        if verbose:
            print("[warn] loop stopped by user")
        return final_output

    if final_output is None:
        final_output = "Reached maximum reasoning steps without a final answer."
        _emit(
            event_sink,
            task_id,
            TaskEvent(
                task_id=task_id or "",
                category=EventCategory.ERROR,
                title="Reached maximum step limit",
                data={"reason": final_output},
                collapsed=True,
            ),
        )
        if verbose:
            print("[warn] loop reached max_steps without final assistant turn")

    if verbose:
        print(f"\n=== ReAct Final ===\n{final_output}")

    _emit(
        event_sink,
        task_id,
        TaskEvent(
            task_id=task_id or "",
            category=EventCategory.DEBUG,
            title="ReAct run completed",
            data={"result": final_output},
            collapsed=True,
        ),
    )

    return final_output

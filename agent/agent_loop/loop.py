"""The ReAct execution loop itself."""

from typing import Any, Callable, Dict, List, Optional, Tuple

from agent.agent_loop.config import DEFAULT_MAX_STEPS
from agent.agent_loop.messages import (
    _parse_tool_calls,
    _to_content_text,
    _to_dict,
    _tool_fallback_parse,
    _with_base_dir,
)
from agent.agent_loop.runtime import (
    _build_runtime,
    _emit,
    _execute_tool,
    _reaps_task_sessions,
)
from agent.llm_errors import describe_llm_failure
from agent.models import (
    EventCategory,
    EventSink,
    LLMRequestData,
    LLMResponseData,
    TaskEvent,
    ToolCallData,
    ToolImage,
    ToolOutcome,
    ToolResultData,
)
from agent.modes import (
    build_system_prompt,
    build_system_prompt_from_config,
)
from agent.provider import ProviderConfig
from agent.tools.permissions import PermissionBroker
from agent.tools.user_question import UserQuestionBroker
from agent.vision import build_image_message, redact_image_payload, supports_images


@_reaps_task_sessions
def run_react_loop(
    user_query: str,
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
    user_question_broker: Optional[UserQuestionBroker] = None,
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

    # The question channel, assigned the same way and read per call. Leaving it unset
    # is a valid configuration, not an error: ``ask_user_question`` then answers
    # "no_client" instead of blocking (ADR 0010 D4).
    registry.user_question_broker = user_question_broker

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

    messages.append({"role": "user", "content": user_query})

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
                "query": user_query,
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
        # Screenshots ride along as base64 data URLs; persist a redacted copy so
        # one observation does not add megabytes to the event log.
        request_data_dict["raw_request"] = redact_image_payload(raw_request_payload)
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

        # A model that is down or misconfigured is a routine failure, not a crash in
        # the agent: describe it in terms the operator can act on, record it as an
        # error event (the web admin shows it), and let the caller decide whether to
        # retry. The raw SDK exception never escapes this loop.
        try:
            response = provider.chat_completion(**raw_request_payload)
        except Exception as exc:  # noqa: BLE001 - every provider failure is reported
            failure = describe_llm_failure(exc, provider)
            _emit(
                event_sink,
                task_id,
                TaskEvent(
                    task_id=task_id or "",
                    category=EventCategory.ERROR,
                    title=f"LLM request failed (step {step})",
                    data={
                        "step": step,
                        "provider": failure.provider,
                        "model": failure.model,
                        "endpoint": failure.endpoint,
                        "type": type(exc).__name__,
                        "error": str(failure),
                    },
                    collapsed=True,
                ),
            )
            raise failure from exc
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

        # Screenshots collected during this step. They travel as one follow-up
        # user message after every tool result, because the OpenAI chat API only
        # accepts text in a ``tool`` message (see ``agent.vision``).
        pending_images: List[Tuple[str, ToolImage]] = []
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
            # Deliberately broad: a tool may raise anything, and each failure has to
            # reach the model as a result instead of aborting the step.
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
            except Exception as exc:  # noqa: BLE001
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

            if isinstance(outcome, ToolOutcome) and outcome.images:
                pending_images.extend((name, image) for image in outcome.images)

            if verbose:
                print(f"[tool:{name}] {result}")

        if pending_images and not stopped:
            image_message = build_image_message(pending_images, provider)
            if image_message is not None:
                messages.append(image_message)
                _emit(
                    event_sink,
                    task_id,
                    TaskEvent(
                        task_id=task_id or "",
                        category=EventCategory.DEBUG,
                        title="Attached screenshots",
                        data={
                            "step": step,
                            "count": len(pending_images),
                            "files": [image.path for _, image in pending_images],
                        },
                        collapsed=True,
                    ),
                )
            else:
                _emit(
                    event_sink,
                    task_id,
                    TaskEvent(
                        task_id=task_id or "",
                        category=EventCategory.DEBUG,
                        title="Screenshots not attached",
                        data={
                            "step": step,
                            "files": [image.path for _, image in pending_images],
                            "reason": (
                                "model image input is disabled or the provider wire format "
                                "is not OpenAI-compatible"
                                if not supports_images(provider)
                                else "screenshot files were missing or exceeded the size limit"
                            ),
                        },
                        collapsed=True,
                    ),
                )
                if verbose:
                    print("[info] screenshots were not attached: model or provider does not accept images")

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

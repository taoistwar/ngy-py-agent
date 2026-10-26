"""The ReAct execution loop itself."""

from typing import Any, Callable, Dict, List, Optional, Tuple

from agent.agent_loop.config import DEFAULT_MAX_STEPS
from agent.agent_loop.messages import _with_base_dir, _with_history
from agent.agent_loop.result_budget import apply_result_budget
from agent.agent_loop.runtime import (
    _build_runtime,
    _emit,
    _reaps_task_sessions,
    _traced_run,
)
from agent.agent_loop.snip_compact import apply_snip_compact
from agent.agent_loop.steps import run_model_turn, run_tool
from agent.models import (
    EventCategory,
    EventSink,
    TaskEvent,
    ToolImage,
    ToolOutcome,
)
from agent.modes import (
    build_system_prompt,
    build_system_prompt_from_config,
)
from agent.provider import ProviderConfig
from agent.telemetry import current_trace_ids, react_step_span
from agent.tools.permissions import PermissionBroker
from agent.tools.user_question import UserQuestionBroker
from agent.vision import build_image_message, supports_images


@_reaps_task_sessions
@_traced_run
def run_react_loop(
    user_query: str,
    provider_name: Optional[str] = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    verbose: bool = True,
    initial_messages: Optional[List[Dict[str, Any]]] = None,
    history_messages: Optional[List[Dict[str, Any]]] = None,
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

    if history_messages:
        # Earlier turns of the session sit before this task's query, so a follow-up
        # continues the conversation instead of restarting it. The API builds this
        # from the session's finished tasks (see ``session_history``).
        messages = _with_history(messages, history_messages)

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
                "history_messages": len(history_messages or []),
                **current_trace_ids(),
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
        # Between steps, never inside one: the previous step's tool turn is complete
        # here, and ``batch_start`` below has to index the compacted list.
        apply_snip_compact(
            messages,
            base_dir=getattr(registry, "base_dir", None),
            event_sink=event_sink,
            task_id=task_id,
            step=step,
        )
        if verbose:
            print(f"\n=== ReAct Step {step}/{max_steps} ===")

        request_kwargs: Dict[str, Any] = {"tool_choice": "auto"}
        if max_output_tokens:
            request_kwargs["max_tokens"] = int(max_output_tokens)
        if thinking_mode and getattr(provider, "wire_compatible_with_openai", False):
            request_kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": True}
            }

        with react_step_span(step, max_steps):
            turn = run_model_turn(
                provider,
                step,
                messages,
                request_tools,
                request_kwargs,
                event_sink,
                task_id,
            )
            if verbose:
                print(f"[assistant] {turn.assistant_content or '(no direct content)'}")

            if not turn.tool_calls:
                final_output = turn.assistant_content or ""
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
                            **current_trace_ids(),
                        },
                        collapsed=True,
                    ),
                )
                break

            # Screenshots collected during this step. They travel as one follow-up
            # user message after every tool result, because the OpenAI chat API only
            # accepts text in a ``tool`` message (see ``agent.vision``).
            pending_images: List[Tuple[str, ToolImage]] = []
            # Where this step's tool results start. The budget sweep only looks at
            # these: older results already left the context as paths (ADR 0012).
            batch_start = len(messages)
            for name, args, call_id in turn.tool_calls:
                if should_stop is not None and should_stop():
                    stopped = True
                    break

                outcome, result = run_tool(
                    registry, name, args, call_id, step, event_sink, task_id
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": result,
                    }
                )

                if isinstance(outcome, ToolOutcome) and outcome.images:
                    pending_images.extend((name, image) for image in outcome.images)

                if verbose:
                    print(f"[tool:{name}] {result}")

            if not stopped:
                # A stopped step returns right after this block, so moving its
                # results to disk would only leave files nobody reads.
                apply_result_budget(
                    messages,
                    batch_start,
                    base_dir=getattr(registry, "base_dir", None),
                    event_sink=event_sink,
                    task_id=task_id,
                    step=step,
                )

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
                                **current_trace_ids(),
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
                                **current_trace_ids(),
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
                data={"reason": final_output, **current_trace_ids()},
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
                data={"reason": final_output, **current_trace_ids()},
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
            data={"result": final_output, **current_trace_ids()},
            collapsed=True,
        ),
    )

    return final_output

"""The ReAct execution loop itself."""

from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from agent.agent_loop.background_context import inject_background_results
from agent.agent_loop.compact_history import compact_history
from agent.agent_loop.config import DEFAULT_MAX_STEPS
from agent.agent_loop.messages import _with_base_dir, _with_history
from agent.agent_loop.micro_compact import mark_seen, prepare_context
from agent.agent_loop.model_turn import run_model_turn
from agent.agent_loop.result_budget import apply_result_budget
from agent.agent_loop.runtime import (
    _build_runtime,
    _emit,
    _reaps_task_sessions,
    _traced_run,
)
from agent.agent_loop.snip_compact import apply_snip_compact
from agent.agent_loop.steps import run_tool
from agent.agent_loop.subagent import SUBAGENT_TOOL_NAME, make_subagent_runner
from agent.agent_loop.todo_context import append_todo_context
from agent.agent_loop.todo_reminder import (
    TODO_WRITE_TOOL_NAME,
    TodoReminder,
    append_to_last_tool_message,
)
from agent.agents_md import (
    AgentsMdInstructions,
    AgentsMdSettings,
    append_project_instructions,
    load_instructions,
)
from agent.mcp.prompt import append_server_status
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
from agent.tools.background import BackgroundTasks
from agent.tools.permissions import PermissionBroker
from agent.tools.user_question import UserQuestionBroker
from agent.vision import build_image_message, redact_image_payload, supports_images


@_reaps_task_sessions
@_traced_run
def run_react_loop(
    user_query: str,
    provider_name: Optional[str] = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    verbose: bool = True,
    initial_messages: Optional[List[Dict[str, Any]]] = None,
    # A resumed run starts from a conversation that already ends with the query, so
    # appending it again would ask the model the same thing twice.
    append_user_query: bool = True,
    # Where the step counter starts: a resumed run continues the numbering of the one
    # that died, which is what keeps ``max_steps`` meaning one budget per task.
    first_step: int = 1,
    history_messages: Optional[List[Dict[str, Any]]] = None,
    task_id: str | None = None,
    event_sink: EventSink | None = None,
    provider_config: Optional[ProviderConfig] = None,
    enable_tools: bool = True,
    max_output_tokens: Optional[int] = None,
    thinking_mode: bool = False,
    # Streaming is the default: it is what surfaces the reasoning trace on gateways
    # that only send it incrementally, and it fails fast instead of after a minute
    # of silence. Adapters without a stream mode answer in one piece anyway.
    stream: bool = True,
    mode: str = "build",
    base_dir: Optional[str] = None,
    agent_config: Optional[Dict[str, Any]] = None,
    # Global AGENTS.md rules (on/off and byte cap), resolved by the web layer from
    # env + database. ``None`` means "ask the environment" (ADR 0022).
    agents_md_settings: Optional[AgentsMdSettings] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    permission_broker: Optional[PermissionBroker] = None,
    user_question_broker: Optional[UserQuestionBroker] = None,
    # The conversation's plan (``todo_write``). The app layer binds the session's
    # board; ``None`` keeps the plan in memory for this run.
    todo_board: Any = None,
    # The project's task board (``task_*``); bound by the app layer, in memory when
    # nobody bound it.
    task_board: Any = None,
    # The run's background ledger (``exec_command(run_in_background=True)``). One is
    # created below when the caller does not supply it, because the notification
    # channel is a property of the loop, not of a caller (ADR 0034).
    background: Optional[BackgroundTasks] = None,
) -> str:
    # The ledger exists even when nobody passed one: without it ``exec_command`` still
    # starts background commands (they are sessions, ADR 0008), the model just never
    # hears that they ended.
    background = background if background is not None else BackgroundTasks(task_id or "")
    _, registry, provider, request_tools = _build_runtime(
        provider_name=provider_name,
        provider_config=provider_config,
        enable_tools=enable_tools,
        mode=mode,
        base_dir=base_dir,
        agent_config=agent_config,
        task_id=task_id or "",
        should_stop=should_stop,
        todo_board=todo_board,
        task_board=task_board,
        background=background,
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

    # The nested-loop channel (``subagent``). Wired here because it needs both of the
    # things a tool is deliberately denied - the provider and the event sink - and a
    # mode without the tool (``ask``, ``plan``) is not given a runner it cannot reach.
    if SUBAGENT_TOOL_NAME in getattr(registry, "tools", {}):
        registry.subagent_runner = make_subagent_runner(
            registry=registry,
            provider=provider,
            event_sink=event_sink,
            task_id=task_id,
            should_stop=should_stop,
            stream=stream,
        )

    if verbose:
        print(f"Provider: {provider.config.provider}")
        print(f"Provider model: {provider.config.model}")
        print(f"Provider tool schemas: {(request_tools or [])[:1]}")

    instructions: Optional[AgentsMdInstructions] = None
    if initial_messages is not None:
        # A rebuilt transcript or a caller-owned conversation is used verbatim: its
        # system prompt was composed by whoever built it, and re-adding the workspace
        # instructions here would append them twice on every turn of the CLI REPL.
        messages = initial_messages
    else:
        if agent_config is not None:
            system_prompt = build_system_prompt_from_config(agent_config, enable_tools=enable_tools)
        elif enable_tools:
            system_prompt = build_system_prompt(mode, enable_tools=True)
        else:
            system_prompt = "You are a helpful assistant. Answer the user request directly and clearly."
        system_prompt = _with_base_dir(system_prompt, base_dir)
        # Which servers this run asked for, and whether they answered: without it a
        # server that failed to start looks exactly like one that was never configured.
        system_prompt = append_server_status(
            system_prompt, getattr(registry, "mcp_status", [])
        )
        # The workspace's own rules (https://agents.md/), after the generic ones: a
        # project's build/test commands outrank an agent's defaults.
        instructions = load_instructions(base_dir, agents_md_settings)
        if instructions is not None:
            system_prompt = append_project_instructions(system_prompt, instructions)
        # Where the work stands, when an earlier task in this conversation left a
        # plan: without it a follow-up task starts by replacing a half-done list.
        # Read defensively like ``base_dir``: a caller may hand in a registry of its
        # own (the loop's tests do), and a plan is not worth failing a run over.
        board = getattr(registry, "todo_board", None)
        if board is not None:
            system_prompt = append_todo_context(system_prompt, board.snapshot())
        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
        ]

    if history_messages:
        # Earlier turns of the session sit before this task's query, so a follow-up
        # continues the conversation instead of restarting it. The API builds this
        # from the session's finished tasks (see ``agent.history``).
        messages = _with_history(messages, history_messages)

    if append_user_query:
        messages.append({"role": "user", "content": user_query})

    if instructions is not None:
        # The same information is inside the system prompt below, but a task log that
        # names the files is what lets a surprising instruction be traced to one.
        _emit(
            event_sink,
            task_id,
            TaskEvent(
                task_id=task_id or "",
                category=EventCategory.DEBUG,
                title="Loaded AGENTS.md",
                data=instructions.describe(),
                collapsed=True,
            ),
        )

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
                "stream": stream,
                "max_output_tokens": max_output_tokens,
                "base_dir": base_dir,
                "agent_id": (agent_config or {}).get("agent_id"),
                "mcp_servers": (agent_config or {}).get("mcp_servers"),
                # Per server: connected, how many tools it contributed, or why it did
                # not. Without this a missing MCP tool is only visible as its absence.
                "mcp_status": getattr(registry, "mcp_status", []),
                "history_messages": len(history_messages or []),
                "first_step": first_step,
                # The conversation this run started from. Everything that happens next
                # is already in the response and tool events, so this one snapshot is
                # what lets a restarted process rebuild the transcript and continue
                # instead of replaying the task (see ``task_recovery``).
                "initial_messages": redact_image_payload(messages),
                **current_trace_ids(),
            },
            collapsed=True,
        ),
    )

    final_output: Optional[str] = None
    stopped = False
    # Tool results this run has already sent to the model, by ``tool_call_id``. Scoped
    # to the run: a compaction must never shorten a result the model has not read, and
    # "read" is only meaningful for requests this loop made (ADR 0016).
    seen_results: Set[str] = set()
    # Only when the plan tool exists: a mode without ``todo_write`` (ask, plan) must
    # not be nudged about a tool it cannot call.
    reminder = (
        TodoReminder() if TODO_WRITE_TOOL_NAME in getattr(registry, "tools", {}) else None
    )

    for step in range(first_step, max_steps + 1):
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
        # What the model started in the background and has ended since the last turn.
        # Before the request is built, so the report is part of the context it answers
        # from - and never as a tool result: that call was already answered with a
        # placeholder (ADR 0034).
        inject_background_results(messages, background, event_sink, task_id or "", step)
        # The conditional third step: only when the estimate is over the limit, and
        # before ``mark_seen`` below claims the results that just arrived unread.
        context = prepare_context(
            messages,
            seen_results,
            base_dir=getattr(registry, "base_dir", None),
            event_sink=event_sink,
            task_id=task_id,
            step=step,
            model_max_input_tokens=int(getattr(provider.config, "max_input_tokens", 0) or 0),
        )
        if context.get("still_over"):
            # The fourth and last resort: text surgery could not free enough, so spend
            # one model call on replacing the old history with a summary (ADR 0017).
            compacted = compact_history(
                messages,
                user_query,
                provider,
                base_dir=getattr(registry, "base_dir", None),
                event_sink=event_sink,
                task_id=task_id,
                step=step,
                context_limit=int(context.get("context_limit") or 0),
            )
            if verbose and compacted.get("reason") == "compacted":
                print(
                    f"[compacted] {compacted['compacted_messages']} messages summarized, "
                    f"{compacted['after_chars']} chars left"
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

        # Everything now in ``messages`` is about to go out, so from the next step on
        # it counts as read: that is what licenses shortening it (ADR 0016).
        mark_seen(seen_results, messages)

        with react_step_span(step, max_steps):
            turn = run_model_turn(
                provider,
                step,
                messages,
                request_tools,
                request_kwargs,
                event_sink,
                task_id,
                stream=stream,
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

                # After the budget sweep, so the nudge is not the part that got moved
                # to a file. It rides on the last tool result: that is what the model
                # reads next, and a user message would read as the user saying it.
                if reminder is not None:
                    notice = reminder.record(name for name, _, _ in turn.tool_calls)
                    if notice is not None and append_to_last_tool_message(
                        messages, batch_start, notice
                    ):
                        _emit(
                            event_sink,
                            task_id,
                            TaskEvent(
                                task_id=task_id or "",
                                category=EventCategory.DEBUG,
                                title="Todo reminder sent",
                                data={
                                    "step": step,
                                    "rounds_without_todo": reminder.every,
                                    **current_trace_ids(),
                                },
                                collapsed=True,
                            ),
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

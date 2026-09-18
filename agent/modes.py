"""Per-mode agent configuration: system prompt, tool set and skills.

Each task mode (build / ask / plan) provides its own:
- ``system_prompt``: the base system instruction for the agent
- ``tool_names``: which registered tools the agent may use (``None`` = all)
- ``skills``: list of enabled skill names (see ``SKILLS``)
"""

from typing import Any, Dict, List

from agent.tool_registry import ToolRegistry

# Skill registry. A skill contributes an instruction block to the system prompt.
# Add new skills here and reference them from a mode's ``skills`` list.
SKILLS: Dict[str, Dict[str, str]] = {
    "step_by_step": {
        "label": "Step-by-step reasoning",
        "instruction": "Break complex requests into explicit numbered steps before acting.",
    },
    "self_reflect": {
        "label": "Self-reflection",
        "instruction": "After each tool result, briefly reflect on whether it moves you toward the goal.",
    },
    "cite_sources": {
        "label": "Cite sources",
        "instruction": "When you use information from a tool, cite which tool produced it.",
    },
}

AVAILABLE_SKILLS = sorted(SKILLS.keys())

MODE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "build": {
        "label": "Build",
        "description": "Implement solutions end-to-end using all available tools.",
        "system_prompt": (
            "You are a Build agent operating in a ReAct loop. Your job is to implement the "
            "user's request end-to-end: reason about the goal, use the available tools to "
            "gather information and perform actions, observe the results, and continue until "
            "the task is complete. When done, summarize what you built and the outcome."
        ),
        "tool_names": None,
        "skills": ["step_by_step", "self_reflect"],
    },
    "ask": {
        "label": "Ask",
        "description": "Answer questions clearly using read-only tools when helpful.",
        "system_prompt": (
            "You are an Ask agent. Answer the user's question clearly and accurately. You may "
            "use read-only tools (such as the clock or a calculator) to verify facts, but do "
            "not perform side-effecting actions. If the question is ambiguous, state your "
            "assumptions before answering."
        ),
        "tool_names": ["get_current_time", "code_interpreter", "read_file"],
        "skills": ["cite_sources"],
    },
    "plan": {
        "label": "Plan",
        "description": "Produce a concrete plan without performing actions.",
        "system_prompt": (
            "You are a Plan agent. Do NOT execute the task. Instead, produce a concrete, "
            "ordered plan that another agent could follow: goals, milestones, required tools "
            "or information, risks, and acceptance criteria. Reason carefully and avoid "
            "calling tools that change state."
        ),
        "tool_names": [],
        "skills": ["step_by_step"],
    },
}

VALID_MODES = sorted(MODE_CONFIGS.keys())
DEFAULT_MODE = "build"


def get_mode_config(mode: str) -> Dict[str, Any]:
    """Return the configuration for ``mode``, falling back to the default mode."""
    if mode not in MODE_CONFIGS:
        return MODE_CONFIGS[DEFAULT_MODE]
    return MODE_CONFIGS[mode]


DIRECT_ANSWER_PROMPT = "You are a helpful assistant. Answer the user request directly and clearly."


def _compose_prompt(prompt: str, skill_names: Any, enable_tools: bool) -> str:
    if not enable_tools:
        return DIRECT_ANSWER_PROMPT
    skills = [SKILLS[name] for name in (skill_names or []) if name in SKILLS]
    if skills:
        lines = ["", "## Active skills"]
        for skill in skills:
            lines.append(f"- {skill['label']}: {skill['instruction']}")
        prompt += "\n".join(lines)
    return prompt


def build_system_prompt_from_config(config: Dict[str, Any], enable_tools: bool = True) -> str:
    """Build the system prompt from an explicit agent config (prompt + skills)."""
    return _compose_prompt(
        str(config.get("system_prompt") or ""),
        config.get("skills"),
        enable_tools,
    )


def build_system_prompt(mode: str, enable_tools: bool = True) -> str:
    """Build the full system prompt for a mode, including active skill instructions."""
    config = get_mode_config(mode)
    return build_system_prompt_from_config(
        {"system_prompt": config["system_prompt"], "skills": config.get("skills", [])},
        enable_tools=enable_tools,
    )


def build_tool_registry_from_names(
    tool_names: Any,
    base_dir: str | None = None,
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
) -> ToolRegistry:
    """Build a ToolRegistry from an explicit tool-name allow list (``None`` = all tools)."""
    options = {
        "base_dir": base_dir,
        "max_tokens": max_tokens,
        "provider": provider,
        "model": model,
    }
    if tool_names is None:
        return ToolRegistry(**options)
    return ToolRegistry(enabled_tools=list(tool_names), **options)


def build_tool_registry(
    mode: str,
    base_dir: str | None = None,
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
) -> ToolRegistry:
    """Build a ToolRegistry restricted to the tools allowed for ``mode``."""
    return build_tool_registry_from_names(
        get_mode_config(mode).get("tool_names"),
        base_dir=base_dir,
        max_tokens=max_tokens,
        provider=provider,
        model=model,
    )


def list_available_tools() -> List[Dict[str, Any]]:
    """List every registered tool with its description and parameter schema."""
    registry = ToolRegistry()
    return [
        {
            "name": name,
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters") or {},
        }
        for name, tool in registry.tools.items()
    ]


def list_available_skills() -> List[Dict[str, str]]:
    """List every registered skill with its label and instruction block."""
    return [
        {
            "name": name,
            "label": config.get("label", name),
            "instruction": config.get("instruction", ""),
        }
        for name, config in SKILLS.items()
    ]

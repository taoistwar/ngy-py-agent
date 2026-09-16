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

DEFAULT_TOOL_NAMES = [
    "get_current_temperature",
    "get_current_time",
    "convert_currency",
    "code_interpreter",
]

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
        "tool_names": ["get_current_time", "code_interpreter"],
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


def build_system_prompt(mode: str, enable_tools: bool = True) -> str:
    """Build the full system prompt for a mode, including active skill instructions."""
    config = get_mode_config(mode)
    prompt = config["system_prompt"]
    if not enable_tools:
        return (
            "You are a helpful assistant. Answer the user request directly and clearly."
        )
    skills = [SKILLS[name] for name in config.get("skills", []) if name in SKILLS]
    if skills:
        lines = ["", "## Active skills"]
        for skill in skills:
            lines.append(f"- {skill['label']}: {skill['instruction']}")
        prompt += "\n".join(lines)
    return prompt


def build_tool_registry(mode: str) -> ToolRegistry:
    """Build a ToolRegistry restricted to the tools allowed for ``mode``."""
    config = get_mode_config(mode)
    tool_names = config.get("tool_names")
    if tool_names is None:
        return ToolRegistry()
    return ToolRegistry(enabled_tools=list(tool_names))

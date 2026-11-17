"""Tell the model which MCP servers this run has, and what each one contributes.

A server that failed to start is indistinguishable from one that was never configured
when the only signal is a missing tool: the model sees no ``mcp__`` tools either way and
answers "I have no MCP", which hides the real problem. The section says which servers
were asked for, whether they answered, and what their tools are called.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def append_server_status(prompt: str, statuses: Sequence[Mapping[str, Any]]) -> str:
    """Append the run's MCP server list, or return ``prompt`` untouched when there is none."""
    lines: list[str] = []
    for status in statuses or ():
        name = str(status.get("name") or "mcp")
        if status.get("ok"):
            count = int(status.get("tool_count") or 0)
            suffix = "tool" if count == 1 else "tools"
            lines.append(f"- {name}: connected, {count} {suffix} available.")
        else:
            reason = str(status.get("error") or "unknown error").strip().replace("\n", " ")
            lines.append(f"- {name}: not connected, its tools are unavailable ({reason})")
    if not lines:
        return prompt

    header = [
        "",
        "## MCP servers",
        "Remote tools from the servers below are available as "
        "`mcp__<server>__<tool>`; each call needs the user's confirmation.",
    ]
    return f"{prompt}\n" + "\n".join(header + lines)

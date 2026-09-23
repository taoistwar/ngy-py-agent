"""What the model is told about ``write_stdin``: its name, description and schema."""

from typing import Any, Dict

from agent.tools.write_stdin.rules import POLL_MAX_YIELD_MS

WRITE_STDIN_TOOL_NAME = "write_stdin"

WRITE_STDIN_DESCRIPTION = (
    "Type into a command that exec_command left running, and read what it prints back. "
    "Pass the 'session_id' that exec_command returned for a command still running. Set 'chars' to "
    "write text to the command's stdin (include '\\n' to send a line); leave 'chars' empty to only "
    "poll for new output. A 'chars' equal to Ctrl-C ('\\u0003') interrupts the command instead of "
    "writing it. 'yield_time_ms' bounds how long to wait for output and 'max_output_tokens' bounds "
    "how much is returned. The result says whether the command is still running (it prints a "
    "session_id) or has finished (it prints an exit_code); a finished session cannot be reused."
)

WRITE_STDIN_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": (
                "The session id exec_command returned for a command still running. "
                "A finished session is rejected."
            ),
        },
        "chars": {
            "type": "string",
            "description": (
                "Text to write to the command's stdin. Empty (the default) only polls for new "
                "output. A single Ctrl-C character ('\\u0003') interrupts the command."
            ),
        },
        "yield_time_ms": {
            "type": "integer",
            "minimum": 0,
            "maximum": POLL_MAX_YIELD_MS,
            "description": (
                "How long to wait for output, in MILLISECONDS. A poll (empty 'chars') is raised to "
                "at least 5000 and capped at 300000; a write waits at most 30000. Defaults to 250."
            ),
        },
        "max_output_tokens": {
            "type": "integer",
            "minimum": 1,
            "description": (
                "Token budget for the returned output. Defaults to 10000; a larger request may be "
                "capped by policy. Output above the budget is persisted and its path is returned."
            ),
        },
    },
    "required": ["session_id"],
}

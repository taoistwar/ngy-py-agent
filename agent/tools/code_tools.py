"""Code execution tools."""

import contextlib
import io
import json
import math
import random
import re
import sys
from datetime import datetime
from typing import Dict


def code_interpreter(code: str) -> Dict:
    """
    Execute Python code in a full Python environment.
    This provides unrestricted access to Python's built-in functions and standard library.
    """
    try:
        # Strip markdown code blocks and other formatting
        # Remove ```python or ```py or ``` blocks
        code = re.sub(r"^```(?:python|py)?\s*\n", "", code.strip())
        code = re.sub(r"\n```\s*$", "", code)
        code = re.sub(r"^```\s*", "", code)
        code = re.sub(r"\s*```$", "", code)

        # Also strip any leading/trailing whitespace
        code = code.strip()

        # NOTE: we deliberately do NOT rewrite '^' to '**' here. '^' is a
        # valid Python operator (bitwise XOR), so a blanket substitution
        # silently changes the meaning of correct code -- 5 ^ 3 is 6, but
        # rewritten as 5 ** 3 it returns 125 with no error. It also broke
        # anchored regexes (r'^a.*' -> r'**a.*' raises "nothing to repeat")
        # and corrupted carets inside string literals. The two meanings of
        # '^' cannot be told apart from the source, so the convention is
        # stated in the tool description instead.

        # Create a full Python namespace with all builtins available
        # This gives the agent access to the complete Python environment
        namespace = {
            "__builtins__": __builtins__,
            "math": math,
            "random": random,
            "datetime": datetime,
            "sys": sys,
            "re": re,
            "json": json,
        }

        # Capture both stdout and stderr
        output_buffer = io.StringIO()
        error_buffer = io.StringIO()

        with (
            contextlib.redirect_stdout(output_buffer),
            contextlib.redirect_stderr(error_buffer),
        ):
            exec(code, namespace)

        # Get output and any error messages
        printed_output = output_buffer.getvalue()
        error_output = error_buffer.getvalue()

        # Try to get result from common variable names
        result = namespace.get("result", None)
        if result is None:
            for var_name in [
                "A",
                "total",
                "sum",
                "output",
                "answer",
                "final",
                "value",
            ]:
                if var_name in namespace:
                    result = namespace[var_name]
                    break

        response = {
            "result": result,
            "output": printed_output if printed_output else None,
            "stderr": error_output if error_output else None,
            "success": True,
        }

        return response

    except SyntaxError as e:
        error_msg = f"Syntax Error on line {e.lineno}: {e.msg}\n{e.text}"
        return {"error": error_msg, "error_type": "SyntaxError", "success": False}
    except Exception as e:
        import traceback

        error_trace = traceback.format_exc()
        return {
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": error_trace,
            "success": False,
        }

"""The ``memory_save`` call: validate one note, store it, say what happened.

Nothing is written until every check has passed, and a refusal is an answer rather than
an error: "this was scoped to the current task" is the correct outcome of a candidate
that should not become a standing rule, and the model has to read why.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from agent.models import ToolOutcome
from agent.tools.memory_notes import parse_record, should_store
from agent.tools.memory_store import MemoryBook, MemoryDisabled, MemoryFull


class MemorySaveError(ValueError):
    """A note that cannot be stored as sent in; the message is the whole answer."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def memory_save_impl(record: Dict[str, Any], book: MemoryBook) -> Tuple[str, Dict[str, Any]]:
    """Validate and store one note; returns ``(model_text, details)``."""
    normalized, error = parse_record(record, require_scope=True)
    if error is not None:
        raise MemorySaveError(error)

    existing = book.snapshot()
    keep, why = should_store(normalized, existing)
    if not keep:
        return f"Nothing saved: {why}", {
            "success": True,
            "saved": False,
            "reason": "duplicate",
            "name": normalized["name"],
        }

    # Read before the write: afterwards the store cannot say whether this name was new.
    replaced = any(item.get("name") == normalized["name"] for item in existing)
    stored = book.save(normalized)
    verb = "Replaced" if replaced else "Saved"
    model_text = (
        f"{verb} memory {stored['name']!r} ({stored['type']}): {stored['description']}\n"
        "It is now in the index every later session sees in this workspace."
    )
    return model_text, {
        "success": True,
        "saved": True,
        "replaced": replaced,
        "memory": stored,
    }


def make_memory_save_tool(book: Optional[MemoryBook] = None):
    """Bind the tool to one run's memory library (``None`` keeps it in memory)."""
    book = book if book is not None else MemoryBook()

    # ``type`` is the schema property the model sends, so it has to be the parameter
    # name; the implementation takes it as ``memory_type`` to keep the builtin name.
    def memory_save(
        name: str = "",
        type: str = "",
        description: str = "",
        body: str = "",
        scope: str = "",
    ) -> ToolOutcome:
        try:
            model_text, details = memory_save_impl(
                {
                    "name": name,
                    "type": type,
                    "description": description,
                    "body": body,
                    "scope": scope,
                },
                book,
            )
        except MemorySaveError as exc:
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                details={"success": False, "reason": "invalid_argument", "error": exc.message},
            )
        except MemoryDisabled as exc:
            return ToolOutcome(
                model_text=(
                    f"Error: {exc} The note was not saved; do not try again in this run. "
                    "Write it down in your answer instead if it matters to the user."
                ),
                details={"success": False, "reason": "disabled", "error": str(exc)},
            )
        except MemoryFull as exc:
            return ToolOutcome(
                model_text=f"Error: memory is full: {exc}",
                details={"success": False, "reason": "full", "error": str(exc)},
            )
        except Exception as exc:  # noqa: BLE001 - a store failure must reach the model
            return ToolOutcome(
                model_text=f"Error: the memory could not be saved: {exc}",
                details={"success": False, "reason": "store_error", "error": str(exc)},
            )
        return ToolOutcome(model_text=model_text, details=details)

    return memory_save

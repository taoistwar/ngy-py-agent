"""The ``write_file`` factory: binds the write to a workspace root and a ledger."""

from __future__ import annotations

from typing import Any, Optional, Sequence

from agent.models import EventCategory, ToolOutcome
from agent.tools.file_access import AccessDenied, FileAccessConfig, load_access_config
from agent.tools.read_ledger import DEFAULT_LEDGER, ReadLedger
from agent.tools.text_encoding import DecodeError, EncodeError
from agent.tools.write_file.errors import WriteFileError
from agent.tools.write_file.write import write_file_impl


def make_write_file_tool(
    base_dir: Optional[str],
    access_config: Optional[FileAccessConfig] = None,
    ledger: Optional[ReadLedger] = None,
    extra_read_roots: Sequence[Any] = (),
):
    """Bind the write tool to a workspace root and a read ledger."""
    config = access_config if access_config is not None else load_access_config()
    read_ledger = ledger if ledger is not None else DEFAULT_LEDGER

    def write_file(file_path: str, content: str, encoding: Any = None) -> ToolOutcome:
        try:
            details = write_file_impl(
                file_path, content, encoding, base_dir, config, read_ledger, extra_read_roots
            )
        except (WriteFileError, DecodeError, EncodeError) as exc:
            payload = exc.to_dict()
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                event_category=EventCategory.FILE_WRITE,
                event_title=f"File write failed: {payload.get('file_path') or file_path}",
                details={"success": False, **payload},
            )
        except AccessDenied as exc:
            payload = exc.to_dict()
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                event_category=EventCategory.FILE_WRITE,
                event_title=f"File write denied: {file_path}",
                details={"success": False, **payload},
            )

        verb = "created" if details["created"] else "replaced"
        return ToolOutcome(
            model_text=f"The file {details['file_path']} has been {verb} successfully.",
            event_category=EventCategory.FILE_WRITE,
            event_title=f"File write: {details['file_path']}",
            details={"success": True, **details},
        )

    return write_file

"""The ``delete_file`` factory: binds the delete to a workspace root and a ledger."""

from __future__ import annotations

from typing import Any, Optional, Sequence

from agent.models import EventCategory, ToolOutcome
from agent.tools.delete_file.delete import delete_file_impl
from agent.tools.delete_file.errors import DeleteFileError
from agent.tools.file_access import AccessDenied, FileAccessConfig, load_access_config
from agent.tools.read_ledger import DEFAULT_LEDGER, ReadLedger


def make_delete_file_tool(
    base_dir: Optional[str],
    access_config: Optional[FileAccessConfig] = None,
    ledger: Optional[ReadLedger] = None,
    extra_read_roots: Sequence[Any] = (),
):
    """Bind the delete tool to a workspace root and a read ledger."""
    config = access_config if access_config is not None else load_access_config()
    read_ledger = ledger if ledger is not None else DEFAULT_LEDGER

    def delete_file(file_path: str) -> ToolOutcome:
        try:
            details = delete_file_impl(file_path, base_dir, config, read_ledger, extra_read_roots)
        except DeleteFileError as exc:
            payload = exc.to_dict()
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                event_category=EventCategory.FILE_DELETE,
                event_title=f"File delete failed: {payload.get('file_path') or file_path}",
                details={"success": False, **payload},
            )
        except AccessDenied as exc:
            payload = exc.to_dict()
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                event_category=EventCategory.FILE_DELETE,
                event_title=f"File delete denied: {file_path}",
                details={"success": False, **payload},
            )

        return ToolOutcome(
            model_text=f"The file {details['file_path']} has been deleted successfully.",
            event_category=EventCategory.FILE_DELETE,
            event_title=f"File delete: {details['file_path']}",
            details={"success": True, **details},
        )

    return delete_file

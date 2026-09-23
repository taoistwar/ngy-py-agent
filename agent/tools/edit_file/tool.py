"""The ``edit_file`` factory: binds the pipeline to a workspace root.

Kept separate from :mod:`~agent.tools.edit_file.edit` so that "what the tool is"
and "how it runs one call" stay readable on their own.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from agent.models import EventCategory, ToolOutcome
from agent.tools.edit_file.edit import edit_file_impl
from agent.tools.edit_file.errors import EditFileError
from agent.tools.file_access import AccessDenied, FileAccessConfig, load_access_config
from agent.tools.read_ledger import DEFAULT_LEDGER, ReadLedger
from agent.tools.text_encoding import DecodeError, EncodeError


def make_edit_file_tool(
    base_dir: Optional[str],
    access_config: Optional[FileAccessConfig] = None,
    ledger: Optional[ReadLedger] = None,
    extra_read_roots: Sequence[Any] = (),
):
    """Bind the edit tool to a workspace root."""
    config = access_config if access_config is not None else load_access_config()
    read_ledger = ledger if ledger is not None else DEFAULT_LEDGER

    def edit_file(
        file_path: str,
        old_string: str,
        new_string: str = "",
        replace_all: bool = False,
        encoding: Any = None,
    ) -> ToolOutcome:
        try:
            details = edit_file_impl(
                file_path,
                old_string,
                new_string,
                replace_all,
                encoding,
                base_dir,
                config,
                read_ledger,
                extra_read_roots,
            )
        except (EditFileError, DecodeError, EncodeError) as exc:
            payload = exc.to_dict()
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                event_category=EventCategory.FILE_EDIT,
                event_title=f"File edit failed: {payload.get('file_path') or file_path}",
                details={"success": False, **payload},
            )
        except AccessDenied as exc:
            payload = exc.to_dict()
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                event_category=EventCategory.FILE_EDIT,
                event_title=f"File edit denied: {file_path}",
                details={"success": False, **payload},
            )

        return ToolOutcome(
            model_text=f"The file {details['file_path']} has been updated successfully.",
            event_category=EventCategory.FILE_EDIT,
            event_title=f"File edit: {details['file_path']}",
            details={"success": True, **details},
        )

    return edit_file

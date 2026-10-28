"""Snapshot history for a workspace, so a finished task can be undone (ADR 0020).

- :mod:`agent.checkpoints.git` - the guarded git calls, including why they cannot
  reach the user's own repository.
- :mod:`agent.checkpoints.store` - one repository per workspace, one branch per task,
  and the revert rules that follow from that.

Nothing here is part of the tool surface: the store is a recorder the registry feeds,
not a tool the model can call.
"""

from agent.checkpoints.store import (
    STATUS_ADDED,
    STATUS_DELETED,
    STATUS_MODIFIED,
    Change,
    CheckpointStore,
    RevertResult,
)

__all__ = [
    "STATUS_ADDED",
    "STATUS_DELETED",
    "STATUS_MODIFIED",
    "Change",
    "CheckpointStore",
    "RevertResult",
]

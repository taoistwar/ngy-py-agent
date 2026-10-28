"""Snapshot history for a workspace, so a finished task can be undone (ADR 0020).

- :mod:`agent.checkpoints.git` - the guarded git calls, including why they cannot
  reach the user's own repository.
- :mod:`agent.checkpoints.layout` - where the repository lives and what its refs are
  called.
- :mod:`agent.checkpoints.records` - the shapes the store reports back, and the git
  output it parses into them.
- :mod:`agent.checkpoints.store` - one repository per workspace, one branch per task,
  and the revert rules that follow from that.

Nothing here is part of the tool surface: the store is a recorder the registry feeds,
not a tool the model can call.
"""

from agent.checkpoints.records import (
    STATUS_ADDED,
    STATUS_DELETED,
    STATUS_MODIFIED,
    Change,
    RevertResult,
)
from agent.checkpoints.store import CheckpointStore

__all__ = [
    "STATUS_ADDED",
    "STATUS_DELETED",
    "STATUS_MODIFIED",
    "Change",
    "CheckpointStore",
    "RevertResult",
]

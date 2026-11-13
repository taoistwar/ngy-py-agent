"""Recording what a task changed, and putting it back (ADR 0020).

The workspace is snapshotted into a private git repository that lives *outside* it
(``agent/checkpoints/git.py`` explains the plumbing). One repository per workspace,
one branch per task: the branch is what makes attribution possible, because
``git diff <task-base> <task-head>`` then names exactly the files that task touched and
nothing a neighbouring task did.

Baselines are committed when a task first mutates something: the baseline is the disk
as it was at that moment, not the last commit. Between two tasks the user may have
edited files by hand, or undone an earlier task; those files exist on disk without
being in ``HEAD``, and a baseline that ignored them would report them as created by the
next task - and a revert would then delete them.

Two properties are deliberate:

- **Never a gate.** :meth:`CheckpointStore.begin` and :meth:`CheckpointStore.end`
  swallow their own failures. A checkpoint that cannot be written must not stop the
  tool call it was recording.
- **Never silent about being unavailable.** The reason goes into
  :attr:`CheckpointStore.unavailable_reason`, so the API can tell the user that undo
  is off instead of offering a button that cannot work.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from agent.checkpoints import git
from agent.checkpoints.layout import (
    BASE_SUFFIX as _BASE_SUFFIX,
)
from agent.checkpoints.layout import (
    BRANCH_PREFIX as _BRANCH_PREFIX,
)
from agent.checkpoints.layout import (
    enabled as _enabled,
)
from agent.checkpoints.layout import (
    normalized as _normalized,
)
from agent.checkpoints.layout import (
    ref_component as _ref_component,
)
from agent.checkpoints.layout import (
    store_root as _store_root,
)
from agent.checkpoints.layout import (
    workspace_key as _workspace_key,
)
from agent.checkpoints.layout import (
    workspace_path as _workspace_path,
)
from agent.checkpoints.records import (
    Change,
    RevertResult,
)
from agent.checkpoints.records import (
    parse_name_status as _parse_name_status,
)
from agent.checkpoints.records import (
    parse_numstat as _parse_numstat,
)
from agent.checkpoints.records import (
    status_of as _status_of,
)

# Tools whose single argument names the file they write, so the snapshot can be an
# O(1) ``git add`` of that path instead of a full tree scan.
FILE_TOOLS: Mapping[str, str] = {"write_file": "file_path", "edit_file": "file_path"}

# Tools that can change anything at all: the snapshot has to look at the whole tree.
# ``write_stdin`` is here because typing into a shell session can do whatever that
# session's command does next, not because it writes files itself.
TREE_TOOLS = frozenset({"exec_command", "write_stdin", "code_interpreter"})

# Sentinels for "this tool touches no files" and "this tool can touch any file".
_NOTHING = object()
_WHOLE_TREE = object()

_LOCKS: Dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(key: str) -> threading.RLock:
    """One lock per repository, shared by every store pointing at it.

    Several tasks run at once and each re-points the shared repository's ``HEAD``, so
    the git operations of two tasks must never interleave.
    """
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


class CheckpointStore:
    """One workspace's checkpoint history, shared by every task that runs in it."""

    def __init__(self, workspace: Path, root: Optional[Path] = None):
        self.workspace = _normalized(workspace)
        self.root = _normalized(root) if root is not None else _normalized(_store_root())
        # ``repo_dir`` holds everything about one workspace: the bare repository,
        # the per-task markers and a file naming the workspace, for whoever has to
        # look at this store by hand.
        self.repo_dir = self.root / _workspace_key(self.workspace)
        self.git_dir = self.repo_dir / "repo"
        self._lock = _lock_for(str(self.repo_dir))
        # Which task's branch the shared index currently matches. Guarded by the lock;
        # this is what keeps a per-file snapshot down to one `git add`.
        self._index_task: Optional[str] = None
        self._ready: Optional[bool] = None
        self._error = ""

    # ---------------------------------------------------------------- lifecycle

    @classmethod
    def for_run(cls, base_dir: Optional[str], task_id: str) -> Optional["CheckpointStore"]:
        """The store for one task, or ``None`` when there is nothing to record.

        ``None`` means "not applicable": no task id (a CLI run, a library caller) or
        checkpointing switched off. A machine without git still gets a store - it just
        reports why it cannot record, so the UI can say so.
        """
        if not _enabled():
            return None
        if not str(task_id or "").strip():
            return None
        workspace = _workspace_path(base_dir)
        if workspace is None:
            return None
        return cls(workspace)

    @property
    def unavailable_reason(self) -> str:
        return self._error

    def enable(self) -> bool:
        """Create the private repository if needed; ``False`` when unavailable."""
        if self._ready is not None:
            return self._ready
        try:
            if not git.available():
                raise git.GitError("git was not found on this machine")
            git.init(self.git_dir)
            self._write_workspace_marker()
            self._ready = True
        except (git.GitError, OSError) as exc:
            self._error = str(exc)
            self._ready = False
        return self._ready

    # ---------------------------------------------------------------- recording

    def begin(self, task_id: str, tool: str, arguments: Mapping[str, Any]) -> None:
        """Called **before** ``tool`` runs: make sure this task has a baseline.

        This is the only moment the pre-change state can be captured, which is why the
        baseline is committed here. It costs one ``git status`` per mutating call and a
        full tree ``git add`` once per task - but only when the disk and the last commit
        actually differ, so a workspace nobody has touched since the previous task pays
        almost nothing.
        """
        pathspec = self._pathspec(tool, arguments)
        if pathspec is _NOTHING or not self.enable():
            return
        if self._base_ref(task_id) is not None:
            return
        try:
            with self._lock:
                if self._base_ref(task_id) is None:
                    self._record_base(task_id)
        except (git.GitError, OSError) as exc:
            self._error = str(exc)

    def end(self, task_id: str, tool: str, arguments: Mapping[str, Any]) -> None:
        """Called **after** ``tool`` ran: commit what it changed.

        Recording afterwards is what makes the task's head mean "what this task left
        behind", which is exactly what a revert has to compare the disk against.
        """
        pathspec = self._pathspec(tool, arguments)
        if pathspec is _NOTHING or not self.enable():
            return
        try:
            with self._lock:
                base = self._base_ref(task_id)
                if base is None:
                    # ``begin`` failed or never ran; anchor as late as possible rather
                    # than refusing to record anything at all.
                    base = self._record_base(task_id)
                self._prepare_index(task_id, base, pathspec is _WHOLE_TREE)
                self._stage(pathspec)
                committed = self._commit(tool)
                self._index_task = task_id if committed else None
        except (git.GitError, OSError) as exc:
            # A checkpoint is an aid, never a gate: the tool call it was recording has
            # already happened either way.
            self._error = str(exc)
            self._index_task = None

    # ------------------------------------------------------------------ reading

    def changes(self, task_id: str) -> List[Change]:
        """The files this task changed, minus the ones already reverted."""
        if not self.enable():
            return []
        base = self._base_ref(task_id)
        tip = self._tip_ref(task_id)
        if base is None or tip is None:
            return []
        try:
            with self._lock:
                entries = _parse_name_status(self._diff_bytes("--name-status", base, tip))
                counts = _parse_numstat(self._diff_bytes("--numstat", base, tip))
        except (git.GitError, OSError) as exc:
            self._error = str(exc)
            return []
        reverted = self._reverted_paths(task_id)
        changes: List[Change] = []
        for status_code, path in entries:
            if path in reverted:
                continue
            added, removed = counts.get(path, (0, 0))
            changes.append(
                Change(
                    path=path,
                    status=_status_of(status_code),
                    additions=added,
                    deletions=removed,
                    conflict=self._conflicts(tip, path),
                )
            )
        return changes

    def _conflicts(self, tip: str, path: str) -> bool:
        """Whether the disk holds something other than what the task left behind.

        Same comparison :meth:`revert` makes before touching a file, exposed ahead of
        the click: a file the user or another agent edited after this task wrote it
        cannot be undone, and the UI should say so rather than offer a button that
        will refuse (ADR 0020 D5, D7).
        """
        return _read_bytes(self.workspace / path) != self._blob(tip, path)

    def diff(self, task_id: str, path: str) -> str:
        """The unified diff of one file, for the confirmation dialog."""
        base = self._base_ref(task_id)
        tip = self._tip_ref(task_id)
        if base is None or tip is None:
            return ""
        try:
            completed = git.run(
                self.git_dir,
                self.workspace,
                ["diff", "--no-color", "--no-renames", base, tip, "--", path],
                check=False,
            )
        except (git.GitError, OSError) as exc:
            self._error = str(exc)
            return ""
        return completed.stdout.decode("utf-8", "replace")

    # ----------------------------------------------------------------- reverting

    def revert(
        self,
        task_id: str,
        paths: Optional[Sequence[str]] = None,
        force: bool = False,
    ) -> RevertResult:
        """Put ``paths`` (or every changed file) back to the task's baseline.

        A file whose current content is not what the task left behind has been edited
        since, by the user or another task. It is reported as a conflict and left
        alone unless ``force`` is set: overwriting somebody's work to make an undo
        look complete is worse than a partial undo that says what it skipped.
        """
        result = RevertResult()
        wanted = None if paths is None else {str(item) for item in paths}
        base = self._base_ref(task_id)
        tip = self._tip_ref(task_id)
        if base is None or tip is None:
            return result

        targets = [item for item in self.changes(task_id) if wanted is None or item.path in wanted]
        try:
            with self._lock:
                for change in targets:
                    self._revert_one(change, base, tip, force, result)
                self._index_task = None
        except (git.GitError, OSError) as exc:
            self._error = str(exc)
            return result
        if result.restored:
            self._mark_reverted(task_id, result.restored)
        return result

    def _revert_one(
        self,
        change: Change,
        base: str,
        tip: str,
        force: bool,
        result: RevertResult,
    ) -> None:
        target = self.workspace / change.path
        # What the task left behind, which is what the disk must still match for the
        # revert to be safe.
        expected = self._blob(tip, change.path)
        current = _read_bytes(target)
        if not force and current != expected:
            result.conflicts.append(change.path)
            return
        if self._blob(base, change.path) is None:
            # The file did not exist before this task: undoing an addition is
            # removing it. Decided from the baseline, not from the status code, so a
            # file the task deleted and re-created is handled the same way.
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            result.restored.append(change.path)
            return
        restored = git.run(
            self.git_dir,
            self.workspace,
            ["checkout", base, "--", change.path],
            check=False,
        )
        if restored.returncode != 0:
            result.skipped.append(change.path)
            return
        result.restored.append(change.path)

    def forget(self, task_id: str) -> None:
        """Drop this task's history. Called when the task itself is deleted."""
        if not self.enable():
            return
        try:
            with self._lock:
                for name in (self._branch(task_id), self._base_branch(task_id)):
                    git.run(
                        self.git_dir,
                        self.workspace,
                        ["update-ref", "-d", f"refs/heads/{name}"],
                        check=False,
                    )
                self._index_task = None
        except (git.GitError, OSError):
            return
        try:
            self._record_path(task_id).unlink()
        except OSError:
            pass

    # ------------------------------------------------------------------ internals

    def _pathspec(self, tool: str, arguments: Mapping[str, Any]) -> Any:
        if tool in TREE_TOOLS:
            return _WHOLE_TREE
        argument = FILE_TOOLS.get(tool)
        if argument is None:
            return _NOTHING
        path = self._relative(arguments.get(argument))
        if path is None:
            # A path outside the workspace is not this store's business.
            return _NOTHING
        return [path]

    def _relative(self, raw: Any) -> Optional[str]:
        if not isinstance(raw, str) or not raw.strip():
            return None
        candidate = Path(raw.strip())
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        try:
            return candidate.resolve().relative_to(self.workspace).as_posix()
        except (OSError, ValueError):
            return None

    def _stage(self, pathspec: Any) -> None:
        args = ["add", "-A", "--"]
        if pathspec is not _WHOLE_TREE:
            args.extend(pathspec)
        git.run(self.git_dir, self.workspace, args)

    def _commit(self, tool: str) -> bool:
        """Commit the staged state; ``False`` when the call changed nothing."""
        staged = git.run(
            self.git_dir, self.workspace, ["diff", "--cached", "--quiet"], check=False
        )
        if staged.returncode == 0:
            return False
        git.run(
            self.git_dir,
            self.workspace,
            ["commit", "--quiet", "--no-verify", "-m", f"checkpoint: {tool}"],
        )
        return True

    def _prepare_index(self, task_id: str, base: str, whole_tree: bool) -> None:
        """Point ``HEAD`` at this task's branch and get the index ready for the add.

        Re-pointing ``HEAD`` is what lets one repository serve several tasks: the
        branch a commit lands on is decided per call, under the lock.

        A whole-tree add syncs the index to the work tree by itself, so it needs no
        reset - and must clear the "which task owns the index" marker, because
        afterwards the index matches the work tree rather than any one branch. A
        single-path add stages only that path, so the rest of the index has to be
        this task's branch first or the commit would carry another task's files.
        """
        branch = self._branch(task_id)
        git.run(
            self.git_dir, self.workspace, ["symbolic-ref", "HEAD", f"refs/heads/{branch}"]
        )
        tip = self._tip_ref(task_id)
        if tip is None:
            # First snapshot for this task: start the branch at the baseline. Without
            # this the branch is unborn, ``HEAD`` resolves to nothing, and both
            # ``diff --cached`` and ``commit`` have no parent to work against.
            git.run(
                self.git_dir,
                self.workspace,
                ["update-ref", f"refs/heads/{branch}", base],
            )
            tip = base
            self._index_task = None
        if whole_tree:
            self._index_task = None
            return
        if self._index_task == task_id:
            return
        git.run(self.git_dir, self.workspace, ["reset", "--mixed", "--quiet", tip])
        self._index_task = task_id

    def _record_base(self, task_id: str) -> str:
        """Capture the workspace as it is now and make it this task's baseline.

        The baseline must be a commit of the *current disk*, not whatever ``HEAD``
        already points at. Files the user created or edited by hand between tasks, and
        files an earlier task's undo deleted, are on disk but not in ``HEAD``; taking
        ``HEAD`` as the baseline would make them look like this task created them, and
        reverting would then delete the user's files.
        """
        head = git.run(
            self.git_dir, self.workspace, ["rev-parse", "--verify", "--quiet", "HEAD"], check=False
        )
        dirty = git.run(
            self.git_dir,
            self.workspace,
            ["status", "--porcelain", "--untracked-files=all"],
            check=False,
        ).stdout
        if head.returncode != 0 or dirty.strip():
            git.run(self.git_dir, self.workspace, ["add", "-A"])
            git.run(
                self.git_dir,
                self.workspace,
                # ``--allow-empty``: an empty workspace is a legitimate baseline, and
                # the task about to run may be the one that fills it.
                ["commit", "--quiet", "--no-verify", "--allow-empty", "-m", "baseline"],
            )
            self._index_task = None
            head = git.run(self.git_dir, self.workspace, ["rev-parse", "HEAD"])
        base = head.stdout.decode("utf-8", "replace").strip()
        git.run(
            self.git_dir,
            self.workspace,
            ["update-ref", f"refs/heads/{self._base_branch(task_id)}", base],
        )
        return base

    def _diff_bytes(self, mode: str, base: str, tip: str) -> bytes:
        completed = git.run(
            self.git_dir,
            self.workspace,
            ["diff", "--no-renames", mode, "-z", base, tip],
            check=False,
        )
        return completed.stdout if completed.returncode == 0 else b""

    def _blob(self, ref: str, path: str) -> Optional[bytes]:
        completed = git.run(
            self.git_dir, self.workspace, ["show", f"{ref}:{path}"], check=False
        )
        return completed.stdout if completed.returncode == 0 else None

    def _base_ref(self, task_id: str) -> Optional[str]:
        return self._rev(f"refs/heads/{self._base_branch(task_id)}")

    def _tip_ref(self, task_id: str) -> Optional[str]:
        return self._rev(f"refs/heads/{self._branch(task_id)}")

    def _rev(self, ref: str) -> Optional[str]:
        completed = git.run(
            self.git_dir, self.workspace, ["rev-parse", "--verify", "--quiet", ref], check=False
        )
        if completed.returncode != 0:
            return None
        return completed.stdout.decode("utf-8", "replace").strip() or None

    def _branch(self, task_id: str) -> str:
        return f"{_BRANCH_PREFIX}/{_ref_component(task_id)}"

    def _base_branch(self, task_id: str) -> str:
        return f"{_BRANCH_PREFIX}/{_ref_component(task_id)}{_BASE_SUFFIX}"

    def _record_path(self, task_id: str) -> Path:
        return self.repo_dir / f"{_ref_component(task_id)}.json"

    def _reverted_paths(self, task_id: str) -> set:
        try:
            payload = json.loads(self._record_path(task_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        reverted = payload.get("reverted") if isinstance(payload, dict) else None
        return set(reverted) if isinstance(reverted, list) else set()

    def _mark_reverted(self, task_id: str, paths: Sequence[str]) -> None:
        reverted = sorted(self._reverted_paths(task_id) | set(paths))
        try:
            self._record_path(task_id).write_text(
                json.dumps({"reverted": reverted}, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def _write_workspace_marker(self) -> None:
        """Record which directory this repository belongs to, for humans debugging it."""
        marker = self.repo_dir / "workspace.txt"
        if marker.exists():
            return
        try:
            marker.write_text(str(self.workspace), encoding="utf-8")
        except OSError:
            pass


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        if not path.is_file():
            return None
        return path.read_bytes()
    except OSError:
        return None

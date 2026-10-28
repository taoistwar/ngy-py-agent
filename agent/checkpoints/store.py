"""Recording what a task changed, and putting it back (ADR 0020).

The workspace is snapshotted into a private git repository that lives *outside* it
(``agent/checkpoints/git.py`` explains the plumbing). One repository per workspace,
one branch per task: the branch is what makes attribution possible, because
``git diff <task-base> <task-head>`` then names exactly the files that task touched and
nothing a neighbouring task did.

Baselines are free. The first snapshot a task takes records the current ``HEAD`` as
its base; the first snapshot *ever* in a workspace has to scan the whole tree once to
create that initial commit, and every later task starts from a commit that already
exists.

Two properties are deliberate:

- **Never a gate.** :meth:`CheckpointStore.begin` and :meth:`CheckpointStore.end`
  swallow their own failures. A checkpoint that cannot be written must not stop the
  tool call it was recording.
- **Never silent about being unavailable.** The reason goes into
  :attr:`CheckpointStore.unavailable_reason`, so the API can tell the user that undo
  is off instead of offering a button that cannot work.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from agent.checkpoints import git
from agent.tools.file_access import default_workspace_root

STORE_ROOT_ENV = "CHECKPOINT_ROOT"
ENABLED_ENV = "CHECKPOINT_ENABLED"
DEFAULT_STORE_DIRNAME = "data/checkpoints"

# Tools whose single argument names the file they write, so the snapshot can be an
# O(1) ``git add`` of that path instead of a full tree scan.
FILE_TOOLS: Mapping[str, str] = {"write_file": "file_path", "edit_file": "file_path"}

# Tools that can change anything at all: the snapshot has to look at the whole tree.
# ``write_stdin`` is here because typing into a shell session can do whatever that
# session's command does next, not because it writes files itself.
TREE_TOOLS = frozenset({"exec_command", "write_stdin", "code_interpreter"})

STATUS_ADDED = "added"
STATUS_MODIFIED = "modified"
STATUS_DELETED = "deleted"

_BRANCH_PREFIX = "cp"
_BASE_SUFFIX = "-base"

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


@dataclass(frozen=True)
class Change:
    """One file this task changed."""

    path: str
    status: str
    additions: int = 0
    deletions: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "status": self.status,
            "additions": self.additions,
            "deletions": self.deletions,
        }


@dataclass
class RevertResult:
    """What a revert actually did, per file.

    A revert is not all-or-nothing: a file the user has edited since the task wrote
    it is a conflict, and refusing *that file* must not refuse the rest.
    """

    restored: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.conflicts and not self.skipped

    def to_dict(self) -> Dict[str, Any]:
        return {
            "restored": list(self.restored),
            "conflicts": list(self.conflicts),
            "skipped": list(self.skipped),
            "clean": self.clean,
        }


def _store_root() -> Path:
    override = (os.getenv(STORE_ROOT_ENV) or "").strip()
    return Path(override).expanduser() if override else Path.cwd() / DEFAULT_STORE_DIRNAME


def _enabled() -> bool:
    raw = (os.getenv(ENABLED_ENV) or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _workspace_key(workspace: Path) -> str:
    """A stable, filesystem-safe name for one workspace.

    Case-folded on Windows: the same directory reached through two spellings must not
    end up as two repositories, or a revert would look at the wrong history.
    """
    identity = str(workspace)
    if os.name == "nt":
        identity = identity.lower()
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]


def _ref_component(task_id: str) -> str:
    """A task id that is legal inside a git ref name."""
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in task_id)
    if safe != task_id:
        safe = f"{safe[:24]}-{hashlib.sha1(task_id.encode('utf-8')).hexdigest()[:8]}"
    return safe


def _parse_name_status(raw: bytes) -> List[Tuple[str, str]]:
    """Parse ``git diff --name-status -z`` into ``(status, path)`` pairs.

    Renames are never produced: the diff calls pass ``--no-renames`` so that a moved
    file reports as a delete plus an add. That keeps every entry single-path, which is
    what a per-file revert needs.
    """
    fields = [item for item in raw.split(b"\0") if item]
    pairs: List[Tuple[str, str]] = []
    for index in range(0, len(fields) - 1, 2):
        status = fields[index].decode("utf-8", "replace")[:1]
        path = fields[index + 1].decode("utf-8", "replace")
        pairs.append((status, path))
    return pairs


def _parse_numstat(raw: bytes) -> Dict[str, Tuple[int, int]]:
    """Parse ``git diff --numstat -z`` into ``path -> (additions, deletions)``.

    With ``-z`` each entry is one NUL-terminated record of ``added\tdel\tpath``;
    binary files report ``-`` for both counts.
    """
    counts: Dict[str, Tuple[int, int]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        parts = record.decode("utf-8", "replace").split("\t")
        if len(parts) < 3:
            continue
        added, removed = parts[0], parts[1]
        # A path containing a tab survives the split; it is everything past the second.
        path = "\t".join(parts[2:])
        counts[path] = (
            0 if added == "-" else int(added or 0),
            0 if removed == "-" else int(removed or 0),
        )
    return counts


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

        This is the only moment the pre-change state can be captured, so the first
        mutating call of the first task in a workspace is where the one full tree
        scan happens. Every later call finds the ref already recorded and returns
        after a single ``rev-parse``.
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
                Change(path=path, status=_status_of(status_code), additions=added, deletions=removed)
            )
        return changes

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
        """Capture the workspace as it is now and make it this task's baseline."""
        head = git.run(
            self.git_dir, self.workspace, ["rev-parse", "--verify", "--quiet", "HEAD"], check=False
        )
        if head.returncode != 0:
            # The first snapshot in this workspace: the baseline is whatever is on
            # disk right now. The only full tree scan the store ever does.
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


def _status_of(code: str) -> str:
    if code == "A":
        return STATUS_ADDED
    if code == "D":
        return STATUS_DELETED
    return STATUS_MODIFIED


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        if not path.is_file():
            return None
        return path.read_bytes()
    except OSError:
        return None


def _normalized(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - platform specific
        return path.absolute()


def _workspace_path(base_dir: Optional[str]) -> Optional[Path]:
    text = (base_dir or "").strip()
    if text:
        candidate = _normalized(Path(text).expanduser())
    else:
        candidate = _normalized(default_workspace_root())
    return candidate if candidate.is_dir() else None

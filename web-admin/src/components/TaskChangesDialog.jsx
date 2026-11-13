import { useCallback, useEffect, useState } from "react"

import { fetchTaskChangeDiff, fetchTaskChanges, revertTask } from "../api"
import Modal from "./admin/Modal"

const STATUS_LABEL_KEYS = {
  added: "changeStatusAdded",
  modified: "changeStatusModified",
  deleted: "changeStatusDeleted",
}

/**
 * What a task changed, with a per-file undo (ADR 0020).
 *
 * The list is the task's own history, not a diff of the workspace: it comes from the
 * checkpoint branch the task wrote to, so it keeps naming the files this task touched
 * even after other tasks have run.
 *
 * A file marked ``conflict`` was edited after the task wrote it - by the user or by
 * another agent - so undoing it would overwrite that work. Its undo button is
 * disabled and the row says why; the server refuses the same file on its own.
 */
export default function TaskChangesDialog({ taskId, translate, onClose, onReverted }) {
  const [state, setState] = useState({ available: false, reason: "", files: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [preview, setPreview] = useState({ path: "", diff: "", loading: false })
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      setState(await fetchTaskChanges(taskId))
    } catch (loadError) {
      setError(loadError?.message || translate("revertFailed"))
    } finally {
      setLoading(false)
    }
  }, [taskId, translate])

  useEffect(() => {
    load()
  }, [load])

  const showDiff = async (path) => {
    if (preview.path === path) {
      setPreview({ path: "", diff: "", loading: false })
      return
    }
    setPreview({ path, diff: "", loading: true })
    try {
      const payload = await fetchTaskChangeDiff(taskId, path)
      setPreview({ path, diff: payload.diff || "", loading: false })
    } catch (diffError) {
      setPreview({ path: "", diff: "", loading: false })
      setError(diffError?.message || translate("revertFailed"))
    }
  }

  const undo = async (paths) => {
    if (busy || paths.length === 0) return
    setBusy(true)
    setError("")
    try {
      setResult(await revertTask(taskId, { paths }))
      // The patch of an undone file no longer describes anything on disk.
      setPreview({ path: "", diff: "", loading: false })
      await load()
      onReverted?.()
    } catch (revertError) {
      setError(revertError?.message || translate("revertFailed"))
    } finally {
      setBusy(false)
    }
  }

  const files = state.files || []
  const undoable = files.filter((file) => !file.conflict).map((file) => file.path)
  const restored = result?.restored || []

  return (
    <Modal
      title={translate("taskChangesTitle")}
      hint={translate("taskChangesHint")}
      closeLabel={translate("revertCancel")}
      onClose={onClose}
      wide
    >
      <div className="permission-prompt">
        {loading ? <p className="hint">{translate("revertLoading")}</p> : null}

        {!loading && !state.available ? (
          <p className="permission-error">{state.reason || translate("revertUnavailable")}</p>
        ) : null}

        {!loading && state.available && files.length === 0 ? (
          <p className="hint">{translate("revertEmpty")}</p>
        ) : null}

        {files.length > 0 ? (
          <>
            <div className="change-toolbar">
              <span className="hint">
                {files.length} {translate("taskChangesFiles")}
              </span>
              <button
                type="button"
                className="btn btn-primary btn-compact"
                disabled={busy || undoable.length === 0}
                onClick={() => undo(undoable)}
              >
                {busy ? translate("revertSending") : translate("taskChangesUndoAll")}
              </button>
            </div>
            <div className="change-list">
              {files.map((file) => (
                <div
                  key={file.path}
                  className={`change-row ${file.conflict ? "change-row-conflict" : ""}`}
                >
                  <button
                    type="button"
                    className="change-open"
                    title={translate("revertPreview")}
                    onClick={() => showDiff(file.path)}
                  >
                    <span className={`change-status change-status-${file.status}`}>
                      {translate(STATUS_LABEL_KEYS[file.status] || "changeStatusModified")}
                    </span>
                    <span className="change-path">{file.path}</span>
                    <span className="change-counts">
                      <span className="change-additions">+{file.additions}</span>
                      <span className="change-deletions">-{file.deletions}</span>
                    </span>
                  </button>
                  {file.conflict ? (
                    <span className="change-conflict">{translate("taskChangesConflict")}</span>
                  ) : null}
                  <button
                    type="button"
                    className="btn btn-compact"
                    disabled={busy || file.conflict}
                    title={
                      file.conflict
                        ? translate("taskChangesConflict")
                        : translate("taskChangesUndo")
                    }
                    onClick={() => undo([file.path])}
                  >
                    {translate("taskChangesUndo")}
                  </button>
                  {preview.path === file.path ? (
                    <pre className="change-diff">
                      {preview.loading
                        ? translate("revertLoading")
                        : preview.diff || translate("revertPreviewEmpty")}
                    </pre>
                  ) : null}
                </div>
              ))}
            </div>
          </>
        ) : null}

        {restored.length > 0 ? (
          <p className="hint">
            {translate("revertDone")} {restored.join(", ")}
          </p>
        ) : null}

        {result?.conflicts?.length > 0 ? (
          <p className="permission-error">
            {translate("revertConflictNote")} {result.conflicts.join(", ")}
          </p>
        ) : null}

        {error ? <p className="permission-error">{error}</p> : null}

        <div className="permission-actions">
          <button type="button" className="btn" onClick={onClose}>
            {translate("revertCancel")}
          </button>
        </div>
      </div>
    </Modal>
  )
}

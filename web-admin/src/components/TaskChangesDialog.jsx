import { useCallback, useEffect, useState } from "react"
import { DiffEditor } from "@monaco-editor/react"

import { fetchTaskChangeDiff, fetchTaskChanges, revertTask } from "../api"
import { useTheme } from "../theme"
import { languageForPath } from "../utils/language"
import Modal from "./admin/Modal"

const STATUS_LABEL_KEYS = {
  added: "changeStatusAdded",
  modified: "changeStatusModified",
  deleted: "changeStatusDeleted",
}

// Tall enough to read a hunk in context, short enough to leave the file list
// visible underneath: the dialog is about choosing a file, not about reading it.
const DIFF_EDITOR_HEIGHT = "280px"

const DIFF_OPTIONS = {
  readOnly: true,
  originalEditable: false,
  renderSideBySide: true,
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  fontSize: 12,
  lineNumbers: "on",
  renderLineHighlight: "none",
  wordWrap: "on",
  automaticLayout: true,
}

function emptyPreview() {
  return { path: "", diff: "", before: null, after: null, loading: false }
}

/**
 * One file's change, as a read-only Monaco diff.
 *
 * ``before``/``after`` are the full texts; when the server has none to give - a
 * binary file, one too large to render - the raw patch is shown instead, since
 * hiding the change entirely would be worse than showing it plainly.
 */
function ChangePreview({ preview, path, translate }) {
  const { monacoTheme } = useTheme()
  const sideBySide = typeof preview.before === "string" && typeof preview.after === "string"

  if (preview.loading) {
    return (
      <div className="change-diff">
        <p className="hint change-diff-note">{translate("revertLoading")}</p>
      </div>
    )
  }

  if (!sideBySide) {
    return (
      <div className="change-diff">
        <pre className="change-diff-patch">
          {preview.diff || translate("revertPreviewEmpty")}
        </pre>
      </div>
    )
  }

  return (
    <div className="change-diff">
      <DiffEditor
        height={DIFF_EDITOR_HEIGHT}
        language={languageForPath(path)}
        original={preview.before}
        modified={preview.after}
        options={DIFF_OPTIONS}
        theme={monacoTheme}
      />
    </div>
  )
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
  const [preview, setPreview] = useState(emptyPreview)
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
      setPreview(emptyPreview())
      return
    }
    setPreview({ ...emptyPreview(), path, loading: true })
    try {
      const payload = await fetchTaskChangeDiff(taskId, path)
      setPreview({
        path,
        diff: payload.diff || "",
        // ``null`` means "not text": that file falls back to the patch below.
        before: typeof payload.before === "string" ? payload.before : null,
        after: typeof payload.after === "string" ? payload.after : null,
        loading: false,
      })
    } catch (diffError) {
      setPreview(emptyPreview())
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
      setPreview(emptyPreview())
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
                    <ChangePreview preview={preview} path={file.path} translate={translate} />
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

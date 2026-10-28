import { useCallback, useEffect, useState } from "react"

import { fetchTaskChangeDiff, fetchTaskChanges, revertTask } from "../api"
import Modal from "./admin/Modal"

/**
 * Undo a task's file changes (ADR 0020).
 *
 * The list is the task's own history, not a diff of the workspace: it comes from the
 * checkpoint branch the task wrote to, so it keeps naming the files this task touched
 * even after other tasks have run.
 *
 * ``available: false`` is not an error - a machine without git, a run from before the
 * feature existed, and a disabled store all answer that way, and the payload carries
 * the reason. Showing the reason beats showing a button that cannot do anything.
 */
export default function RevertChangesDialog({ taskId, translate, onClose, onReverted }) {
  const [state, setState] = useState({ available: false, reason: "", files: [] })
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState([])
  const [preview, setPreview] = useState({ path: "", diff: "" })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [result, setResult] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const payload = await fetchTaskChanges(taskId)
      setState(payload)
      // Everything is pre-selected: "undo this task" is the common case, and
      // un-ticking a file is a cheaper gesture than ticking ten.
      setSelected(payload.files.map((file) => file.path))
    } catch (loadError) {
      setError(loadError?.message || translate("revertFailed"))
    } finally {
      setLoading(false)
    }
  }, [taskId, translate])

  useEffect(() => {
    load()
  }, [load])

  const toggle = (path) => {
    setSelected((current) =>
      current.includes(path) ? current.filter((item) => item !== path) : [...current, path]
    )
  }

  const showDiff = async (path) => {
    if (preview.path === path) {
      setPreview({ path: "", diff: "" })
      return
    }
    try {
      const payload = await fetchTaskChangeDiff(taskId, path)
      setPreview({ path, diff: payload.diff || "" })
    } catch (diffError) {
      setError(diffError?.message || translate("revertFailed"))
    }
  }

  const submit = async () => {
    if (busy || selected.length === 0) return
    setBusy(true)
    setError("")
    try {
      const payload = await revertTask(taskId, { paths: selected })
      setResult(payload)
      await load()
      onReverted?.()
    } catch (revertError) {
      setError(revertError?.message || translate("revertFailed"))
    } finally {
      setBusy(false)
    }
  }

  const conflicts = result?.conflicts || []

  return (
    <Modal
      title={translate("revertTitle")}
      hint={translate("revertHint")}
      closeLabel={translate("revertCancel")}
      onClose={onClose}
      wide
    >
      <div className="permission-prompt">
        {loading ? <p className="hint">{translate("revertLoading")}</p> : null}

        {!loading && !state.available ? (
          <p className="permission-error">{state.reason || translate("revertUnavailable")}</p>
        ) : null}

        {!loading && state.available && state.files.length === 0 ? (
          <p className="hint">{translate("revertEmpty")}</p>
        ) : null}

        {state.files.map((file) => (
          <div className="permission-field" key={file.path}>
            <label>
              <input
                type="checkbox"
                checked={selected.includes(file.path)}
                onChange={() => toggle(file.path)}
              />
              <strong>{file.path}</strong>
            </label>
            <span className="hint">
              {file.status} +{file.additions} -{file.deletions}
            </span>
            <button type="button" className="btn btn-compact" onClick={() => showDiff(file.path)}>
              {translate("revertPreview")}
            </button>
          </div>
        ))}

        {preview.path ? (
          <div className="permission-detail">
            <em>{preview.path}</em>
            <pre>{preview.diff || translate("revertPreviewEmpty")}</pre>
          </div>
        ) : null}

        {conflicts.length > 0 ? (
          <p className="permission-error">
            {translate("revertConflictNote")} {conflicts.join(", ")}
          </p>
        ) : null}

        {result && result.restored.length > 0 ? (
          <p className="hint">
            {translate("revertDone")} {result.restored.join(", ")}
          </p>
        ) : null}

        {error ? <p className="permission-error">{error}</p> : null}

        <div className="permission-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || selected.length === 0 || !state.available}
            onClick={submit}
          >
            {busy ? translate("revertSending") : translate("revertSelected")}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            {translate("revertCancel")}
          </button>
        </div>
      </div>
    </Modal>
  )
}

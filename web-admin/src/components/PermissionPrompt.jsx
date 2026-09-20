import { useState } from "react"
import Modal from "./admin/Modal"
import { answerPermission } from "../api"

/**
 * Confirmation dialog for a tool call that is blocking the agent.
 *
 * The request comes from ``GET /api/tasks/{id}`` (``pending_permission``) and the
 * task thread is parked until this posts back, times out, or the task is stopped.
 *
 * It is deliberately **not** dismissible and its close button says "Deny": there
 * is no "maybe later", because the agent stays blocked either way, and the only
 * silent outcome would be the timeout - which is a refusal anyway. Making that
 * explicit beats letting Escape look like it did nothing.
 */
const DETAIL_LABELS = {
  command: "command",
  description: "description",
  code: "code",
  content: "content",
  content_bytes: "content_bytes",
  old_string: "old_string",
  new_string: "new_string",
  reason: "reason",
  gitDiff: "diff",
  match_count: "matches",
  encoding: "encoding",
}

export default function PermissionPrompt({ request, onDecided, translate }) {
  const [busy, setBusy] = useState("")
  const [error, setError] = useState("")

  if (!request) {
    return null
  }

  const decide = async (allowed, scope) => {
    if (busy) return
    // "always" is a persistent approval: it survives the task, so it must be the
    // button the user actually pressed rather than a default.
    setBusy(allowed ? scope : "deny")
    setError("")
    try {
      await answerPermission(request.task_id, request.request_id, allowed, scope)
      onDecided?.()
    } catch (submitError) {
      setError(submitError?.message || translate("permissionFailed"))
    } finally {
      setBusy("")
    }
  }

  const details = Object.entries(request.details || {}).filter(
    ([key, value]) => key !== "kind" && value !== "" && value !== null && value !== undefined
  )

  return (
    <Modal
      title={request.summary || request.tool}
      hint={translate("permissionHint")}
      closeLabel={translate("permissionDeny")}
      onClose={() => decide(false, "once")}
      dismissible={false}
      wide
    >
      <div className="permission-prompt">
        <div className="permission-field">
          <span>{translate("permissionTool")}</span>
          <strong>{request.tool}</strong>
        </div>
        <div className="permission-field">
          <span>{translate("permissionTarget")}</span>
          <code className="permission-target">{request.target}</code>
        </div>
        {details.length > 0 ? (
          <div className="permission-details">
            <span className="hint">{translate("permissionDetails")}</span>
            {details.map(([key, value]) => (
              <div className="permission-detail" key={key}>
                <em>{DETAIL_LABELS[key] || key}</em>
                <pre>{String(value)}</pre>
              </div>
            ))}
          </div>
        ) : null}
        {error ? <p className="permission-error">{error}</p> : null}
        <div className="permission-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={Boolean(busy)}
            onClick={() => decide(true, "once")}
          >
            {busy === "once" ? translate("permissionSending") : translate("permissionAllowOnce")}
          </button>
          <button
            type="button"
            className="btn"
            disabled={Boolean(busy)}
            onClick={() => decide(true, "session")}
          >
            {busy === "session" ? translate("permissionSending") : translate("permissionAllowSession")}
          </button>
          <button
            type="button"
            className="btn"
            disabled={Boolean(busy)}
            onClick={() => decide(true, "always")}
          >
            {busy === "always" ? translate("permissionSending") : translate("permissionAllowAlways")}
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={Boolean(busy)}
            onClick={() => decide(false, "once")}
          >
            {busy === "deny" ? translate("permissionSending") : translate("permissionDeny")}
          </button>
        </div>
      </div>
    </Modal>
  )
}

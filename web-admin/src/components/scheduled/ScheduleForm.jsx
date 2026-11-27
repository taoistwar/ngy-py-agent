// Create or edit one scheduled task. The form is the only place a cron expression is
// typed, so the pattern and its examples sit right next to the field instead of in a
// help page nobody opens.
import { useState } from "react"
import { agentDisplayName } from "../admin/shared"
import { PERMISSION_MODE_VALUES, permissionModeLabel } from "./permissionOptions"

const DEFAULT_CRON = "0 9 * * *"

export default function ScheduleForm({
  schedule,
  agents,
  models,
  workspaces,
  onSubmit,
  onCancel,
  translate,
}) {
  const editing = Boolean(schedule?.schedule_id)
  const [name, setName] = useState(schedule?.name || "")
  const [cron, setCron] = useState(schedule?.cron || DEFAULT_CRON)
  const [prompt, setPrompt] = useState(schedule?.prompt || "")
  const [agentId, setAgentId] = useState(schedule?.agent_id || "")
  const [modelId, setModelId] = useState(schedule?.model_id || "")
  const [workspaceId, setWorkspaceId] = useState(schedule?.workspace_id || "")
  const [permissionMode, setPermissionMode] = useState(schedule?.permission_mode || "")
  const [enabled, setEnabled] = useState(schedule ? schedule.enabled : true)
  const [recurring, setRecurring] = useState(schedule ? schedule.recurring : true)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState("")

  // The first agent is what the backend falls back to when none is chosen, so the
  // select shows it instead of an empty option that would mean something else.
  const effectiveAgentId = agentId || agents?.[0]?.agent_id || ""

  const submit = async (event) => {
    event.preventDefault()
    setFormError("")
    if (!cron.trim()) {
      setFormError(translate("scheduleFormCronRequired"))
      return
    }
    if (!prompt.trim()) {
      setFormError(translate("scheduleFormPromptRequired"))
      return
    }
    setBusy(true)
    try {
      await onSubmit({
        name: name.trim(),
        cron: cron.trim(),
        prompt: prompt.trim(),
        agent_id: effectiveAgentId,
        model_id: modelId || null,
        workspace_id: workspaceId || null,
        permission_mode: permissionMode,
        enabled,
        recurring,
      })
    } catch (submitError) {
      // The backend's message names the offending field (usually the cron), so it is
      // shown inside the form rather than in the page-wide banner.
      setFormError(submitError?.message || translate("errorUnknown"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="schedule-form" onSubmit={submit}>
      <div className="schedule-form-head">
        <h3>{translate(editing ? "scheduleFormEditTitle" : "scheduleFormCreateTitle")}</h3>
        <button type="button" className="btn btn-compact" onClick={onCancel}>
          {translate("scheduleFormCancel")}
        </button>
      </div>

      <div className="schedule-form-row">
        <label>
          <span>{translate("scheduleFormName")}</span>
          <input
            type="text"
            value={name}
            placeholder={translate("scheduleFormNamePlaceholder")}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          <span>{translate("scheduleFormCron")}</span>
          <input
            type="text"
            className="schedule-cron-input"
            value={cron}
            spellCheck="false"
            placeholder="0 9 * * *"
            onChange={(event) => setCron(event.target.value)}
          />
        </label>
      </div>
      <span className="hint schedule-cron-hint">{translate("scheduleFormCronHint")}</span>

      <label>
        <span>{translate("scheduleFormPrompt")}</span>
        <textarea
          className="schedule-prompt-input"
          value={prompt}
          placeholder={translate("scheduleFormPromptPlaceholder")}
          onChange={(event) => setPrompt(event.target.value)}
        />
      </label>

      <div className="schedule-form-row">
        <label>
          <span>{translate("scheduleFormAgent")}</span>
          <select value={effectiveAgentId} onChange={(event) => setAgentId(event.target.value)}>
            {(agents || []).map((agent) => (
              <option key={agent.agent_id} value={agent.agent_id}>
                {agentDisplayName(agent, translate)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{translate("scheduleFormModel")}</span>
          <select value={modelId} onChange={(event) => setModelId(event.target.value)}>
            <option value="">{translate("scheduleFormModelDefault")}</option>
            {(models || []).map((model) => (
              <option key={model.model_id} value={model.model_id}>
                {model.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{translate("scheduleFormWorkspace")}</span>
          <select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}>
            <option value="">{translate("scheduleFormWorkspaceNone")}</option>
            {(workspaces || []).map((workspace) => (
              <option key={workspace.workspace_id} value={workspace.workspace_id}>
                {workspace.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{translate("scheduleFormPermission")}</span>
          <select
            value={permissionMode}
            onChange={(event) => setPermissionMode(event.target.value)}
          >
            <option value="">{translate("scheduleFormPermissionGlobal")}</option>
            {PERMISSION_MODE_VALUES.map((mode) => (
              <option key={mode} value={mode}>
                {permissionModeLabel(translate, mode)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <span className="hint">{translate("scheduleFormPermissionHint")}</span>

      <div className="schedule-form-checks">
        <label className="schedule-check">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
          />
          <span>{translate("scheduleFormEnabled")}</span>
        </label>
        <label className="schedule-check">
          <input
            type="checkbox"
            checked={recurring}
            onChange={(event) => setRecurring(event.target.checked)}
          />
          <span>{translate("scheduleFormRecurring")}</span>
        </label>
      </div>
      <span className="hint">{translate("scheduleFormRecurringHint")}</span>

      {formError ? <p className="form-error">{formError}</p> : null}

      <div className="schedule-form-actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {translate(busy ? "scheduleFormSaving" : "scheduleFormSave")}
        </button>
      </div>
    </form>
  )
}

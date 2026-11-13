import { useEffect, useState } from "react"

// Mirrors MAX_STEPS_LIMIT in api_schemas.py so the field never offers a rejected value.
const MAX_STEPS_LIMIT = 10000

export function MaxStepsManager({ maxStepsConfig, onSave, onRefresh, translate }) {
  const [value, setValue] = useState("")
  const [busy, setBusy] = useState(false)
  // One editable field shows the live value, so the panel needs no separate read-only copy.
  const current = maxStepsConfig ? String(maxStepsConfig.max_steps ?? "") : ""
  const changed = Boolean(value) && value !== current

  useEffect(() => {
    if (!maxStepsConfig) return
    setValue(String(maxStepsConfig.max_steps ?? 8))
  }, [maxStepsConfig])

  const submit = async (event) => {
    event.preventDefault()
    const parsed = Number(value)
    if (!Number.isFinite(parsed) || parsed < 1) return
    setBusy(true)
    try {
      await onSave(Math.max(1, Math.min(parsed, MAX_STEPS_LIMIT)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("maxStepsTitle")}</h2>
          <span className="hint">
            {translate("maxStepsCurrentSource")}:{" "}
            {maxStepsConfig?.source === "database"
              ? translate("maxStepsSourceDb")
              : translate("maxStepsSourceEnv")}
          </span>
        </div>
        <button type="button" className="btn btn-compact" onClick={onRefresh}>
          {translate("sidebarQuickRefreshMaxSteps")}
        </button>
      </div>
      <div className="panel-body">
        <form className="form-grid" onSubmit={submit}>
          <label>
            <span>{translate("maxStepsSet")}</span>
            <input
              type="number"
              min="1"
              max={MAX_STEPS_LIMIT}
              value={value}
              disabled={!maxStepsConfig}
              onChange={(event) => setValue(event.target.value)}
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy || !changed}>
            {busy ? translate("maxStepsSaving") : translate("maxStepsSave")}
          </button>
        </form>
        <div className="hint">{translate("maxStepsHint")}</div>
      </div>
    </section>
  )
}

export function PermissionModeManager({ permissionModeConfig, onSave, onRefresh, translate }) {
  const [mode, setMode] = useState("")
  const [busy, setBusy] = useState(false)
  const current = permissionModeConfig ? String(permissionModeConfig.mode || "") : ""
  const changed = Boolean(mode) && mode !== current

  useEffect(() => {
    if (!permissionModeConfig) return
    setMode(String(permissionModeConfig.mode || "ask"))
  }, [permissionModeConfig])

  const submit = async (event) => {
    event.preventDefault()
    if (!mode) return
    setBusy(true)
    try {
      await onSave(mode)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("permissionModeTitle")}</h2>
          <span className="hint">
            {translate("permissionModeCurrentSource")}:{" "}
            {permissionModeConfig?.source === "database"
              ? translate("permissionModeSourceDb")
              : translate("permissionModeSourceEnv")}
          </span>
        </div>
        <button type="button" className="btn btn-compact" onClick={onRefresh}>
          {translate("sidebarQuickRefreshPermissionMode")}
        </button>
      </div>
      <div className="panel-body">
        <form className="form-grid" onSubmit={submit}>
          <label>
            <span>{translate("permissionModeSet")}</span>
            <select
              value={mode}
              disabled={!permissionModeConfig}
              onChange={(event) => setMode(event.target.value)}
            >
              <option value="ask">{translate("permissionModeAsk")}</option>
              <option value="auto_approve">{translate("permissionModeAuto")}</option>
              <option value="deny_all">{translate("permissionModeDenyAll")}</option>
            </select>
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy || !changed}>
            {busy ? translate("permissionModeSaving") : translate("permissionModeSave")}
          </button>
        </form>
        <div className="hint">{translate("permissionModeHint")}</div>
      </div>
    </section>
  )
}

export function RetentionManager({ retentionConfig, onSave, onRefresh, translate }) {
  const [days, setDays] = useState("")
  const [busy, setBusy] = useState(false)
  const current = retentionConfig ? String(retentionConfig.retention_days ?? "") : ""
  const changed = Boolean(days) && days !== current

  useEffect(() => {
    if (!retentionConfig) return
    setDays(String(retentionConfig.retention_days ?? 0))
  }, [retentionConfig])

  const submit = async (event) => {
    event.preventDefault()
    const parsed = Number(days)
    if (!Number.isFinite(parsed) || parsed < 0) return
    setBusy(true)
    try {
      await onSave(parsed)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("retentionTitle")}</h2>
          <span className="hint">
            {translate("retentionCurrentSource")}:{" "}
            {retentionConfig?.retention_source === "database"
              ? translate("retentionSourceDb")
              : translate("retentionSourceEnv")}
          </span>
        </div>
        <button type="button" className="btn btn-compact" onClick={onRefresh}>
          {translate("sidebarQuickRefreshRetention")}
        </button>
      </div>
      <div className="panel-body">
        <form className="form-grid" onSubmit={submit}>
          <label>
            <span>{translate("retentionSetDays")}</span>
            <input
              type="number"
              min="0"
              value={days}
              disabled={!retentionConfig}
              onChange={(event) => setDays(event.target.value)}
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy || !changed}>
            {busy ? translate("retentionSaving") : translate("retentionSave")}
          </button>
        </form>
        <div className="hint">{translate("retentionHint")}</div>
      </div>
    </section>
  )
}

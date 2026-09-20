import { useEffect, useState } from "react"

export function MaxStepsManager({ maxStepsConfig, onSave, onRefresh, translate }) {
  const [value, setValue] = useState("")
  const [busy, setBusy] = useState(false)

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
      await onSave(Math.max(1, Math.min(parsed, 1000)))
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
            <span>{translate("maxStepsCurrent")}</span>
            <input type="text" readOnly value={maxStepsConfig ? maxStepsConfig.max_steps : ""} />
          </label>
          <label>
            <span>{translate("maxStepsSet")}</span>
            <input type="number" min="1" max="1000" value={value} onChange={(event) => setValue(event.target.value)} />
          </label>
          <button type="submit" className="btn" disabled={busy || !value}>
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
            <span>{translate("permissionModeCurrent")}</span>
            <input
              type="text"
              readOnly
              value={permissionModeConfig ? permissionModeConfig.mode : ""}
            />
          </label>
          <label>
            <span>{translate("permissionModeSet")}</span>
            <select value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="ask">{translate("permissionModeAsk")}</option>
              <option value="auto_approve">{translate("permissionModeAuto")}</option>
              <option value="deny_all">{translate("permissionModeDenyAll")}</option>
            </select>
          </label>
          <button type="submit" className="btn" disabled={busy || !mode}>
            {busy ? translate("permissionModeSaving") : translate("permissionModeSave")}
          </button>
        </form>
        <div className="hint">{translate("permissionModeHint")}</div>
      </div>
    </section>
  )
}

export function PermissionRulesManager({ rules, onDelete, onRefresh, translate }) {
  const [busy, setBusy] = useState("")
  const list = rules?.rules || []

  const remove = async (rule) => {
    const key = `${rule.tool}|${rule.target}`
    setBusy(key)
    try {
      await onDelete(rule.tool, rule.target)
    } finally {
      setBusy("")
    }
  }

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("permissionRulesTitle")}</h2>
          <span className="hint">{rules?.path || ""}</span>
        </div>
        <button type="button" className="btn btn-compact" onClick={onRefresh}>
          {translate("sidebarQuickRefreshPermissionRules")}
        </button>
      </div>
      <div className="panel-body">
        {list.length === 0 ? (
          <div className="hint">{translate("permissionRulesEmpty")}</div>
        ) : (
          <ul className="permission-rule-list">
            {list.map((rule) => (
              <li key={`${rule.tool}|${rule.target}`}>
                <div className="permission-rule-body">
                  <strong>{rule.tool}</strong>
                  <code>{rule.target}</code>
                </div>
                <button
                  type="button"
                  className="btn btn-compact btn-danger"
                  disabled={busy === `${rule.tool}|${rule.target}`}
                  onClick={() => remove(rule)}
                >
                  {translate("permissionRulesRemove")}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="hint">{translate("permissionRulesHint")}</div>
      </div>
    </section>
  )
}

export function RetentionManager({ retentionConfig, onSave, onRefresh, translate }) {
  const [days, setDays] = useState("")
  const [busy, setBusy] = useState(false)

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
            <span>{translate("retentionCurrentDays")}</span>
            <input type="text" readOnly value={retentionConfig ? retentionConfig.retention_days : ""} />
          </label>
          <label>
            <span>{translate("retentionSetDays")}</span>
            <input type="number" min="0" value={days} onChange={(event) => setDays(event.target.value)} />
          </label>
          <button type="submit" className="btn" disabled={busy || !days}>
            {busy ? translate("retentionSaving") : translate("retentionSave")}
          </button>
        </form>
        <div className="hint">{translate("retentionHint")}</div>
      </div>
    </section>
  )
}

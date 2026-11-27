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
    setValue(String(maxStepsConfig.max_steps ?? 9))
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
              : translate("maxStepsSourceDefault")}
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

// Mirrors MIN_MAX_BYTES / MAX_BYTES_LIMIT in agent/agents_md.py so the field never
// offers a value the API would reject.
const AGENTS_MD_MIN_BYTES = 1024
const AGENTS_MD_MAX_BYTES_LIMIT = 1024 * 1024

export function AgentsMdManager({ agentsMdConfig, onSave, onRefresh, translate }) {
  const [enabled, setEnabled] = useState(true)
  const [maxBytes, setMaxBytes] = useState("")
  const [busy, setBusy] = useState(false)
  const currentEnabled = Boolean(agentsMdConfig?.enabled)
  const currentBytes = agentsMdConfig ? String(agentsMdConfig.max_bytes ?? "") : ""
  // Both fields are one setting, so either change means "save again".
  const changed =
    Boolean(agentsMdConfig) && (enabled !== currentEnabled || maxBytes !== currentBytes)

  useEffect(() => {
    if (!agentsMdConfig) return
    setEnabled(Boolean(agentsMdConfig.enabled))
    setMaxBytes(String(agentsMdConfig.max_bytes ?? AGENTS_MD_MIN_BYTES))
  }, [agentsMdConfig])

  const submit = async (event) => {
    event.preventDefault()
    const parsed = Number(maxBytes)
    if (!Number.isFinite(parsed)) return
    setBusy(true)
    try {
      await onSave(
        enabled,
        Math.max(AGENTS_MD_MIN_BYTES, Math.min(parsed, AGENTS_MD_MAX_BYTES_LIMIT)),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("agentsMdTitle")}</h2>
          <span className="hint">
            {translate("agentsMdCurrentSource")}:{" "}
            {agentsMdConfig?.source === "database"
              ? translate("agentsMdSourceDb")
              : translate("agentsMdSourceDefault")}
          </span>
        </div>
        <button type="button" className="btn btn-compact" onClick={onRefresh}>
          {translate("sidebarQuickRefreshAgentsMd")}
        </button>
      </div>
      <div className="panel-body">
        <form className="form-grid" onSubmit={submit}>
          <label>
            <span>{translate("agentsMdEnabled")}</span>
            <select
              value={enabled ? "on" : "off"}
              disabled={!agentsMdConfig}
              onChange={(event) => setEnabled(event.target.value === "on")}
            >
              <option value="on">{translate("agentsMdEnabledOn")}</option>
              <option value="off">{translate("agentsMdEnabledOff")}</option>
            </select>
          </label>
          <label>
            <span>{translate("agentsMdMaxBytes")}</span>
            <input
              type="number"
              min={AGENTS_MD_MIN_BYTES}
              max={AGENTS_MD_MAX_BYTES_LIMIT}
              step="1024"
              value={maxBytes}
              disabled={!agentsMdConfig}
              onChange={(event) => setMaxBytes(event.target.value)}
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy || !changed}>
            {busy ? translate("agentsMdSaving") : translate("agentsMdSave")}
          </button>
        </form>
        <div className="hint">{translate("agentsMdHint")}</div>
      </div>
    </section>
  )
}

/**
 * The model that translates reasoning traces into the console's language.
 *
 * One choice for the whole app: unset means reasoning is never translated, which is
 * also the shipped default - a translation is a model call per trace.
 */
export function TranslationModelManager({ translationConfig, models, onSave, onRefresh, translate }) {
  const [modelId, setModelId] = useState("")
  const [busy, setBusy] = useState(false)
  const current = translationConfig ? String(translationConfig.model_id || "") : ""
  const changed = Boolean(translationConfig) && modelId !== current
  // A model deleted after being chosen is no longer in the list; keeping it as an
  // option would show a selection the server cannot resolve.
  const options = models || []
  const known = options.some((model) => model.model_id === current)

  useEffect(() => {
    if (!translationConfig) return
    setModelId(String(translationConfig.model_id || ""))
  }, [translationConfig])

  const submit = async (event) => {
    event.preventDefault()
    if (!changed) return
    setBusy(true)
    try {
      await onSave(modelId)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("translationTitle")}</h2>
          <span className="hint">
            {translate("translationCurrentSource")}:{" "}
            {translationConfig?.source === "database"
              ? translate("translationSourceDb")
              : translate("translationSourceDefault")}
          </span>
        </div>
        <button type="button" className="btn btn-compact" onClick={onRefresh}>
          {translate("sidebarQuickRefreshTranslation")}
        </button>
      </div>
      <div className="panel-body">
        <form className="form-grid" onSubmit={submit}>
          <label>
            <span>{translate("translationModelLabel")}</span>
            <select
              value={known || !current ? modelId : current}
              disabled={!translationConfig}
              onChange={(event) => setModelId(event.target.value)}
            >
              <option value="">{translate("translationModelOff")}</option>
              {!known && current ? <option value={current}>{current}</option> : null}
              {options.map((model) => (
                <option key={model.model_id} value={model.model_id}>
                  {model.name}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy || !changed}>
            {busy ? translate("translationSaving") : translate("translationSave")}
          </button>
        </form>
        <div className="hint">{translate("translationHint")}</div>
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
              : translate("retentionSourceDefault")}
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

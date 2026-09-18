// Shared constants, helpers and form atoms used by the admin management panels.

const BUILTIN_AGENT_LABEL_KEYS = {
  build: "modeBuild",
  ask: "modeAsk",
  plan: "modePlan",
}

export function agentDisplayName(agent, translate) {
  if (!agent) return ""
  if (agent.is_builtin && BUILTIN_AGENT_LABEL_KEYS[agent.agent_id]) {
    return translate(BUILTIN_AGENT_LABEL_KEYS[agent.agent_id])
  }
  return agent.name
}

export const PROVIDER_OPTIONS = [
  "openai-compatible",
  "openai",
  "anthropic",
  "anthropic-compatible",
  "ollama",
  "gemini",
]

// Mirrors MCP_TRANSPORTS in mcp_store.py; the backend rejects anything else.
export const MCP_TRANSPORT_OPTIONS = ["stdio", "sse"]

export const INPUT_TOKEN_PRESETS = [32768, 65536, 131072, 262144]
export const OUTPUT_TOKEN_PRESETS = [8192, 16384, 32768, 65536]

export function formatTokenCount(value) {
  const num = Number(value)
  if (!Number.isFinite(num) || num <= 0) return ""
  if (num % 1024 === 0) return `${num / 1024}K`
  if (num % 1000 === 0) return `${num / 1000}K`
  return String(num)
}

/** Case-insensitive keyword match across any of the provided fields. */
export function matchesKeyword(keyword, ...values) {
  const needle = String(keyword || "").trim().toLowerCase()
  if (!needle) return true
  return values.some((value) => String(value ?? "").toLowerCase().includes(needle))
}

export function ManagerSearch({ value, onChange, placeholder, clearLabel, countLabel, matched, total }) {
  return (
    <div className="manager-search">
      <input
        type="text"
        className="manager-search-input"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      {value ? (
        <button type="button" className="btn btn-compact" onClick={() => onChange("")}>
          {clearLabel}
        </button>
      ) : null}
      <span className="manager-search-meta">
        {countLabel} {matched}/{total}
      </span>
    </div>
  )
}

export function TokenLimitField({ label, value, presets, onChange, translate }) {
  const current = String(value ?? "").trim()

  return (
    <div className="token-field">
      <span className="token-field-label">{label}</span>
      <input
        type="text"
        inputMode="numeric"
        value={current}
        placeholder={translate("modelFormTokensDefault")}
        onChange={(event) => onChange(event.target.value.replace(/[^\d]/g, ""))}
      />
      <div className="token-presets">
        {presets.map((preset) => {
          const isActive = current === String(preset)
          return (
            <button
              key={preset}
              type="button"
              className={`token-preset ${isActive ? "active" : ""}`}
              onClick={() => onChange(isActive ? "" : String(preset))}
            >
              {formatTokenCount(preset)}
            </button>
          )
        })}
        <button
          type="button"
          className="token-preset token-preset-clear"
          disabled={!current}
          onClick={() => onChange("")}
        >
          {translate("modelFormTokensClear")}
        </button>
      </div>
      <span className="token-field-hint">
        {current ? `${current} tokens` : translate("modelFormTokensDefaultHint")}
      </span>
    </div>
  )
}

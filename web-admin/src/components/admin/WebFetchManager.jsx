import { useEffect, useState } from "react"

// The backends web_fetch knows how to call. ``needsKey`` mirrors the provider
// table in agent/tools/web_fetch/providers.py: the local fetcher needs none.
const FETCH_PROVIDERS = [
  { value: "builtin", label: "Built-in (local HTTP + Markdown)", needsKey: false },
  { value: "deepseek", label: "DeepSeek Fetch", needsKey: true },
]

export default function WebFetchManager({ config, onSave, translate }) {
  const [provider, setProvider] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [baseUrl, setBaseUrl] = useState("")
  const [busy, setBusy] = useState(false)

  const currentProvider = config?.provider || ""
  const currentKey = config?.api_key || ""
  const currentBaseUrl = config?.base_url || ""
  const changed =
    Boolean(config) &&
    (provider !== currentProvider || apiKey !== currentKey || baseUrl !== currentBaseUrl)

  useEffect(() => {
    if (!config) return
    setProvider(config.provider || "builtin")
    setApiKey(config.api_key || "")
    setBaseUrl(config.base_url || "")
  }, [config])

  const selected = FETCH_PROVIDERS.find((item) => item.value === provider)
  const keyMissing = Boolean(selected?.needsKey) && !apiKey.trim()

  const submit = async (event) => {
    event.preventDefault()
    if (!provider) return
    setBusy(true)
    try {
      await onSave({
        provider,
        api_key: apiKey.trim(),
        base_url: baseUrl.trim(),
      })
    } finally {
      setBusy(false)
    }
  }

  // Rendered as one tab of the tools page: the panel, its title and the refresh
  // button belong to that page, so only the backend form lives here.
  return (
    <div className="tool-tab-scroll">
      <div className="hint">
        {translate("webFetchCurrentSource")}:{" "}
        {config?.source === "database"
          ? translate("webFetchSourceDb")
          : translate("webFetchSourceEnv")}
      </div>
      <form className="form-grid" onSubmit={submit}>
        <label>
          <span>{translate("webFetchProvider")}</span>
          <select
            value={provider}
            disabled={!config}
            onChange={(event) => setProvider(event.target.value)}
          >
            {FETCH_PROVIDERS.map((item) => (
              <option value={item.value} key={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{translate("webFetchApiKey")}</span>
          <input
            type="password"
            autoComplete="new-password"
            value={apiKey}
            disabled={!config}
            placeholder={translate("webFetchApiKeyPlaceholder")}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </label>
        <label>
          <span>{translate("webFetchBaseUrl")}</span>
          <input
            type="url"
            value={baseUrl}
            disabled={!config}
            placeholder={translate("webFetchBaseUrlPlaceholder")}
            onChange={(event) => setBaseUrl(event.target.value)}
          />
        </label>
        <button type="submit" className="btn btn-primary" disabled={busy || !changed}>
          {busy ? translate("webFetchSaving") : translate("webFetchSave")}
        </button>
      </form>
      <div className="hint">{translate("webFetchHint")}</div>
      {selected?.needsKey ? (
        keyMissing ? <div className="hint">{translate("webFetchKeyMissing")}</div> : null
      ) : (
        <div className="hint">{translate("webFetchBuiltinHint")}</div>
      )}
      {provider === "deepseek" ? (
        <div className="hint">{translate("webFetchDeepseekHint")}</div>
      ) : null}
    </div>
  )
}

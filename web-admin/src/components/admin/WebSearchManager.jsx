import { useEffect, useState } from "react"

// The backends the tool knows how to call. ``needsKey`` mirrors the provider table
// in agent/tools/web_search/providers.py: only DuckDuckGo works without a signup.
const SEARCH_PROVIDERS = [
  { value: "duckduckgo", label: "DuckDuckGo (keyless)", needsKey: false },
  { value: "deepseek", label: "DeepSeek Search", needsKey: true },
  { value: "tavily", label: "Tavily", needsKey: true },
  { value: "serper", label: "Serper (Google)", needsKey: true },
  { value: "bing", label: "Bing Web Search", needsKey: true },
]

export default function WebSearchManager({ config, onSave, onRefresh, translate }) {
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
    setProvider(config.provider || "duckduckgo")
    setApiKey(config.api_key || "")
    setBaseUrl(config.base_url || "")
  }, [config])

  const selected = SEARCH_PROVIDERS.find((item) => item.value === provider)
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

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("webSearchTitle")}</h2>
          <span className="hint">
            {translate("webSearchCurrentSource")}:{" "}
            {config?.source === "database"
              ? translate("webSearchSourceDb")
              : translate("webSearchSourceEnv")}
          </span>
        </div>
        <button type="button" className="btn btn-compact" onClick={onRefresh}>
          {translate("webSearchRefresh")}
        </button>
      </div>
      <div className="panel-body">
        <form className="form-grid" onSubmit={submit}>
          <label>
            <span>{translate("webSearchProvider")}</span>
            <select
              value={provider}
              disabled={!config}
              onChange={(event) => setProvider(event.target.value)}
            >
              {SEARCH_PROVIDERS.map((item) => (
                <option value={item.value} key={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{translate("webSearchApiKey")}</span>
            <input
              type="password"
              autoComplete="new-password"
              value={apiKey}
              disabled={!config}
              placeholder={translate("webSearchApiKeyPlaceholder")}
              onChange={(event) => setApiKey(event.target.value)}
            />
          </label>
          <label>
            <span>{translate("webSearchBaseUrl")}</span>
            <input
              type="url"
              value={baseUrl}
              disabled={!config}
              placeholder={translate("webSearchBaseUrlPlaceholder")}
              onChange={(event) => setBaseUrl(event.target.value)}
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy || !changed}>
            {busy ? translate("webSearchSaving") : translate("webSearchSave")}
          </button>
        </form>
        <div className="hint">{translate("webSearchHint")}</div>
        {selected?.needsKey ? (
          keyMissing ? <div className="hint">{translate("webSearchKeyMissing")}</div> : null
        ) : (
          <div className="hint">{translate("webSearchKeyless")}</div>
        )}
      </div>
    </section>
  )
}

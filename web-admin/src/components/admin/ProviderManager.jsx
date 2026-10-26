import { useMemo, useState } from "react"
import Modal from "./Modal"
import { ManagerSearch, PROVIDER_PROTOCOL_OPTIONS, matchesKeyword } from "./shared"

// The endpoint needs a URL; the OpenAI-compatible adapter has a default one.
const BASE_URL_REQUIRED_PROTOCOLS = ["anthropic_compatible"]

function emptyProviderForm() {
  return {
    provider_id: "",
    name: "",
    protocol: PROVIDER_PROTOCOL_OPTIONS[0],
    base_url: "",
    api_key: "",
    rpm_limit: "",
  }
}

function providerToForm(provider) {
  return {
    provider_id: provider.provider_id,
    name: provider.name || "",
    protocol: provider.protocol || PROVIDER_PROTOCOL_OPTIONS[0],
    base_url: provider.base_url || "",
    api_key: provider.api_key || "",
    rpm_limit: provider.rpm_limit ? String(provider.rpm_limit) : "",
  }
}

export default function ProviderManager({ providers, onCreate, onUpdate, onDelete, onRefresh, translate }) {
  const [search, setSearch] = useState("")
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const editingId = form?.provider_id || ""

  const filtered = useMemo(
    () =>
      providers.filter((provider) =>
        matchesKeyword(search, provider.name, provider.protocol, provider.base_url)
      ),
    [providers, search]
  )

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }))

  const openCreate = () => {
    setError("")
    setForm(emptyProviderForm())
  }

  const openEdit = (provider) => {
    setError("")
    setForm(providerToForm(provider))
  }

  const closeModal = () => {
    if (busy) return
    setError("")
    setForm(null)
  }

  const submit = async (event) => {
    event.preventDefault()
    setError("")
    if (!form.name.trim()) {
      setError(translate("providerNameRequired"))
      return
    }
    if (BASE_URL_REQUIRED_PROTOCOLS.includes(form.protocol) && !form.base_url.trim()) {
      setError(translate("providerBaseUrlRequired"))
      return
    }
    setBusy(true)
    const payload = {
      name: form.name.trim(),
      protocol: form.protocol,
      base_url: form.base_url.trim(),
      api_key: form.api_key,
      rpm_limit: Number(form.rpm_limit) || 0,
    }
    try {
      if (editingId) {
        await onUpdate(editingId, payload)
      } else {
        await onCreate(payload)
      }
      setForm(null)
      setError("")
    } catch {
      // error surfaced through the global banner
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async (provider) => {
    if (!window.confirm(`${translate("providerDeleteConfirm")} (${provider.name})`)) return
    try {
      await onDelete(provider.provider_id)
    } catch {
      // error surfaced through the global banner
    }
  }

  return (
    <section className="panel model-manager">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("providerManagerTitle")}</h2>
          <span className="hint">{translate("providerManagerHint")}</span>
        </div>
        <div className="manager-toolbar-actions">
          <button type="button" className="btn btn-compact" onClick={onRefresh}>
            {translate("providerListRefresh")}
          </button>
          <button type="button" className="btn btn-compact btn-primary" onClick={openCreate}>
            {translate("providerFormCreate")}
          </button>
        </div>
      </div>
      <div className="panel-body">
        <ManagerSearch
          value={search}
          onChange={setSearch}
          placeholder={translate("providerSearchPlaceholder")}
          clearLabel={translate("managerSearchClear")}
          countLabel={translate("managerSearchResult")}
          matched={filtered.length}
          total={providers.length}
        />

        <div className="model-list">
          {filtered.length === 0 ? (
            <div className="empty">
              {providers.length === 0
                ? translate("providerListEmpty")
                : translate("managerSearchNoMatch")}
            </div>
          ) : (
            <table className="model-table">
              <thead>
                <tr>
                  <th>{translate("providerListName")}</th>
                  <th>{translate("providerListProtocol")}</th>
                  <th>{translate("providerListBaseUrl")}</th>
                  <th>{translate("providerListRpm")}</th>
                  <th>{translate("providerListModels")}</th>
                  <th>{translate("modelListActions")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((provider) => (
                  <tr key={provider.provider_id}>
                    <td className="model-name">{provider.name}</td>
                    <td>
                      <code>{provider.protocol}</code>
                    </td>
                    <td className="mono">{provider.base_url || "-"}</td>
                    <td className="mono">
                      {provider.rpm_limit > 0
                        ? provider.rpm_limit
                        : translate("providerRpmUnlimited")}
                    </td>
                    <td className="mono">{provider.model_count ?? 0}</td>
                    <td className="model-actions">
                      <button type="button" className="btn btn-xs" onClick={() => openEdit(provider)}>
                        {translate("modelEdit")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-danger btn-xs"
                        onClick={() => handleDelete(provider)}
                      >
                        {translate("modelDelete")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {form && (
        <Modal
          title={editingId ? translate("providerFormEdit") : translate("providerFormCreate")}
          closeLabel={translate("dialogClose")}
          onClose={closeModal}
        >
          <form className="form-grid" onSubmit={submit}>
            <label>
              <span>{translate("providerFormName")}</span>
              <input
                autoFocus
                value={form.name}
                onChange={(event) => setField("name", event.target.value)}
                placeholder={translate("providerFormNamePlaceholder")}
              />
            </label>
            <label>
              <span>{translate("providerFormProtocol")}</span>
              <select
                value={form.protocol}
                onChange={(event) => setField("protocol", event.target.value)}
              >
                {PROVIDER_PROTOCOL_OPTIONS.map((item) => (
                  <option value={item} key={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{translate("providerFormBaseUrl")}</span>
              <input
                value={form.base_url}
                onChange={(event) => setField("base_url", event.target.value)}
                placeholder={translate("providerFormBaseUrlPlaceholder")}
              />
            </label>
            <label>
              <span>{translate("providerFormApiKey")}</span>
              <input
                type="password"
                value={form.api_key}
                onChange={(event) => setField("api_key", event.target.value)}
                placeholder={translate("providerFormApiKeyPlaceholder")}
              />
            </label>
            <label>
              <span>{translate("providerFormRpm")}</span>
              <input
                type="number"
                min="0"
                step="1"
                value={form.rpm_limit}
                onChange={(event) => setField("rpm_limit", event.target.value)}
                placeholder={translate("providerFormRpmPlaceholder")}
              />
            </label>
            <div className="hint">{translate("providerRpmHint")}</div>
            {error && <div className="form-error">{error}</div>}
            <div className="model-form-actions">
              <button type="submit" className="btn btn-primary" disabled={busy}>
                {busy
                  ? translate("modelFormSaving")
                  : editingId
                    ? translate("modelFormUpdate")
                    : translate("providerFormSave")}
              </button>
              <button type="button" className="btn" onClick={closeModal} disabled={busy}>
                {translate("modelFormCancel")}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  )
}

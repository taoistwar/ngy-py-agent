import { useMemo, useState } from "react"
import Modal from "./Modal"
import {
  INPUT_TOKEN_PRESETS,
  ManagerSearch,
  OUTPUT_TOKEN_PRESETS,
  PROVIDER_OPTIONS,
  TokenLimitField,
  formatTokenCount,
  matchesKeyword,
} from "./shared"

function emptyModelForm() {
  return {
    model_id: "",
    name: "",
    provider: "openai-compatible",
    base_url: "",
    api_key: "",
    supports_tool_calls: true,
    supports_image_input: false,
    thinking_mode: false,
    max_input_tokens: "",
    max_output_tokens: "",
  }
}

function modelToForm(model) {
  return {
    model_id: model.model_id,
    name: model.name || "",
    provider: model.provider || "openai-compatible",
    base_url: model.base_url || "",
    api_key: model.api_key || "",
    supports_tool_calls: model.supports_tool_calls !== false,
    supports_image_input: model.supports_image_input === true,
    thinking_mode: model.thinking_mode === true,
    max_input_tokens: model.max_input_tokens ? String(model.max_input_tokens) : "",
    max_output_tokens: model.max_output_tokens ? String(model.max_output_tokens) : "",
  }
}

export default function ModelManager({ models, onCreate, onUpdate, onDelete, onRefresh, translate }) {
  const [search, setSearch] = useState("")
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const editingId = form?.model_id || ""

  const filtered = useMemo(
    () => models.filter((model) => matchesKeyword(search, model.name, model.provider, model.base_url)),
    [models, search]
  )

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }))

  const openCreate = () => {
    setError("")
    setForm(emptyModelForm())
  }

  const openEdit = (model) => {
    setError("")
    setForm(modelToForm(model))
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
      setError(translate("modelNameRequired"))
      return
    }
    setBusy(true)
    const payload = {
      name: form.name.trim(),
      provider: form.provider,
      base_url: form.base_url.trim(),
      api_key: form.api_key,
      supports_tool_calls: form.supports_tool_calls,
      supports_image_input: form.supports_image_input,
      thinking_mode: form.thinking_mode,
      max_input_tokens: Number(form.max_input_tokens) || 0,
      max_output_tokens: Number(form.max_output_tokens) || 0,
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

  const handleDelete = async (model) => {
    if (!window.confirm(`${translate("modelDeleteConfirm")} (${model.name})`)) return
    try {
      await onDelete(model.model_id)
    } catch {
      // error surfaced through the global banner
    }
  }

  return (
    <section className="panel model-manager">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("modelManagerTitle")}</h2>
          <span className="hint">{translate("modelManagerHint")}</span>
        </div>
        <div className="manager-toolbar-actions">
          <button type="button" className="btn btn-compact" onClick={onRefresh}>
            {translate("modelListRefresh")}
          </button>
          <button type="button" className="btn btn-compact" onClick={openCreate}>
            {translate("modelFormCreate")}
          </button>
        </div>
      </div>
      <div className="panel-body">
        <ManagerSearch
          value={search}
          onChange={setSearch}
          placeholder={translate("modelSearchPlaceholder")}
          clearLabel={translate("managerSearchClear")}
          countLabel={translate("managerSearchResult")}
          matched={filtered.length}
          total={models.length}
        />

        <div className="model-list">
          {filtered.length === 0 ? (
            <div className="empty">
              {models.length === 0 ? translate("modelListEmpty") : translate("managerSearchNoMatch")}
            </div>
          ) : (
            <table className="model-table">
              <thead>
                <tr>
                  <th>{translate("modelListName")}</th>
                  <th>{translate("modelListProvider")}</th>
                  <th>{translate("modelListBaseUrl")}</th>
                  <th>{translate("modelListToolCalls")}</th>
                  <th>{translate("modelListImageInput")}</th>
                  <th>{translate("modelListThinking")}</th>
                  <th>{translate("modelListTokens")}</th>
                  <th>{translate("modelListActions")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((model) => (
                  <tr key={model.model_id}>
                    <td className="model-name">{model.name}</td>
                    <td>
                      <code>{model.provider}</code>
                    </td>
                    <td className="mono">{model.base_url || "-"}</td>
                    <td className={model.supports_tool_calls ? "flag-on" : "flag-off"}>
                      {model.supports_tool_calls ? translate("yes") : translate("no")}
                    </td>
                    <td className={model.supports_image_input ? "flag-on" : "flag-off"}>
                      {model.supports_image_input ? translate("yes") : translate("no")}
                    </td>
                    <td className={model.thinking_mode ? "flag-on" : "flag-off"}>
                      {model.thinking_mode ? translate("yes") : translate("no")}
                    </td>
                    <td className="mono">
                      {model.max_input_tokens ? formatTokenCount(model.max_input_tokens) : "-"}/
                      {model.max_output_tokens ? formatTokenCount(model.max_output_tokens) : "-"}
                    </td>
                    <td className="model-actions">
                      <button type="button" className="btn btn-xs" onClick={() => openEdit(model)}>
                        {translate("modelEdit")}
                      </button>
                      <button type="button" className="btn btn-danger btn-xs" onClick={() => handleDelete(model)}>
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
          title={editingId ? translate("modelFormEdit") : translate("modelFormCreate")}
          closeLabel={translate("dialogClose")}
          onClose={closeModal}
        >
          <form className="form-grid" onSubmit={submit}>
            <label>
              <span>{translate("modelFormName")}</span>
              <input
                autoFocus
                value={form.name}
                onChange={(event) => setField("name", event.target.value)}
                placeholder={translate("modelFormNamePlaceholder")}
              />
            </label>
            <label>
              <span>{translate("modelFormProvider")}</span>
              <select value={form.provider} onChange={(event) => setField("provider", event.target.value)}>
                {PROVIDER_OPTIONS.map((item) => (
                  <option value={item} key={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{translate("modelFormBaseUrl")}</span>
              <input
                value={form.base_url}
                onChange={(event) => setField("base_url", event.target.value)}
                placeholder={translate("modelFormBaseUrlPlaceholder")}
              />
            </label>
            <label>
              <span>{translate("modelFormApiKey")}</span>
              <input
                type="password"
                value={form.api_key}
                onChange={(event) => setField("api_key", event.target.value)}
                placeholder={translate("modelFormApiKeyPlaceholder")}
              />
            </label>
            <div className="model-form-checks">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={form.supports_tool_calls}
                  onChange={(event) => setField("supports_tool_calls", event.target.checked)}
                />
                {translate("modelFormToolCalls")}
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={form.supports_image_input}
                  onChange={(event) => setField("supports_image_input", event.target.checked)}
                />
                {translate("modelFormImageInput")}
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={form.thinking_mode}
                  onChange={(event) => setField("thinking_mode", event.target.checked)}
                />
                {translate("modelFormThinking")}
              </label>
            </div>
            <div className="model-form-tokens">
              <TokenLimitField
                label={translate("modelFormMaxInput")}
                value={form.max_input_tokens}
                presets={INPUT_TOKEN_PRESETS}
                onChange={(value) => setField("max_input_tokens", value)}
                translate={translate}
              />
              <TokenLimitField
                label={translate("modelFormMaxOutput")}
                value={form.max_output_tokens}
                presets={OUTPUT_TOKEN_PRESETS}
                onChange={(value) => setField("max_output_tokens", value)}
                translate={translate}
              />
            </div>
            {error && <div className="form-error">{error}</div>}
            <div className="model-form-actions">
              <button type="submit" className="btn" disabled={busy}>
                {busy
                  ? translate("modelFormSaving")
                  : editingId
                    ? translate("modelFormUpdate")
                    : translate("modelFormSave")}
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

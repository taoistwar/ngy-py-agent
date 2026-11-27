// Page for the cross-session memory library (ADR 0035): what earlier conversations
// kept, and the switches that decide whether it is used at all. The same store the
// agent writes through ``memory_save`` is edited here, so a wrong note is recoverable.
import { useEffect, useMemo, useState } from "react"

const TYPES = ["user", "feedback", "project", "reference"]
const TYPE_LABEL_KEYS = {
  user: "memoryTypeUser",
  feedback: "memoryTypeFeedback",
  project: "memoryTypeProject",
  reference: "memoryTypeReference",
}

const EMPTY_DRAFT = { memory_id: "", name: "", type: "user", description: "", body: "" }

/** The editor is either adding (no id) or editing one stored note. */
function draftFrom(memory) {
  if (!memory) return { ...EMPTY_DRAFT }
  return {
    memory_id: memory.memory_id,
    name: memory.name || "",
    type: memory.type || "user",
    description: memory.description || "",
    body: memory.body || "",
  }
}

function updatedLabel(value) {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "-"
  return date.toLocaleString()
}

export default function MemoryManager({
  memories,
  config,
  onCreate,
  onUpdate,
  onDelete,
  onSaveConfig,
  onRefresh,
  translate,
}) {
  const [search, setSearch] = useState("")
  const [draft, setDraft] = useState(null)
  const [busy, setBusy] = useState("")
  const [formError, setFormError] = useState("")

  const [enabled, setEnabled] = useState(config?.enabled ?? true)
  const [autoExtract, setAutoExtract] = useState(config?.auto_extract ?? true)
  const [maxChars, setMaxChars] = useState(String(config?.max_prompt_chars ?? 4000))
  const [configBusy, setConfigBusy] = useState(false)
  const [configSaved, setConfigSaved] = useState(false)

  useEffect(() => {
    setEnabled(config?.enabled ?? true)
    setAutoExtract(config?.auto_extract ?? true)
    setMaxChars(String(config?.max_prompt_chars ?? 4000))
  }, [config])

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    if (!keyword) return memories
    return memories.filter((item) =>
      `${item.name || ""} ${item.description || ""} ${item.body || ""} ${item.type || ""}`
        .toLowerCase()
        .includes(keyword),
    )
  }, [memories, search])

  const openCreate = () => {
    setFormError("")
    setDraft({ ...EMPTY_DRAFT })
  }

  const openEdit = (memory) => {
    setFormError("")
    setDraft(draftFrom(memory))
  }

  const submit = async (event) => {
    event.preventDefault()
    setFormError("")
    const name = draft.name.trim()
    const body = draft.body.trim()
    if (!name) {
      setFormError(translate("memoryNameRequired"))
      return
    }
    if (!body) {
      setFormError(translate("memoryBodyRequired"))
      return
    }
    const payload = {
      name,
      type: draft.type,
      description: draft.description.trim(),
      body,
    }
    setBusy("form")
    try {
      if (draft.memory_id) {
        await onUpdate(draft.memory_id, payload)
      } else {
        await onCreate(payload)
      }
      setDraft(null)
    } catch (saveError) {
      setFormError(saveError?.message || translate("errorUnknown"))
    } finally {
      setBusy("")
    }
  }

  const remove = async (memory) => {
    if (!window.confirm(`${translate("memoryDeleteConfirm")} (${memory.name})`)) return
    setBusy(memory.memory_id)
    try {
      await onDelete(memory.memory_id)
    } catch {
      // error surfaced through the global banner
    } finally {
      setBusy("")
    }
  }

  const submitConfig = async (event) => {
    event.preventDefault()
    setConfigBusy(true)
    setConfigSaved(false)
    try {
      await onSaveConfig({
        enabled,
        auto_extract: autoExtract,
        max_prompt_chars: Number(maxChars) || 0,
      })
      setConfigSaved(true)
    } catch {
      // error surfaced through the global banner
    } finally {
      setConfigBusy(false)
    }
  }

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("memoryManagerTitle")}</h2>
          <span className="hint">{translate("memoryManagerHint")}</span>
        </div>
        <div className="task-toolbar-actions">
          <button type="button" className="btn btn-compact" onClick={onRefresh}>
            {translate("memoryListRefresh")}
          </button>
          <button type="button" className="btn btn-compact btn-primary" onClick={openCreate}>
            {translate("memoryNew")}
          </button>
        </div>
      </div>

      <div className="panel-body">
        <form className="model-form form-grid" onSubmit={submitConfig}>
          <p className="model-form-heading">{translate("memoryConfigTitle")}</p>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
            />
            {translate("memoryEnabled")}
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={autoExtract}
              onChange={(event) => setAutoExtract(event.target.checked)}
            />
            {translate("memoryAutoExtract")}
          </label>
          <label>
            <span>{translate("memoryMaxPromptChars")}</span>
            <input
              type="number"
              min="0"
              max="12000"
              value={maxChars}
              onChange={(event) => setMaxChars(event.target.value)}
            />
          </label>
          <div className="model-form-actions">
            <button type="submit" className="btn btn-primary" disabled={configBusy}>
              {configBusy ? translate("memorySaving") : translate("memoryConfigSave")}
            </button>
            {configSaved ? (
              <span className="hint">{translate("memoryConfigSaved")}</span>
            ) : (
              <span className="hint">
                {translate("memoryConfigSource")}: {config?.source || "-"}
              </span>
            )}
          </div>
        </form>

        {draft ? (
          <form className="model-form form-grid" onSubmit={submit}>
            <p className="model-form-heading">
              {draft.memory_id ? translate("memoryEdit") : translate("memoryNew")}
            </p>
            <label>
              <span>{translate("memoryName")}</span>
              <input
                value={draft.name}
                placeholder={translate("memoryNamePlaceholder")}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
            </label>
            <label>
              <span>{translate("memoryType")}</span>
              <select
                value={draft.type}
                onChange={(event) => setDraft({ ...draft, type: event.target.value })}
              >
                {TYPES.map((type) => (
                  <option key={type} value={type}>
                    {translate(TYPE_LABEL_KEYS[type])}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{translate("memoryDescription")}</span>
              <input
                value={draft.description}
                placeholder={translate("memoryDescriptionPlaceholder")}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              />
            </label>
            <label>
              <span>{translate("memoryBody")}</span>
              <textarea
                rows={5}
                value={draft.body}
                placeholder={translate("memoryBodyPlaceholder")}
                onChange={(event) => setDraft({ ...draft, body: event.target.value })}
              />
            </label>
            {formError ? <div className="form-error">{formError}</div> : null}
            <div className="model-form-actions">
              <button type="submit" className="btn btn-primary" disabled={busy === "form"}>
                {busy === "form" ? translate("memorySaving") : translate("memorySave")}
              </button>
              <button type="button" className="btn btn-compact" onClick={() => setDraft(null)}>
                {translate("memoryCancel")}
              </button>
            </div>
          </form>
        ) : null}

        <div className="task-search-bar">
          <input
            type="text"
            className="task-search-input"
            value={search}
            placeholder={translate("memorySearchPlaceholder")}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>

        <div className="model-list">
          {filtered.length === 0 ? (
            <div className="empty">{translate("memoryListEmpty")}</div>
          ) : (
            <table className="model-table">
              <thead>
                <tr>
                  <th>{translate("memoryListName")}</th>
                  <th>{translate("memoryListType")}</th>
                  <th>{translate("memoryListDescription")}</th>
                  <th>{translate("memoryListUpdated")}</th>
                  <th>{translate("modelListActions")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((memory) => (
                  <tr key={memory.memory_id}>
                    <td className="model-name mono">{memory.name}</td>
                    <td>{translate(TYPE_LABEL_KEYS[memory.type] || "memoryTypeUser")}</td>
                    <td>{memory.description || "-"}</td>
                    <td>{updatedLabel(memory.updated_at)}</td>
                    <td className="model-actions">
                      <button
                        type="button"
                        className="btn btn-compact btn-xs"
                        onClick={() => openEdit(memory)}
                      >
                        {translate("memoryEditAction")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-danger btn-xs"
                        disabled={busy === memory.memory_id}
                        onClick={() => remove(memory)}
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
        <div className="hint">{translate("memoryHint")}</div>
      </div>
    </section>
  )
}

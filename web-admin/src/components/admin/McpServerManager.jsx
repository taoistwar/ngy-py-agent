import { useMemo, useState } from "react"
import Modal from "./Modal"
import { MCP_TRANSPORT_OPTIONS, ManagerSearch, matchesKeyword } from "./shared"

function emptyMcpForm() {
  return { mcp_id: "", name: "", description: "", transport: MCP_TRANSPORT_OPTIONS[0], target: "" }
}

function serverToForm(server) {
  return {
    mcp_id: server.mcp_id,
    name: server.name || "",
    description: server.description || "",
    transport: server.transport || MCP_TRANSPORT_OPTIONS[0],
    target: server.target || "",
  }
}

export default function McpServerManager({ servers, onCreate, onUpdate, onDelete, onRefresh, translate }) {
  const [search, setSearch] = useState("")
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const editingId = form?.mcp_id || ""

  const filtered = useMemo(
    () =>
      servers.filter((server) =>
        matchesKeyword(search, server.name, server.description, server.transport, server.target)
      ),
    [servers, search]
  )

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }))

  const openCreate = () => {
    setError("")
    setForm(emptyMcpForm())
  }

  const openEdit = (server) => {
    setError("")
    setForm(serverToForm(server))
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
      setError(translate("mcpNameRequired"))
      return
    }
    if (!form.target.trim()) {
      setError(translate("mcpTargetRequired"))
      return
    }
    setBusy(true)
    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
      transport: form.transport,
      target: form.target.trim(),
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

  const handleDelete = async (server) => {
    if (!window.confirm(`${translate("mcpDeleteConfirm")} (${server.name})`)) return
    try {
      await onDelete(server.mcp_id)
    } catch {
      // error surfaced through the global banner
    }
  }

  return (
    <section className="panel model-manager">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("mcpManagerTitle")}</h2>
          <span className="hint">{translate("mcpManagerHint")}</span>
        </div>
        <div className="manager-toolbar-actions">
          <button type="button" className="btn btn-compact" onClick={onRefresh}>
            {translate("mcpListRefresh")}
          </button>
          <button type="button" className="btn btn-compact" onClick={openCreate}>
            {translate("mcpFormCreate")}
          </button>
        </div>
      </div>
      <div className="panel-body">
        <ManagerSearch
          value={search}
          onChange={setSearch}
          placeholder={translate("mcpSearchPlaceholder")}
          clearLabel={translate("managerSearchClear")}
          countLabel={translate("managerSearchResult")}
          matched={filtered.length}
          total={servers.length}
        />

        <div className="model-list">
          {filtered.length === 0 ? (
            <div className="empty">
              {servers.length === 0 ? translate("mcpListEmpty") : translate("managerSearchNoMatch")}
            </div>
          ) : (
            <table className="model-table">
              <thead>
                <tr>
                  <th>{translate("mcpListName")}</th>
                  <th>{translate("mcpListTransport")}</th>
                  <th>{translate("mcpListTarget")}</th>
                  <th>{translate("mcpListDescription")}</th>
                  <th>{translate("modelListActions")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((server) => (
                  <tr key={server.mcp_id}>
                    <td className="model-name">{server.name}</td>
                    <td>
                      <code>{server.transport}</code>
                    </td>
                    <td className="mono">{server.target || "-"}</td>
                    <td>{server.description || "-"}</td>
                    <td className="model-actions">
                      <button type="button" className="btn btn-xs" onClick={() => openEdit(server)}>
                        {translate("modelEdit")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-danger btn-xs"
                        onClick={() => handleDelete(server)}
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
          title={editingId ? translate("mcpFormEdit") : translate("mcpFormCreate")}
          closeLabel={translate("dialogClose")}
          onClose={closeModal}
        >
          <form className="form-grid" onSubmit={submit}>
            <label>
              <span>{translate("mcpFormName")}</span>
              <input
                autoFocus
                value={form.name}
                onChange={(event) => setField("name", event.target.value)}
                placeholder={translate("mcpFormNamePlaceholder")}
              />
            </label>
            <label>
              <span>{translate("mcpFormDescription")}</span>
              <input
                value={form.description}
                onChange={(event) => setField("description", event.target.value)}
                placeholder={translate("mcpFormDescriptionPlaceholder")}
              />
            </label>
            <label>
              <span>{translate("mcpFormTransport")}</span>
              <select
                value={form.transport}
                onChange={(event) => setField("transport", event.target.value)}
              >
                {MCP_TRANSPORT_OPTIONS.map((transport) => (
                  <option value={transport} key={transport}>
                    {transport}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{translate("mcpFormTarget")}</span>
              <input
                value={form.target}
                onChange={(event) => setField("target", event.target.value)}
                placeholder={translate("mcpFormTargetPlaceholder")}
              />
            </label>
            {error && <div className="form-error">{error}</div>}
            <div className="model-form-actions">
              <button type="submit" className="btn" disabled={busy}>
                {busy
                  ? translate("modelFormSaving")
                  : editingId
                    ? translate("mcpFormUpdate")
                    : translate("mcpFormSave")}
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

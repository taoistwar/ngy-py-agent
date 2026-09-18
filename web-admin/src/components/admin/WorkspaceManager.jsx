import { useMemo, useState } from "react"
import Modal from "./Modal"
import { ManagerSearch, matchesKeyword } from "./shared"

function emptyWorkspaceForm() {
  return { workspace_id: "", name: "", root_path: "" }
}

export default function WorkspaceManager({ workspaces, onCreate, onUpdate, onDelete, onRefresh, translate }) {
  const [search, setSearch] = useState("")
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const editingId = form?.workspace_id || ""

  const filtered = useMemo(
    () => workspaces.filter((workspace) => matchesKeyword(search, workspace.name, workspace.root_path)),
    [workspaces, search]
  )

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }))

  const openCreate = () => {
    setError("")
    setForm(emptyWorkspaceForm())
  }

  const openEdit = (workspace) => {
    setError("")
    setForm({
      workspace_id: workspace.workspace_id,
      name: workspace.name || "",
      root_path: workspace.root_path || "",
    })
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
      setError(translate("workspaceNameRequired"))
      return
    }
    if (!form.root_path.trim()) {
      setError(translate("workspaceRootRequired"))
      return
    }
    setBusy(true)
    const payload = { name: form.name.trim(), root_path: form.root_path.trim() }
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

  const handleDelete = async (workspace) => {
    if (!window.confirm(`${translate("workspaceDeleteConfirm")} (${workspace.name})`)) return
    try {
      await onDelete(workspace.workspace_id)
    } catch {
      // error surfaced through the global banner
    }
  }

  return (
    <section className="panel model-manager">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("workspaceManagerTitle")}</h2>
          <span className="hint">{translate("workspaceManagerHint")}</span>
        </div>
        <div className="manager-toolbar-actions">
          <button type="button" className="btn btn-compact" onClick={onRefresh}>
            {translate("workspaceListRefresh")}
          </button>
          <button type="button" className="btn btn-compact" onClick={openCreate}>
            {translate("workspaceFormCreate")}
          </button>
        </div>
      </div>
      <div className="panel-body">
        <ManagerSearch
          value={search}
          onChange={setSearch}
          placeholder={translate("workspaceSearchPlaceholder")}
          clearLabel={translate("managerSearchClear")}
          countLabel={translate("managerSearchResult")}
          matched={filtered.length}
          total={workspaces.length}
        />

        <div className="model-list">
          {filtered.length === 0 ? (
            <div className="empty">
              {workspaces.length === 0 ? translate("workspaceListEmpty") : translate("managerSearchNoMatch")}
            </div>
          ) : (
            <table className="model-table">
              <thead>
                <tr>
                  <th>{translate("workspaceListName")}</th>
                  <th>{translate("workspaceListRoot")}</th>
                  <th>{translate("workspaceListSessions")}</th>
                  <th>{translate("modelListActions")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((workspace) => (
                  <tr key={workspace.workspace_id}>
                    <td className="model-name">{workspace.name}</td>
                    <td className="mono">{workspace.root_path}</td>
                    <td>{workspace.session_count || 0}</td>
                    <td className="model-actions">
                      <button type="button" className="btn btn-xs" onClick={() => openEdit(workspace)}>
                        {translate("modelEdit")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-danger btn-xs"
                        onClick={() => handleDelete(workspace)}
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
          title={editingId ? translate("workspaceFormEdit") : translate("workspaceFormCreate")}
          closeLabel={translate("dialogClose")}
          onClose={closeModal}
        >
          <form className="form-grid" onSubmit={submit}>
            <label>
              <span>{translate("workspaceFormName")}</span>
              <input
                autoFocus
                value={form.name}
                onChange={(event) => setField("name", event.target.value)}
                placeholder={translate("workspaceFormNamePlaceholder")}
              />
            </label>
            <label>
              <span>{translate("workspaceFormRoot")}</span>
              <input
                value={form.root_path}
                onChange={(event) => setField("root_path", event.target.value)}
                placeholder={translate("workspaceFormRootPlaceholder")}
              />
            </label>
            {error && <div className="form-error">{error}</div>}
            <div className="model-form-actions">
              <button type="submit" className="btn" disabled={busy}>
                {busy
                  ? translate("modelFormSaving")
                  : editingId
                    ? translate("workspaceFormUpdate")
                    : translate("workspaceFormSave")}
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

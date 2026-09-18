import { useEffect, useMemo, useState } from "react"

export default function SkillManager({ skills, skillsRoot, onSaveRoot, onImport, onDelete, onRefresh, translate }) {
  const [rootInput, setRootInput] = useState(skillsRoot || "")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [search, setSearch] = useState("")

  useEffect(() => {
    setRootInput(skillsRoot || "")
  }, [skillsRoot])

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    if (!keyword) return skills
    return skills.filter((item) =>
      `${item.display_name || ""} ${item.name || ""} ${item.description || ""}`
        .toLowerCase()
        .includes(keyword)
    )
  }, [skills, search])

  const saveRoot = async (event) => {
    event.preventDefault()
    setError("")
    setBusy(true)
    try {
      await onSaveRoot(rootInput.trim())
    } catch {
      // error surfaced through the global banner
    } finally {
      setBusy(false)
    }
  }

  const handleImport = async () => {
    const source = window.prompt(translate("skillImportPrompt"), "")
    if (source === null) return
    const value = source.trim()
    if (!value) return
    try {
      await onImport(value)
    } catch {
      // error surfaced through the global banner
    }
  }

  const handleDelete = async (skill) => {
    const label = skill.display_name || skill.name
    if (!window.confirm(`${translate("skillDeleteConfirm")} (${label})`)) return
    try {
      await onDelete(skill.name)
    } catch {
      // error surfaced through the global banner
    }
  }

  return (
    <section className="panel model-manager">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("skillManagerTitle")}</h2>
          <span className="hint">{translate("skillManagerHint")}</span>
        </div>
        <div className="task-toolbar-actions">
          <button type="button" className="btn btn-compact" onClick={onRefresh}>
            {translate("skillListRefresh")}
          </button>
          <button type="button" className="btn btn-compact" onClick={handleImport}>
            {translate("skillImport")}
          </button>
        </div>
      </div>
      <div className="panel-body">
        <form className="model-form form-grid" onSubmit={saveRoot}>
          <p className="model-form-heading">{translate("skillRootTitle")}</p>
          <label>
            <span>{translate("skillRootLabel")}</span>
            <input
              value={rootInput}
              onChange={(event) => setRootInput(event.target.value)}
              placeholder={translate("skillRootPlaceholder")}
            />
          </label>
          {error && <div className="form-error">{error}</div>}
          <div className="model-form-actions">
            <button type="submit" className="btn" disabled={busy}>
              {busy ? translate("modelFormSaving") : translate("skillRootSave")}
            </button>
          </div>
        </form>

        <div className="task-search-bar">
          <input
            type="text"
            className="task-search-input"
            value={search}
            placeholder={translate("skillSearchPlaceholder")}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>

        <div className="model-list">
          {filtered.length === 0 ? (
            <div className="empty">{translate("skillListEmpty")}</div>
          ) : (
            <table className="model-table">
              <thead>
                <tr>
                  <th>{translate("skillListName")}</th>
                  <th>{translate("skillListDescription")}</th>
                  <th>{translate("skillListPath")}</th>
                  <th>{translate("modelListActions")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((skill) => (
                  <tr key={skill.name}>
                    <td className="model-name">{skill.display_name || skill.name}</td>
                    <td>{skill.description || "-"}</td>
                    <td className="mono">{skill.path}</td>
                    <td className="model-actions">
                      <button
                        type="button"
                        className="btn btn-danger btn-xs"
                        onClick={() => handleDelete(skill)}
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
    </section>
  )
}

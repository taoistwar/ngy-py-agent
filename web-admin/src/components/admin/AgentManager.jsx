import { useEffect, useMemo, useState } from "react"
import AgentCheckList from "./AgentCheckList"
import { AgentMcpDetail, AgentSkillDetail, AgentToolDetail } from "./AgentDetail"
import Modal from "./Modal"
import { buildMcpItems, resolveMcpServers, splitAgentMcpServers } from "./agentMcpSelection"
import { ManagerSearch, agentDisplayName, matchesKeyword } from "./shared"

// Hint shown in the shared detail dialog, keyed by the selected row type.
const DETAIL_HINT_KEYS = {
  tool: "agentToolDetailHint",
  skill: "agentSkillDetailHint",
  mcp: "agentMcpDetailHint",
}

function emptyAgentForm() {
  return {
    agent_id: "",
    name: "",
    description: "",
    system_prompt: "",
    use_all_tools: true,
    tool_names: [],
    skill_names: [],
    mcp_selection: [],
  }
}

function buildAgentForm(agent, servers) {
  const { selection, legacy } = splitAgentMcpServers(agent, servers)
  return {
    form: {
      agent_id: agent.agent_id,
      name: agent.name || "",
      description: agent.description || "",
      system_prompt: agent.system_prompt || "",
      use_all_tools: agent.tool_names === null || agent.tool_names === undefined,
      tool_names: Array.isArray(agent.tool_names) ? [...agent.tool_names] : [],
      skill_names: Array.isArray(agent.skill_names) ? [...agent.skill_names] : [],
      mcp_selection: selection,
    },
    legacyMcp: legacy,
  }
}

export default function AgentManager({
  agents,
  meta,
  createSignal,
  mcpServers,
  onManageMcp,
  onCreate,
  onUpdate,
  onDelete,
  onRefresh,
  translate,
}) {
  const tools = meta?.tools || []
  const builtinSkills = meta?.skills || []
  const librarySkills = meta?.library_skills || []

  const [search, setSearch] = useState("")
  const [form, setForm] = useState(null)
  const [legacyMcp, setLegacyMcp] = useState([])
  const [detail, setDetail] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const editingId = form?.agent_id || ""

  const toolItems = useMemo(
    () =>
      tools.map((tool) => ({
        id: tool.name,
        title: tool.name,
        description: tool.description,
        payload: tool,
      })),
    [tools]
  )

  const skillItems = useMemo(() => {
    const builtin = builtinSkills.map((skill) => ({
      id: skill.name,
      title: skill.label || skill.name,
      description: skill.instruction,
      badge: translate("agentBuiltin"),
      badgeClass: "badge-builtin",
      payload: { kind: "builtin", skill },
    }))
    const builtinNames = new Set(builtin.map((item) => item.id))
    // A skill folder may shadow a built-in skill name; the built-in one wins
    // because ``skill_names`` is a flat namespace resolved against the registry.
    const library = librarySkills
      .filter((skill) => !builtinNames.has(skill.name))
      .map((skill) => ({
        id: skill.name,
        title: skill.display_name || skill.name,
        description: skill.description,
        badge: translate("agentSkillLibrary"),
        badgeClass: "badge-library",
        payload: { kind: "library", skill },
      }))
    return [...builtin, ...library]
  }, [builtinSkills, librarySkills, translate])

  const mcpItems = useMemo(
    () => buildMcpItems(mcpServers, legacyMcp, translate),
    [mcpServers, legacyMcp, translate]
  )

  const filtered = useMemo(
    () =>
      agents.filter((agent) =>
        matchesKeyword(
          search,
          agentDisplayName(agent, translate),
          agent.description,
          (agent.tool_names || []).join(" "),
          (agent.skill_names || []).join(" ")
        )
      ),
    [agents, search, translate]
  )

  useEffect(() => {
    if (createSignal > 0) {
      setError("")
      setDetail(null)
      setLegacyMcp([])
      setForm(emptyAgentForm())
    }
  }, [createSignal])

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }))

  const openCreate = () => {
    setError("")
    setDetail(null)
    setLegacyMcp([])
    setForm(emptyAgentForm())
  }

  const openEdit = (agent) => {
    const next = buildAgentForm(agent, mcpServers)
    setError("")
    setDetail(null)
    setLegacyMcp(next.legacyMcp)
    setForm(next.form)
  }

  const closeModal = () => {
    if (busy) return
    setError("")
    setDetail(null)
    setLegacyMcp([])
    setForm(null)
  }

  const toggleTool = (name) => {
    setForm((prev) => {
      // Unchecking a single tool while "use all tools" is on switches the form to
      // an explicit allow list that keeps every other tool selected.
      if (prev.use_all_tools) {
        return {
          ...prev,
          use_all_tools: false,
          tool_names: tools.map((tool) => tool.name).filter((item) => item !== name),
        }
      }
      return {
        ...prev,
        tool_names: prev.tool_names.includes(name)
          ? prev.tool_names.filter((item) => item !== name)
          : [...prev.tool_names, name],
      }
    })
  }

  const toggleSkill = (name) => {
    setForm((prev) => ({
      ...prev,
      skill_names: prev.skill_names.includes(name)
        ? prev.skill_names.filter((item) => item !== name)
        : [...prev.skill_names, name],
    }))
  }

  const toggleMcp = (id) => {
    setForm((prev) => ({
      ...prev,
      mcp_selection: prev.mcp_selection.includes(id)
        ? prev.mcp_selection.filter((item) => item !== id)
        : [...prev.mcp_selection, id],
    }))
  }

  const submit = async (event) => {
    event.preventDefault()
    setError("")
    if (!form.name.trim()) {
      setError(translate("agentNameRequired"))
      return
    }
    const selectedMcp = resolveMcpServers(form.mcp_selection, mcpServers, legacyMcp)
    setBusy(true)
    const payload = {
      name: form.name.trim(),
      description: form.description,
      system_prompt: form.system_prompt,
      tool_names: form.use_all_tools ? null : form.tool_names,
      skill_names: form.skill_names,
      mcp_servers: selectedMcp,
    }
    try {
      if (editingId) {
        await onUpdate(editingId, payload)
      } else {
        await onCreate(payload)
      }
      setDetail(null)
      setForm(null)
      setError("")
    } catch {
      // error surfaced through the global banner
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async (agent) => {
    if (!window.confirm(`${translate("agentDeleteConfirm")} (${agentDisplayName(agent, translate)})`)) {
      return
    }
    try {
      await onDelete(agent.agent_id)
    } catch {
      // error surfaced through the global banner
    }
  }

  return (
    <section className="panel model-manager">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("agentManagerTitle")}</h2>
          <span className="hint">{translate("agentManagerHint")}</span>
        </div>
        <div className="manager-toolbar-actions">
          <button type="button" className="btn btn-compact" onClick={onRefresh}>
            {translate("agentListRefresh")}
          </button>
          <button type="button" className="btn btn-compact" onClick={openCreate}>
            {translate("agentFormCreate")}
          </button>
        </div>
      </div>
      <div className="panel-body">
        <ManagerSearch
          value={search}
          onChange={setSearch}
          placeholder={translate("agentSearchPlaceholder")}
          clearLabel={translate("managerSearchClear")}
          countLabel={translate("managerSearchResult")}
          matched={filtered.length}
          total={agents.length}
        />

        <div className="model-list">
          {filtered.length === 0 ? (
            <div className="empty">
              {agents.length === 0 ? translate("agentListEmpty") : translate("managerSearchNoMatch")}
            </div>
          ) : (
            <table className="model-table">
              <thead>
                <tr>
                  <th>{translate("agentListName")}</th>
                  <th>{translate("agentListTools")}</th>
                  <th>{translate("agentListSkills")}</th>
                  <th>{translate("agentListMcp")}</th>
                  <th>{translate("modelListActions")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((agent) => (
                  <tr key={agent.agent_id}>
                    <td className="model-name">
                      {agentDisplayName(agent, translate)}
                      {agent.is_builtin && (
                        <span className="badge badge-builtin">{translate("agentBuiltin")}</span>
                      )}
                    </td>
                    <td className="mono">
                      {agent.tool_names === null
                        ? translate("agentAllTools")
                        : (agent.tool_names || []).join(", ") || "-"}
                    </td>
                    <td className="mono">{(agent.skill_names || []).join(", ") || "-"}</td>
                    <td className="mono">{(agent.mcp_servers || []).length || "-"}</td>
                    <td className="model-actions">
                      <button type="button" className="btn btn-xs" onClick={() => openEdit(agent)}>
                        {translate("modelEdit")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-danger btn-xs"
                        onClick={() => handleDelete(agent)}
                        disabled={agent.is_builtin}
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
          wide
          dismissible={!detail}
          title={editingId ? translate("agentFormEdit") : translate("agentFormCreate")}
          closeLabel={translate("dialogClose")}
          onClose={closeModal}
        >
          <form className="form-grid agent-form" onSubmit={submit}>
            <label>
              <span>{translate("agentFormName")}</span>
              <input
                autoFocus
                value={form.name}
                onChange={(event) => setField("name", event.target.value)}
                placeholder={translate("agentFormNamePlaceholder")}
              />
            </label>
            <label>
              <span>{translate("agentFormDescription")}</span>
              <input
                value={form.description}
                onChange={(event) => setField("description", event.target.value)}
                placeholder={translate("agentFormDescriptionPlaceholder")}
              />
            </label>
            <label className="agent-prompt-field">
              <span>{translate("agentFormPrompt")}</span>
              <textarea
                value={form.system_prompt}
                onChange={(event) => setField("system_prompt", event.target.value)}
                rows={6}
              />
            </label>

            <div className="agent-section">
              <div className="agent-section-head">
                <span>{translate("agentFormTools")}</span>
                <div className="agent-section-actions">
                  <span className="hint">
                    {form.use_all_tools
                      ? translate("agentAllTools")
                      : `${form.tool_names.length}/${tools.length}`}
                  </span>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={form.use_all_tools}
                      onChange={(event) => setField("use_all_tools", event.target.checked)}
                    />
                    {translate("agentFormAllTools")}
                  </label>
                </div>
              </div>
              <AgentCheckList
                items={toolItems}
                selectedIds={form.use_all_tools ? toolItems.map((item) => item.id) : form.tool_names}
                disabled={false}
                onToggle={toggleTool}
                onShowDetail={(item) => setDetail({ type: "tool", item })}
                emptyLabel={translate("agentNoTools")}
                detailLabel={translate("agentToolDetail")}
                fallbackDescription={translate("agentToolNoDescription")}
              />
            </div>

            <div className="agent-section">
              <div className="agent-section-head">
                <span>{translate("agentFormSkills")}</span>
                <span className="hint">
                  {`${form.skill_names.length}/${skillItems.length}`}
                </span>
              </div>
              <AgentCheckList
                items={skillItems}
                selectedIds={form.skill_names}
                disabled={false}
                onToggle={toggleSkill}
                onShowDetail={(item) => setDetail({ type: "skill", item })}
                emptyLabel={translate("agentNoSkills")}
                detailLabel={translate("agentToolDetail")}
                fallbackDescription={translate("agentToolNoDescription")}
              />
              <p className="hint">{translate("agentSkillHint")}</p>
            </div>

            <div className="agent-section">
              <div className="agent-section-head">
                <span>{translate("agentFormMcp")}</span>
                <div className="agent-section-actions">
                  <span className="hint">
                    {`${form.mcp_selection.length}/${mcpItems.length}`}
                  </span>
                  {onManageMcp ? (
                    <button type="button" className="btn btn-xs" onClick={onManageMcp}>
                      {translate("agentMcpManage")}
                    </button>
                  ) : null}
                </div>
              </div>
              <AgentCheckList
                items={mcpItems}
                selectedIds={form.mcp_selection}
                disabled={false}
                onToggle={toggleMcp}
                onShowDetail={(item) => setDetail({ type: "mcp", item })}
                emptyLabel={translate("agentMcpEmpty")}
                detailLabel={translate("agentToolDetail")}
                fallbackDescription={translate("agentToolNoDescription")}
              />
              <p className="hint">{translate("agentMcpHint")}</p>
            </div>

            {error && <div className="form-error">{error}</div>}
            <div className="model-form-actions">
              <button type="submit" className="btn" disabled={busy}>
                {busy
                  ? translate("modelFormSaving")
                  : editingId
                    ? translate("agentFormUpdate")
                    : translate("agentFormSave")}
              </button>
              <button type="button" className="btn" onClick={closeModal} disabled={busy}>
                {translate("modelFormCancel")}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {detail && (
        <Modal
          wide
          title={detail.item.title}
          hint={translate(DETAIL_HINT_KEYS[detail.type])}
          closeLabel={translate("dialogClose")}
          onClose={() => setDetail(null)}
        >
          {detail.type === "tool" ? (
            <AgentToolDetail tool={detail.item.payload} translate={translate} />
          ) : detail.type === "skill" ? (
            <AgentSkillDetail
              kind={detail.item.payload.kind}
              skill={detail.item.payload.skill}
              translate={translate}
            />
          ) : (
            <AgentMcpDetail server={detail.item.payload} translate={translate} />
          )}
        </Modal>
      )}
    </section>
  )
}

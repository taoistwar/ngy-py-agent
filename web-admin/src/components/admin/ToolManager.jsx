import { useMemo, useState } from "react"
import { AgentToolDetail } from "./AgentDetail"
import Modal from "./Modal"
import { ManagerSearch, agentDisplayName, matchesKeyword } from "./shared"

// Confirmation kind -> locale key, mirroring PERMISSION_KINDS in
// agent/tools/permissions.py.
const PERMISSION_LABEL_KEYS = {
  none: "toolPermissionNone",
  read: "toolPermissionRead",
  write: "toolPermissionWrite",
  exec: "toolPermissionExec",
  computer: "toolPermissionComputer",
}

// Answers a tool's confirmation dialog may offer, mirroring SCOPES in
// agent/tools/permissions.py.
const SCOPE_LABEL_KEYS = {
  once: "toolScopeOnce",
  session: "toolScopeSession",
  always: "toolScopeAlways",
}

const DESCRIPTION_PREVIEW_CHARS = 140

function truncate(text, maxLength) {
  const value = String(text || "")
  if (value.length <= maxLength) return value
  return `${value.slice(0, maxLength - 1)}...`
}

function permissionLabel(permission, translate) {
  const key = PERMISSION_LABEL_KEYS[permission]
  return key ? translate(key) : String(permission || "none")
}

function parameterCount(tool) {
  const properties = tool?.parameters?.properties
  if (!properties || typeof properties !== "object") return 0
  return Object.keys(properties).length
}

function scopeSummary(tool, translate) {
  const scopes = Array.isArray(tool?.scopes) ? tool.scopes : []
  if (scopes.length === 0) return "-"
  return scopes
    .map((scope) => translate(SCOPE_LABEL_KEYS[scope] || scope))
    .join(" / ")
}

function resolveAgentNames(agentIds, agents, translate) {
  return (agentIds || []).map((agentId) => {
    const agent = (agents || []).find((item) => item.agent_id === agentId)
    return {
      id: agentId,
      label: agent ? agentDisplayName(agent, translate) : agentId,
    }
  })
}

function ToolDetail({ tool, agents, translate }) {
  const agentNames = resolveAgentNames(tool.agent_ids, agents, translate)

  return (
    <div className="agent-detail">
      <div className="agent-detail-meta">
        <span className="agent-detail-label">{translate("toolDetailPermission")}</span>
        <span className={`badge badge-permission-${tool.permission || "none"}`}>
          {permissionLabel(tool.permission, translate)}
        </span>
      </div>
      <div className="agent-detail-meta">
        <span className="agent-detail-label">{translate("toolDetailScopes")}</span>
        <span className="agent-detail-value">{scopeSummary(tool, translate)}</span>
      </div>
      <div className="agent-detail-meta">
        <span className="agent-detail-label">{translate("toolDetailSource")}</span>
        <code className="agent-detail-value">{tool.source || "-"}</code>
      </div>
      <div className="agent-detail-meta">
        <span className="agent-detail-label">{translate("toolDetailPreview")}</span>
        <span className="agent-detail-value">
          {tool.has_preview ? translate("yes") : translate("no")}
        </span>
      </div>
      <div className="agent-detail-meta">
        <span className="agent-detail-label">{translate("toolDetailAgents")}</span>
        {agentNames.length > 0 ? (
          agentNames.map((agent) => (
            <span className={`badge badge-mode-${agent.id}`} key={agent.id}>
              {agent.label}
            </span>
          ))
        ) : (
          <span className="hint">{translate("toolDetailNoAgents")}</span>
        )}
      </div>
      <AgentToolDetail tool={tool} translate={translate} />
    </div>
  )
}

export default function ToolManager({ tools, agents, onRefresh, translate }) {
  const [search, setSearch] = useState("")
  const [detailName, setDetailName] = useState("")

  const filtered = useMemo(
    () =>
      tools.filter((tool) =>
        matchesKeyword(
          search,
          tool.name,
          tool.description,
          (tool.agent_ids || []).join(" ")
        )
      ),
    [tools, search]
  )

  // The selection is a name, not the row object: the list is refreshed on a
  // timer, and the dialog has to show the new copy of the tool, not a snapshot.
  const detailTool = useMemo(
    () => tools.find((tool) => tool.name === detailName) || null,
    [tools, detailName]
  )

  return (
    <section className="panel model-manager">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("toolManagerTitle")}</h2>
          <span className="hint">{translate("toolManagerHint")}</span>
        </div>
        <div className="manager-toolbar-actions">
          <button type="button" className="btn btn-compact" onClick={onRefresh}>
            {translate("toolListRefresh")}
          </button>
        </div>
      </div>
      <div className="panel-body">
        <ManagerSearch
          value={search}
          onChange={setSearch}
          placeholder={translate("toolSearchPlaceholder")}
          clearLabel={translate("managerSearchClear")}
          countLabel={translate("managerSearchResult")}
          matched={filtered.length}
          total={tools.length}
        />

        <div className="model-list">
          {filtered.length === 0 ? (
            <div className="empty">
              {tools.length === 0 ? translate("toolListEmpty") : translate("managerSearchNoMatch")}
            </div>
          ) : (
            <table className="model-table">
              <thead>
                <tr>
                  <th>{translate("toolListName")}</th>
                  <th>{translate("toolListPermission")}</th>
                  <th>{translate("toolListParams")}</th>
                  <th>{translate("toolListAgents")}</th>
                  <th>{translate("modelListActions")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((tool) => {
                  const agentNames = resolveAgentNames(tool.agent_ids, agents, translate)
                  return (
                    <tr key={tool.name}>
                      <td>
                        <code>{tool.name}</code>
                        <div className="hint">
                          {truncate(tool.description, DESCRIPTION_PREVIEW_CHARS)}
                        </div>
                      </td>
                      <td>
                        <span className={`badge badge-permission-${tool.permission || "none"}`}>
                          {permissionLabel(tool.permission, translate)}
                        </span>
                      </td>
                      <td className="mono">{parameterCount(tool)}</td>
                      <td>
                        {agentNames.length === 0
                          ? "-"
                          : agentNames.map((agent) => agent.label).join(", ")}
                      </td>
                      <td className="model-actions">
                        <button
                          type="button"
                          className="btn btn-xs"
                          onClick={() => setDetailName(tool.name)}
                        >
                          {translate("toolDetail")}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {detailTool && (
        <Modal
          wide
          title={detailTool.name}
          hint={translate("toolDetailHint")}
          closeLabel={translate("dialogClose")}
          onClose={() => setDetailName("")}
        >
          <ToolDetail tool={detailTool} agents={agents} translate={translate} />
        </Modal>
      )}
    </section>
  )
}

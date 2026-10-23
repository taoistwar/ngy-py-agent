import { useMemo, useState } from "react"
import ToolDetailDialog from "./ToolDetailDialog"
import { ManagerSearch, matchesKeyword } from "./shared"
import {
  categoryLabel,
  groupTools,
  localizedText,
  parameterCount,
  permissionLabel,
  resolveAgentNames,
} from "./toolMeta"

const DESCRIPTION_PREVIEW_CHARS = 140

function truncate(text, maxLength) {
  const value = String(text || "")
  if (value.length <= maxLength) return value
  return `${value.slice(0, maxLength - 1)}...`
}

function ToolRow({ tool, agents, translate, locale, onOpen }) {
  const agentNames = resolveAgentNames(tool.agent_ids, agents, translate)
  // English always, the current locale's text underneath when it has one.
  const translation = localizedText(tool, locale)

  return (
    <tr>
      <td>
        <code>{tool.name}</code>
        <div className="hint">{truncate(tool.description, DESCRIPTION_PREVIEW_CHARS)}</div>
        {translation ? (
          <div className="tool-desc-i18n">
            {truncate(translation.description, DESCRIPTION_PREVIEW_CHARS)}
          </div>
        ) : null}
      </td>
      <td>
        <span className={`badge badge-permission-${tool.permission || "none"}`}>
          {permissionLabel(tool.permission, translate)}
        </span>
      </td>
      <td className="mono">{parameterCount(tool)}</td>
      <td>
        {agentNames.length === 0 ? "-" : agentNames.map((agent) => agent.label).join(", ")}
      </td>
      <td className="model-actions">
        <button type="button" className="btn btn-xs" onClick={onOpen}>
          {translate("toolDetail")}
        </button>
      </td>
    </tr>
  )
}

function ToolGroup({ group, agents, translate, locale, onOpen }) {
  return (
    <div className="tool-group">
      <div className="tool-group-head">
        <h3>{categoryLabel(group.category, translate)}</h3>
        <span className="hint">{group.tools.length}</span>
      </div>
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
          {group.tools.map((tool) => (
            <ToolRow
              key={tool.name}
              tool={tool}
              agents={agents}
              translate={translate}
              locale={locale}
              onOpen={() => onOpen(tool.name)}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function ToolManager({ tools, agents, locale, onRefresh, translate }) {
  const [search, setSearch] = useState("")
  const [detailName, setDetailName] = useState("")

  const filtered = useMemo(
    () =>
      tools.filter((tool) =>
        matchesKeyword(
          search,
          tool.name,
          tool.description,
          localizedText(tool, locale)?.description,
          (tool.agent_ids || []).join(" ")
        )
      ),
    [tools, search, locale]
  )

  const groups = useMemo(() => groupTools(filtered), [filtered])

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
            groups.map((group) => (
              <ToolGroup
                key={group.category}
                group={group}
                agents={agents}
                translate={translate}
                locale={locale}
                onOpen={setDetailName}
              />
            ))
          )}
        </div>
      </div>

      {detailTool && (
        // Keyed by name so switching tools remounts the form with that tool's
        // schema defaults instead of keeping the previous tool's arguments.
        <ToolDetailDialog
          key={detailTool.name}
          tool={detailTool}
          agents={agents}
          locale={locale}
          onClose={() => setDetailName("")}
          translate={translate}
        />
      )}
    </section>
  )
}

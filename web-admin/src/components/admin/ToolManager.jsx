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

function ToolRow({ tool, agents, translate, locale, showEnglish, onOpen }) {
  const agentNames = resolveAgentNames(tool.agent_ids, agents, translate)
  // One language per row, never both: the locale's text, the English source when
  // the page asks for it, and English as the fallback for a tool without a
  // translation. Which one this is is the toolbar toggle's business, not the row's.
  const translation = localizedText(tool, locale)
  const description =
    (showEnglish ? "" : translation?.description) ||
    tool.description ||
    translate("agentToolNoDescription")

  return (
    <tr>
      <td>
        <code>{tool.name}</code>
        <div className="hint">{truncate(description, DESCRIPTION_PREVIEW_CHARS)}</div>
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

function ToolGroup({ group, agents, translate, locale, showEnglish, onOpen }) {
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
              showEnglish={showEnglish}
              onOpen={() => onOpen(tool.name)}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function ToolManager({
  tools,
  agents,
  locale,
  showEnglish = false,
  onToggleLanguage,
  translate,
}) {
  const [search, setSearch] = useState("")
  const [detailName, setDetailName] = useState("")

  // Both languages stay searchable: the toggle changes what is shown, not what a
  // keyword can find.
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

  // Rendered as one tab of the tools page: the panel, its title and the refresh
  // button belong to that page, so only the inventory itself lives here.
  return (
    <>
      <div className="hint">{translate("toolManagerHint")}</div>
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
              showEnglish={showEnglish}
              onOpen={setDetailName}
            />
          ))
        )}
      </div>

      {detailTool && (
        // Keyed by name so switching tools remounts the form with that tool's
        // schema defaults instead of keeping the previous tool's arguments.
        <ToolDetailDialog
          key={detailTool.name}
          tool={detailTool}
          agents={agents}
          locale={locale}
          showEnglish={showEnglish}
          onToggleLanguage={onToggleLanguage}
          onClose={() => setDetailName("")}
          translate={translate}
        />
      )}
    </>
  )
}

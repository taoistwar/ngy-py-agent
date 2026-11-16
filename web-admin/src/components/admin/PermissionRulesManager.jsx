// Page for the "always allow" approvals remembered across tasks. A rule pins one tool
// to one exact target, so removing a rule is what makes the agent ask again.
import { useMemo, useState } from "react"
import { ManagerSearch, matchesKeyword } from "./shared"

// Remembered approvals pile up fast; keep one page short enough to scan.
const PAGE_SIZE = 10

function ruleKey(rule) {
  return `${rule.tool}|${rule.target}`
}

export default function PermissionRulesManager({ rules, onDelete, onRefresh, translate }) {
  const [busy, setBusy] = useState("")
  const [search, setSearch] = useState("")
  const [toolFilter, setToolFilter] = useState("")
  const [page, setPage] = useState(1)
  const list = rules?.rules || []

  // The dropdown is the command list of the rules themselves, so it never offers
  // a tool that has nothing to show.
  const toolOptions = useMemo(() => {
    const counts = new Map()
    list.forEach((rule) => {
      counts.set(rule.tool, (counts.get(rule.tool) || 0) + 1)
    })
    return [...counts.entries()].sort((left, right) => left[0].localeCompare(right[0]))
  }, [list])

  const filtered = useMemo(
    () =>
      list.filter(
        (rule) =>
          (!toolFilter || rule.tool === toolFilter) &&
          matchesKeyword(search, rule.tool, rule.target)
      ),
    [list, search, toolFilter]
  )

  // The list is refreshed on a timer, so the last page can disappear under us.
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageRules = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  const changeSearch = (value) => {
    setSearch(value)
    setPage(1)
  }

  const changeToolFilter = (value) => {
    setToolFilter(value)
    setPage(1)
  }

  const remove = async (rule) => {
    const key = ruleKey(rule)
    setBusy(key)
    try {
      await onDelete(rule.tool, rule.target)
    } finally {
      setBusy("")
    }
  }

  const renderList = () => {
    if (list.length === 0) {
      return <div className="hint">{translate("permissionRulesEmpty")}</div>
    }
    if (filtered.length === 0) {
      return <div className="hint">{translate("managerSearchNoMatch")}</div>
    }
    return (
      <>
        <ul className="permission-rule-list">
          {pageRules.map((rule) => (
            <li key={ruleKey(rule)}>
              <div className="permission-rule-body">
                <strong>{rule.tool}</strong>
                <code>{rule.target}</code>
              </div>
              <button
                type="button"
                className="btn btn-compact btn-danger"
                disabled={busy === ruleKey(rule)}
                onClick={() => remove(rule)}
              >
                {translate("permissionRulesRemove")}
              </button>
            </li>
          ))}
        </ul>
        {totalPages > 1 ? (
          <div className="permission-rule-pagination">
            <button
              type="button"
              className="btn btn-compact"
              onClick={() => setPage(currentPage - 1)}
              disabled={currentPage <= 1}
            >
              {translate("permissionRulesPrev")}
            </button>
            <span className="permission-rule-page-indicator">
              {translate("permissionRulesPage")} {currentPage} / {totalPages}
            </span>
            <button
              type="button"
              className="btn btn-compact"
              onClick={() => setPage(currentPage + 1)}
              disabled={currentPage >= totalPages}
            >
              {translate("permissionRulesNext")}
            </button>
          </div>
        ) : null}
      </>
    )
  }

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("permissionRulesPath")}</h2>
          <span className="hint">{rules?.path || ""}</span>
        </div>
        <button type="button" className="btn btn-compact" onClick={onRefresh}>
          {translate("sidebarQuickRefreshPermissionRules")}
        </button>
      </div>
      <div className="panel-body">
        <div className="permission-rule-toolbar">
          <ManagerSearch
            value={search}
            onChange={changeSearch}
            placeholder={translate("permissionRulesSearchPlaceholder")}
            clearLabel={translate("managerSearchClear")}
            countLabel={translate("managerSearchResult")}
            matched={filtered.length}
            total={list.length}
          />
          <select
            className="permission-rule-filter"
            value={toolFilter}
            onChange={(event) => changeToolFilter(event.target.value)}
          >
            <option value="">
              {translate("permissionRulesFilterAll")} ({list.length})
            </option>
            {toolOptions.map(([tool, count]) => (
              <option key={tool} value={tool}>
                {tool} ({count})
              </option>
            ))}
          </select>
        </div>
        {renderList()}
        <div className="hint">{translate("permissionRulesHint")}</div>
      </div>
    </section>
  )
}

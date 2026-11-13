// Page for the "always allow" approvals remembered across tasks. A rule pins one tool
// to one exact target, so removing a rule is what makes the agent ask again.
import { useState } from "react"

export default function PermissionRulesManager({ rules, onDelete, onRefresh, translate }) {
  const [busy, setBusy] = useState("")
  const list = rules?.rules || []

  const remove = async (rule) => {
    const key = `${rule.tool}|${rule.target}`
    setBusy(key)
    try {
      await onDelete(rule.tool, rule.target)
    } finally {
      setBusy("")
    }
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
        {list.length === 0 ? (
          <div className="hint">{translate("permissionRulesEmpty")}</div>
        ) : (
          <ul className="permission-rule-list">
            {list.map((rule) => (
              <li key={`${rule.tool}|${rule.target}`}>
                <div className="permission-rule-body">
                  <strong>{rule.tool}</strong>
                  <code>{rule.target}</code>
                </div>
                <button
                  type="button"
                  className="btn btn-compact btn-danger"
                  disabled={busy === `${rule.tool}|${rule.target}`}
                  onClick={() => remove(rule)}
                >
                  {translate("permissionRulesRemove")}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="hint">{translate("permissionRulesHint")}</div>
      </div>
    </section>
  )
}

// Page for the static deny-list (ADR 0024): a tool + argument combination listed
// here never runs and never asks. The rule is written to the same JSON file the
// tasks read, so a change takes effect on the next tool call, not on restart.
import { useState } from "react"

const MATCH_FIXED = "fixed"
const MATCH_REGEX = "regex"

const EMPTY_ARGUMENT = { field: "", match: MATCH_FIXED, value: "" }

/** The text one matcher compares against, as the file spells it. */
function specText(spec) {
  if (!spec) return ""
  return String(spec.match === MATCH_REGEX ? spec.pattern ?? "" : spec.value ?? "")
}

/** One line for the list: a regex is shown between slashes, like the file. */
function specLabel(spec) {
  const text = specText(spec)
  return spec?.match === MATCH_REGEX ? `/${text}/` : text
}

export default function DenyListManager({ denylist, tools, onCreate, onDelete, onRefresh, translate }) {
  const [tool, setTool] = useState("")
  const [toolMatch, setToolMatch] = useState(MATCH_FIXED)
  const [reason, setReason] = useState("")
  const [args, setArgs] = useState([{ ...EMPTY_ARGUMENT }])
  const [busy, setBusy] = useState("")
  const [formError, setFormError] = useState("")

  const rules = denylist?.rules || []
  const problems = denylist?.problems || []

  // Exact matches pick a registered tool from a list; a regex stays free text,
  // and an exact value that is not registered (hand-edited file) is kept so the
  // current input is never silently dropped from the select.
  const toolNames = (tools || []).map((item) => item.name).filter(Boolean)
  const exactChoices = tool && !toolNames.includes(tool) ? [tool, ...toolNames] : toolNames
  const pickTool = toolMatch === MATCH_FIXED && exactChoices.length > 0

  // Argument names come from the selected tool's schema. Switching tools drops a
  // row whose name the new tool does not declare, so the form cannot submit a
  // combination the tool would never receive.
  const selectedTool = toolNames.includes(tool)
    ? (tools || []).find((item) => item.name === tool)
    : null
  const parameterNames = Object.keys(selectedTool?.parameters?.properties || {})

  const chooseTool = (name) => {
    setTool(name)
    const nextTool = (tools || []).find((item) => item.name === name)
    const nextNames = Object.keys(nextTool?.parameters?.properties || {})
    if (nextNames.length === 0) return
    setArgs((current) =>
      current.map((item) => (nextNames.includes(item.field) ? item : { ...item, field: "" })),
    )
  }

  const updateArg = (index, patch) => {
    setArgs((current) =>
      current.map((item, position) => (position === index ? { ...item, ...patch } : item)),
    )
  }

  const submit = async (event) => {
    event.preventDefault()
    setFormError("")
    if (!tool.trim()) {
      setFormError(translate("denyListToolRequired"))
      return
    }
    // A blank row is "not used"; a half-filled one is a mistake, because a rule
    // that only half-matches is exactly the rule the user did not mean to write.
    const rows = args.filter((item) => item.field.trim() || item.value.trim())
    if (rows.some((item) => !item.field.trim() || !item.value.trim())) {
      setFormError(translate("denyListArgRequired"))
      return
    }

    setBusy("form")
    try {
      await onCreate({
        tool: tool.trim(),
        tool_match: toolMatch,
        args: rows.map((item) => ({
          field: item.field.trim(),
          match: item.match,
          value: item.value,
        })),
        reason: reason.trim(),
      })
      setTool("")
      setToolMatch(MATCH_FIXED)
      setReason("")
      setArgs([{ ...EMPTY_ARGUMENT }])
    } catch (createError) {
      setFormError(createError?.message || translate("errorUnknown"))
    } finally {
      setBusy("")
    }
  }

  const remove = async (rule) => {
    setBusy(rule.id)
    try {
      await onDelete(rule.id)
    } finally {
      setBusy("")
    }
  }

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("denyListTitle")}</h2>
          <span className="hint">
            {translate("denyListPath")}: {denylist?.path || ""}
          </span>
        </div>
        <button type="button" className="btn btn-compact" onClick={onRefresh}>
          {translate("sidebarQuickRefreshDenyList")}
        </button>
      </div>
      <div className="panel-body">
        {problems.length > 0 ? (
          <div className="deny-problems">
            <strong>{translate("denyListProblems")}</strong>
            <ul>
              {problems.map((problem) => (
                <li key={problem}>
                  <code>{problem}</code>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <form className="deny-form" onSubmit={submit}>
          <h3>{translate("denyListAddTitle")}</h3>
          <div className="deny-form-row">
            <label>
              <span>{translate("denyListTool")}</span>
              {pickTool ? (
                <select value={tool} onChange={(event) => chooseTool(event.target.value)}>
                  <option value="">{translate("denyListToolSelect")}</option>
                  {exactChoices.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={tool}
                  placeholder={translate("denyListToolPlaceholder")}
                  onChange={(event) => setTool(event.target.value)}
                />
              )}
            </label>
            <label>
              <span>{translate("denyListToolMatch")}</span>
              <select
                value={toolMatch}
                onChange={(event) => setToolMatch(event.target.value)}
              >
                <option value={MATCH_FIXED}>{translate("denyListMatchFixed")}</option>
                <option value={MATCH_REGEX}>{translate("denyListMatchRegex")}</option>
              </select>
            </label>
          </div>

          <div className="deny-args">
            <span className="deny-args-title">{translate("denyListArgs")}</span>
            {args.map((item, index) => {
              // A name that the tool no longer declares is kept visible instead of
              // snapping the select back to the placeholder mid-edit.
              const fieldChoices =
                parameterNames.length > 0
                  ? item.field && !parameterNames.includes(item.field)
                    ? [item.field, ...parameterNames]
                    : parameterNames
                  : []
              return (
                <div className="deny-arg-row" key={index}>
                  {fieldChoices.length > 0 ? (
                    <select
                      value={item.field}
                      aria-label={translate("denyListArgField")}
                      onChange={(event) => updateArg(index, { field: event.target.value })}
                    >
                      <option value="">{translate("denyListArgFieldSelect")}</option>
                      {fieldChoices.map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={item.field}
                      placeholder={translate("denyListArgField")}
                      aria-label={translate("denyListArgField")}
                      onChange={(event) => updateArg(index, { field: event.target.value })}
                    />
                  )}
                  <select
                    value={item.match}
                    aria-label={translate("denyListArgMatch")}
                    onChange={(event) => updateArg(index, { match: event.target.value })}
                  >
                    <option value={MATCH_FIXED}>{translate("denyListMatchFixed")}</option>
                    <option value={MATCH_REGEX}>{translate("denyListMatchRegex")}</option>
                  </select>
                  <input
                    type="text"
                    value={item.value}
                    placeholder={translate("denyListArgValue")}
                    aria-label={translate("denyListArgValue")}
                    onChange={(event) => updateArg(index, { value: event.target.value })}
                  />
                  <button
                    type="button"
                    className="btn btn-compact"
                    aria-label={translate("denyListArgRemove")}
                    disabled={args.length === 1}
                    onClick={() =>
                      setArgs((current) => current.filter((_, position) => position !== index))
                    }
                  >
                    ×
                  </button>
                </div>
              )
            })}
            <button
              type="button"
              className="btn btn-compact"
              onClick={() => setArgs((current) => [...current, { ...EMPTY_ARGUMENT }])}
            >
              {translate("denyListArgAdd")}
            </button>
          </div>

          <label>
            <span>{translate("denyListReason")}</span>
            <input
              type="text"
              value={reason}
              placeholder={translate("denyListReasonPlaceholder")}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>

          {formError ? <p className="form-error">{formError}</p> : null}

          <div>
            <button type="submit" className="btn btn-primary" disabled={busy === "form"}>
              {busy === "form" ? translate("denyListSubmitting") : translate("denyListSubmit")}
            </button>
          </div>
        </form>

        {rules.length === 0 ? (
          <div className="hint">{translate("denyListEmpty")}</div>
        ) : (
          <ul className="permission-rule-list">
            {rules.map((rule) => (
              <li key={rule.id}>
                <div className="permission-rule-body">
                  <div className="deny-rule-title">
                    <strong>{rule.id}</strong>
                    <span className="deny-match">{specLabel(rule.tool)}</span>
                  </div>
                  {(rule.args || []).length > 0 ? (
                    <ul className="deny-rule-args">
                      {(rule.args || []).map((argument, index) => (
                        <li key={`${argument.field}-${index}`}>
                          <code>{argument.field}</code>
                          <span className="deny-match">{specLabel(argument)}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <span className="hint">{translate("denyListWholeTool")}</span>
                  )}
                  {rule.reason ? <span className="hint">{rule.reason}</span> : null}
                </div>
                <button
                  type="button"
                  className="btn btn-compact btn-danger"
                  disabled={busy === rule.id}
                  onClick={() => remove(rule)}
                >
                  {translate("denyListRemove")}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="hint">{translate("denyListHint")}</div>
      </div>
    </section>
  )
}

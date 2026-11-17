import { useEffect, useRef, useState } from "react"
import { testTool } from "../../api"
import { normalizeParameters } from "./AgentDetail"
import Modal from "./Modal"
import ToolTestGrid from "./ToolTestGrid"
import {
  buildArguments,
  initialValues,
  localizedText,
  permissionLabel,
  resolveAgentNames,
  scopeSummary,
} from "./toolMeta"

// Why an argument could not be turned into a value, keyed by buildArguments'
// error kind.
const ARGUMENT_ERROR_KEYS = {
  missing: "toolTestMissing",
  number: "toolTestInvalidNumber",
  json: "toolTestInvalidJson",
}

export default function ToolDetailDialog({ tool, agents, locale, onClose, translate }) {
  const params = normalizeParameters(tool.parameters)
  const translation = localizedText(tool, locale)
  const [values, setValues] = useState(() => initialValues(params))
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState(null)
  const [inputError, setInputError] = useState("")
  const resultRef = useRef(null)

  // A tool with many arguments puts the result below the fold; scroll it into view
  // once, so pressing Test looks like it did something.
  useEffect(() => {
    if (!result) return
    resultRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [result])

  const agentNames = resolveAgentNames(tool.agent_ids, agents, translate)
  // The backend route runs without the confirmation gate, so a gated tool has to
  // be confirmed here instead.
  const gated = Boolean(tool.permission) && tool.permission !== "none"

  const setValue = (name, value) =>
    setValues((previous) => ({ ...previous, [name]: value }))

  const runTest = async () => {
    setInputError("")
    const built = buildArguments(params, values)
    if (built.error) {
      setInputError(`${translate(ARGUMENT_ERROR_KEYS[built.error.kind])}: ${built.error.name}`)
      return
    }
    if (gated && !window.confirm(translate("toolTestGatedConfirm"))) {
      return
    }

    setTesting(true)
    setResult(null)
    try {
      setResult(await testTool(tool.name, built.arguments))
    } catch (error) {
      setResult({ ok: false, error: error?.message || translate("errorUnknown") })
    } finally {
      setTesting(false)
    }
  }

  return (
    <Modal
      wide
      className="modal-dialog-tool"
      title={tool.name}
      hint={translate("toolDetailHint")}
      closeLabel={translate("dialogClose")}
      onClose={onClose}
    >
      {/* Tool metadata and description span the dialog; the parameter schema and
          the test inputs share one grid below, so both columns line up. */}
      <div className="tool-detail-head">
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
        <p className="agent-detail-desc tool-detail-desc">
          {tool.description || translate("agentToolNoDescription")}
        </p>
        {translation?.description ? (
          <p className="agent-detail-desc agent-desc-i18n tool-detail-desc">
            {translation.description}
          </p>
        ) : null}
      </div>

      <ToolTestGrid
        params={params}
        parameters={tool.parameters}
        values={values}
        onChange={setValue}
        translate={translate}
        translatedParams={translation?.parameters}
        inputError={inputError}
        onRun={runTest}
        testing={testing}
        result={result}
        resultRef={resultRef}
      />
    </Modal>
  )
}

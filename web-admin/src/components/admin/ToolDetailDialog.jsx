import { useEffect, useRef, useState } from "react"
import { testTool } from "../../api"
import { AgentToolDetail, normalizeParameters } from "./AgentDetail"
import Modal from "./Modal"
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

function ToolTestResult({ result, translate }) {
  const ok = Boolean(result.ok)

  return (
    <div className="agent-section">
      <div className="agent-section-head">
        <span>{translate("toolTestResult")}</span>
        <div className="agent-section-actions">
          <span className={`badge ${ok ? "badge-library" : "badge-warning"}`}>
            {ok ? translate("toolTestOk") : translate("toolTestFailed")}
          </span>
          {typeof result.duration_ms === "number" ? (
            <span className="hint">{`${result.duration_ms} ms`}</span>
          ) : null}
        </div>
      </div>
      {ok ? (
        <>
          <pre className="agent-detail-block tool-test-output">{result.result || "-"}</pre>
          {result.details ? (
            <pre className="agent-detail-block tool-test-output">{result.details}</pre>
          ) : null}
          {result.truncated ? (
            <p className="hint">{translate("toolTestTruncated")}</p>
          ) : null}
        </>
      ) : (
        <pre className="agent-detail-block tool-test-output tool-test-error">{result.error}</pre>
      )}
    </div>
  )
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
      title={tool.name}
      hint={translate("toolDetailHint")}
      closeLabel={translate("dialogClose")}
      onClose={onClose}
      actions={
        <button type="button" className="btn btn-compact btn-primary" onClick={runTest} disabled={testing}>
          {testing ? translate("toolTestRunning") : translate("toolTest")}
        </button>
      }
    >
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

        <AgentToolDetail
          tool={tool}
          translate={translate}
          values={values}
          onChange={setValue}
          translation={translation}
        />

        {inputError ? <div className="form-error">{inputError}</div> : null}
        {result ? (
          <div ref={resultRef}>
            <ToolTestResult result={result} translate={translate} />
          </div>
        ) : null}
      </div>
    </Modal>
  )
}

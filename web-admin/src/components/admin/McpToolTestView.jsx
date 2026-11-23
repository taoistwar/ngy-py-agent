// One MCP tool, callable by hand: its argument form and the server's answer. It
// lives inside McpProbeDialog, so the tool list is one click away from a test.

import { useState } from "react"
import { testMcpTool } from "../../api"
import { normalizeParameters } from "./AgentDetail"
import ParameterInput from "./ParameterInput"
import { buildArguments, initialValues } from "./toolMeta"

// Why an argument could not be turned into a value, keyed by buildArguments'
// error kind.
const ARGUMENT_ERROR_KEYS = {
  missing: "toolTestMissing",
  number: "toolTestInvalidNumber",
  json: "toolTestInvalidJson",
}

function TestResult({ result, translate }) {
  if (!result) {
    return <p className="hint">{translate("toolTestEmpty")}</p>
  }
  if (!result.ok) {
    return (
      <pre className="agent-detail-block tool-test-error">
        {result.error || translate("toolTestFailed")}
      </pre>
    )
  }
  return (
    <>
      <pre className="agent-detail-block tool-test-output">{result.result || "-"}</pre>
      {result.truncated ? <p className="hint">{translate("toolTestTruncated")}</p> : null}
    </>
  )
}

function ParamField({ param, value, onChange, translate }) {
  return (
    <label>
      <span>
        <code className="agent-param-name">{param.name}</code>{" "}
        <span className="agent-param-type">{param.type}</span>{" "}
        {param.required ? (
          <span className="badge badge-builtin">{translate("agentToolRequired")}</span>
        ) : null}
      </span>
      <ParameterInput param={param} value={value} onChange={onChange} translate={translate} />
      {param.description ? <span className="agent-param-desc">{param.description}</span> : null}
    </label>
  )
}

export default function McpToolTestView({ server, tool, onBack, translate }) {
  const schema = tool.input_schema || {}
  const params = normalizeParameters(schema)
  const [values, setValues] = useState(() => initialValues(params))
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [inputError, setInputError] = useState("")

  const setValue = (name, value) => setValues((previous) => ({ ...previous, [name]: value }))

  const run = async () => {
    setInputError("")
    const built = buildArguments(params, values)
    if (built.error) {
      setInputError(`${translate(ARGUMENT_ERROR_KEYS[built.error.kind])}: ${built.error.name}`)
      return
    }

    setRunning(true)
    setResult(null)
    try {
      setResult(await testMcpTool(server.mcp_id, tool.name, built.arguments))
    } catch (error) {
      setResult({ ok: false, error: error?.message || translate("errorUnknown") })
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      <p className="agent-detail-desc">
        {tool.description || translate("agentToolNoDescription")}
      </p>

      <div className="agent-section-head">
        <span>{translate("toolTestPanel")}</span>
        <div className="agent-section-actions">
          <button type="button" className="btn btn-xs" onClick={onBack}>
            {translate("mcpToolTestBack")}
          </button>
          <button type="button" className="btn btn-xs btn-primary" onClick={run} disabled={running}>
            {running ? translate("toolTestRunning") : translate("toolTest")}
          </button>
        </div>
      </div>

      {params.length > 0 ? (
        <div className="form-grid">
          {params.map((param) => (
            <ParamField
              key={param.name}
              param={param}
              value={values[param.name]}
              onChange={(next) => setValue(param.name, next)}
              translate={translate}
            />
          ))}
        </div>
      ) : (
        <p className="hint">{translate("toolTestNoParams")}</p>
      )}

      {inputError ? <div className="form-error">{inputError}</div> : null}

      <div className="agent-section-head">
        <span>{translate("toolTestResult")}</span>
        {result ? (
          <div className="agent-section-actions">
            <span className={`badge ${result.ok ? "badge-library" : "badge-warning"}`}>
              {result.ok ? translate("toolTestOk") : translate("toolTestFailed")}
            </span>
            {typeof result.duration_ms === "number" ? (
              <span className="hint">{`${result.duration_ms} ms`}</span>
            ) : null}
          </div>
        ) : null}
      </div>
      <section className="tool-test-result mcp-tool-test-result">
        <TestResult result={result} translate={translate} />
      </section>
    </>
  )
}

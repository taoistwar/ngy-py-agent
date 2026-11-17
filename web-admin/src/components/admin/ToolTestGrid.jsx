// Tool detail body: the read-only parameter schema on the left and its test
// inputs on the right. Both live in one row-per-parameter grid, so every
// parameter lines up with the field that feeds it.

import { ParamSchema } from "./AgentDetail"

const TEXTUAL_TYPES = new Set(["string", "any", "null"])

// Editor for one tool argument, chosen from its JSON schema.
function ParameterInput({ param, value, onChange, translate }) {
  const current = value ?? ""

  if (param.options.length > 0 || param.type === "boolean") {
    const options = param.options.length > 0 ? param.options : ["true", "false"]
    return (
      <select
        className="agent-param-input"
        value={current}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{translate("toolTestValueUnset")}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    )
  }

  if (param.type === "object" || param.type === "array") {
    return (
      <textarea
        className="agent-param-input"
        rows={3}
        value={current}
        placeholder={param.type === "array" ? '["value"]' : '{"key": "value"}'}
        onChange={(event) => onChange(event.target.value)}
      />
    )
  }

  return (
    <input
      className="agent-param-input"
      type="text"
      inputMode={TEXTUAL_TYPES.has(param.type) ? undefined : "decimal"}
      value={current}
      placeholder={param.defaultValue !== undefined ? String(param.defaultValue) : param.name}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

/** Name and type of a parameter above its test input. */
function ParamInputHead({ param, translate }) {
  return (
    <div className="agent-param-head">
      <code className="agent-param-name">{param.name}</code>
      <span className="agent-param-type">{param.type}</span>
      {param.required ? (
        <span className="badge badge-builtin">{translate("agentToolRequired")}</span>
      ) : null}
    </div>
  )
}

function TestResult({ result, translate }) {
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

export default function ToolTestGrid({
  params,
  parameters,
  values,
  onChange,
  translate,
  translatedParams,
  inputError,
  onRun,
  testing,
  result,
  resultRef,
}) {
  const hasSchema = Boolean(parameters) && Object.keys(parameters).length > 0

  return (
    <div className="tool-detail-grid">
      <div className="tool-detail-row">
        <div className="tool-detail-head-cell">{translate("agentToolParams")}</div>
        <div className="tool-detail-head-cell">{translate("toolTestPanel")}</div>
      </div>

      {params.length > 0 ? (
        params.map((param) => (
          <div className="tool-detail-row" key={param.name}>
            <div className="agent-param">
              <ParamSchema
                param={param}
                translate={translate}
                translatedDescription={translatedParams?.[param.name]}
              />
            </div>
            <div className="agent-param">
              <ParamInputHead param={param} translate={translate} />
              <ParameterInput
                param={param}
                value={values?.[param.name]}
                onChange={(next) => onChange(param.name, next)}
                translate={translate}
              />
            </div>
          </div>
        ))
      ) : (
        <div className="tool-detail-row">
          <div className="agent-param">
            {hasSchema ? (
              <pre className="agent-detail-block">{JSON.stringify(parameters, null, 2)}</pre>
            ) : (
              <p className="hint">{translate("agentToolNoParams")}</p>
            )}
          </div>
          <div className="agent-param">
            <p className="hint">{translate("toolTestNoParams")}</p>
          </div>
        </div>
      )}

      {inputError ? (
        <div className="tool-detail-row">
          <div className="tool-detail-spacer" />
          <div className="form-error">{inputError}</div>
        </div>
      ) : null}

      {/* The run action stays under the inputs, next to what it sends. */}
      <div className="tool-detail-row">
        <div className="tool-detail-spacer" />
        <div className="tool-test-actions">
          <button type="button" className="btn btn-compact btn-primary" onClick={onRun} disabled={testing}>
            {testing ? translate("toolTestRunning") : translate("toolTest")}
          </button>
        </div>
      </div>

      <div className="tool-detail-row">
        <div className="tool-detail-spacer" />
        <div ref={resultRef}>
          {result ? (
            <TestResult result={result} translate={translate} />
          ) : (
            <p className="hint">{translate("toolTestEmpty")}</p>
          )}
        </div>
      </div>
    </div>
  )
}

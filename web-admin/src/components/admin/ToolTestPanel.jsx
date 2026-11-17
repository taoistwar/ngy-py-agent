// Test bench of the tool detail dialog: the last run's output is pinned above
// the argument inputs, which sit in the right-hand column of the dialog.

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

function TestResultBody({ result, translate }) {
  if (!result) {
    return <p className="hint">{translate("toolTestEmpty")}</p>
  }
  if (!result.ok) {
    return <pre className="agent-detail-block tool-test-output tool-test-error">{result.error}</pre>
  }
  return (
    <>
      <pre className="agent-detail-block tool-test-output">{result.result || "-"}</pre>
      {result.details ? (
        <pre className="agent-detail-block tool-test-output">{result.details}</pre>
      ) : null}
      {result.truncated ? <p className="hint">{translate("toolTestTruncated")}</p> : null}
    </>
  )
}

// The box keeps its height across runs, so pressing Test never moves the inputs.
function TestResultHead({ result, translate }) {
  const ok = Boolean(result?.ok)

  return (
    <div className="agent-section-head">
      <span>{translate("toolTestResult")}</span>
      {result ? (
        <div className="agent-section-actions">
          <span className={`badge ${ok ? "badge-library" : "badge-warning"}`}>
            {ok ? translate("toolTestOk") : translate("toolTestFailed")}
          </span>
          {typeof result.duration_ms === "number" ? (
            <span className="hint">{`${result.duration_ms} ms`}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export default function ToolTestPanel({
  params,
  values,
  onChange,
  translate,
  inputError,
  onRun,
  testing,
  result,
  resultRef,
}) {
  return (
    <div className="tool-test-panel">
      <section className="tool-test-result" ref={resultRef}>
        <TestResultHead result={result} translate={translate} />
        <div className="tool-test-result-body">
          <TestResultBody result={result} translate={translate} />
        </div>
      </section>

      <div className="agent-section-head">
        <span>{translate("toolTestPanel")}</span>
      </div>

      {params.length > 0 ? (
        <div className="agent-param-list">
          {params.map((param) => (
            <div className="agent-param" key={param.name}>
              <div className="agent-param-head">
                <code className="agent-param-name">{param.name}</code>
                <span className="agent-param-type">{param.type}</span>
                {param.required ? (
                  <span className="badge badge-builtin">{translate("agentToolRequired")}</span>
                ) : null}
              </div>
              <ParameterInput
                param={param}
                value={values?.[param.name]}
                onChange={(next) => onChange(param.name, next)}
                translate={translate}
              />
            </div>
          ))}
        </div>
      ) : (
        <p className="hint">{translate("toolTestNoParams")}</p>
      )}

      {inputError ? <div className="form-error">{inputError}</div> : null}

      {/* The run action stays under the inputs, next to what it sends. */}
      <div className="tool-test-actions">
        <button type="button" className="btn btn-compact btn-primary" onClick={onRun} disabled={testing}>
          {testing ? translate("toolTestRunning") : translate("toolTest")}
        </button>
      </div>
    </div>
  )
}

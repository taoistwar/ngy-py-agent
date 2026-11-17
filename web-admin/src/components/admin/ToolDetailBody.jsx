// Body of the tool detail dialog. The schema and the test form share one grid:
// the metadata block and the result box form the first row, so the 参数 and
// 测试输入 sections below start on the same line and every parameter sits next
// to the field that feeds it.

import { ParamSchema } from "./AgentDetail"
import { permissionLabel, resolveAgentNames, scopeSummary } from "./toolMeta"

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

function ToolMeta({ tool, agents, translate }) {
  const agentNames = resolveAgentNames(tool.agent_ids, agents, translate)

  return (
    <>
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
    </>
  )
}

export default function ToolDetailBody({
  tool,
  agents,
  translate,
  translation,
  params,
  values,
  onChange,
  inputError,
  onRun,
  testing,
  result,
  resultRef,
}) {
  const hasSchema = Boolean(tool.parameters) && Object.keys(tool.parameters).length > 0
  const translatedParams = translation?.parameters || {}

  return (
    <div className="tool-detail-grid">
      <div className="tool-detail-main">
        <ToolMeta tool={tool} agents={agents} translate={translate} />
        <p className="agent-detail-desc">
          {tool.description || translate("agentToolNoDescription")}
        </p>
        {translation?.description ? (
          <p className="agent-detail-desc agent-desc-i18n">{translation.description}</p>
        ) : null}
      </div>

      {/* The heading stays outside the box; the box itself fills the height of
          the metadata block beside it, which is what lines the sections up. */}
      <div className="tool-test-result-cell">
        <div className="agent-section-head">
          <span>{translate("toolTestResult")}</span>
          {result ? (
            <div className="agent-section-actions">
              <span
                className={`badge ${result.ok ? "badge-library" : "badge-warning"}`}
              >
                {result.ok ? translate("toolTestOk") : translate("toolTestFailed")}
              </span>
              {typeof result.duration_ms === "number" ? (
                <span className="hint">{`${result.duration_ms} ms`}</span>
              ) : null}
            </div>
          ) : null}
        </div>
        <section className="tool-test-result" ref={resultRef}>
          <div className="tool-test-result-body">
            <TestResultBody result={result} translate={translate} />
          </div>
        </section>
      </div>

      <div className="agent-section-head">
        <span>{translate("agentToolParams")}</span>
      </div>
      {/* The run action heads the form it submits. */}
      <div className="agent-section-head">
        <span>{translate("toolTestPanel")}</span>
        <button type="button" className="btn btn-xs btn-primary" onClick={onRun} disabled={testing}>
          {testing ? translate("toolTestRunning") : translate("toolTest")}
        </button>
      </div>

      {params.length > 0 ? (
        params.map((param) => (
          <ParamRow
            key={param.name}
            param={param}
            value={values?.[param.name]}
            onChange={onChange}
            translate={translate}
            translatedDescription={translatedParams[param.name]}
          />
        ))
      ) : (
        <>
          <div className="agent-param">
            {hasSchema ? (
              <pre className="agent-detail-block">{JSON.stringify(tool.parameters, null, 2)}</pre>
            ) : (
              <p className="hint">{translate("agentToolNoParams")}</p>
            )}
          </div>
          <div className="agent-param">
            <p className="hint">{translate("toolTestNoParams")}</p>
          </div>
        </>
      )}

      {inputError ? (
        <>
          <div className="tool-detail-spacer" />
          <div className="form-error">{inputError}</div>
        </>
      ) : null}
    </div>
  )
}

/** One grid row: the schema card on the left, its input on the right. */
function ParamRow({ param, value, onChange, translate, translatedDescription }) {
  return (
    <>
      <div className="agent-param">
        <ParamSchema
          param={param}
          translate={translate}
          translatedDescription={translatedDescription}
        />
      </div>
      <div className="agent-param">
        <ParamInputHead param={param} translate={translate} />
        <ParameterInput
          param={param}
          value={value}
          onChange={(next) => onChange(param.name, next)}
          translate={translate}
        />
      </div>
    </>
  )
}

// Read-only detail views for the agent editor: tool schema and skill instruction.

export function normalizeParameters(parameters) {
  if (!parameters || typeof parameters !== "object") return []
  const properties = parameters.properties
  if (!properties || typeof properties !== "object") return []
  const required = Array.isArray(parameters.required) ? parameters.required : []
  return Object.entries(properties).map(([name, schema]) => ({
    name,
    type: Array.isArray(schema?.type) ? schema.type.join(" | ") : schema?.type || "any",
    description: schema?.description || "",
    required: required.includes(name),
    // Kept for the test form: a sensible starting value and the allowed values.
    defaultValue: schema?.default,
    options: Array.isArray(schema?.enum) ? schema.enum.map((value) => String(value)) : [],
  }))
}

const TEXTUAL_TYPES = new Set(["string", "any", "null"])

// Editor for one tool argument, chosen from its JSON schema. It sits next to the
// read-only rendering so the tool page and the agent editor describe a parameter
// the same way.
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

export function AgentToolDetail({ tool, translate, values, onChange }) {
  const params = normalizeParameters(tool.parameters)
  const hasSchema = Boolean(tool.parameters) && Object.keys(tool.parameters).length > 0
  const editable = typeof onChange === "function"

  return (
    <div className="agent-detail">
      <p className="agent-detail-desc">{tool.description || translate("agentToolNoDescription")}</p>
      <div className="agent-section">
        <div className="agent-section-head">
          <span>{translate("agentToolParams")}</span>
        </div>
        {params.length > 0 ? (
          <div className="agent-param-list">
            {params.map((param) => (
              <div className="agent-param" key={param.name}>
                <div className="agent-param-head">
                  <code className="agent-param-name">{param.name}</code>
                  <span className="agent-param-type">{param.type}</span>
                  {param.required && (
                    <span className="badge badge-builtin">{translate("agentToolRequired")}</span>
                  )}
                </div>
                <span className="agent-param-desc">
                  {param.description || translate("agentToolNoDescription")}
                </span>
                {editable ? (
                  <ParameterInput
                    param={param}
                    value={values?.[param.name]}
                    onChange={(next) => onChange(param.name, next)}
                    translate={translate}
                  />
                ) : null}
              </div>
            ))}
          </div>
        ) : hasSchema ? (
          <pre className="agent-detail-block">{JSON.stringify(tool.parameters, null, 2)}</pre>
        ) : (
          <p className="hint">{translate("agentToolNoParams")}</p>
        )}
      </div>
    </div>
  )
}

export function AgentMcpDetail({ server, translate }) {
  return (
    <div className="agent-detail">
      <div className="agent-detail-meta">
        <span className="agent-detail-label">{translate("mcpListTransport")}</span>
        <span className="agent-detail-value">{server.transport || "-"}</span>
      </div>
      <div className="agent-detail-meta">
        <span className="agent-detail-label">{translate("mcpListTarget")}</span>
        <span className="agent-detail-value">{server.target || "-"}</span>
      </div>
      <div className="agent-section">
        <div className="agent-section-head">
          <span>{translate("mcpListDescription")}</span>
        </div>
        <p className="agent-detail-desc">
          {server.description || translate("agentToolNoDescription")}
        </p>
      </div>
    </div>
  )
}

export function AgentSkillDetail({ kind, skill, translate }) {
  const isBuiltin = kind === "builtin"
  const instruction = skill.instruction || ""

  return (
    <div className="agent-detail">
      <div className="agent-detail-meta">
        <span className="agent-detail-label">{translate("agentSkillIdentifier")}</span>
        <code className="agent-detail-value">{skill.name}</code>
        <span className={`badge ${isBuiltin ? "badge-builtin" : "badge-library"}`}>
          {isBuiltin ? translate("agentBuiltin") : translate("agentSkillLibrary")}
        </span>
      </div>
      {!isBuiltin && skill.path ? (
        <div className="agent-detail-meta">
          <span className="agent-detail-label">{translate("skillListPath")}</span>
          <span className="agent-detail-value">{skill.path}</span>
        </div>
      ) : null}
      {isBuiltin ? (
        <div className="agent-section">
          <div className="agent-section-head">
            <span>{translate("agentSkillInstruction")}</span>
          </div>
          {instruction ? (
            <pre className="agent-detail-block">{instruction}</pre>
          ) : (
            <p className="hint">{translate("agentSkillNoInstruction")}</p>
          )}
        </div>
      ) : (
        <div className="agent-section">
          <div className="agent-section-head">
            <span>{translate("skillListDescription")}</span>
          </div>
          <p className="agent-detail-desc">
            {skill.description || translate("agentToolNoDescription")}
          </p>
        </div>
      )}
    </div>
  )
}

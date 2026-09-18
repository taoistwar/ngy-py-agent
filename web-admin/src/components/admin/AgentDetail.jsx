// Read-only detail views for the agent editor: tool schema and skill instruction.

function normalizeParameters(parameters) {
  if (!parameters || typeof parameters !== "object") return []
  const properties = parameters.properties
  if (!properties || typeof properties !== "object") return []
  const required = Array.isArray(parameters.required) ? parameters.required : []
  return Object.entries(properties).map(([name, schema]) => ({
    name,
    type: schema?.type || "any",
    description: schema?.description || "",
    required: required.includes(name),
  }))
}

export function AgentToolDetail({ tool, translate }) {
  const params = normalizeParameters(tool.parameters)
  const hasSchema = Boolean(tool.parameters) && Object.keys(tool.parameters).length > 0

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

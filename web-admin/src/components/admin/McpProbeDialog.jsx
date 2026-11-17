// Result of one MCP connection test: whether the server answered, what it called
// itself, and the tools it exposed. It lives outside McpServerManager so the
// marketplace page stays a list with a form.

import Modal from "./Modal"

function MetaRow({ label, children }) {
  return (
    <div className="agent-detail-meta">
      <span className="agent-detail-label">{label}</span>
      <span className="agent-detail-value">{children}</span>
    </div>
  )
}

/** "name version", or "-" when the server did not identify itself. */
function serverLabel(result) {
  const name = result.server_name || "-"
  return result.server_version ? `${name} ${result.server_version}` : name
}

function ToolTable({ tools, translate }) {
  if (tools.length === 0) {
    return <p className="hint">{translate("mcpProbeToolsEmpty")}</p>
  }
  return (
    <table className="model-table">
      <thead>
        <tr>
          <th>{translate("mcpProbeToolName")}</th>
          <th>{translate("mcpProbeToolDescription")}</th>
        </tr>
      </thead>
      <tbody>
        {tools.map((tool) => (
          <tr key={tool.name}>
            <td className="mono">{tool.name}</td>
            <td>{tool.description || "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ProbeBody({ result, translate }) {
  const tools = result.tools || []
  return (
    <>
      <div className="agent-detail-meta">
        <span className="agent-detail-label">{translate("mcpProbeStatus")}</span>
        <span className={`badge ${result.ok ? "badge-library" : "badge-warning"}`}>
          {result.ok ? translate("mcpProbeOk") : translate("mcpProbeFailed")}
        </span>
        {typeof result.duration_ms === "number" ? (
          <span className="hint">{`${result.duration_ms} ms`}</span>
        ) : null}
      </div>
      <MetaRow label={translate("mcpProbeServer")}>{serverLabel(result)}</MetaRow>
      <MetaRow label={translate("mcpProbeProtocol")}>{result.protocol_version || "-"}</MetaRow>
      {result.ok ? (
        <>
          <div className="agent-section-head">
            <span>{translate("mcpProbeTools")}</span>
            <span className="hint">{tools.length}</span>
          </div>
          <ToolTable tools={tools} translate={translate} />
        </>
      ) : (
        <pre className="agent-detail-block tool-test-error">
          {result.error || translate("mcpProbeFailed")}
        </pre>
      )}
    </>
  )
}

export default function McpProbeDialog({ server, state, onClose, translate }) {
  const running = state?.status === "running"
  const result = state?.result || null
  const hint = server ? `${server.name} · ${server.transport} · ${server.target}` : ""

  return (
    <Modal
      title={translate("mcpProbeTitle")}
      hint={hint}
      closeLabel={translate("dialogClose")}
      onClose={onClose}
      wide
    >
      <p className="hint">{translate("mcpProbeHint")}</p>
      {running ? <p className="hint">{translate("mcpProbeRunning")}</p> : null}
      {result ? <ProbeBody result={result} translate={translate} /> : null}
    </Modal>
  )
}

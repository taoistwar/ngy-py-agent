// Result of one MCP connection test: whether the server answered, what it called
// itself, and the tools it exposed. Picking a tool opens its own test form, so the
// marketplace can check a preset's tools and not just its handshake.
//
// It lives outside McpServerManager so the marketplace page stays a list with a form.

import { useState } from "react"

import McpToolTestView from "./McpToolTestView"
import Modal from "./Modal"
import { mcpTransportLabel } from "./shared"

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

function ToolTable({ tools, translate, onPick }) {
  if (tools.length === 0) {
    return <p className="hint">{translate("mcpProbeToolsEmpty")}</p>
  }
  return (
    <table className="model-table">
      <thead>
        <tr>
          <th>{translate("mcpProbeToolName")}</th>
          <th>{translate("mcpProbeToolDescription")}</th>
          <th>{translate("modelListActions")}</th>
        </tr>
      </thead>
      <tbody>
        {/* The row is the entry point: clicking a tool opens its test form. */}
        {tools.map((tool) => (
          <tr
            key={tool.name}
            className="model-row-link"
            title={translate("mcpToolTestOpenHint")}
            tabIndex={0}
            onClick={() => onPick(tool)}
            onKeyDown={(event) => {
              if (event.key !== "Enter") return
              event.preventDefault()
              onPick(tool)
            }}
          >
            <td className="mono">{tool.name}</td>
            <td>{tool.description || "-"}</td>
            <td className="model-actions">
              <button
                type="button"
                className="btn btn-xs"
                onClick={(event) => {
                  event.stopPropagation()
                  onPick(tool)
                }}
              >
                {translate("toolTest")}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ProbeBody({ result, translate, onPickTool }) {
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
            <div className="agent-section-actions">
              {tools.length > 0 ? (
                <span className="hint">{translate("mcpToolTestPickHint")}</span>
              ) : null}
              <span className="hint">{tools.length}</span>
            </div>
          </div>
          <ToolTable tools={tools} translate={translate} onPick={onPickTool} />
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
  // The tool picked for a manual run, or null while the probe summary is shown.
  const [pickedTool, setPickedTool] = useState(null)
  const running = state?.status === "running"
  const result = state?.result || null
  const hint = server
    ? `${server.name} · ${mcpTransportLabel(server.transport)} · ${server.target}`
    : ""
  const toolHint = server && pickedTool ? `${server.name} · ${pickedTool.name}` : ""

  return (
    <Modal
      title={pickedTool ? translate("mcpToolTestTitle") : translate("mcpProbeTitle")}
      hint={pickedTool ? toolHint : hint}
      closeLabel={translate("dialogClose")}
      onClose={onClose}
      wide
    >
      {pickedTool ? (
        <McpToolTestView
          server={server}
          tool={pickedTool}
          onBack={() => setPickedTool(null)}
          translate={translate}
        />
      ) : (
        <>
          <p className="hint">{translate("mcpProbeHint")}</p>
          {running ? <p className="hint">{translate("mcpProbeRunning")}</p> : null}
          {result ? (
            <ProbeBody result={result} translate={translate} onPickTool={setPickedTool} />
          ) : null}
        </>
      )}
    </Modal>
  )
}

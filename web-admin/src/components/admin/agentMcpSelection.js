// Selection helpers binding an agent's stored MCP entries to the MCP marketplace.
//
// An agent stores a resolved copy of every selected MCP server so tasks keep
// working even when a marketplace entry is renamed or removed. The editor keeps
// entries that no longer exist in the marketplace as "legacy" rows so editing an
// agent never drops configuration silently.

export const LEGACY_MCP_PREFIX = "legacy::"

function legacyId(name) {
  return `${LEGACY_MCP_PREFIX}${name}`
}

function describe(transport, target) {
  return `${transport || "stdio"} · ${target || "-"}`
}

/** Split an agent's stored MCP entries into marketplace ids plus orphaned ones. */
export function splitAgentMcpServers(agent, servers) {
  const byId = new Map(servers.map((server) => [server.mcp_id, server]))
  const byName = new Map(servers.map((server) => [server.name, server]))
  const selection = []
  const legacy = []

  for (const entry of agent?.mcp_servers || []) {
    if (!entry || typeof entry !== "object") continue
    const name = String(entry.name || "").trim()
    const match = (entry.mcp_id ? byId.get(entry.mcp_id) : null) || byName.get(name)
    if (match) {
      selection.push(match.mcp_id)
    } else if (name) {
      legacy.push({
        name,
        transport: entry.transport || "stdio",
        target: entry.target || "",
      })
      selection.push(legacyId(name))
    }
  }

  return { selection, legacy }
}

/** Rows for the shared check list: marketplace entries first, then orphans. */
export function buildMcpItems(servers, legacyEntries, translate) {
  const market = servers.map((server) => ({
    id: server.mcp_id,
    title: server.name,
    description: describe(server.transport, server.target),
    badge: server.transport,
    badgeClass: "badge-library",
    payload: { ...server },
  }))

  const legacy = legacyEntries.map((entry) => ({
    id: legacyId(entry.name),
    title: entry.name,
    description: describe(entry.transport, entry.target),
    badge: translate("agentMcpMissing"),
    badgeClass: "badge-warning",
    payload: { ...entry },
  }))

  return [...market, ...legacy]
}

/** Rebuild the stored ``mcp_servers`` snapshot from the current selection. */
export function resolveMcpServers(selection, servers, legacyEntries) {
  const byId = new Map(servers.map((server) => [server.mcp_id, server]))
  const byLegacyId = new Map(legacyEntries.map((entry) => [legacyId(entry.name), entry]))
  const resolved = []

  for (const id of selection) {
    if (String(id).startsWith(LEGACY_MCP_PREFIX)) {
      const entry = byLegacyId.get(id)
      if (entry) {
        resolved.push({ name: entry.name, transport: entry.transport, target: entry.target })
      }
      continue
    }
    const server = byId.get(id)
    if (server) {
      resolved.push({
        mcp_id: server.mcp_id,
        name: server.name,
        transport: server.transport,
        target: server.target,
      })
    }
  }

  return resolved
}

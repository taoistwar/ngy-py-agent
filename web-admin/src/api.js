const API_BASE = ""

function toTextOrJson(response) {
  return response.text().then((text) => {
    if (!text) {
      return {}
    }
    try {
      return JSON.parse(text)
    } catch {
      return { message: text }
    }
  })
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options)
  const payload = await toTextOrJson(response)

  if (!response.ok) {
    const detail = payload?.detail || payload?.message || `Request failed with status ${response.status}`
    throw new Error(detail)
  }

  return payload
}

export async function fetchTasks(sessionId) {
  const query = sessionId
    ? `?${new URLSearchParams({ session_id: sessionId }).toString()}`
    : ""
  const data = await requestJson(`${API_BASE}/api/tasks${query}`)
  return data.tasks ?? []
}

export async function fetchSessions() {
  const data = await requestJson(`${API_BASE}/api/sessions`)
  return data.sessions ?? []
}

export async function createSession(name, workspaceId) {
  const trimmed = typeof name === "string" ? name.trim() : ""
  const body = {}
  if (trimmed) {
    body.name = trimmed
  }
  if (workspaceId) {
    body.workspace_id = workspaceId
  }
  return requestJson(`${API_BASE}/api/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  })
}

export async function fetchWorkspaces() {
  const data = await requestJson(`${API_BASE}/api/workspaces`)
  return data.workspaces ?? []
}

export async function fetchAgents() {
  const data = await requestJson(`${API_BASE}/api/agents`)
  return data.agents ?? []
}

export async function fetchSkills() {
  return requestJson(`${API_BASE}/api/skills`)
}

export async function updateSkillsRoot(skillsRoot) {
  return requestJson(`${API_BASE}/api/admin/skills-root`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ skills_root: skillsRoot }),
  })
}

export async function importSkill(sourcePath) {
  return requestJson(`${API_BASE}/api/skills/import`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ source_path: sourcePath }),
  })
}

export async function deleteSkill(name) {
  return requestJson(`${API_BASE}/api/skills/${encodeURIComponent(name)}`, {
    method: "DELETE",
  })
}

export async function fetchAgentMeta() {
  return requestJson(`${API_BASE}/api/agents/meta`)
}

export async function createAgent(payload) {
  return requestJson(`${API_BASE}/api/agents`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function updateAgent(agentId, payload) {
  return requestJson(`${API_BASE}/api/agents/${agentId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function deleteAgent(agentId) {
  return requestJson(`${API_BASE}/api/agents/${agentId}`, {
    method: "DELETE",
  })
}

export async function createWorkspace(payload) {
  return requestJson(`${API_BASE}/api/workspaces`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function updateWorkspace(workspaceId, payload) {
  return requestJson(`${API_BASE}/api/workspaces/${workspaceId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function deleteWorkspace(workspaceId) {
  return requestJson(`${API_BASE}/api/workspaces/${workspaceId}`, {
    method: "DELETE",
  })
}

export async function renameSession(sessionId, name) {
  return requestJson(`${API_BASE}/api/sessions/${sessionId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ name }),
  })
}

export async function deleteSession(sessionId) {
  return requestJson(`${API_BASE}/api/sessions/${sessionId}`, {
    method: "DELETE",
  })
}

export async function fetchModels() {
  const data = await requestJson(`${API_BASE}/api/models`)
  return data.models ?? []
}

export async function createModel(payload) {
  return requestJson(`${API_BASE}/api/models`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function updateModel(modelId, payload) {
  return requestJson(`${API_BASE}/api/models/${modelId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function deleteModel(modelId) {
  return requestJson(`${API_BASE}/api/models/${modelId}`, {
    method: "DELETE",
  })
}

export async function fetchMcpServers() {
  const data = await requestJson(`${API_BASE}/api/mcp-servers`)
  return data.servers ?? []
}

export async function createMcpServer(payload) {
  return requestJson(`${API_BASE}/api/mcp-servers`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function updateMcpServer(mcpId, payload) {
  return requestJson(`${API_BASE}/api/mcp-servers/${mcpId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function deleteMcpServer(mcpId) {
  return requestJson(`${API_BASE}/api/mcp-servers/${mcpId}`, {
    method: "DELETE",
  })
}

export async function createTask(payload) {
  return requestJson(`${API_BASE}/api/tasks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function deleteTask(taskId) {
  return requestJson(`${API_BASE}/api/tasks/${taskId}`, {
    method: "DELETE",
  })
}

export async function fetchTask(taskId) {
  return requestJson(`${API_BASE}/api/tasks/${taskId}`)
}

export async function stopTask(taskId) {
  return requestJson(`${API_BASE}/api/tasks/${taskId}/stop`, {
    method: "POST",
  })
}

export async function fetchTaskEvents(taskId, { offset, limit }) {
  const query = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  })
  return requestJson(`${API_BASE}/api/tasks/${taskId}/events?${query.toString()}`)
}

export async function fetchRetentionConfig() {
  return requestJson(`${API_BASE}/api/admin/retention`)
}

export async function updateRetentionConfig(retentionDays) {
  return requestJson(`${API_BASE}/api/admin/retention`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ retention_days: retentionDays }),
  })
}

export async function fetchHealth() {
  return requestJson(`${API_BASE}/api/healthz`)
}

export async function fetchMaxStepsConfig() {
  return requestJson(`${API_BASE}/api/admin/max-steps`)
}

export async function updateMaxStepsConfig(maxSteps) {
  return requestJson(`${API_BASE}/api/admin/max-steps`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ max_steps: maxSteps }),
  })
}

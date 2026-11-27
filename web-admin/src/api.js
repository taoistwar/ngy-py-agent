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

// A rejected request carries either a sentence (our handlers) or FastAPI's list of
// validation items, one per bad field. Both are flattened to a string: handing the
// list to ``new Error`` printed "[object Object]" and hid which field was wrong.
function describeDetail(detail) {
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item
        const loc = Array.isArray(item?.loc) ? item.loc.filter((part) => part !== "body") : []
        const message = item?.msg || JSON.stringify(item)
        return loc.length > 0 ? `${loc.join(".")}: ${message}` : message
      })
      .join("; ")
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail)
  return ""
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options)
  const payload = await toTextOrJson(response)

  if (!response.ok) {
    const detail =
      describeDetail(payload?.detail) ||
      describeDetail(payload?.message) ||
      `Request failed with status ${response.status}`
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

// How full the session's context window already is, for the composer's meter.
// ``modelId`` is the model the composer has selected: its input window is the
// denominator, even when the last turn ran on another model.
export async function fetchContextUsage(sessionId, modelId) {
  const query = modelId ? `?${new URLSearchParams({ model_id: modelId }).toString()}` : ""
  return requestJson(`${API_BASE}/api/sessions/${sessionId}/context${query}`)
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

// The cross-session memory library (ADR 0035). ``fetchMemories`` returns the list and
// the switches together, because the page renders them side by side.
export async function fetchMemories() {
  return requestJson(`${API_BASE}/api/memories`)
}

export async function createMemory(memory) {
  return requestJson(`${API_BASE}/api/memories`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(memory),
  })
}

export async function updateMemory(memoryId, patch) {
  return requestJson(`${API_BASE}/api/memories/${encodeURIComponent(memoryId)}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(patch),
  })
}

export async function deleteMemory(memoryId) {
  return requestJson(`${API_BASE}/api/memories/${encodeURIComponent(memoryId)}`, {
    method: "DELETE",
  })
}

export async function updateMemoryConfig(config) {
  return requestJson(`${API_BASE}/api/admin/memory-config`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(config),
  })
}

export async function fetchAgentMeta() {
  return requestJson(`${API_BASE}/api/agents/meta`)
}

export async function fetchTools() {
  const data = await requestJson(`${API_BASE}/api/tools`)
  return data.tools ?? []
}

// Run one tool with hand-written arguments. The response is what the model would
// receive, so a tool that reports an error still answers 200; only a broken
// request (unknown tool) is rejected.
export async function testTool(name, args) {
  return requestJson(`${API_BASE}/api/tools/${encodeURIComponent(name)}/test`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ arguments: args }),
  })
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

export async function fetchProviders() {
  const data = await requestJson(`${API_BASE}/api/providers`)
  return data.providers ?? []
}

export async function createProvider(payload) {
  return requestJson(`${API_BASE}/api/providers`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function updateProvider(providerId, payload) {
  return requestJson(`${API_BASE}/api/providers/${providerId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function deleteProvider(providerId) {
  return requestJson(`${API_BASE}/api/providers/${providerId}`, {
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

// One connection attempt: start the server, handshake, and return its tool list.
export async function probeMcpServer(mcpId) {
  return requestJson(`${API_BASE}/api/mcp-servers/${mcpId}/probe`, {
    method: "POST",
  })
}

// Run one tool of one server with hand-written arguments. A call the server
// reports as failed still answers 200; only an unknown preset is rejected.
export async function testMcpTool(mcpId, toolName, args) {
  return requestJson(
    `${API_BASE}/api/mcp-servers/${encodeURIComponent(mcpId)}/tools/${encodeURIComponent(toolName)}/test`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ arguments: args }),
    }
  )
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

// Branch a new session at this task: it is copied together with every task before
// it in the same conversation, and the original session keeps its own turns.
export async function forkTask(taskId) {
  return requestJson(`${API_BASE}/api/tasks/${taskId}/fork`, {
    method: "POST",
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

// What a task changed, so the list can offer an undo (ADR 0020). ``available`` is
// false when this machine cannot check-point or the run predates the feature, and
// the payload says which - an undo button that cannot work is worse than none.
export async function fetchTaskChanges(taskId) {
  return requestJson(`${API_BASE}/api/tasks/${taskId}/changes`)
}

// One file's patch, fetched on demand: a task can touch enough files to matter.
export async function fetchTaskChangeDiff(taskId, path) {
  const query = new URLSearchParams({ path })
  return requestJson(`${API_BASE}/api/tasks/${taskId}/changes/diff?${query.toString()}`)
}

// Undo everything (``paths`` omitted) or a chosen subset. ``force`` overwrites files
// edited after the task wrote them; without it those come back as conflicts.
export async function revertTask(taskId, { paths = null, force = false } = {}) {
  return requestJson(`${API_BASE}/api/tasks/${taskId}/revert`, {
    method: "POST",
    // Without this header the browser labels a string body ``text/plain``, and the
    // server reads the body as bytes instead of JSON: every undo answered 422 with
    // "Input should be a valid dictionary" (editing and re-running a turn both undo).
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ paths, force }),
  })
}

// Prepare a re-run: undo everything this task changed, then delete it. The order
// matters - deleting the task forgets its checkpoint refs, so an undo after that
// would have no history left to restore from.
//
// ``available: false`` means there is no checkpoint history at all (no git, an old
// run, a missing workspace). There is nothing the undo could restore in that case, so
// the re-run still goes ahead rather than losing its main action.
//
// A file edited after the task wrote it is a conflict: the revert leaves it alone.
// Deleting the task then would throw away the only history that can still undo it, so
// report the blocked paths and let the caller keep the task for the undo dialog.
export async function revertAndDeleteTask(taskId) {
  const changes = await fetchTaskChanges(taskId)
  if (changes.available && changes.files?.length > 0) {
    const result = await revertTask(taskId)
    const blocked = [...(result.conflicts || []), ...(result.skipped || [])]
    if (!result.clean || blocked.length > 0) {
      return { deleted: false, blocked }
    }
  }
  await deleteTask(taskId)
  return { deleted: true, blocked: [] }
}

export async function fetchPermissionModeConfig() {
  return requestJson(`${API_BASE}/api/admin/permission-mode`)
}

export async function updatePermissionModeConfig(mode) {
  return requestJson(`${API_BASE}/api/admin/permission-mode`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ mode }),
  })
}

export async function fetchPermissionRules() {
  return requestJson(`${API_BASE}/api/admin/permission-rules`)
}

export async function createPermissionRule(tool, target) {
  return requestJson(`${API_BASE}/api/admin/permission-rules`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ tool, target }),
  })
}

export async function deletePermissionRule(tool, target) {
  const query = new URLSearchParams({ tool, target }).toString()
  return requestJson(`${API_BASE}/api/admin/permission-rules?${query}`, {
    method: "DELETE",
  })
}

// Static hard denials (ADR 0024): a matching tool + argument combination never
// runs, and the permission gate is never asked about it.
export async function fetchDenyList() {
  return requestJson(`${API_BASE}/api/admin/denylist`)
}

export async function createDenyRule(payload) {
  return requestJson(`${API_BASE}/api/admin/denylist`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function deleteDenyRule(id) {
  const query = new URLSearchParams({ id }).toString()
  return requestJson(`${API_BASE}/api/admin/denylist?${query}`, {
    method: "DELETE",
  })
}

// Answer a pending tool confirmation. ``scope`` is "once", "session" or "always":
// session allows the same tool + target for the rest of the task, always also
// remembers it on disk.
export async function answerPermission(taskId, requestId, allowed, scope = "once") {
  return requestJson(
    `${API_BASE}/api/tasks/${taskId}/permission/${encodeURIComponent(requestId)}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ allowed, scope }),
    }
  )
}

// Answer a pending question batch. ``answers`` is keyed by question id and each value
// is ``{ answers: [...] }`` - the same shape the tool is promised as output. An empty
// object means "skip": the model is told nobody answered and decides for itself.
export async function answerQuestion(taskId, requestId, answers) {
  return requestJson(
    `${API_BASE}/api/tasks/${taskId}/question/${encodeURIComponent(requestId)}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ answers }),
    }
  )
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

export async function fetchAgentsMdConfig() {
  return requestJson(`${API_BASE}/api/admin/agents-md`)
}

export async function updateAgentsMdConfig(enabled, maxBytes) {
  return requestJson(`${API_BASE}/api/admin/agents-md`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ enabled, max_bytes: maxBytes }),
  })
}

// The backend and credentials of the web_search tool. The page's value replaces
// WEB_SEARCH_* from .env and is applied to the next search, not the next restart.
export async function fetchWebSearchConfig() {
  return requestJson(`${API_BASE}/api/admin/web-search`)
}

export async function updateWebSearchConfig(payload) {
  return requestJson(`${API_BASE}/api/admin/web-search`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

// The backend and credentials of the web_fetch tool. The page's value replaces
// WEB_FETCH_* from .env and is applied to the next fetch, not the next restart.
export async function fetchWebFetchConfig() {
  return requestJson(`${API_BASE}/api/admin/web-fetch`)
}

export async function updateWebFetchConfig(payload) {
  return requestJson(`${API_BASE}/api/admin/web-fetch`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

// Scheduled tasks. A schedule names a cron expression and the prompt every run
// sends; each run opens its own session before it creates the task.
export async function fetchSchedules() {
  const data = await requestJson(`${API_BASE}/api/schedules`)
  return data.schedules ?? []
}

// Runs whose task is still running - or waiting for an answer - right now.
export async function fetchRunningSchedules() {
  const data = await requestJson(`${API_BASE}/api/schedules/running`)
  return data.tasks ?? []
}

export async function createSchedule(payload) {
  return requestJson(`${API_BASE}/api/schedules`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function updateSchedule(scheduleId, payload) {
  return requestJson(`${API_BASE}/api/schedules/${scheduleId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })
}

export async function deleteSchedule(scheduleId) {
  return requestJson(`${API_BASE}/api/schedules/${scheduleId}`, {
    method: "DELETE",
  })
}

// Fire a schedule now, paused or not. It goes through the same path as a timed run,
// so the attempt shows up in the history like any other.
export async function runScheduleNow(scheduleId) {
  return requestJson(`${API_BASE}/api/schedules/${scheduleId}/run`, {
    method: "POST",
  })
}

export async function fetchScheduleRuns(scheduleId, limit = 50) {
  const query = new URLSearchParams({ limit: String(limit) }).toString()
  const data = await requestJson(`${API_BASE}/api/schedules/${scheduleId}/runs?${query}`)
  return data.runs ?? []
}

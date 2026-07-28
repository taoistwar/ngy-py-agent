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

export async function fetchTasks() {
  const data = await requestJson(`${API_BASE}/api/tasks`)
  return data.tasks ?? []
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

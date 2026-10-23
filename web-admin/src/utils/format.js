// Small formatting helpers shared by the task pages and the event log.

export function formatTime(value) {
  if (!value) return ""
  const time = new Date(value)
  if (Number.isNaN(time.getTime())) {
    return String(value)
  }
  return time.toLocaleString()
}

export function safeStringify(value) {
  if (value === undefined) return ""
  if (typeof value === "string") {
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch {
      return value
    }
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

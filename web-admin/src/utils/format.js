// Small formatting helpers shared by the task pages and the event log.

export function formatTime(value) {
  if (!value) return ""
  const time = new Date(value)
  if (Number.isNaN(time.getTime())) {
    return String(value)
  }
  return time.toLocaleString()
}

// Wall-clock time in the compact form the detail header has room for: "8.4s",
// "42s", "1m 12s", "1h 05m". A sub-second run keeps one decimal instead of reading
// as "0s", which looks like a figure that failed to load.
export function formatDuration(milliseconds) {
  const ms = Math.max(0, Number(milliseconds) || 0)
  if (ms < 10_000) {
    return `${(ms / 1000).toFixed(1)}s`
  }
  const totalSeconds = Math.round(ms / 1000)
  if (totalSeconds < 60) {
    return `${totalSeconds}s`
  }
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes < 60) {
    return `${minutes}m ${String(seconds).padStart(2, "0")}s`
  }
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`
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

// Narrowing the task log down to what the reader is looking for: the event-type
// filter and the text query are both answered from the page already loaded, so
// typing never waits on the API.
//
// The text index is built once per event page. A single LLM event carries a
// provider-shaped payload of megabytes, so matching a raw blob per keystroke
// would stall the input; the index reads the payload the friendly view reads and
// skips the raw dumps the raw viewer shows on demand.

// How a run unfolds, not alphabetical order: a menu built from one task should
// read like its log. Categories missing from this list are appended sorted.
const CATEGORY_ORDER = [
  "llm_request",
  "llm_response",
  "tool_call",
  "tool_result",
  "file_edit",
  "file_write",
  "file_delete",
  "exec",
  "computer",
  "permission_request",
  "permission_decision",
  "user_question",
  "user_answer",
  "debug",
  "error",
]

// Payloads kept only for the raw viewer (see ``friendlyEvent``); they are the
// provider's own JSON and would dominate both the index and the match rate.
const RAW_PAYLOAD_KEYS = new Set([
  "raw_request",
  "raw_response",
  "request_payload",
  "response_payload",
  "request",
  "tools",
])

// One tool result can carry a whole file. Indexing past this is a memory cost the
// search box never pays back, and the prefix still covers what a reader types.
const MAX_INDEX_CHARS = 200000

export function normalizeCategory(category) {
  return String(category || "").toLowerCase().trim() || "unknown"
}

export function normalizeQuery(query) {
  return String(query || "").trim().toLowerCase()
}

// Flattens a payload into searchable words: keys as well as values, so "tool_call"
// from a payload's own field names is findable too.
function collectText(value, parts) {
  if (value === null || value === undefined) return
  if (typeof value === "string") {
    parts.push(value)
    return
  }
  if (typeof value === "number" || typeof value === "boolean") {
    parts.push(String(value))
    return
  }
  if (Array.isArray(value)) {
    value.forEach((item) => collectText(item, parts))
    return
  }
  if (typeof value === "object") {
    Object.entries(value).forEach(([key, item]) => {
      if (RAW_PAYLOAD_KEYS.has(key)) return
      parts.push(key)
      collectText(item, parts)
    })
  }
}

export function buildEventSearchText(event) {
  const parts = [String(event?.title || ""), normalizeCategory(event?.category)]
  collectText(event?.data, parts)
  return parts.join(" ").toLowerCase().slice(0, MAX_INDEX_CHARS)
}

/** One lowercase haystack per event, keyed by ``event_id``. */
export function buildEventSearchIndex(events) {
  const index = new Map()
  ;(events || []).forEach((event) => {
    if (!event?.event_id) return
    index.set(event.event_id, buildEventSearchText(event))
  })
  return index
}

/** The event types present in ``events``, each with how many events carry it. */
export function collectEventCategories(events) {
  const counts = new Map()
  ;(events || []).forEach((event) => {
    const category = normalizeCategory(event?.category)
    counts.set(category, (counts.get(category) || 0) + 1)
  })

  const rank = (category) => {
    const position = CATEGORY_ORDER.indexOf(category)
    return position === -1 ? CATEGORY_ORDER.length : position
  }

  return [...counts.entries()]
    .map(([category, count]) => ({ category, count }))
    .sort((left, right) => rank(left.category) - rank(right.category) || left.category.localeCompare(right.category))
}

/**
 * The events left after applying ``categories`` (empty set = every type) and
 * ``query`` (empty = no text narrowing). Returns ``events`` untouched when no
 * filter is active, so the unfiltered log keeps its identity across renders.
 */
export function filterEvents(events, { categories, query } = {}, searchIndex) {
  const list = events || []
  const selected = categories instanceof Set ? categories : new Set(categories || [])
  const needle = normalizeQuery(query)
  if (selected.size === 0 && !needle) return list

  return list.filter((event) => {
    if (selected.size > 0 && !selected.has(normalizeCategory(event?.category))) return false
    if (!needle) return true
    const haystack = searchIndex?.get(event?.event_id) ?? buildEventSearchText(event)
    return haystack.includes(needle)
  })
}

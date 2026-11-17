// Labels and argument handling shared by the tool list and the tool test dialog.

import { agentDisplayName } from "./shared"

// Order the list is grouped in; a category the page does not know yet is appended
// after these, in the order the API returned it. Mirrors CATEGORY_KINDS in
// agent/tools/spec.py.
export const CATEGORY_ORDER = [
  "file",
  "network",
  "shell",
  "computer",
  "compute",
  "interaction",
  "other",
]

const CATEGORY_LABEL_KEYS = {
  file: "toolCategoryFile",
  network: "toolCategoryNetwork",
  shell: "toolCategoryShell",
  computer: "toolCategoryComputer",
  compute: "toolCategoryCompute",
  interaction: "toolCategoryInteraction",
  other: "toolCategoryOther",
}

// Confirmation kind -> locale key, mirroring PERMISSION_KINDS in
// agent/tools/permissions.py.
const PERMISSION_LABEL_KEYS = {
  none: "toolPermissionNone",
  read: "toolPermissionRead",
  write: "toolPermissionWrite",
  exec: "toolPermissionExec",
  computer: "toolPermissionComputer",
}

// Answers a tool's confirmation dialog may offer, mirroring SCOPES in
// agent/tools/permissions.py.
const SCOPE_LABEL_KEYS = {
  once: "toolScopeOnce",
  session: "toolScopeSession",
  always: "toolScopeAlways",
}

export function categoryLabel(category, translate) {
  const key = CATEGORY_LABEL_KEYS[category]
  return key ? translate(key) : String(category || "other")
}

/** Split tools into one bucket per category, in display order. */
export function groupTools(tools) {
  const buckets = new Map()
  tools.forEach((tool) => {
    const category = tool.category || "other"
    if (!buckets.has(category)) buckets.set(category, [])
    buckets.get(category).push(tool)
  })

  const known = CATEGORY_ORDER.filter((category) => buckets.has(category))
  const unknown = [...buckets.keys()].filter((category) => !CATEGORY_ORDER.includes(category))
  return [...known, ...unknown].map((category) => ({
    category,
    tools: buckets.get(category),
  }))
}

/**
 * The text to show under the English one, or null.
 *
 * English is the source of truth and is always displayed; a non-English locale
 * adds its own translation underneath. A locale without a translation, or English
 * itself, gets nothing extra - never a partial mix.
 */
export function localizedText(tool, locale) {
  if (!locale || locale === "en") return null
  const text = tool?.description_i18n?.[locale]
  return text && text.description ? text : null
}

export function permissionLabel(permission, translate) {
  const key = PERMISSION_LABEL_KEYS[permission]
  return key ? translate(key) : String(permission || "none")
}

export function scopeSummary(tool, translate) {
  const scopes = Array.isArray(tool?.scopes) ? tool.scopes : []
  if (scopes.length === 0) return "-"
  return scopes.map((scope) => translate(SCOPE_LABEL_KEYS[scope] || scope)).join(" / ")
}

export function parameterCount(tool) {
  const properties = tool?.parameters?.properties
  if (!properties || typeof properties !== "object") return 0
  return Object.keys(properties).length
}

// Agent ids travel in the tool list (the store is the source of truth); the names
// and their translated built-in labels come from the agent list the page already
// has, so an unknown id falls back to the id itself.
export function resolveAgentNames(agentIds, agents, translate) {
  return (agentIds || []).map((agentId) => {
    const agent = (agents || []).find((item) => item.agent_id === agentId)
    return {
      id: agentId,
      label: agent ? agentDisplayName(agent, translate) : agentId,
    }
  })
}

/** Starting form values: schema defaults where present, otherwise empty. */
export function initialValues(params) {
  const values = {}
  params.forEach((param) => {
    const preset = param.defaultValue
    if (preset === undefined || preset === null) {
      values[param.name] = ""
    } else if (typeof preset === "object") {
      values[param.name] = JSON.stringify(preset)
    } else {
      values[param.name] = String(preset)
    }
  })
  return values
}

/**
 * Turn form strings back into the argument values the tool expects.
 *
 * Empty optional arguments are omitted rather than sent as "", because a tool
 * distinguishes "not provided" (use its default) from an empty string. Returns
 * `{ error: { kind, name } }` when a value cannot be converted; the caller
 * translates it (`kind` is `missing` / `number` / `json`).
 */
export function buildArguments(params, values) {
  const args = {}

  for (const param of params) {
    const raw = String(values?.[param.name] ?? "").trim()
    if (!raw) {
      if (param.required) return { error: { kind: "missing", name: param.name } }
      continue
    }

    if (param.type === "boolean") {
      args[param.name] = raw === "true"
    } else if (param.type === "integer" || param.type === "number") {
      const parsed = Number(raw)
      if (!Number.isFinite(parsed)) return { error: { kind: "number", name: param.name } }
      args[param.name] = parsed
    } else if (param.type === "object" || param.type === "array") {
      let parsed
      try {
        parsed = JSON.parse(raw)
      } catch {
        return { error: { kind: "json", name: param.name } }
      }
      args[param.name] = parsed
    } else {
      args[param.name] = raw
    }
  }

  return { arguments: args }
}

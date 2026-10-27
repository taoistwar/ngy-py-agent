// Vocabulary plumbing for the friendly task-log view.
//
// The words themselves live in ``./dictionary`` (one module per locale); this file
// only resolves a locale and looks things up. Splitting them that way keeps a new
// language a self-contained translated file rather than an edit to a shared table.

import { dictionaryForLocale } from "./dictionary/index.js"

/** The vocabulary for ``locale``; English when that locale has none. */
export function dictionaryFor(locale) {
  return dictionaryForLocale(locale)
}

export function fillTemplate(template, params) {
  if (!template) return ""
  return String(template).replace(/\{(\w+)\}/g, (match, name) =>
    params && params[name] !== undefined && params[name] !== null ? String(params[name]) : match,
  )
}

export function fieldLabel(dict, key) {
  const label = dict.fields[key]
  if (label) return label
  const humanized = String(key || "").replace(/[_-]+/g, " ").trim()
  if (!humanized) return ""
  return humanized.charAt(0).toUpperCase() + humanized.slice(1)
}

export function valueLabel(dict, key, value) {
  const table = dict.values[key]
  if (!table) return null
  const lookup = value === null || value === undefined ? "null" : String(value)
  return table[lookup] || null
}

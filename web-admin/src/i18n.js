import de from "./locales/de.json"
import en from "./locales/en.json"
import fr from "./locales/fr.json"
import ru from "./locales/ru.json"
import zhCN from "./locales/zh-CN.json"
import zhTW from "./locales/zh-TW.json"

export const LOCALES = ["en", "zh-CN", "zh-TW", "fr", "de", "ru"]
export const LOCALE_KEY = "web-admin.locale"

const MESSAGES = {
  en,
  "zh-CN": zhCN,
  "zh-TW": zhTW,
  fr,
  de,
  ru,
}

// Chinese regions that write Traditional characters; every other zh tag (CN, SG,
// MY, ...) reads Simplified.
const TRADITIONAL_CHINESE_REGIONS = ["tw", "hk", "mo"]
// Locales where the base language is enough to pick a bundle ("fr-CA" -> "fr").
const BASE_LANGUAGE_LOCALES = ["fr", "de", "ru"]

function isSupportedLocale(locale) {
  return LOCALES.includes(locale)
}

function findSupportedLocale(tag) {
  const lower = String(tag || "").toLowerCase()
  return LOCALES.find((locale) => locale.toLowerCase() === lower) || null
}

/**
 * Maps a BCP 47 tag (``navigator.language``, a saved preference, ...) onto one of
 * ``LOCALES``. Returns ``null`` when nothing matches, so the caller keeps its own
 * default; the event vocabulary in ``src/events/dictionary`` reuses this so both
 * halves of the UI agree on which language is showing.
 */
export function resolveLocale(tag) {
  const exact = findSupportedLocale(tag)
  if (exact) {
    return exact
  }

  const parts = String(tag || "").toLowerCase().replace(/_/g, "-").split("-")
  const language = parts[0]
  const subtags = parts.slice(1)

  if (language === "zh") {
    if (subtags.includes("hant")) {
      return "zh-TW"
    }
    if (subtags.includes("hans")) {
      return "zh-CN"
    }
    return subtags.some((part) => TRADITIONAL_CHINESE_REGIONS.includes(part)) ? "zh-TW" : "zh-CN"
  }

  if (BASE_LANGUAGE_LOCALES.includes(language)) {
    return findSupportedLocale(language)
  }

  return null
}

export function getDefaultLocale() {
  if (typeof window === "undefined") {
    return "en"
  }

  const saved = window.localStorage.getItem(LOCALE_KEY)
  if (isSupportedLocale(saved)) {
    return saved
  }

  return resolveLocale(window.navigator?.language) || "en"
}

export function t(locale, key) {
  const messages = MESSAGES[isSupportedLocale(locale) ? locale : "en"]
  return messages[key] || MESSAGES.en[key] || key
}

export function getLocaleOptions(locale) {
  return LOCALES.map((value) => ({
    value,
    label: t(value, "languageName"),
    current: value === locale,
  }))
}

const TASK_STATUS_TEXT_KEYS = {
  running: "statusRunning",
  waiting: "statusWaiting",
  pending: "statusPending",
  in_progress: "statusInProgress",
  processing: "statusProcessing",
  started: "statusStarted",
  success: "statusSuccess",
  failed: "statusFailed",
  stopped: "statusStopped",
  degraded: "statusDegraded",
  unknown: "statusUnknown",
}

// "waiting" is a blocked-on-the-user state, but the task is still in flight:
// polling must continue, otherwise the UI freezes exactly when it needs to show
// the confirmation dialog (see ADR 0006 D10).
const TASK_RUNNING_STATUS_SET = new Set([
  "running",
  "waiting",
  "pending",
  "in_progress",
  "processing",
  "started",
])

function normalizeTaskStatus(status) {
  return String(status || "").toLowerCase().trim().replace(/\s+/g, "_")
}

export function isTaskRunningStatus(status) {
  return TASK_RUNNING_STATUS_SET.has(normalizeTaskStatus(status))
}

export function getTaskStatusText(translate, status) {
  const key = TASK_STATUS_TEXT_KEYS[normalizeTaskStatus(status)] || TASK_STATUS_TEXT_KEYS.unknown
  return translate(key)
}

export function getTaskStatusClass(status) {
  const normalized = normalizeTaskStatus(status)
  if (normalized === "success" || normalized === "failed" || normalized === "stopped") {
    return normalized
  }
  if (normalized === "waiting") {
    return "waiting"
  }
  if (TASK_RUNNING_STATUS_SET.has(normalized)) {
    return "running"
  }
  return "running"
}

export function getEventCategoryText(translate, category) {
  const key = `category_${String(category || "").toLowerCase()}`
  if (!MESSAGES.en[key]) {
    return translate("category_unknown")
  }
  return translate(key)
}

export { MESSAGES }

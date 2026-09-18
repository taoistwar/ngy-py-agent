import en from "./locales/en.json"
import zhCN from "./locales/zh-CN.json"

export const LOCALES = ["en", "zh-CN"]
export const LOCALE_KEY = "web-admin.locale"

const MESSAGES = {
  en,
  "zh-CN": zhCN,
}

function isSupportedLocale(locale) {
  return LOCALES.includes(locale)
}

export function getDefaultLocale() {
  if (typeof window === "undefined") {
    return "en"
  }

  const saved = window.localStorage.getItem(LOCALE_KEY)
  if (isSupportedLocale(saved)) {
    return saved
  }

  const browserLocale = window.navigator?.language?.toLowerCase()
  if (!browserLocale) {
    return "en"
  }

  if (browserLocale.startsWith("zh")) {
    return "zh-CN"
  }

  return "en"
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

const TASK_RUNNING_STATUS_SET = new Set(["running", "pending", "in_progress", "processing", "started"])

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

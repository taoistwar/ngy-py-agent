// Theme modes shared by the pre-paint bootstrap (index.html) and the React shell.
// The bootstrap script repeats the storage key, so keep both in sync.

export const THEME_STORAGE_KEY = "web-admin.theme"
export const THEMES = ["dark", "light"]

const MONACO_THEMES = {
  dark: "vs-dark",
  light: "light",
}

export function isTheme(value) {
  return THEMES.includes(value)
}

export function getSystemTheme() {
  if (typeof window === "undefined" || !window.matchMedia) return "dark"
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"
}

export function getStoredTheme() {
  if (typeof window === "undefined") return ""
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY)
    return isTheme(saved) ? saved : ""
  } catch {
    return ""
  }
}

export function getInitialTheme() {
  return getStoredTheme() || getSystemTheme()
}

export function applyTheme(theme) {
  if (typeof document === "undefined") return
  const next = isTheme(theme) ? theme : getInitialTheme()
  document.documentElement.setAttribute("data-theme", next)
  document.documentElement.style.colorScheme = next
}

export function saveTheme(theme) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // ignore persistence errors
  }
}

export function getMonacoTheme(theme) {
  return MONACO_THEMES[isTheme(theme) ? theme : "dark"]
}

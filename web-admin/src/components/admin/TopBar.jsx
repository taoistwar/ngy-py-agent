// Application shell header: brand, primary navigation, health, theme and language.
import ThemeToggle from "../ThemeToggle"
import { formatTime } from "../../utils/format"

const MENU_ITEMS = [
  { key: "tasks", labelKey: "menuTasks" },
  { key: "agents", labelKey: "menuAgents" },
  { key: "tools", labelKey: "menuTools" },
  { key: "skills", labelKey: "menuSkills" },
  { key: "mcp", labelKey: "menuMcp" },
  { key: "workspaces", labelKey: "menuWorkspaces" },
  { key: "providers", labelKey: "menuProviders" },
  { key: "models", labelKey: "menuModels" },
  { key: "config", labelKey: "menuConfig" },
]

function getHealthClass(healthStatus) {
  if (healthStatus === "ok") {
    return "success"
  }
  if (healthStatus === "unavailable") {
    return "failed"
  }
  return "running"
}

function getHealthText(healthStatus, translate) {
  if (healthStatus === "ok") {
    return translate("healthOk")
  }
  if (healthStatus === "unavailable") {
    return translate("healthUnavailable")
  }
  if (healthStatus === "degraded") {
    return translate("statusDegraded")
  }
  return translate("unknown")
}

export default function TopBar({
  activeMenu,
  onChangeMenu,
  health,
  locale,
  localeOptions,
  setLocale,
  systemTime,
  translate,
}) {
  return (
    <header className="admin-topbar">
      <div className="topbar-main">
        <div className="topbar-brand">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24">
              <path
                d="M5 16.5V7.5a2 2 0 0 1 3.4-1.4L19 16.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M19 7.5v9"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
              />
            </svg>
          </span>
          <span className="brand-text">
            <h1>{translate("appTitle")}</h1>
            <span className="topbar-subtitle">{translate("appSubtitle")}</span>
          </span>
        </div>
        <div className="topbar-right">
          <div className="metric-item health-metric">
            <em>{translate("healthLabel")}</em>
            <strong className={`status ${getHealthClass(health)}`}>{getHealthText(health, translate)}</strong>
          </div>
          <ThemeToggle translate={translate} />
          <label className="lang-switch">
            <span>{translate("languageLabel")}</span>
            <select
              value={locale}
              className="lang-select"
              onChange={(event) => setLocale(event.target.value)}
            >
              {localeOptions.map((item) => (
                <option value={item.value} key={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <div className="metric-item time-metric">
            <em>{translate("sidebarSystemTime")}</em>
            <strong>{formatTime(systemTime)}</strong>
          </div>
        </div>
      </div>
      <nav className="topbar-nav" aria-label={translate("menuAriaLabel")}>
        {MENU_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`nav-item ${activeMenu === item.key ? "active" : ""}`}
            onClick={() => onChangeMenu(item.key)}
          >
            {translate(item.labelKey)}
          </button>
        ))}
      </nav>
    </header>
  )
}

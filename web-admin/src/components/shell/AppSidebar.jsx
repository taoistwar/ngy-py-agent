// Persistent left navigation. Groups are collapsible second-level sections; the
// whole rail collapses to icons for wide content such as the task console.
import { useEffect, useMemo, useState } from "react"
import { ChevronIcon, SidebarIcon } from "../icons"
import { formatTime } from "../../utils/format"
import { getHealthClass, getHealthText } from "../../utils/health"
import { NAV_GROUPS, NAV_ICONS, findNavLocation } from "./navigation"

const GROUPS_STORAGE_KEY = "web-admin.navGroups"
const COMPACT_QUERY = "(max-width: 1180px)"

// Below the breakpoint the rail is always icon-only; the user preference only
// matters on wide screens, so both states share one render path.
function useIsCompact() {
  const [compact, setCompact] = useState(() =>
    typeof window === "undefined" ? false : window.matchMedia(COMPACT_QUERY).matches
  )

  useEffect(() => {
    const mediaQuery = window.matchMedia(COMPACT_QUERY)
    const handleChange = (event) => setCompact(event.matches)
    mediaQuery.addEventListener("change", handleChange)
    return () => mediaQuery.removeEventListener("change", handleChange)
  }, [])

  return compact
}

function loadOpenGroups() {
  const defaults = Object.fromEntries(NAV_GROUPS.map((group) => [group.key, true]))
  try {
    const saved = JSON.parse(window.localStorage.getItem(GROUPS_STORAGE_KEY) || "null")
    if (saved && typeof saved === "object") return { ...defaults, ...saved }
  } catch {
    // ignore malformed preferences
  }
  return defaults
}

function NavItemIcon({ name }) {
  const ItemIcon = NAV_ICONS[name] || NAV_ICONS.overview
  return (
    <span className="nav-link-icon">
      <ItemIcon />
    </span>
  )
}

export default function AppSidebar({
  activeMenu,
  collapsed,
  health,
  onNavigate,
  onToggleCollapse,
  systemTime,
  translate,
}) {
  const [openGroups, setOpenGroups] = useState(loadOpenGroups)
  const compact = useIsCompact()
  const railMode = collapsed || compact
  const activeGroupKey = useMemo(() => findNavLocation(activeMenu).group.key, [activeMenu])
  const healthClass = getHealthClass(health)
  const healthText = getHealthText(health, translate)
  const toggleLabel = translate(railMode ? "navExpand" : "navCollapse")

  useEffect(() => {
    try {
      window.localStorage.setItem(GROUPS_STORAGE_KEY, JSON.stringify(openGroups))
    } catch {
      // ignore persistence errors
    }
  }, [openGroups])

  useEffect(() => {
    setOpenGroups((prev) => (prev[activeGroupKey] ? prev : { ...prev, [activeGroupKey]: true }))
  }, [activeGroupKey])

  const toggleGroup = (groupKey) => {
    setOpenGroups((prev) => ({ ...prev, [groupKey]: !prev[groupKey] }))
  }

  return (
    <aside className={`app-sidebar${railMode ? " is-collapsed" : ""}`}>
      <div className="sidebar-head">
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
            <path d="M19 7.5v9" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
          </svg>
        </span>
        {!railMode && (
          <span className="brand-text">
            <span className="brand-title">{translate("appTitle")}</span>
            <span className="brand-subtitle">{translate("appSubtitle")}</span>
          </span>
        )}
        {!compact && (
          <button
            type="button"
            className="sidebar-toggle"
            onClick={onToggleCollapse}
            title={toggleLabel}
            aria-label={toggleLabel}
          >
            <SidebarIcon collapsed={railMode} />
          </button>
        )}
      </div>

      {railMode ? (
        <nav className="sidebar-nav sidebar-nav-rail" aria-label={translate("menuAriaLabel")}>
          {NAV_GROUPS.map((group, index) => (
            <div className="nav-rail-group" key={group.key}>
              {index > 0 && <span className="nav-rail-divider" aria-hidden="true" />}
              {group.items.map((item) => {
                const active = item.key === activeMenu
                const label = translate(item.labelKey)
                return (
                  <button
                    key={item.key}
                    type="button"
                    className={`nav-rail-btn${active ? " active" : ""}`}
                    onClick={() => onNavigate(item.key)}
                    title={label}
                    aria-label={label}
                    aria-current={active ? "page" : undefined}
                  >
                    <NavItemIcon name={item.icon} />
                  </button>
                )
              })}
            </div>
          ))}
        </nav>
      ) : (
        <nav className="sidebar-nav" aria-label={translate("menuAriaLabel")}>
          {NAV_GROUPS.map((group) => {
            const isOpen = openGroups[group.key] !== false
            return (
              <div className="nav-group" key={group.key}>
                <button
                  type="button"
                  className={`nav-group-head${isOpen ? " is-open" : ""}`}
                  onClick={() => toggleGroup(group.key)}
                  aria-expanded={isOpen}
                >
                  <span className="nav-group-label">{translate(group.labelKey)}</span>
                  <span className="nav-group-caret">
                    <ChevronIcon />
                  </span>
                </button>
                {isOpen && (
                  <div className="nav-group-items">
                    {group.items.map((item) => {
                      const active = item.key === activeMenu
                      return (
                        <button
                          key={item.key}
                          type="button"
                          className={`nav-link${active ? " active" : ""}`}
                          onClick={() => onNavigate(item.key)}
                          aria-current={active ? "page" : undefined}
                        >
                          <NavItemIcon name={item.icon} />
                          <span className="nav-link-label">{translate(item.labelKey)}</span>
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </nav>
      )}

      <div className="sidebar-foot">
        <span className="sidebar-health" title={`${translate("healthLabel")}: ${healthText}`}>
          <span className={`health-dot ${healthClass}`} aria-hidden="true" />
          {!railMode && (
            <span className="sidebar-foot-text">
              {translate("healthLabel")} · {healthText}
            </span>
          )}
        </span>
        {!railMode && (
          <span className="sidebar-clock">
            {translate("sidebarSystemTime")} · {formatTime(systemTime)}
          </span>
        )}
      </div>
    </aside>
  )
}

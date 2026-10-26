// Page header for the content column. It owns the breadcrumb, the page title and
// the global display preferences, so every page shares the same heading rhythm.
import ThemeToggle from "../ThemeToggle"
import { findNavLocation } from "./navigation"

export default function AppTopbar({ activeMenu, locale, localeOptions, onLocaleChange, translate }) {
  const { group, item } = findNavLocation(activeMenu)

  return (
    <header className="app-topbar">
      <div className="page-heading">
        <span className="page-eyebrow">{translate(group.labelKey)}</span>
        <h1 className="page-title">{translate(item.labelKey)}</h1>
      </div>
      <div className="topbar-actions">
        <ThemeToggle translate={translate} />
        <label className="lang-switch">
          <span className="lang-switch-label">{translate("languageLabel")}</span>
          <select
            value={locale}
            className="lang-select"
            onChange={(event) => onLocaleChange(event.target.value)}
          >
            {localeOptions.map((option) => (
              <option value={option.value} key={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
    </header>
  )
}

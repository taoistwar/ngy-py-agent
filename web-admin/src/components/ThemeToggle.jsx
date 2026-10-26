// Light/dark switch for the top bar. Both options stay visible so the current
// skin is obvious and switching is a single click, not a cycle.
import { useTheme } from "../theme"
import { MoonIcon, SunIcon } from "./icons"

const OPTIONS = [
  { value: "light", labelKey: "themeLight", icon: SunIcon },
  { value: "dark", labelKey: "themeDark", icon: MoonIcon },
]

export default function ThemeToggle({ translate }) {
  const { theme, setTheme } = useTheme()

  return (
    <div className="theme-toggle" role="group" aria-label={translate("themeLabel")}>
      {OPTIONS.map((option) => {
        const OptionIcon = option.icon
        const active = theme === option.value
        return (
          <button
            key={option.value}
            type="button"
            className={`theme-toggle-btn ${active ? "active" : ""}`}
            onClick={() => setTheme(option.value)}
            aria-pressed={active}
            title={translate(option.labelKey)}
          >
            <OptionIcon />
            <span className="theme-toggle-label">{translate(option.labelKey)}</span>
          </button>
        )
      })}
    </div>
  )
}

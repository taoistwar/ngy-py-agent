import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"
import { applyTheme, getInitialTheme, getMonacoTheme, isTheme, saveTheme } from "./modes"

const ThemeContext = createContext({
  theme: "dark",
  monacoTheme: "vs-dark",
  setTheme: () => {},
  toggleTheme: () => {},
})

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(getInitialTheme)

  useEffect(() => {
    applyTheme(theme)
    saveTheme(theme)
  }, [theme])

  const setTheme = useCallback((next) => {
    if (isTheme(next)) setThemeState(next)
  }, [])

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => (prev === "dark" ? "light" : "dark"))
  }, [])

  const value = useMemo(
    () => ({ theme, monacoTheme: getMonacoTheme(theme), setTheme, toggleTheme }),
    [setTheme, theme, toggleTheme]
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  return useContext(ThemeContext)
}

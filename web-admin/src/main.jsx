import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { loader } from "@monaco-editor/react"
import App from "./App"
import { EventStandalonePage } from "./components/EventDetail"
import { getDefaultLocale, t } from "./i18n"
import "./index.css"
import "./App.css"

loader.config({
  paths: {
    vs: `${import.meta.env.BASE_URL}monaco-editor/min/vs`,
  },
})

// `?event=..` renders a single event without the console shell: it is the target of
// the "open in a new tab" button in the task log.
const standaloneEventId = new URLSearchParams(window.location.search).get("event")
const locale = getDefaultLocale()
const translate = (key) => t(locale, key)

createRoot(document.getElementById("root")).render(
  <StrictMode>
    {standaloneEventId ? (
      <EventStandalonePage locale={locale} translate={translate} />
    ) : (
      <App />
    )}
  </StrictMode>,
)

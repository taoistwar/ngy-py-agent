// One event, rendered three ways: inline in the timeline card, as a fullscreen
// overlay, and as a standalone page opened in a new browser tab (?task=..&event=..).
import { useEffect, useMemo, useState } from "react"
import { createPortal } from "react-dom"
import { default as MonacoEditor } from "@monaco-editor/react"
import { fetchTask, fetchTaskEvents } from "../api"
import { buildReasoningView } from "../events/friendlyEvent"
import { getEventCategoryText } from "../i18n"
import { useTheme } from "../theme"
import { formatTime, safeStringify } from "../utils/format"
import EventFriendlyView from "./EventFriendlyView"
import { CloseIcon } from "./icons"

// LLM payloads are long provider-shaped JSON; the rest fit in a small window.
const LLM_EDITOR_HEIGHT = "450px"
const DEFAULT_EDITOR_HEIGHT = "150px"
const EVENT_PAGE_LIMIT = 100
const EVENT_MAX_PAGES = 10

export function eventDetailUrl(event, taskId) {
  const params = new URLSearchParams()
  if (taskId) params.set("task", taskId)
  params.set("event", event.event_id)
  return `${window.location.pathname}?${params.toString()}`
}

export function getRawEventPayload(event) {
  const category = String(event?.category || "").toLowerCase()
  const data = event?.data
  if (!data || typeof data !== "object") {
    return data
  }

  if (category === "llm_request") {
    if (data.raw_request !== undefined) {
      return data.raw_request
    }
    if (data.request_payload !== undefined) {
      return data.request_payload
    }
  }

  if (category === "llm_response") {
    if (data.response !== undefined) {
      return data.response
    }
    if (data.raw_response !== undefined) {
      return data.raw_response
    }
    if (data.response_payload !== undefined) {
      return data.response_payload
    }
  }

  return data
}

export function getTagClass(category) {
  return `tag ${category}`
}

function RawEventView({ event, height }) {
  const { monacoTheme } = useTheme()
  const isLlmPayload = event.category === "llm_request" || event.category === "llm_response"
  return (
    <div className="event-json-editor">
      <MonacoEditor
        height={height || (isLlmPayload ? LLM_EDITOR_HEIGHT : DEFAULT_EDITOR_HEIGHT)}
        defaultLanguage="json"
        defaultValue={safeStringify(getRawEventPayload(event))}
        options={{
          readOnly: true,
          minimap: {
            enabled: false,
          },
          scrollBeyondLastLine: false,
          wordWrap: "on",
          fontSize: 14,
          folding: true,
          lineNumbers: "on",
          renderLineHighlight: "none",
          renderWhitespace: "all",
          automaticLayout: true,
        }}
        theme={monacoTheme}
      />
    </div>
  )
}

/**
 * Tabs plus the two renderings of one event.
 *
 * @param {{event: object, locale: string, translate: Function, actions?: object, height?: string}} props
 * ``actions`` sits at the end of the tab row (new tab / fullscreen buttons).
 */
export function EventDetailBody({ event, locale, translate, actions = null, height }) {
  const reasoning = useMemo(() => buildReasoningView(event, locale), [event, locale])
  // A turn with a trace opens on it: the reasoning is what explains the step, and the
  // answer is one click away. Without a trace the panel belongs to the answer, and
  // the raw JSON stays one click away for whoever debugs the agent.
  const [viewMode, setViewMode] = useState(() => (reasoning ? "reasoning" : "friendly"))

  return (
    <div className="event-detail">
      <div className="event-view-bar">
        <div className="event-view-tabs" role="tablist" aria-label={translate("eventViewSwitchAria")}>
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "friendly"}
            className={`event-view-tab ${viewMode === "friendly" ? "active" : ""}`}
            onClick={() => setViewMode("friendly")}
          >
            {translate("eventViewFriendly")}
          </button>
          {reasoning && (
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === "reasoning"}
              className={`event-view-tab ${viewMode === "reasoning" ? "active" : ""}`}
              onClick={() => setViewMode("reasoning")}
            >
              {translate("eventViewReasoning")}
            </button>
          )}
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "raw"}
            className={`event-view-tab ${viewMode === "raw" ? "active" : ""}`}
            onClick={() => setViewMode("raw")}
          >
            {translate("eventViewRaw")}
          </button>
        </div>
        {actions && <div className="event-view-actions">{actions}</div>}
      </div>
      {viewMode === "friendly" && (
        <EventFriendlyView event={event} locale={locale} translate={translate} />
      )}
      {viewMode === "reasoning" && reasoning && (
        <pre className="event-friendly-text mono event-reasoning-text">{reasoning.text}</pre>
      )}
      {viewMode === "raw" && <RawEventView event={event} height={height} />}
    </div>
  )
}

/** Fullscreen reading view: overlays the console, closes on Esc or the X button. */
export function EventDetailOverlay({ event, locale, translate, onClose }) {
  useEffect(() => {
    const onKeyDown = (keyboardEvent) => {
      if (keyboardEvent.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKeyDown)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [onClose])

  return createPortal(
    <div className="event-overlay" role="dialog" aria-modal="true" aria-label={event.title}>
      <header className="event-overlay-header">
        <div className="event-title">
          <span className={getTagClass(event.category)}>
            {getEventCategoryText(translate, event.category)}
          </span>
          <span>{event.title}</span>
        </div>
        <span className="hint">{formatTime(event.timestamp)}</span>
        <button
          type="button"
          className="icon-btn"
          title={translate("eventFullscreenClose")}
          aria-label={translate("eventFullscreenClose")}
          onClick={onClose}
        >
          <CloseIcon />
        </button>
      </header>
      <div className="event-overlay-body">
        <EventDetailBody
          event={event}
          locale={locale}
          translate={translate}
          height="calc(100vh - 210px)"
        />
      </div>
    </div>,
    document.body,
  )
}

async function findEvent(taskId, eventId) {
  let offset = 0
  for (let page = 0; page < EVENT_MAX_PAGES; page += 1) {
    const result = await fetchTaskEvents(taskId, { offset, limit: EVENT_PAGE_LIMIT })
    const items = result?.items || []
    const match = items.find((item) => item.event_id === eventId)
    if (match) return match
    if (!result?.has_more || items.length === 0) return null
    offset = result.next_offset ?? offset + items.length
  }
  return null
}

/**
 * The page behind the "open in a new tab" button: one event, no console chrome.
 *
 * @param {{locale: string, translate: Function}} props
 */
export function EventStandalonePage({ locale, translate }) {
  const params = new URLSearchParams(window.location.search)
  const taskId = params.get("task") || ""
  const eventId = params.get("event") || ""
  const [state, setState] = useState({ status: "loading", event: null, task: null, error: "" })

  useEffect(() => {
    if (!taskId || !eventId) {
      setState({ status: "missing", event: null, task: null, error: "" })
      return undefined
    }

    let alive = true
    async function load() {
      try {
        const task = await fetchTask(taskId)
        const event = await findEvent(taskId, eventId)
        if (!alive) return
        setState({ status: event ? "ready" : "missing", event, task, error: "" })
      } catch (error) {
        if (!alive) return
        setState({ status: "error", event: null, task: null, error: error?.message || String(error) })
      }
    }
    load()
    return () => {
      alive = false
    }
  }, [taskId, eventId])

  return (
    <div className="event-standalone">
      <header className="event-standalone-header">
        <div className="topbar-brand">
          <h1>{translate("eventStandaloneTitle")}</h1>
          <span className="topbar-subtitle">{translate("eventStandaloneSubtitle")}</span>
        </div>
        {state.task && <span className="hint">{state.task.name || state.task.query}</span>}
      </header>
      <main className="event-standalone-main">
        {state.status === "loading" && <p className="hint">{translate("eventStandaloneLoading")}</p>}
        {state.status === "error" && (
          <p className="hint">
            {translate("eventStandaloneError")}: {state.error}
          </p>
        )}
        {state.status === "missing" && <p className="hint">{translate("eventStandaloneMissing")}</p>}
        {state.event && (
          <>
            <div className="event-standalone-meta">
              <span className={getTagClass(state.event.category)}>
                {getEventCategoryText(translate, state.event.category)}
              </span>
              <h2>{state.event.title}</h2>
              <span className="hint">{formatTime(state.event.timestamp)}</span>
            </div>
            <EventDetailBody
              event={state.event}
              locale={locale}
              translate={translate}
              height="calc(100vh - 250px)"
            />
          </>
        )}
      </main>
    </div>
  )
}

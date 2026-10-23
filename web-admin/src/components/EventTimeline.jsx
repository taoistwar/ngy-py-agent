import { useEffect, useState } from "react"
import { default as MonacoEditor } from "@monaco-editor/react"
import { getEventCategoryText } from "../i18n"
import { formatTime, safeStringify } from "../utils/format"
import EventFriendlyView from "./EventFriendlyView"

// LLM payloads are long provider-shaped JSON; the rest fit in a small window.
const LLM_EDITOR_HEIGHT = "450px"
const DEFAULT_EDITOR_HEIGHT = "150px"

function getRawEventPayload(event) {
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

function getTagClass(category) {
  return `tag ${category}`
}

function RawEventView({ event }) {
  const isLlmPayload = event.category === "llm_request" || event.category === "llm_response"
  return (
    <div className="event-json-editor">
      <MonacoEditor
        height={isLlmPayload ? LLM_EDITOR_HEIGHT : DEFAULT_EDITOR_HEIGHT}
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
        theme="vs-dark"
      />
    </div>
  )
}

function EventItem({ event, collapsed, onToggle, translate, locale }) {
  // Friendly by default: the raw JSON stays one click away for whoever debugs the agent.
  const [viewMode, setViewMode] = useState("friendly")
  const friendly = viewMode === "friendly"

  return (
    <div className="event-card">
      <div className="event-header" onClick={onToggle}>
        <div className="event-title">
          <span className={getTagClass(event.category)}>
            {getEventCategoryText(translate, event.category)}
          </span>
          <span>{event.title}</span>
        </div>
        <div className="hint">{formatTime(event.timestamp)}</div>
      </div>
      {!collapsed && (
        <div className="event-body">
          <div className="event-view-tabs" role="tablist" aria-label={translate("eventViewSwitchAria")}>
            <button
              type="button"
              role="tab"
              aria-selected={friendly}
              className={`event-view-tab ${friendly ? "active" : ""}`}
              onClick={() => setViewMode("friendly")}
            >
              {translate("eventViewFriendly")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={!friendly}
              className={`event-view-tab ${friendly ? "" : "active"}`}
              onClick={() => setViewMode("raw")}
            >
              {translate("eventViewRaw")}
            </button>
          </div>
          {friendly ? (
            <EventFriendlyView event={event} locale={locale} translate={translate} />
          ) : (
            <RawEventView event={event} />
          )}
        </div>
      )}
    </div>
  )
}

export default function EventTimeline({ task, events, hasMore, loadingMore, onLoadMore, translate, locale }) {
  const [collapsedMap, setCollapsedMap] = useState({})

  useEffect(() => {
    const next = {}
    events.forEach((event) => {
      if (collapsedMap[event.event_id] === undefined) {
        next[event.event_id] = event.collapsed ?? true
      }
    })
    if (Object.keys(next).length > 0) {
      setCollapsedMap((prev) => ({ ...prev, ...next }))
    }
  }, [events])

  if (!task) {
    return <div className="timeline-empty">{translate("taskEventsNoTask")}</div>
  }

  // Keep creation order so the earliest event appears first.
  const ordered = events

  return (
    <div>
      {ordered.length === 0 ? (
        <div className="timeline-empty">{translate("taskEventsNoRecords")}</div>
      ) : (
        <div className="timeline">
          {ordered.map((event) => (
            <EventItem
              key={event.event_id}
              event={event}
              collapsed={collapsedMap[event.event_id]}
              onToggle={() =>
                setCollapsedMap((prev) => ({
                  ...prev,
                  [event.event_id]: !prev[event.event_id],
                }))
              }
              translate={translate}
              locale={locale}
            />
          ))}
        </div>
      )}
      {events.length > 0 && (
        <div className="load-more">
          <button type="button" className="btn" onClick={onLoadMore} disabled={loadingMore || !hasMore}>
            {loadingMore ? translate("eventsLoading") : translate("eventsLoadMore")}
          </button>
          {!hasMore && <span className="hint">{translate("eventsNoMore")}</span>}
        </div>
      )}
    </div>
  )
}

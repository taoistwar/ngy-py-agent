import { useEffect, useMemo, useState } from "react"
import { buildEventSearchIndex, collectEventCategories, filterEvents } from "../events/eventFilter"
import { getEventCategoryText, isTaskRunningStatus } from "../i18n"
import { formatTime } from "../utils/format"
import { EventDetailBody, EventDetailOverlay, eventDetailUrl, getTagClass } from "./EventDetail"
import EventFilterBar from "./EventFilterBar"
import {
  ChevronsDownIcon,
  ChevronsUpIcon,
  ExpandIcon,
  ExternalLinkIcon,
  LanguagesIcon,
} from "./icons"

// While a task is in flight the log is a progress feed: the model's answers are what
// the reader is waiting for, so they open on arrival and the tool calls, debug traces
// and permission decisions stay folded. Otherwise a busy step pushes the newest
// answer off screen exactly when it matters.
const LIVE_OPEN_CATEGORIES = new Set(["llm_response"])

function defaultCollapsed(event, running) {
  const category = String(event.category || "").toLowerCase()
  if (running && LIVE_OPEN_CATEGORIES.has(category)) return false
  return event.collapsed ?? true
}

function EventItem({ event, taskId, collapsed, onToggle, translation, translate, locale }) {
  const [fullscreen, setFullscreen] = useState(false)
  const openLabel = translate("eventOpenInNewTab")
  const fullscreenLabel = translate("eventFullscreen")

  const actions = (
    <>
      <a
        className="icon-btn"
        href={eventDetailUrl(event, taskId)}
        target="_blank"
        rel="noopener noreferrer"
        title={openLabel}
        aria-label={openLabel}
      >
        <ExternalLinkIcon />
      </a>
      <button
        type="button"
        className="icon-btn"
        title={fullscreenLabel}
        aria-label={fullscreenLabel}
        onClick={() => setFullscreen(true)}
      >
        <ExpandIcon />
      </button>
    </>
  )

  return (
    <div className="event-card">
      <div className="event-header" onClick={onToggle}>
        <div className="event-title">
          {/* Reachable while the card is collapsed, before the body is shown. */}
          <button
            type="button"
            className="event-fullscreen-btn"
            title={fullscreenLabel}
            aria-label={fullscreenLabel}
            onClick={(clickEvent) => {
              clickEvent.stopPropagation()
              setFullscreen(true)
            }}
          >
            <ExpandIcon />
          </button>
          <span className={getTagClass(event.category)}>
            {getEventCategoryText(translate, event.category)}
          </span>
          <span>{event.title}</span>
        </div>
        <div className="hint">{formatTime(event.timestamp)}</div>
      </div>
      {!collapsed && (
        <div className="event-body">
          <EventDetailBody
            event={event}
            locale={locale}
            translate={translate}
            translation={translation}
            actions={actions}
          />
        </div>
      )}
      {fullscreen && (
        <EventDetailOverlay
          event={event}
          locale={locale}
          translate={translate}
          translation={translation}
          onClose={() => setFullscreen(false)}
        />
      )}
    </div>
  )
}

export default function EventTimeline({
  task,
  events,
  hasMore,
  loadingMore,
  onLoadMore,
  translations = {},
  onTranslateReasoning = null,
  translatingReasoning = false,
  translateNotice = "",
  translate,
  locale,
}) {
  const [collapsedMap, setCollapsedMap] = useState({})
  // Selected event types; an empty set means "every type", so the default view is
  // the whole log with no filter bookkeeping in the way.
  const [selectedCategories, setSelectedCategories] = useState(() => new Set())
  const [query, setQuery] = useState("")
  const taskId = task?.task_id || ""
  const running = isTaskRunningStatus(task?.status)

  // Filters belong to the task being read: carrying them across a task switch
  // would hide the new task's events behind a selection made for the old one.
  useEffect(() => {
    setSelectedCategories(new Set())
    setQuery("")
  }, [taskId])

  useEffect(() => {
    const next = {}
    events.forEach((event) => {
      if (collapsedMap[event.event_id] === undefined) {
        next[event.event_id] = defaultCollapsed(event, running)
      }
    })
    if (Object.keys(next).length > 0) {
      setCollapsedMap((prev) => ({ ...prev, ...next }))
    }
  }, [events, running])

  // Indexed once per page, not once per keystroke: LLM payloads are large enough
  // that re-serializing them on every character would lag the search box.
  const searchIndex = useMemo(() => buildEventSearchIndex(events), [events])
  const categoryOptions = useMemo(() => collectEventCategories(events), [events])
  const visibleEvents = useMemo(
    () => filterEvents(events, { categories: selectedCategories, query }, searchIndex),
    [events, selectedCategories, query, searchIndex],
  )

  if (!task) {
    return <div className="timeline-empty">{translate("taskEventsNoTask")}</div>
  }

  // Keep creation order so the earliest event appears first.
  const ordered = visibleEvents

  // A whole task log can be 100+ events; one click should be enough to see them all
  // (or to get back to the compact list) — for what the filters kept, so a narrowed
  // log is not expanded event by event.
  const setAllCollapsed = (collapsed) => {
    const next = {}
    visibleEvents.forEach((event) => {
      next[event.event_id] = collapsed
    })
    setCollapsedMap(next)
  }

  const toggleCategory = (category) => {
    setSelectedCategories((prev) => {
      const next = new Set(prev)
      if (next.has(category)) {
        next.delete(category)
      } else {
        next.add(category)
      }
      return next
    })
  }

  const selectAllCategories = () => {
    setSelectedCategories(new Set(categoryOptions.map((option) => option.category)))
  }

  const clearCategories = () => setSelectedCategories(new Set())

  const filtersActive = selectedCategories.size > 0 || query.trim() !== ""
  const emptyText = events.length === 0
    ? translate("taskEventsNoRecords")
    : filtersActive
      ? translate("eventFilterNoMatch")
      : translate("taskEventsNoRecords")

  return (
    <div>
      {events.length > 0 && (
        <div className="event-timeline-toolbar">
          <EventFilterBar
            options={categoryOptions}
            selected={selectedCategories}
            onToggleCategory={toggleCategory}
            onSelectAllCategories={selectAllCategories}
            onClearCategories={clearCategories}
            query={query}
            onQueryChange={setQuery}
            matchedCount={visibleEvents.length}
            totalCount={events.length}
            translate={translate}
          />
          <div className="event-toolbar-bulk">
            <button type="button" className="event-bulk-btn" onClick={() => setAllCollapsed(true)}>
              <ChevronsUpIcon />
              {translate("eventsCollapseAll")}
            </button>
            <button type="button" className="event-bulk-btn" onClick={() => setAllCollapsed(false)}>
              <ChevronsDownIcon />
              {translate("eventsExpandAll")}
            </button>
            {/* Far right of the log's toolbar: translates this task's deep-think
                traces into the console's language, skipping the ones already done. */}
            {onTranslateReasoning ? (
              <button
                type="button"
                className="event-bulk-btn event-bulk-icon"
                onClick={() => onTranslateReasoning()}
                disabled={translatingReasoning}
                title={translate("eventsTranslateReasoning")}
                aria-label={translate("eventsTranslateReasoning")}
              >
                <LanguagesIcon />
              </button>
            ) : null}
            {/* What the click did: the pass runs on the server, so without a word here
                the button would look inert for as long as the model takes. */}
            {translateNotice ? (
              <span className="event-translate-note" role="status" aria-live="polite">
                {translate(translateNotice)}
              </span>
            ) : null}
          </div>
        </div>
      )}
      {ordered.length === 0 ? (
        <div className="timeline-empty">{emptyText}</div>
      ) : (
        <div className="timeline">
          {ordered.map((event) => (
            <EventItem
              key={event.event_id}
              event={event}
              taskId={taskId}
              translation={translations[event.event_id] || ""}
              collapsed={collapsedMap[event.event_id] ?? defaultCollapsed(event, running)}
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

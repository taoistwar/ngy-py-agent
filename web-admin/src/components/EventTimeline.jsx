import { useEffect, useState } from "react"
import { getEventCategoryText } from "../i18n"
import { formatTime } from "../utils/format"
import { EventDetailBody, EventDetailOverlay, eventDetailUrl, getTagClass } from "./EventDetail"
import { ChevronsDownIcon, ChevronsUpIcon, ExpandIcon, ExternalLinkIcon } from "./icons"

function EventItem({ event, taskId, collapsed, onToggle, translate, locale }) {
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
            actions={actions}
          />
        </div>
      )}
      {fullscreen && (
        <EventDetailOverlay
          event={event}
          locale={locale}
          translate={translate}
          onClose={() => setFullscreen(false)}
        />
      )}
    </div>
  )
}

export default function EventTimeline({ task, events, hasMore, loadingMore, onLoadMore, translate, locale }) {
  const [collapsedMap, setCollapsedMap] = useState({})
  const taskId = task?.task_id || ""

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

  // A whole task log can be 100+ events; one click should be enough to see them all
  // (or to get back to the compact list).
  const setAllCollapsed = (collapsed) => {
    const next = {}
    events.forEach((event) => {
      next[event.event_id] = collapsed
    })
    setCollapsedMap(next)
  }

  return (
    <div>
      {ordered.length > 0 && (
        <div className="event-timeline-toolbar">
          <button type="button" className="event-bulk-btn" onClick={() => setAllCollapsed(true)}>
            <ChevronsUpIcon />
            {translate("eventsCollapseAll")}
          </button>
          <button type="button" className="event-bulk-btn" onClick={() => setAllCollapsed(false)}>
            <ChevronsDownIcon />
            {translate("eventsExpandAll")}
          </button>
        </div>
      )}
      {ordered.length === 0 ? (
        <div className="timeline-empty">{translate("taskEventsNoRecords")}</div>
      ) : (
        <div className="timeline">
          {ordered.map((event) => (
            <EventItem
              key={event.event_id}
              event={event}
              taskId={taskId}
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

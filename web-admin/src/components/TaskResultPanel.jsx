// The task result pane: the agent's final answer, rendered as Markdown, with the raw
// text one click away and a full-screen reading mode.
//
// The pane used to be a JSON editor only, which showed ``**bold**`` and list markers
// as literal characters - the answer is Markdown, so it reads as Markdown by default.
//
// The body is not a scroll box: the detail pane is the only scroll container, and
// the title bar folds the result away when a long answer takes over the screen.

import { useEffect, useState } from "react"
import { createPortal } from "react-dom"
import { default as MonacoEditor } from "@monaco-editor/react"
import { useTheme } from "../theme"
import { safeStringify } from "../utils/format"
import AutoHeightMonaco from "./AutoHeightMonaco"
import CollapsibleSectionTitle from "./CollapsibleSectionTitle"
import MarkdownView from "./MarkdownView"
import { CloseIcon, ExpandIcon } from "./icons"

// The overlay body is a flex column, so the editor can claim whatever is left.
const FULLSCREEN_EDITOR_HEIGHT = "100%"

const VIEW_RENDERED = "rendered"
const VIEW_SOURCE = "source"

const SOURCE_EDITOR_OPTIONS = {
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
  automaticLayout: true,
}

function SourceView({ text, theme, fullscreen }) {
  if (fullscreen) {
    return (
      <MonacoEditor
        height={FULLSCREEN_EDITOR_HEIGHT}
        language="markdown"
        value={text}
        options={SOURCE_EDITOR_OPTIONS}
        theme={theme}
      />
    )
  }

  return (
    <AutoHeightMonaco value={text} language="markdown" theme={theme} options={SOURCE_EDITOR_OPTIONS} />
  )
}

function ResultTabs({ view, onChange, translate }) {
  return (
    // Pill tabs are shared with the event view; keeping the class keeps both panels
    // looking like the same control instead of a near-copy.
    <div className="event-view-tabs" role="tablist" aria-label={translate("detailResult")}>
      <button
        type="button"
        role="tab"
        aria-selected={view === VIEW_RENDERED}
        className={`event-view-tab ${view === VIEW_RENDERED ? "active" : ""}`}
        onClick={() => onChange(VIEW_RENDERED)}
      >
        {translate("detailResultRendered")}
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={view === VIEW_SOURCE}
        className={`event-view-tab ${view === VIEW_SOURCE ? "active" : ""}`}
        onClick={() => onChange(VIEW_SOURCE)}
      >
        {translate("detailResultSource")}
      </button>
    </div>
  )
}

function ResultBody({ text, markdown, view, fullscreen }) {
  const { monacoTheme } = useTheme()

  if (markdown && view === VIEW_RENDERED) {
    return (
      <div className={`task-result-markdown ${fullscreen ? "is-fullscreen" : ""}`}>
        <MarkdownView text={text} />
      </div>
    )
  }

  return (
    <div className="detail-json-editor">
      <SourceView text={text} theme={monacoTheme} fullscreen={fullscreen} />
    </div>
  )
}

/** Full-screen reading view: overlays the console, closes on Esc or the X button. */
function ResultOverlay({ translate, view, onViewChange, markdown, onClose, children }) {
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
    <div
      className="task-result-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={translate("detailResult")}
    >
      <header className="task-result-overlay-header">
        <p className="detail-section-title">{translate("detailResult")}</p>
        {markdown ? <ResultTabs view={view} onChange={onViewChange} translate={translate} /> : null}
        <button
          type="button"
          className="icon-btn"
          title={translate("detailResultExitFullscreen")}
          aria-label={translate("detailResultExitFullscreen")}
          onClick={onClose}
        >
          <CloseIcon />
        </button>
      </header>
      <div className="task-result-overlay-body">{children}</div>
    </div>,
    document.body,
  )
}

export default function TaskResultPanel({ result, translate, onOpenChanges }) {
  const hasResult = result !== undefined && result !== null
  // A structured result is JSON: rendering it as Markdown would only reflow the braces.
  const markdown = typeof result === "string"
  const text = hasResult ? (markdown ? result : safeStringify(result)) : ""
  const empty = !hasResult || !text.trim()
  const [view, setView] = useState(markdown ? VIEW_RENDERED : VIEW_SOURCE)
  const [fullscreen, setFullscreen] = useState(false)
  const [open, setOpen] = useState(true)

  const renderBody = (isFullscreen) => (
    <ResultBody
      text={text}
      markdown={markdown}
      view={view}
      fullscreen={isFullscreen}
    />
  )

  const showTabs = open && !empty && markdown

  return (
    <>
      <section className={`detail-section detail-section-result${open ? "" : " is-collapsed"}`}>
        <div className="detail-section-header">
          <CollapsibleSectionTitle
            title={translate("detailResult")}
            open={open}
            onToggle={() => setOpen((previous) => !previous)}
            translate={translate}
          />
          <div className="task-result-actions">
            {showTabs ? <ResultTabs view={view} onChange={setView} translate={translate} /> : null}
            {open ? (
              <button
                type="button"
                className="icon-btn"
                title={translate("detailResultFullscreen")}
                aria-label={translate("detailResultFullscreen")}
                disabled={empty}
                onClick={() => setFullscreen(true)}
              >
                <ExpandIcon />
              </button>
            ) : null}
            <button type="button" className="btn btn-compact" onClick={onOpenChanges}>
              {translate("taskChangesView")}
            </button>
          </div>
        </div>
        {open ? (
          empty ? (
            <p className="hint">{translate("detailNoResult")}</p>
          ) : fullscreen ? null : (
            renderBody(false)
          )
        ) : null}
      </section>
      {fullscreen && !empty ? (
        <ResultOverlay
          translate={translate}
          view={view}
          onViewChange={setView}
          markdown={markdown}
          onClose={() => setFullscreen(false)}
        >
          {renderBody(true)}
        </ResultOverlay>
      ) : null}
    </>
  )
}

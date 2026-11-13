// The task result pane: the agent's final answer, rendered as Markdown, with the raw
// text one click away and a full-screen reading mode.
//
// The pane used to be a JSON editor only, which showed ``**bold**`` and list markers
// as literal characters - the answer is Markdown, so it reads as Markdown by default.

import { useEffect, useState } from "react"
import { createPortal } from "react-dom"
import { default as MonacoEditor } from "@monaco-editor/react"
import { useTheme } from "../theme"
import { safeStringify } from "../utils/format"
import MarkdownView from "./MarkdownView"
import { CloseIcon, ExpandIcon } from "./icons"

const INLINE_EDITOR_HEIGHT = "180px"
// The overlay body is a flex column, so the editor can claim whatever is left.
const FULLSCREEN_EDITOR_HEIGHT = "100%"

const VIEW_RENDERED = "rendered"
const VIEW_SOURCE = "source"

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

function ResultBody({ text, markdown, view, height, fullscreen }) {
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
      <MonacoEditor
        height={height}
        defaultLanguage="markdown"
        value={text}
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
          automaticLayout: true,
        }}
        theme={monacoTheme}
      />
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

  const renderBody = (isFullscreen) => (
    <ResultBody
      text={text}
      markdown={markdown}
      view={view}
      height={isFullscreen ? FULLSCREEN_EDITOR_HEIGHT : INLINE_EDITOR_HEIGHT}
      fullscreen={isFullscreen}
    />
  )

  return (
    <>
      <section className="detail-section detail-section-result">
        <div className="detail-section-header">
          <p className="detail-section-title">{translate("detailResult")}</p>
          <div className="task-result-actions">
            {empty || !markdown ? null : (
              <ResultTabs view={view} onChange={setView} translate={translate} />
            )}
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
            <button type="button" className="btn btn-compact" onClick={onOpenChanges}>
              {translate("taskChangesView")}
            </button>
          </div>
        </div>
        {empty ? <p className="hint">{translate("detailNoResult")}</p> : fullscreen ? null : renderBody(false)}
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

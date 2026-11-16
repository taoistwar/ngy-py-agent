// The task result pane: the agent's final answer, rendered as Markdown, with the raw
// text one click away, a copy button that takes the whole answer to the clipboard, and
// a full-screen reading mode. The header also prints what the run cost - total tokens
// (click for the input/output split) and wall-clock time.
//
// The pane used to be a JSON editor only, which showed ``**bold**`` and list markers
// as literal characters - the answer is Markdown, so it reads as Markdown by default.
//
// The body is not a scroll box: the detail pane is the only scroll container, and
// the title bar folds the result away when a long answer takes over the screen.

import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { default as MonacoEditor } from "@monaco-editor/react"
import { useTheme } from "../theme"
import { copyText } from "../utils/clipboard"
import { formatTokenTotal } from "../utils/contextUsage"
import { formatDuration, safeStringify } from "../utils/format"
import AutoHeightMonaco from "./AutoHeightMonaco"
import CollapsibleSectionTitle from "./CollapsibleSectionTitle"
import MarkdownView from "./MarkdownView"
import { CheckIcon, CloseIcon, CopyIcon, ExpandIcon } from "./icons"

// The overlay body is a flex column, so the editor can claim whatever is left.
const FULLSCREEN_EDITOR_HEIGHT = "100%"

const VIEW_RENDERED = "rendered"
const VIEW_SOURCE = "source"

const COPY_IDLE = "idle"
const COPY_DONE = "done"
const COPY_FAILED = "failed"

// How long the copy button keeps its tick before going back to the copy glyph.
const COPY_FEEDBACK_MS = 1600

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

/**
 * What this run spent, next to the result's controls.
 *
 * The total is the headline, because that is the figure a user compares across runs;
 * the input/output split - the pair that actually explains the total - is one click
 * away instead of taking two chips of the header for itself.
 */
function ResultUsage({ usage, durationMs, translate }) {
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    // Clicking anywhere else, or pressing Esc, closes the split: a panel that only
    // closes from its own chip feels stuck once the eye has moved on.
    const onPointerDown = (event) => {
      if (!wrapperRef.current?.contains(event.target)) setOpen(false)
    }
    const onKeyDown = (event) => {
      if (event.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", onPointerDown)
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("mousedown", onPointerDown)
      document.removeEventListener("keydown", onKeyDown)
    }
  }, [open])

  const input = Number(usage?.input_tokens) || 0
  const output = Number(usage?.output_tokens) || 0
  const total = Number(usage?.total_tokens) || input + output

  return (
    <div className="task-result-usage" ref={wrapperRef}>
      <button
        type="button"
        className="task-result-stat"
        aria-expanded={open}
        title={translate("detailTokensHint")}
        onClick={() => setOpen((previous) => !previous)}
      >
        {translate("detailTokens")}
        {formatTokenTotal(total)}
      </button>
      <span className="task-result-stat">
        {translate("detailDuration")}
        {formatDuration(durationMs)}
      </span>
      {open ? (
        <div className="task-result-usage-tip" role="tooltip">
          <span className="task-result-usage-row">
            <span>{translate("composerContextInput")}</span>
            <strong>{input.toLocaleString()}</strong>
          </span>
          <span className="task-result-usage-row">
            <span>{translate("composerContextOutput")}</span>
            <strong>{output.toLocaleString()}</strong>
          </span>
          <span className="task-result-usage-row is-total">
            <span>{translate("detailTokensTotal")}</span>
            <strong>{total.toLocaleString()}</strong>
          </span>
        </div>
      ) : null}
    </div>
  )
}

/**
 * Copies the answer's raw text - what is on screen may be rendered Markdown, but the
 * source is what pastes cleanly into an editor or a chat message.
 *
 * The outcome is reported in place (a tick, or a red glyph on failure) instead of a
 * toast: a toast would cover the answer the user is reading.
 */
function ResultCopyButton({ text, disabled, translate }) {
  const [state, setState] = useState(COPY_IDLE)
  const timerRef = useRef(null)

  // A re-run or another task changes the text; a stale tick would lie about it.
  useEffect(() => {
    setState(COPY_IDLE)
    window.clearTimeout(timerRef.current)
  }, [text])

  // The pane can unmount while the feedback is still ticking down.
  useEffect(() => () => window.clearTimeout(timerRef.current), [])

  const copy = async () => {
    const copied = await copyText(text)
    setState(copied ? COPY_DONE : COPY_FAILED)
    window.clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(() => setState(COPY_IDLE), COPY_FEEDBACK_MS)
  }

  const label =
    state === COPY_DONE
      ? translate("detailResultCopyDone")
      : state === COPY_FAILED
        ? translate("detailResultCopyFailed")
        : translate("detailResultCopy")

  const className = [
    "icon-btn",
    state === COPY_DONE ? "is-copied" : "",
    state === COPY_FAILED ? "icon-btn-danger" : "",
  ]
    .filter(Boolean)
    .join(" ")

  return (
    <button
      type="button"
      className={className}
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={copy}
    >
      {state === COPY_DONE ? <CheckIcon /> : <CopyIcon />}
    </button>
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

export default function TaskResultPanel({ result, usage, durationMs, translate, onOpenChanges }) {
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
            <ResultUsage usage={usage} durationMs={durationMs} translate={translate} />
            {showTabs ? <ResultTabs view={view} onChange={setView} translate={translate} /> : null}
            {open ? (
              <>
                <ResultCopyButton text={text} disabled={empty} translate={translate} />
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
              </>
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

// One text block of the friendly event view, plus the two things a reader of a long
// payload asks for: the answer as rendered Markdown (like the task result pane), and
// display-only tools that reformat the same text without touching the stored event.
//
// Every tool is a view: switching tabs or pressing a chip recomputes what is shown
// from the block's own copy, so the log entry stays the record it always was.

import { useEffect, useMemo, useState } from "react"
import { TEXT_TRANSFORMS, isJsonText, jsonFieldEntries } from "../utils/textTransforms"
import EventTextCleanDialog from "./EventTextCleanDialog"
import MarkdownView from "./MarkdownView"

// Above this size a block is folded: one tool result can carry a whole file.
const TEXT_PREVIEW_CHARS = 480
const TEXT_PREVIEW_LINES = 10

const VIEW_RENDERED = "rendered"
const VIEW_SOURCE = "source"

function isLong(text) {
  return text.length > TEXT_PREVIEW_CHARS || text.split("\n").length > TEXT_PREVIEW_LINES
}

function previewOf(text) {
  const byChars = text.slice(0, TEXT_PREVIEW_CHARS)
  const byLines = text.split("\n").slice(0, TEXT_PREVIEW_LINES).join("\n")
  return byChars.length <= byLines.length ? `${byChars}…` : `${byLines}…`
}

/**
 * @param {{text: string, mono?: boolean, markdown?: boolean, transforms?: boolean,
 *          translate: (key: string) => string}} props
 * ``markdown`` adds the rendered/source switch; ``transforms`` adds the chip row.
 */
export default function EventTextBlock({
  text = "",
  mono = false,
  markdown = false,
  transforms = false,
  translate,
}) {
  const [expanded, setExpanded] = useState(false)
  const [view, setView] = useState(markdown ? VIEW_RENDERED : VIEW_SOURCE)
  // What is on screen may be a transformed copy; a new event resets it (a transform
  // of the previous event shown under the new one's title would be a lie).
  const [value, setValue] = useState(text)
  const [cleaning, setCleaning] = useState(false)

  useEffect(() => {
    setValue(text)
    setExpanded(false)
    setCleaning(false)
  }, [text])

  // React reuses this instance when the panel switches to another event's block: a
  // component that turns into a rendered answer must not inherit "source" from the
  // tool arguments it used to show.
  useEffect(() => {
    setView(markdown ? VIEW_RENDERED : VIEW_SOURCE)
  }, [markdown])

  const valueIsJson = useMemo(() => isJsonText(value), [value])
  // The cleaning dialog works per named parameter, so it only makes sense on a JSON
  // object; the chip row hides the button for text that has no fields to list.
  const cleanFields = useMemo(() => jsonFieldEntries(value), [value])
  const long = isLong(value)
  const hasText = value.trim() !== ""
  const showTools = transforms && hasText
  const showRenderTabs = markdown && hasText
  const rendered = markdown && view === VIEW_RENDERED

  return (
    <div className="event-text-block">
      {(showTools || showRenderTabs) && (
        <div className="event-text-controls">
          {showTools && (
            <div className="event-text-tools" role="group" aria-label={translate("eventTextToolsAria")}>
              {TEXT_TRANSFORMS.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  className="event-text-tool"
                  disabled={Boolean(item.jsonOnly) && !valueIsJson}
                  onClick={() => setValue(item.apply(value))}
                >
                  {translate(item.label)}
                </button>
              ))}
              {/* Opens the same tools on single parameters of this JSON object;
                  kept last and marked because it leaves the block for a dialog. */}
              {cleanFields && (
                <button
                  type="button"
                  className="event-text-tool event-text-tool-clean"
                  onClick={() => setCleaning(true)}
                >
                  {translate("eventTextClean")}
                </button>
              )}
            </div>
          )}
          {showRenderTabs && (
            <div className="event-view-tabs" role="tablist" aria-label={translate("eventViewSwitchAria")}>
              <button
                type="button"
                role="tab"
                aria-selected={view === VIEW_RENDERED}
                className={`event-view-tab ${view === VIEW_RENDERED ? "active" : ""}`}
                onClick={() => setView(VIEW_RENDERED)}
              >
                {translate("detailResultRendered")}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === VIEW_SOURCE}
                className={`event-view-tab ${view === VIEW_SOURCE ? "active" : ""}`}
                onClick={() => setView(VIEW_SOURCE)}
              >
                {translate("detailResultSource")}
              </button>
            </div>
          )}
        </div>
      )}
      {rendered ? (
        <div className="event-friendly-markdown">
          <MarkdownView text={value} />
        </div>
      ) : (
        <div className="event-friendly-text-wrap">
          <pre className={`event-friendly-text ${mono ? "mono" : ""}`}>
            {long && !expanded ? previewOf(value) : value}
          </pre>
          {long && (
            <button
              type="button"
              className="event-friendly-toggle"
              onClick={() => setExpanded((previous) => !previous)}
            >
              {expanded ? translate("eventShowLess") : translate("eventShowMore")}
            </button>
          )}
        </div>
      )}
      {cleaning && cleanFields && (
        <EventTextCleanDialog
          fields={cleanFields}
          translate={translate}
          onClose={() => setCleaning(false)}
        />
      )}
    </div>
  )
}

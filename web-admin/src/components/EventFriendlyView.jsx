import { useMemo, useState } from "react"
import { buildFriendlyEvent } from "../events/friendlyEvent"

// Above this size a block is folded: one tool result can carry a whole file.
const TEXT_PREVIEW_CHARS = 480
const TEXT_PREVIEW_LINES = 10

function CollapsibleText({ text, mono, translate }) {
  const [expanded, setExpanded] = useState(false)
  const lines = text.split("\n")
  const isLong = text.length > TEXT_PREVIEW_CHARS || lines.length > TEXT_PREVIEW_LINES

  let visible = text
  if (isLong && !expanded) {
    const byChars = text.slice(0, TEXT_PREVIEW_CHARS)
    const byLines = lines.slice(0, TEXT_PREVIEW_LINES).join("\n")
    visible = byChars.length <= byLines.length ? `${byChars}…` : `${byLines}…`
  }

  return (
    <div className="event-friendly-text-wrap">
      <pre className={`event-friendly-text ${mono ? "mono" : ""}`}>{visible}</pre>
      {isLong && (
        <button type="button" className="event-friendly-toggle" onClick={() => setExpanded((prev) => !prev)}>
          {expanded ? translate("eventShowLess") : translate("eventShowMore")}
        </button>
      )}
    </div>
  )
}

function KeyValueTable({ rows }) {
  return (
    <table className="event-kv">
      <tbody>
        {rows.map((row, index) => (
          <tr key={`${row.label}-${index}`}>
            <th scope="row">{row.label}</th>
            <td className={row.mono ? "mono" : ""}>{row.value || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ThinkingBlock({ section, translate }) {
  const [open, setOpen] = useState(false)

  // The body is mounted only once the reader opens it: a reasoning trace can run to
  // thousands of characters and every LLM step in the log carries one.
  return (
    <div className="event-friendly-section">
      <button
        type="button"
        className="event-thinking-toggle"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className="event-thinking-title">{section.title}</span>
        <span className="event-thinking-meta">{section.meta}</span>
        <span className="event-thinking-action">
          {open ? translate("eventShowLess") : translate("eventShowMore")}
        </span>
      </button>
      {open && <pre className="event-friendly-text mono">{section.text}</pre>}
    </div>
  )
}

function Section({ section, translate }) {
  if (section.kind === "thinking") {
    return <ThinkingBlock section={section} translate={translate} />
  }

  return (
    <div className="event-friendly-section">
      <p className="event-friendly-section-title">{section.title}</p>
      {section.kind === "text" && (
        <CollapsibleText text={section.text} mono={section.mono} translate={translate} />
      )}
      {section.kind === "entries" && <KeyValueTable rows={section.rows} />}
      {section.kind === "blocks" && (
        <div className="event-friendly-items">
          {section.items.map((item, index) => (
            <article className="event-friendly-item" key={`${item.title}-${index}`}>
              <header>
                <span className="event-friendly-item-title">{item.title}</span>
                {item.meta && <span className="event-friendly-item-meta">{item.meta}</span>}
              </header>
              {item.text && <CollapsibleText text={item.text} mono translate={translate} />}
            </article>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * Readable rendering of one task event, aimed at people who do not read raw JSON.
 *
 * @param {{event: object, locale: string, translate: (key: string) => string}} props
 */
export default function EventFriendlyView({ event, locale, translate }) {
  const view = useMemo(() => buildFriendlyEvent(event, locale), [event, locale])
  const isEmpty = view.fields.length === 0 && view.sections.length === 0

  return (
    <div className={`event-friendly tone-${view.tone}`}>
      <p className="event-friendly-headline">{view.headline}</p>
      {view.fields.length > 0 && <KeyValueTable rows={view.fields} />}
      {view.sections.map((section, index) => (
        <Section section={section} translate={translate} key={`${section.title}-${index}`} />
      ))}
      {isEmpty && <p className="hint">{view.emptyText}</p>}
    </div>
  )
}

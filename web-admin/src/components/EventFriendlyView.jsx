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

function Section({ section, translate }) {
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
 * The reasoning trace is deliberately absent: it has its own tab next to this one,
 * because folding it in here buried the answer under it.
 *
 * @param {{event: object, locale: string, translate: (key: string) => string}} props
 */
export default function EventFriendlyView({ event, locale, translate }) {
  const view = useMemo(() => buildFriendlyEvent(event, locale), [event, locale])
  const sections = view.sections.filter((section) => section.kind !== "thinking")
  const isEmpty = view.fields.length === 0 && sections.length === 0

  return (
    <div className={`event-friendly tone-${view.tone}`}>
      <p className="event-friendly-headline">{view.headline}</p>
      {view.fields.length > 0 && <KeyValueTable rows={view.fields} />}
      {sections.map((section, index) => (
        <Section section={section} translate={translate} key={`${section.title}-${index}`} />
      ))}
      {isEmpty && <p className="hint">{view.emptyText}</p>}
    </div>
  )
}

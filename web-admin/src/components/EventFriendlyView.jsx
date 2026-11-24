import { useMemo } from "react"
import { buildFriendlyEvent } from "../events/friendlyEvent"
import EventTextBlock from "./EventTextBlock"

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
        <EventTextBlock
          text={section.text}
          mono={section.mono}
          markdown={section.markdown}
          transforms={section.transforms}
          translate={translate}
        />
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
              {item.text && (
                <EventTextBlock
                  text={item.text}
                  mono
                  markdown={item.markdown}
                  transforms={item.transforms}
                  translate={translate}
                />
              )}
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

// Detail section titles double as fold toggles: long prompts and long results
// can be tucked away instead of pushing everything else down the pane.
import { ChevronIcon } from "./icons"

export default function CollapsibleSectionTitle({ title, open, onToggle, translate }) {
  return (
    <button
      type="button"
      className={`detail-section-title detail-section-toggle${open ? " is-open" : ""}`}
      aria-expanded={open}
      title={translate(open ? "detailSectionCollapse" : "detailSectionExpand")}
      onClick={onToggle}
    >
      <span className="detail-section-caret" aria-hidden="true">
        <ChevronIcon />
      </span>
      <span>{title}</span>
    </button>
  )
}

import { useEffect } from "react"
import { createPortal } from "react-dom"

/**
 * Shared admin dialog. Renders into a portal on document.body so the panel is
 * never clipped by the surrounding layout, and closes on Escape / backdrop click.
 */
export default function Modal({
  title,
  hint,
  closeLabel,
  onClose,
  children,
  wide = false,
  dismissible = true,
}) {
  useEffect(() => {
    if (!dismissible) {
      return undefined
    }
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        onClose()
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [onClose, dismissible])

  return createPortal(
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (dismissible && event.target === event.currentTarget) {
          onClose()
        }
      }}
    >
      <section
        className={`panel modal-dialog ${wide ? "modal-dialog-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="panel-titlebar">
          <div>
            <h2>{title}</h2>
            {hint ? <span className="hint">{hint}</span> : null}
          </div>
          <button type="button" className="btn btn-compact" onClick={onClose}>
            {closeLabel}
          </button>
        </div>
        <div className="panel-body modal-dialog-body">{children}</div>
      </section>
    </div>,
    document.body
  )
}

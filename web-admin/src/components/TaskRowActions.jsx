// Row actions collapsed behind one "more" button: edit, re-run, fork into a new
// session, undo what it changed, and delete. They used to sit inline, but five
// icon buttons crowded the meta line of every row.
//
// The menu is portaled to the body and positioned with viewport coordinates,
// because the task list scrolls (`overflow: auto`) and would clip it.

import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"

import { EditIcon, ForkIcon, MoreIcon, RerunIcon, TrashIcon, UndoIcon } from "./icons"

// Rough menu box, used to flip it above the button and keep it on screen.
const MENU_WIDTH = 184
const MENU_HEIGHT = 216

function anchorFromRect(rect) {
  const spaceBelow = window.innerHeight - rect.bottom
  const openUpward = spaceBelow < MENU_HEIGHT && rect.top > spaceBelow
  return {
    // Right-aligned with the trigger: the button sits at the row's right edge.
    left: Math.round(Math.max(8, Math.min(rect.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8))),
    top: openUpward ? undefined : Math.round(rect.bottom + 4),
    bottom: openUpward ? Math.round(window.innerHeight - rect.top + 4) : undefined,
    openUpward,
  }
}

export default function TaskRowActions({
  running,
  onEdit,
  onRerun,
  onFork,
  onRevert,
  onDelete,
  translate,
}) {
  const [anchor, setAnchor] = useState(null)
  const buttonRef = useRef(null)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!anchor) return undefined
    const closeOnOutsideClick = (event) => {
      // The trigger is excluded: it toggles the menu by itself.
      if (buttonRef.current?.contains(event.target)) return
      if (menuRef.current?.contains(event.target)) return
      setAnchor(null)
    }
    const closeOnEscape = (event) => {
      if (event.key !== "Escape") return
      setAnchor(null)
      buttonRef.current?.focus()
    }
    const closeOnViewportChange = () => setAnchor(null)
    window.addEventListener("click", closeOnOutsideClick)
    window.addEventListener("keydown", closeOnEscape)
    window.addEventListener("resize", closeOnViewportChange)
    window.addEventListener("scroll", closeOnViewportChange, true)
    return () => {
      window.removeEventListener("click", closeOnOutsideClick)
      window.removeEventListener("keydown", closeOnEscape)
      window.removeEventListener("resize", closeOnViewportChange)
      window.removeEventListener("scroll", closeOnViewportChange, true)
    }
  }, [anchor])

  const toggle = (event) => {
    // Opening the menu must not also select the row underneath.
    event.stopPropagation()
    if (anchor) {
      setAnchor(null)
      return
    }
    const rect = buttonRef.current?.getBoundingClientRect()
    setAnchor(rect ? anchorFromRect(rect) : null)
  }

  // Editing, re-running, forking or undoing a running task would work from a turn
  // that is still writing; deleting stays available.
  const items = [
    { key: "edit", label: translate("taskEdit"), icon: <EditIcon />, run: onEdit, disabled: running },
    { key: "rerun", label: translate("taskRerun"), icon: <RerunIcon />, run: onRerun, disabled: running },
    { key: "fork", label: translate("taskFork"), icon: <ForkIcon />, run: onFork, disabled: running },
    { key: "revert", label: translate("taskRevert"), icon: <UndoIcon />, run: onRevert, disabled: running },
    { key: "delete", label: translate("taskDelete"), icon: <TrashIcon />, run: onDelete, danger: true },
  ]

  const pick = (item) => {
    if (item.disabled) return
    setAnchor(null)
    item.run()
  }

  const label = translate("taskMoreActions")

  return (
    <div className="task-row-actions">
      <button
        ref={buttonRef}
        type="button"
        className={`icon-btn task-row-actions-trigger ${anchor ? "active" : ""}`}
        title={label}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={anchor ? "true" : "false"}
        onClick={toggle}
      >
        <MoreIcon />
      </button>
      {anchor &&
        createPortal(
          <div
            ref={menuRef}
            className={`task-row-menu ${anchor.openUpward ? "upward" : ""}`}
            role="menu"
            aria-label={label}
            style={{ left: `${anchor.left}px`, top: anchor.top, bottom: anchor.bottom }}
          >
            {items.map((item) => (
              <button
                key={item.key}
                type="button"
                role="menuitem"
                className={`task-row-menu-item ${item.danger ? "danger" : ""}`}
                disabled={Boolean(item.disabled)}
                onClick={(event) => {
                  event.stopPropagation()
                  pick(item)
                }}
              >
                {item.icon}
                <span className="task-row-menu-label">{item.label}</span>
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  )
}

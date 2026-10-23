// Agent dropdown used by the task composer: one icon + name per agent, plus the
// "create agent" entry. A native <select> cannot show the icons, so this mirrors
// the skill picker: a button plus a portal menu (the composer panel clips
// absolutely positioned children at the bottom of the column).

import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"

import { AgentIcon, agentIconName } from "./agentIcons"
import { agentDisplayName } from "./admin/shared"

// Menu height budget used to decide whether it opens below or above the button.
const MENU_FLIP_THRESHOLD = 220

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

function anchorFromRect(rect) {
  const spaceBelow = window.innerHeight - rect.bottom
  const openUpward = spaceBelow < MENU_FLIP_THRESHOLD && rect.top > spaceBelow
  return {
    left: rect.left,
    openUpward,
    top: openUpward ? undefined : `${Math.round(rect.bottom + 4)}px`,
    bottom: openUpward ? `${Math.round(window.innerHeight - rect.top + 4)}px` : undefined,
  }
}

export default function AgentPicker({ agents, value, onSelect, onCreate, translate }) {
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState(null)
  const buttonRef = useRef(null)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const closePicker = (event) => {
      if (menuRef.current && menuRef.current.contains(event.target)) return
      if (buttonRef.current && buttonRef.current.contains(event.target)) return
      setOpen(false)
    }
    const closeOnViewportChange = () => setOpen(false)
    window.addEventListener("click", closePicker)
    window.addEventListener("resize", closeOnViewportChange)
    window.addEventListener("scroll", closeOnViewportChange, true)
    return () => {
      window.removeEventListener("click", closePicker)
      window.removeEventListener("resize", closeOnViewportChange)
      window.removeEventListener("scroll", closeOnViewportChange, true)
    }
  }, [open])

  const list = agents || []
  const current = list.find((item) => item.agent_id === value) || list[0]
  const label = current ? agentDisplayName(current, translate) : translate("taskFormAgent")

  const toggle = () => {
    if (open) {
      setOpen(false)
      return
    }
    const rect = buttonRef.current?.getBoundingClientRect()
    setAnchor(rect ? anchorFromRect(rect) : null)
    setOpen(true)
  }

  const pick = (agentId) => {
    onSelect(agentId)
    setOpen(false)
  }

  const create = () => {
    setOpen(false)
    onCreate()
  }

  return (
    <div className="agent-picker">
      <button
        ref={buttonRef}
        type="button"
        className={`agent-picker-btn ${open ? "active" : ""}`}
        onClick={toggle}
        title={translate("taskFormAgent")}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <AgentIcon name={agentIconName(current)} />
        <span className="agent-picker-label">{label}</span>
        <span className="agent-picker-caret">▾</span>
      </button>
      {open &&
        anchor &&
        createPortal(
          <div
            ref={menuRef}
            className={`agent-picker-menu ${anchor.openUpward ? "upward" : ""}`}
            style={{ left: `${Math.round(anchor.left)}px`, top: anchor.top, bottom: anchor.bottom }}
            role="listbox"
            aria-label={translate("taskFormAgent")}
          >
            {list.map((item) => {
              const selected = Boolean(current) && item.agent_id === current.agent_id
              return (
                <button
                  type="button"
                  role="option"
                  aria-selected={selected}
                  key={item.agent_id}
                  className={`agent-picker-item ${selected ? "active" : ""}`}
                  onClick={() => pick(item.agent_id)}
                >
                  <AgentIcon name={agentIconName(item)} />
                  <span className="agent-picker-name">{agentDisplayName(item, translate)}</span>
                  {selected && (
                    <span className="agent-picker-check">
                      <CheckIcon />
                    </span>
                  )}
                </button>
              )
            })}
            <button type="button" className="agent-picker-item agent-picker-create" onClick={create}>
              {translate("agentCreateOption")}
            </button>
          </div>,
          document.body,
        )}
    </div>
  )
}

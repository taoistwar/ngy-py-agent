// The two narrowings above the task log, side by side: which event types to show
// (a multi-select menu, because one task usually spans several) and a text query
// over what the events say.
//
// The menu is a portal for the same reason the agent picker is: the detail panel
// scrolls its own body and would clip an absolutely positioned child.

import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"

import { getEventCategoryText } from "../i18n"
import { CloseIcon, SearchIcon } from "./icons"

// Height budget used to decide whether the menu opens below or above the button.
const MENU_FLIP_THRESHOLD = 280

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

function selectedLabel(selected, translate) {
  const picked = [...selected]
  if (picked.length === 0) return translate("eventFilterAllCategories")
  const first = getEventCategoryText(translate, picked[0])
  return picked.length === 1 ? first : `${first} +${picked.length - 1}`
}

function CategoryMenu({ options, selected, onToggle, onSelectAll, onClear, translate }) {
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState(null)
  const buttonRef = useRef(null)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const closeMenu = (event) => {
      if (menuRef.current?.contains(event.target)) return
      if (buttonRef.current?.contains(event.target)) return
      setOpen(false)
    }
    const closeOnViewportChange = () => setOpen(false)
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setOpen(false)
    }
    window.addEventListener("click", closeMenu)
    window.addEventListener("resize", closeOnViewportChange)
    // The menu is anchored to a button inside a scrolling pane: scrolling would
    // leave it pointing at nothing, so it closes like the other pickers do.
    window.addEventListener("scroll", closeOnViewportChange, true)
    window.addEventListener("keydown", closeOnEscape)
    return () => {
      window.removeEventListener("click", closeMenu)
      window.removeEventListener("resize", closeOnViewportChange)
      window.removeEventListener("scroll", closeOnViewportChange, true)
      window.removeEventListener("keydown", closeOnEscape)
    }
  }, [open])

  const toggle = () => {
    if (open) {
      setOpen(false)
      return
    }
    const rect = buttonRef.current?.getBoundingClientRect()
    setAnchor(rect ? anchorFromRect(rect) : null)
    setOpen(true)
  }

  const filtered = selected.size > 0

  return (
    <div className="event-filter-select">
      <button
        ref={buttonRef}
        type="button"
        className={`event-filter-btn ${filtered ? "active" : ""}`}
        onClick={toggle}
        title={translate("eventFilterCategoryAria")}
        aria-expanded={open}
        aria-label={translate("eventFilterCategoryAria")}
      >
        <span className="event-filter-btn-label">{selectedLabel(selected, translate)}</span>
        <span className="event-filter-caret">▾</span>
      </button>
      {open &&
        anchor &&
        createPortal(
          <div
            ref={menuRef}
            className={`event-filter-menu ${anchor.openUpward ? "upward" : ""}`}
            style={{ left: `${Math.round(anchor.left)}px`, top: anchor.top, bottom: anchor.bottom }}
            role="group"
            aria-label={translate("eventFilterCategoryAria")}
          >
            <div className="event-filter-menu-head">
              <button type="button" className="event-filter-menu-action" onClick={onSelectAll}>
                {translate("eventFilterSelectAll")}
              </button>
              <button
                type="button"
                className="event-filter-menu-action"
                onClick={onClear}
                disabled={!filtered}
              >
                {translate("eventFilterClear")}
              </button>
            </div>
            <div className="event-filter-options">
              {options.map((option) => {
                const checked = selected.has(option.category)
                return (
                  <label
                    key={option.category}
                    className={`event-filter-option ${checked ? "active" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggle(option.category)}
                    />
                    <span className="event-filter-option-label">
                      {getEventCategoryText(translate, option.category)}
                    </span>
                    <span className="event-filter-option-count">{option.count}</span>
                  </label>
                )
              })}
            </div>
          </div>,
          document.body,
        )}
    </div>
  )
}

export default function EventFilterBar({
  options,
  selected,
  onToggleCategory,
  onSelectAllCategories,
  onClearCategories,
  query,
  onQueryChange,
  matchedCount,
  totalCount,
  translate,
}) {
  const searchLabel = translate("eventFilterSearch")
  return (
    <div className="event-filter-bar">
      <CategoryMenu
        options={options}
        selected={selected}
        onToggle={onToggleCategory}
        onSelectAll={onSelectAllCategories}
        onClear={onClearCategories}
        translate={translate}
      />
      <div className="event-filter-search">
        <SearchIcon />
        <input
          className="event-filter-search-input"
          type="text"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={searchLabel}
          aria-label={searchLabel}
        />
        {query && (
          <button
            type="button"
            className="event-filter-search-clear"
            onClick={() => onQueryChange("")}
            title={translate("eventFilterClear")}
            aria-label={translate("eventFilterClear")}
          >
            <CloseIcon />
          </button>
        )}
      </div>
      {matchedCount !== totalCount && (
        <span className="event-filter-count">
          {matchedCount} / {totalCount}
        </span>
      )}
    </div>
  )
}

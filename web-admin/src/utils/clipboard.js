// Clipboard helper. The async Clipboard API needs a secure context, but the admin
// is routinely opened over plain http on a LAN address, so keep a selection based
// fallback for exactly that case.

const HIDDEN_AREA_TOP = "-1000px"

function legacyCopy(value) {
  const area = document.createElement("textarea")
  area.value = value
  // Kept in the layout (an off-screen position) instead of `display: none`,
  // which would make the text unselectable.
  area.setAttribute("readonly", "")
  area.style.position = "fixed"
  area.style.top = HIDDEN_AREA_TOP
  area.style.opacity = "0"
  document.body.appendChild(area)
  try {
    area.select()
    return document.execCommand("copy")
  } catch {
    return false
  } finally {
    document.body.removeChild(area)
  }
}

/** Copies `text`; resolves to whether the clipboard actually took it. */
export async function copyText(text) {
  const value = typeof text === "string" ? text : ""
  if (!value) return false

  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return true
    } catch {
      // Denied or unavailable in this context; try the fallback below.
    }
  }

  return legacyCopy(value)
}

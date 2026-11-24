// A copy-to-clipboard icon button.
//
// The outcome is reported in place (a tick, or a red glyph on failure) instead of a
// toast: a toast would cover the content the user is copying - an answer, a parameter
// value - exactly while they are looking at it.
//
// It copies the text it is given verbatim: what is on screen may be rendered or
// transformed, but the source is what pastes cleanly into an editor or a chat message.

import { useEffect, useRef, useState } from "react"
import { copyText } from "../utils/clipboard"
import { CheckIcon, CopyIcon } from "./icons"

const COPY_IDLE = "idle"
const COPY_DONE = "done"
const COPY_FAILED = "failed"

// How long the tick stays before going back to the copy glyph.
const COPY_FEEDBACK_MS = 1600

/**
 * @param {{text: string, label: string, doneLabel: string, failedLabel: string,
 *          disabled?: boolean}} props
 * ``label`` is the idle tooltip; the other two replace it while the feedback shows.
 */
export default function CopyIconButton({
  text,
  label,
  doneLabel,
  failedLabel,
  disabled = false,
}) {
  const [state, setState] = useState(COPY_IDLE)
  const timerRef = useRef(null)

  // The text can change underneath the button (another task, a transform in the
  // cleaning dialog); a stale tick would claim something that is no longer there.
  useEffect(() => {
    setState(COPY_IDLE)
    window.clearTimeout(timerRef.current)
  }, [text])

  // The host can unmount while the feedback is still ticking down.
  useEffect(() => () => window.clearTimeout(timerRef.current), [])

  const copy = async () => {
    const copied = await copyText(text)
    setState(copied ? COPY_DONE : COPY_FAILED)
    window.clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(() => setState(COPY_IDLE), COPY_FEEDBACK_MS)
  }

  const title =
    state === COPY_DONE ? doneLabel : state === COPY_FAILED ? failedLabel : label

  const className = [
    "icon-btn",
    state === COPY_DONE ? "is-copied" : "",
    state === COPY_FAILED ? "icon-btn-danger" : "",
  ]
    .filter(Boolean)
    .join(" ")

  return (
    <button
      type="button"
      className={className}
      title={title}
      aria-label={title}
      disabled={disabled}
      onClick={copy}
    >
      {state === COPY_DONE ? <CheckIcon /> : <CopyIcon />}
    </button>
  )
}

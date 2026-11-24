// Cleaning dialog for a JSON payload in the event log.
//
// The chip row under a block applies a transform to the whole text; a tool call's
// arguments are a document of named parameters, and usually only one of them is the
// messy part (a command full of escapes, say). This dialog lists the first-level
// fields so a transform can be applied to the checked parameters alone.
//
// Like the chips, it is a view: the log keeps the arguments the model actually sent,
// and the dialog starts from a snapshot of the block it was opened on.

import { useState } from "react"
import { copyText } from "../utils/clipboard"
import { TEXT_TRANSFORMS, fieldsToJsonText, isJsonText } from "../utils/textTransforms"
import CopyIconButton from "./CopyIconButton"
import Modal from "./admin/Modal"

function initialEntries(fields) {
  return fields.map((field) => ({ ...field, checked: true }))
}

/** Whether any visible parameter diffed from the snapshot the dialog opened on. */
function isDirty(entries, fields) {
  return entries.some((entry, index) => entry.value !== fields[index]?.value)
}

/**
 * @param {{fields: Array<{name: string, value: string}>, translate: Function,
 *          onClose: Function}} props
 * ``fields`` is ``jsonFieldEntries`` of the block's text: the dialog never mutates
 * the block, it only transforms its own copy of these values.
 */
export default function EventTextCleanDialog({ fields, translate, onClose }) {
  const [entries, setEntries] = useState(() => initialEntries(fields))
  const [copyState, setCopyState] = useState("idle")

  const selected = entries.filter((entry) => entry.checked)
  const anySelected = selected.length > 0
  // Format/minify need JSON in at least one checked parameter; on a plain command
  // they would either do nothing or rewrite the shell text.
  const anySelectedJson = selected.some((entry) => isJsonText(entry.value))
  const allChecked = entries.length > 0 && entries.every((entry) => entry.checked)
  const dirty = isDirty(entries, fields)

  function toggleEntry(name) {
    setEntries((previous) =>
      previous.map((entry) =>
        entry.name === name ? { ...entry, checked: !entry.checked } : entry,
      ),
    )
    setCopyState("idle")
  }

  function toggleAll() {
    const next = !allChecked
    setEntries((previous) => previous.map((entry) => ({ ...entry, checked: next })))
    setCopyState("idle")
  }

  function applyTransform(transform) {
    setEntries((previous) =>
      previous.map((entry) =>
        entry.checked ? { ...entry, value: transform.apply(entry.value) } : entry,
      ),
    )
    setCopyState("idle")
  }

  function reset() {
    setEntries(initialEntries(fields))
    setCopyState("idle")
  }

  async function copyResult() {
    const copied = await copyText(fieldsToJsonText(selected))
    setCopyState(copied ? "done" : "failed")
  }

  return (
    <Modal
      title={translate("eventCleanTitle")}
      hint={translate("eventCleanHint")}
      closeLabel={translate("dialogClose")}
      onClose={onClose}
      wide
    >
      <div className="event-clean">
        <div className="event-clean-toolbar">
          <div className="event-text-tools" role="group" aria-label={translate("eventTextToolsAria")}>
            {TEXT_TRANSFORMS.map((item) => (
              <button
                key={item.label}
                type="button"
                className="event-text-tool"
                disabled={!anySelected || (Boolean(item.jsonOnly) && !anySelectedJson)}
                onClick={() => applyTransform(item)}
              >
                {translate(item.label)}
              </button>
            ))}
          </div>
          <div className="event-clean-toolbar-actions">
            <label className="event-clean-all">
              <input type="checkbox" checked={allChecked} onChange={toggleAll} />
              {translate("eventFilterSelectAll")}
            </label>
            <button type="button" className="btn btn-compact" disabled={!dirty} onClick={reset}>
              {translate("eventCleanReset")}
            </button>
          </div>
        </div>
        <p className="event-clean-fields-title">{translate("eventCleanFields")}</p>
        <ul className="event-clean-fields">
          {entries.map((entry) => (
            <li className="event-clean-field" key={entry.name}>
              <div className="event-clean-field-head">
                <label className="event-clean-field-toggle">
                  <input
                    type="checkbox"
                    checked={entry.checked}
                    onChange={() => toggleEntry(entry.name)}
                  />
                  <span className="event-clean-field-name">{entry.name}</span>
                </label>
                {/* Copies the value as shown here, after any transform: often the
                    reason to open this dialog is to take one parameter away. */}
                <CopyIconButton
                  text={entry.value}
                  label={translate("eventCleanFieldCopy")}
                  doneLabel={translate("detailResultCopyDone")}
                  failedLabel={translate("detailResultCopyFailed")}
                />
              </div>
              <pre className="event-clean-field-value">{entry.value}</pre>
            </li>
          ))}
        </ul>
        <div className="event-clean-footer">
          <button
            type="button"
            className="btn btn-primary btn-compact"
            disabled={!anySelected}
            onClick={copyResult}
          >
            {translate("detailResultCopy")}
          </button>
          {copyState !== "idle" && (
            <span className="hint">
              {translate(copyState === "done" ? "detailResultCopyDone" : "detailResultCopyFailed")}
            </span>
          )}
        </div>
      </div>
    </Modal>
  )
}

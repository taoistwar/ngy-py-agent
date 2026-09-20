// Icon-only row actions for the task list: re-run and delete.

import { RerunIcon, TrashIcon } from "./icons"

export default function TaskRowActions({ running, onRerun, onDelete, translate }) {
  const rerunLabel = translate("taskRerun")

  return (
    <div className="task-row-actions">
      <button
        type="button"
        className="icon-btn"
        title={rerunLabel}
        aria-label={rerunLabel}
        disabled={running}
        onClick={(event) => {
          event.stopPropagation()
          onRerun()
        }}
      >
        <RerunIcon />
      </button>
      <button
        type="button"
        className="icon-btn icon-btn-danger"
        title={translate("taskDelete")}
        aria-label={translate("taskDelete")}
        onClick={(event) => {
          event.stopPropagation()
          onDelete()
        }}
      >
        <TrashIcon />
      </button>
    </div>
  )
}

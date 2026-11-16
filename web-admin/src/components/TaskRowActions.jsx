// Icon-only row actions for the task list: edit, re-run, undo what it changed,
// and delete.

import { EditIcon, RerunIcon, TrashIcon, UndoIcon } from "./icons"

export default function TaskRowActions({
  running,
  onEdit,
  onRerun,
  onRevert,
  onDelete,
  translate,
}) {
  const rerunLabel = translate("taskRerun")
  const revertLabel = translate("taskRevert")

  return (
    <div className="task-row-actions">
      <button
        type="button"
        className="icon-btn"
        title={translate("taskEdit")}
        aria-label={translate("taskEdit")}
        // Editing a running task would fill the composer from a turn that is still
        // writing; sending it would then delete the task mid-run.
        disabled={running}
        onClick={(event) => {
          event.stopPropagation()
          onEdit()
        }}
      >
        <EditIcon />
      </button>
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
        className="icon-btn"
        title={revertLabel}
        aria-label={revertLabel}
        // A running task is still writing; its history is not final yet.
        disabled={running}
        onClick={(event) => {
          event.stopPropagation()
          onRevert()
        }}
      >
        <UndoIcon />
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

// Icon-only actions in the task list title bar: refresh and batch delete.

import { RefreshIcon, TrashIcon } from "./icons"

export default function TaskToolbarActions({ selectedCount, onRefresh, onBatchDelete, translate }) {
  const batchLabel = translate("taskListBatchDelete")

  return (
    <div className="task-toolbar-actions">
      <button
        type="button"
        className="icon-btn"
        title={translate("taskListRefresh")}
        aria-label={translate("taskListRefresh")}
        onClick={onRefresh}
      >
        <RefreshIcon />
      </button>
      <button
        type="button"
        className="icon-btn icon-btn-danger"
        title={batchLabel}
        aria-label={batchLabel}
        disabled={selectedCount === 0}
        onClick={onBatchDelete}
      >
        <TrashIcon />
      </button>
    </div>
  )
}

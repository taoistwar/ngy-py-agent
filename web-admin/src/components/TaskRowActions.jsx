// Icon-only row actions for the task list: re-run and delete.

function RerunIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="1 4 1 10 7 10" />
      <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
    </svg>
  )
}

function DeleteIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <line x1="10" y1="11" x2="10" y2="17" />
      <line x1="14" y1="11" x2="14" y2="17" />
    </svg>
  )
}

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
        <DeleteIcon />
      </button>
    </div>
  )
}

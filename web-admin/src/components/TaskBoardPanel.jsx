// The project's task board, as the `task_*` tools last left it.
//
// Workspace scoped (a conversation with no workspace keeps a board of its own) and
// returned inside the task detail response, so the pane's existing one-second poll is
// what keeps it in sync - the same mechanism as the plan above it, no extra channel.
//
// One line per task, ordered by what needs attention: what is in progress, then what
// can be claimed next, then what is blocked, then what is done.
import { CheckIcon } from "./icons"

const STATUS_KEYS = {
  pending: "todoStatusPending",
  in_progress: "todoStatusInProgress",
  completed: "todoStatusCompleted",
}

function statusOf(item) {
  return STATUS_KEYS[item?.status] ? item.status : "pending"
}

// The rank a row is sorted by. Ties keep the backend order (creation time), which is
// the order the graph was written in.
function rankOf(item) {
  const status = statusOf(item)
  if (status === "in_progress") return 0
  if (status === "completed") return 3
  return item?.ready ? 1 : 2
}

function blockedNames(item) {
  const subjects = Array.isArray(item?.blocked_by_subjects) ? item.blocked_by_subjects : []
  if (subjects.length > 0) return subjects.join(", ")
  return (Array.isArray(item?.incomplete_blockers) ? item.incomplete_blockers : []).join(", ")
}

export default function TaskBoardPanel({ board, translate }) {
  const items = Array.isArray(board) ? board : []
  if (items.length === 0) return null

  const done = items.filter((item) => item.status === "completed").length
  const percent = Math.round((done / items.length) * 100)
  const ordered = [...items].sort((a, b) => rankOf(a) - rankOf(b))

  return (
    <section
      className="board-panel"
      aria-label={translate("taskBoardTitle")}
      title={translate("taskBoardHint")}
    >
      <div className="board-panel-header">
        <span className="board-panel-title">{translate("taskBoardTitle")}</span>
        <span className="board-panel-count">
          {done}/{items.length}
        </span>
      </div>
      <div
        className="board-panel-progress"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={items.length}
        aria-valuenow={done}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <ol className="board-panel-list">
        {ordered.map((item) => {
          const status = statusOf(item)
          const blocked = status === "pending" && !item?.ready
          const blockedText = blocked ? blockedNames(item) : ""
          return (
            <li
              key={item?.task_id || item?.subject}
              className={`board-item is-${status}${blocked ? " is-blocked" : ""}`}
              title={[item?.description, translate(STATUS_KEYS[status])]
                .filter(Boolean)
                .join("\n\n")}
            >
              <span className="board-item-marker" aria-hidden="true">
                {status === "completed" ? (
                  <CheckIcon />
                ) : status === "in_progress" ? (
                  <span className="board-item-dot" />
                ) : null}
              </span>
              <span className="board-item-body">
                <span className="board-item-subject">{item?.subject || ""}</span>
                {status !== "completed" && (
                  <span className="board-item-meta">
                    {status === "in_progress" ? (
                      <span className="board-item-chip is-active">
                        {translate(STATUS_KEYS[status])}
                      </span>
                    ) : blocked ? (
                      <span className="board-item-chip is-blocked">
                        {translate("taskBoardBlocked")}
                        {blockedText ? `: ${blockedText}` : ""}
                      </span>
                    ) : (
                      <span className="board-item-chip is-ready">
                        {translate("taskBoardReady")}
                      </span>
                    )}
                    {item?.owner_name ? (
                      <span className="board-item-owner">{item.owner_name}</span>
                    ) : null}
                  </span>
                )}
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

// The conversation's plan, as `todo_write` last wrote it.
//
// It is session scoped and arrives inside the task detail response, so the pane's
// existing one-second poll is what keeps it in sync: a status change made by the
// running task shows up on the next tick without any extra stream or socket.
//
// The panel sits above both detail tabs rather than inside one, because a running
// task opens its log - and the plan is what that log is executing.
import { CheckIcon } from "./icons"

const STATUS_KEYS = {
  pending: "todoStatusPending",
  in_progress: "todoStatusInProgress",
  completed: "todoStatusCompleted",
}

function statusOf(item) {
  return STATUS_KEYS[item?.status] ? item.status : "pending"
}

export default function TodoPanel({ todos, translate }) {
  const items = Array.isArray(todos) ? todos : []
  if (items.length === 0) return null

  const done = items.filter((item) => item.status === "completed").length
  const percent = Math.round((done / items.length) * 100)

  return (
    <section className="todo-panel" aria-label={translate("todoPanelTitle")}>
      <div className="todo-panel-header">
        <span className="todo-panel-title">{translate("todoPanelTitle")}</span>
        <span className="todo-panel-count">
          {done}/{items.length}
        </span>
      </div>
      <div
        className="todo-panel-progress"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={items.length}
        aria-valuenow={done}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <ol className="todo-panel-list">
        {items.map((item, index) => {
          const status = statusOf(item)
          return (
            <li
              key={`${index}-${item?.content || ""}`}
              className={`todo-item is-${status}`}
              title={translate(STATUS_KEYS[status])}
            >
              <span className="todo-item-marker" aria-hidden="true">
                {status === "completed" ? (
                  <CheckIcon />
                ) : status === "in_progress" ? (
                  <span className="todo-item-dot" />
                ) : null}
              </span>
              <span className="todo-item-text">{item?.content || ""}</span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

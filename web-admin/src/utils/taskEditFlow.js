// Editing a task from the list: the row's prompt, agent and model are filled back
// into the composer, and sending that composer replaces the original turn.
//
// "Replace" is three steps, in this order:
//   1. the turn is undone (its file changes are reverted) and deleted, the same way
//      a re-run does it, so the replay starts from a clean workspace;
//   2. the turns created after it in the same session are deleted too - a task is
//      built from the session's transcript, so leaving them would replay them as
//      context for the edited turn;
//   3. the caller creates a task from the edited content.

import { deleteTask, fetchTasks, revertAndDeleteTask, stopTask } from "../api"
import { isTaskRunningStatus } from "../i18n"

// What the composer is filled with when "edit" is clicked on a row. An agent or a
// model that no longer exists is left out, so the composer keeps its own default
// instead of selecting something that cannot run.
export function buildTaskEditDraft(task, { agents = [], models = [] } = {}) {
  const agentKnown = agents.some((item) => item.agent_id === task.mode)
  const modelKnown = models.some((item) => item.model_id === task.model_id)
  return {
    taskId: task.task_id,
    query: task.query || "",
    agentId: agentKnown ? task.mode : "",
    modelId: modelKnown ? task.model_id : "",
  }
}

// Ids of the session's turns that came after ``taskId``, in the order they ran.
function turnIdsAfter(sessionTasks, taskId) {
  const index = sessionTasks.findIndex((item) => item.task_id === taskId)
  if (index < 0) return []
  return sessionTasks.slice(index + 1).map((item) => item.task_id)
}

// Delete ``task`` and every turn after it. A turn that is still running is stopped
// first: deleting a live task would leave its thread appending events to a record
// that no longer exists.
//
// Returns ``{deleted, blocked, removed}``. ``deleted: false`` means the undo hit a
// conflict and the task was kept - its undo dialog is the only place those files can
// be settled - so nothing at all is deleted.
export async function replaceTaskWithEdit(task, sessionId) {
  // Read the list before anything is removed: the turns to drop are only known by
  // their position relative to this one.
  const sessionTasks = sessionId ? await fetchTasks(sessionId) : []
  const laterIds = turnIdsAfter(sessionTasks, task.task_id)

  const result = await revertAndDeleteTask(task.task_id)
  if (!result.deleted) {
    return { deleted: false, blocked: result.blocked, removed: [] }
  }

  const removed = [task.task_id]
  for (const taskId of laterIds) {
    const later = sessionTasks.find((item) => item.task_id === taskId)
    if (later && isTaskRunningStatus(later.status)) {
      // A failed stop still lets the delete through: the record is what matters,
      // and the thread cannot outlive it for long.
      await stopTask(taskId).catch(() => {})
    }
    await deleteTask(taskId)
    removed.push(taskId)
  }

  return { deleted: true, blocked: [], removed }
}

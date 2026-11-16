// Forking a task from the list: the turn and everything before it is copied into a
// new session, which becomes the active conversation. The original session is left
// untouched - the fork is a branch, not a move.
//
// The copy lands as the branch's newest turn, so the session's own task list already
// points at it; selecting it explicitly keeps the pane on the row the user clicked
// even if the branch has a task with a later clock.

import { forkTask } from "../api"

export async function forkTaskSession(task, { refreshSessions, selectSession, selectTask } = {}) {
  if (!task?.task_id) return null
  const forked = await forkTask(task.task_id)
  await refreshSessions()
  if (!forked?.session_id) return forked
  await selectSession(forked.session_id)
  if (forked.task_id) selectTask(forked.task_id)
  return forked
}

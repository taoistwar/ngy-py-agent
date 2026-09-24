import { useState } from "react"
import Modal from "./admin/Modal"
import { answerQuestion } from "../api"

// Sentinel for the free-form row. It is deliberately not a label the model sent:
// "Other" is the client's option, so the answer never names it (ADR 0010 D5).
const OTHER = "__other__"

/**
 * Question dialog for `ask_user_question`.
 *
 * The request comes from `GET /api/tasks/{id}` (`pending_question`) and the task
 * thread is parked until this posts back, times out, or the task is stopped - the
 * same shape as `PermissionPrompt`, but the answer carries data instead of a verdict.
 *
 * Two things it has to get right:
 *
 * - **the free-form row is added here.** The model is told not to send an "Other"
 *   option, so this dialog is what makes "none of these" possible;
 * - **skipping is a real answer.** An empty answer set reaches the model as "nobody
 *   answered, decide yourself" - better than making the user wait out the timeout.
 *
 * Not dismissible: closing the dialog silently would leave the task blocked until
 * the timeout, and "skip" already says that on purpose. Escape and the close button
 * both skip.
 */
export default function QuestionPrompt({ request, onAnswered, translate }) {
  const [selected, setSelected] = useState({})
  const [notes, setNotes] = useState({})
  const [busy, setBusy] = useState("")
  const [error, setError] = useState("")

  if (!request) {
    return null
  }

  const questions = Array.isArray(request.questions) ? request.questions : []

  const send = async (kind, answers) => {
    if (busy) return
    setBusy(kind)
    setError("")
    try {
      await answerQuestion(request.task_id, request.request_id, answers)
      onAnswered?.()
    } catch (submitError) {
      setError(submitError?.message || translate("questionFailed"))
    } finally {
      setBusy("")
    }
  }

  const submit = () => {
    // One entry per question, in the order the model asked them: an option label
    // first, then whatever the user typed. Nothing is invented and nothing is
    // prefixed - an array entry *is* an answer (ADR 0010 D5).
    const answers = {}
    questions.forEach((question) => {
      const picked = selected[question.id]
      const note = (notes[question.id] || "").trim()
      const list = []
      if (picked && picked !== OTHER) {
        list.push(picked)
      }
      if (note) {
        list.push(note)
      }
      answers[question.id] = { answers: list }
    })
    return send("submit", answers)
  }

  const skip = () => send("skip", {})

  return (
    <Modal
      title={translate("questionTitle")}
      hint={translate("questionHint")}
      closeLabel={translate("questionSkip")}
      onClose={skip}
      dismissible={false}
      wide
    >
      <div className="question-prompt">
        {questions.map((question) => (
          <div className="question-block" key={question.id}>
            <div className="question-head">
              <span className="question-chip">{question.header || question.id}</span>
              <strong>{question.question}</strong>
            </div>
            <div className="question-options">
              {(question.options || []).map((option) => (
                <label className="question-option" key={`${question.id}-${option.label}`}>
                  <input
                    type="radio"
                    name={`question-${question.id}`}
                    checked={selected[question.id] === option.label}
                    onChange={() => setSelected({ ...selected, [question.id]: option.label })}
                  />
                  <span className="question-option-text">
                    <strong>{option.label}</strong>
                    {option.description ? <em>{option.description}</em> : null}
                  </span>
                </label>
              ))}
              <label className="question-option question-option-other">
                <input
                  type="radio"
                  name={`question-${question.id}`}
                  checked={selected[question.id] === OTHER}
                  onChange={() => setSelected({ ...selected, [question.id]: OTHER })}
                />
                <span className="question-option-text">
                  <strong>{translate("questionOther")}</strong>
                  <input
                    type="text"
                    className="question-note"
                    value={notes[question.id] || ""}
                    placeholder={translate("questionOtherPlaceholder")}
                    onChange={(event) =>
                      setNotes({ ...notes, [question.id]: event.target.value })
                    }
                    onFocus={() =>
                      setSelected((current) => ({ ...current, [question.id]: OTHER }))
                    }
                  />
                </span>
              </label>
            </div>
          </div>
        ))}
        {error ? <p className="permission-error">{error}</p> : null}
        <div className="permission-actions">
          <button type="button" className="btn btn-primary" disabled={Boolean(busy)} onClick={submit}>
            {busy === "submit" ? translate("questionSending") : translate("questionSubmit")}
          </button>
          <button type="button" className="btn" disabled={Boolean(busy)} onClick={skip}>
            {busy === "skip" ? translate("questionSending") : translate("questionSkip")}
          </button>
        </div>
      </div>
    </Modal>
  )
}

"""Asking the user a question and waiting for the answer (see ADR 0010).

The permission gate answers "may this call run?" and can only carry back yes or no.
Some decisions are not permissions at all - which of two designs to take, which
environment to target, whether to replace a file - and their answer is **data**, not a
verdict. That needs its own inbound channel, so this module mirrors the shape of
:mod:`agent.tools.permissions` and none of its semantics:

* the request goes out as a ``user_question`` event carrying the questions verbatim;
* the answer comes back through the API layer (:meth:`UserQuestionBroker.resolve`);
* waiting polls instead of blocking outright, so a stop request is honoured
  immediately rather than after the timeout (ADR 0006 D6);
* **nobody answering is not a refusal.** A gate fails closed because silence must not
  mean yes; a question does the opposite - silence means "decide yourself", and the
  tool says so in as many words (ADR 0010 D2).

Scope is one task, like the permission broker, and the two are deliberately separate
objects with separate event categories: an audit trail that cannot tell "the user
allowed a command" from "the user chose option B" is not an audit trail.

A question cannot allow, forbid or stop anything. It only asks.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

TIMEOUT_ENV = "ASK_USER_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 120.0
# Poll rather than block, so a stop request is seen at once (ADR 0006 D6).
_POLL_SECONDS = 0.25

# Why an answer set came back the way it did. Plain strings so they travel in event
# payloads and the UI can branch on them without a translation step.
STATUS_ANSWERED = "answered"
STATUS_TIMEOUT = "timeout"
STATUS_STOPPED = "stopped"
STATUS_NO_CLIENT = "no_client"

NO_CLIENT_NOTE = (
    "No client is connected that can answer questions, so nothing was asked. Decide "
    "yourself with the information you have, and state the assumption you made."
)
STOPPED_NOTE = (
    "The task was stopped while the questions were pending, so there are no answers. "
    "Do not ask again; continue only if the remaining work does not depend on them."
)
TIMEOUT_NOTE = (
    "Nobody answered within {seconds} seconds, so there are no answers. Do not ask "
    "again: decide yourself with the information you have, and state the assumption "
    "you made."
)


def timeout_seconds() -> float:
    """Wait limit for an answer, overridable by ``ASK_USER_TIMEOUT_SECONDS``.

    Its own knob, not the permission one: they read the same way but mean different
    things ("refuse the call" versus "carry on without an answer"), so tuning one
    must not silently retune the other.
    """
    raw = (os.getenv(TIMEOUT_ENV) or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class UserQuestionRequest:
    """One batch of questions, as handed to the UI."""

    request_id: str
    task_id: str
    questions: Tuple[Dict[str, Any], ...]
    created_at: float = field(default_factory=time.time)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def question_ids(self) -> Tuple[str, ...]:
        return tuple(str(question.get("id") or "") for question in self.questions)

    def to_payload(self) -> Dict[str, Any]:
        """The event payload the client renders.

        Every question carries ``is_other: true``: the free-form row is the **client's**
        to add, so the model is told not to send one (same contract as the reference
        implementation).
        """
        questions: List[Dict[str, Any]] = []
        for question in self.questions:
            payload = dict(question)
            payload["is_other"] = True
            questions.append(payload)
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "questions": questions,
            "created_at": self.created_at,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class QuestionResult:
    """What came back, and why it may be empty."""

    answers: Dict[str, Dict[str, List[str]]]
    status: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def answered(self) -> bool:
        return self.status == STATUS_ANSWERED

    def note(self) -> str:
        """The model-facing sentence explaining an empty answer set."""
        if self.status == STATUS_ANSWERED:
            return ""
        if self.status == STATUS_STOPPED:
            return STOPPED_NOTE
        if self.status == STATUS_TIMEOUT:
            return TIMEOUT_NOTE.format(seconds=int(self.timeout_seconds))
        return NO_CLIENT_NOTE

    def response(self) -> Dict[str, Any]:
        """The output contract: ``{"answers": {"<id>": {"answers": [...]}}}``."""
        return {"answers": self.answers}


def validate_answers(
    request: UserQuestionRequest, payload: Any
) -> Tuple[Optional[Dict[str, Dict[str, List[str]]]], Optional[str]]:
    """``(answers, error)`` for an incoming answer body.

    Structural only, in the same spirit as the tool's own validation: an id that was
    never asked, or an answer that is not a list of strings, is refused (the API turns
    the message into a 400) rather than being silently dropped into a payload the model
    then misreads. A question the user skipped may be absent or carry an empty list.
    """
    if not isinstance(payload, dict):
        return None, "The request body must be a JSON object with an 'answers' field."
    raw = payload.get("answers")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        return None, "'answers' must be an object keyed by question id."

    known = set(request.question_ids())
    answers: Dict[str, Dict[str, List[str]]] = {}
    for question_id, value in raw.items():
        if str(question_id) not in known:
            return None, f"Unknown question id: {question_id!r}."
        if not isinstance(value, dict):
            return None, f"The answer for {question_id!r} must be an object."
        items = value.get("answers")
        if items is None:
            items = []
        if not isinstance(items, (list, tuple)):
            return None, f"'answers' for {question_id!r} must be a list of strings."
        for item in items:
            if not isinstance(item, str):
                return None, f"'answers' for {question_id!r} must contain only strings."
        answers[str(question_id)] = {"answers": [str(item) for item in items]}
    return answers, None


class UserQuestionBroker:
    """Asks one task's user questions and waits for the answers."""

    def __init__(
        self,
        *,
        task_id: str = "",
        emit: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
        wait_seconds: Optional[float] = None,
    ) -> None:
        self.task_id = task_id
        self.wait_seconds = wait_seconds if wait_seconds is not None else timeout_seconds()
        self.should_stop = should_stop
        self._emit = emit
        self._lock = threading.Lock()
        self._waiters: Dict[str, "_Waiter"] = {}

    # ------------------------------------------------------------------ public

    def ask(self, questions: Sequence[Dict[str, Any]]) -> QuestionResult:
        """Show ``questions`` to the user and wait for the answers.

        Returns a result rather than raising, including when the answer set is empty:
        "nobody answered" is a normal outcome the model must be able to act on.
        """
        request = UserQuestionRequest(
            request_id=uuid4().hex,
            task_id=self.task_id,
            questions=tuple(dict(question) for question in questions),
            timeout_seconds=self.wait_seconds,
        )
        waiter = _Waiter(event=threading.Event(), request=request)
        with self._lock:
            self._waiters[request.request_id] = waiter
        self._emit_event("user_question", _question_title(request), request.to_payload())

        deadline = time.monotonic() + self.wait_seconds
        while True:
            if waiter.event.wait(_POLL_SECONDS):
                break
            # Stop beats the timeout: the user asked for the task to end.
            if self.should_stop is not None and self.should_stop():
                waiter.status = STATUS_STOPPED
                break
            if time.monotonic() >= deadline:
                waiter.status = STATUS_TIMEOUT
                break

        with self._lock:
            self._waiters.pop(request.request_id, None)

        status = STATUS_ANSWERED if waiter.resolved else (waiter.status or STATUS_TIMEOUT)
        answers = waiter.answers if waiter.resolved else {}
        self._emit_event(
            "user_answer",
            f"Answered {len(answers)} of {len(request.questions)} question(s)"
            if waiter.resolved
            else f"No answer ({status})",
            {
                "request_id": request.request_id,
                "task_id": self.task_id,
                "status": status,
                "answers": answers,
                "answered_count": len(answers),
                "question_count": len(request.questions),
            },
        )
        return QuestionResult(
            answers=answers, status=status, timeout_seconds=self.wait_seconds
        )

    def resolve(self, request_id: str, answers: Dict[str, Dict[str, List[str]]]) -> bool:
        """Answer a pending request. Returns whether it was still pending.

        Called from the API layer, i.e. from a *different* thread than the one blocked
        in :meth:`ask` - hence the lock and the ``threading.Event``.
        """
        with self._lock:
            waiter = self._waiters.get(request_id)
        if waiter is None:
            return False
        # ``resolved`` first: a teardown racing with this call checks it, and must not
        # be able to turn an answer that already arrived into "nobody answered".
        waiter.resolved = True
        waiter.answers = dict(answers)
        waiter.event.set()
        return True

    def pending(self) -> Optional[UserQuestionRequest]:
        """The request currently being waited on, if any."""
        with self._lock:
            for waiter in self._waiters.values():
                if not waiter.event.is_set():
                    return waiter.request
        return None

    def cancel_all(self, status: str = STATUS_STOPPED) -> None:
        """Release every waiter so no thread is stuck until the timeout.

        Leaves ``resolved`` untouched on purpose: a released waiter was not answered,
        and must not be reported as one.
        """
        with self._lock:
            waiters = list(self._waiters.values())
        for waiter in waiters:
            if waiter.resolved:
                continue
            waiter.status = status
            waiter.event.set()

    # ----------------------------------------------------------------- private

    def _emit_event(self, category: str, title: str, data: Dict[str, Any]) -> None:
        """Hand one audit event to the caller-supplied emitter.

        ``category`` is the event category value (``user_question`` / ``user_answer``);
        ``emit`` turns it into the real ``TaskEvent``, which keeps this module free of
        the task-store types - the same split the permission broker uses.
        """
        if self._emit is None:
            return
        try:
            self._emit(category, title, data)
        except Exception:  # noqa: BLE001 - event emission must never break the call
            return


@dataclass
class _Waiter:
    """A pending question plus the thread waiting for its answer."""

    event: threading.Event
    request: UserQuestionRequest
    answers: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    status: Optional[str] = None
    # True only when :meth:`UserQuestionBroker.resolve` answered it; a released waiter
    # stays ``False`` so it is not reported as an answer.
    resolved: bool = False


def _question_title(request: UserQuestionRequest) -> str:
    """One line for the event timeline."""
    count = len(request.questions)
    if not count:
        return "Question"
    first_question = request.questions[0]
    first = str(first_question.get("header") or first_question.get("question") or "").strip()
    if count == 1:
        return f"Question: {first[:60]}"
    return f"{count} questions: {first[:40]}"

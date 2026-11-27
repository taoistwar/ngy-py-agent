"""Translating a task's reasoning traces into the language the console is read in.

The translation model is one global setting (:data:`commons.state.translation_model_id`).
While it is unset nothing is translated: spending tokens on every finished task is not
something to opt into by accident, and the page offers the switch.

A trace is translated once per language and then stored, so the automatic pass after a
task finishes and the log's manual action cost one call per trace in total, not one per
view. A failure is not stored, which is what makes the next click a retry.

The provider endpoint's RPM budget is shared with the task loop (ADR 0013): the adapters
spend it on every call, and this batch only *reads* what is left so it can stop before
queueing minutes of waits. What it could not translate is reported as deferred and picked
up by the next call - translation must not become the reason a console request hangs.

A pass runs on its own thread, not inside the request: a task can carry dozens of traces
and each is at least one model call, so the click has to answer at once ("a pass is
running") and let the console read the result back while it fills in
(``routes/task_api.py`` exposes the status the page polls).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from agent.models import EventCategory
from agent.provider import ProviderConfig, build_provider
from agent.rate_limit import RpmLimitError, provider_throttle
from agent.runtime.config import build_provider_config
from commons import state

# The languages the console ships; mirrors ``LOCALES`` in ``web-admin/src/i18n.js``.
LOCALE_LANGUAGES: Dict[str, str] = {
    "en": "English",
    "zh-CN": "Simplified Chinese",
    "zh-TW": "Traditional Chinese",
    "fr": "French",
    "de": "German",
    "ru": "Russian",
}

SUPPORTED_LOCALES: Tuple[str, ...] = tuple(LOCALE_LANGUAGES)

# One request per chunk. A reasoning trace is a whole model turn's deliberation, and a
# small translation model has an output budget; chunks are joined back in order.
MAX_CHUNK_CHARS = 3000

_TRANSLATE_PROMPT = (
    "You translate the private reasoning trace of an AI agent. Translate the user's text "
    "into {language}. Keep code, file paths, tool names, Markdown and line breaks exactly "
    "as they are. Reply with the translation only - no preamble, no notes."
)


class TranslationNotConfigured(RuntimeError):
    """Raised when the reasoning translation has no usable model configured."""


def is_supported_locale(locale: str) -> bool:
    """Whether this console locale has a name the prompt can ask for."""
    return str(locale or "") in LOCALE_LANGUAGES


def translation_model() -> Optional[Dict[str, Any]]:
    """The configured translation model with its endpoint, or ``None`` when unusable.

    Unusable covers both "nothing configured" and "the model was deleted": the page
    would otherwise offer a model that fails one call at a time.
    """
    model_id = str(state.translation_model_id or "").strip()
    if not model_id:
        return None
    store = state.monitor_store
    model = store.llm.get_model(model_id)
    if model is None:
        return None
    provider_id = str(model.get("provider_id") or "")
    provider = store.llm.get_provider(provider_id) if provider_id else None
    return {"model_id": model_id, "model": model, "provider": provider}


def reasoning_traces(task_id: str) -> List[Tuple[str, str]]:
    """``(event_id, text)`` for every response event of the task that has a trace."""
    traces: List[Tuple[str, str]] = []
    for event in state.monitor_store.get_events(task_id):
        if str(event.get("category") or "") != EventCategory.LLM_RESPONSE.value:
            continue
        data = event.get("data") or {}
        # Some providers ship the trace as a list of blocks; ``str`` keeps the call
        # working rather than dropping a trace we cannot render.
        text = data.get("reasoning") if isinstance(data, dict) else None
        if not text:
            continue
        collapsed = str(text).strip()
        if collapsed:
            traces.append((str(event.get("event_id") or ""), collapsed))
    return traces


def split_reasoning(text: str, max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    """Split one trace into request-sized pieces, preferring paragraph boundaries."""
    limit = max(1, int(max_chars))
    chunks: List[str] = []
    current = ""
    for paragraph in str(text or "").split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        # A single paragraph longer than the limit still has to fit: cut it hard.
        while len(paragraph) > limit:
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


def translate_chunks(chunks: List[str], language: str, provider: Any) -> str:
    """Translate prepared chunks through ``provider``, one request per chunk."""
    messages_system = _TRANSLATE_PROMPT.format(language=language)
    parts: List[str] = []
    for chunk in chunks:
        response = provider.chat_completion(
            messages=[
                {"role": "system", "content": messages_system},
                {"role": "user", "content": chunk},
            ]
        )
        message = response.choices[0].message
        content = (
            message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        )
        translated = str(content or "").strip()
        if translated:
            parts.append(translated)
    return "\n\n".join(parts)


def translate_reasoning_text(text: str, language: str, provider: Any) -> str:
    """Translate one trace through ``provider``, one request per chunk."""
    return translate_chunks(split_reasoning(text), language, provider)


def _spend(budget: Optional[int], requests: int) -> Optional[int]:
    """Take ``requests`` off the endpoint's remaining budget; ``None`` stays unlimited."""
    if budget is None:
        return None
    return max(0, budget - max(1, int(requests)))


def _wire(entry: Dict[str, Any]) -> Tuple[str, Optional[ProviderConfig]]:
    """The provider name and wire config of a resolved model record."""
    model = entry["model"]
    provider = entry["provider"] or {}
    provider_name = str(provider.get("protocol") or model.get("protocol") or "openai-compatible")
    return provider_name, build_provider_config(model, provider)


def translate_missing_reasoning(
    task_id: str,
    locale: str,
    force: bool = False,
) -> Dict[str, Any]:
    """Translate the task's traces that have no stored copy for ``locale`` yet.

    Returns the response payload the route hands back: the stored translations keyed
    by event id, plus what this call did. Raises :class:`TranslationNotConfigured`
    when there is no model to call.
    """
    entry = translation_model()
    if entry is None:
        raise TranslationNotConfigured(
            "No translation model is configured; choose one in the global settings."
        )
    language = LOCALE_LANGUAGES.get(str(locale or ""))
    if language is None:
        raise ValueError(f"Unsupported locale '{locale}'.")

    stored = state.monitor_store.list_reasoning_translations(task_id, locale)
    provider_name, provider_config = _wire(entry)
    # Translation is a batch of calls against the same endpoint the task used, so it
    # spends the same per-minute bucket (ADR 0013). It stops asking when the window is
    # full: the remaining traces are reported as deferred instead of queueing minutes
    # of waits. Waiting itself stays the wire layer's job, not this loop's.
    base_url = getattr(provider_config, "base_url", "") if provider_config else ""
    budget = provider_throttle.available_requests(provider_name, base_url)
    provider = None
    items: Dict[str, str] = {}
    errors: List[str] = []
    translated = 0
    skipped = 0
    failed = 0
    deferred = 0

    traces = reasoning_traces(task_id)
    for index, (event_id, text) in enumerate(traces):
        if not force and event_id in stored:
            items[event_id] = stored[event_id]
            skipped += 1
            continue
        if budget is not None and budget <= 0:
            deferred = len(traces) - index
            break
        chunks = split_reasoning(text)
        try:
            if provider is None:
                provider = build_provider(provider_name, provider_config)
            translation = translate_chunks(chunks, language, provider)
        # The window closed while the batch was running. The adapter already waited as
        # long as it is allowed to, so the rest is left for the next call rather than
        # turning into a row of identical failures.
        except RpmLimitError as exc:
            deferred = len(traces) - index
            errors.append(str(exc))
            break
        # Broad on purpose: one bad trace must not drop the translations that did
        # work, and an unreadable answer is a retry rather than an error page.
        except Exception as exc:  # noqa: BLE001
            budget = _spend(budget, len(chunks))
            failed += 1
            errors.append(f"{event_id}: {exc.__class__.__name__}: {exc}")
            continue
        budget = _spend(budget, len(chunks))
        if not translation:
            failed += 1
            errors.append(f"{event_id}: empty translation")
            continue
        state.monitor_store.save_reasoning_translation(
            event_id, locale, translation, str(entry["model_id"])
        )
        items[event_id] = translation
        translated += 1

    return {
        "locale": locale,
        "model_id": str(entry["model_id"]),
        "items": items,
        "translated": translated,
        "skipped": skipped,
        "failed": failed,
        "deferred": deferred,
        "errors": errors,
    }


# ---------------------------------------------------------------- background pass

_JOB_LOCK = threading.Lock()
# (task id, locale) -> what the last pass did, and whether one is still running. The
# console polls the reader endpoint while ``running``; a finished record is what lets
# the poll say "3 translated" or "4 left by the RPM limit" instead of guessing from the
# number of rows that appeared. Old records are dropped; a task's traces are not
# replayed forever.
_JOBS: Dict[Tuple[str, str], Dict[str, Any]] = {}
_JOB_TTL_SECONDS = 3600.0
_JOB_COUNTERS = ("translated", "skipped", "failed", "deferred")


def translation_status(task_id: str, locale: str) -> Dict[str, Any]:
    """Whether a pass for this task and language is in flight, and how the last one went."""
    with _JOB_LOCK:
        job = _JOBS.get((str(task_id), str(locale)))
        if job is None:
            return {"running": False, **dict.fromkeys(_JOB_COUNTERS, 0)}
        return {
            "running": bool(job["running"]),
            **{name: int(job.get(name) or 0) for name in _JOB_COUNTERS},
        }


def _prune_jobs(now: float) -> None:
    """Drop finished records nobody will read again; called with the lock held."""
    stale = [
        key
        for key, job in _JOBS.items()
        if not job["running"] and now - float(job.get("finished_at") or 0.0) > _JOB_TTL_SECONDS
    ]
    for key in stale:
        _JOBS.pop(key, None)


def _run_translation_job(key: Tuple[str, str], task_id: str, locale: str, force: bool) -> None:
    """The worker: one pass, then the outcome is left for the poll to read."""
    try:
        result = translate_missing_reasoning(task_id, locale, force=force)
        counts = {name: int(result.get(name) or 0) for name in _JOB_COUNTERS}
    # Broad on purpose: a background thread has no caller to raise to, and the poll has
    # to learn that the pass ended even when it ended badly.
    except Exception as exc:  # noqa: BLE001
        counts = dict.fromkeys(_JOB_COUNTERS, 0)
        print(
            f"[Reasoning translation] {task_id}/{locale} failed: "
            f"{exc.__class__.__name__}: {exc}"
        )
    with _JOB_LOCK:
        job = _JOBS.get(key)
        if job is None:
            return
        job.update(counts)
        job["running"] = False
        job["finished_at"] = time.monotonic()


def start_reasoning_translation(
    task_id: str,
    locale: str,
    force: bool = False,
) -> Dict[str, Any]:
    """Start a pass on a worker thread; returns the status the caller answers with.

    A second request while one is running joins it instead of starting another
    (``started`` is false): two threads on one task would translate the same traces
    twice and double the endpoint's load for nothing.
    """
    entry = translation_model()
    if entry is None:
        raise TranslationNotConfigured(
            "No translation model is configured; choose one in the global settings."
        )
    if not is_supported_locale(locale):
        raise ValueError(f"Unsupported locale '{locale}'.")

    key = (str(task_id), str(locale))
    with _JOB_LOCK:
        _prune_jobs(time.monotonic())
        job = _JOBS.get(key)
        if job is not None and job["running"]:
            return {
                "model_id": str(entry["model_id"]),
                "started": False,
                "running": True,
                **{name: int(job.get(name) or 0) for name in _JOB_COUNTERS},
            }
        _JOBS[key] = {
            "running": True,
            "finished_at": 0.0,
            **dict.fromkeys(_JOB_COUNTERS, 0),
        }

    worker = threading.Thread(
        target=_run_translation_job,
        args=(key, str(task_id), str(locale), bool(force)),
        name=f"reasoning-translate-{task_id}",
        daemon=True,
    )
    worker.start()
    return {
        "model_id": str(entry["model_id"]),
        "started": True,
        "running": True,
        **dict.fromkeys(_JOB_COUNTERS, 0),
    }


__all__ = [
    "LOCALE_LANGUAGES",
    "MAX_CHUNK_CHARS",
    "SUPPORTED_LOCALES",
    "TranslationNotConfigured",
    "is_supported_locale",
    "reasoning_traces",
    "split_reasoning",
    "start_reasoning_translation",
    "translate_chunks",
    "translate_missing_reasoning",
    "translate_reasoning_text",
    "translation_model",
    "translation_status",
]

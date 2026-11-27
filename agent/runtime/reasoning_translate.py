"""Translating a task's reasoning traces into the language the console is read in.

The translation model is one global setting (:data:`commons.state.translation_model_id`).
While it is unset nothing is translated: spending tokens on every finished task is not
something to opt into by accident, and the page offers the switch.

A trace is translated once per language and then stored, so the automatic pass after a
task finishes and the log's manual action cost one call per trace in total, not one per
view. A failure is not stored, which is what makes the next click a retry.

The route is synchronous on purpose: the provider call blocks, so FastAPI runs it on its
worker thread instead of stalling the event loop (``routes/task_api.py``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from agent.models import EventCategory
from agent.provider import ProviderConfig, build_provider
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


def translate_reasoning_text(text: str, language: str, provider: Any) -> str:
    """Translate one trace through ``provider``, one request per chunk."""
    messages_system = _TRANSLATE_PROMPT.format(language=language)
    parts: List[str] = []
    for chunk in split_reasoning(text):
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
    provider = None
    items: Dict[str, str] = {}
    errors: List[str] = []
    translated = 0
    skipped = 0
    failed = 0

    for event_id, text in reasoning_traces(task_id):
        if not force and event_id in stored:
            items[event_id] = stored[event_id]
            skipped += 1
            continue
        try:
            if provider is None:
                provider = build_provider(provider_name, provider_config)
            translation = translate_reasoning_text(text, language, provider)
        # Broad on purpose: one bad trace must not drop the translations that did
        # work, and an unreadable answer is a retry rather than an error page.
        except Exception as exc:  # noqa: BLE001
            failed += 1
            errors.append(f"{event_id}: {exc.__class__.__name__}: {exc}")
            continue
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
        "errors": errors,
    }


__all__ = [
    "LOCALE_LANGUAGES",
    "MAX_CHUNK_CHARS",
    "SUPPORTED_LOCALES",
    "TranslationNotConfigured",
    "is_supported_locale",
    "reasoning_traces",
    "split_reasoning",
    "translate_missing_reasoning",
    "translate_reasoning_text",
    "translation_model",
]

"""What a memory record is: the four kinds, the limits, and the checks before writing.

The rules live here rather than inside the tools that write them because two writers
share them: ``memory_save`` (the model asking to keep something) and the post-task
extractor (``agent.runtime.memory_extract``). A rule only one of them enforced would
let the other write what the first refuses.

A record is a small, self-describing note:

- ``name``        a slug, the identity of the memory (saving the same name replaces it)
- ``type``        ``user`` / ``feedback`` / ``project`` / ``reference``
- ``description`` one line, what the prompt index shows
- ``body``        the note itself, read only when it matters

Nothing here reads or writes a store, so both writers can validate before touching one.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# What the tools, the API and the extractor agree on. A plain tuple rather than an
# enum: the value is stored as text and rendered into prompts, so it stays a string.
MEMORY_TYPES = ("user", "feedback", "project", "reference")

TYPE_HINTS: Dict[str, str] = {
    "user": "a lasting preference of the user (tooling, style, language)",
    "feedback": "working feedback that still applies next time (how to do the work)",
    "project": "a stable fact about the project (decisions, constraints, layout)",
    "reference": "where something lives outside the repo (a page, a ticket, a system)",
}

# How a candidate says whether it outlives the conversation. Only ``persistent`` is
# stored: "do not create files in this session" constrains this task and would be
# wrong to carry into the next one (ADR 0035).
SCOPES = ("persistent", "current_task")

MAX_NAME_CHARS = 48
MAX_DESCRIPTION_CHARS = 200
MAX_BODY_CHARS = 4000
# A hard ceiling on the library itself. The prompt index is capped separately, but a
# store that grows without bound eventually makes recall a selection problem nobody
# can judge, so writing stops and says so instead.
MAX_MEMORIES = 200
# How much of the index enters a system prompt. Bodies never enter it: they are read
# through ``memory_search``, which is what keeps the prompt from growing with the
# library (ADR 0035).
DEFAULT_MAX_PROMPT_CHARS = 4000
# The ceiling the admin API will store. A prompt index is background knowledge, and one
# that costs more than this is a library that needs pruning, not a bigger budget.
MAX_PROMPT_CHARS = 12000

# A name becomes a file-system-friendly, provider-neutral identifier that survives
# being echoed back by the model: lower case, unicode letters and digits, single
# dashes. Chinese names are kept rather than transliterated - they are what the user
# and the model both wrote.
_SLUG_SEPARATORS = re.compile(r"[^\w]+", re.UNICODE)

# Language that only means something inside the conversation it was said in. The list
# is deliberately small and explicit: a broader heuristic would reject genuine project
# facts for containing the word "task".
_TEMPORARY_MARKERS = (
    "this session",
    "this conversation",
    "current task",
    "in this task",
    "for this task",
    "for now",
    "本次会话",
    "本次任务",
    "当前任务",
    "这次任务",
    "这次不要",
    "临时",
)


def memory_slug(name: Any) -> str:
    """Normalize a memory name into the identity a later save replaces."""
    text = str(name or "").strip().lower()
    text = _SLUG_SEPARATORS.sub("-", text).strip("-")
    return text[:MAX_NAME_CHARS].strip("-")


def one_line(text: Any) -> str:
    """Collapse whitespace: a description is an index line, not a paragraph."""
    return " ".join(str(text or "").split())


def _temporary_marker(*texts: str) -> str:
    """The phrase that makes a candidate session-scoped, or an empty string."""
    haystack = " ".join(texts).lower()
    for marker in _TEMPORARY_MARKERS:
        if marker in haystack:
            return marker
    return ""


def parse_record(
    payload: Mapping[str, Any],
    *,
    require_scope: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Normalize one candidate; returns ``(record, None)`` or ``(None, why not)``.

    ``require_scope`` is for the model-facing paths, where the model has to say whether
    what it learned outlives the conversation. The management API omits it: a person
    typing a memory into the admin page is not a candidate that has to prove itself.
    """
    if not isinstance(payload, Mapping):
        return None, "a memory is an object with name, type, description and body."

    name = memory_slug(payload.get("name"))
    if not name:
        return None, "name is required: a short identifier with letters, digits or dashes."

    memory_type = str(payload.get("type") or payload.get("memory_type") or "").strip().lower()
    if memory_type not in MEMORY_TYPES:
        allowed = ", ".join(MEMORY_TYPES)
        return None, f"type must be one of {allowed}; got {memory_type or 'nothing'!r}."

    description = one_line(payload.get("description"))
    if not description:
        return None, "description is required: one line saying what the memory is about."
    if len(description) > MAX_DESCRIPTION_CHARS:
        return None, (
            f"description is {len(description)} characters; an index line stays under "
            f"{MAX_DESCRIPTION_CHARS}."
        )

    body = str(payload.get("body") or "").strip()
    if not body:
        return None, "body is required: the note itself, in the user's language."
    if len(body) > MAX_BODY_CHARS:
        return None, (
            f"body is {len(body)} characters; keep a memory under {MAX_BODY_CHARS} so "
            "recalling it stays cheap."
        )

    if require_scope:
        scope = str(payload.get("scope") or "").strip().lower()
        if scope not in SCOPES:
            return None, "scope must be 'persistent' or 'current_task'."
        if scope != "persistent":
            return None, (
                "only facts that still matter in a later session are stored. This one was "
                "scoped to the current task, so it was not saved - keep following it for "
                "the rest of this task, but do not treat it as a lasting rule."
            )

    temporary = _temporary_marker(description, body)
    if temporary:
        return None, (
            f"the phrase {temporary!r} marks this as limited to the current conversation, "
            "and a memory outlives it. Save the lasting part, or nothing."
        )

    return {
        "name": name,
        "type": memory_type,
        "description": description,
        "body": body,
    }, None


def should_store(
    record: Mapping[str, Any],
    existing: Iterable[Mapping[str, Any]],
) -> Tuple[bool, str]:
    """Whether writing ``record`` changes anything; ``(False, why)`` when it does not.

    Only the body is compared, and across the whole library rather than within one name:
    the same note re-proposed under a second name is the duplicate that actually happens
    (a model rephrasing its own slug). Everything else - a new name, a corrected body
    under the same name - is a change worth writing.
    """
    for item in existing:
        if str(item.get("body") or "") == record["body"]:
            return False, f"the same note is already stored as {item.get('name')!r}."
    return True, ""


def render_memory_line(record: Mapping[str, Any]) -> str:
    """One index line: the type, the name, and what the memory is about."""
    description = one_line(record.get("description"))[:MAX_DESCRIPTION_CHARS]
    return f"- [{record.get('type') or 'user'}] {record.get('name')}: {description}"


def render_memory_index(
    records: Sequence[Mapping[str, Any]],
    *,
    max_chars: int = DEFAULT_MAX_PROMPT_CHARS,
) -> str:
    """The index block: as many lines as fit, plus how many did not.

    Truncating here is the whole point of keeping bodies out of the prompt: a library
    of two hundred notes still costs a bounded number of characters, and the note that
    did not fit is still reachable through ``memory_search``.
    """
    # A record without a name is not a memory: skipping it keeps a malformed row from
    # rendering as "- [user] None:" in every prompt.
    named = [record for record in records if str(record.get("name") or "").strip()]
    lines: List[str] = []
    used = 0
    for index, record in enumerate(named):
        line = render_memory_line(record)
        if used + len(line) + 1 > max_chars:
            remaining = len(named) - index
            lines.append(
                f"- ({remaining} more memories are not shown; call memory_search with a "
                "keyword to find one.)"
            )
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def _search_terms(query: Any) -> List[str]:
    return [term for term in re.split(r"[\s,;/|]+", str(query or "").lower()) if term]


def rank_memories(
    records: Sequence[Mapping[str, Any]],
    query: Any,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """The records matching ``query``, best first, at most ``limit`` of them.

    This is the fallback the reference implementation keeps behind its model-based
    selection, and here it is the only path: the index is already in the prompt, so
    what a search has to answer is "which bodies are worth reading", not "which notes
    might matter" (ADR 0035). Name hits weigh more than description hits, which weigh
    more than body hits.
    """
    terms = _search_terms(query)
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for record in records:
        name = str(record.get("name") or "").lower()
        description = str(record.get("description") or "").lower()
        body = str(record.get("body") or "").lower()
        if not terms:
            score = 1
        else:
            score = 0
            for term in terms:
                if term in name:
                    score += 3
                if term in description:
                    score += 2
                if term in body:
                    score += 1
        if score:
            scored.append((score, dict(record)))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("name") or "")))
    return [record for _, record in scored[: max(1, limit)]]

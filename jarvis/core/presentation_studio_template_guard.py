"""Garde-fous de promotion et d'instanciation d'un modele de presentation (handoff jarvis-remotion-presentation-integration, Slice 19, QA).

Petites fonctions que `PresentationStudioTemplates` appelle : la taille du document SERIALISE contre le plafond reel d'un document du Studio, les mots
de la partition (du contenu du projet comme un autre), la signalisation d'une presentation a moitie faite, le blanchiment des emplacements locaux.
Contrat : `docs/presentation-studio.md` > *Template and prefab promotion contract*.
"""

from __future__ import annotations

import json
from typing import Any

from jarvis.domain.presentation_studio_template import MAX_TEMPLATE_BYTES
from jarvis.domain.presentation_studio_template_sanitize import Finding

FAILED_MARKER = "[instantiation \u00e9chou\u00e9e] "


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def record_size_finding(document: dict[str, Any]) -> Finding | None:
    """The SERIALIZED record against the real cap of a stored document, with the part that weighs: the plan says no when the write would."""

    size = _size(document) + 1
    if size <= MAX_TEMPLATE_BYTES:
        return None
    embedded, score = _size(document["embedded"]), _size(document["score"]) if document["score"] else 0
    return Finding("embedded_too_large", "record", f"the record would weigh {size} bytes once serialized, over the {MAX_TEMPLATE_BYTES} a stored "
                   f"template holds: the embedded sources weigh {embedded} of them (score {score}); promote the heavy scene to the library on its "
                   "own, or lighten its sources")


def spoken_words(score: dict[str, Any] | None) -> list[str]:
    """What the score SAYS (speech, notes, labels, cue phrases, sequence steps): the project's content like a title, searched in the sources."""

    if not score:
        return []
    words: list[str] = [i.get(k, "") for i in score.get("items", ()) for k in ("label", "text", "note")]
    for cue in score.get("cues", ()):
        words += [cue.get("label", ""), *((cue.get("predicate") or {}).get("phrases") or ())]
    for seq in score.get("sequences", ()):
        words += [seq.get("label", ""), *(step.get("text", "") for step in seq.get("steps", ()))]
    words += [r.get("label", "") for r in score.get("recovery_points", ())]
    return [w for w in words if isinstance(w, str) and w]


async def mark_failed(studio: Any, presentation_id: str, title: str, cause: BaseException) -> tuple[str, str]:
    """`(sentence for the error, code of the cause)`. Best effort and honest about it: Core has no deletion of a presentation and the library none of
    a prefab, so the half-made presentation is RENAMED with a visible marker and the failure is journaled by the caller. The presentation-scoped
    sources already published are unpinned and age out through the retention (archived after an hour, never deleted)."""

    code = getattr(getattr(cause, "code", None), "value", type(cause).__name__)
    text = "marked '[instantiation \u00e9chou\u00e9e]' in its title; nothing was deleted"
    try:
        view = await studio.get(presentation_id)
        await studio.save_presentation(presentation_id, {
            "expected_revision": view.presentation.revision, "title": (FAILED_MARKER + title)[:80],
            "active_variant_id": view.presentation.active_variant_id, "resources": []})
    except Exception as exc:  # noqa: BLE001 - the original failure matters more; this one is said, not hidden
        text = f"it could NOT be marked ({getattr(getattr(exc, 'code', None), 'value', type(exc).__name__)}): archive or finish it by hand"
    return text, code


def blank(value: Any, slots: set[str]) -> Any:
    """A copy where the record-local slots are blanked, so a real project id left in a score is still found by the final net."""

    if isinstance(value, str):
        return "" if value in slots else value
    if isinstance(value, list):
        return [blank(v, slots) for v in value]
    if isinstance(value, dict):
        return {k: blank(v, slots) for k, v in value.items()}
    return value

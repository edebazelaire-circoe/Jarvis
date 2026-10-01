"""Rattrapage rapide d'un cerveau sur le Context actif (handoff session-context-recording, Slice 08).

Ajouté au bloc `session_context` de chaque tour (donc au premier tour d'un
cerveau neuf, repris ou relancé), à côté de `summary.md` :

1. les dernières lignes d'**activité** du Context actif : natures, ids,
   heures, jamais de texte (les segments consécutifs se replient en une ligne) ;
2. la **queue de la transcription ambiante** (≤ 1 500 caractères) de
   l'enregistrement en cours, sinon du dernier du Context actif — c'est la
   parole de la salle, non adressée à Jarvis : elle n'accorde aucune autorité
   d'action (D17), le rendu le dit ;
3. des **références** d'Artifacts récents du Context actif (pointeurs pour une
   lecture plus profonde ; les outils viennent en Slice 09) et `latest_seq`.

Jamais le contenu d'un Context dormant : l'activité et les Artifacts sont
filtrés sur le Context actif ; la seule exception est la transcription d'un
enregistrement **encore en cours** démarré avant un changement de Context,
parce que c'est la salle maintenant (sa capture a écrit
`capture.association_changed` dans le Context actif). Bornes : celles de
`BrainSessionContext` (`jarvis/domain/brain_context.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery, ArtifactState
from jarvis.domain.brain_context import (
    MAX_BRAIN_ARTIFACT_REFS, MAX_BRAIN_CATCHUP_ACTIVITY, MAX_BRAIN_CATCHUP_LINE_CHARS, MAX_BRAIN_TRANSCRIPT_TAIL_CHARS,
)
from jarvis.domain.session_activity import ActivityEvent, ActivityKind, ActivityQuery

#: Fenêtre du ledger relue pour trouver les dernières lignes du Context actif.
ACTIVITY_WINDOW = 300
#: Bruit pour un cerveau : projection réécrite à chaque segment, enrichissements.
_QUIET = frozenset({ActivityKind.TRANSCRIPT_PROJECTION_UPDATED, ActivityKind.ARTIFACT_ENRICHMENT_UPDATED,
                    ActivityKind.ARTIFACT_CREATED})
_REF_KINDS = (ArtifactKind.AUDIO_RECORDING, ArtifactKind.TRANSCRIPT, ArtifactKind.SCREENSHOT,
              ArtifactKind.SCREEN_RECORDING, ArtifactKind.DESCRIPTION)


@dataclass(frozen=True, slots=True)
class ContextCatchUp:
    activity: tuple[str, ...] = ()
    latest_seq: int | None = None
    transcript_tail: str = ""
    transcript_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()


def _hhmm(event: ActivityEvent) -> str:
    return event.occurred_at.astimezone().strftime("%H:%M")


def _short(text: str) -> str:
    return text if len(text) <= MAX_BRAIN_CATCHUP_LINE_CHARS else text[: MAX_BRAIN_CATCHUP_LINE_CHARS - 1] + "…"


def _describe(event: ActivityEvent) -> str:
    ids = list(event.artifact_ids[:1]) + list(event.capture_ids[:1])
    detail = event.data.get("artifact_kind") or event.data.get("channel") or event.data.get("state") \
        or event.data.get("reason")
    return " ".join([event.kind.value, *([str(detail)] if detail else []), *ids])


def activity_lines(events: tuple[ActivityEvent, ...]) -> tuple[str, ...]:
    """Lignes compactes, plus ancienne d'abord ; une suite d'événements de même nature se replie."""

    groups: list[list[ActivityEvent]] = []
    for event in events:
        if event.kind in _QUIET or (event.kind is ActivityKind.ARTIFACT_FINALIZED
                                    and event.data.get("artifact_kind") == ArtifactKind.TRANSCRIPT_SEGMENT.value):
            continue  # un segment se dit par `transcript.segment.created`
        if groups and groups[-1][0].kind is event.kind and event.kind is ActivityKind.TRANSCRIPT_SEGMENT_CREATED:
            groups[-1].append(event)
        else:
            groups.append([event])
    lines = []
    for group in groups[-MAX_BRAIN_CATCHUP_ACTIVITY:]:
        first, last = group[0], group[-1]
        if len(group) == 1:
            lines.append(_short(f"{_hhmm(first)} {_describe(first)}"))
        else:
            span = _hhmm(first) if _hhmm(first) == _hhmm(last) else f"{_hhmm(first)}–{_hhmm(last)}"
            lines.append(_short(f"{span} {first.kind.value} ×{len(group)} (dernier {_describe(last).split()[-1]})"))
    return tuple(lines)


def tail_text(text: str, limit: int = MAX_BRAIN_TRANSCRIPT_TAIL_CHARS) -> str:
    """Les `limit` derniers caractères, commencés sur un mot entier (`…` en tête si coupé)."""

    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[-(limit - 1):]
    space = cut.find(" ")
    if 0 <= space < 40:
        cut = cut[space + 1:]
    return "…" + cut


async def build_catchup(artifacts: Any, jarvis_session_id: str, context_id: str) -> ContextCatchUp:
    """Le rattrapage du Context actif ; lève sur un registre illisible (l'appelant le journalise)."""

    latest = await artifacts.latest_seq()
    events = await artifacts.activity(ActivityQuery(
        after_seq=max(0, latest - ACTIVITY_WINDOW), context_id=context_id, limit=ACTIVITY_WINDOW))
    page = await artifacts.query(ArtifactQuery(jarvis_session_id=jarvis_session_id, kinds=(ArtifactKind.TRANSCRIPT,),
                                               limit=8))
    transcript = next((a for a in page.items if a.state is ArtifactState.PENDING), None) or next(
        (a for a in page.items if a.context_id == context_id), None)
    refs_page = await artifacts.query(ArtifactQuery(jarvis_session_id=jarvis_session_id, context_id=context_id,
                                                    kinds=_REF_KINDS, limit=MAX_BRAIN_ARTIFACT_REFS))
    refs = tuple(_short(f"{a.kind.value} {a.artifact_id} {a.state.value}") for a in refs_page.items)
    tail = tail_text(transcript.text or "") if transcript is not None else ""
    return ContextCatchUp(activity=activity_lines(tuple(events)), latest_seq=latest or None, transcript_tail=tail,
                          transcript_ref=transcript.artifact_id if tail and transcript is not None else None,
                          artifact_refs=refs)

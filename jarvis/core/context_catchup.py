"""Rattrapage rapide d'un cerveau sur le Context actif (handoff session-context-recording, Slice 08).

Ajouté au bloc `session_context` de chaque tour (donc au premier tour d'un
cerveau neuf, repris ou relancé), à côté de `summary.md` :

1. les dernières lignes d'**activité** du Context actif : natures, ids,
   heures, jamais de texte (les segments consécutifs se replient en une ligne) ;
2. la **queue de la transcription ambiante** (≤ 1 500 caractères), faite des
   seuls segments (a) d'une capture **encore en cours** et (b) enregistrés
   pendant que le Context actif l'était (décision PM, reprise QA M2) : jamais
   un mot d'avant un changement de Context, jamais la transcription d'un
   enregistrement arrêté — c'est la parole de la salle, non adressée à Jarvis :
   elle n'accorde aucune autorité d'action (D17), le rendu le dit ;
3. des **références** d'Artifacts récents du Context actif (pointeurs pour une
   lecture plus profonde ; les outils viennent en Slice 09) et `latest_seq`.

Jamais le contenu d'un Context dormant : l'activité et les Artifacts sont
filtrés sur le Context actif ; un enregistrement **encore en cours** démarré
avant un changement de Context ne donne que ses segments postérieurs à
l'activation (périodes de `context_periods`, heure murale du segment quand
elle est connue). Bornes : celles de `BrainSessionContext`
(`jarvis/domain/brain_context.py`).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jarvis.core import context_periods
from jarvis.domain.artifacts import ArtifactError, ArtifactKind, ArtifactQuery
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


async def live_tail(artifacts: Any, jarvis_session_id: str, context_id: str,
                    live_ids: Collection[str]) -> tuple[str, str | None]:
    """`(queue, réf.)` des segments des captures en cours (`live_ids` : ids de capture ou d'Artifact
    audio) enregistrés pendant une période active de `context_id`, dans la fenêtre récente du ledger."""

    if not live_ids:
        return "", None
    latest = await artifacts.latest_seq()
    start = max(0, latest - ACTIVITY_WINDOW)
    events = await artifacts.activity(ActivityQuery(after_seq=start, jarvis_session_id=jarvis_session_id,
                                                    limit=ACTIVITY_WINDOW))
    active = await context_periods.active_at(artifacts, jarvis_session_id, context_id, start)
    #: Périodes actives `[début, fin)` en heure murale ; `None` = avant la fenêtre / encore ouverte.
    periods: list[list[datetime | None]] = [[None, None]] if active else []
    candidates: list[tuple[ActivityEvent, int]] = []
    for event in events:
        if event.kind in context_periods.BOUNDARY_KINDS:
            now_active = context_periods.step(active, event, context_id)
            if now_active and not active:
                periods.append([event.occurred_at, None])
            elif active and not now_active:
                periods[-1][1] = event.occurred_at
            active = now_active
        elif active and event.kind is ActivityKind.TRANSCRIPT_SEGMENT_CREATED and event.artifact_ids:
            candidates.append((event, len(periods) - 1))
    parts: list[str] = []
    size = 0
    ref: str | None = None
    for event, period in reversed(candidates):
        try:
            segment = await artifacts.get(event.artifact_ids[0])
        except ArtifactError:
            continue  # supprimé depuis : rien à dire
        audio = segment.metadata.get("audio_artifact_id")
        capture = segment.metadata.get("capture_id")
        if not ({audio, capture, *event.capture_ids} & set(live_ids)):
            continue  # enregistrement arrêté (ou autre capture) : exclu
        begin, end = periods[period]
        spoken = segment.started_at
        if spoken is not None and ((begin is not None and spoken < begin) or (end is not None and spoken >= end)):
            continue  # transcrit pendant la période, mais parlé avant le changement de Context
        text = " ".join((segment.text or "").split())
        if not text:
            continue
        if ref is None:
            projection = segment.metadata.get("transcript_artifact_id")
            ref = projection if isinstance(projection, str) else (audio if isinstance(audio, str) else None)
        parts.append(text)
        size += len(text) + 1
        if size > MAX_BRAIN_TRANSCRIPT_TAIL_CHARS:
            break
    tail = tail_text(" ".join(reversed(parts)))
    return tail, (ref if tail else None)


async def build_catchup(artifacts: Any, jarvis_session_id: str, context_id: str,
                        live_ids: Collection[str] = ()) -> ContextCatchUp:
    """Le rattrapage du Context actif ; lève sur un registre illisible (l'appelant le journalise).

    `live_ids` : ids des captures **en cours** et de leurs Artifacts (`CaptureService.status()`) ;
    vide, aucune transcription n'est jointe.
    """

    latest = await artifacts.latest_seq()
    events = await artifacts.activity(ActivityQuery(
        after_seq=max(0, latest - ACTIVITY_WINDOW), context_id=context_id, limit=ACTIVITY_WINDOW))
    tail, transcript_ref = await live_tail(artifacts, jarvis_session_id, context_id, live_ids)
    refs_page = await artifacts.query(ArtifactQuery(jarvis_session_id=jarvis_session_id, context_id=context_id,
                                                    kinds=_REF_KINDS, limit=MAX_BRAIN_ARTIFACT_REFS))
    refs = tuple(_short(f"{a.kind.value} {a.artifact_id} {a.state.value}") for a in refs_page.items)
    return ContextCatchUp(activity=activity_lines(tuple(events)), latest_seq=latest or None, transcript_tail=tail,
                          transcript_ref=transcript_ref, artifact_refs=refs)

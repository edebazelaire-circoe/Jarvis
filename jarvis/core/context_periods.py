"""Périodes d'activité d'un Context dans le ledger (handoff session-context-recording, Slice 08).

Une seule règle, partagée par le worker d'enrichissement et le rattrapage du
cerveau (D05) : en marchant le ledger d'une Session par `seq` croissant,
`context.created|activated` d'un Context le rend actif (et tout autre
inactif), `context.dormant` du Context le rend inactif, `session.closed`
rend tout inactif.

`active_at` dérive l'état **à** un `seq` donné du dernier de ces événements
survenu à ce `seq` ou avant : une page lue depuis un curseur ne part donc
jamais d'un « actif » supposé (reprise QA, B1 : une période dormante plus
longue qu'une page entrait dans le résumé du Context réactivé).

`active_periods` donne les mêmes périodes en **heure murale** (`occurred_at`
des événements de frontière) : un segment de transcription appartient au
Context actif **quand il a été parlé** (`started_at` du segment), pas quand
son événement est journalisé — une transcription en retard ne fait pas passer
la parole de A dans B (reprise finale, D05 ; même règle que le rattrapage).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from jarvis.domain.session_activity import MAX_ACTIVITY_LIMIT, ActivityEvent, ActivityKind, ActivityQuery

#: Les seuls événements qui changent l'état actif d'un Context.
BOUNDARY_KINDS = (ActivityKind.CONTEXT_CREATED, ActivityKind.CONTEXT_ACTIVATED, ActivityKind.CONTEXT_DORMANT,
                  ActivityKind.SESSION_CLOSED)


def step(active: bool, event: ActivityEvent, context_id: str) -> bool:
    """L'état actif de `context_id` après `event` (inchangé pour tout autre événement)."""

    kind = event.kind
    if kind in {ActivityKind.CONTEXT_CREATED, ActivityKind.CONTEXT_ACTIVATED}:
        return event.context_id == context_id
    if kind is ActivityKind.CONTEXT_DORMANT and event.context_id == context_id:
        return False
    if kind is ActivityKind.SESSION_CLOSED:
        return False
    return active


async def active_at(artifacts: Any, jarvis_session_id: str, context_id: str, seq: int) -> bool:
    """`context_id` était-il actif juste après l'événement `seq` ?

    Pages de `BOUNDARY_KINDS` de la Session (peu nombreux : quelques-uns par
    changement de Context). Sans aucun événement de frontière jusque-là :
    actif (Context adopté sans `context.created`, seul de sa Session).
    """

    active = True
    after = 0
    while after < seq:
        page = await artifacts.activity(ActivityQuery(after_seq=after, jarvis_session_id=jarvis_session_id,
                                                      kinds=BOUNDARY_KINDS, limit=MAX_ACTIVITY_LIMIT))
        for event in page:
            if event.seq > seq:
                return active
            active = step(active, event, context_id)
        if len(page) < MAX_ACTIVITY_LIMIT:
            return active
        after = page[-1].seq
    return active


#: Période active `[début, fin)` en heure murale ; `None` = depuis toujours / encore ouverte.
Period = tuple[datetime | None, datetime | None]


async def active_periods(artifacts: Any, jarvis_session_id: str, context_id: str) -> list[Period]:
    """Toutes les périodes actives de `context_id` dans sa Session, en heure murale.

    Même marche et même départ que `active_at` (actif sans événement de frontière), à une
    différence près : rien de parlé avant la naissance (`context.created`) du Context ne lui
    appartient, ni avant sa première activation quand elle est la première frontière.
    """

    active, first = True, True
    begin: datetime | None = None
    periods: list[Period] = []
    after = 0
    while True:
        page = await artifacts.activity(ActivityQuery(after_seq=after, jarvis_session_id=jarvis_session_id,
                                                      kinds=BOUNDARY_KINDS, limit=MAX_ACTIVITY_LIMIT))
        for event in page:
            now_active = step(active, event, context_id)
            if event.kind is ActivityKind.CONTEXT_CREATED and event.context_id == context_id:
                periods.clear()  # naissance : la période supposée d'avant ne lui appartenait pas
                begin = event.occurred_at
            elif now_active and (not active or first):
                begin = event.occurred_at
            elif active and not now_active:
                periods.append((begin, event.occurred_at))
            active, first = now_active, False
        if len(page) < MAX_ACTIVITY_LIMIT:
            break
        after = page[-1].seq
    if active:
        periods.append((begin, None))
    return periods


def spoken_within(periods: list[Period], moment: datetime) -> bool:
    """`moment` (heure parlée d'un segment) tombe-t-il dans une des `periods` ?"""

    return any((begin is None or begin <= moment) and (end is None or moment < end) for begin, end in periods)


__all__ = ["BOUNDARY_KINDS", "Period", "active_at", "active_periods", "spoken_within", "step"]

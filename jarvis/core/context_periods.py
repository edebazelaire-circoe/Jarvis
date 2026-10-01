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
"""

from __future__ import annotations

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


__all__ = ["BOUNDARY_KINDS", "active_at", "step"]

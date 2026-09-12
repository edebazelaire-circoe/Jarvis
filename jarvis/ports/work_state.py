"""Ports de l'état de travail Core (handoff work-state, tâche 10).

Deux coutures, implémentées par le `WorkStateStore` de la tâche 11 :

- `WorkObservationSink` : l'entrée des observateurs de bord
  (`AgentTaskTracker`, `JobService`, un futur observateur Codex). Ils
  constatent ; Core normalise, ordonne et révise ;
- `WorkStateReader` : la lecture de l'état retenu, commune au cerveau et à
  l'UI (Décision D16). Aucun consommateur ne modifie l'état par ce port.
"""

from __future__ import annotations

from typing import Protocol

from jarvis.domain.work_state import WorkObservation, WorkSnapshot


class WorkObservationSink(Protocol):
    """Entrée des observations de travail, possédée par Core.

    L'observateur ne connaît ni la révision, ni les règles de transition, ni
    le bus : il remet un constat borné et neutre. Une observation périmée,
    en double ou contredisant un état terminal n'est pas une erreur pour lui
    — Core l'ignore selon `apply_observation`.

    Concurrence : `observe` peut être appelé depuis la boucle d'un
    observateur qui lit un flux en direct ; l'implémentation ne doit pas le
    bloquer (file bornée ou application immédiate, jamais d'attente réseau
    sans borne).
    """

    async def observe(self, observation: WorkObservation) -> None: ...


class WorkStateReader(Protocol):
    """Lecture seule de l'état de travail normalisé.

    L'instantané rendu est immuable et borné (`MAX_WORK_ITEMS`) : il peut
    être projeté tel quel vers le cerveau ou l'UI.
    """

    async def snapshot(self) -> WorkSnapshot: ...

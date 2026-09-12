"""Contexte d'exécution d'un tour cerveau (handoff work-state, tâche 12).

Le cerveau doit connaître le travail en cours aussi bien que l'UI qui
l'affiche (Décision D16) : statut, libellé, activité, modèle, durées, issue.
Ce module en donne la projection **bornée** que Core assemble à chaque tour
depuis son `WorkSnapshot` et remet au backend :

- `BrainWorkEntry` : un travail, réduit à ses faits publics et opérationnels ;
- `WorkAttention` : un changement inattendu (échec, interruption, blocage)
  relevé par la politique d'événements de Core depuis le dernier tour ;
- `BrainWorkContext` : l'ensemble borné, avec la révision et l'identité du
  magasin lu, pour qu'on puisse prouver que le cerveau et l'UI lisent la même
  source ;
- `BrainContext` : l'agrégat remis au backend (état de travail public du
  cerveau + contexte de travail), extensible sans changer la signature du port.

Rien ici ne vient d'une trace de fournisseur ni d'un raisonnement : seuls des
champs déjà publics de `WorkItem` sont repris, tronqués (Décision 12).

Bornes dures : au plus `MAX_BRAIN_WORK_ACTIVE` travaux actifs puis
`MAX_BRAIN_WORK_FINISHED` terminés récents, `MAX_BRAIN_WORK_ATTENTION`
changements, chaque texte tronqué, et une forme de fil qui ne dépasse jamais
`MAX_BRAIN_WORK_CONTEXT_CHARS` caractères. Ce qui ne tient pas est compté,
jamais rendu partiellement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from jarvis.domain.v2 import BrainWorkingState
from jarvis.domain.work_state import WorkItem, WorkSnapshot, WorkStatus, clip_text

#: Travaux actifs listés au cerveau, bloqués d'abord puis du plus ancien au
#: plus récent : ce qui tourne répond à « où en sont mes tâches ? ».
MAX_BRAIN_WORK_ACTIVE = 12
#: Travaux terminés récents, du plus récent au plus ancien.
MAX_BRAIN_WORK_FINISHED = 6
#: Changements inattendus remis au prochain tour ; au-delà, les plus anciens
#: tombent (ils restent visibles comme travaux terminés).
MAX_BRAIN_WORK_ATTENTION = 8
MAX_BRAIN_LABEL_CHARS = 120
MAX_BRAIN_ACTIVITY_CHARS = 120
MAX_BRAIN_SUMMARY_CHARS = 240
#: Garde-fou global sur la forme de fil (JSON compact) remise au backend.
MAX_BRAIN_WORK_CONTEXT_CHARS = 6_000

#: Statuts qui méritent l'attention du cerveau quand un travail actif y passe :
#: il a échoué, son hôte a disparu, ou il attend l'utilisateur. Une réussite
#: suit le chemin normal du résultat, une annulation est une décision connue.
ATTENTION_WORK_STATUSES = frozenset({WorkStatus.FAILED, WorkStatus.INTERRUPTED, WorkStatus.BLOCKED})


def needs_attention(previous: WorkStatus | None, current: WorkStatus) -> bool:
    """Vrai pour un changement que le cerveau doit apprendre sans l'avoir demandé.

    Seul un travail **actif** qui passe en échec, en interruption ou en
    blocage compte. Une création déjà terminée (`previous is None`) n'est pas
    un événement : c'est ce que rejoue un producteur après un redémarrage de
    Core, et en faire une alerte inonderait le cerveau de vieilles nouvelles.
    """

    return (
        previous is not None
        and not previous.is_terminal
        and current is not previous
        and current in ATTENTION_WORK_STATUSES
    )


def _check_short(name: str, value: str, limit: int) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if len(value) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")


def _seconds(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds()))


def _compact_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


@dataclass(frozen=True, slots=True)
class BrainWorkEntry:
    """Un travail tel que le cerveau le reçoit : faits publics, textes tronqués.

    `elapsed_s` est la durée écoulée depuis le début (jusqu'à la fin pour un
    travail terminé) ; `ended_ago_s` l'ancienneté de la fin. Core les calcule
    au moment d'assembler le contexte : le backend n'a pas de calcul de date
    à refaire, et deux horloges ne se contredisent pas.
    """

    source: str
    external_id: str
    status: WorkStatus
    started_at: datetime
    elapsed_s: int
    label: str = ""
    activity: str = ""
    summary: str = ""
    model: str = ""
    ended_at: datetime | None = None
    ended_ago_s: int | None = None
    error_class: str | None = None
    work_id: str | None = None
    parent_external_id: str | None = None
    progress_fraction: float | None = None
    background: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, WorkStatus):
            raise TypeError("status must be a WorkStatus")
        _check_short("label", self.label, MAX_BRAIN_LABEL_CHARS)
        _check_short("activity", self.activity, MAX_BRAIN_ACTIVITY_CHARS)
        _check_short("summary", self.summary, MAX_BRAIN_SUMMARY_CHARS)
        if self.elapsed_s < 0 or (self.ended_ago_s is not None and self.ended_ago_s < 0):
            raise ValueError("durations must be positive or zero")
        if self.status.is_terminal != (self.ended_at is not None):
            raise ValueError("ended_at is set exactly when the status is terminal")

    @classmethod
    def from_item(cls, item: WorkItem, *, now: datetime) -> BrainWorkEntry:
        end = item.ended_at or max(now, item.started_at)
        return cls(
            source=item.source,
            external_id=item.external_id,
            status=item.status,
            started_at=item.started_at,
            elapsed_s=_seconds(item.started_at, end),
            label=clip_text(item.label, MAX_BRAIN_LABEL_CHARS),
            activity=clip_text(item.activity, MAX_BRAIN_ACTIVITY_CHARS),
            summary=clip_text(item.summary, MAX_BRAIN_SUMMARY_CHARS),
            model=item.model,
            ended_at=item.ended_at,
            ended_ago_s=_seconds(item.ended_at, now) if item.ended_at is not None else None,
            error_class=item.error_class,
            work_id=item.link.work_id,
            parent_external_id=item.parent_external_id,
            progress_fraction=item.progress_fraction,
            background=item.background,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "external_id": self.external_id,
            "status": self.status.value,
            "label": self.label,
            "activity": self.activity,
            "summary": self.summary,
            "model": self.model,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at is not None else None,
            "elapsed_s": self.elapsed_s,
            "ended_ago_s": self.ended_ago_s,
            "error_class": self.error_class,
            "work_id": self.work_id,
            "parent_external_id": self.parent_external_id,
            "progress_fraction": self.progress_fraction,
            "background": self.background,
        }


@dataclass(frozen=True, slots=True)
class WorkAttention:
    """Changement inattendu d'un travail, relevé par la politique d'événements.

    Ne porte que des faits : quel travail, de quel statut vers quel statut, à
    quelle révision. Ce n'est pas une demande de parole (Décision D17) : le
    cerveau décide si l'utilisateur doit l'apprendre, et comment.
    """

    source: str
    external_id: str
    status: WorkStatus
    previous_status: WorkStatus
    revision: int
    noticed_at: datetime
    label: str = ""
    error_class: str | None = None
    work_id: str | None = None

    def __post_init__(self) -> None:
        if not needs_attention(self.previous_status, self.status):
            raise ValueError("a work attention describes an active work that failed, was interrupted or blocked")
        _check_short("label", self.label, MAX_BRAIN_LABEL_CHARS)
        if self.revision < 1:
            raise ValueError("revision starts at 1")

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.external_id)

    @classmethod
    def from_item(cls, item: WorkItem, *, previous_status: WorkStatus, noticed_at: datetime) -> WorkAttention:
        return cls(
            source=item.source,
            external_id=item.external_id,
            status=item.status,
            previous_status=previous_status,
            revision=item.revision,
            noticed_at=noticed_at,
            label=clip_text(item.label, MAX_BRAIN_LABEL_CHARS),
            error_class=item.error_class,
            work_id=item.link.work_id,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "external_id": self.external_id,
            "status": self.status.value,
            "previous_status": self.previous_status.value,
            "revision": self.revision,
            "noticed_at": self.noticed_at.isoformat(),
            "label": self.label,
            "error_class": self.error_class,
            "work_id": self.work_id,
        }


@dataclass(frozen=True, slots=True)
class BrainWorkContext:
    """Travail en cours remis au cerveau pour un tour, à une révision donnée.

    `revision` et `store_id` sont ceux du `WorkStateStore` lu — les mêmes que
    `GET /v1/work/snapshot` rend à l'UI. `active_total` et `finished_total`
    comptent tout l'instantané ; `items` n'en liste qu'une partie bornée.
    """

    revision: int
    generated_at: datetime
    store_id: str | None = None
    items: tuple[BrainWorkEntry, ...] = ()
    attention: tuple[WorkAttention, ...] = ()
    active_total: int = 0
    finished_total: int = 0

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("revision must be positive or zero")
        if not all(isinstance(entry, BrainWorkEntry) for entry in self.items):
            raise TypeError("items must be BrainWorkEntry values")
        if not all(isinstance(note, WorkAttention) for note in self.attention):
            raise TypeError("attention must be WorkAttention values")
        active = sum(1 for entry in self.items if not entry.status.is_terminal)
        if active > MAX_BRAIN_WORK_ACTIVE or len(self.items) - active > MAX_BRAIN_WORK_FINISHED:
            raise ValueError("too many work entries for a brain context")
        if len(self.attention) > MAX_BRAIN_WORK_ATTENTION:
            raise ValueError("too many attention notes for a brain context")
        if active > self.active_total or len(self.items) - active > self.finished_total:
            raise ValueError("totals cannot be lower than the listed entries")

    @property
    def listed_active(self) -> int:
        return sum(1 for entry in self.items if not entry.status.is_terminal)

    def to_payload(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "store_id": self.store_id,
            "generated_at": self.generated_at.isoformat(),
            "active_total": self.active_total,
            "finished_total": self.finished_total,
            "items": [entry.to_payload() for entry in self.items],
            "attention": [note.to_payload() for note in self.attention],
        }


def build_brain_work_context(
    snapshot: WorkSnapshot,
    *,
    now: datetime,
    store_id: str | None = None,
    attention: tuple[WorkAttention, ...] = (),
    max_chars: int = MAX_BRAIN_WORK_CONTEXT_CHARS,
) -> BrainWorkContext:
    """Réduire un instantané Core au contexte borné d'un tour. Fonction pure.

    Ordre de service du budget de caractères : **changements inattendus
    d'abord** (au plus 8 notes courtes), puis travaux actifs (bloqués d'abord,
    puis du plus ancien au plus récent), puis travaux terminés (du plus récent
    au plus ancien). Une entrée qui ne tient pas arrête son groupe : l'ordre
    reste lisible, et le reste est compté dans les totaux.

    Les changements passent avant la liste des actifs parce qu'ils sont le
    seul canal par lequel le cerveau apprend qu'un travail a échoué, s'est
    interrompu ou attend l'utilisateur : un poste chargé (beaucoup d'actifs
    aux longs libellés) est exactement le cas où ils seraient perdus. Un
    travail actif qui ne tient pas reste, lui, visible au tour suivant.
    """

    active = sorted(
        (item for item in snapshot.items if not item.status.is_terminal),
        key=lambda item: (item.status is not WorkStatus.BLOCKED, item.started_at, item.revision),
    )
    finished = sorted(
        (item for item in snapshot.items if item.status.is_terminal),
        key=lambda item: (item.ended_at, item.revision),
        reverse=True,
    )
    empty = BrainWorkContext(
        revision=snapshot.revision,
        generated_at=now,
        store_id=store_id,
        active_total=len(active),
        finished_total=len(finished),
    )
    budget = max_chars - _compact_size(empty.to_payload())

    def take(values, limit: int) -> list:
        nonlocal budget
        kept = []
        for value in values[:limit]:
            cost = _compact_size(value.to_payload()) + 1
            if cost > budget:
                break
            budget -= cost
            kept.append(value)
        return kept

    notes = take(list(attention[-MAX_BRAIN_WORK_ATTENTION:])[::-1], MAX_BRAIN_WORK_ATTENTION)[::-1]
    listed_active = take([BrainWorkEntry.from_item(item, now=now) for item in active[:MAX_BRAIN_WORK_ACTIVE]], MAX_BRAIN_WORK_ACTIVE)
    listed_finished = take([BrainWorkEntry.from_item(item, now=now) for item in finished[:MAX_BRAIN_WORK_FINISHED]], MAX_BRAIN_WORK_FINISHED)
    return BrainWorkContext(
        revision=snapshot.revision,
        generated_at=now,
        store_id=store_id,
        items=(*listed_active, *listed_finished),
        attention=tuple(notes),
        active_total=len(active),
        finished_total=len(finished),
    )


@dataclass(frozen=True, slots=True)
class BrainContext:
    """Ce que Core remet au backend pour un tour, en plus du tour lui-même.

    Agrégat plutôt que paramètres supplémentaires : un fait public de plus
    (identité du locuteur, par exemple) s'y ajoute sans toucher à la signature
    de `ContextAwareBrainBackend.run_turn_with_context`. `work` vaut `None`
    quand Core n'a pas pu lire son état de travail : le tour part quand même.
    """

    state: BrainWorkingState
    work: BrainWorkContext | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, BrainWorkingState):
            raise TypeError("state must be a BrainWorkingState")
        if self.work is not None and not isinstance(self.work, BrainWorkContext):
            raise TypeError("work must be a BrainWorkContext")

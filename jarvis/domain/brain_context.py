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
from typing import TYPE_CHECKING, Any

from jarvis.domain.v2 import BrainWorkingState
from jarvis.domain.work_state import WorkItem, WorkSnapshot, WorkStatus, clip_text

if TYPE_CHECKING:  # type only: the presentation import closures stay free of the Board contract
    from jarvis.domain.workspace_board import Board

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
#: Bloc `board` de chaque tour (handoff board-session, Slice 04b), en
#: caractères de JSON compact. Titre (≤ 120) et résumé (≤ 1 500) tiennent
#: toujours par contrat du Board et ne sont jamais tronqués ici ; les
#: références remplissent le reste.
MAX_BRAIN_BOARD_CONTEXT_CHARS = 2_048

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
    #: Board du travail (Slice 04b) ; `None` : non attribué, vu de tous les Boards.
    board_id: str | None = None

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
            board_id=item.board_id,
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
            **({"board_id": self.board_id} if self.board_id is not None else {}),
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


#: Texte d'une réponse coupée rendu au cerveau : assez pour qu'il s'y retrouve.
MAX_INTERRUPTED_TEXT_CHARS = 1200
#: Réponses coupées remises au cerveau en un tour.
MAX_BRAIN_INTERRUPTIONS = 4


def estimate_heard_text(text: str, played_ms: float, total_ms: float) -> str:
    """Début d'une réponse qui a été joué, estimé au prorata de l'audio.

    `total_ms` est l'audio reçu pour ce texte, `played_ms` ce qui en a été joué
    avant la coupure. Le fournisseur ne donne pas l'alignement mot à mot : la
    coupe est une estimation, reculée au mot entier précédent. Rien de joué,
    rien d'entendu.
    """

    text = text.strip()
    if played_ms <= 0 or not text or total_ms <= 0:
        return ""
    ratio = min(1.0, played_ms / total_ms)
    cut = int(len(text) * ratio)
    if cut >= len(text):
        return text
    space = text.rfind(" ", 0, cut + 1)
    if space > 0:
        cut = space
    return text[:cut].rstrip(" ,;:.!?…")


@dataclass(frozen=True, slots=True)
class BrainSpeechInterruption:
    """Une réponse du cerveau que l'utilisateur n'a pas entendue jusqu'au bout.

    Le cerveau garde dans sa propre session le texte entier qu'il a écrit ;
    sans ce constat, il tient pour dit ce que l'utilisateur a coupé, et prend
    un « oui » à la première phrase pour un « oui » à tout le reste.

    - `text` : la réponse écrite par le cerveau ;
    - `heard_text` : le début effectivement joué, estimé (vide si rien) ;
    - `played_ms` / `total_ms` : audio joué et audio reçu (`total_ms` vaut
      `None` quand la génération a elle-même été coupée : durée totale inconnue).
    """

    text: str
    heard_text: str
    played_ms: int
    total_ms: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("interrupted speech needs its text")
        if not isinstance(self.heard_text, str):
            raise TypeError("heard_text must be text")
        if type(self.played_ms) is not int or self.played_ms < 0:
            raise ValueError("played_ms must be a non-negative integer")
        if self.total_ms is not None and (type(self.total_ms) is not int or self.total_ms < 0):
            raise ValueError("total_ms must be a non-negative integer")

    def to_payload(self) -> dict[str, Any]:
        return {
            "text": clip_text(self.text, MAX_INTERRUPTED_TEXT_CHARS),
            "heard_text": clip_text(self.heard_text, MAX_INTERRUPTED_TEXT_CHARS),
            "played_ms": self.played_ms,
            "total_ms": self.total_ms,
        }


#: Réponses encore en attente de bouche remises au cerveau à un tour donné.
MAX_BRAIN_PENDING_REPLIES = 4


@dataclass(frozen=True, slots=True)
class BrainPendingReply:
    """Une formulation que le cerveau a rédigée et que la bouche n'a pas dite.

    C'est l'autre moitié de `BrainSpeechInterruption` : là, une phrase commencée
    n'a pas été entendue jusqu'au bout ; ici, une phrase n'a pas commencé.
    Décision du 28/09/2026 (Décision 48, amende la 47) : une formulation écrite
    pour une intention passée n'est plus prononçable d'elle-même ; la bouche la
    retient (`held_for_brain`) et Core la remet au cerveau, qui la redit —
    reformulée, par une nouvelle parole liée (`BrainEvent.revalidates`) — ou non.

    - `speech_id` : l'identité de présentation, toujours présente ; c'est elle
      que le cerveau nomme pour dire qu'il la redit, et elle que porte le verdict ;
    - `work_id` : le travail conclu, quand il existe (un relais spontané sans
      travail n'en a pas) ;
    - `correlation_id` : le tour qui l'a rédigée ;
    - `kind` : `result`, `error` ou `question` — une parole transitoire n'arrive
      jamais ici, elle se périme d'elle-même ;
    - `text` : ce qui aurait été dit, tel qu'il a été écrit.
    """

    speech_id: str
    correlation_id: str
    kind: str
    text: str
    work_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("speech_id", "correlation_id", "kind"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"pending reply needs its {name}")
        if self.work_id is not None and (not isinstance(self.work_id, str) or not self.work_id.strip()):
            raise ValueError("pending reply work_id must be a non-empty string when present")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("pending reply needs its text")

    def to_payload(self) -> dict[str, Any]:
        return {"speech_id": self.speech_id, "work_id": self.work_id, "correlation_id": self.correlation_id,
                "kind": self.kind, "text": clip_text(self.text, MAX_INTERRUPTED_TEXT_CHARS)}


@dataclass(frozen=True, slots=True)
class BrainBoardContext:
    """Le Board de la conversation du tour, borné (~2 Ko), remis au backend à chaque tour.

    Budget : la forme de fil **sérialisée** (JSON compact, échappements et
    `omitted_refs` compris) ne dépasse jamais `max_chars` (QA Slice 04b : un
    résumé de guillemets doublait sa taille une fois échappé, et la clé
    `omitted_refs` n'était pas comptée).

    Règles de troncature (`from_board`, documentées dans `docs/boards.md`) :

    - `title` et `context_summary` sont repris **entiers** : le contrat du
      Board les borne déjà (120 et 1 500 caractères, résumé refusé au-delà,
      jamais tronqué) — c'est l'éditeur qui condense. Seule exception : un
      résumé dont la forme **échappée** (guillemets, barres obliques inverses,
      retours à la ligne comptent double) ne tient pas seule dans le budget ;
      il est alors coupé dans ce bloc, `summary_clipped: true`, et aucune
      référence n'est remise. Le Board, lui, n'est jamais modifié ;
    - les références sont ajoutées **entières**, dans l'ordre tâches →
      artefacts → projets puis dans l'ordre du Board, tant que le bloc sérialisé
      reste sous `max_chars` ; la première qui ne tient pas arrête l'ajout, et
      toutes les suivantes sont comptées dans `omitted_refs` (jamais une
      référence coupée).
    """

    board_id: str
    title: str
    context_summary: str = ""
    task_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    project_refs: tuple[str, ...] = ()
    omitted_refs: int = 0
    summary_clipped: bool = False

    @classmethod
    def from_board(cls, board: Board, *, max_chars: int = MAX_BRAIN_BOARD_CONTEXT_CHARS) -> BrainBoardContext:
        kinds = ("task_refs", "artifact_refs", "project_refs")
        remaining = [(kind, ref) for kind in kinds for ref in getattr(board, kind)]
        total = len(remaining)

        def block(kept: dict[str, list[str]], omitted: int, summary: str, clipped: bool) -> BrainBoardContext:
            return cls(board_id=board.board_id, title=board.title, context_summary=summary,
                       **{name: tuple(kept.get(name, ())) for name in kinds},
                       omitted_refs=omitted, summary_clipped=clipped)

        summary, clipped = board.context_summary, False
        # Tête (titre + résumé), avec le compte de toutes les références comme
        # si aucune ne tenait : c'est le pire cas du bloc sans référence.
        if _compact_size(block({}, total, summary, False).to_payload()) > max_chars:
            summary, clipped = _clip_summary(lambda text: block({}, total, text, True), summary, max_chars), True
            return block({}, total, summary, clipped)
        kept: dict[str, list[str]] = {name: [] for name in kinds}
        for index, (kind, ref) in enumerate(remaining):
            kept[kind].append(ref)
            # Le bloc tel qu'il serait livré si l'ajout s'arrêtait après celle-ci.
            if _compact_size(block(kept, total - index - 1, summary, clipped).to_payload()) > max_chars:
                kept[kind].pop()
                return block(kept, total - index, summary, clipped)
        return block(kept, 0, summary, clipped)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "board_id": self.board_id,
            "title": self.title,
            "context_summary": self.context_summary,
            "task_refs": list(self.task_refs),
            "artifact_refs": list(self.artifact_refs),
            "project_refs": list(self.project_refs),
        }
        if self.omitted_refs:
            payload["omitted_refs"] = self.omitted_refs
        if self.summary_clipped:
            payload["summary_clipped"] = True
        return payload


def _clip_summary(build: Any, summary: str, max_chars: int) -> str:
    """Le plus long préfixe du résumé dont le bloc sérialisé (`build(préfixe)`) tient dans `max_chars`."""

    low, high = 0, len(summary)
    while low < high:
        middle = (low + high + 1) // 2
        if _compact_size(build(summary[:middle]).to_payload()) <= max_chars:
            low = middle
        else:
            high = middle - 1
    return summary[:low]


#: Bloc `session_context` de chaque tour (handoff session-context-recording,
#: Slice 03) : `summary.md` du Context actif, en **octets** UTF-8, et Contexts
#: dormants nommés (id + titre seulement). Même ordre de grandeur que le bloc
#: `board` (~2 Ko) : le brief reste court, l'agent lit le reste dans son dossier.
MAX_BRAIN_CONTEXT_SUMMARY_BYTES = 2_048
MAX_BRAIN_DORMANT_CONTEXTS = 8
_MAX_BRAIN_PATH_CHARS = 1_024


@dataclass(frozen=True, slots=True)
class BrainDormantContext:
    """Un Context dormant tel que le cerveau le voit : id et titre, jamais son contenu."""

    context_id: str
    title: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {"context_id": self.context_id, "title": self.title}


@dataclass(frozen=True, slots=True)
class BrainSessionContext:
    """Le Context actif de la Session du tour, borné, remis au backend à chaque tour (Slice 03).

    C'est la seule hydratation du cerveau depuis un Context : identité, dossier
    absolu (son seul espace de travail implicite), `summary.md` borné à
    `MAX_BRAIN_CONTEXT_SUMMARY_BYTES` octets (coupé sur un caractère entier,
    `summary_clipped`), et au plus `MAX_BRAIN_DORMANT_CONTEXTS` dormants par
    id et titre (le reste compté dans `omitted_dormant`). Jamais le contenu
    d'un dormant : les Contexts ne se mélangent pas (D03).

    `sessions_root` : dossier absolu `<data_root>/sessions`, ce que le Control
    Center accorde au CLI (`--add-dir`) ; constant pour la vie de Core, donc
    un changement de Context ou de Session ne relance aucun CLI.
    `workspace_error` : code stable quand le dossier n'a pas pu être créé ou
    est refusé (`context_workspace_failed` / `context_workspace_unsafe`) ; le
    tour part quand même et l'agent est prévenu de ne pas y écrire.
    """

    jarvis_session_id: str
    context_id: str
    workspace_path: str
    sessions_root: str
    title: str | None = None
    workspace_error: str | None = None
    summary: str = ""
    summary_clipped: bool = False
    dormant: tuple[BrainDormantContext, ...] = ()
    omitted_dormant: int = 0

    def __post_init__(self) -> None:
        for name in ("jarvis_session_id", "context_id", "workspace_path", "sessions_root"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > _MAX_BRAIN_PATH_CHARS:
                raise ValueError(f"{name} must be a non-empty bounded string")
        if len(self.summary.encode("utf-8")) > MAX_BRAIN_CONTEXT_SUMMARY_BYTES:
            raise ValueError("summary exceeds MAX_BRAIN_CONTEXT_SUMMARY_BYTES")
        if not isinstance(self.dormant, tuple) or len(self.dormant) > MAX_BRAIN_DORMANT_CONTEXTS:
            raise ValueError("dormant must be a bounded tuple")
        if not all(isinstance(item, BrainDormantContext) for item in self.dormant):
            raise TypeError("dormant must be BrainDormantContext")
        if self.omitted_dormant < 0:
            raise ValueError("omitted_dormant cannot be negative")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jarvis_session_id": self.jarvis_session_id,
            "context_id": self.context_id,
            "title": self.title,
            "workspace_path": self.workspace_path,
            "sessions_root": self.sessions_root,
            "summary": self.summary,
            "dormant": [item.to_payload() for item in self.dormant],
        }
        if self.summary_clipped:
            payload["summary_clipped"] = True
        if self.omitted_dormant:
            payload["omitted_dormant"] = self.omitted_dormant
        if self.workspace_error:
            payload["workspace_error"] = self.workspace_error
        return payload


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
    #: Réponses coupées depuis le tour précédent (voir `BrainSpeechInterruption`).
    interruptions: tuple[BrainSpeechInterruption, ...] = ()
    #: Formulations d'intentions passées, non dites, remises au cerveau (`BrainPendingReply`).
    pending_replies: tuple[BrainPendingReply, ...] = ()
    #: Le Board de la conversation du tour (Slice 04b) ; `None` hors Boards ou lecture en échec.
    board: BrainBoardContext | None = None
    #: Le Context actif de la Session du tour (Slice 03 session-context) ; `None` hors Session ou lecture en échec.
    session_context: BrainSessionContext | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, BrainWorkingState):
            raise TypeError("state must be a BrainWorkingState")
        if self.work is not None and not isinstance(self.work, BrainWorkContext):
            raise TypeError("work must be a BrainWorkContext")
        if not isinstance(self.interruptions, tuple) or len(self.interruptions) > MAX_BRAIN_INTERRUPTIONS:
            raise ValueError("interruptions must be a bounded tuple")
        if not all(isinstance(item, BrainSpeechInterruption) for item in self.interruptions):
            raise TypeError("interruptions must be BrainSpeechInterruption")
        if not isinstance(self.pending_replies, tuple) or len(self.pending_replies) > MAX_BRAIN_PENDING_REPLIES:
            raise ValueError("pending replies must be a bounded tuple")
        if not all(isinstance(item, BrainPendingReply) for item in self.pending_replies):
            raise TypeError("pending replies must be BrainPendingReply")

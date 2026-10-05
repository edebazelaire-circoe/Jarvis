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

from dataclasses import dataclass, replace
from datetime import datetime
import json
from typing import TYPE_CHECKING, Any, ClassVar

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
#: Mémoire du Board dans ce bloc (handoff board-memory-workspace-inspector,
#: Slice 03, R3), budget **séparé** des 2 048 caractères ci-dessus : manifeste
#: d'au plus 40 entrées, profondeur 2, noms et tailles, dont la liste sérialisée
#: tient en `MAX_BRAIN_BOARD_MANIFEST_CHARS` ; tête de `summary.md` en octets
#: UTF-8, coupée sur un caractère entier. Jamais le contenu d'un autre fichier.
MAX_BRAIN_BOARD_MANIFEST_ENTRIES = 40
MAX_BRAIN_BOARD_MANIFEST_DEPTH = 2
MAX_BRAIN_BOARD_MANIFEST_CHARS = 2_048
MAX_BRAIN_BOARD_SUMMARY_BYTES = 2_048
_MAX_BRAIN_BOARD_ENTRY_PATH_CHARS = 240
_MAX_BRAIN_BOARD_LOCATOR_CHARS = 160
_BOARD_MEMORY_ENTRY_KINDS = frozenset({"file", "directory", "link"})

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
class BrainBoardMemoryEntry:
    """Une entrée du manifeste : chemin relatif à `memory/`, nature, octets d'un fichier (jamais son contenu)."""

    path: str
    kind: str
    size: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path or len(self.path) > _MAX_BRAIN_BOARD_ENTRY_PATH_CHARS:
            raise ValueError("entry path must be a non-empty bounded string")
        if self.path.count("/") >= MAX_BRAIN_BOARD_MANIFEST_DEPTH:
            raise ValueError(f"entry path is deeper than {MAX_BRAIN_BOARD_MANIFEST_DEPTH}")
        if self.kind not in _BOARD_MEMORY_ENTRY_KINDS:
            raise ValueError(f"entry kind must be one of {sorted(_BOARD_MEMORY_ENTRY_KINDS)}")
        if self.size is not None and (type(self.size) is not int or self.size < 0):
            raise ValueError("entry size must be a non-negative integer or None")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"path": self.path, "kind": self.kind}
        if self.size is not None:
            payload["size"] = self.size
        return payload


@dataclass(frozen=True, slots=True)
class BrainBoardMemory:
    """La mémoire du Board du tour, bornée (Slice 03, R3) : où elle est, ce qu'elle contient, son condensé.

    - `locator` : `boards/<board_id>/memory`, **relatif** à la racine de
      données (forme canonique des API) ; `path` : le même dossier en absolu,
      ce que le cerveau ouvre avec ses outils de fichiers (`--add-dir
      <data_root>/boards`) ;
    - `entries` : au plus `MAX_BRAIN_BOARD_MANIFEST_ENTRIES`, profondeur
      `MAX_BRAIN_BOARD_MANIFEST_DEPTH`, liste sérialisée ≤
      `MAX_BRAIN_BOARD_MANIFEST_CHARS` ; `truncated` : il en existe d'autres ;
    - `summary` : tête de `summary.md` (casse ignorée) ≤
      `MAX_BRAIN_BOARD_SUMMARY_BYTES` octets, `summary_clipped` s'il continue ;
    - `error` : code stable quand la mémoire n'a pas pu être lue (rien d'autre
      n'est alors joint) ; `summary_error` : seul `summary.md` est illisible.
    """

    locator: str
    path: str
    entries: tuple[BrainBoardMemoryEntry, ...] = ()
    truncated: bool = False
    summary: str = ""
    summary_clipped: bool = False
    error: str | None = None
    summary_error: str | None = None

    def __post_init__(self) -> None:
        if not is_board_memory_locator(self.locator):
            raise ValueError("locator must be boards/<board_id>/memory")
        if not isinstance(self.path, str) or not self.path or len(self.path) > _MAX_BRAIN_PATH_CHARS:
            raise ValueError("path must be a non-empty bounded string")
        if not isinstance(self.entries, tuple) or len(self.entries) > MAX_BRAIN_BOARD_MANIFEST_ENTRIES:
            raise ValueError("entries must be a bounded tuple")
        if not all(isinstance(item, BrainBoardMemoryEntry) for item in self.entries):
            raise TypeError("entries must be BrainBoardMemoryEntry")
        if _manifest_size(self.entries) > MAX_BRAIN_BOARD_MANIFEST_CHARS:
            raise ValueError("entries exceed MAX_BRAIN_BOARD_MANIFEST_CHARS")
        if not isinstance(self.summary, str) or len(self.summary.encode("utf-8")) > MAX_BRAIN_BOARD_SUMMARY_BYTES:
            raise ValueError("summary exceeds MAX_BRAIN_BOARD_SUMMARY_BYTES")
        for name in ("error", "summary_error"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value or len(value) > 64):
                raise ValueError(f"{name} must be a short code")
        if self.error is not None and (self.entries or self.summary):
            raise ValueError("an unreadable memory carries no entries and no summary")

    @classmethod
    def bounded(cls, *, locator: str, path: str, entries: tuple[BrainBoardMemoryEntry, ...], more: bool,
                summary: str = "", summary_clipped: bool = False,
                summary_error: str | None = None) -> BrainBoardMemory:
        """Le bloc d'une mémoire lue : les entrées dans l'ordre, tant que le manifeste tient ; le reste → `truncated`."""

        kept: list[BrainBoardMemoryEntry] = []
        truncated = more
        for entry in entries:
            if (len(kept) >= MAX_BRAIN_BOARD_MANIFEST_ENTRIES
                    or _manifest_size((*kept, entry)) > MAX_BRAIN_BOARD_MANIFEST_CHARS):
                truncated = True
                break
            kept.append(entry)
        return cls(locator=locator, path=path, entries=tuple(kept), truncated=truncated,
                   summary=clip_utf8(summary, MAX_BRAIN_BOARD_SUMMARY_BYTES), summary_clipped=summary_clipped
                   or len(summary.encode("utf-8")) > MAX_BRAIN_BOARD_SUMMARY_BYTES, summary_error=summary_error)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"locator": self.locator, "path": self.path,
                                   "entries": [entry.to_payload() for entry in self.entries]}
        if self.truncated:
            payload["truncated"] = True
        if self.summary:
            payload["summary"] = self.summary
        if self.summary_clipped:
            payload["summary_clipped"] = True
        if self.error:
            payload["error"] = self.error
        if self.summary_error:
            payload["summary_error"] = self.summary_error
        return payload


def is_board_memory_locator(value: object, board_id: str | None = None) -> bool:
    """`boards/<board_id>/memory` (du Board donné, s'il l'est), borné ; sans E/S."""

    if not isinstance(value, str) or len(value) > _MAX_BRAIN_BOARD_LOCATOR_CHARS:
        return False
    parts = value.split("/")
    return (len(parts) == 3 and parts[0] == "boards" and parts[2] == "memory" and bool(parts[1])
            and parts[1] not in {".", ".."} and "\\" not in parts[1]
            and (board_id is None or parts[1] == board_id))


def _manifest_size(entries: tuple[BrainBoardMemoryEntry, ...] | list[BrainBoardMemoryEntry]) -> int:
    return len(json.dumps([entry.to_payload() for entry in entries], ensure_ascii=False, separators=(",", ":")))


def clip_utf8(text: str, max_bytes: int) -> str:
    """Le plus long préfixe de `text` qui tient en `max_bytes` octets UTF-8 (jamais un caractère coupé)."""

    data = text.encode("utf-8")
    return text if len(data) <= max_bytes else data[:max_bytes].decode("utf-8", errors="ignore")


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

    `board_kind` (R1) est compté dans ce budget. `memory` (Slice 03, R3,
    `BrainBoardMemory`) a **son propre** budget et n'est pas compté dans
    `max_chars` : `None` quand Core n'a pas de magasin de mémoire.
    """

    board_id: str
    title: str
    context_summary: str = ""
    task_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    project_refs: tuple[str, ...] = ()
    omitted_refs: int = 0
    summary_clipped: bool = False
    #: Nature du Board (R1, `BoardKind.value`) : `empty`, `meeting` ou `presentation`.
    board_kind: str = "empty"
    memory: BrainBoardMemory | None = None

    @classmethod
    def from_board(cls, board: Board, *, max_chars: int = MAX_BRAIN_BOARD_CONTEXT_CHARS,
                   memory: BrainBoardMemory | None = None) -> BrainBoardContext:
        kinds = ("task_refs", "artifact_refs", "project_refs")
        remaining = [(kind, ref) for kind in kinds for ref in getattr(board, kind)]
        total = len(remaining)
        board_kind = board.board_kind.value

        def block(kept: dict[str, list[str]], omitted: int, summary: str, clipped: bool) -> BrainBoardContext:
            # Sans `memory` : son budget est le sien, ajouté après (`replace`).
            return cls(board_id=board.board_id, title=board.title, context_summary=summary,
                       **{name: tuple(kept.get(name, ())) for name in kinds},
                       omitted_refs=omitted, summary_clipped=clipped, board_kind=board_kind)

        summary, clipped = board.context_summary, False
        # Tête (titre + résumé), avec le compte de toutes les références comme
        # si aucune ne tenait : c'est le pire cas du bloc sans référence.
        if _compact_size(block({}, total, summary, False).to_payload()) > max_chars:
            summary, clipped = _clip_summary(lambda text: block({}, total, text, True), summary, max_chars), True
            return replace(block({}, total, summary, clipped), memory=memory)
        kept: dict[str, list[str]] = {name: [] for name in kinds}
        for index, (kind, ref) in enumerate(remaining):
            kept[kind].append(ref)
            # Le bloc tel qu'il serait livré si l'ajout s'arrêtait après celle-ci.
            if _compact_size(block(kept, total - index - 1, summary, clipped).to_payload()) > max_chars:
                kept[kind].pop()
                return replace(block(kept, total - index, summary, clipped), memory=memory)
        return replace(block(kept, 0, summary, clipped), memory=memory)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "board_id": self.board_id,
            "title": self.title,
            "board_kind": self.board_kind,
            "context_summary": self.context_summary,
            "task_refs": list(self.task_refs),
            "artifact_refs": list(self.artifact_refs),
            "project_refs": list(self.project_refs),
        }
        if self.omitted_refs:
            payload["omitted_refs"] = self.omitted_refs
        if self.summary_clipped:
            payload["summary_clipped"] = True
        if self.memory is not None:
            payload["memory"] = self.memory.to_payload()
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
#: Rattrapage rapide d'un cerveau neuf ou repris (Slice 08) : dernières lignes
#: d'activité du Context actif (natures, ids, heures ; jamais de texte),
#: queue de la transcription ambiante en cours, références d'Artifacts.
MAX_BRAIN_CATCHUP_ACTIVITY = 12
MAX_BRAIN_CATCHUP_LINE_CHARS = 160
MAX_BRAIN_TRANSCRIPT_TAIL_CHARS = 1_500
MAX_BRAIN_ARTIFACT_REFS = 8


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
    absolu (espace de travail implicite de la conversation), `summary.md` borné à
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
    #: Rattrapage (Slice 08) : lignes compactes d'activité récente du Context actif, plus ancienne d'abord.
    activity: tuple[str, ...] = ()
    #: Dernier `seq` du ledger vu à l'assemblage (curseur pour une lecture plus profonde, Slice 09).
    latest_seq: int | None = None
    #: Queue de la transcription **ambiante** (salle, non adressée, D17) et son Artifact `transcript`.
    transcript_tail: str = ""
    transcript_ref: str | None = None
    #: Artifacts récents du Context actif, `nature id état` (pointeurs, jamais leur contenu).
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for items, limit, name in ((self.activity, MAX_BRAIN_CATCHUP_ACTIVITY, "activity"),
                                   (self.artifact_refs, MAX_BRAIN_ARTIFACT_REFS, "artifact_refs")):
            if (not isinstance(items, tuple) or len(items) > limit
                    or not all(isinstance(i, str) and len(i) <= MAX_BRAIN_CATCHUP_LINE_CHARS for i in items)):
                raise ValueError(f"{name} must be a bounded tuple of short strings")
        if len(self.transcript_tail) > MAX_BRAIN_TRANSCRIPT_TAIL_CHARS:
            raise ValueError("transcript_tail exceeds MAX_BRAIN_TRANSCRIPT_TAIL_CHARS")
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
        if self.activity:
            payload["activity"] = list(self.activity)
        if self.latest_seq is not None:
            payload["latest_seq"] = self.latest_seq
        if self.transcript_tail:
            payload["transcript_tail"] = self.transcript_tail
            payload["transcript_ref"] = self.transcript_ref
        if self.artifact_refs:
            payload["artifact_refs"] = list(self.artifact_refs)
        return payload


#: Bloc `presentation` d'un tour adressé en PRESENTATION (handoff
#: presentation-interaction-mode, Slice 05, P4), en caractères de JSON compact.
#: **Même valeur** que `MAX_ADDRESSED_CONTEXT_CHARS`
#: (`jarvis/domain/presentation_addressed_turn.py`), le budget auquel la
#: projection est déjà taillée. Épinglée par un test plutôt qu'importée : ce
#: module est dans la fermeture d'import du service spéculatif, et la
#: projection adressée n'a rien à y faire.
MAX_BRAIN_PRESENTATION_CONTEXT_CHARS = 6_000
#: Bornes de forme, reprises des plafonds du magasin de séance : le fil en
#: retient seize, une énonciation fait au plus 600 caractères, et aucune
#: section de la projection n'a plus d'entrées que le fil.
_MAX_PRESENTATION_ITEMS = 16
_MAX_PRESENTATION_SPEECH_CHARS = 600
_MAX_PRESENTATION_ID_CHARS = 128
#: Les clés que `AddressedTurnContext.to_brain_context()` produit, et rien
#: d'autre : une clé inconnue vient d'une projection d'une autre version, et
#: elle est refusée plutôt que remise à un modèle sans que personne ne sache
#: ce qu'elle dit.
_PRESENTATION_KEYS = frozenset({
    "session_id", "revision", "situation", "evidence", "disposition", "authorizes_actions",
    "deictic", "referent", "prepared_resource", "action", "recent_speech", "prepared_resources",
    "topics", "claims", "entities", "sources", "open_questions", "attention", "clipped",
})
_PRESENTATION_LISTS = frozenset({
    "recent_speech", "prepared_resources", "topics", "claims", "entities", "sources",
    "open_questions", "attention",
})
_PRESENTATION_OBJECTS = frozenset({"referent", "prepared_resource"})
_JSON_SCALARS = (str, int, float, bool, type(None))


@dataclass(frozen=True, slots=True, repr=False)
class BrainPresentationContext:
    """Le contexte de séance d'un tour adressé en PRESENTATION, tel que Core le transporte (P4).

    Construit **dans Voice** depuis `AddressedTurnContext.to_brain_context()` —
    le fil frais et l'ensemble de travail borné —, posé sur le tour par
    `POST .../brain-turns`, remis au backend dans `BrainContext.presentation`.
    Core ne le fabrique pas et ne le garde pas : il n'est ni persisté avec le
    tour, ni écrit dans un journal, ni réappliqué par un doublon.

    **Porte de la parole de la salle.** C'est tout son objet (D06), et c'est
    pourquoi sa forme est fermée : clés connues, listes bornées, objets plats,
    taille totale sous `MAX_BRAIN_PRESENTATION_CONTEXT_CHARS`. Hors forme, la
    construction lève `ValueError` : le serveur le rend en 400, et Voice
    l'écarte **avant** l'envoi pour que le tour, lui, parte quand même.

    Normalisé par `from_payload` : `recent_speech` va de la plus fraîche à la
    plus ancienne (`sequence` décroissante), quel que soit l'ordre reçu. C'est
    l'ordre dans lequel un déictique se résout, et le brief le rend tel quel.

    `authorizes_actions` est figé à faux, comme la projection dont il sort : du
    contexte, jamais un ordre (D03). `repr` ne montre que la taille : la parole
    ne doit pas pouvoir tomber dans une trace par un `repr()` de passage.
    """

    wire: str

    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if not isinstance(self.wire, str):
            raise TypeError("presentation context wire form must be a string")
        if len(self.wire) > MAX_BRAIN_PRESENTATION_CONTEXT_CHARS:
            raise ValueError("presentation context exceeds MAX_BRAIN_PRESENTATION_CONTEXT_CHARS")
        try:
            payload = json.loads(self.wire)
        except ValueError as exc:
            raise ValueError("presentation context wire form is not JSON") from exc
        _validate_presentation(payload)

    def __repr__(self) -> str:
        return f"BrainPresentationContext(chars={len(self.wire)})"

    @classmethod
    def from_payload(cls, value: object) -> BrainPresentationContext:
        """Valider et normaliser une projection. Lève `ValueError` hors contrat."""

        payload = _validate_presentation(value)
        normalized = {**payload, "recent_speech": sorted(
            payload["recent_speech"], key=lambda item: item["sequence"], reverse=True,
        )}
        return cls(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")))

    @property
    def chars(self) -> int:
        return len(self.wire)

    def to_payload(self) -> dict[str, Any]:
        """Une copie neuve à chaque appel : l'instance reste immuable."""

        return json.loads(self.wire)


def _presentation_text(name: str, value: object, limit: int) -> None:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"presentation context {name} must be a non-empty bounded string")


def _presentation_object(name: str, value: object) -> None:
    """Un objet plat : des clés texte, des valeurs scalaires JSON. Rien d'imbriqué."""

    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, _JSON_SCALARS) for key, item in value.items()
    ):
        raise ValueError(f"presentation context {name} must hold flat JSON objects")


def _validate_presentation(value: object) -> dict[str, Any]:
    """La forme fermée de `BrainPresentationContext`. Rend la valeur, ou lève `ValueError`."""

    if not isinstance(value, dict):
        raise ValueError("presentation context must be a JSON object")
    unknown = set(value) - _PRESENTATION_KEYS
    if unknown:
        raise ValueError(f"presentation context has unknown keys: {sorted(map(str, unknown))[:4]}")
    if value.get("authorizes_actions", False) is not False:
        raise ValueError("presentation context never authorizes actions")
    if not isinstance(value.get("recent_speech"), list):
        raise ValueError("presentation context requires recent_speech")
    for name in _PRESENTATION_LISTS:
        items = value.get(name, [])
        if not isinstance(items, list) or len(items) > _MAX_PRESENTATION_ITEMS:
            raise ValueError(f"presentation context {name} must be a bounded list")
        for item in items:
            _presentation_object(name, item)
    for name in _PRESENTATION_OBJECTS:
        if value.get(name) is not None:
            _presentation_object(name, value[name])
    clipped = value.get("clipped", [])
    if (not isinstance(clipped, list) or len(clipped) > _MAX_PRESENTATION_ITEMS
            or not all(isinstance(item, str) for item in clipped)):
        raise ValueError("presentation context clipped must be a bounded list of strings")
    for name in _PRESENTATION_KEYS - _PRESENTATION_LISTS - _PRESENTATION_OBJECTS - {"clipped"}:
        if not isinstance(value.get(name), _JSON_SCALARS):
            raise ValueError(f"presentation context {name} must be a JSON scalar")
    for item in value["recent_speech"]:
        _presentation_text("recent_speech.utterance_id", item.get("utterance_id"), _MAX_PRESENTATION_ID_CHARS)
        _presentation_text("recent_speech.text", item.get("text"), _MAX_PRESENTATION_SPEECH_CHARS)
        sequence = item.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("presentation context recent_speech.sequence must be a nonnegative integer")
    for item in value.get("prepared_resources", []):
        _presentation_text("prepared_resources.resource_id", item.get("resource_id"), _MAX_PRESENTATION_ID_CHARS)
        if "object_id" in item:
            _presentation_text("prepared_resources.object_id", item["object_id"], _MAX_PRESENTATION_ID_CHARS)
    if _compact_size(value) > MAX_BRAIN_PRESENTATION_CONTEXT_CHARS:
        raise ValueError("presentation context exceeds MAX_BRAIN_PRESENTATION_CONTEXT_CHARS")
    return value


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
    #: Le contexte de séance d'un tour adressé en PRESENTATION (Slice 05, P4) ; `None` hors séance,
    #: sur la voie directe, et pour tout tour qui n'en portait pas.
    presentation: BrainPresentationContext | None = None

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
        if self.presentation is not None and not isinstance(self.presentation, BrainPresentationContext):
            raise TypeError("presentation must be a BrainPresentationContext")

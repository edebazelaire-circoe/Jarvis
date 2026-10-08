"""Presentation Studio : l'anneau d'annulation borné (handoff jarvis-interactive-presentation-studio, Slice 08).

Module **pur** (aucune E/S, pas d'`await`). L'état courant d'une variante est toujours déjà sur disque (chaque commit de
la Slice 05 est durable à l'acquittement) : il n'y a donc **aucun second chemin de persistance** ici. Ce module ne tient
que la mémoire courte de l'annulation : des enregistrements d'annulation de la Slice 05 (opérations inverses), rangés
par variante, avec des bornes **dures** et une éviction **visible**.

## Bornes (toutes dures, testées)

| Borne | Valeur | Dépassement |
| --- | ---: | --- |
| entrées par variante (annuler + rétablir) | 32 | la plus ancienne cède (`variant_bound`), comptée |
| octets d'une entrée | 64 Kio (`MAX_UNDO_BYTES`) | l'entrée n'est pas gardée : voir « Trou » |
| octets par variante | 256 Kio | la plus ancienne cède (`variant_bound`) |
| octets au total | 1 Mio | l'anneau le moins récemment utilisé est abandonné (`memory_bound`) |
| variantes suivies | 8 | l'anneau le moins récemment utilisé est abandonné (`tracked_variants_bound`) |

**Trou.** Une entrée trop grosse ne peut pas être gardée, et garder les plus anciennes sauterait une étape : annuler
la précédente rejouerait des inverses sur un état qui n'est plus le leur. Un commit non annulable abandonne donc
l'anneau de la variante (`entry_too_large`) ; un annuler/rétablir dont l'inverse est trop gros vide la pile opposée.

## Cohérence

Chaque anneau retient l'empreinte (`scenes_digest`) des scènes **telles que l'anneau les attend**. Un commit, un
annuler ou un rétablir la met à jour ; une écriture hors anneau (un `PUT` de variante qui change les scènes) la rend
fausse, et l'anneau est abandonné (`document_moved_on`) au prochain usage au lieu de rejouer des inverses sur un
autre état. Un changement qui laisse les scènes identiques (le titre de la variante) ne casse rien.

Rien ici n'est durable : un redémarrage vide tout (`history_unavailable`, raison `not_recorded_since_start`).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import re
import secrets
from typing import Any

from jarvis.domain.prefab import canonical_json
from jarvis.domain.presentation_studio_checks import PresentationStudioErrorCode as C, _exact_keys, _fail
from jarvis.domain.presentation_studio_edit import MAX_UNDO_BYTES, StudioActor

MAX_ENTRIES_PER_VARIANT = 32
MAX_ENTRY_BYTES = MAX_UNDO_BYTES
MAX_VARIANT_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
MAX_TRACKED_VARIANTS = 8
#: Raisons d'abandon retenues pour répondre « pourquoi plus d'historique ? » (bornée : la plus ancienne cède).
MAX_REMEMBERED_DROPS = 32
#: Entrées détaillées dans un état d'historique (les plus récentes d'abord) ; les comptes disent le reste.
MAX_LISTED_ENTRIES = 8
#: Un corps d'annuler/rétablir tient dans quelques dizaines d'octets.
MAX_HISTORY_BODY_BYTES = 4 * 1024

ENTRY_ID = re.compile(r"psh_[0-9a-f]{12}\Z")

Key = tuple[str, str]  # (presentation_id, variant_id)
Pin = tuple[str, int]  # (prefab_id, version)


class HistoryDirection(StrEnum):
    UNDO = "undo"
    REDO = "redo"

    @property
    def opposite(self) -> HistoryDirection:
        return HistoryDirection.REDO if self is HistoryDirection.UNDO else HistoryDirection.UNDO


class HistoryStatus(StrEnum):
    APPLIED = "applied"
    #: Aucun historique pour cette variante (redémarrage, anneau abandonné ou évincé) : `reason` dit pourquoi.
    UNAVAILABLE = "history_unavailable"
    NOTHING_TO_UNDO = "nothing_to_undo"
    NOTHING_TO_REDO = "nothing_to_redo"
    #: Le document a bougé (autre écriture, autre entrée en tête que celle que l'appelant a vue) : rien n'est écrit.
    STALE = "stale"
    #: L'édition inverse est refusée par les validations d'édition (déterministe) : l'anneau est abandonné.
    REFUSED = "refused"


class DropReason(StrEnum):
    NOT_RECORDED = "not_recorded_since_start"
    DOCUMENT_MOVED_ON = "document_moved_on"
    ENTRY_TOO_LARGE = "entry_too_large"
    ENTRY_NOT_APPLICABLE = "entry_not_applicable"
    VARIANT_BOUND = "variant_bound"
    MEMORY_BOUND = "memory_bound"
    TRACKED_VARIANTS_BOUND = "tracked_variants_bound"
    VARIANT_ARCHIVED = "variant_archived"
    PRESENTATION_REMOVED = "presentation_removed"
    RECORD_FAILED = "record_failed"
    REDO_CLEARED = "redo_cleared"


#: Phrase de l'utilisateur pour chaque raison (jamais un contenu de scène).
REASON_TEXT: Mapping[DropReason, str] = {
    DropReason.NOT_RECORDED: "history is kept in memory only: nothing was recorded for this variant since Core started",
    DropReason.DOCUMENT_MOVED_ON: "the variant was changed outside the edit history: older steps no longer match it",
    DropReason.ENTRY_TOO_LARGE: "an edit was too large to keep for undo (limit {entry_kib} KiB): the steps it would skip were dropped",
    DropReason.ENTRY_NOT_APPLICABLE: "an undo step no longer applies to the variant: history was dropped",
    DropReason.VARIANT_BOUND: "the oldest steps were dropped to stay within the history bound",
    DropReason.MEMORY_BOUND: "this variant's history was dropped to stay within the total history memory bound",
    DropReason.TRACKED_VARIANTS_BOUND: "this variant's history was dropped: only {variants} variants keep a history",
    DropReason.REDO_CLEARED: "a new edit ended the redo branch",
    DropReason.VARIANT_ARCHIVED: "the variant was archived: its history was dropped",
    DropReason.PRESENTATION_REMOVED: "the presentation was removed: its history was dropped",
    DropReason.RECORD_FAILED: "the history could not record the last edit: it was dropped rather than left inconsistent",
}


def reason_text(reason: DropReason | str) -> str:
    try:
        return REASON_TEXT[DropReason(reason)].format(entry_kib=MAX_ENTRY_BYTES // 1024, variants=MAX_TRACKED_VARIANTS)
    except ValueError:
        return str(reason)


# ------------------------------------------------------------------ outils

def scenes_digest(scenes: Sequence[Any]) -> str:
    """Empreinte de la forme stockée des scènes (canonique : l'ordre des clés d'un objet n'y compte pas, celui des scènes si)."""

    return hashlib.sha256(canonical_json([scene.to_dict() for scene in scenes]).encode("utf-8")).hexdigest()


def ops_size(ops: Sequence[Mapping[str, Any]]) -> int:
    return len(json.dumps(list(ops), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def pins_of(ops: Sequence[Mapping[str, Any]]) -> frozenset[Pin]:
    """Les `(prefab_id, version)` que rejouer ces opérations écrirait dans le document : ceux des `scene.add` (l'inverse d'un
    retrait emporte la scène entière). Les autres inverses ne portent aucun pin : ils s'appliquent à une scène déjà épinglée."""

    found: set[Pin] = set()
    for op in ops:
        if op.get("op") != "scene.add":
            continue
        scene = op.get("scene")
        prefab = scene.get("prefab") if isinstance(scene, Mapping) else None
        if isinstance(prefab, Mapping) and isinstance(prefab.get("id"), str) and isinstance(prefab.get("version"), int):
            found.add((prefab["id"], prefab["version"]))
    return frozenset(found)


def new_entry_id() -> str:
    return "psh_" + secrets.token_hex(6)


@dataclass(frozen=True, slots=True)
class HistoryRequest:
    actor: StudioActor
    #: Si l'appelant l'a vue : l'entrée qu'il croit en tête. Une autre en tête -> `stale`, jamais une autre annulation.
    expected_entry_id: str | None = None


def parse_history_request(raw: object) -> HistoryRequest:
    data = _exact_keys(raw, "history", {"actor"}, frozenset({"expected_entry_id"}))
    try:
        actor = StudioActor(data["actor"])
    except ValueError:
        raise _fail("actor must be 'user' or 'brain'") from None
    expected = data.get("expected_entry_id")
    if expected is not None and not (isinstance(expected, str) and ENTRY_ID.fullmatch(expected)):
        raise _fail("expected_entry_id is not a valid id (psh_...)")
    return HistoryRequest(actor, expected)


@dataclass(frozen=True, slots=True)
class HistoryStep:
    """Ce qu'un annuler/rétablir dit au service d'édition : « ce commit défait/refait l'entrée `entry_id` »."""

    direction: HistoryDirection
    entry_id: str


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    entry_id: str
    #: Opérations inverses, dans l'ordre où il faut les appliquer (celles du `undo_record` de la Slice 05).
    ops: tuple[Mapping[str, Any], ...]
    #: Noms des opérations d'**origine** (jamais une valeur ni un titre) : de quoi afficher « annuler : scene.rename ».
    op_names: tuple[str, ...]
    tier: str
    actor: str
    #: Révision de la variante juste après l'édition que cette entrée défait.
    revision: int
    size: int
    pins: frozenset[Pin] = frozenset()

    def summary(self) -> dict[str, Any]:
        return {"entry_id": self.entry_id, "ops": list(self.op_names), "tier": self.tier, "actor": self.actor,
                "revision": self.revision, "bytes": self.size}


@dataclass(slots=True)
class Ring:
    #: Le plus ancien d'abord ; le dernier est ce que « annuler » défait.
    undo: list[HistoryEntry] = field(default_factory=list)
    #: Le plus profond d'abord ; le dernier est ce que « rétablir » refait.
    redo: list[HistoryEntry] = field(default_factory=list)
    #: Empreinte des scènes que l'anneau attend (`None` : pas encore connue).
    expected_digest: str | None = None
    evicted: int = 0
    redo_cleared: int = 0

    @property
    def size(self) -> int:
        return sum(e.size for e in self.undo) + sum(e.size for e in self.redo)

    @property
    def count(self) -> int:
        return len(self.undo) + len(self.redo)

    def stack(self, direction: HistoryDirection) -> list[HistoryEntry]:
        return self.undo if direction is HistoryDirection.UNDO else self.redo


@dataclass(frozen=True, slots=True)
class Drop:
    """Ce que l'anneau a perdu, pour que l'appelant le journalise : jamais une éviction muette."""

    key: Key
    reason: DropReason
    #: `entries` (quelques entrées), `redo` (la pile rétablir, vidée), `ring` (l'anneau entier).
    kind: str
    entries: int
    bytes: int


class UndoBook:
    """Tous les anneaux, bornés. Synchrone et sans verrou : l'appelant est la boucle d'évènements (aucun `await` ici)."""

    def __init__(self, *, new_id: Callable[[], str] = new_entry_id) -> None:
        self._rings: OrderedDict[Key, Ring] = OrderedDict()
        self._notes: OrderedDict[Key, DropReason] = OrderedDict()
        self._reserved: dict[int, tuple[Key | None, frozenset[Pin]]] = {}
        self._counter = 0
        self._new_id = new_id
        self.evicted_entries = 0
        self.dropped_rings = 0

    # ------------------------------------------------------------ lecture

    def ring(self, key: Key) -> Ring | None:
        return self._rings.get(key)

    def why_unavailable(self, key: Key) -> DropReason:
        return self._notes.get(key, DropReason.NOT_RECORDED)

    @property
    def total_bytes(self) -> int:
        return sum(ring.size for ring in self._rings.values())

    def pins(self) -> frozenset[Pin]:
        """Tout `(prefab_id, version)` que rejouer une entrée garde ou écrirait, **plus** les réservations en cours."""

        held: set[Pin] = set()
        for ring in self._rings.values():
            for entry in (*ring.undo, *ring.redo):
                held |= entry.pins
        for _, pins in self._reserved.values():
            held |= pins
        return frozenset(held)

    def stats(self) -> dict[str, Any]:
        return {"tracked_variants": len(self._rings), "total_bytes": self.total_bytes,
                "evicted_entries": self.evicted_entries, "dropped_rings": self.dropped_rings,
                "limits": limits()}

    def describe(self, key: Key) -> dict[str, Any]:
        ring = self._rings.get(key)
        if ring is None:
            reason = self.why_unavailable(key)
            return {"tracked": False, "reason": reason.value, "message": reason_text(reason),
                    "undo_count": 0, "redo_count": 0, "undo": [], "redo": [], "next_undo": None, "next_redo": None,
                    "bytes": 0, "evicted": 0, "redo_cleared": 0}
        return {"tracked": True, "reason": None, "message": None, "undo_count": len(ring.undo),
                "redo_count": len(ring.redo),
                "undo": [e.summary() for e in reversed(ring.undo[-MAX_LISTED_ENTRIES:])],
                "redo": [e.summary() for e in reversed(ring.redo[-MAX_LISTED_ENTRIES:])],
                "next_undo": ring.undo[-1].summary() if ring.undo else None,
                "next_redo": ring.redo[-1].summary() if ring.redo else None,
                "bytes": ring.size, "evicted": ring.evicted, "redo_cleared": ring.redo_cleared}

    # ------------------------------------------------------------ réservation (avant d'écrire un pin dans un document)

    def reserve(self, pins: frozenset[Pin], key: Key | None = None) -> int:
        self._counter += 1
        self._reserved[self._counter] = (key, pins)
        return self._counter

    def in_flight(self, key: Key) -> bool:
        """Un commit de cette variante a réservé son entrée et n'a pas encore fini (entre `begin` et `commit`/`abort`) :
        le fichier peut déjà avoir changé alors que l'anneau n'a pas encore enregistré cette édition."""

        return any(reserved_key == key for reserved_key, _ in self._reserved.values())

    def release(self, token: int) -> None:
        self._reserved.pop(token, None)

    # ------------------------------------------------------------ écriture de l'anneau

    def make_entry(self, ops: Sequence[Mapping[str, Any]], *, op_names: Sequence[str], tier: str, actor: str,
                   revision: int) -> HistoryEntry | None:
        """L'entrée, ou `None` si elle dépasse la borne d'une entrée (elle n'est pas gardée)."""

        size = ops_size(ops)
        if size > MAX_ENTRY_BYTES:
            return None
        return HistoryEntry(self._new_id(), tuple(ops), tuple(op_names), tier, actor, revision, size, pins_of(ops))

    def record_edit(self, key: Key, entry: HistoryEntry | None, *, before_digest: str, after_digest: str) -> list[Drop]:
        """Un commit hors annuler/rétablir. `entry` `None` : inverse trop gros, l'anneau est abandonné (« Trou »)."""

        drops: list[Drop] = []
        ring = self._rings.get(key)
        if ring is not None and ring.expected_digest is not None and ring.expected_digest != before_digest:
            drops.append(self._drop(key, DropReason.DOCUMENT_MOVED_ON))
            ring = None
        if entry is None:
            if ring is not None:
                drops.append(self._drop(key, DropReason.ENTRY_TOO_LARGE))
            else:
                self._remember(key, DropReason.ENTRY_TOO_LARGE)
            return drops
        if ring is None:
            drops.extend(self._make_room_for_a_ring())
            ring = self._rings[key] = Ring()
            self._notes.pop(key, None)
        if ring.redo:  # a new edit ends the redo branch (semantic, not an eviction)
            ring.redo_cleared += len(ring.redo)
            drops.append(Drop(key, DropReason.REDO_CLEARED, "redo", len(ring.redo), sum(e.size for e in ring.redo)))
            ring.redo.clear()
        ring.undo.append(entry)
        ring.expected_digest = after_digest
        self._rings.move_to_end(key)
        drops.extend(self._enforce(key))
        return drops

    def record_step(self, key: Key, direction: HistoryDirection, entry_id: str, new_entry: HistoryEntry | None, *,
                    after_digest: str) -> list[Drop]:
        """Un annuler/rétablir réussi : l'entrée `entry_id` (en tête de sa pile) passe, inversée, sur la pile opposée."""

        ring = self._rings.get(key)
        source = ring.stack(direction) if ring is not None else []
        if ring is None or not source or source[-1].entry_id != entry_id:
            raise LookupError(f"{entry_id} is not the next {direction.value} step of {key[1]}")
        source.pop()
        drops: list[Drop] = []
        opposite = ring.stack(direction.opposite)
        if new_entry is None:  # inverse too big: the opposite stack would skip a step, so it goes
            if opposite:
                ring.evicted += len(opposite)
                self.evicted_entries += len(opposite)
                drops.append(Drop(key, DropReason.ENTRY_TOO_LARGE, "entries", len(opposite), sum(e.size for e in opposite)))
                opposite.clear()
            else:
                self._remember(key, DropReason.ENTRY_TOO_LARGE)
        else:
            opposite.append(new_entry)
        ring.expected_digest = after_digest
        self._rings.move_to_end(key)
        drops.extend(self._enforce(key))
        return drops

    def discard_step(self, key: Key, direction: HistoryDirection, entry_id: str, *, after_digest: str) -> None:
        """Une entrée qui n'a rien changé (inverse sans effet) : retirée sans rien sur la pile opposée."""

        ring = self._rings.get(key)
        source = ring.stack(direction) if ring is not None else []
        if ring is not None and source and source[-1].entry_id == entry_id:
            source.pop()
            ring.expected_digest = after_digest

    def drop(self, key: Key, reason: DropReason) -> Drop | None:
        return self._drop(key, reason) if key in self._rings else None

    def drop_presentation(self, presentation_id: str, reason: DropReason) -> list[Drop]:
        return [self._drop(key, reason) for key in [k for k in self._rings if k[0] == presentation_id]]

    # ------------------------------------------------------------ interne

    def _remember(self, key: Key, reason: DropReason) -> None:
        self._notes[key] = reason
        self._notes.move_to_end(key)
        while len(self._notes) > MAX_REMEMBERED_DROPS:
            self._notes.popitem(last=False)

    def _drop(self, key: Key, reason: DropReason) -> Drop:
        ring = self._rings.pop(key)
        self.dropped_rings += 1
        self.evicted_entries += ring.count
        self._remember(key, reason)
        return Drop(key, reason, "ring", ring.count, ring.size)

    def _make_room_for_a_ring(self) -> list[Drop]:
        drops = []
        while len(self._rings) >= MAX_TRACKED_VARIANTS:
            oldest = next(iter(self._rings))
            drops.append(self._drop(oldest, DropReason.TRACKED_VARIANTS_BOUND))
        return drops

    def _enforce(self, key: Key) -> list[Drop]:
        """Applique les bornes à l'anneau qui vient de bouger ; dit tout ce qui a cédé."""

        ring = self._rings[key]
        evicted, freed = 0, 0
        while ring.count > MAX_ENTRIES_PER_VARIANT or ring.size > MAX_VARIANT_BYTES:
            gone = (ring.undo or ring.redo).pop(0)
            evicted += 1
            freed += gone.size
        drops: list[Drop] = []
        if evicted:
            ring.evicted += evicted
            self.evicted_entries += evicted
            drops.append(Drop(key, DropReason.VARIANT_BOUND, "entries", evicted, freed))
        while self.total_bytes > MAX_TOTAL_BYTES:
            victim = next((k for k in self._rings if k != key), None)
            if victim is None:
                break  # one ring alone is within MAX_VARIANT_BYTES < MAX_TOTAL_BYTES: unreachable
            drops.append(self._drop(victim, DropReason.MEMORY_BOUND))
        return drops


def limits() -> dict[str, int]:
    return {"entries_per_variant": MAX_ENTRIES_PER_VARIANT, "bytes_per_entry": MAX_ENTRY_BYTES,
            "bytes_per_variant": MAX_VARIANT_BYTES, "bytes_total": MAX_TOTAL_BYTES,
            "tracked_variants": MAX_TRACKED_VARIANTS}


# ------------------------------------------------------------------ résultat

#: Statut HTTP de chaque issue (le statut du `refused` est celui de son code d'édition).
HISTORY_HTTP_STATUS: Mapping[HistoryStatus, int] = {
    HistoryStatus.APPLIED: 200, HistoryStatus.UNAVAILABLE: 409, HistoryStatus.NOTHING_TO_UNDO: 409,
    HistoryStatus.NOTHING_TO_REDO: 409, HistoryStatus.STALE: 409, HistoryStatus.REFUSED: 400,
}

#: Codes d'enveloppe des issues qui ne sont pas `applied` (voir `PresentationStudioErrorCode`).
HISTORY_CODE: Mapping[HistoryStatus, C] = {
    HistoryStatus.UNAVAILABLE: C.HISTORY_UNAVAILABLE, HistoryStatus.NOTHING_TO_UNDO: C.HISTORY_EMPTY,
    HistoryStatus.NOTHING_TO_REDO: C.HISTORY_EMPTY, HistoryStatus.STALE: C.HISTORY_STALE,
}


@dataclass(frozen=True, slots=True)
class HistoryResult:
    status: HistoryStatus
    direction: HistoryDirection
    actor: StudioActor
    presentation_id: str
    variant_id: str
    #: Révision courante de la variante après l'appel (inchangée si rien n'a été écrit).
    revision: int | None
    history: Mapping[str, Any]
    entry: Mapping[str, Any] | None = None
    tier: str | None = None
    changed: bool = False
    reason: str | None = None
    code: str | None = None
    message: str | None = None
    #: Références de la partition qui ne se résolvent plus après le changement (seulement un compte ; `None` : sans partition).
    score_problems: int | None = None
    http: int | None = None

    @property
    def http_status(self) -> int:
        return self.http if self.http is not None else HISTORY_HTTP_STATUS[self.status]

    def to_dict(self) -> dict[str, Any]:
        wire: dict[str, Any] = {
            "status": self.status.value, "direction": self.direction.value, "actor": self.actor.value,
            "presentation_id": self.presentation_id, "variant_id": self.variant_id, "revision": self.revision,
            "changed": self.changed, "tier": self.tier, "entry": dict(self.entry) if self.entry else None,
            "score_problems": self.score_problems, "history": dict(self.history)}
        if self.status is not HistoryStatus.APPLIED:
            wire.update({"reason": self.reason, "code": self.code, "message": self.message,
                         "error": {"code": self.code, "message": self.message}})
        return wire

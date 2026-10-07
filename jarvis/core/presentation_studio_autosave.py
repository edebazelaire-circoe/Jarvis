"""Garantie de durabilité et historique d'annulation du Studio (handoff jarvis-interactive-presentation-studio, Slice 08).

## Il n'y a pas de second chemin de persistance

Chaque commit de la Slice 05 (`PresentationStudioEditService`) écrit la variante **avant d'être acquitté** :
fichier temporaire, `fsync`, remplacement atomique (`os.replace`), puis vidage du dossier
(`file_presentation_studio_store._sync_folder`), le tout sous la comparaison de révision. « Autosave » est donc ce
contrat, pas une file : **un commit acquitté est durable**, sans délai ni fenêtre de perte. Ce module n'ajoute ni tampon
ni minuterie (rien à vider à l'arrêt, au changement de variante ou à la mise en veille). Les gestes à haute cadence
(glisser un curseur) passent par `mode=preview`, qui n'écrit rien ; le commit unique se fait au relâchement.

## Ce que ce module tient

`PresentationStudioHistory` : l'anneau d'annulation/rétablissement **en mémoire** (`presentation_studio_history.UndoBook`,
bornes dures), branché sur le service d'édition par trois appels synchrones (`begin`/`commit`/`abort`, protocole
`EditHistory`), puis `undo` / `redo` / `status`. Un annuler **est** une édition : il passe par
`PresentationStudioEditService.edit` (mêmes validations, même base de révision, même écriture durable, même évènement),
avec les opérations inverses de l'entrée.

- **Périmé, jamais forcé.** Avant de rejouer, l'empreinte des scènes lues est comparée à celle que l'anneau attend ;
  si elle diffère (écriture hors anneau), `stale` et l'anneau est abandonné. Une édition concurrente qui gagne la base
  rend `stale` à l'annuler perdant ; son entrée est déjà en tête de l'anneau.
- **Une nouvelle édition vide « rétablir »** (`UndoBook.record_edit`).
- **Redémarrage.** Mémoire seulement : `history_unavailable`, raison `not_recorded_since_start`, jamais un silence.
- **Pins.** `pinned_versions` rend les `(prefab_id, version)` que rejouer une entrée écrirait ; branché dans le
  `PrefabPinRegistry` de la Slice 01a quand la Slice 06 le câble. Une entrée est tenue (`begin`) **avant** que le
  document ne perde la scène qui portait le pin.
- **Variantes.** Un anneau par variante. Changer de variante active **ne vide pas** les anneaux (bornés à 8, le moins
  récent cède) ; archiver ou supprimer appelle `drop_variant` / `drop_presentation` (Slice 16).

Diagnostics `core.presentation_studio.history_*` : ids, noms d'opération, comptes, raisons ; jamais une valeur, un titre
ni une intention.
"""

from __future__ import annotations

import asyncio
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationVariant, clip
from jarvis.domain.presentation_studio_checks import PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import EditResult, EditStatus, StudioActor
from jarvis.domain.presentation_studio_history import (
    HISTORY_CODE, Drop, DropReason, HistoryDirection, HistoryEntry, HistoryRequest, HistoryResult, HistoryStatus,
    HistoryStep, Key, UndoBook, parse_history_request, pins_of, reason_text, scenes_digest,
)
from jarvis.ports.v2 import DiagnosticSink


@dataclass(frozen=True, slots=True)
class _Ticket:
    key: Key
    entry_ops: tuple[Mapping[str, Any], ...]
    reservation: int
    step: HistoryStep | None


class PresentationStudioHistory:
    """Voir l'en-tête. Un exemplaire par Core ; `bind` le relie au service d'édition qui l'appelle."""

    def __init__(self, studio: PresentationStudioService, *, diagnostics: DiagnosticSink | None = None,
                 book: UndoBook | None = None) -> None:
        self._studio = studio
        self._diagnostics = diagnostics
        self._book = book or UndoBook()
        self._edit: PresentationStudioEditService | None = None
        self._lock = asyncio.Lock()  # one undo/redo at a time; plain edits never wait on it

    def bind(self, edit: PresentationStudioEditService) -> None:
        self._edit = edit

    # ------------------------------------------------------------ crochet du service d'édition (synchrone)

    def begin(self, presentation_id: str, variant_id: str, inverse: Sequence[Mapping[str, Any]],
              step: HistoryStep | None) -> _Ticket:
        ops = tuple(inverse)
        return _Ticket((presentation_id, variant_id), ops, self._book.reserve(pins_of(ops)), step)

    def abort(self, ticket: object) -> None:
        assert isinstance(ticket, _Ticket)
        self._book.release(ticket.reservation)

    def commit(self, ticket: object, *, actor: str, op_names: Sequence[str], tier: str, before_digest: str,
               after_digest: str, revision: int) -> None:
        """Le commit est écrit : l'inverse devient une entrée, dans la même étape synchrone que la libération de sa
        réservation (aucun instant où le pin n'est tenu nulle part). Ne lève jamais : un échec ici abandonne l'anneau."""

        assert isinstance(ticket, _Ticket)
        key = ticket.key
        try:
            entry = self._book.make_entry(ticket.entry_ops, op_names=op_names, tier=tier, actor=actor, revision=revision)
            if ticket.step is None:
                drops = self._book.record_edit(key, entry, before_digest=before_digest, after_digest=after_digest)
            else:
                drops = self._book.record_step(key, ticket.step.direction, ticket.step.entry_id, entry,
                                               after_digest=after_digest)
            self._book.release(ticket.reservation)
        except Exception as exc:  # noqa: BLE001 - the edit is already durable; an inconsistent ring is dropped, not trusted
            self._book.release(ticket.reservation)
            drop = self._book.drop(key, DropReason.RECORD_FAILED)
            self._trace("core.presentation_studio.history_record_failed", "Historique non mis a jour: anneau abandonne",
                        level="error", data={"presentation_id": key[0], "variant_id": key[1],
                                             "error": clip(f"{type(exc).__name__}: {exc}")})
            drops = [drop] if drop else []
        self._report(drops)

    # ------------------------------------------------------------ annuler / rétablir

    async def undo(self, presentation_id: str, variant_id: str, raw: object) -> HistoryResult:
        return await self._step(HistoryDirection.UNDO, presentation_id, variant_id, raw)

    async def redo(self, presentation_id: str, variant_id: str, raw: object) -> HistoryResult:
        return await self._step(HistoryDirection.REDO, presentation_id, variant_id, raw)

    async def _step(self, direction: HistoryDirection, presentation_id: str, variant_id: str,
                    raw: object) -> HistoryResult:
        request = parse_history_request(raw)
        key: Key = (presentation_id, variant_id)
        edit = self._require_edit()
        async with self._lock:
            variant = await self._studio.get_variant(presentation_id, variant_id)  # typed error if missing / corrupt
            ring = self._book.ring(key)
            if ring is None:
                reason = self._book.why_unavailable(key)
                return self._answer(HistoryStatus.UNAVAILABLE, direction, request, key, variant, reason=reason.value,
                                    message=reason_text(reason))
            stack = ring.stack(direction)
            if not stack:
                status = HistoryStatus.NOTHING_TO_UNDO if direction is HistoryDirection.UNDO else HistoryStatus.NOTHING_TO_REDO
                older = " (older steps were dropped by the history bound)" if ring.evicted else ""
                return self._answer(status, direction, request, key, variant, reason="empty",
                                    message=f"nothing to {direction.value}{older}")
            entry = stack[-1]
            if request.expected_entry_id is not None and request.expected_entry_id != entry.entry_id:
                return self._answer(HistoryStatus.STALE, direction, request, key, variant, entry=entry,
                                    reason="head_changed",
                                    message=f"the next {direction.value} step is {entry.entry_id}, not "
                                            f"{request.expected_entry_id}: read the history again")
            if scenes_digest(variant.scenes) != ring.expected_digest:
                self._report([self._book.drop(key, DropReason.DOCUMENT_MOVED_ON)])
                reason = DropReason.DOCUMENT_MOVED_ON
                return self._answer(HistoryStatus.STALE, direction, request, key, variant, entry=entry,
                                    reason=reason.value, message=reason_text(reason))
            return await self._apply(edit, direction, request, key, variant, entry)

    async def _apply(self, edit: PresentationStudioEditService, direction: HistoryDirection, request: HistoryRequest,
                     key: Key, variant: PresentationVariant, entry: HistoryEntry) -> HistoryResult:
        body = {"actor": request.actor.value, "mode": "commit", "basis": {"variant_revision": variant.revision},
                "ops": list(entry.ops)}
        result: EditResult = await edit.edit(key[0], key[1], body, step=HistoryStep(direction, entry.entry_id))
        if result.status is EditStatus.STALE:  # another writer won the base: its own entry is already on the ring
            return self._answer(HistoryStatus.STALE, direction, request, key, variant, entry=entry, revision=result.revision,
                                reason="revision_moved", code_override=result.code, message=result.message)
        if result.status is EditStatus.REFUSED:
            self._report([self._book.drop(key, DropReason.ENTRY_NOT_APPLICABLE)])
            return self._answer(HistoryStatus.REFUSED, direction, request, key, variant, entry=entry,
                                revision=result.revision, reason=DropReason.ENTRY_NOT_APPLICABLE.value,
                                code_override=result.code, message=result.message, http=result.http_status)
        if not result.changed:  # the inverse changed nothing (state already equal): the step is spent, nothing to redo
            ring = self._book.ring(key)
            if ring is not None and ring.stack(direction) and ring.stack(direction)[-1].entry_id == entry.entry_id:
                self._book.discard_step(key, direction, entry.entry_id, after_digest=scenes_digest(variant.scenes))
        score = await self._score_problems(key, variant)
        self._trace("core.presentation_studio.history_applied", "Annuler/retablir applique",
                    data={"presentation_id": key[0], "variant_id": key[1], "direction": direction.value,
                          "actor": request.actor.value, "entry_id": entry.entry_id, "revision": result.revision,
                          "tier": result.tier.value if result.tier else None, "changed": result.changed,
                          "score_problems": score})
        return self._answer(HistoryStatus.APPLIED, direction, request, key, variant, entry=entry,
                            revision=result.revision, tier=result.tier.value if result.tier else None,
                            changed=result.changed, score_problems=score)

    async def _score_problems(self, key: Key, variant: PresentationVariant) -> int | None:
        """Combien de références de la partition ne se résolvent plus (un retrait annulé ou refait les change) ; `None` sans partition."""

        if variant.score_id is None:
            return None
        try:
            answer = await self._studio.get_score(key[0], key[1])
        except PresentationStudioError as exc:
            # the score is unreadable or absent: the step stands, the fault is already journaled by the variant service
            self._trace("core.presentation_studio.history_score_unchecked", "Partition non verifiee apres annuler/retablir",
                        level="warning", data={"presentation_id": key[0], "variant_id": key[1], "code": exc.code.value})
            return None
        return len(answer["problems"])

    # ------------------------------------------------------------ état, abandon, pins

    async def status(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        """L'historique de la variante : ce qui s'annulerait/rétablirait, les bornes, ce qui a été évincé. Lecture seule."""

        key: Key = (presentation_id, variant_id)
        variant = await self._studio.get_variant(presentation_id, variant_id)
        ring = self._book.ring(key)
        in_sync = ring is None or ring.expected_digest is None or ring.expected_digest == scenes_digest(variant.scenes)
        return {"presentation_id": presentation_id, "variant_id": variant_id, "revision": variant.revision,
                "in_sync": in_sync, "durable": False,
                "durability": "the variant itself is durable at every acknowledged commit; this history is memory only",
                **self._book.describe(key), "stats": self._book.stats()}

    def drop_variant(self, presentation_id: str, variant_id: str, reason: DropReason = DropReason.VARIANT_ARCHIVED) -> None:
        """Appelé par la Slice 16 quand une variante est archivée ou supprimée."""

        self._report([self._book.drop((presentation_id, variant_id), reason)])

    def drop_presentation(self, presentation_id: str, reason: DropReason = DropReason.PRESENTATION_REMOVED) -> None:
        self._report(self._book.drop_presentation(presentation_id, reason))

    def pins(self) -> frozenset[tuple[str, int]]:
        return self._book.pins()

    async def pinned_versions(self, prefab_ids: Collection[str]) -> Mapping[str, frozenset[int]]:
        """`PrefabPinRegistry.pinned_versions` (Slice 01a) pour les piles d'annulation. Ne lève pas : la mémoire répond toujours."""

        held = self._book.pins()
        return {prefab_id: frozenset(version for pid, version in held if pid == prefab_id) for prefab_id in prefab_ids}

    # ------------------------------------------------------------ interne

    def _require_edit(self) -> PresentationStudioEditService:
        if self._edit is None:
            raise PresentationStudioError(C.STORAGE_IO, "the undo history is not bound to the edit service")
        return self._edit

    def _answer(self, status: HistoryStatus, direction: HistoryDirection, request: HistoryRequest, key: Key,
                variant: PresentationVariant, *, entry: HistoryEntry | None = None, revision: int | None = None,
                tier: str | None = None, changed: bool = False, reason: str | None = None, message: str | None = None,
                score_problems: int | None = None, code_override: str | None = None,
                http: int | None = None) -> HistoryResult:
        code = code_override or (HISTORY_CODE[status].value if status in HISTORY_CODE else None)
        if status is not HistoryStatus.APPLIED:
            self._trace("core.presentation_studio.history_not_applied", "Annuler/retablir non applique",
                        data={"presentation_id": key[0], "variant_id": key[1], "direction": direction.value,
                              "actor": request.actor.value, "status": status.value, "reason": reason, "code": code})
        return HistoryResult(
            status, direction, request.actor, key[0], key[1], variant.revision if revision is None else revision,
            self._book.describe(key), entry=entry.summary() if entry is not None else None, tier=tier, changed=changed,
            reason=reason, code=code, message=clip(message) if message else None, score_problems=score_problems,
            http=http)

    def _report(self, drops: Sequence[Drop | None]) -> None:
        for drop in drops:
            if drop is None:
                continue
            self._trace("core.presentation_studio.history_dropped" if drop.kind == "ring"
                        else "core.presentation_studio.history_evicted",
                        "Historique d'annulation reduit", level="info" if drop.reason is DropReason.REDO_CLEARED else "warning",
                        data={"presentation_id": drop.key[0], "variant_id": drop.key[1], "reason": drop.reason.value,
                              "kind": drop.kind, "entries": drop.entries, "bytes": drop.bytes})

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a studio operation
            pass

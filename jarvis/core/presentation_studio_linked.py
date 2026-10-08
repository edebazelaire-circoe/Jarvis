"""Documents liés à une variante (handoff jarvis-interactive-presentation-studio, Slice 16).

Une variante *cite* d'autres documents par un id : la partition (`score_id`, Slice 10), la direction artistique
(`art_direction_id`, Slice 09). Brancher une variante (`PresentationStudioVariants.create_branch`) doit **copier
profondément** ces documents sous de nouveaux ids : deux variantes ne partagent jamais un document éditable (éditer la
partition de A ne doit jamais bouger B). Ce module est le **registre** de ces genres de documents :

- `LinkedKind` : un genre (`name`), le champ de la variante qui le cite (`field`), la zone du magasin où il vit (`area`,
  pour trouver les orphelins) et `prepare` (lit la source, valide, **n'écrit rien**, rend un `PreparedCopy` dont `write()`
  écrit la copie). Lire avant d'allouer le numéro : une source illisible refuse la branche sans consommer de numéro.
- `LinkedDocuments` : le registre. `refuse_unsupported` **ferme** par défaut : une variante qui cite un document dont aucun
  genre n'est enregistré (une direction artistique tant que la Slice 09 n'est pas câblée) n'est pas branchable
  (`presentation_studio_linked_document_unsupported`) : le partager serait pire que refuser.
- `ScoreLink` : le genre « partition », écrit ici.

`ArtDirectionLink` : le genre « direction artistique » (Slice 09), de même forme. Les deux sont enregistrés par défaut ; un futur genre
(Slice 17, 20) s'ajoute avec `PresentationStudioVariants(..., linked=...)` ; l'ordre d'écriture, les orphelins et le rapport sont déjà couverts.
"""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Protocol

from jarvis.domain.presentation_studio import (
    PresentationStudioError, PresentationStudioErrorCode as C, PresentationVariant, dump_document, stamp,
)
from jarvis.domain.presentation_studio_art_direction import new_art_direction_id
from jarvis.domain.presentation_studio_score import new_score_id

#: Champs d'une variante qui citent un document lié. Un champ renseigné sans genre enregistré refuse la branche.
LINKED_FIELDS = ("score_id", "art_direction_id")


@dataclass(frozen=True, slots=True)
class LinkedCopy:
    """Le résultat de la copie d'un document lié."""

    kind: str
    source_ref: str | None
    #: Nouvel id (`None` : la source n'en avait pas, ou son fichier est absent).
    new_ref: str | None
    #: `copied`, `none` (la source ne citait rien) ou `missing_source` (citait un fichier absent : lien pendant, branche sans lui).
    status: str
    #: Écrit la copie (`None` : rien à écrire). Appelé sous le verrou, **après** l'allocation du numéro, **avant** la variante.
    write: Callable[[], Awaitable[None]] | None = field(default=None, compare=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "source_ref": self.source_ref, "new_ref": self.new_ref, "status": self.status}


class LinkedKind(Protocol):
    name: str
    #: Champ de `PresentationVariant` qui cite ce document.
    field: str
    #: Zone du magasin (`FilePresentationStudioStore.list_documents`) où il vit.
    area: str

    async def prepare(self, presentation_id: str, source: PresentationVariant, new_variant_id: str,
                      now: datetime) -> LinkedCopy:
        """Lit la source et prépare la copie profonde sous un nouvel id (`LinkedCopy.write` l'écrira) ; n'écrit rien."""


class LinkedDocuments:
    def __init__(self, *kinds: LinkedKind) -> None:
        self._kinds: dict[str, LinkedKind] = {}
        for kind in kinds:
            self.register(kind)

    def register(self, kind: LinkedKind) -> None:
        if kind.name in self._kinds or any(k.field == kind.field for k in self._kinds.values()):
            raise ValueError(f"linked document kind {kind.name!r} or its field {kind.field!r} is already registered")
        if kind.field not in LINKED_FIELDS:
            raise ValueError(f"{kind.field!r} is not a linked field of a variant ({', '.join(LINKED_FIELDS)})")
        self._kinds[kind.name] = kind

    @property
    def kinds(self) -> tuple[LinkedKind, ...]:
        return tuple(self._kinds.values())

    def refuse_unsupported(self, variant: PresentationVariant) -> None:
        """Ferme par défaut : un document cité dont personne ne sait faire la copie profonde refuse la branche."""

        registered = {kind.field for kind in self._kinds.values()}
        unsupported = [name for name in LINKED_FIELDS if getattr(variant, name) is not None and name not in registered]
        if unsupported:
            raise PresentationStudioError(
                C.LINKED_DOCUMENT_UNSUPPORTED,
                f"variant {variant.variant_id} cites {', '.join(unsupported)}: no copier is registered, so the branch would "
                "share an editable document with its parent; refused")

    def referenced(self, variants: Iterable[PresentationVariant], kind: LinkedKind) -> frozenset[str]:
        return frozenset(ref for v in variants if (ref := getattr(v, kind.field)) is not None)


class ArtDirectionLink:
    """Le genre « direction artistique » (Slice 09) : `art_directions/<art_direction_id>.json`, une copie par variante sous un nouvel
    id `psd_` (le document nomme sa variante, qui devient la branche), révision 1. Une branche « sérieuse » résout ainsi **sa propre**
    DA (`require_art_direction`, garde de la lecture), jamais celle de sa source : éditer la DA d'une variante ne bouge pas l'autre."""

    name = "art_direction"
    field = "art_direction_id"
    area = "art_directions"

    def __init__(self, studio: Any) -> None:
        self._studio = studio

    async def prepare(self, presentation_id: str, source: PresentationVariant, new_variant_id: str,
                      now: datetime) -> LinkedCopy:
        if source.art_direction_id is None:
            return LinkedCopy(self.name, None, None, "none")
        try:
            art = await self._studio.load_art_direction_locked(presentation_id, source)
        except PresentationStudioError as exc:
            if exc.code is C.UNKNOWN_ART_DIRECTION:
                return LinkedCopy(self.name, source.art_direction_id, None, "missing_source")  # dangling link: the branch starts without
            raise  # corrupt / newer: the branch is refused, never "repaired" by dropping the art direction
        at = stamp(now)
        copied = replace(art, art_direction_id=new_art_direction_id(), variant_id=new_variant_id, revision=1,
                         created_at=at, updated_at=at)
        text = dump_document(copied.to_document())

        async def write() -> None:
            await self._studio.run_blocking("branch_art_direction", presentation_id, self._studio.store.write_art_direction,
                                            presentation_id, copied.art_direction_id, text)

        return LinkedCopy(self.name, source.art_direction_id, copied.art_direction_id, "copied", write)


class ScoreLink:
    """Le genre « partition » (Slice 10) : `scores/<score_id>.json`, une copie par variante, items et cues gardent leurs ids
    (uniques *dans* une partition ; les garder permet de comparer deux variantes, Slice 19)."""

    name = "score"
    field = "score_id"
    area = "scores"

    def __init__(self, studio: Any) -> None:
        self._studio = studio

    async def prepare(self, presentation_id: str, source: PresentationVariant, new_variant_id: str,
                      now: datetime) -> LinkedCopy:
        if source.score_id is None:
            return LinkedCopy(self.name, None, None, "none")
        try:
            score = await self._studio.load_score_locked(presentation_id, source)
        except PresentationStudioError as exc:
            if exc.code is C.UNKNOWN_SCORE:
                return LinkedCopy(self.name, source.score_id, None, "missing_source")  # dangling link: the branch starts without
            raise  # corrupt / newer: the branch is refused, the source is never "repaired" by dropping its score
        at = stamp(now)
        copied = replace(score, score_id=new_score_id(), variant_id=new_variant_id, revision=1, created_at=at, updated_at=at)
        text = dump_document(copied.to_document())

        async def write() -> None:
            await self._studio.run_blocking("branch_score", presentation_id, self._studio.store.write_score, presentation_id,
                                            copied.score_id, text)

        return LinkedCopy(self.name, source.score_id, copied.score_id, "copied", write)

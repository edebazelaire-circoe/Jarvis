"""Purge definitive des presentations archivees : le plan, son jeton de confirmation, le corps des requetes. Pur (aucune E/S).

Le plan nomme l'**ensemble exact** de ce qui partira : chaque presentation archivee (id, titre, date d'archivage, revision du
manifeste), ses variantes vivantes et archivees, ses documents lies (comptes), ses Artifacts derives (snapshots et rendus) et ses
sources de scene `presentation-studio.p<12 hex>.*`. Le jeton est un HMAC de cet ensemble et d'une expiration (meme construction
que l'archivage de variantes, `presentation_studio_variants.issue_confirmation`, avec son propre prefixe `ppk_` : un jeton d'un
autre geste n'est jamais accepte). Si l'ensemble change entre le plan et l'execution (une presentation archivee ou restauree, un
nouveau rendu, une source publiee), l'execution est refusee `confirmation_stale` et rien n'est efface.

Contrat : `docs/presentation-studio.md` > *Rail des presentations* > *Purge definitive des archivees*.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from typing import Any

from jarvis.domain.presentation_studio import PresentationStudioError, is_presentation_id
from jarvis.domain.presentation_studio_checks import PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_variants import CONFIRMATION_TTL_S

#: Validite du jeton d'une purge (secondes) : celle de l'archivage de variantes.
PURGE_CONFIRMATION_TTL_S = CONFIRMATION_TTL_S
PURGE_TOKEN_PREFIX = "ppk_"
_TOKEN = re.compile(rf"{PURGE_TOKEN_PREFIX}[0-9]{{1,12}}\.[0-9a-f]{{64}}\Z")
#: Filtre d'ids d'une requete (au plus).
MAX_PURGE_IDS = 256
ACTORS = ("user", "brain")
PLAN_KEYS = frozenset({"presentation_ids", "actor"})
PURGE_KEYS = PLAN_KEYS | {"confirmation", "confirmed"}


@dataclass(frozen=True, slots=True)
class PurgeTarget:
    """Une presentation archivee et tout ce qui part avec elle."""

    presentation_id: str
    title: str | None
    archived_at: str | None
    #: Revision du manifeste ; `None` si le manifeste est illisible (la presentation reste purgeable : `rail.json` dit archivee).
    revision: int | None
    variant_ids: tuple[str, ...]
    archived_variant_ids: tuple[str, ...]
    #: Tous les Artifacts effaces (snapshots et leurs derives, en cascade), tries.
    artifact_ids: tuple[str, ...]
    #: Sources de scene propres a la presentation (`presentation-studio.p<12 hex>.*`), triees.
    prefab_ids: tuple[str, ...]
    scores: int = 0
    art_directions: int = 0
    compositions: int = 0
    #: Les snapshots parmi `artifact_ids` (les racines de la cascade).
    snapshot_ids: tuple[str, ...] = ()

    @property
    def renders(self) -> int:
        return len(self.artifact_ids) - len(self.snapshot_ids)

    def view(self) -> dict[str, Any]:
        return {"presentation_id": self.presentation_id, "title": self.title, "archived_at": self.archived_at,
                "revision": self.revision, "variants": len(self.variant_ids), "archived_variants": len(self.archived_variant_ids),
                "scores": self.scores, "art_directions": self.art_directions, "compositions": self.compositions,
                "snapshots": len(self.snapshot_ids), "renders": self.renders, "prefabs": len(self.prefab_ids)}

    def bound(self) -> list[Any]:
        """Ce que le jeton lie (l'ensemble exact)."""

        return [self.presentation_id, self.title, self.archived_at, self.revision, list(self.variant_ids),
                list(self.archived_variant_ids), list(self.artifact_ids), list(self.prefab_ids), self.scores, self.art_directions,
                self.compositions]


@dataclass(frozen=True, slots=True)
class PurgePlan:
    targets: tuple[PurgeTarget, ...]
    #: Archivees laissees hors du plan, avec la raison (un Artifact encore `pending`, un rendu en cours...) : `{presentation_id,
    #: title, reason}`. Hors du jeton : elles ne seront pas effacees.
    blocked: tuple[dict[str, Any], ...] = ()
    #: Faits signales sans bloquer (une source de scene laissee parce que son prefixe de 12 hex est partage...).
    notes: tuple[str, ...] = ()

    @property
    def presentation_ids(self) -> tuple[str, ...]:
        return tuple(t.presentation_id for t in self.targets)

    def view(self) -> dict[str, Any]:
        rows = [t.view() for t in self.targets]
        totals = {key: sum(row[key] for row in rows) for key in ("variants", "archived_variants", "scores", "art_directions",
                                                                   "compositions", "snapshots", "renders", "prefabs")}
        return {"presentations": rows, "count": len(rows), "totals": totals, "blocked": list(self.blocked),
                "notes": list(self.notes), "irreversible": True, "backup": "backups/purge-presentations-<UTC timestamp>/"}


def purge_digest(secret: bytes, plan: PurgePlan, expires_at: int) -> str:
    body = json.dumps({"purge": sorted((t.bound() for t in plan.targets), key=lambda row: row[0]), "exp": expires_at},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def issue_purge_confirmation(secret: bytes, plan: PurgePlan, now_epoch: int) -> str:
    expires = now_epoch + PURGE_CONFIRMATION_TTL_S
    return f"{PURGE_TOKEN_PREFIX}{expires}.{purge_digest(secret, plan, expires)}"


def check_purge_confirmation(secret: bytes, plan: PurgePlan, token: object, now_epoch: int) -> None:
    """Le jeton doit etre celui de **ce** plan. Absent ou mal forme : `confirmation_required`. Pour un autre ensemble, d'un autre
    processus ou expire : `confirmation_stale`. Comparaison a temps constant."""

    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise PresentationStudioError(C.CONFIRMATION_REQUIRED, "purging needs the confirmation token of a purge plan (plan first, "
                                                               "read it to the user, then confirm)")
    expires = int(token[len(PURGE_TOKEN_PREFIX):].split(".", 1)[0])
    expected = f"{PURGE_TOKEN_PREFIX}{expires}.{purge_digest(secret, plan, expires)}"
    if not hmac.compare_digest(token, expected):
        raise PresentationStudioError(C.CONFIRMATION_STALE, "the confirmation does not match what would be purged now (a "
                                                            "presentation was archived or restored, an export or a scene source "
                                                            "changed, or the token is not from this plan): plan again")
    if now_epoch > expires:
        raise PresentationStudioError(C.CONFIRMATION_STALE, "the confirmation expired: plan again")


@dataclass(frozen=True, slots=True)
class PurgeRequest:
    presentation_ids: tuple[str, ...] | None
    actor: str
    confirmation: object = None
    confirmed: bool | None = None


def parse_purge_request(raw: object, *, execute: bool) -> PurgeRequest:
    """`{presentation_ids?, actor?}` (plan) ; plus `{confirmation, confirmed}` (execution). Cle inconnue : refus."""

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise PresentationStudioError(C.INVALID_PRESENTATION, "body must be a JSON object")
    unknown = set(raw) - (PURGE_KEYS if execute else PLAN_KEYS)
    if unknown:
        raise PresentationStudioError(C.INVALID_PRESENTATION, "unknown key: " + ", ".join(sorted(map(str, unknown))))
    actor = raw.get("actor", "user")
    if actor not in ACTORS:
        raise PresentationStudioError(C.INVALID_PRESENTATION, "actor must be user or brain")
    ids = raw.get("presentation_ids")
    if ids is not None:
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_PURGE_IDS or not all(is_presentation_id(i) for i in ids):
            raise PresentationStudioError(C.INVALID_PRESENTATION, f"presentation_ids: 1 to {MAX_PURGE_IDS} presentation ids")
        if len(set(ids)) != len(ids):
            raise PresentationStudioError(C.INVALID_PRESENTATION, "presentation_ids: each id once")
        ids = tuple(sorted(ids))
    confirmed = raw.get("confirmed")
    if confirmed is not None and type(confirmed) is not bool:
        raise PresentationStudioError(C.INVALID_PRESENTATION, "confirmed must be a boolean")
    return PurgeRequest(ids, actor, raw.get("confirmation"), confirmed)

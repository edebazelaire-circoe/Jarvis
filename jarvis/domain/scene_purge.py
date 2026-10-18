"""Purge définitive des objets archivés de la scène : plan, jeton de confirmation, instantané résultant. Pur.

Demande de l'utilisateur (2026-10-18) : « vire tous les trucs archivés, je veux
vraiment que tout soit supprimé », puis « une vraie purge définitive, en
sauvegardant d'abord la base ». Jusque-là, un objet archivé gardait pour
toujours sa pierre tombale (`SceneSnapshot.archived_ids`, bornée à 4 096) et
sa forme complète dans `scene_history`.

En deux temps, comme l'archivage des variantes du Presentation Studio
(`presentation_studio_variants.issue_confirmation`) :

1. **plan** (n'écrit rien) : `plan_archive_purge` dit quelles pierres tombales
   et combien de lignes d'historique partiraient, et lesquelles restent ;
   `issue_purge_token` rend un jeton HMAC à durée limitée
   (`PURGE_CONFIRMATION_TTL_S`) ;
2. **exécution** : Core recalcule le plan sous son verrou ; le jeton doit
   décrire **exactement** ce plan (`check_purge_token`), sinon rien n'est
   effacé.

Ce que le jeton lie : la scène (`scene_id`), le chargement de Core
(`epoch`, et un secret propre au processus), l'ensemble exact des ids
purgés, dans l'ordre, et le nombre de lignes d'historique purgées. Il ne lie
**pas** la révision : la projection runtime la fait avancer à chaque mise à
jour d'étoile, et une confirmation donnée à la voix arrive des secondes plus
tard. Ce qui serait effacé est identique tant que l'ensemble l'est ; tout
archivage, toute pierre tombale libérée par le runtime change l'ensemble et
périme le jeton.

Ce qui reste : les ids que le runtime suit encore (`retained`, fourni par la
projection de Core). Retirer leur pierre tombale laisserait la prochaine
observation de leur travail recréer l'étoile que l'utilisateur a archivée
(`docs/scene-model.md` › *Archive purge*). Leur historique reste avec eux.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import hmac
import json
import re
from typing import Any

from jarvis.domain.scene import SceneSnapshot

#: Validité d'un jeton de confirmation (secondes) : le temps d'un « oui » à la voix.
PURGE_CONFIRMATION_TTL_S = 600
PURGE_TOKEN_PREFIX = "spg_"
_TOKEN = re.compile(r"\Aspg_[0-9]{1,12}\.[0-9a-f]{64}\Z")
#: Ids gardés cités dans une réponse (le compte, lui, est complet).
MAX_REPORTED_KEPT_IDS = 20
#: Motif d'un id gardé, rendu à l'appelant.
KEPT_REASON = ("encore suivis par le runtime (travail connu de Core) : leur pierre tombale empêche leur étoile de "
               "renaître ; purgeables quand le runtime les aura oubliés")


class ScenePurgeCode(StrEnum):
    """Refus stables d'une purge ; aucun n'efface quoi que ce soit."""

    #: Jeton absent ou mal formé : planifier d'abord.
    CONFIRMATION_REQUIRED = "confirmation_required"
    #: Jeton valide de forme mais pour un autre état (ensemble, scène, chargement de Core) ou expiré.
    CONFIRMATION_STALE = "confirmation_stale"
    #: La projection runtime ne peut pas encore dire ce qu'elle suit (démarrage de Core, producteurs pas encore revenus).
    RUNTIME_SETTLING = "runtime_settling"
    #: La sauvegarde préalable a échoué : rien n'a été effacé.
    BACKUP_FAILED = "purge_backup_failed"


class ScenePurgeError(Exception):
    """Refus d'une purge, avec un code stable ; `retry_after_s` quand réessayer plus tard suffit."""

    def __init__(self, code: ScenePurgeCode, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after_s = retry_after_s


@dataclass(frozen=True, slots=True)
class ScenePurgePlan:
    """Ce qu'une purge ferait sur un instantané donné.

    `purge_ids` / `kept_ids` : partition de `snapshot.archived_ids`, dans
    l'ordre d'archivage. `history_rows` : lignes de `scene_history` qui
    partiraient (toutes celles dont l'id ne garde pas sa pierre tombale,
    anciennes incarnations comprises) ; `kept_history_rows` : celles des ids
    gardés.
    """

    scene_id: str
    revision: int
    purge_ids: tuple[str, ...]
    kept_ids: tuple[str, ...]
    history_rows: int
    kept_history_rows: int

    @property
    def empty(self) -> bool:
        return not self.purge_ids and not self.history_rows

    def kept_block(self) -> dict[str, Any]:
        return {"archived_ids": len(self.kept_ids), "history_rows": self.kept_history_rows,
                "ids": list(self.kept_ids[:MAX_REPORTED_KEPT_IDS]), "reason": KEPT_REASON if self.kept_ids else ""}


@dataclass(frozen=True, slots=True)
class ScenePurgeOffer:
    """Réponse du plan : le plan, et le jeton à rendre pour l'exécuter (`None` s'il n'y a rien à purger)."""

    plan: ScenePurgePlan
    confirmation: str | None
    issued_at: int
    expires_at: int | None

    def to_payload(self, *, epoch: str | None) -> dict[str, Any]:
        return {
            "scene_id": self.plan.scene_id, "epoch": epoch, "revision": self.plan.revision,
            "purgeable": {"archived_ids": len(self.plan.purge_ids), "history_rows": self.plan.history_rows},
            "kept": self.plan.kept_block(),
            "confirmation": self.confirmation, "expires_at": self.expires_at, "ttl_s": PURGE_CONFIRMATION_TTL_S,
        }


@dataclass(frozen=True, slots=True)
class ScenePurgeResult:
    """Issue d'une purge exécutée : comptes effacés, ids gardés, sauvegarde écrite avant."""

    scene_id: str
    revision: int
    purged_ids: int
    history_rows: int
    kept_ids: tuple[str, ...]
    kept_history_rows: int
    backup_path: str
    #: Base reconstruite (`VACUUM`) et `-wal` vidé : aucun reste des objets purgés hors de la sauvegarde.
    compacted: bool = True

    def to_payload(self, *, epoch: str | None) -> dict[str, Any]:
        kept = ScenePurgePlan(self.scene_id, self.revision, (), self.kept_ids, 0, self.kept_history_rows).kept_block()
        return {"scene_id": self.scene_id, "epoch": epoch, "revision": self.revision,
                "purged": {"archived_ids": self.purged_ids, "history_rows": self.history_rows},
                "kept": kept, "backup_path": self.backup_path, "compacted": self.compacted}


def plan_archive_purge(snapshot: SceneSnapshot, retained: Iterable[str], *, history_rows: int,
                       kept_history_rows: int) -> ScenePurgePlan:
    """Partager les pierres tombales entre purgées et gardées (`retained` : ids que le runtime suit encore)."""

    keep = frozenset(retained)
    kept = tuple(object_id for object_id in snapshot.archived_ids if object_id in keep)
    purge = tuple(object_id for object_id in snapshot.archived_ids if object_id not in keep)
    if history_rows < 0 or kept_history_rows < 0:
        raise ValueError("history row counts cannot be negative")
    return ScenePurgePlan(snapshot.scene_id, snapshot.revision, purge, kept, history_rows, kept_history_rows)


def purged_snapshot(snapshot: SceneSnapshot, plan: ScenePurgePlan) -> SceneSnapshot:
    """L'instantané après la purge : mêmes objets et liens, pierres tombales gardées seulement, révision suivante."""

    if (plan.scene_id, plan.revision) != (snapshot.scene_id, snapshot.revision):
        raise ValueError("the purge plan was made on another revision")
    return replace(snapshot, revision=snapshot.revision + 1, archived_ids=plan.kept_ids)


def purge_digest(secret: bytes, plan: ScenePurgePlan, *, epoch: str | None, expires_at: int) -> str:
    body = json.dumps({"s": plan.scene_id, "e": epoch, "ids": list(plan.purge_ids), "h": plan.history_rows,
                       "exp": expires_at}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def issue_purge_token(secret: bytes, plan: ScenePurgePlan, *, epoch: str | None, now_epoch: int) -> tuple[str | None, int | None]:
    """`(jeton, expiration)` ; `(None, None)` quand il n'y a rien à purger (aucune exécution à confirmer)."""

    if plan.empty:
        return None, None
    expires = now_epoch + PURGE_CONFIRMATION_TTL_S
    return f"{PURGE_TOKEN_PREFIX}{expires}.{purge_digest(secret, plan, epoch=epoch, expires_at=expires)}", expires


def check_purge_token(secret: bytes, plan: ScenePurgePlan, token: object, *, epoch: str | None, now_epoch: int) -> None:
    """Le jeton doit décrire **ce** plan et ne pas avoir expiré. Comparaison à temps constant."""

    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise ScenePurgeError(ScenePurgeCode.CONFIRMATION_REQUIRED,
                              "a purge needs the confirmation token of a plan: plan first, then confirm with confirmed=true")
    expires = int(token[len(PURGE_TOKEN_PREFIX):].split(".", 1)[0])
    expected = f"{PURGE_TOKEN_PREFIX}{expires}.{purge_digest(secret, plan, epoch=epoch, expires_at=expires)}"
    if plan.empty or not hmac.compare_digest(token, expected):
        raise ScenePurgeError(ScenePurgeCode.CONFIRMATION_STALE,
                              "the confirmation no longer matches what would be purged (an object was archived, the runtime "
                              "released one, or Core restarted): plan again and confirm what you see")
    if now_epoch > expires:
        raise ScenePurgeError(ScenePurgeCode.CONFIRMATION_STALE, "the confirmation expired: plan again")

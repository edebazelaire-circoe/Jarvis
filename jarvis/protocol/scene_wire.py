"""Forme HTTP du transport de la scène (handoff jarvis-constellation-scene-runtime, Slice 03).

Partagée par Core (`LocalProtocolServer`), son client (`LocalCoreClient`) et
le proxy du Control Center (`jarvis/runtime/scene_view.py`) : les bornes, les
codes d'erreur stables, la lecture des paramètres du long-poll et
l'encodage borné des réponses vivent en un seul endroit.

Décision 20 : instantané complet (`GET /v1/scene/snapshot`), puis patchs de
révision monotones (`GET /v1/scene/patches`), avec resynchronisation sur
saut, autre `scene_id` ou autre époque. Une route de patchs ne renvoie
jamais l'instantané.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
import re
from typing import Any

from aiohttp import web

from jarvis.domain.scene import SceneSnapshot, SceneUpdate
from jarvis.ports.scene import ScenePatchWindow

#: Corps d'une commande. Une charge vaut au plus 16 KiB en UTF-8 compact ;
#: échappée en ASCII (`\uXXXX`, paires de substitution) et avec ses autres
#: champs, elle reste sous 64 KiB. Au-delà : 413, rien n'est lu de plus.
MAX_SCENE_COMMAND_BYTES = 65_536
#: Budget d'une réponse de patchs. Un patch seul (une commande) pèse au plus
#: ~250 KiB ; au-delà du budget, la réponse s'arrête après le dernier patch
#: entier et dit `more: true`.
MAX_PATCH_RESPONSE_BYTES = 1_048_576
#: Lecture d'une réponse de scène par un client. Le pire instantané (512
#: objets à 16 KiB, 1 024 relations, 4 096 pierres tombales) tient sous 11 MiB
#: en UTF-8 compact.
MAX_SCENE_RESPONSE_BYTES = 16 * 1_048_576
#: Longueur d'un `scene_id` ou d'une époque reçus en paramètre.
MAX_TOKEN_CHARS = 128

#: Codes d'erreur stables (`error.code`).
SCENE_UNAVAILABLE = "scene_unavailable"
SCENE_PERSIST_FAILED = "scene_persist_failed"
SCENE_ACTOR_FORBIDDEN = "scene_actor_forbidden"
PAYLOAD_TOO_LARGE = "payload_too_large"
INVALID_REQUEST = "invalid_request"

_REVISION = re.compile(r"\A[0-9]{1,19}\Z")
_WAIT = re.compile(r"\A[0-9]{1,4}(?:\.[0-9]{1,6})?\Z")
_PATCH_QUERY_KEYS = frozenset({"scene_id", "epoch", "after", "wait_s"})


class SceneBodyTooLarge(Exception):
    """Corps de commande au-delà de `MAX_SCENE_COMMAND_BYTES` : 413, pas 400."""


@dataclass(frozen=True, slots=True)
class PatchQuery:
    scene_id: str
    epoch: str
    after: int
    wait_s: float


def compact_json(value: object) -> str:
    """JSON compact en UTF-8 réel : le texte non ASCII n'est pas gonflé en `\\uXXXX`."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _token(query: Mapping[str, str], name: str) -> str:
    value = query.get(name)
    if value is None:
        raise ValueError(f"{name} is required")
    if not value or len(value) > MAX_TOKEN_CHARS or value != value.strip():
        raise ValueError(f"{name} must be a non-empty identifier of at most {MAX_TOKEN_CHARS} characters")
    return value


def parse_patch_query(query: Any) -> PatchQuery:
    """Lire `scene_id`, `epoch`, `after` (entier ≥ 0) et `wait_s` (secondes, facultatif).

    `query` : un `MultiDictProxy` d'aiohttp. Clé inconnue ou répétée, valeur
    mal formée : `ValueError` (400). `wait_s` n'est pas borné ici : Core le
    borne (`MAX_REVISION_WAIT_S`), le Control Center applique sa propre borne.
    """

    keys = list(query.keys())
    unknown = set(keys) - _PATCH_QUERY_KEYS
    if unknown:
        raise ValueError(f"unexpected query parameter(s): {sorted(unknown)[:4]}")
    if len(keys) != len(set(keys)):
        raise ValueError("a query parameter is repeated")
    after = query.get("after")
    if after is None:
        raise ValueError("after is required")
    if not _REVISION.match(after):
        raise ValueError("after must be a non-negative integer")
    raw_wait = query.get("wait_s", "0")
    if not _WAIT.match(raw_wait):
        raise ValueError("wait_s must be a non-negative number of seconds")
    wait_s = float(raw_wait)
    if not math.isfinite(wait_s):
        raise ValueError("wait_s must be finite")
    return PatchQuery(_token(query, "scene_id"), _token(query, "epoch"), int(after), wait_s)


async def read_bounded_body(request: web.Request, limit: int = MAX_SCENE_COMMAND_BYTES) -> bytes:
    """Lire le corps sans jamais dépasser `limit` octets ; au-delà, `SceneBodyTooLarge`.

    La taille annoncée est refusée avant toute lecture ; un corps sans
    longueur (fragmenté) est coupé dès que la borne est franchie.
    """

    if request.content_length is not None and request.content_length > limit:
        raise SceneBodyTooLarge()
    raw = bytearray()
    async for chunk in request.content.iter_chunked(16_384):
        raw.extend(chunk)
        if len(raw) > limit:
            raise SceneBodyTooLarge()
    return bytes(raw)


def availability_block(availability: Any) -> dict[str, Any]:
    """`{state, code}` d'une `SceneAvailability` : ce que `/v1/health` et les erreurs 503 portent."""

    return {"state": availability.state.value, "code": availability.code.value if availability.code is not None else None}


def snapshot_body(snapshot: SceneSnapshot, epoch: str | None) -> str:
    """Réponse de `GET /v1/scene/snapshot`, encodée (appelée hors de la boucle : jusqu'à ~11 MiB)."""

    return compact_json({
        "scene_id": snapshot.scene_id,
        "epoch": epoch,
        "revision": snapshot.revision,
        "snapshot": snapshot.to_payload(),
    })


def patch_window_body(window: ScenePatchWindow, *, epoch: str | None, after: int) -> str:
    """Réponse de `GET /v1/scene/patches`, bornée à `MAX_PATCH_RESPONSE_BYTES`.

    `revision` est la révision atteinte en appliquant `patches` (celle de
    Core quand la réponse est complète ou demande une resynchronisation).
    `more: true` : le budget est atteint, le client applique ce qu'il a reçu
    et redemande aussitôt à partir de `revision`. Au moins un patch est
    toujours rendu, quelle que soit sa taille.
    """

    parts: list[str] = []
    size = 0
    reached = after if window.patches else window.revision
    for patch in window.patches:
        encoded = compact_json(patch.to_payload())
        cost = len(encoded.encode("utf-8")) + 1
        if parts and size + cost > MAX_PATCH_RESPONSE_BYTES:
            break
        parts.append(encoded)
        size += cost
        reached = patch.revision
    more = len(parts) < len(window.patches)
    head = compact_json({
        "scene_id": window.scene_id,
        "epoch": epoch,
        "revision": reached,
        "resync_required": window.resync_required,
        "more": more,
    })
    return f'{head[:-1]},"patches":[{",".join(parts)}]}}'


def command_body(update: SceneUpdate, *, epoch: str | None) -> dict[str, Any]:
    """Réponse 200 de `POST /v1/scene/commands` : l'issue du domaine, refus compris."""

    return {
        "outcome": update.outcome.value,
        "reason": update.reason.value if update.reason is not None else None,
        "scene_id": update.snapshot.scene_id,
        "epoch": epoch,
        "revision": update.snapshot.revision,
        "patch": update.patch.to_payload() if update.patch is not None else None,
    }


def error_body(code: str, message: str, **extra: Any) -> dict[str, Any]:
    """Forme d'erreur de la boucle locale : `{"error": {"code", "message", ...}}`."""

    return {"error": {"code": code, "message": message, **extra}}

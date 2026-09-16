"""Proxy de la scène constellation pour le Control Center (handoff jarvis-constellation-scene-runtime, Slice 03).

Core possède la scène (Décision 11). Le navigateur la lit et la commande
**par le Control Center**, jamais directement : il n'a pas le jeton de Core.

- `GET /api/scene` → `GET /v1/scene/snapshot` : instantané complet, validé ;
- `GET /api/scene/patches` → `GET /v1/scene/patches` : long-poll relayé,
  attente bornée ici aussi (un Core figé ne tient pas la page) ;
- `POST /api/scene/commands` → `POST /v1/scene/commands` : l'acteur est
  **toujours `user`**. Un corps sans acteur le reçoit ; un autre acteur est
  refusé (403) : le navigateur ne parle jamais au nom du cerveau.

Même forme dégradée que `GET /api/work` (`jarvis/runtime/work_view.py`) : Core
injoignable, réponse illisible ou scène indisponible sont dits tels quels
(`core_reachable`, `scene`, `error`), sans rien inventer. Le proxy ne garde
aucun état de scène : l'ordre des patchs, les sauts et les resynchronisations
sont l'affaire du client (`control_center_scene.js`).
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Protocol

from jarvis.domain.scene import SceneActor, SceneCommand, SceneCommandOutcome, ScenePatch, SceneSnapshot
from jarvis.protocol import scene_wire
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.runtime.agent_tasks import truncate
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.work_ingress import CoreWorkTransport
from jarvis.runtime.work_view import CORE_REFUSED, CORE_UNREACHABLE

SCENE_VIEW_SOURCE = "core"
#: Réponse de Core qui ne respecte pas le contrat du transport.
INVALID_SCENE_RESPONSE = "invalid_scene_response"
#: Commande partie sans réponse à l'échéance : son issue est inconnue.
CORE_TIMEOUT = "core_timeout"

#: Lecture de l'instantané (jusqu'à ~11 MiB au pire sur la boucle locale).
SNAPSHOT_TIMEOUT_S = 10.0
#: Attente maximale d'un long-poll relayé par le Control Center (Core borne à 30 s).
MAX_PATCH_WAIT_S = 25.0
#: Marge au-delà de l'attente demandée avant de déclarer Core injoignable.
PATCH_WAIT_GRACE_S = 5.0
#: Une commande écrit en une transaction SQLite (verrou ≤ 5 s côté Core).
COMMAND_TIMEOUT_S = 10.0

_SCENE_ERROR_CODES = frozenset({scene_wire.SCENE_UNAVAILABLE, scene_wire.SCENE_PERSIST_FAILED})


class SceneActorForbidden(Exception):
    """Corps de commande du navigateur portant un autre acteur que `user` : 403."""


class SceneTransport(Protocol):
    """Accès aux routes de scène de Core (`CoreSceneTransport` en production)."""

    async def scene_snapshot(self) -> dict[str, Any]: ...

    async def scene_patches(self, *, scene_id: str, epoch: str, after: int, wait_s: float, timeout_s: float) -> dict[str, Any]: ...

    async def scene_command(self, command: dict[str, Any]) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class CoreSceneTransport(CoreWorkTransport):
    """Transport de scène : même jeton relu à chaque connexion que `CoreWorkTransport`.

    Jeton refusé (Core redémarré) : relu, puis une seule nouvelle tentative.
    Rejouer une commande est sûr ici : un 401 est rendu avant que Core ne la lise.
    """

    async def scene_snapshot(self) -> dict[str, Any]:
        return await self._with_fresh_token(lambda client: client.scene_snapshot())

    async def scene_patches(self, *, scene_id: str, epoch: str, after: int, wait_s: float, timeout_s: float) -> dict[str, Any]:
        return await self._with_fresh_token(
            lambda client: client.scene_patches(scene_id=scene_id, epoch=epoch, after=after, wait_s=wait_s, timeout_s=timeout_s)
        )

    async def scene_command(self, command: dict[str, Any]) -> dict[str, Any]:
        return await self._with_fresh_token(lambda client: client.scene_command(command))

    async def _with_fresh_token(self, call: Callable[[LocalCoreClient], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        try:
            return await call(self._connect())
        except CoreProtocolError as exc:
            if exc.status != 401:
                raise
        await self.close()
        return await call(self._connect())


def _degraded(code: str, message: str, *, core_reachable: bool, scene: dict[str, Any] | None, **empty: Any) -> dict[str, Any]:
    return {
        "source": SCENE_VIEW_SOURCE,
        "core_reachable": core_reachable,
        "scene": scene,
        "scene_id": None,
        "epoch": None,
        "revision": None,
        **empty,
        "error": {"code": code, "message": message},
    }


def unavailable_snapshot_payload(code: str, message: str, *, core_reachable: bool = False, scene: dict[str, Any] | None = None) -> dict[str, Any]:
    """Réponse de `GET /api/scene` quand la scène n'est pas lisible : aucun instantané."""

    return _degraded(code, message, core_reachable=core_reachable, scene=scene, snapshot=None)


def unavailable_patches_payload(code: str, message: str, *, core_reachable: bool = False, scene: dict[str, Any] | None = None) -> dict[str, Any]:
    """Réponse de `GET /api/scene/patches` quand Core ne répond pas : aucun patch, pas de resynchronisation."""

    return _degraded(code, message, core_reachable=core_reachable, scene=scene, patches=[], resync_required=False, more=False)


def _require_text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"scene response has no {key}")
    return value


def _require_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"scene response has no valid {key}")
    return value


def decode_snapshot_response(raw: Any) -> dict[str, Any]:
    """Valider `GET /v1/scene/snapshot` ; seuls les champs déclarés survivent."""

    if not isinstance(raw, dict):
        raise TypeError("scene snapshot response must be an object")
    scene_id, epoch, revision = _require_text(raw, "scene_id"), _require_text(raw, "epoch"), _require_int(raw, "revision")
    snapshot = SceneSnapshot.from_payload(raw.get("snapshot"))
    if (snapshot.scene_id, snapshot.revision) != (scene_id, revision):
        raise ValueError("scene snapshot does not match its scene_id/revision")
    return {"scene_id": scene_id, "epoch": epoch, "revision": revision, "snapshot": snapshot.to_payload()}


def decode_patches_response(raw: Any, *, after: int) -> dict[str, Any]:
    """Valider `GET /v1/scene/patches` : patchs stricts et consécutifs à partir de `after + 1`."""

    if not isinstance(raw, dict):
        raise TypeError("scene patches response must be an object")
    scene_id, epoch, revision = _require_text(raw, "scene_id"), _require_text(raw, "epoch"), _require_int(raw, "revision")
    resync, more, items = raw.get("resync_required"), raw.get("more"), raw.get("patches")
    if not isinstance(resync, bool) or not isinstance(more, bool) or not isinstance(items, list):
        raise ValueError("scene patches response is malformed")
    patches = [ScenePatch.from_payload(item) for item in items]
    if resync and patches:
        raise ValueError("a resync response carries no patch")
    expected = after + 1
    for patch in patches:
        if patch.revision != expected:
            raise ValueError(f"scene patch {patch.revision} is not consecutive (expected {expected})")
        expected += 1
    if patches and patches[-1].revision != revision:
        raise ValueError("scene patches do not end at the announced revision")
    if not patches and not resync and revision != after:
        raise ValueError("an empty scene patch response must stay at the requested revision")
    return {
        "scene_id": scene_id,
        "epoch": epoch,
        "revision": revision,
        "patches": [patch.to_payload() for patch in patches],
        "resync_required": resync,
        "more": more,
    }


def user_command(body: Any) -> SceneCommand:
    """Commande du navigateur, acteur forcé à `user`.

    Sans `actor` : `user` est posé. `actor` présent et différent de `user` :
    `SceneActorForbidden` (403), jamais réécrit en silence. Forme invalide :
    `ValueError`/`TypeError` (400).
    """

    if not isinstance(body, dict):
        raise TypeError("scene command must be a JSON object")
    actor = body.get("actor", SceneActor.USER.value)
    if actor != SceneActor.USER.value:
        raise SceneActorForbidden("the Control Center only sends user commands")
    return SceneCommand.from_payload({**body, "actor": SceneActor.USER.value})


class CoreSceneView:
    """Relais sans état des routes de scène de Core vers le navigateur."""

    def __init__(
        self,
        transport: SceneTransport,
        *,
        journal: RuntimeJournal | None = None,
        snapshot_timeout_s: float = SNAPSHOT_TIMEOUT_S,
        command_timeout_s: float = COMMAND_TIMEOUT_S,
        max_patch_wait_s: float = MAX_PATCH_WAIT_S,
        patch_wait_grace_s: float = PATCH_WAIT_GRACE_S,
    ) -> None:
        if min(snapshot_timeout_s, command_timeout_s, patch_wait_grace_s) <= 0 or max_patch_wait_s < 0:
            raise ValueError("scene view timeouts must be positive")
        self.transport = transport
        self.journal = journal
        self.snapshot_timeout_s = snapshot_timeout_s
        self.command_timeout_s = command_timeout_s
        self.max_patch_wait_s = max_patch_wait_s
        self.patch_wait_grace_s = patch_wait_grace_s
        #: Codes d'indisponibilité déjà journalisés depuis la dernière lecture
        #: réussie : une panne de Core se lit une fois, pas à chaque sondage.
        self._down: set[str] = set()

    # ------------------------------------------------------------ lectures

    async def snapshot(self) -> dict[str, Any]:
        try:
            raw = await asyncio.wait_for(self.transport.scene_snapshot(), timeout=self.snapshot_timeout_s)
            body = await asyncio.to_thread(decode_snapshot_response, raw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - classé et journalisé par `_read_failure`
            code, message, reachable, scene = self._read_failure(exc, "snapshot", self.snapshot_timeout_s)
            return unavailable_snapshot_payload(code, message, core_reachable=reachable, scene=scene)
        self._restored("snapshot")
        return self._ready(body)

    async def patches(self, query: scene_wire.PatchQuery) -> dict[str, Any]:
        wait_s = min(query.wait_s, self.max_patch_wait_s)
        deadline = wait_s + self.patch_wait_grace_s
        try:
            raw = await asyncio.wait_for(
                self.transport.scene_patches(
                    scene_id=query.scene_id, epoch=query.epoch, after=query.after, wait_s=wait_s, timeout_s=deadline,
                ),
                # Seconde borne, indépendante du client HTTP : un Core figé ne
                # garde jamais la page au-delà de l'attente demandée + marge.
                timeout=deadline + 1.0,
            )
            body = decode_patches_response(raw, after=query.after)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - classé et journalisé par `_read_failure`
            code, message, reachable, scene = self._read_failure(exc, "patches", deadline)
            return unavailable_patches_payload(code, message, core_reachable=reachable, scene=scene)
        self._restored("patches")
        return self._ready(body)

    # ------------------------------------------------------------ commandes

    async def command(self, command: SceneCommand) -> tuple[int, dict[str, Any]]:
        """Relayer une commande `user` ; rend `(statut HTTP, corps)`.

        200 : issue du domaine (refus compris). 400/413 : refus de forme par
        Core. 503 : Core injoignable, scène indisponible ou écriture échouée.
        504 : pas de réponse à l'échéance, **issue inconnue** (la commande a
        pu être appliquée) : le client relit la scène. 502 : réponse illisible.
        """

        if command.actor is not SceneActor.USER:
            raise ValueError("the scene view relays user commands only")
        op = command.op.value
        try:
            raw = await asyncio.wait_for(self.transport.scene_command(command.to_payload()), timeout=self.command_timeout_s)
            body = self._decode_command(raw)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            message = f"Core n'a pas répondu en {self.command_timeout_s:g} s : issue inconnue, relire la scène."
            return self._command_failed(504, CORE_TIMEOUT, message, op=op, core_reachable=False)
        except CoreProtocolError as exc:
            return self._command_refused_by_core(exc, op=op)
        except (TypeError, ValueError) as exc:
            self._report_invalid(exc, "command")
            return self._command_failed(502, INVALID_SCENE_RESPONSE, f"Réponse de Core illisible : {truncate(str(exc), 160)}", op=op, core_reachable=True)
        except Exception as exc:  # noqa: BLE001 - Core arrêté, jeton absent, réseau
            detail = truncate(str(exc), 160) or type(exc).__name__
            return self._command_failed(503, CORE_UNREACHABLE, f"Core injoignable : {detail}", op=op, core_reachable=False)
        self._emit(
            "scene.command",
            f"commande de scène {op} : {body['outcome']}",
            data={"op": op, "outcome": body["outcome"], "reason": body["reason"], "revision": body["revision"]},
        )
        return 200, {"source": SCENE_VIEW_SOURCE, "core_reachable": True, **body, "error": None}

    @staticmethod
    def _decode_command(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise TypeError("scene command response must be an object")
        outcome = SceneCommandOutcome(raw.get("outcome"))
        reason = raw.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("scene command reason must be a string")
        patch = raw.get("patch")
        decoded = ScenePatch.from_payload(patch) if patch is not None else None
        revision = _require_int(raw, "revision")
        if (decoded is not None) != (outcome is SceneCommandOutcome.APPLIED):
            raise ValueError("an applied scene command carries exactly one patch")
        if decoded is not None and decoded.revision != revision:
            raise ValueError("scene command patch does not match its revision")
        return {
            "outcome": outcome.value,
            "reason": reason,
            "scene_id": _require_text(raw, "scene_id"),
            "epoch": _require_text(raw, "epoch"),
            "revision": revision,
            "patch": decoded.to_payload() if decoded is not None else None,
        }

    def _command_refused_by_core(self, exc: CoreProtocolError, *, op: str) -> tuple[int, dict[str, Any]]:
        if exc.code in _SCENE_ERROR_CODES:
            return self._command_failed(503, exc.code, _core_message(exc), op=op, core_reachable=True, scene=_scene_block(exc))
        if exc.status in (400, 413):
            return self._command_failed(exc.status, exc.code, _core_message(exc), op=op, core_reachable=True)
        return self._command_failed(502, CORE_REFUSED, f"Core a refusé la commande ({exc.status} {exc.code}).", op=op, core_reachable=True)

    def _command_failed(
        self, status: int, code: str, message: str, *, op: str, core_reachable: bool, scene: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        self._emit(
            "scene.command_failed",
            f"commande de scène {op} non relayée : {message}",
            level="warning",
            data={"op": op, "status": status, "code": code},
        )
        return status, {
            "source": SCENE_VIEW_SOURCE,
            "core_reachable": core_reachable,
            "scene": scene,
            "error": {"code": code, "message": message},
        }

    # ------------------------------------------------------------ diagnostic

    @staticmethod
    def _ready(body: dict[str, Any]) -> dict[str, Any]:
        return {"source": SCENE_VIEW_SOURCE, "core_reachable": True, "scene": {"state": "ready", "code": None}, **body, "error": None}

    def _read_failure(self, exc: Exception, what: str, timeout_s: float) -> tuple[str, str, bool, dict[str, Any] | None]:
        """Classer l'échec d'une lecture : `(code, message, core_reachable, scene)`, journalisé à la transition."""

        if isinstance(exc, CoreProtocolError) and exc.code in _SCENE_ERROR_CODES:
            result = (scene_wire.SCENE_UNAVAILABLE, _core_message(exc), True, _scene_block(exc))
        elif isinstance(exc, CoreProtocolError):
            result = (CORE_REFUSED, f"Core a refusé la lecture ({exc.status} {exc.code}).", True, None)
        elif isinstance(exc, TimeoutError):
            result = (CORE_UNREACHABLE, f"Core n'a pas répondu en {timeout_s:g} s.", False, None)
        elif isinstance(exc, (TypeError, ValueError)):
            self._report_invalid(exc, what)
            result = (INVALID_SCENE_RESPONSE, f"Réponse de scène de Core illisible : {truncate(str(exc), 160)}", True, None)
        else:
            detail = truncate(str(exc), 160) or type(exc).__name__
            result = (CORE_UNREACHABLE, f"Core injoignable : {detail}", False, None)
        code, message = result[0], result[1]
        if code not in self._down:
            self._down.add(code)
            self._emit(
                "scene.view_unavailable",
                f"Scène non lisible depuis le Control Center ({what}) : {message}",
                level="warning",
                data={"code": code, "read": what, "exception_type": type(exc).__name__},
            )
        return result

    def _restored(self, what: str) -> None:
        if not self._down:
            return
        codes, self._down = sorted(self._down), set()
        self._emit("scene.view_restored", f"Scène de nouveau lisible depuis le Control Center ({what})", data={"after": codes})

    def _report_invalid(self, exc: Exception, what: str) -> None:
        # Core a répondu hors contrat : défaut à corriger, en erreur (panneau ERR).
        self._emit(
            "scene.view_invalid_response",
            f"Réponse de scène de Core illisible ({what}).",
            level="error",
            data={"read": what, "exception_type": type(exc).__name__, "error": truncate(str(exc), 200)},
        )

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any]) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except Exception:  # noqa: BLE001 - même règle que `CoreWorkView` : un journal indisponible n'arrête pas le relais
            pass

    async def aclose(self) -> None:
        try:
            await self.transport.close()
        except Exception:  # noqa: BLE001 - l'arrêt du Control Center ne reste jamais bloqué
            pass


def _core_message(exc: CoreProtocolError) -> str:
    return truncate(exc.message, 200) or f"{exc.status} {exc.code}"


def _scene_block(exc: CoreProtocolError) -> dict[str, Any] | None:
    scene = exc.details.get("scene")
    if not isinstance(scene, dict) or not isinstance(scene.get("state"), str):
        return None
    code = scene.get("code")
    return {"state": scene["state"], "code": code if isinstance(code, str) else None}

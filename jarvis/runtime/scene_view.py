"""Proxy de la scène constellation pour le Control Center (handoff jarvis-constellation-scene-runtime, Slice 03).

Core possède la scène (Décision 11). Le navigateur la lit et la commande
**par le Control Center**, jamais directement : il n'a pas le jeton de Core.

- `GET /api/scene` → `GET /v1/scene/snapshot` : instantané complet, validé ;
- `GET /api/scene/patches` → `GET /v1/scene/patches` : long-poll relayé,
  attente bornée ici aussi (un Core figé ne tient pas la page) ;
- `POST /api/scene/commands` → `POST /v1/scene/commands` : l'acteur est
  **toujours `user`**. Un corps sans acteur le reçoit ; un autre acteur est
  refusé (403) : le navigateur ne parle jamais au nom du cerveau ;
- `POST /api/jobs/cancel` → `POST /v1/work/cancel` (Slice 08) : l'arrêt
  d'une étoile `job` depuis son menu. Toute autre source (sous-agent Claude)
  est refusée ici (409 `not_cancellable`), sans appeler Core : aucun arrêt
  individuel n'existe pour elle.

Même forme dégradée que `GET /api/work` (`jarvis/runtime/work_view.py`) : Core
injoignable, réponse illisible ou scène indisponible sont dits tels quels
(`core_reachable`, `scene`, `error`), sans rien inventer. Le proxy ne garde
aucun état de scène : l'ordre des patchs, les sauts et les resynchronisations
sont l'affaire du client (`control_center_scene.js`).

Charge (QA Slice 03) : les long-polls ont leur **propre pool de connexions**
vers Core, et leur nombre simultané est plafonné (`MAX_CONCURRENT_PATCH_WAITS`).
Au-delà, la réponse est immédiate (`patch_waits_busy`, `retry_after_ms`), sans
connexion tenue. Instantanés et commandes ne font donc jamais la queue derrière
des attentes longues.

Messages : ce qui part vers la page ne porte jamais de chemin de fichier
(`page_text`) ; le message complet reste dans le journal.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
import time
from typing import Any, Awaitable, Callable, Literal, Protocol

import aiohttp

from jarvis.domain.scene import MAX_SCENE_OBJECTS, SceneActor, SceneCommand, SceneCommandOutcome, SceneOp, ScenePatch, SceneSnapshot
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
#: Commande jamais partie (connexion à Core non obtenue) : rien n'a été appliqué.
COMMAND_NOT_SENT = "command_not_sent"
#: Trop de long-polls en cours dans ce Control Center : réessayer plus tard.
PATCH_WAITS_BUSY = "patch_waits_busy"

#: Lecture de l'instantané (jusqu'à ~11 MiB au pire sur la boucle locale).
SNAPSHOT_TIMEOUT_S = 10.0
#: Attente maximale d'un long-poll relayé par le Control Center (Core borne à 30 s).
MAX_PATCH_WAIT_S = 25.0
#: Marge au-delà de l'attente demandée avant de déclarer Core injoignable.
PATCH_WAIT_GRACE_S = 5.0
#: Une commande écrit en une transaction SQLite (verrou ≤ 5 s côté Core) :
#: délai de réponse une fois la requête partie.
COMMAND_TIMEOUT_S = 10.0
#: Arrêt d'un job (Slice 08) : Core attend jusqu'à 5 s la fin du job, plus le
#: nettoyage d'un job `back_brain` ; au-delà, issue inconnue.
WORK_CANCEL_TIMEOUT_S = 20.0
#: Seule source de travail qui s'arrête individuellement (`JOB_WORK_SOURCE` de Core).
CANCELLABLE_WORK_SOURCE = "job"
#: Refus : ce travail n'a pas d'arrêt individuel.
NOT_CANCELLABLE = "not_cancellable"
#: Issues d'arrêt que Core peut rendre.
WORK_CANCEL_OUTCOMES = frozenset({"cancelled", "cancel_requested", "cleanup_unknown", "already_terminal"})
#: Délai pour obtenir la connexion à Core. Au-delà, la commande n'est pas partie.
COMMAND_CONNECT_TIMEOUT_S = 3.0
#: Long-polls relayés en même temps. Au-delà : réponse immédiate `patch_waits_busy`.
MAX_CONCURRENT_PATCH_WAITS = 32
#: Délai conseillé au client avant de redemander quand le plafond est atteint.
PATCH_RETRY_AFTER_MS = 1_000
#: Fenêtre de limitation des avertissements répétitifs (acteur refusé, plafond atteint).
REPORT_WINDOW_S = 60.0

_PATH = re.compile(
    # C:\dossier avec espaces\fichier, C:/…, \\serveur\partage\… : dossiers avec espaces, nom de fichier sans.
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\(?=\w))(?:[^\\/\r\n\"'<>|:*?]*[\\/])*[^\s\\/\"'<>|:*?]*"
    # /home/…/fichier : au moins deux segments, jamais une URL (`http://…/api`).
    r"|(?<![\w.:/])/(?:[^\s'\"<>/:]+/)+[^\s'\"<>:]*"
)

_SCENE_ERROR_CODES = frozenset({scene_wire.SCENE_UNAVAILABLE, scene_wire.SCENE_PERSIST_FAILED})


class SceneActorForbidden(Exception):
    """Corps de commande du navigateur portant un autre acteur que `user` : 403.

    `actor` : la valeur reçue, résumée (au plus 40 caractères), pour le journal.
    """

    def __init__(self, actor: object) -> None:
        super().__init__("the Control Center only sends user commands")
        try:
            text = json.dumps(actor, ensure_ascii=False)
        except (TypeError, ValueError):
            text = type(actor).__name__
        self.actor = truncate(text, 40)


def page_text(text: str, limit: int = 200) -> str:
    """Texte destiné à la page : chemins de fichiers remplacés par `<chemin>`, longueur bornée."""

    return truncate(_PATH.sub("<chemin>", text), limit)


class ReportThrottle:
    """Au plus un rapport par clé par fenêtre ; le suivant dit combien ont été tus entre-temps.

    `admit(key)` rend `None` (taire) ou le nombre d'occurrences tues depuis le
    dernier rapport de cette clé. Clés bornées : au-delà de `max_keys`, tout
    est oublié (au pire un rapport de plus, jamais une mémoire qui grossit).
    """

    def __init__(self, window_s: float = REPORT_WINDOW_S, *, clock: Callable[[], float] = time.monotonic, max_keys: int = 64) -> None:
        self.window_s = window_s
        self.clock = clock
        self.max_keys = max_keys
        self._entries: dict[str, list[float]] = {}

    def admit(self, key: str) -> int | None:
        now = self.clock()
        entry = self._entries.get(key)
        if entry is not None and now - entry[0] < self.window_s:
            entry[1] += 1
            return None
        if entry is None and len(self._entries) >= self.max_keys:
            self._entries.clear()
        suppressed = int(entry[1]) if entry is not None else 0
        self._entries[key] = [now, 0]
        return suppressed


class SceneTransport(Protocol):
    """Accès aux routes de scène de Core (`CoreSceneTransport` en production)."""

    async def scene_snapshot(self) -> dict[str, Any]: ...

    async def scene_patches(self, *, scene_id: str, epoch: str, after: int, wait_s: float, timeout_s: float) -> dict[str, Any]: ...

    async def scene_command(self, command: dict[str, Any], *, connect_timeout_s: float, read_timeout_s: float) -> dict[str, Any]:
        """`aiohttp.ConnectionTimeoutError` : connexion non obtenue, commande **non envoyée**."""
        ...

    async def work_cancel(self, *, source: str, external_id: str, connect_timeout_s: float, read_timeout_s: float) -> dict[str, Any]:
        """`POST /v1/work/cancel` ; `aiohttp.ConnectionTimeoutError` : requête **non envoyée**."""
        ...

    async def close(self) -> None: ...


async def _with_fresh_token(transport: CoreWorkTransport, call: Callable[[LocalCoreClient], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    """Jeton refusé (Core redémarré) : relu, puis une seule nouvelle tentative.

    Rejouer est sûr, commande comprise : un 401 est rendu avant que Core ne lise le corps.
    """

    try:
        return await call(transport._connect())
    except CoreProtocolError as exc:
        if exc.status != 401:
            raise
    await transport.close()
    return await call(transport._connect())


class CoreSceneTransport(CoreWorkTransport):
    """Transport de scène : même jeton relu à chaque connexion que `CoreWorkTransport`.

    Deux connexions à Core : celle héritée (instantanés, commandes) et
    `_polls` (long-polls seulement). Chacune a son propre pool : des dizaines
    d'attentes longues n'occupent jamais une place dont une commande a besoin.
    """

    def __init__(self, *, host: str, port: int, token_file) -> None:  # noqa: ANN001 - même signature que le parent
        super().__init__(host=host, port=port, token_file=token_file)
        self._polls = CoreWorkTransport(host=host, port=port, token_file=token_file)

    async def scene_snapshot(self) -> dict[str, Any]:
        return await _with_fresh_token(self, lambda client: client.scene_snapshot())

    async def scene_patches(self, *, scene_id: str, epoch: str, after: int, wait_s: float, timeout_s: float) -> dict[str, Any]:
        return await _with_fresh_token(
            self._polls,
            lambda client: client.scene_patches(scene_id=scene_id, epoch=epoch, after=after, wait_s=wait_s, timeout_s=timeout_s),
        )

    async def scene_command(self, command: dict[str, Any], *, connect_timeout_s: float, read_timeout_s: float) -> dict[str, Any]:
        return await _with_fresh_token(
            self,
            lambda client: client.scene_command(command, connect_timeout_s=connect_timeout_s, read_timeout_s=read_timeout_s),
        )

    async def work_cancel(self, *, source: str, external_id: str, connect_timeout_s: float, read_timeout_s: float) -> dict[str, Any]:
        return await _with_fresh_token(
            self,
            lambda client: client.cancel_work(
                source=source, external_id=external_id, connect_timeout_s=connect_timeout_s, read_timeout_s=read_timeout_s,
            ),
        )

    async def close(self) -> None:
        try:
            await self._polls.close()
        finally:
            await super().close()


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


def decode_command_response(raw: Any) -> dict[str, Any]:
    """Valider `POST /v1/scene/commands` : issue, motif, révision et patch cohérents."""

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


def decode_work_cancel_response(raw: Any, *, source: str, external_id: str) -> dict[str, Any]:
    """Valider `POST /v1/work/cancel` : même travail, issue connue, statut textuel."""

    if not isinstance(raw, dict):
        raise TypeError("work cancel response must be an object")
    if raw.get("source") != source or raw.get("external_id") != external_id:
        raise ValueError("work cancel response names another work")
    outcome, status = raw.get("outcome"), raw.get("status")
    if outcome not in WORK_CANCEL_OUTCOMES or not isinstance(status, str) or not status:
        raise ValueError("work cancel response has no valid outcome/status")
    return {"source": source, "external_id": external_id, "outcome": outcome, "status": status}


@dataclass(frozen=True, slots=True)
class SceneCallFailure:
    """Échec classé d'un appel de scène à Core : ce que le proxy et les outils du cerveau en disent.

    `message` peut contenir un chemin de fichier (message de Core) : tout
    texte montré hors du journal passe par `page_text`.
    """

    status: int
    code: str
    message: str
    core_reachable: bool
    scene: dict[str, Any] | None = None
    #: Réponse de Core hors contrat (défaut à corriger, pas une panne).
    invalid_response: bool = False


#: Classes d'exceptions qu'un appel de scène à Core peut lever par le transport ;
#: toute autre est un défaut de l'appelant.
SCENE_CALL_ERRORS = (aiohttp.ClientError, OSError, TimeoutError, CoreProtocolError, TypeError, ValueError)


def core_error_text(exc: CoreProtocolError) -> str:
    """Message d'une erreur JSON de Core (`scene_unavailable`, 400/413 de Core).

    Jamais appelée sur un corps non JSON (code `http_<statut>`) : celui-là est
    classé `core_refused` avec statut et code seulement.
    """

    return exc.message or f"{exc.status} {exc.code}"


def classify_scene_call_failure(
    exc: BaseException, *, connect_timeout_s: float, read_timeout_s: float, call: Literal["command", "read"] = "command",
) -> SceneCallFailure:
    """Classement unique des échecs d'appel de scène (Control Center et `jarvis-display`).

    Codes : `command_not_sent` (connexion non obtenue : rien n'est parti),
    `core_timeout` (partie sans réponse : issue inconnue), `scene_unavailable`
    / `scene_persist_failed` (503 de Core), le code de Core pour 400/413,
    `core_refused` (autre refus HTTP), `invalid_scene_response` (hors
    contrat), `core_unreachable` (connexion refusée, ou liaison perdue en
    cours : issue inconnue pour une commande).
    """

    command = call == "command"
    if isinstance(exc, aiohttp.ConnectionTimeoutError):
        message = (f"Commande non envoyée : connexion à Core non obtenue en {connect_timeout_s:g} s. "
                   "Rien n'a été appliqué, réessayer est sûr." if command
                   else f"Connexion à Core non obtenue en {connect_timeout_s:g} s.")
        return SceneCallFailure(503, COMMAND_NOT_SENT if command else CORE_TIMEOUT, message, False)
    if isinstance(exc, TimeoutError):
        message = (f"Core n'a pas répondu en {read_timeout_s:g} s après l'envoi : issue inconnue, relire la scène." if command
                   else f"Core n'a pas répondu en {read_timeout_s:g} s.")
        return SceneCallFailure(504, CORE_TIMEOUT, message, False)
    if isinstance(exc, CoreProtocolError):
        text = core_error_text(exc)
        if exc.code in _SCENE_ERROR_CODES:
            return SceneCallFailure(503, exc.code, text, True, _scene_block(exc))
        if exc.status in (400, 413) and not exc.code.startswith("http_"):
            return SceneCallFailure(exc.status, exc.code, text, True)
        what = "la commande" if command else "la lecture"
        return SceneCallFailure(502, CORE_REFUSED, f"Core a refusé {what} ({exc.status} {exc.code}).", True)
    if isinstance(exc, (TypeError, ValueError)):
        return SceneCallFailure(502, INVALID_SCENE_RESPONSE, f"Réponse de Core illisible : {exc}", True, invalid_response=True)
    detail = str(exc) or type(exc).__name__
    if isinstance(exc, (aiohttp.ClientConnectorError, ConnectionError)):
        suffix = ", commande non envoyée" if command else ""
        return SceneCallFailure(503, CORE_UNREACHABLE, f"Core injoignable{suffix} : {detail}", False)
    if command:
        return SceneCallFailure(503, CORE_UNREACHABLE, f"Liaison à Core perdue ({detail}) : issue inconnue, relire la scène.", False)
    return SceneCallFailure(503, CORE_UNREACHABLE, f"Liaison à Core perdue ({detail}).", False)


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
        raise SceneActorForbidden(actor)
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
        command_connect_timeout_s: float = COMMAND_CONNECT_TIMEOUT_S,
        max_patch_wait_s: float = MAX_PATCH_WAIT_S,
        patch_wait_grace_s: float = PATCH_WAIT_GRACE_S,
        max_concurrent_waits: int = MAX_CONCURRENT_PATCH_WAITS,
        throttle: ReportThrottle | None = None,
    ) -> None:
        if min(snapshot_timeout_s, command_timeout_s, command_connect_timeout_s, patch_wait_grace_s) <= 0 or max_patch_wait_s < 0:
            raise ValueError("scene view timeouts must be positive")
        if max_concurrent_waits < 1:
            raise ValueError("max_concurrent_waits must be at least 1")
        self.transport = transport
        self.journal = journal
        self.snapshot_timeout_s = snapshot_timeout_s
        self.command_timeout_s = command_timeout_s
        self.command_connect_timeout_s = command_connect_timeout_s
        self.max_patch_wait_s = max_patch_wait_s
        self.patch_wait_grace_s = patch_wait_grace_s
        self.max_concurrent_waits = max_concurrent_waits
        self.throttle = throttle or ReportThrottle()
        #: Long-polls en cours vers Core (plafonnés par `max_concurrent_waits`).
        self.waiting = 0
        #: Codes d'indisponibilité déjà journalisés depuis la dernière lecture
        #: réussie : une panne de Core se lit une fois, pas à chaque sondage.
        self._down: set[str] = set()
        #: Lectures (`snapshot`, `patches`, `command`) dont la réponse hors
        #: contrat est déjà journalisée ; oublié au retour à la normale.
        self._invalid_reported: set[str] = set()

    @property
    def job_cancel_deadline_s(self) -> float:
        """Attente maximale d'un arrêt de job relayé (connexion + réponse + marge), montrée par la page."""

        return self.command_connect_timeout_s + WORK_CANCEL_TIMEOUT_S + 1.0

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
        if self.waiting >= self.max_concurrent_waits:
            return self._busy()
        self.waiting += 1
        try:
            return await self._relay_patches(query)
        finally:
            self.waiting -= 1

    def _busy(self) -> dict[str, Any]:
        """Plafond atteint : réponse immédiate, aucune connexion tenue ni ouverte vers Core."""

        suppressed = self.throttle.admit("patch_waits_busy")
        if suppressed is not None:
            self._emit(
                "scene.view_busy",
                f"{self.max_concurrent_waits} attentes de scène déjà en cours : nouvelle attente refusée, le client réessaie",
                level="warning",
                data={"limit": self.max_concurrent_waits, "suppressed": suppressed},
            )
        body = unavailable_patches_payload(
            PATCH_WAITS_BUSY,
            f"Trop d'attentes de scène en cours ({self.max_concurrent_waits}) : nouvel essai dans {PATCH_RETRY_AFTER_MS / 1000:g} s.",
        )
        # Core n'a pas été interrogé : on ne sait rien de lui.
        return {**body, "core_reachable": None, "retry_after_ms": PATCH_RETRY_AFTER_MS}

    async def _relay_patches(self, query: scene_wire.PatchQuery) -> dict[str, Any]:
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
        Core. 503 : Core injoignable ou connexion non obtenue en
        `command_connect_timeout_s` (`command_not_sent` : **rien n'est parti**,
        réessayer est sûr), scène indisponible ou écriture échouée. 504 : requête
        partie, pas de réponse en `command_timeout_s`, **issue inconnue** (la
        commande a pu être appliquée) : le client relit la scène. 502 : réponse
        illisible ou refus d'appel.
        """

        if command.actor is not SceneActor.USER:
            raise ValueError("the scene view relays user commands only")
        op = command.op.value
        try:
            raw = await asyncio.wait_for(
                self.transport.scene_command(
                    command.to_payload(), connect_timeout_s=self.command_connect_timeout_s, read_timeout_s=self.command_timeout_s,
                ),
                # Seconde borne : elle ne sait pas si la requête est partie, d'où « issue inconnue ».
                timeout=self.command_connect_timeout_s + self.command_timeout_s + 1.0,
            )
            body = decode_command_response(raw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - classé par `classify_scene_call_failure` ; inconnu = liaison perdue, issue inconnue
            failure = classify_scene_call_failure(
                exc, connect_timeout_s=self.command_connect_timeout_s, read_timeout_s=self.command_timeout_s,
            )
            if failure.invalid_response:
                self._report_invalid(exc, "command")
            return self._command_failed(failure.status, failure.code, failure.message, op=op,
                                        core_reachable=failure.core_reachable, scene=failure.scene)
        self._invalid_reported.discard("command")
        self._emit(
            "scene.command",
            f"commande de scène {op} : {body['outcome']}",
            data={"op": op, "outcome": body["outcome"], "reason": body["reason"], "revision": body["revision"]},
        )
        if command.op is SceneOp.ARCHIVE_MANY and body["patch"] is not None:
            # Slice 08, reprise QA : le patch d'un archivage groupé porte la forme
            # historique de chaque objet (jusqu'à ~8 Mio). La page ne s'en sert
            # pas : elle lit l'issue et la révision, le patch lui arrive par le
            # long-poll. Validé plus haut, puis omis ici (`patch_omitted`).
            body = {**body, "patch": None, "patch_omitted": True}
        return 200, {"source": SCENE_VIEW_SOURCE, "core_reachable": True, **body, "error": None}

    async def cancel_work(self, source: str, external_id: str) -> tuple[int, dict[str, Any]]:
        """Relayer l'arrêt d'une étoile `job` ; rend `(statut HTTP, corps)` (Slice 08).

        409 `not_cancellable` sans appeler Core pour toute autre source (un
        sous-agent Claude n'a pas d'arrêt individuel). 200 : issue de Core
        (`cancelled`, `cancel_requested`, `already_terminal`). 400/404/409 de
        Core relayés avec leur code. Échec d'appel : même classement que les
        commandes (`command_not_sent` = rien n'est parti, `core_timeout` =
        issue inconnue).
        """

        if source != CANCELLABLE_WORK_SOURCE:
            self._emit(
                "scene.work_cancel_refused",
                "arrêt refusé : ce travail n'a pas d'arrêt individuel",
                data={"source": truncate(str(source), 40), "code": NOT_CANCELLABLE},
            )
            return 409, {
                "source": SCENE_VIEW_SOURCE,
                "core_reachable": None,
                "error": {
                    "code": NOT_CANCELLABLE,
                    "message": "Ce travail n'a pas d'arrêt individuel : seuls les jobs Core s'arrêtent, pas un sous-agent Claude.",
                },
            }
        read_timeout_s = WORK_CANCEL_TIMEOUT_S
        try:
            raw = await asyncio.wait_for(
                self.transport.work_cancel(
                    source=source, external_id=external_id,
                    connect_timeout_s=self.command_connect_timeout_s, read_timeout_s=read_timeout_s,
                ),
                timeout=self.job_cancel_deadline_s,
            )
            body = decode_work_cancel_response(raw, source=source, external_id=external_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - refus de Core relayés, le reste classé par `classify_scene_call_failure`
            if isinstance(exc, CoreProtocolError) and exc.status in (400, 404, 409) and not exc.code.startswith("http_"):
                messages = {
                    404: "Core ne connaît pas ce job (déjà oublié, ou Core redémarré).",
                    409: "Core refuse cet arrêt : ce travail n'a pas d'arrêt individuel.",
                }
                return self._work_cancel_failed(
                    exc.status, exc.code, messages.get(exc.status, core_error_text(exc)), external_id=external_id, core_reachable=True,
                )
            failure = classify_scene_call_failure(exc, connect_timeout_s=self.command_connect_timeout_s, read_timeout_s=read_timeout_s)
            if failure.invalid_response:
                self._report_invalid(exc, "work_cancel")
            return self._work_cancel_failed(
                failure.status, failure.code, failure.message, external_id=external_id, core_reachable=failure.core_reachable,
            )
        self._emit(
            "scene.work_cancel",
            f"arrêt de job demandé depuis la scène : {body['outcome']}",
            data={"external_id": truncate(external_id, 128), "outcome": body["outcome"], "status": body["status"]},
        )
        return 200, {"source": SCENE_VIEW_SOURCE, "core_reachable": True, **body, "error": None}

    def _work_cancel_failed(
        self, status: int, code: str, message: str, *, external_id: str, core_reachable: bool,
    ) -> tuple[int, dict[str, Any]]:
        """Message complet au journal ; la page reçoit la version sans chemin (`page_text`)."""

        self._emit(
            "scene.work_cancel_failed",
            f"arrêt de job non abouti : {truncate(message, 500)}",
            level="warning",
            data={"external_id": truncate(external_id, 128), "status": status, "code": code, "error": truncate(message, 500)},
        )
        return status, {
            "source": SCENE_VIEW_SOURCE,
            "core_reachable": core_reachable,
            "error": {"code": code, "message": page_text(message) or code},
        }

    def _command_failed(
        self, status: int, code: str, message: str, *, op: str, core_reachable: bool, scene: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """`message` complet au journal ; la page n'en reçoit qu'une version sans chemin (`page_text`)."""

        self._emit(
            "scene.command_failed",
            f"commande de scène {op} non relayée : {truncate(message, 500)}",
            level="warning",
            data={"op": op, "status": status, "code": code, "error": truncate(message, 500)},
        )
        return status, {
            "source": SCENE_VIEW_SOURCE,
            "core_reachable": core_reachable,
            "scene": scene,
            "error": {"code": code, "message": page_text(message) or code},
        }

    # ------------------------------------------------------------ diagnostic

    @staticmethod
    def _ready(body: dict[str, Any]) -> dict[str, Any]:
        scene: dict[str, Any] = {"state": "ready", "code": None}
        snapshot = body.get("snapshot")
        if isinstance(snapshot, dict):
            # Saturation (Slice 04) : déduite de l'instantané validé, pour que
            # la page puisse dire « scène pleine — archiver ». Une réponse de
            # patchs n'a pas d'instantané : le bloc reste `{state, code}`.
            objects = len(snapshot["objects"])
            scene.update(saturated=objects >= MAX_SCENE_OBJECTS, objects=objects, object_limit=MAX_SCENE_OBJECTS)
        return {"source": SCENE_VIEW_SOURCE, "core_reachable": True, "scene": scene, **body, "error": None}

    def _read_failure(self, exc: Exception, what: str, timeout_s: float) -> tuple[str, str, bool, dict[str, Any] | None]:
        """Classer l'échec d'une lecture : `(code, message pour la page, core_reachable, scene)`.

        Journalisé à la transition seulement (message complet, chemins compris).
        """

        if isinstance(exc, CoreProtocolError) and exc.code in _SCENE_ERROR_CODES:
            code, message, reachable, scene = scene_wire.SCENE_UNAVAILABLE, exc.message or f"{exc.status} {exc.code}", True, _scene_block(exc)
        elif isinstance(exc, CoreProtocolError):
            code, message, reachable, scene = CORE_REFUSED, f"Core a refusé la lecture ({exc.status} {exc.code}).", True, None
        elif isinstance(exc, TimeoutError):
            code, message, reachable, scene = CORE_UNREACHABLE, f"Core n'a pas répondu en {timeout_s:g} s.", False, None
        elif isinstance(exc, (TypeError, ValueError)):
            self._report_invalid(exc, what)
            code, message, reachable, scene = INVALID_SCENE_RESPONSE, f"Réponse de scène de Core illisible : {exc}", True, None
        else:
            code, message, reachable, scene = CORE_UNREACHABLE, f"Core injoignable : {str(exc) or type(exc).__name__}", False, None
        if code not in self._down:
            self._down.add(code)
            self._emit(
                "scene.view_unavailable",
                f"Scène non lisible depuis le Control Center ({what}) : {truncate(message, 500)}",
                level="warning",
                data={"code": code, "read": what, "exception_type": type(exc).__name__, "error": truncate(message, 500)},
            )
        return code, page_text(message) or code, reachable, scene

    def _restored(self, what: str) -> None:
        self._invalid_reported.discard(what)
        if not self._down:
            return
        codes, self._down = sorted(self._down), set()
        self._invalid_reported.clear()
        self._emit("scene.view_restored", f"Scène de nouveau lisible depuis le Control Center ({what})", data={"after": codes})

    def _report_invalid(self, exc: Exception, what: str) -> None:
        # Core a répondu hors contrat : défaut à corriger, en erreur (panneau
        # ERR), une fois par lecture jusqu'au retour à la normale.
        if what in self._invalid_reported:
            return
        self._invalid_reported.add(what)
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


def _scene_block(exc: CoreProtocolError) -> dict[str, Any] | None:
    scene = exc.details.get("scene")
    if not isinstance(scene, dict) or not isinstance(scene.get("state"), str):
        return None
    code = scene.get("code")
    block: dict[str, Any] = {"state": scene["state"], "code": code if isinstance(code, str) else None}
    # Occupation (Slice 04), relayée seulement si Core l'a donnée et bien typée.
    saturated, objects, limit = scene.get("saturated"), scene.get("objects"), scene.get("object_limit")
    if isinstance(saturated, bool) and isinstance(limit, int) and not isinstance(limit, bool) and (
        objects is None or (isinstance(objects, int) and not isinstance(objects, bool))
    ):
        block.update(saturated=saturated, objects=objects, object_limit=limit)
    return block

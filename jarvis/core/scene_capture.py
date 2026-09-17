"""Courtier des captures visuelles de la scène (handoff jarvis-constellation-scene-runtime, Slice 09, partie 2).

Séquence (décision du PM après le spike) :

1. le cerveau (`scene_capture`, serveur `jarvis-display`) appelle
   `POST /v1/scene/captures` ; `request()` crée **une** demande en attente
   (identifiant aléatoire à usage unique, échéance 5 s) et réveille le long-poll
   des patchs ;
2. la réponse du long-poll porte `capture_request {id, remaining_ms}` ; le
   Control Center la relaie telle quelle, et seul l'onglet meneur visible dessine
   et envoie le PNG (`POST /api/scene/captures/<id>`, relayé en
   `PUT /v1/scene/captures/<id>`) ;
3. `complete()` valide l'identifiant (en attente, non échu), le PNG, range le
   fichier par le `SceneCaptureStore` injecté, applique la rétention et rend la
   main à la demande du cerveau.

Aucune page ne répond avant l'échéance : `no_visible_page`. Une seconde demande
pendant qu'une autre attend : `capture_busy`. Une demande encore en attente est
redonnée au long-poll au plus une fois par `CAPTURE_REDELIVER_S` (passation de
meneur) ; un lecteur court (`wait_s = 0`, suiveur) ne la reçoit jamais.

Le journal ne porte que des identifiants courts, tailles et durées.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import secrets
import time
from typing import Any

from jarvis.domain.scene_capture import (
    CAPTURE_BUSY,
    CAPTURE_CANCELLED,
    CAPTURE_DEADLINE_S,
    CAPTURE_EXPIRED,
    CAPTURE_KEEP_FILES,
    CAPTURE_MAX_AGE_S,
    CAPTURE_REDELIVER_S,
    CAPTURE_STORE_FAILED,
    CAPTURE_UNAVAILABLE,
    INVALID_PNG,
    NO_VISIBLE_PAGE,
    UNKNOWN_CAPTURE,
    check_capture_id,
    png_dimensions,
)
from jarvis.ports.scene import SceneCaptureStore
from jarvis.ports.v2 import DiagnosticSink


class SceneCaptureError(Exception):
    """Refus ou échec d'une capture : `code` stable et statut HTTP de la route."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(slots=True)
class _Pending:
    capture_id: str
    created: float
    deadline: float
    result: asyncio.Future
    last_delivered: float = float("-inf")
    deliveries: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def _short(capture_id: str) -> str:
    """Préfixe journalisé : assez pour relier les lignes, jamais l'identifiant entier (capacité d'envoi)."""

    return capture_id[:8]


class SceneCaptureBroker:
    def __init__(
        self,
        store: SceneCaptureStore | None,
        *,
        diagnostics: DiagnosticSink | None = None,
        deadline_s: float = CAPTURE_DEADLINE_S,
        redeliver_s: float = CAPTURE_REDELIVER_S,
        keep_files: int = CAPTURE_KEEP_FILES,
        max_age_s: float = CAPTURE_MAX_AGE_S,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.diagnostics = diagnostics
        self.deadline_s = deadline_s
        self.redeliver_s = redeliver_s
        self.keep_files = keep_files
        self.max_age_s = max_age_s
        self.wall_clock = wall_clock
        self._pending: _Pending | None = None
        self._wake: asyncio.Event | None = None
        self._closed = False

    @property
    def available(self) -> bool:
        return self.store is not None and not self._closed

    # ------------------------------------------------------------ cycle de vie

    async def start(self) -> None:
        """Rétention au démarrage de Core. Ne lève pas : un dossier illisible se journalise."""

        self._closed = False
        await self._prune("start")

    def close(self) -> None:
        """Arrêt de Core : la demande en attente échoue aussitôt (`capture_cancelled`)."""

        self._closed = True
        pending, self._pending = self._pending, None
        if pending is not None and not pending.result.done():
            pending.result.set_exception(SceneCaptureError(CAPTURE_CANCELLED, "Core s'arrête : capture abandonnée.", 503))
        self._set_wake()

    # ------------------------------------------------------------ demande du cerveau

    async def request(self) -> dict[str, Any]:
        """Créer la demande et attendre le PNG rangé, au plus `deadline_s`."""

        if not self.available:
            raise SceneCaptureError(CAPTURE_UNAVAILABLE, "Capture de scène non configurée dans Core.", 503)
        if self._pending is not None:
            self._emit("core.scene.capture_refused", "capture refusée : une autre est en cours", level="info",
                       data={"code": CAPTURE_BUSY, "pending": _short(self._pending.capture_id)})
            raise SceneCaptureError(CAPTURE_BUSY, "Une capture est déjà en cours : réessaie dans quelques secondes.", 409)
        loop = asyncio.get_running_loop()
        now = loop.time()
        pending = _Pending(secrets.token_urlsafe(24), now, now + self.deadline_s, loop.create_future())
        self._pending = pending
        self._emit("core.scene.capture_requested", "capture de scène demandée",
                   data={"capture": _short(pending.capture_id), "deadline_ms": round(self.deadline_s * 1000)})
        self._set_wake()
        try:
            return await asyncio.wait_for(asyncio.shield(pending.result), timeout=self.deadline_s)
        except TimeoutError:
            self._emit("core.scene.capture_timeout", "aucune page visible n'a rendu la capture à temps", level="warning",
                       data={"code": NO_VISIBLE_PAGE, "capture": _short(pending.capture_id), "deliveries": pending.deliveries,
                             "waited_ms": round((loop.time() - now) * 1000)})
            raise SceneCaptureError(
                NO_VISIBLE_PAGE,
                f"Aucune page visible du Control Center n'a rendu la capture en {self.deadline_s:g} s "
                "(page fermée, onglet caché, ou scène éteinte).",
                504,
            ) from None
        finally:
            if self._pending is pending:
                self._pending = None
            if not pending.result.done():
                pending.result.cancel()

    # ------------------------------------------------------------ long-poll

    def wake_event(self) -> asyncio.Event:
        """Événement levé à la prochaine demande (ou à l'arrêt) ; à prendre avant `delivery_due()`."""

        if self._wake is None:
            self._wake = asyncio.Event()
        return self._wake

    def _set_wake(self) -> None:
        if self._wake is not None:
            self._wake.set()
        self._wake = None

    def delivery_due(self) -> float | None:
        """Secondes avant que la demande en attente soit (re)donnée au long-poll ; `None` sans demande."""

        pending = self._pending
        if pending is None:
            return None
        now = asyncio.get_running_loop().time()
        if now >= pending.deadline:
            return None
        return max(0.0, pending.last_delivered + self.redeliver_s - now)

    def deliver(self, *, long_poll: bool) -> dict[str, Any] | None:
        """`capture_request` à joindre à une réponse de patchs, ou `None`.

        Seul un long-poll (le meneur) le reçoit, et seulement quand il est dû :
        une réponse sans patch ne rejoue pas la demande en boucle.
        """

        pending = self._pending
        if pending is None or not long_poll:
            return None
        now = asyncio.get_running_loop().time()
        if now >= pending.deadline or now < pending.last_delivered + self.redeliver_s:
            return None
        pending.last_delivered = now
        pending.deliveries += 1
        return {"id": pending.capture_id, "remaining_ms": max(0, round((pending.deadline - now) * 1000))}

    # ------------------------------------------------------------ envoi de la page

    async def complete(self, capture_id: str, data: bytes) -> dict[str, Any]:
        """Ranger le PNG d'une demande en attente ; rend `{capture_id, name, path, bytes, width, height, duration_ms}`."""

        try:
            check_capture_id(capture_id)
        except ValueError as exc:
            raise SceneCaptureError(UNKNOWN_CAPTURE, str(exc), 404) from None
        pending = self._pending
        loop = asyncio.get_running_loop()
        if pending is None or pending.capture_id != capture_id or pending.result.done():
            self._emit("core.scene.capture_upload_refused", "envoi de capture refusé : identifiant inconnu ou déjà utilisé",
                       level="warning", data={"code": UNKNOWN_CAPTURE, "capture": _short(capture_id)})
            raise SceneCaptureError(UNKNOWN_CAPTURE, "Aucune capture en attente avec cet identifiant (inconnue, déjà rendue ou échue).", 404)
        if loop.time() >= pending.deadline:
            raise SceneCaptureError(CAPTURE_EXPIRED, "Capture échue : trop tard.", 410)
        try:
            width, height = png_dimensions(data)
        except ValueError as exc:
            self._emit("core.scene.capture_upload_refused", "envoi de capture refusé : PNG invalide", level="warning",
                       data={"code": INVALID_PNG, "capture": _short(capture_id), "bytes": len(data)})
            raise SceneCaptureError(INVALID_PNG, str(exc), 400) from None
        assert self.store is not None
        try:
            stored = await asyncio.to_thread(self.store.save, bytes(data), now_epoch_s=self.wall_clock())
        except OSError as exc:
            self._emit("core.scene.capture_store_failed", f"capture non rangée : {type(exc).__name__}", level="error",
                       data={"code": CAPTURE_STORE_FAILED, "capture": _short(capture_id), "error": type(exc).__name__})
            error = SceneCaptureError(CAPTURE_STORE_FAILED, f"Capture non rangée ({type(exc).__name__}).", 500)
            if not pending.result.done():
                pending.result.set_exception(SceneCaptureError(CAPTURE_STORE_FAILED, str(error), 500))
            raise error from None
        duration_ms = round((loop.time() - pending.created) * 1000)
        result = {"capture_id": capture_id, "name": stored.name, "path": stored.path, "bytes": stored.size,
                  "width": width, "height": height, "duration_ms": duration_ms}
        if not pending.result.done():
            pending.result.set_result(result)
        self._emit("core.scene.capture_stored", "capture de scène rangée", data={
            "capture": _short(capture_id), "name": stored.name, "bytes": stored.size, "width": width, "height": height,
            "duration_ms": duration_ms, "deliveries": pending.deliveries})
        await self._prune("capture")
        return result

    # ------------------------------------------------------------ outils

    async def _prune(self, where: str) -> None:
        if self.store is None:
            return
        try:
            removed = await asyncio.to_thread(self.store.prune, now_epoch_s=self.wall_clock(), keep=self.keep_files,
                                              max_age_s=self.max_age_s)
        except OSError as exc:
            self._emit("core.scene.capture_prune_failed", f"rétention des captures impossible : {type(exc).__name__}",
                       level="warning", data={"where": where, "error": type(exc).__name__})
            return
        if removed:
            self._emit("core.scene.capture_pruned", f"{removed} capture(s) supprimée(s)", data={"where": where, "removed": removed})

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self.diagnostics is None:
            return
        try:
            self.diagnostics.emit(kind, message, level=level, data=data)
        except OSError:
            pass  # intentional: a full disk must not fail a capture that already succeeded or refused cleanly

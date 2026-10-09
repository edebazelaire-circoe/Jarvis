"""Service du Studio Remotion optionnel (Slice 11 ; `docs/remotion-studio.md`).

Un seul Studio par profil d'exécution (jamais un par présentation), lancé SEULEMENT sur demande explicite (`open`), jamais par
l'aperçu ni au démarrage de Core. Il ne sert que le dossier de travail matérialisé depuis UNE version de prefab Remotion
(`StudioPin`) ; l'écriture vers la bibliothèque passe par `PrefabService`, jamais par ce service. États : `stopped`,
`starting`, `ready`, `stopping`, `failed` (avec code stable et diagnostics). Opérations : `open` (réutilise l'hôte vivant, change de
scène en place), `sync` (rechargement à chaud d'une nouvelle version), `close`, `restart`, `status`. Un délai d'inactivité
(aucune requête, aucun WebSocket ouvert) arrête le Studio ; un processus disparu devient `failed` / `process_exited`.

Les effets (fichiers, processus) sont dans un `StudioRunner` (port) ; la source vient d'un `source_provider` injecté.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import time
from typing import Any

from jarvis.domain import remotion_studio as D
from jarvis.domain.local_capabilities import bound_detail
from jarvis.domain.remotion_source import RemotionSource
from jarvis.domain.remotion_studio import StudioError, StudioErrorCode as C, StudioPin, StudioState, StudioStatus as S
from jarvis.ports.remotion_studio import StudioRunner
from jarvis.ports.v2 import DiagnosticSink

#: `(pin) -> (source, props d'exemple)` ; lève `StudioError(SOURCE_UNAVAILABLE)` si la version n'est pas une source Remotion saine.
SourceProvider = Callable[[StudioPin], Awaitable[tuple[RemotionSource, Mapping[str, Any]]]]
TICK_S = 15.0
RUNNABLE_CAPABILITY = ("ready", "running")


class RemotionStudioService:
    def __init__(self, runner: StudioRunner, *, source_provider: SourceProvider, capability_status: Callable[[], str],
                 diagnostics: DiagnosticSink | None = None, idle_timeout_s: float = D.DEFAULT_IDLE_TIMEOUT_S,
                 clock: Callable[[], float] = time.time, tick_s: float = TICK_S) -> None:
        self._runner = runner
        self._source = source_provider
        self._capability_status = capability_status
        self._diagnostics = diagnostics
        self._idle_timeout_s = D.parse_idle_timeout(idle_timeout_s)
        self._clock = clock
        self._tick_s = tick_s
        self._lock = asyncio.Lock()
        self._state: StudioState | None = None
        self._watch: asyncio.Task | None = None

    # ------------------------------------------------------------------ journal et persistance

    def _emit(self, kind: str, message: str, *, level: str = "info", **data: Any) -> None:
        if self._diagnostics is not None:
            self._diagnostics.emit(f"remotion_studio.{kind}", message, level=level, data=data)

    def _note(self, state: StudioState, line: str) -> None:
        state.diagnostics.append(bound_detail(line))
        del state.diagnostics[:-D.MAX_DIAGNOSTIC_LINES]

    def _load(self) -> StudioState:
        if self._state is None:
            try:
                raw = self._runner.read_state()
                self._state = StudioState.from_payload(raw) if raw else StudioState()
            except (StudioError, ValueError, KeyError) as exc:
                # État illisible : jamais deviné ni réécrit sans le dire. On repart arrêté ; le fichier est remplacé à la prochaine écriture.
                self._state = StudioState()
                self._emit("state_unreadable", f"Studio state ignored: {type(exc).__name__}", level="warning")
        return self._state

    def _save(self, state: StudioState) -> None:
        self._state = state
        self._runner.write_state(state.to_payload())

    def _fail(self, state: StudioState, code: C, detail: str, *, stop_reason: str = "") -> StudioState:
        state.status = S.FAILED
        state.last_error_code, state.last_error_detail = code.value, bound_detail(detail)
        state.stop_reason = stop_reason
        state.diagnostics = [bound_detail(line) for line in self._runner.log_tail(6)] or state.diagnostics
        state.port = None
        state.process_ref, state.launch_id = "", ""
        self._cancel_watch()
        try:
            self._save(state)
        except StudioError as exc:
            self._emit("state_write_failed", f"Studio state not written: {exc.code.value}", level="error")
        self._emit("failed", f"Studio failed: {code.value}", level="error", code=code.value, detail=state.last_error_detail)
        return state

    # ------------------------------------------------------------------ vue

    def _configured_port(self) -> int | None:
        try:
            return self._runner.configured_port()
        except StudioError:
            return None

    def _view(self, state: StudioState) -> dict[str, Any]:
        return D.public_view(state, idle_timeout_s=self._idle_timeout_s, now=self._clock(), configured_port=self._configured_port())

    def _refresh(self, state: StudioState) -> None:
        """Rend `state` conforme au processus (vivant ? actif ? fichiers modifiés ?). Lecture seule hors constat d'une disparition."""

        if state.status is not S.READY:
            return
        if not self._runner.is_alive(state.process_ref):
            self._fail(state, C.PROCESS_EXITED, "the Studio process is gone (closed outside Jarvis or crashed)")
            return
        activity = self._runner.activity(state.launch_id)
        last_ms = activity.get("last_ms")
        if isinstance(last_ms, (int, float)) and not isinstance(last_ms, bool):
            state.last_activity_at = max(state.ready_at or 0.0, state.synced_at or 0.0, float(last_ms) / 1000.0)
        elif state.last_activity_at is None:
            state.last_activity_at = state.ready_at
        ws = activity.get("ws_open")
        state.ws_open = ws if type(ws) is int and ws >= 0 else 0
        blocked = activity.get("blocked_egress")
        state.egress_blocked = blocked if type(blocked) is int and blocked >= 0 else 0
        state.modified_files = list(self._runner.modified_work())

    # ------------------------------------------------------------------ lecture

    async def status(self) -> dict[str, Any]:
        state = self._load()
        if not self._lock.locked():
            await asyncio.to_thread(self._refresh, state)
        return self._view(state)

    # ------------------------------------------------------------------ verrou

    def _acquire(self) -> None:
        if self._lock.locked():
            raise StudioError(C.BUSY, "another Studio operation is in progress")

    async def _prepare(self, pin: StudioPin) -> tuple[dict[str, bytes], RemotionSource]:
        try:
            source, props = await self._source(pin)
        except StudioError:
            raise
        except Exception as exc:  # noqa: BLE001 - la cause réelle est dite, jamais « indisponible » générique
            code = getattr(exc, "code", None)
            raise StudioError(C.SOURCE_UNAVAILABLE, f"{pin.prefab_id}@{pin.version}: {getattr(code, 'value', type(exc).__name__)}: {exc}") from None
        return D.plan_workspace(source, props), source

    # ------------------------------------------------------------------ open

    async def open(self, pin: StudioPin) -> dict[str, Any]:
        """Ouvre le Studio sur `pin` (demande explicite). Déjà vivant : réutilisé (même scène) ou rechargé à chaud (autre scène)."""

        self._acquire()
        async with self._lock:
            state = self._load()
            await asyncio.to_thread(self._refresh, state)
            if state.status is S.READY:
                if await asyncio.to_thread(self._healthy, state):
                    if state.pin == pin:
                        self._touch(state)
                        self._emit("reused", "Studio already open on this scene", prefab_id=pin.prefab_id, version=pin.version)
                        return {**self._view(state), "reused": True}
                    await self._sync_locked(state, pin)
                    return {**self._view(state), "reused": True}
                await asyncio.to_thread(self._kill, state)
                self._fail(state, C.HEALTH_FAILED, "the Studio did not answer; it was stopped and is restarted")
            await self._start_locked(state, pin)
            return self._view(state)

    def _touch(self, state: StudioState) -> None:
        state.last_activity_at = self._clock()

    def _healthy(self, state: StudioState) -> bool:
        try:
            self._runner.probe(state.port or 0, state.launch_id)
            return True
        except StudioError:
            return False

    def _kill(self, state: StudioState) -> None:
        try:
            self._runner.stop(state.process_ref)
        except StudioError as exc:
            self._note(state, f"{exc.code.value}: {exc.detail}")

    async def _start_locked(self, state: StudioState, pin: StudioPin) -> None:
        runtime_status = await asyncio.to_thread(self._capability_status)
        if runtime_status not in RUNNABLE_CAPABILITY:
            raise StudioError(C.RUNTIME_UNAVAILABLE, f"the Remotion capability is '{runtime_status}': install or repair it first "
                                                    "(POST /v1/local-capabilities/remotion/install|repair)")
        reason = await asyncio.to_thread(self._runner.runtime_ready)
        if reason:
            raise StudioError(C.RUNTIME_UNAVAILABLE, reason)
        files, source = await self._prepare(pin)  # un refus ici ne change PAS l'état (rien n'a démarré)
        state.status, state.pin = S.STARTING, pin
        state.source_digest, state.workspace_digest = source.digest, D.workspace_digest(files)
        state.composition = source.block.composition.to_dict()
        state.last_error_code = state.last_error_detail = state.stop_reason = ""
        state.started_at, state.ready_at, state.synced_at = self._clock(), None, None
        state.syncs = 0  # par lancement : « rafraîchie N fois » ne compte que ce Studio-ci
        state.diagnostics, state.modified_files = [], []
        await asyncio.to_thread(self._save, state)
        self._emit("starting", "Studio starting", prefab_id=pin.prefab_id, version=pin.version)
        try:
            report = await asyncio.to_thread(self._runner.sync_work, files)
            if report.edits_saved:
                state.edits_saved += len(report.edits_saved)
                self._note(state, f"{len(report.edits_saved)} file(s) edited outside Jarvis were saved aside before the refresh")
            launched = await asyncio.to_thread(self._launch_with_retry)
        except StudioError as exc:
            self._fail(state, exc.code, exc.detail)
            return
        except Exception as exc:  # noqa: BLE001 - jamais un échec muet : code interne + journal
            self._emit("start_crashed", f"Studio start raised {type(exc).__name__}", level="error")
            self._fail(state, C.INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
            return
        now = self._clock()
        state.status, state.port, state.process_ref, state.launch_id = S.READY, launched.port, launched.process_ref, launched.launch_id
        state.ready_at = state.last_activity_at = now
        state.diagnostics = []
        await asyncio.to_thread(self._save, state)
        self._start_watch()
        self._emit("ready", "Studio ready", port=launched.port, prefab_id=pin.prefab_id, version=pin.version,
                   seconds=round(now - (state.started_at or now), 1))

    def _guard_idle_s(self) -> float:
        return self._idle_timeout_s + D.IDLE_GUARD_MARGIN_S

    def _launch_with_retry(self):
        configured = self._runner.configured_port()
        try:
            return self._runner.launch(port=configured, idle_s=self._guard_idle_s())
        except StudioError as exc:
            if configured is not None or exc.code not in (C.PORT_UNAVAILABLE, C.HEALTH_FAILED):
                raise
            self._emit("port_retry", "Studio port collision: retrying once with another free port", level="warning", code=exc.code.value)
            return self._runner.launch(port=None, idle_s=self._guard_idle_s())

    # ------------------------------------------------------------------ sync (rechargement à chaud)

    async def sync(self, pin: StudioPin | None = None) -> dict[str, Any]:
        """Rematérialise la source (même scène relue, ou autre version/scène) : le serveur de développement recharge à chaud."""

        self._acquire()
        async with self._lock:
            state = self._load()
            await asyncio.to_thread(self._refresh, state)
            if state.status is not S.READY or state.pin is None:
                raise StudioError(C.NOT_RUNNING, "the Studio is not open: open it first")
            await self._sync_locked(state, pin or state.pin)
            return self._view(state)

    async def _sync_locked(self, state: StudioState, pin: StudioPin) -> None:
        files, source = await self._prepare(pin)
        try:
            report = await asyncio.to_thread(self._runner.sync_work, files)
        except StudioError as exc:
            self._note(state, f"{exc.code.value}: {exc.detail}")
            self._emit("sync_failed", f"Studio sync failed: {exc.code.value}", level="error", code=exc.code.value)
            await asyncio.to_thread(self._save, state)
            raise
        state.pin, state.source_digest, state.workspace_digest = pin, source.digest, D.workspace_digest(files)
        state.composition = source.block.composition.to_dict()
        state.synced_at, state.syncs = self._clock(), state.syncs + 1
        state.last_activity_at = state.synced_at
        if report.edits_saved:
            state.edits_saved += len(report.edits_saved)
            self._note(state, f"{len(report.edits_saved)} file(s) edited outside Jarvis were saved aside before the refresh")
        state.modified_files = []
        await asyncio.to_thread(self._save, state)
        self._emit("synced", "Studio work copy refreshed (hot reload)", prefab_id=pin.prefab_id, version=pin.version,
                   written=report.written, removed=report.removed, unchanged=report.unchanged)

    # ------------------------------------------------------------------ close / restart

    async def close(self, *, reason: str = "user") -> dict[str, Any]:
        self._acquire()
        async with self._lock:
            state = self._load()
            await self._close_locked(state, reason)
            return self._view(state)

    async def _close_locked(self, state: StudioState, reason: str) -> None:
        if state.status in (S.STOPPED,):
            return
        self._cancel_watch()
        state.status = S.STOPPING
        await asyncio.to_thread(self._save, state)
        try:
            if state.process_ref:
                saved = await asyncio.to_thread(self._runner.save_modified)
                if saved:
                    state.edits_saved += len(saved)
                    self._note(state, f"{len(saved)} file(s) edited in the Studio were saved aside (never written to the prefab library)")
                await asyncio.to_thread(self._runner.stop, state.process_ref)
        except StudioError as exc:
            self._fail(state, exc.code, exc.detail)
            return
        state.status, state.port, state.process_ref, state.launch_id = S.STOPPED, None, "", ""
        state.stop_reason, state.ws_open, state.modified_files = reason, 0, []
        state.last_error_code = state.last_error_detail = ""
        await asyncio.to_thread(self._save, state)
        self._emit("stopped", "Studio stopped", reason=reason)

    async def restart(self) -> dict[str, Any]:
        self._acquire()
        async with self._lock:
            state = self._load()
            pin = state.pin
            if pin is None:
                raise StudioError(C.NOT_RUNNING, "there is no scene to reopen: open the Studio on a scene first")
            restarts = state.restarts + 1
            if state.status is not S.FAILED or state.process_ref:
                await self._close_locked(state, "restart")
            if state.status is S.FAILED:
                state.status = S.STOPPED
            state.restarts = restarts
            await self._start_locked(state, pin)
            return self._view(state)

    # ------------------------------------------------------------------ surveillance (inactivité, disparition)

    def _start_watch(self) -> None:
        self._cancel_watch()
        try:
            self._watch = asyncio.get_running_loop().create_task(self._watch_loop(), name="remotion-studio-watch")
        except RuntimeError:
            self._watch = None

    def _cancel_watch(self) -> None:
        """Annule la surveillance ; sûr depuis un thread (`_refresh` tourne dans `to_thread`)."""

        task, self._watch = self._watch, None
        try:
            current = asyncio.current_task()
        except RuntimeError:  # appelé depuis un thread : aucune tâche courante
            current = None
        if task is not None and task is not current:  # la surveillance qui s'arrête elle-même ne s'annule pas (elle sort seule)
            try:
                task.get_loop().call_soon_threadsafe(task.cancel)
            except RuntimeError:  # boucle fermée : Core s'arrête
                pass

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick_s)
            if self._watch is not asyncio.current_task():
                return  # remplacée ou arrêtée pendant la pause
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - la surveillance ne s'arrête jamais en silence
                self._emit("watch_error", f"Studio watch error: {type(exc).__name__}", level="error")

    async def tick(self) -> None:
        """Un passage de surveillance : disparition du processus -> `failed` ; inactivité dépassée -> arrêt."""

        if self._lock.locked():
            return
        async with self._lock:
            state = self._load()
            if state.status is not S.READY:
                return
            await asyncio.to_thread(self._refresh, state)
            if state.status is not S.READY:
                return
            idle = self._clock() - (state.last_activity_at or state.ready_at or self._clock())
            if state.ws_open == 0 and idle >= self._idle_timeout_s:
                self._emit("idle_timeout", "Studio idle: stopping it", idle_s=round(idle), timeout_s=self._idle_timeout_s)
                await self._close_locked(state, "idle_timeout")

    # ------------------------------------------------------------------ cycle de vie de Core

    async def reconcile(self) -> dict[str, Any]:
        """Au démarrage de Core : rien n'est lancé. Un Studio resté vivant (Core tué) est adopté s'il répond avec son identifiant ;
        sinon l'état devient `failed` (disparu) ou `stopped`."""

        async with self._lock:
            state = self._load()
            if state.status in (S.STARTING, S.STOPPING) and state.process_ref and self._runner.is_alive(state.process_ref):
                await asyncio.to_thread(self._kill, state)
            if state.status is S.READY:
                if self._runner.is_alive(state.process_ref) and self._healthy(state):
                    self._start_watch()
                    self._emit("adopted", "A Studio left running by a previous Core was adopted", port=state.port)
                else:
                    self._fail(state, C.PROCESS_EXITED, "the Studio was no longer running when Core started")
            elif state.status in (S.STARTING, S.STOPPING):
                self._fail(state, C.START_FAILED if state.status is S.STARTING else C.STOP_FAILED, "interrupted by a Core restart")
            return self._view(state)

    async def stop(self) -> None:
        """Arrêt de Core : le Studio ne survit pas à Core (pas d'orphelin). Ne lève jamais."""

        self._cancel_watch()
        try:
            async with self._lock:
                state = self._load()
                if state.status in (S.READY, S.STARTING) and state.process_ref:
                    await self._close_locked(state, "core_stopped")
        except Exception as exc:  # noqa: BLE001
            self._emit("stop_failed", f"Studio stop at Core shutdown failed: {type(exc).__name__}", level="error")

    def stop_for_capability_change(self) -> None:
        """Appelé (thread) avant `uninstall`/`update`/`repair`/`disable` de la capacité : le Studio tient des fichiers de `runtime/`."""

        state = self._load()
        if state.process_ref:
            self._cancel_watch()
            self._kill(state)
            state.status, state.port, state.process_ref, state.launch_id = S.STOPPED, None, "", ""
            state.stop_reason = "capability_change"
            try:
                self._save(state)
            except StudioError:
                pass
            self._emit("stopped", "Studio stopped before a capability change", reason="capability_change")


def prefab_source_provider(prefabs) -> SourceProvider:
    """Branche le Studio sur la bibliothèque de prefabs (`PrefabService`) : lecture seule, version exacte. Le service ne reçoit
    ni chemin de la bibliothèque ni accès en écriture ; il ne voit que les octets de la source et les props d'exemple."""

    async def provide(pin: StudioPin) -> tuple[RemotionSource, Mapping[str, Any]]:
        source = await prefabs.remotion_source(pin.prefab_id, pin.version)
        manifest = await prefabs.manifest(pin.prefab_id, pin.version)
        return source, dict(manifest.sample_props)

    return provide

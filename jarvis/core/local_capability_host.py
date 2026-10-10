"""Hôte des capacités locales (handoff jarvis-remotion-presentation-integration, Slice 03 ; `docs/local-capabilities.md`).

Orchestre cycle de vie (installer une fois, mettre à jour, réparer, désactiver,
désinstaller), santé et processus enfant d'une capacité locale. Il ne sait RIEN
d'un runtime précis : tout effet (réseau, npm, processus) passe par un
`CapabilityRunner` injecté. Sans runner (`UnavailableRunner`, défaut) il
n'exécute rien et le dit par un code typé. Il est indépendant du service des
plugins MCP distants (`mcp_plugin_service.py`) : ni registre, ni coffre, ni
`jarvis-tools` en commun.

Règles : une opération par capacité à la fois (`busy`, jamais une file) ; chaque
étape est écrite avant l'effet qui la suit, si bien qu'un arrêt de Core laisse
un état vrai (`reconcile` le répare au démarrage) ; un échec du runner devient
un état typé (`install_failed`, `crashed`...) renvoyé à l'appelant et journalisé,
jamais un silence ; un refus de précondition lève `LocalCapabilityError`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import threading
from typing import Any

from jarvis.domain.local_capabilities import (
    CapabilityManifest, CapabilityState, Health, InstallStatus, LocalCapabilityError, LocalCapabilityErrorCode as C,
    ProcessStatus, bound_detail, check_invariants, initial_state, public_view, unreadable_view, transition_install, transition_process,
    with_enabled, with_health,
)
from jarvis.domain.v2 import utc_now
from jarvis.ports.local_capabilities import CapabilityRunner, LocalCapabilityStore
from jarvis.ports.v2 import DiagnosticSink


class UnavailableRunner:
    """Runner par défaut : n'exécute rien. Toute opération à effet dit `runner_unavailable`."""

    def _no(self) -> LocalCapabilityError:
        return LocalCapabilityError(C.RUNNER_UNAVAILABLE, "no capability runner is wired in this Core")

    def check_requirements(self, manifest: CapabilityManifest) -> tuple[str, ...]:
        raise self._no()

    def install(self, manifest: CapabilityManifest, runtime_dir: Path) -> Mapping[str, str]:
        raise self._no()

    def verify(self, manifest: CapabilityManifest, runtime_dir: Path, installed: Mapping[str, str]) -> None:
        raise self._no()

    def start(self, manifest: CapabilityManifest, runtime_dir: Path) -> str:
        raise self._no()

    def stop(self, process_ref: str) -> None:
        raise self._no()

    def is_alive(self, process_ref: str) -> bool:
        return False

    def remove(self, manifest: CapabilityManifest, runtime_dir: Path) -> None:
        raise self._no()


class LocalCapabilityHost:
    def __init__(self, store: LocalCapabilityStore, *, runner: CapabilityRunner | None = None,
                 manifests: Mapping[str, CapabilityManifest] | None = None,
                 clock: Callable[[], datetime] = utc_now, diagnostics: DiagnosticSink | None = None) -> None:
        self._store = store
        self._runner: CapabilityRunner = runner if runner is not None else UnavailableRunner()
        self._manifests: dict[str, CapabilityManifest] = dict(manifests or {})
        self._clock = clock
        self._diagnostics = diagnostics
        self._guard = threading.Lock()
        self._busy: set[str] = set()

    @property
    def runner(self) -> CapabilityRunner:
        return self._runner

    # ------------------------------------------------------------ infrastructure

    def _emit(self, kind: str, message: str, *, level: str = "info", **data: Any) -> None:
        if self._diagnostics is not None:
            self._diagnostics.emit(f"local_capability.{kind}", message, level=level, data=data)

    def register(self, manifest: CapabilityManifest) -> None:
        """Déclare (ou remplace) le manifeste : changer les versions épinglées exige ensuite `update`."""

        with self._guard:
            if manifest.capability_id in self._busy:
                raise LocalCapabilityError(C.BUSY, manifest.capability_id)
            self._manifests[manifest.capability_id] = manifest

    def _manifest(self, capability_id: str) -> CapabilityManifest:
        manifest = self._manifests.get(capability_id)
        if manifest is None:
            raise LocalCapabilityError(C.UNKNOWN, capability_id)
        return manifest

    @contextmanager
    def _operation(self, capability_id: str, name: str) -> Iterator[CapabilityManifest]:
        manifest = self._manifest(capability_id)
        with self._guard:
            if capability_id in self._busy:
                self._emit("refused", f"{name} refused: busy", level="warning", capability_id=capability_id, code=C.BUSY.value)
                raise LocalCapabilityError(C.BUSY, f"{capability_id}: another operation is running")
            self._busy.add(capability_id)
        self._emit(name, f"{name} started", capability_id=capability_id)
        try:
            yield manifest
        except LocalCapabilityError as exc:
            if exc.code in (C.STORE_FAILED, C.INTERNAL_ERROR):  # défaut local, pas un refus de précondition
                self._emit(f"{name}.failed", f"{name} failed: {exc.code.value}", level="error",
                           capability_id=capability_id, code=exc.code.value, detail=exc.detail)
            else:
                self._emit("refused", f"{name} refused: {exc.code.value}", level="warning", capability_id=capability_id, code=exc.code.value)
            raise
        except Exception as exc:  # noqa: BLE001 - never escapes untyped nor unlogged
            detail = bound_detail(f"{type(exc).__name__}: {exc}")
            self._emit(f"{name}.failed", f"{name} crashed: {type(exc).__name__}", level="error",
                       capability_id=capability_id, code=C.INTERNAL_ERROR.value, detail=detail)
            raise LocalCapabilityError(C.INTERNAL_ERROR, detail) from exc
        finally:
            with self._guard:
                self._busy.discard(capability_id)

    def _load(self, capability_id: str) -> CapabilityState:
        state = self._store.load(capability_id)
        return state if state is not None else initial_state(capability_id, now=self._clock())

    def _save(self, state: CapabilityState) -> CapabilityState:
        self._store.save(state)
        return state

    def _view(self, manifest: CapabilityManifest, state: CapabilityState) -> dict[str, Any]:
        return public_view(manifest, state)

    def _failure(self, exc: BaseException, default: C) -> tuple[C, str]:
        """Code et détail bornés d'un échec du runner ; une exception inattendue est journalisée avec sa trace."""

        if isinstance(exc, LocalCapabilityError):
            return exc.code, exc.detail
        detail = bound_detail(f"{type(exc).__name__}: {exc}")
        self._emit("runner_error", f"unexpected runner error {type(exc).__name__}", level="error", code=default.value, error=detail)
        return default, detail

    # ------------------------------------------------------------------ lecture

    def status(self, capability_id: str) -> dict[str, Any]:
        manifest = self._manifest(capability_id)
        return self._view(manifest, self._load(capability_id))

    def list_status(self) -> list[dict[str, Any]]:
        """Toutes les capacités ; un `state.json` illisible donne une entrée typée `state_unreadable`, les saines restent listées."""

        out: list[dict[str, Any]] = []
        for cid in sorted(self._manifests):
            try:
                out.append(self.status(cid))
            except LocalCapabilityError as exc:
                self._emit("status.failed", f"state of {cid} unreadable: {exc.code.value}", level="error",
                           capability_id=cid, code=exc.code.value, detail=exc.detail)
                out.append(unreadable_view(self._manifests[cid], exc))
        return out

    # ------------------------------------------------------------------ install

    def install(self, capability_id: str) -> dict[str, Any]:
        """Installe UNE fois. Déjà installée aux versions épinglées : aucun effet (le runner n'est pas appelé)."""

        with self._operation(capability_id, "install") as manifest:
            state = self._load(capability_id)
            pinned = tuple(sorted(manifest.components))
            if state.install_status is InstallStatus.INSTALLED:
                if state.installed_components == pinned:
                    self._emit("install.noop", "already installed at the pinned versions", capability_id=capability_id)
                    return self._view(manifest, state)
                raise LocalCapabilityError(C.UPDATE_REQUIRED, f"{capability_id}: installed versions differ from the pinned ones")
            return self._install_from(manifest, state, "install")

    def update(self, capability_id: str) -> dict[str, Any]:
        """Aligne la capacité installée sur les versions épinglées du manifeste (arrête le processus avant)."""

        with self._operation(capability_id, "update") as manifest:
            state = self._load(capability_id)
            if state.install_status is InstallStatus.NOT_INSTALLED:
                raise LocalCapabilityError(C.NOT_INSTALLED, capability_id)
            if state.install_status is InstallStatus.INSTALLED and state.installed_components == tuple(sorted(manifest.components)):
                return self._view(manifest, state)
            return self._install_from(manifest, state, "update")

    def repair(self, capability_id: str) -> dict[str, Any]:
        """Sonde ; si saine, rien. Sinon (échec, malsaine, plantée) réinstalle aux versions épinglées."""

        with self._operation(capability_id, "repair") as manifest:
            state = self._load(capability_id)
            if state.install_status is InstallStatus.NOT_INSTALLED:
                raise LocalCapabilityError(C.NOT_INSTALLED, capability_id)
            if state.install_status is InstallStatus.INSTALLED and state.installed_components == tuple(sorted(manifest.components)):
                state = self._probe(manifest, state)
                if state.health is Health.HEALTHY and state.process_status is not ProcessStatus.CRASHED:
                    return self._view(manifest, state)
            return self._install_from(manifest, state, "repair")

    def _install_from(self, manifest: CapabilityManifest, state: CapabilityState, name: str) -> dict[str, Any]:
        cid = manifest.capability_id
        state = self._stop_process(manifest, state)
        if state.process_status is not ProcessStatus.STOPPED:
            return self._view(manifest, state)  # l'arrêt a échoué : l'état typé le dit, on n'installe pas par-dessus
        if state.install_status in (InstallStatus.INSTALLING, InstallStatus.UNINSTALLING):  # reste d'un arrêt brutal, la garde `busy` garantit qu'il est périmé
            state = self._save(transition_install(state, InstallStatus.FAILED, now=self._clock(), error_code=C.INSTALL_INTERRUPTED))
        state = self._save(transition_install(state, InstallStatus.INSTALLING, now=self._clock()))
        try:
            missing = self._runner.check_requirements(manifest)
            if missing:
                raise LocalCapabilityError(C.REQUIREMENT_MISSING, "; ".join(missing))
            installed = dict(self._runner.install(manifest, self._store.runtime_dir(cid)))
            if installed != dict(manifest.components):
                raise LocalCapabilityError(C.INSTALL_FAILED, "the runner reported versions other than the pinned ones")
        except Exception as exc:  # noqa: BLE001 - converted to a typed state, logged by _failure/_emit
            code, detail = self._failure(exc, C.INSTALL_FAILED)
            state = self._save(transition_install(state, InstallStatus.FAILED, now=self._clock(), error_code=code, error_detail=detail))
            self._emit(f"{name}.failed", f"{name} failed: {code.value}", level="error", capability_id=cid, code=code.value, detail=detail)
            return self._view(manifest, state)
        state = self._save(transition_install(state, InstallStatus.INSTALLED, now=self._clock(), components=installed))
        state = self._probe(manifest, state)
        self._emit(f"{name}.done", f"{name} done", capability_id=cid, status=self._view(manifest, state)["status"])
        return self._view(manifest, state)

    # ------------------------------------------------------------------- santé

    def check_health(self, capability_id: str) -> dict[str, Any]:
        with self._operation(capability_id, "health") as manifest:
            state = self._load(capability_id)
            if state.install_status is not InstallStatus.INSTALLED:
                raise LocalCapabilityError(C.NOT_INSTALLED, capability_id)
            return self._view(manifest, self._probe(manifest, state))

    def _probe(self, manifest: CapabilityManifest, state: CapabilityState) -> CapabilityState:
        cid = manifest.capability_id
        if state.process_status in (ProcessStatus.RUNNING, ProcessStatus.STARTING) and not self._alive(state.process_ref):
            state = self._save(transition_process(state, ProcessStatus.CRASHED, now=self._clock(), process_ref=state.process_ref,
                                                  error_code=C.PROCESS_EXITED, error_detail="the child process is gone"))
            self._emit("process.exited", "child process is gone", level="error", capability_id=cid, code=C.PROCESS_EXITED.value)
        try:
            self._runner.verify(manifest, self._store.runtime_dir(cid), dict(state.installed_components))
        except Exception as exc:  # noqa: BLE001
            code, detail = self._failure(exc, C.HEALTH_FAILED)
            self._emit("health.failed", f"health failed: {code.value}", level="error", capability_id=cid, code=code.value, detail=detail)
            return self._save(with_health(state, Health.UNHEALTHY, now=self._clock(), error_code=code, error_detail=detail))
        healthy = with_health(state, Health.HEALTHY, now=self._clock())
        if state.process_status is ProcessStatus.CRASHED:  # un processus planté reste signalé même si les fichiers sont sains
            healthy = replace(healthy, last_error_code=state.last_error_code, last_error_detail=state.last_error_detail)
        return self._save(healthy)

    def _alive(self, process_ref: str) -> bool:
        try:
            return bool(process_ref) and self._runner.is_alive(process_ref)
        except Exception:  # noqa: BLE001 - an unanswerable liveness probe means "not alive"
            self._emit("runner_error", "is_alive raised", level="warning", process_ref=process_ref)
            return False

    def _alive_for_stop(self, capability_id: str, process_ref: str) -> bool:
        try:
            return bool(self._runner.is_alive(process_ref))
        except Exception as exc:  # noqa: BLE001 - unknown liveness must lead to a stop attempt, never to a skipped one
            self._emit("runner_error", "is_alive raised while stopping: stop is attempted anyway", level="warning",
                       capability_id=capability_id, error=bound_detail(f"{type(exc).__name__}: {exc}"))
            return True

    # ----------------------------------------------------------------- processus

    def start(self, capability_id: str) -> dict[str, Any]:
        with self._operation(capability_id, "start") as manifest:
            state = self._load(capability_id)
            if state.install_status is not InstallStatus.INSTALLED:
                raise LocalCapabilityError(C.NOT_INSTALLED, capability_id)
            if not state.enabled:
                raise LocalCapabilityError(C.DISABLED, capability_id)
            if state.installed_components != tuple(sorted(manifest.components)):
                raise LocalCapabilityError(C.UPDATE_REQUIRED, capability_id)
            if state.process_status is ProcessStatus.RUNNING and self._alive(state.process_ref):
                return self._view(manifest, state)  # déjà lancé : idempotent
            if state.process_status in (ProcessStatus.RUNNING, ProcessStatus.STARTING, ProcessStatus.STOPPING):
                state = self._save(transition_process(state, ProcessStatus.CRASHED, now=self._clock(), process_ref=state.process_ref,
                                                      error_code=C.PROCESS_EXITED, error_detail="stale process state"))
            if state.process_status is ProcessStatus.CRASHED and state.process_ref:
                state = self._stop_process(manifest, state)  # libère l'éventuel orphelin avant de relancer
                if state.process_status is not ProcessStatus.STOPPED:
                    return self._view(manifest, state)
            state = self._save(transition_process(state, ProcessStatus.STARTING, now=self._clock()))
            try:
                ref = self._runner.start(manifest, self._store.runtime_dir(capability_id))
                state = self._save(transition_process(state, ProcessStatus.RUNNING, now=self._clock(), process_ref=str(ref)))
            except Exception as exc:  # noqa: BLE001
                code, detail = self._failure(exc, C.START_FAILED)
                state = self._save(transition_process(state, ProcessStatus.CRASHED, now=self._clock(), error_code=code, error_detail=detail))
                self._emit("start.failed", f"start failed: {code.value}", level="error", capability_id=capability_id, code=code.value, detail=detail)
            return self._view(manifest, state)

    def stop(self, capability_id: str) -> dict[str, Any]:
        with self._operation(capability_id, "stop") as manifest:
            state = self._load(capability_id)
            return self._view(manifest, self._stop_process(manifest, state))

    def _stop_process(self, manifest: CapabilityManifest, state: CapabilityState) -> CapabilityState:
        """Arrête le processus connu ; idempotent. Un échec d'arrêt laisse `crashed` + `stop_failed` (orphelin possible, dit)."""

        if state.process_status is ProcessStatus.STOPPED:
            return state
        ref = state.process_ref
        if state.process_status is not ProcessStatus.STOPPING:
            state = self._save(transition_process(state, ProcessStatus.STOPPING, now=self._clock()))
        try:
            # Sonde STRICTE : si `is_alive` lève, on ne sait pas, donc on arrête quand même. « Pas vivant » ne
            # vaut que pour la sonde passive (`_alive`) ; sinon disable/uninstall/update effaceraient `runtime/`
            # sous un enfant encore vivant.
            if ref and self._alive_for_stop(manifest.capability_id, ref):
                self._runner.stop(ref)
        except Exception as exc:  # noqa: BLE001
            _, detail = self._failure(exc, C.STOP_FAILED)
            code = C.STOP_FAILED
            self._emit("stop.failed", "stop failed", level="error", capability_id=manifest.capability_id, code=code.value, detail=detail)
            return self._save(transition_process(state, ProcessStatus.CRASHED, now=self._clock(), error_code=code, error_detail=detail))
        return self._save(transition_process(state, ProcessStatus.STOPPED, now=self._clock()))

    # ------------------------------------------------------ activation, retrait

    def disable(self, capability_id: str) -> dict[str, Any]:
        with self._operation(capability_id, "disable") as manifest:
            state = self._stop_process(manifest, self._load(capability_id))
            if state.process_status is not ProcessStatus.STOPPED:
                return self._view(manifest, state)
            return self._view(manifest, self._save(with_enabled(state, False, now=self._clock())))

    def enable(self, capability_id: str) -> dict[str, Any]:
        """Réactive sans lancer : le démarrage reste une demande explicite."""

        with self._operation(capability_id, "enable") as manifest:
            return self._view(manifest, self._save(with_enabled(self._load(capability_id), True, now=self._clock())))

    def uninstall(self, capability_id: str) -> dict[str, Any]:
        with self._operation(capability_id, "uninstall") as manifest:
            state = self._load(capability_id)
            if state.install_status is InstallStatus.NOT_INSTALLED:
                return self._view(manifest, state)
            state = self._stop_process(manifest, state)
            if state.process_status is not ProcessStatus.STOPPED:
                return self._view(manifest, state)
            if state.install_status is InstallStatus.INSTALLING:
                state = self._save(transition_install(state, InstallStatus.FAILED, now=self._clock(), error_code=C.INSTALL_INTERRUPTED))
            state = self._save(transition_install(state, InstallStatus.UNINSTALLING, now=self._clock()))
            try:
                self._runner.remove(manifest, self._store.runtime_dir(capability_id))
            except Exception as exc:  # noqa: BLE001
                code, detail = self._failure(exc, C.UNINSTALL_FAILED)
                state = self._save(transition_install(state, InstallStatus.FAILED, now=self._clock(), error_code=code, error_detail=detail))
                self._emit("uninstall.failed", "uninstall failed", level="error", capability_id=capability_id, code=code.value, detail=detail)
                return self._view(manifest, state)
            return self._view(manifest, self._save(transition_install(state, InstallStatus.NOT_INSTALLED, now=self._clock())))

    # -------------------------------------------------------------- redémarrage

    def reconcile(self) -> list[dict[str, Any]]:
        """Au démarrage de Core : rend l'état stocké conforme à la réalité. N'installe, ne lance, n'arrête rien.

        Une installation ou désinstallation « en cours » est interrompue (`failed`) ; un processus noté vivant
        mais disparu devient `crashed`. Les états corrompus sont rapportés, pas réécrits.
        """

        out: list[dict[str, Any]] = []
        for cid in sorted(self._manifests):
            try:
                with self._operation(cid, "reconcile") as manifest:
                    state = self._store.load(cid)
                    if state is None:
                        continue
                    if state.install_status in (InstallStatus.INSTALLING, InstallStatus.UNINSTALLING):
                        state = self._save(transition_install(state, InstallStatus.FAILED, now=self._clock(), error_code=C.INSTALL_INTERRUPTED))
                    if state.process_status in (ProcessStatus.RUNNING, ProcessStatus.STARTING, ProcessStatus.STOPPING) \
                            and not self._alive(state.process_ref):
                        state = self._save(transition_process(state, ProcessStatus.CRASHED, now=self._clock(), process_ref=state.process_ref,
                                                              error_code=C.PROCESS_EXITED, error_detail="gone after restart"))
                    check_invariants(state)
                    out.append(self._view(manifest, state))
            except LocalCapabilityError:
                pass  # déjà journalisé par `_operation` (une seule fois) ; les autres capacités continuent
        return out

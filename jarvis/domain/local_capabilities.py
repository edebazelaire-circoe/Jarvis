"""Contrat pur des capacités locales installables (handoff jarvis-remotion-presentation-integration, Slice 03).

Une **capacité locale** est un runtime que Jarvis installe UNE fois par profil
d'exécution, épingle à des versions exactes, surveille (santé, réparation) et
dont il gère le processus enfant. Ce n'est PAS un plugin MCP distant :
`jarvis/domain/mcp_plugins.py` ne parle que d'URL `streamable_http` et garde
son sens ; ici il n'y a ni URL, ni coffre de secrets, ni OAuth, ni endpoint.
Contrat canonique : `docs/local-capabilities.md` ; pendant distant :
`docs/mcp/plugins.md`.

Axes indépendants (comme `enabled` / `connection_status` des plugins) :
`install_status` (ce qui est sur le disque), `process_status` (le processus
enfant), `health` (dernier verdict de sonde) et `enabled` (choix de
l'utilisateur). `status` n'est qu'un résumé dérivé, jamais stocké.

Invariants : un processus n'existe que sur une capacité installée ; une
capacité désactivée n'a pas de processus ; `last_error_code` est un code stable
de `LocalCapabilityErrorCode`, jamais un texte brut du runner (le détail
borné vit à part dans `last_error_detail`) ; les versions sont EXACTES (ni
plage, ni `latest`).

Pur : aucune E/S, aucune horloge implicite (chaque transition reçoit `now`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Any

CAPABILITY_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
#: Version exacte `1.2.3` avec suffixe de pré-version facultatif ; jamais `^`, `~`, `*`, `latest`.
EXACT_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]{1,32})?")
COMPONENT_NAME_PATTERN = re.compile(r"[a-z0-9@][a-z0-9@/._-]{0,63}")
#: Exigence de poste : `node` seulement, version minimale `>=` (pas d'épinglage : c'est le poste qui la fournit).
MAX_COMPONENTS = 32
MAX_REQUIREMENTS = 16
MAX_DISPLAY_NAME_CHARS = 64
MAX_ERROR_DETAIL_CHARS = 300
KIND_LOCAL_RUNTIME = "local_runtime"
#: Transport propre, jamais `streamable_http` : un autre mot, pour que rien ne les confonde.
TRANSPORT_LOCAL_PROCESS = "local_process"
FAMILY = "local_capability"


class LocalCapabilityErrorCode(StrEnum):
    UNKNOWN = "local_capability_unknown"
    INVALID = "local_capability_invalid"
    #: Une autre opération tient déjà cette capacité.
    BUSY = "local_capability_busy"
    NOT_INSTALLED = "local_capability_not_installed"
    DISABLED = "local_capability_disabled"
    #: Installée à d'autres versions que le manifeste : `update` explicite, jamais de mise à jour implicite.
    UPDATE_REQUIRED = "local_capability_update_required"
    REQUIREMENT_MISSING = "local_capability_requirement_missing"
    INSTALL_FAILED = "local_capability_install_failed"
    #: Une installation interrompue (arrêt de Core) a été trouvée en cours au redémarrage.
    INSTALL_INTERRUPTED = "local_capability_install_interrupted"
    UNINSTALL_FAILED = "local_capability_uninstall_failed"
    HEALTH_FAILED = "local_capability_health_failed"
    START_FAILED = "local_capability_start_failed"
    STOP_FAILED = "local_capability_stop_failed"
    PROCESS_EXITED = "local_capability_process_exited"
    #: Aucun runner branché : par défaut le socle n'exécute ni réseau ni npm.
    RUNNER_UNAVAILABLE = "local_capability_runner_unavailable"
    STORE_FAILED = "local_capability_store_failed"
    INTERNAL_ERROR = "local_capability_internal_error"


class LocalCapabilityError(Exception):
    def __init__(self, code: LocalCapabilityErrorCode, detail: str = "") -> None:
        super().__init__(f"{code.value}: {detail}" if detail else code.value)
        self.code = code
        self.detail = bound_detail(detail)


class InstallStatus(StrEnum):
    NOT_INSTALLED = "not_installed"
    INSTALLING = "installing"
    INSTALLED = "installed"
    FAILED = "failed"
    UNINSTALLING = "uninstalling"


class ProcessStatus(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"


class Health(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class CapabilityStatus(StrEnum):
    """Résumé unique pour l'utilisateur (dérivé, `derive_status`)."""

    NOT_INSTALLED = "not_installed"
    INSTALLING = "installing"
    UNINSTALLING = "uninstalling"
    INSTALL_FAILED = "install_failed"
    DISABLED = "disabled"
    REPAIR_NEEDED = "repair_needed"
    CRASHED = "crashed"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    READY = "ready"


_INSTALL_TRANSITIONS: Mapping[InstallStatus, frozenset[InstallStatus]] = MappingProxyType({
    InstallStatus.NOT_INSTALLED: frozenset({InstallStatus.INSTALLING}),
    InstallStatus.INSTALLING: frozenset({InstallStatus.INSTALLED, InstallStatus.FAILED}),
    InstallStatus.INSTALLED: frozenset({InstallStatus.INSTALLING, InstallStatus.UNINSTALLING}),
    InstallStatus.FAILED: frozenset({InstallStatus.INSTALLING, InstallStatus.UNINSTALLING}),
    InstallStatus.UNINSTALLING: frozenset({InstallStatus.NOT_INSTALLED, InstallStatus.FAILED}),
})
_PROCESS_TRANSITIONS: Mapping[ProcessStatus, frozenset[ProcessStatus]] = MappingProxyType({
    ProcessStatus.STOPPED: frozenset({ProcessStatus.STARTING}),
    ProcessStatus.STARTING: frozenset({ProcessStatus.RUNNING, ProcessStatus.CRASHED, ProcessStatus.STOPPED, ProcessStatus.STOPPING}),
    ProcessStatus.RUNNING: frozenset({ProcessStatus.STOPPING, ProcessStatus.CRASHED}),
    ProcessStatus.STOPPING: frozenset({ProcessStatus.STOPPED, ProcessStatus.CRASHED}),
    ProcessStatus.CRASHED: frozenset({ProcessStatus.STARTING, ProcessStatus.STOPPED, ProcessStatus.STOPPING}),
})


def bound_detail(text: object) -> str:
    return str(text or "").replace("\n", " ")[:MAX_ERROR_DETAIL_CHARS]


def _invalid(message: str) -> LocalCapabilityError:
    return LocalCapabilityError(LocalCapabilityErrorCode.INVALID, message)


@dataclass(frozen=True)
class Requirement:
    """Exigence du poste (ex. `node >= 20.0.0`), vérifiée par le runner, jamais installée par lui."""

    name: str
    minimum: str


@dataclass(frozen=True)
class CapabilityManifest:
    """Ce qu'une capacité promet : identité, composants épinglés, exigences, point d'entrée logique.

    `entrypoint` est un NOM logique résolu par le runner du hôte, jamais une
    ligne de commande : un manifeste ne porte aucun chemin ni commande shell.
    """

    capability_id: str
    display_name: str
    components: tuple[tuple[str, str], ...]
    requirements: tuple[Requirement, ...] = ()
    entrypoint: str = "main"
    kind: str = KIND_LOCAL_RUNTIME

    @property
    def pinned(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.components))


def new_manifest(*, capability_id: str, display_name: str, components: Mapping[str, str],
                 requirements: Iterable[tuple[str, str]] = (), entrypoint: str = "main") -> CapabilityManifest:
    if not isinstance(capability_id, str) or not CAPABILITY_ID_PATTERN.fullmatch(capability_id):
        raise _invalid("capability_id must be a lowercase slug of at most 32 characters")
    if capability_id.startswith("jarvis-"):
        raise _invalid("capability_id may not start with the reserved native prefix 'jarvis-'")
    name = (display_name or "").strip() if isinstance(display_name, str) else ""
    if not name or len(name) > MAX_DISPLAY_NAME_CHARS:
        raise _invalid(f"display_name must be 1..{MAX_DISPLAY_NAME_CHARS} characters")
    if not components or len(components) > MAX_COMPONENTS:
        raise _invalid(f"components must hold 1..{MAX_COMPONENTS} pinned entries")
    for comp, version in components.items():
        if not isinstance(comp, str) or not COMPONENT_NAME_PATTERN.fullmatch(comp):
            raise _invalid("component name is not a valid package name")
        if not isinstance(version, str) or not EXACT_VERSION_PATTERN.fullmatch(version):
            raise _invalid(f"component {comp!r} needs an exact version (no range, no 'latest')")
    reqs = []
    for req_name, minimum in requirements:
        if req_name != "node" or not isinstance(minimum, str) or not EXACT_VERSION_PATTERN.fullmatch(minimum):
            raise _invalid("only 'node' with an exact minimum version is a known requirement")
        reqs.append(Requirement(req_name, minimum))
    if len(reqs) > MAX_REQUIREMENTS:
        raise _invalid("too many requirements")
    if not isinstance(entrypoint, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", entrypoint):
        raise _invalid("entrypoint must be a logical name, not a command line")
    return CapabilityManifest(capability_id, name, tuple(sorted(components.items())), tuple(reqs), entrypoint)


@dataclass(frozen=True)
class CapabilityState:
    capability_id: str
    install_status: InstallStatus = InstallStatus.NOT_INSTALLED
    process_status: ProcessStatus = ProcessStatus.STOPPED
    health: Health = Health.UNKNOWN
    enabled: bool = True
    #: Versions réellement présentes sur le disque (vide hors `installed`).
    installed_components: tuple[tuple[str, str], ...] = ()
    #: Référence opaque du processus (pid) pour reconnaître un orphelin au redémarrage ; jamais une commande.
    process_ref: str = ""
    last_error_code: LocalCapabilityErrorCode | None = None
    last_error_detail: str = ""
    updated_at: str = ""
    #: Nombre d'installations tentées : preuve de « une seule fois » pour les tests et le diagnostic.
    install_attempts: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id, "install_status": self.install_status.value,
            "process_status": self.process_status.value, "health": self.health.value, "enabled": self.enabled,
            "installed_components": dict(self.installed_components), "process_ref": self.process_ref,
            "last_error_code": self.last_error_code.value if self.last_error_code else None,
            "last_error_detail": self.last_error_detail, "updated_at": self.updated_at,
            "install_attempts": self.install_attempts,
        }


def state_from_payload(payload: Mapping[str, Any]) -> CapabilityState:
    """Relit un état stocké ; refuse (jamais ne devine) un fichier altéré."""

    try:
        code = payload.get("last_error_code")
        comps = payload.get("installed_components") or {}
        if not isinstance(comps, Mapping):
            raise ValueError("installed_components")
        state = CapabilityState(
            capability_id=str(payload["capability_id"]),
            install_status=InstallStatus(payload["install_status"]),
            process_status=ProcessStatus(payload["process_status"]),
            health=Health(payload["health"]), enabled=bool(payload["enabled"]),
            installed_components=tuple(sorted((str(k), str(v)) for k, v in comps.items())),
            process_ref=str(payload.get("process_ref") or ""),
            last_error_code=LocalCapabilityErrorCode(code) if code else None,
            last_error_detail=bound_detail(payload.get("last_error_detail")),
            updated_at=str(payload.get("updated_at") or ""), install_attempts=int(payload.get("install_attempts") or 0),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise LocalCapabilityError(LocalCapabilityErrorCode.STORE_FAILED, f"stored state is not readable: {exc!r}") from None
    check_invariants(state)
    return state


def check_invariants(state: CapabilityState) -> None:
    if state.process_status is not ProcessStatus.STOPPED and state.install_status is not InstallStatus.INSTALLED:
        raise LocalCapabilityError(LocalCapabilityErrorCode.INTERNAL_ERROR, "a process needs an installed capability")
    if not state.enabled and state.process_status in (ProcessStatus.STARTING, ProcessStatus.RUNNING):
        raise LocalCapabilityError(LocalCapabilityErrorCode.INTERNAL_ERROR, "a disabled capability has no running process")


def initial_state(capability_id: str, *, now: datetime) -> CapabilityState:
    return CapabilityState(capability_id=capability_id, updated_at=now.isoformat())


def _touch(state: CapabilityState, now: datetime, **changes: Any) -> CapabilityState:
    new = replace(state, updated_at=now.isoformat(), **changes)
    check_invariants(new)
    return new


def transition_install(state: CapabilityState, to: InstallStatus, *, now: datetime,
                       error_code: LocalCapabilityErrorCode | None = None, error_detail: str = "",
                       components: Mapping[str, str] | None = None) -> CapabilityState:
    if to not in _INSTALL_TRANSITIONS[state.install_status]:
        raise LocalCapabilityError(LocalCapabilityErrorCode.INTERNAL_ERROR,
                                   f"install transition {state.install_status.value} -> {to.value} is not allowed")
    changes: dict[str, Any] = {"install_status": to, "last_error_code": error_code, "last_error_detail": bound_detail(error_detail)}
    if to is InstallStatus.INSTALLING:
        changes.update(install_attempts=state.install_attempts + 1, health=Health.UNKNOWN)
    elif to is InstallStatus.INSTALLED:
        changes.update(installed_components=tuple(sorted((components or {}).items())), health=Health.UNKNOWN)
    elif to is InstallStatus.NOT_INSTALLED:
        changes.update(installed_components=(), health=Health.UNKNOWN, process_status=ProcessStatus.STOPPED, process_ref="")
    elif to is InstallStatus.FAILED:
        changes.update(health=Health.UNHEALTHY, installed_components=())
    return _touch(state, now, **changes)


def transition_process(state: CapabilityState, to: ProcessStatus, *, now: datetime, process_ref: str | None = None,
                       error_code: LocalCapabilityErrorCode | None = None, error_detail: str = "") -> CapabilityState:
    if to not in _PROCESS_TRANSITIONS[state.process_status]:
        raise LocalCapabilityError(LocalCapabilityErrorCode.INTERNAL_ERROR,
                                   f"process transition {state.process_status.value} -> {to.value} is not allowed")
    ref = state.process_ref if process_ref is None else process_ref
    if to is ProcessStatus.STOPPED:
        ref = ""
    return _touch(state, now, process_status=to, process_ref=ref, last_error_code=error_code,
                  last_error_detail=bound_detail(error_detail))


def with_health(state: CapabilityState, health: Health, *, now: datetime,
                error_code: LocalCapabilityErrorCode | None = None, error_detail: str = "") -> CapabilityState:
    return _touch(state, now, health=health, last_error_code=error_code if health is Health.UNHEALTHY else None,
                  last_error_detail=bound_detail(error_detail) if health is Health.UNHEALTHY else "")


def with_enabled(state: CapabilityState, enabled: bool, *, now: datetime) -> CapabilityState:
    return _touch(state, now, enabled=enabled)


def derive_status(state: CapabilityState) -> CapabilityStatus:
    if state.install_status is InstallStatus.NOT_INSTALLED:
        return CapabilityStatus.NOT_INSTALLED
    if state.install_status is InstallStatus.INSTALLING:
        return CapabilityStatus.INSTALLING
    if state.install_status is InstallStatus.UNINSTALLING:
        return CapabilityStatus.UNINSTALLING
    if state.install_status is InstallStatus.FAILED:
        return CapabilityStatus.INSTALL_FAILED
    if not state.enabled:
        return CapabilityStatus.DISABLED
    if state.process_status is ProcessStatus.CRASHED:
        return CapabilityStatus.CRASHED
    if state.health is Health.UNHEALTHY:
        return CapabilityStatus.REPAIR_NEEDED
    return {ProcessStatus.STARTING: CapabilityStatus.STARTING, ProcessStatus.RUNNING: CapabilityStatus.RUNNING,
            ProcessStatus.STOPPING: CapabilityStatus.STOPPING, ProcessStatus.STOPPED: CapabilityStatus.READY}[state.process_status]


def public_view(manifest: CapabilityManifest, state: CapabilityState) -> dict[str, Any]:
    """Forme de toute réponse API/UI : typée, sans chemin disque, sans commande, sans secret."""

    pinned = dict(manifest.components)
    installed = dict(state.installed_components)
    return {
        "family": FAMILY, "transport": TRANSPORT_LOCAL_PROCESS, "capability_id": manifest.capability_id,
        "display_name": manifest.display_name, "kind": manifest.kind, "status": derive_status(state).value,
        "install_status": state.install_status.value, "process_status": state.process_status.value,
        "health": state.health.value, "enabled": state.enabled, "pinned": pinned, "installed": installed,
        "update_required": bool(installed) and installed != pinned,
        "requirements": [{"name": r.name, "minimum": r.minimum} for r in manifest.requirements],
        "last_error_code": state.last_error_code.value if state.last_error_code else None,
        "last_error_detail": state.last_error_detail, "install_attempts": state.install_attempts,
        "updated_at": state.updated_at,
    }

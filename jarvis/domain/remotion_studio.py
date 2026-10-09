"""Remotion Studio optionnel (handoff jarvis-remotion-presentation-integration, Slice 11 ; contrat `docs/remotion-studio.md`).

Le Studio (`remotion studio`, serveur de développement avec rechargement à chaud) est un processus SUPPLÉMENTAIRE de la
capacité locale Remotion : ouvert sur demande explicite de l'utilisateur, jamais par l'aperçu, un par profil d'exécution
(jamais un par présentation). Ce module est pur (aucune E/S) : statuts, codes d'échec, vue publique, et le plan du dossier de
travail que le Studio sert, construit à partir de la **seule** source d'une scène de la bibliothèque de prefabs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import json
import re
from typing import Any

from jarvis.domain.local_capabilities import bound_detail
from jarvis.domain.remotion_source import RemotionSource, source_digest

CAPABILITY_ID = "remotion"
FAMILY = "local_capability_studio"
#: Sous `runtime/` (le seul dossier où la capacité écrit ; `uninstall` l'emporte avec lui, le Studio arrêté d'abord).
STUDIO_DIR = "studio"
WORK_DIR = "work"
#: Le Studio n'est servi que depuis le dossier de travail : sa racine Remotion (`package.json` voisin) en est la limite.
WORK_PACKAGE = "package.json"
WORK_ROOT_FILE = "studio-root.tsx"
GUARD_FILE = "studio-guard.cjs"

DEFAULT_IDLE_TIMEOUT_S = 1800.0
MIN_IDLE_TIMEOUT_S = 60.0
MAX_IDLE_TIMEOUT_S = 24 * 3600.0
START_TIMEOUT_S = 120.0
#: Le garde du Studio se termine seul ce nombre de secondes APRÈS le délai d'inactivité de Core (Core l'arrête avant, sauf s'il est mort).
IDLE_GUARD_MARGIN_S = 120.0
STOP_GRACE_S = 5.0
MAX_DIAGNOSTIC_LINES = 12
MAX_SAVED_EDITS = 5
#: Ports acceptés quand l'opérateur en fixe un (`JARVIS_REMOTION_STUDIO_PORT`) : non privilégiés seulement.
MIN_PORT = 1024
MAX_PORT = 65535

PREFAB_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_IDENT_SAFE = re.compile(r"\A[A-Za-z][A-Za-z0-9_-]{0,63}\Z")


class StudioStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    FAILED = "failed"


class StudioErrorCode(str, Enum):
    INVALID = "remotion_studio_invalid"
    BUSY = "remotion_studio_busy"
    RUNTIME_UNAVAILABLE = "remotion_studio_runtime_unavailable"
    SOURCE_UNAVAILABLE = "remotion_studio_source_unavailable"
    NOT_RUNNING = "remotion_studio_not_running"
    PORT_UNAVAILABLE = "remotion_studio_port_unavailable"
    START_FAILED = "remotion_studio_start_failed"
    START_TIMEOUT = "remotion_studio_start_timeout"
    HEALTH_FAILED = "remotion_studio_health_failed"
    PROCESS_EXITED = "remotion_studio_process_exited"
    STOP_FAILED = "remotion_studio_stop_failed"
    SYNC_FAILED = "remotion_studio_sync_failed"
    STORE_FAILED = "remotion_studio_store_failed"
    INTERNAL_ERROR = "remotion_studio_internal_error"
    UNAVAILABLE = "remotion_studio_unavailable"


_HTTP = {StudioErrorCode.INVALID: 400, StudioErrorCode.UNAVAILABLE: 503, StudioErrorCode.STORE_FAILED: 500,
         StudioErrorCode.INTERNAL_ERROR: 500, StudioErrorCode.SOURCE_UNAVAILABLE: 404}


class StudioError(Exception):
    """Refus de précondition ou échec typé ; `code` stable (préfixe `remotion_studio_`), `detail` borné et sans chemin."""

    def __init__(self, code: StudioErrorCode, detail: str = "") -> None:
        self.code = code
        self.detail = bound_detail(detail)
        super().__init__(f"{code.value}: {self.detail}" if self.detail else code.value)

    @property
    def http_status(self) -> int:
        return _HTTP.get(self.code, 409)


@dataclass(frozen=True, slots=True)
class StudioPin:
    """La scène que le Studio affiche : version exacte d'un prefab Remotion (jamais « la dernière » sans le dire)."""

    prefab_id: str
    version: int

    def to_dict(self) -> dict[str, Any]:
        return {"prefab_id": self.prefab_id, "version": self.version}


def parse_pin(raw: object) -> StudioPin:
    if not isinstance(raw, Mapping) or set(raw) != {"prefab_id", "version"}:
        raise StudioError(StudioErrorCode.INVALID, 'the body must be exactly {"prefab_id", "version"}')
    prefab_id, version = raw["prefab_id"], raw["version"]
    if not isinstance(prefab_id, str) or not PREFAB_ID.fullmatch(prefab_id):
        raise StudioError(StudioErrorCode.INVALID, "prefab_id is not a valid prefab id")
    if type(version) is not int or not 1 <= version <= 1_000_000:
        raise StudioError(StudioErrorCode.INVALID, "version must be an exact positive integer (a Studio never follows 'latest')")
    return StudioPin(prefab_id, version)


def valid_port(value: object) -> bool:
    return type(value) is int and MIN_PORT <= value <= MAX_PORT


def parse_idle_timeout(value: object) -> float:
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise StudioError(StudioErrorCode.INVALID, "the idle timeout must be a number of seconds") from None
    if not MIN_IDLE_TIMEOUT_S <= seconds <= MAX_IDLE_TIMEOUT_S:
        raise StudioError(StudioErrorCode.INVALID, f"the idle timeout must be between {int(MIN_IDLE_TIMEOUT_S)} and {int(MAX_IDLE_TIMEOUT_S)} s")
    return seconds


# ------------------------------------------------------------------ dossier de travail

def _entry_import(entry: str) -> str:
    stem = entry.rsplit(".", 1)[0] if "." in entry.rsplit("/", 1)[-1] else entry
    return "./" + stem


def plan_workspace(source: RemotionSource, sample_props: Mapping[str, Any] | None = None) -> dict[str, bytes]:
    """Fichiers EXACTS du dossier de travail du Studio : `src/**` et `public/**` de la scène (octets inchangés), plus trois
    fichiers générés (`package.json` qui fixe la racine Remotion à ce dossier, `studio-root.tsx` qui enregistre la composition
    DÉCLARÉE par le manifeste). Aucun `node_modules`, aucune config Remotion, aucun fichier hors de la source."""

    block = source.block
    composition = block.composition
    if not _IDENT_SAFE.fullmatch(composition.composition_id):
        raise StudioError(StudioErrorCode.SOURCE_UNAVAILABLE, "the composition id is not usable as a Studio composition id")
    files: dict[str, bytes] = {path: bytes(data) for path, data in source.files.items()}
    props = json.dumps(dict(sample_props or {}), ensure_ascii=True, sort_keys=True)
    root = "\n".join((
        "// Généré par Jarvis (docs/remotion-studio.md) : ne pas modifier, le Studio est une vue de la source de la scène.",
        "import React from 'react';",
        "import {Composition, registerRoot} from 'remotion';",
        f"import Scene from {json.dumps(_entry_import(block.entry))};",
        "const Root = () => (",
        f"  <Composition id={json.dumps(composition.composition_id)} component={{Scene as any}} durationInFrames={{{composition.duration_in_frames}}}",
        f"    fps={{{composition.fps}}} width={{{composition.width}}} height={{{composition.height}}} defaultProps={{{props}}} />",
        ");",
        "registerRoot(Root);",
        "",
    ))
    files[WORK_ROOT_FILE] = root.encode("utf-8")
    files[WORK_PACKAGE] = json.dumps({"name": "jarvis-studio-scene", "private": True, "version": "0.0.0"}).encode("utf-8")
    return files


def workspace_digest(files: Mapping[str, bytes]) -> str:
    return source_digest(files)


# ------------------------------------------------------------------ état et vue

@dataclass
class StudioState:
    status: StudioStatus = StudioStatus.STOPPED
    pin: StudioPin | None = None
    source_digest: str = ""
    workspace_digest: str = ""
    composition: dict[str, Any] | None = None
    port: int | None = None
    process_ref: str = ""
    launch_id: str = ""
    started_at: float | None = None
    ready_at: float | None = None
    last_activity_at: float | None = None
    synced_at: float | None = None
    syncs: int = 0
    restarts: int = 0
    last_error_code: str = ""
    last_error_detail: str = ""
    stop_reason: str = ""
    diagnostics: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    edits_saved: int = 0
    egress_blocked: int = 0
    ws_open: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {"schema": 1, "status": self.status.value, "pin": self.pin.to_dict() if self.pin else None,
                "source_digest": self.source_digest, "workspace_digest": self.workspace_digest, "composition": self.composition,
                "port": self.port, "process_ref": self.process_ref, "launch_id": self.launch_id, "started_at": self.started_at,
                "ready_at": self.ready_at, "synced_at": self.synced_at, "syncs": self.syncs, "restarts": self.restarts,
                "last_error_code": self.last_error_code, "last_error_detail": self.last_error_detail,
                "stop_reason": self.stop_reason, "diagnostics": self.diagnostics[-MAX_DIAGNOSTIC_LINES:], "edits_saved": self.edits_saved}

    @classmethod
    def from_payload(cls, raw: object) -> "StudioState":
        """Relit `state.json` ; toute forme inattendue donne l'état arrêté (jamais un état deviné), l'appelant le journalise."""

        if not isinstance(raw, Mapping) or raw.get("schema") != 1:
            raise ValueError("unknown studio state schema")
        pin = raw.get("pin")
        state = cls(status=StudioStatus(str(raw.get("status"))), pin=parse_pin(pin) if pin else None)
        for key in ("source_digest", "workspace_digest", "process_ref", "launch_id", "last_error_code", "last_error_detail", "stop_reason"):
            value = raw.get(key, "")
            setattr(state, key, value if isinstance(value, str) else "")
        port = raw.get("port")
        state.port = port if valid_port(port) else None
        composition = raw.get("composition")
        state.composition = dict(composition) if isinstance(composition, Mapping) else None
        for key in ("started_at", "ready_at", "synced_at"):
            value = raw.get(key)
            setattr(state, key, float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None)
        for key in ("syncs", "restarts", "edits_saved"):
            value = raw.get(key, 0)
            setattr(state, key, value if type(value) is int and value >= 0 else 0)
        diagnostics = raw.get("diagnostics")
        state.diagnostics = [bound_detail(line) for line in diagnostics[:MAX_DIAGNOSTIC_LINES]] if isinstance(diagnostics, list) else []
        return state


def public_view(state: StudioState, *, idle_timeout_s: float, now: float, configured_port: int | None = None) -> dict[str, Any]:
    """Vue publique (Core, Control Center, Tool Brain) : jamais de chemin disque, de jeton, ni de variable d'environnement."""

    ready = state.status is StudioStatus.READY
    idle_in = None
    if ready and state.last_activity_at is not None:
        idle_in = max(0.0, idle_timeout_s - (now - state.last_activity_at))
    return {
        "family": FAMILY, "capability_id": CAPABILITY_ID, "status": state.status.value,
        "url": f"http://127.0.0.1:{state.port}/" if ready and state.port else None,
        "port": state.port if state.status in (StudioStatus.READY, StudioStatus.STARTING) else None,
        "port_mode": "configured" if configured_port else "random",
        "pin": state.pin.to_dict() if state.pin else None, "source_digest": state.source_digest or None,
        "composition": state.composition,
        "started_at": state.started_at, "ready_at": state.ready_at, "synced_at": state.synced_at, "syncs": state.syncs,
        "restarts": state.restarts, "idle_timeout_s": idle_timeout_s, "idle_in_s": None if idle_in is None else round(idle_in, 1),
        "viewers": state.ws_open if ready else 0, "stop_reason": state.stop_reason or None,
        "last_error_code": state.last_error_code or None, "last_error_detail": state.last_error_detail or None,
        "diagnostics": [bound_detail(line) for line in state.diagnostics[-MAX_DIAGNOSTIC_LINES:]],
        "work_copy": {"modified_files": list(state.modified_files)[:20], "edits_saved": state.edits_saved},
        "egress_blocked": state.egress_blocked,
    }

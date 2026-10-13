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
#: Top-level files Jarvis generates in every workspace (read-only); a master workspace adds `src/master/**` (`remotion_studio_master`).
GENERATED_TOP_LEVEL = (WORK_ROOT_FILE, WORK_PACKAGE)

DEFAULT_IDLE_TIMEOUT_S = 1800.0
MIN_IDLE_TIMEOUT_S = 60.0
MAX_IDLE_TIMEOUT_S = 24 * 3600.0
START_TIMEOUT_S = 120.0
#: Le garde du Studio se termine seul ce nombre de secondes APRÈS le délai d'inactivité de Core (Core l'arrête avant, sauf s'il est mort).
IDLE_GUARD_MARGIN_S = 120.0
STOP_GRACE_S = 5.0
MAX_DIAGNOSTIC_LINES = 12
#: Dossiers gardés dans `studio-edits/` : une mise de côté de plus retire la PLUS ANCIENNE (noms triables et monotones) et le
#: journalise (`remotion_studio.edits_rotated`, les noms retirés).
MAX_SAVED_EDITS = 5
MAX_SET_ASIDE_NAMED = 50
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
    ACK_REQUIRED = "remotion_studio_ack_required"
    STATE_UNREADABLE = "remotion_studio_state_unreadable"
    # Slice 12 (native-studio-playback-fix) : espace de travail et publication vers une variante.
    UNPUBLISHED_EDITS = "remotion_studio_unpublished_edits"
    PUBLISH_CONFIRM_REQUIRED = "remotion_studio_publish_confirm_required"
    PUBLISH_NOTHING = "remotion_studio_publish_nothing"
    PUBLISH_BASE_MISMATCH = "remotion_studio_publish_base_mismatch"
    PUBLISH_CONFLICT = "remotion_studio_publish_conflict"
    PUBLISH_INVALID_FILE = "remotion_studio_publish_invalid_file"
    PUBLISH_IMPORT_REFUSED = "remotion_studio_publish_import_refused"
    PUBLISH_REFUSED = "remotion_studio_publish_refused"
    PUBLISH_UNAVAILABLE = "remotion_studio_publish_unavailable"
    #: QA Slice 12 (I1) : l'espace ne donne plus l'empreinte de la liste confirmée ; rien n'est publié, la page relit et reconfirme.
    PUBLISH_LISTING_CHANGED = "remotion_studio_publish_listing_changed"
    # Master target of a Presentation Variant (handoff jarvis-remotion-master-project-studio-export, Slice 05;
    # `docs/remotion-master-project.md` § 3, § 9). All 409.
    MASTER_INCOMPATIBLE = "remotion_studio_master_incompatible"
    MASTER_STALE = "remotion_studio_master_stale"
    PUBLISH_MASTER_UNSUPPORTED = "remotion_studio_publish_master_unsupported"


_HTTP = {StudioErrorCode.INVALID: 400, StudioErrorCode.ACK_REQUIRED: 400, StudioErrorCode.UNAVAILABLE: 503, StudioErrorCode.STORE_FAILED: 500,
         StudioErrorCode.INTERNAL_ERROR: 500, StudioErrorCode.SOURCE_UNAVAILABLE: 404,
         StudioErrorCode.PUBLISH_CONFIRM_REQUIRED: 400, StudioErrorCode.PUBLISH_INVALID_FILE: 422,
         StudioErrorCode.PUBLISH_IMPORT_REFUSED: 422, StudioErrorCode.PUBLISH_REFUSED: 422, StudioErrorCode.PUBLISH_UNAVAILABLE: 503}


class StudioError(Exception):
    """Refus de précondition ou échec typé ; `code` stable (préfixe `remotion_studio_`), `detail` borné et sans chemin."""

    def __init__(self, code: StudioErrorCode, detail: str = "", *, extra: Mapping[str, Any] | None = None, status: int | None = None) -> None:
        self.code = code
        self.detail = bound_detail(detail)
        #: Champs de plus dans l'enveloppe d'erreur (publication : code de la porte d'édition, diagnostics, versions) ; jamais un chemin.
        self.extra = dict(extra or {})
        self._status = status
        super().__init__(f"{code.value}: {self.detail}" if self.detail else code.value)

    @property
    def http_status(self) -> int:
        return self._status or _HTTP.get(self.code, 409)


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


ACK_FIELD = "acknowledge_unsandboxed_scene"
ACK_REFUSAL = ("opening the Studio runs the scene code in your browser without the Player sandbox, on the same origin as the Studio "
               f"API, and the scene source and props can leave this machine: send {ACK_FIELD}: true after the user confirmed")


def _require_ack(value: object) -> None:
    if value is not True:
        raise StudioError(StudioErrorCode.ACK_REQUIRED, ACK_REFUSAL)


def parse_open(raw: object) -> StudioPin:
    """Corps de `open` : le pin EXACT et l'accusé explicite (`acknowledge_unsandboxed_scene: true`) ; sans accusé, rien ne démarre."""

    if not isinstance(raw, Mapping) or set(raw) - {"prefab_id", "version", ACK_FIELD}:
        raise StudioError(StudioErrorCode.INVALID, f'the body must be exactly {{"prefab_id", "version", "{ACK_FIELD}"}}')
    pin = parse_pin({key: value for key, value in raw.items() if key != ACK_FIELD})
    _require_ack(raw.get(ACK_FIELD))
    return pin


def parse_ack_only(raw: object) -> None:
    """Corps de `restart` : exactement `{acknowledge_unsandboxed_scene: true}`."""

    if not isinstance(raw, Mapping) or set(raw) - {ACK_FIELD}:
        raise StudioError(StudioErrorCode.INVALID, f'the body must be exactly {{"{ACK_FIELD}": true}}')
    _require_ack(raw.get(ACK_FIELD))


# ------------------------------------------------------------------ cible maître (Slice 05 de master-project-studio-export)

SCENE_KIND = "scene"
MASTER_KIND = "variant_master"
PROJECT_ACK_FIELD = "acknowledge_unsandboxed_project"
PROJECT_ACK_REFUSAL = ("opening the whole variant in Remotion Studio runs EVERY scene's code in your browser without the Player sandbox, on "
                       "the same origin as the Studio API: send " + PROJECT_ACK_FIELD + ": true, bound to the project_key the user confirmed")
_MASTER_KEYS = frozenset({"kind", "presentation_id", "variant_id", "project_key", PROJECT_ACK_FIELD})
_PROJECT_KEY = re.compile(r"\Ampk_[0-9a-f]{24}\Z")
_PLAIN_ID = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")


@dataclass(frozen=True, slots=True)
class MasterRequest:
    """What a master body asks for: the variant and the `project_key` the user's confirmation showed (the acknowledgment binds to it)."""

    presentation_id: str
    variant_id: str
    project_key: str


@dataclass(frozen=True, slots=True)
class MasterTarget:
    """`variant_master` Studio target (`docs/remotion-master-project.md` § 9): one variant's master project, identified by
    `(presentation_id, variant_id, project_key)`; `variant_revision` is the basis it was planned from (not identity); `scenes` the mounted
    `(scene_id, pin)` in variant order."""

    presentation_id: str
    variant_id: str
    variant_revision: int
    project_key: str
    scenes: tuple[tuple[str, StudioPin], ...]

    @property
    def kind(self) -> str:
        return MASTER_KIND

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.presentation_id, self.variant_id, self.project_key

    def matches(self, request: MasterRequest) -> bool:
        return self.identity == (request.presentation_id, request.variant_id, request.project_key)

    @property
    def pins(self) -> tuple[StudioPin, ...]:
        """Each mounted pin once, in variant order (a pin shared by two scenes is announced once)."""

        return tuple(dict.fromkeys(pin for _, pin in self.scenes))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": MASTER_KIND, "presentation_id": self.presentation_id, "variant_id": self.variant_id,
                "variant_revision": self.variant_revision, "project_key": self.project_key,
                "scenes": [{"scene_id": scene_id, **pin.to_dict()} for scene_id, pin in self.scenes]}

    @classmethod
    def from_dict(cls, raw: object) -> "MasterTarget":
        """Strict read of a schema-2 `target` (`ValueError` / `StudioError` otherwise: the state is then unreadable, never guessed)."""

        if not isinstance(raw, Mapping) or raw.get("kind") != MASTER_KIND:
            raise ValueError("the studio state target is not a variant master")
        revision, scenes = raw.get("variant_revision"), raw.get("scenes")
        if type(revision) is not int or revision < 0 or not isinstance(scenes, list) or not scenes:
            raise ValueError("the studio state target has no revision or no scene")
        mounted: list[tuple[str, StudioPin]] = []
        for row in scenes:
            if not isinstance(row, Mapping) or not isinstance(row.get("scene_id"), str) or not _PLAIN_ID.fullmatch(row["scene_id"]):
                raise ValueError("a studio state target scene is malformed")
            mounted.append((row["scene_id"], parse_pin({"prefab_id": row.get("prefab_id"), "version": row.get("version")})))
        request = _master_ids(raw)
        return cls(request.presentation_id, request.variant_id, revision, request.project_key, tuple(mounted))


StudioTarget = StudioPin | MasterTarget


def _master_ids(raw: Mapping[str, Any]) -> MasterRequest:
    for key in ("presentation_id", "variant_id"):
        if not isinstance(raw.get(key), str) or not _PLAIN_ID.fullmatch(raw[key]):
            raise StudioError(StudioErrorCode.INVALID, f"{key} must be a plain identifier")
    if not isinstance(raw.get("project_key"), str) or not _PROJECT_KEY.fullmatch(raw["project_key"]):
        raise StudioError(StudioErrorCode.INVALID, "project_key must be the mpk_ key the confirmation showed")
    return MasterRequest(raw["presentation_id"], raw["variant_id"], raw["project_key"])


def _is_master_body(raw: object) -> bool:
    return isinstance(raw, Mapping) and ("kind" in raw or PROJECT_ACK_FIELD in raw)


def parse_master(raw: Mapping[str, Any]) -> MasterRequest:
    """Master body `{kind: "variant_master", presentation_id, variant_id, project_key, acknowledge_unsandboxed_project: true}`; mixing a
    scene field in is `remotion_studio_invalid`; no acknowledgment is `remotion_studio_ack_required` (nothing starts)."""

    if raw.get("kind") != MASTER_KIND or set(raw) - _MASTER_KEYS:
        raise StudioError(StudioErrorCode.INVALID, 'a master body is exactly {"kind": "variant_master", "presentation_id", "variant_id", '
                                                   f'"project_key", "{PROJECT_ACK_FIELD}"}} (no scene field)')
    request = _master_ids(raw)
    if raw.get(PROJECT_ACK_FIELD) is not True:
        raise StudioError(StudioErrorCode.ACK_REQUIRED, PROJECT_ACK_REFUSAL)
    return request


def parse_target(raw: object) -> StudioPin | MasterRequest:
    """Body of `open` / `sync` (without `discard_unpublished`): the scene body, unchanged byte for byte, or the master body (`kind`)."""

    return parse_master(raw) if _is_master_body(raw) else parse_open(raw)  # type: ignore[arg-type]


def parse_restart(raw: object) -> tuple[MasterRequest | None, bool]:
    """Body of `restart` -> (master request, discard): `{acknowledge_unsandboxed_scene: true}` exactly (the recorded scene: `None`;
    a scene restart never switches target, so it keeps its edits and takes no `discard_unpublished`), or a master body with the
    optional `discard_unpublished: true` (a restart to another key can set edits aside, § 9 of remotion-master-project.md)."""

    if _is_master_body(raw):
        from jarvis.domain.remotion_studio_workspace import split_discard  # local: the workspace module imports this one

        body, discard = split_discard(raw)
        return parse_master(body), discard
    parse_ack_only(raw)
    return None, False


def target_view(target: StudioTarget | None) -> dict[str, Any] | None:
    if target is None:
        return None
    if isinstance(target, MasterTarget):
        return {**target.to_dict(), "scene_count": len(target.scenes)}
    return {"kind": SCENE_KIND, **target.to_dict()}


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
    #: Slice 05 (master-project-studio-export): the `variant_master` target; exclusive with `pin` (schema 2 in `state.json`).
    master: MasterTarget | None = None
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
    #: QA Slice 12 (B1) : ce que le DERNIER lancement a mis de côté (`studio-edits`) parce que ce n'était pas la forme de l'espace
    #: (fichier ou dossier de premier niveau étranger, lien, jonction, lien dur). Remis à zéro à chaque lancement.
    set_aside: list[str] = field(default_factory=list)
    #: Empreinte (`listing_digest`) de la liste `modified_files` relevée ; jamais persistée (recalculée à chaque relevé).
    work_digest: str = ""
    egress_blocked: int = 0
    ws_open: int = 0
    #: Slice 05: `modified_files` of a master workspace, classified (`{path, class, scene_id}`); recomputed, never persisted.
    classified: list[dict[str, Any]] = field(default_factory=list)

    @property
    def target(self) -> StudioTarget | None:
        return self.master or self.pin

    def set_target(self, target: StudioTarget) -> None:
        self.pin, self.master = (None, target) if isinstance(target, MasterTarget) else (target, None)

    def to_payload(self) -> dict[str, Any]:
        """Schema 1 (byte-compatible with every earlier Core) for a scene target; schema 2 (`target` instead of `pin`) only for a master."""

        payload = self._scene_payload()
        if self.master is not None:
            del payload["pin"]
            payload.update(schema=2, target=self.master.to_dict())
        return payload

    def _scene_payload(self) -> dict[str, Any]:
        return {"schema": 1, "status": self.status.value, "pin": self.pin.to_dict() if self.pin else None,
                "source_digest": self.source_digest, "workspace_digest": self.workspace_digest, "composition": self.composition,
                "port": self.port, "process_ref": self.process_ref, "launch_id": self.launch_id, "started_at": self.started_at,
                "ready_at": self.ready_at, "synced_at": self.synced_at, "syncs": self.syncs, "restarts": self.restarts,
                "last_error_code": self.last_error_code, "last_error_detail": self.last_error_detail,
                "stop_reason": self.stop_reason, "diagnostics": self.diagnostics[-MAX_DIAGNOSTIC_LINES:], "edits_saved": self.edits_saved,
                "set_aside": self.set_aside[:MAX_SET_ASIDE_NAMED]}

    @classmethod
    def from_payload(cls, raw: object) -> "StudioState":
        """Relit `state.json` ; toute forme inattendue donne l'état arrêté (jamais un état deviné), l'appelant le journalise."""

        if not isinstance(raw, Mapping) or raw.get("schema") not in (1, 2) or type(raw.get("schema")) is not int:
            raise ValueError("unknown studio state schema")
        if raw["schema"] == 2:  # a master target (Slice 05): `target`, never `pin`
            if "pin" in raw:
                raise ValueError("a schema 2 studio state names a target, not a pin")
            state = cls(status=StudioStatus(str(raw.get("status"))), master=MasterTarget.from_dict(raw.get("target")))
        else:
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
        aside = raw.get("set_aside")
        state.set_aside = [bound_detail(str(item)) for item in aside[:MAX_SET_ASIDE_NAMED]] if isinstance(aside, list) else []
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
        "pin": state.pin.to_dict() if state.pin else None, "target": target_view(state.target),
        "source_digest": state.source_digest or None,
        "composition": state.composition,
        "started_at": state.started_at, "ready_at": state.ready_at, "synced_at": state.synced_at, "syncs": state.syncs,
        "restarts": state.restarts, "idle_timeout_s": idle_timeout_s, "idle_in_s": None if idle_in is None else round(idle_in, 1),
        "viewers": state.ws_open if ready else 0, "stop_reason": state.stop_reason or None,
        "last_error_code": state.last_error_code or None, "last_error_detail": state.last_error_detail or None,
        "diagnostics": [bound_detail(line) for line in state.diagnostics[-MAX_DIAGNOSTIC_LINES:]],
        # Slice 12 : l'espace de travail (modifiable) et sa base ; `modified_files` les nomme TOUS (la confirmation de publication les
        # montre tous), `unpublished` en est le compte, `digest` l'empreinte que la page renvoie avec `publish` (QA Slice 12, I1) ;
        # `set_aside` : ce que le dernier lancement a mis de côté parce que ce n'était pas la forme de l'espace (B1).
        "work_copy": {"modified_files": list(state.modified_files), "unpublished": len(state.modified_files),
                      "digest": state.work_digest or None, "set_aside": list(state.set_aside),
                      "base": state.pin.to_dict() if state.pin else None, "writable": True, "edits_saved": state.edits_saved,
                      # Slice 05: a master workspace's edits, classified (generated / scene / shared); `None` for a scene target.
                      "classified": None if state.master is None else [dict(row) for row in state.classified]},
        "egress_blocked": state.egress_blocked,
    }

"""Graphe d'architecture vivant : projection du runtime et mutations transactionnelles (docs/architecture-graph.md).

Le graphe n'a pas d'état propre. Il **projette** les réglages qui portent réellement chaque liaison :

| Liaison | Réglage (`binding`) | Relu |
| --- | --- | --- |
| Surface Live -> Core (Duplex) | `voice_architecture.config.brain_orchestration` | au démarrage de Voice |
| Surface -> Core (Simple, Front Brain) | `voice_surface.back_brain_delegation` | au démarrage de Voice |
| Core -> Tool Brain | `tool_brain.mode` (`JARVIS_TOOL_BRAIN` prioritaire) | au démarrage de Core |
| Core -> Sous-agents | gouvernée par la config du cerveau Core (`delegation`) | lecture seule ici |

et **observe** ce qui tourne (battement `.voice_runtime` de Voice, publication `tool-brain-ownership.json` du Tool
Brain, jeton de Core) pour dire honnêtement ce qui est déjà appliqué (`pending`).

Une écriture de liaison est une transaction : révision vérifiée, mutabilité vérifiée, nouvelle configuration
validée (la composition vocale cible doit se résoudre) **avant** l'écriture ; puis écriture atomique des réglages,
puis demande de bascule de Voice ; si la bascule ne peut pas être demandée, les réglages précédents sont réécrits.
Le retour est toujours le snapshot faisant foi, relu après coup.

Ce module vit dans le processus du Control Center (routes montées par la Slice 07) ; il ne parle ni à Core ni à
Voice autrement que par les fichiers du répertoire runtime qu'ils publient déjà.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Protocol

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.domain.architecture_graph import (
    APPLY_FAILED, CONNECTION_GOVERNED, CONNECTION_INCOMPATIBLE, CONNECTION_LOCKED, CONNECTION_NOT_REMOVABLE,
    CONNECTION_UNBINDABLE, CONNECTION_UNKNOWN, REQUEST_INVALID, REVISION_STALE,
    Activation, Applies, ArchitectureGraphError, ArchitectureSnapshot, Channel, Connection, GovernedBy, Mutability,
    Node, NodeKind, NodeState, Pending, Port, PortDirection, PortRef, VoiceArchitectureRef, connection_id,
    port_incompatibility, topology_revision, validate_snapshot,
)
from jarvis.domain.errors import ConfigurationError
from jarvis.domain.voice_architecture import DuplexVoiceConfig, FrontBrainVoiceConfig, VoiceConfigError
from jarvis.runtime.back_brain_delegation import (
    BACK_BRAIN_DELEGATION_FIELD, VOICE_SURFACE_SETTING, delegation_enabled,
)
from jarvis.runtime.tool_brain_ownership import (
    NO_PUBLICATION, SHUTDOWN, STALE_PUBLICATION, UNREADABLE_PUBLICATION, OwnershipView, read_ownership,
)
from jarvis.runtime.tool_brain_wiring import TOOL_BRAIN_MODE_ENV, TOOL_BRAIN_SETTING, resolve_mode, settings_mode
from jarvis.runtime.voice_architecture_config import (
    VOICE_ARCHITECTURE_SETTING, decode_voice_architecture, load_voice_architecture, store_voice_architecture,
)
from jarvis.runtime.voice_composition import VoiceComposition, resolve_voice_composition

SETTINGS_FILE = "control-center-settings.json"
VOICE_RUNTIME_FILE = ".voice_runtime"  # `VisualSignalBus.VOICE_RUNTIME_FILE`, publié chaque seconde par Voice
CORE_TOKEN_FILE = "core.token"  # `V2Settings.token_file` par défaut ; retiré à l'arrêt propre de Core
#: Même seuil que le Control Center (`VOICE_HEARTBEAT_MAX_AGE_S`) pour dire « Voice tourne ».
VOICE_HEARTBEAT_MAX_AGE_S = 5.0

# Identités stables des liaisons portées par un réglage (`binding`). `fixed:` = chemin du code, sans réglage.
BINDING_BRAIN_ORCHESTRATION = "voice_architecture.config.brain_orchestration"
BINDING_VOICE_DELEGATION = f"{VOICE_SURFACE_SETTING}.{BACK_BRAIN_DELEGATION_FIELD}"
BINDING_TOOL_BRAIN = f"{TOOL_BRAIN_SETTING}.mode"
BINDING_SUBAGENTS = "brain_config.core.delegation"
BINDING_VOICE_ARCH = "voice_architecture"

ARCHITECTURE_LABELS = {
    "simple": "Simple", "front_brain": "Front Brain", "duplex": "Duplex",
    "legacy": "Un tour par appui (legacy)", "continuous_brain": "Cerveau continu", "unknown": "Inconnue",
}
_ARCH_CHANGE_HINT = "Changez d'architecture dans Avancé › Architecture & compatibilité."


# ------------------------------------------------------------------ ports, adapters

class SettingsStore(Protocol):
    """Lecture/écriture du fichier de réglages du Control Center (contenu brut, sans valeurs par défaut)."""

    def read(self) -> dict[str, Any]: ...

    def write(self, settings: dict[str, Any]) -> None: ...


class FileSettingsStore:
    """`<runtime>/control-center-settings.json`, même discipline que `ControlCenter._write_settings` : écriture
    complète dans un temporaire puis remplacement atomique ; le temporaire (qui porte des secrets) ne survit pas
    à un échec. La Slice 07 peut lui substituer les méthodes du Control Center."""

    def __init__(self, runtime_root: Path | str) -> None:
        self.path = Path(runtime_root) / SETTINGS_FILE

    def read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}  # argued: no settings file is the normal first-run state, every default applies
        loaded = json.loads(self.path.read_text(encoding="utf-8"))  # a corrupt file must surface, not read as {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{self.path.name} n'est pas un objet JSON")
        return loaded

    def write(self, settings: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".graph.tmp")
        tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass  # argued: same as the Control Center, best effort on Windows where chmod is advisory
        try:
            replace_with_retry(tmp, self.path)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass  # argued: the replace failure is what the caller must see; the stray temp is reported by it
            raise


@dataclass(frozen=True, slots=True)
class RuntimeObservations:
    """Ce qui tourne, d'après les publications des processus. `voice` = rapport frais de Voice ou `None`."""

    voice: Mapping[str, object] | None
    tool_brain: OwnershipView
    core_running: bool


def observe_runtime(runtime_root: Path | str, *, wall: Callable[[], float] = time.time) -> RuntimeObservations:
    root = Path(runtime_root)
    voice: Mapping[str, object] | None = None
    try:
        report = json.loads((root / VOICE_RUNTIME_FILE).read_text(encoding="utf-8"))
        ts = report.get("ts") if isinstance(report, dict) else None
        if (isinstance(ts, (int, float)) and not isinstance(ts, bool)
                and wall() - float(ts) <= VOICE_HEARTBEAT_MAX_AGE_S):
            voice = report
    except (OSError, ValueError):
        voice = None  # argued: absent or half-replaced report reads as "Voice not running", as in the Control Center
    return RuntimeObservations(voice, read_ownership(root, wall=wall), (root / CORE_TOKEN_FILE).is_file())


def _live_tool_brain_mode(view: OwnershipView, core_running: bool) -> str | None:
    """Mode du Tool Brain qui tourne : `off` sans publication fraîche, `None` si on ne peut pas savoir."""

    if not core_running:
        return None
    if view.reason == UNREADABLE_PUBLICATION:
        return None
    if view.reason in (NO_PUBLICATION, STALE_PUBLICATION, SHUTDOWN):
        return "off"  # off ne construit ni ne publie rien ; une publication périmée est celle d'un ancien Core
    return view.mode if view.mode in ("shadow", "active") else "off"


# ------------------------------------------------------------------ projection

@dataclass(frozen=True, slots=True)
class _VoiceView:
    architecture: str
    source: str
    composition: VoiceComposition | None
    problem: str | None
    surface: str
    model: str
    stack: str


def _voice_view(settings: Mapping[str, Any], env: Mapping[str, str]) -> _VoiceView:
    try:
        composition = resolve_voice_composition(settings, environ=env)
        selection, problem = composition.selection, None
    except (VoiceConfigError, ConfigurationError) as exc:
        composition, problem = None, str(exc)
        try:
            selection = load_voice_architecture(settings, environ=env)
        except (VoiceConfigError, ConfigurationError):
            return _VoiceView("unknown", "settings", None, problem, "unknown", "", "")
    compat = selection.compatibility
    config = selection.config
    model = (config.reflex_model if isinstance(config, FrontBrainVoiceConfig) else config.conversation_model).model_id
    if compat is not None:
        return _VoiceView(compat.execution_mode, compat.architecture_source, composition, problem,
                          "gemini_live" if compat.stack_id == "gemini_live" else "realtime", model, compat.stack_id)
    surface = "live" if isinstance(config, DuplexVoiceConfig) else "realtime"
    return _VoiceView(config.architecture.value, "settings", composition, problem, surface, model, "openai_realtime")


def _flip_settings(settings: Mapping[str, Any], binding: str, enabled: bool) -> dict[str, Any]:
    """Copie des réglages où la liaison `binding` vaut `enabled` ; lève `VoiceConfigError` si invalide."""

    result = deepcopy(dict(settings))
    if binding == BINDING_BRAIN_ORCHESTRATION:
        selection = decode_voice_architecture(result[VOICE_ARCHITECTURE_SETTING])
        if not isinstance(selection.config, DuplexVoiceConfig):
            raise VoiceConfigError("voice_architecture_invalid", "brain_orchestration n'existe qu'en Duplex")
        store_voice_architecture(result, replace(selection.config, brain_orchestration=enabled))
    elif binding == BINDING_VOICE_DELEGATION:
        block = result.get(VOICE_SURFACE_SETTING)
        block = dict(block) if isinstance(block, dict) else {}
        block[BACK_BRAIN_DELEGATION_FIELD] = enabled
        result[VOICE_SURFACE_SETTING] = block
    elif binding == BINDING_TOOL_BRAIN:
        block = result.get(TOOL_BRAIN_SETTING)
        block = dict(block) if isinstance(block, dict) else {}
        previous = settings_mode(settings)
        # Rallumer reprend `active` s'il était persisté, sinon `shadow` (première marche du déploiement,
        # OPERATIONS.md) ; couper écrit `off`. Le choix shadow/active est un réglage du nœud, pas de la liaison.
        block["mode"] = ((previous.value if previous is not None and previous.value != "off" else "shadow")
                         if enabled else "off")
        result[TOOL_BRAIN_SETTING] = block
    else:
        raise KeyError(binding)
    return result


def _persisted_value(settings: Mapping[str, Any], binding: str, env: Mapping[str, str]) -> bool:
    if binding == BINDING_BRAIN_ORCHESTRATION:
        config = decode_voice_architecture(settings[VOICE_ARCHITECTURE_SETTING], validate_models=False).config
        return bool(getattr(config, "brain_orchestration", True))
    if binding == BINDING_VOICE_DELEGATION:
        return delegation_enabled(settings)
    if binding == BINDING_TOOL_BRAIN:
        return resolve_mode(settings, env)[0].value != "off"
    raise KeyError(binding)


def _configuration_id(settings: Mapping[str, Any], env: Mapping[str, str]) -> str | None:
    try:
        return resolve_voice_composition(settings, environ=env).configuration_id
    except (VoiceConfigError, ConfigurationError):
        return None


def _voice_link_state(settings: Mapping[str, Any], env: Mapping[str, str], binding: str,
                      running: Mapping[str, object] | None) -> tuple[bool, Pending | None]:
    """État vivant d'une liaison relue au démarrage de Voice.

    Voice publie l'identité de la configuration qu'il a chargée. Si elle diffère de celle des réglages, on
    cherche si c'est **cette** liaison qui l'explique (identité recalculée avec la valeur opposée) : alors le
    runtime vivant a l'ancienne valeur et la nouvelle est `pending`. Sinon (Voice arrêté, ou écart dû à un
    autre réglage), la valeur persistée est rendue sans `pending`.
    """

    persisted = _persisted_value(settings, binding, env)
    running_id = running.get("configuration_id") if running else None
    if not isinstance(running_id, str) or running_id == _configuration_id(settings, env):
        return persisted, None
    try:
        flipped = _configuration_id(_flip_settings(settings, binding, not persisted), env)
    except (VoiceConfigError, KeyError):
        flipped = None
    if flipped == running_id:
        return not persisted, Pending(persisted, Applies.VOICE_RESTART)
    return persisted, None


def _ports(*items: tuple[str, PortDirection, Channel, str]) -> tuple[Port, ...]:
    return tuple(Port(pid, direction, channel, family) for pid, direction, channel, family in items)


IN, OUT = PortDirection.IN, PortDirection.OUT


def project_architecture(settings: Mapping[str, Any], *, environ: Mapping[str, str] | None = None,
                         observations: RuntimeObservations) -> ArchitectureSnapshot:
    """Snapshot de l'architecture **effective** : seulement les nœuds réels de l'architecture vocale courante."""

    env = os.environ if environ is None else environ
    voice = _voice_view(settings, env)
    arch = voice.architecture
    voice_up = observations.voice is not None
    running_id = observations.voice.get("configuration_id") if observations.voice else None
    target_id = voice.composition.configuration_id if voice.composition else None

    if voice.problem:
        voice_state, voice_reason = NodeState.UNAVAILABLE, f"Configuration vocale refusée : {voice.problem}"
    elif not voice_up:
        voice_state, voice_reason = NodeState.INACTIVE, "Voice ne tourne pas (aucun battement récent)."
    elif isinstance(running_id, str) and target_id is not None and running_id != target_id:
        voice_state, voice_reason = NodeState.ACTIVE, "Une nouvelle configuration attend la relance de la voix."
    else:
        voice_state, voice_reason = NodeState.ACTIVE, ""
    endpoint_state = NodeState.ACTIVE if voice_up else NodeState.INACTIVE
    endpoint_reason = "" if voice_up else "Voice ne tourne pas."

    direct = arch in ("simple", "front_brain")
    delegate_channel = Channel.REQUEST if arch in ("duplex", "continuous_brain") else Channel.TOOL_CALL
    delegate_family = "brain_request" if delegate_channel is Channel.REQUEST else "brain_job"
    voice_ports = [("audio_in", IN, Channel.AUDIO, "audio"), ("audio_out", OUT, Channel.AUDIO, "audio"),
                   ("speech_in", IN, Channel.SPEECH, "speech")]
    if arch != "unknown":
        voice_ports.append(("delegate", OUT, delegate_channel, delegate_family))
    if arch == "front_brain":
        voice_ports += [("transcripts", OUT, Channel.EVENT, "transcript"), ("hints", IN, Channel.EVENT, "voice_hint")]
    surface_label = {"live": "GPT-Live", "realtime": "OpenAI Realtime", "gemini_live": "Gemini Live"}.get(voice.surface, "")
    nodes: list[Node] = [
        Node("mic", NodeKind.ENDPOINT, "Micro", endpoint_state, _ports(("audio_out", OUT, Channel.AUDIO, "audio")),
             Activation(False, "Entrée audio de la surface vocale."), endpoint_reason,
             endpoint_type="audio_input", process="voice"),
        Node("voice", NodeKind.BRAIN, "Voice Brain", voice_state, _ports(*voice_ports),
             Activation(False, "La surface vocale porte l'audio."), voice_reason,
             brain_type="voice_surface", process="voice", configurable=True,
             details={"surface": voice.surface, "surface_label": surface_label, "model": voice.model,
                      "stack": voice.stack}),
    ]
    if arch == "front_brain":
        config = voice.composition.selection.config if voice.composition else None
        nodes.append(Node(
            "luna", NodeKind.BRAIN, "Front Brain « Luna »", voice_state,
            _ports(("transcripts", IN, Channel.EVENT, "transcript"), ("hints", OUT, Channel.EVENT, "voice_hint")),
            Activation(False, "Fait partie de l'architecture Front Brain. " + _ARCH_CHANGE_HINT), voice_reason,
            brain_type="front_brain", process="voice", configurable=True,
            details={"analysis_model": config.analysis_model.model_id if isinstance(config, FrontBrainVoiceConfig) else "",
                     "speculative_deltas": bool(getattr(config, "speculative_deltas", False))}))
    core_state = NodeState.ACTIVE if observations.core_running else NodeState.UNAVAILABLE
    nodes.append(Node(
        "core", NodeKind.BRAIN, "Core Brain", core_state,
        _ports(("request", IN, Channel.REQUEST, "brain_request"), ("job", IN, Channel.TOOL_CALL, "brain_job"),
               ("speech", OUT, Channel.SPEECH, "speech"), ("events", OUT, Channel.EVENT, "tool_brain_wake"),
               ("agents", OUT, Channel.TOOL_CALL, "subagent_spawn")),
        Activation(False, "Core porte la conversation, le travail et la mémoire."),
        "" if observations.core_running else "Core n'est pas démarré (jeton de session absent).",
        brain_type="core", process="core", configurable=True))

    tool_mode, tool_source = resolve_mode(settings, env)
    live_mode = _live_tool_brain_mode(observations.tool_brain, observations.core_running)
    shown_mode = live_mode if live_mode is not None else tool_mode.value
    tool_state = {"active": NodeState.ACTIVE, "shadow": NodeState.SHADOW}.get(shown_mode, NodeState.INACTIVE)
    tool_reason = {
        "off": "Tool Brain coupé : Jarvis garde seul la main sur l'écran.",
        "shadow": "Mode observation : décide et enregistre, n'exécute rien.",
        "active": f"Mode actif ; écran : {observations.tool_brain.ownership} ({observations.tool_brain.reason}).",
    }[shown_mode]
    if live_mode is None:
        tool_reason += " État vivant inconnu : Core arrêté ou publication illisible."
    env_raw = str(env.get(TOOL_BRAIN_MODE_ENV, "") or "").strip()
    env_locked_reason = (f"Imposé par l'environnement ({TOOL_BRAIN_MODE_ENV}={env_raw}) ; retirez la variable "
                         "pour le régler ici.") if tool_source == "env" else ""
    nodes.append(Node(
        "tool_brain", NodeKind.BRAIN, "Tool Brain", tool_state, _ports(("wake", IN, Channel.EVENT, "tool_brain_wake")),
        Activation(tool_source != "env", env_locked_reason or "Mode lu au démarrage de Core."), tool_reason,
        brain_type="tool_brain", process="core", system=False, configurable=True,
        details={"mode": shown_mode, "persisted_mode": tool_mode.value, "mode_source": tool_source,
                 "modes": ["off", "shadow", "active"], "ownership": observations.tool_brain.ownership,
                 "ownership_reason": observations.tool_brain.reason}))
    nodes.append(Node(
        "subagents", NodeKind.POOL, "Sous-agents", NodeState.ACTIVE,
        _ports(("spawn", IN, Channel.TOOL_CALL, "subagent_spawn")),
        Activation(False, "Lancés à la demande par le cerveau ; rôles et modèles dans l'onglet Sous-agents."),
        "Lancés à la demande (outil Agent) ; rôle résolu par le registre des sous-agents.",
        process="cli", configurable=False))
    nodes.append(Node(
        "speakers", NodeKind.ENDPOINT, "Haut-parleurs", endpoint_state, _ports(("audio_in", IN, Channel.AUDIO, "audio")),
        Activation(False, "Sortie audio de la surface vocale."), endpoint_reason,
        endpoint_type="audio_output", process="voice"))

    def ref(node: str, port: str) -> PortRef:
        return PortRef(node, port)

    connections: list[Connection] = [
        Connection(ref("mic", "audio_out"), ref("voice", "audio_in"), Channel.AUDIO,
                   "Audio du micro vers la surface vocale", True, Mutability.REQUIRED_LOCKED,
                   "fixed:voice.capture", Applies.VOICE_RESTART,
                   locked_reason="La surface vocale ne fonctionne pas sans micro."),
        Connection(ref("voice", "audio_out"), ref("speakers", "audio_in"), Channel.AUDIO,
                   "Voix de JARVIS vers les haut-parleurs", True, Mutability.REQUIRED_LOCKED,
                   "fixed:voice.playback", Applies.VOICE_RESTART,
                   locked_reason="La surface vocale dit les réponses ; il n'y a pas de synthèse séparée."),
    ]
    if arch == "duplex":
        enabled, pending = _voice_link_state(settings, env, BINDING_BRAIN_ORCHESTRATION, observations.voice)
        connections.append(Connection(
            ref("voice", "delegate"), ref("core", "request"), Channel.REQUEST,
            "Tours cerveau : la voix confie la demande à Core (outils, sous-agents)", enabled, Mutability.TOGGLEABLE,
            BINDING_BRAIN_ORCHESTRATION, Applies.VOICE_RESTART, pending=pending,
            impact_when_disabled=("La voix répond seule ; une demande d'action retombe sur l'analyse spéculative "
                                  "de Core, sans outils ni sous-agents.")))
    elif direct and voice.composition is not None:
        enabled, pending = _voice_link_state(settings, env, BINDING_VOICE_DELEGATION, observations.voice)
        connections.append(Connection(
            ref("voice", "delegate"), ref("core", "job"), Channel.TOOL_CALL,
            "Travail de fond : la voix confie la demande à Core (outil back_brain_delegate)", enabled,
            Mutability.TOGGLEABLE, BINDING_VOICE_DELEGATION, Applies.VOICE_RESTART, pending=pending,
            impact_when_disabled=("La voix traite seule : plus d'outil back_brain_delegate, aucun travail de fond, "
                                  "outil Core ni sous-agent.")))
    elif arch == "continuous_brain":
        connections.append(Connection(
            ref("voice", "delegate"), ref("core", "request"), Channel.REQUEST,
            "Chaque tour part au cerveau Core", True, Mutability.REQUIRED_LOCKED, BINDING_VOICE_ARCH,
            Applies.VOICE_RESTART,
            locked_reason="En mode cerveau continu, chaque tour part à Core. " + _ARCH_CHANGE_HINT))
    elif arch == "legacy":
        connections.append(Connection(
            ref("voice", "delegate"), ref("core", "job"), Channel.TOOL_CALL,
            "La voix confie le travail à l'agent du Control Center (claude_task)", True,
            Mutability.REQUIRED_LOCKED, BINDING_VOICE_ARCH, Applies.VOICE_RESTART,
            locked_reason="En mode legacy, le travail passe toujours par l'agent du Control Center. " + _ARCH_CHANGE_HINT))
    if arch == "front_brain":
        for source, target, purpose in ((ref("voice", "transcripts"), ref("luna", "transcripts"),
                                         "Transcriptions vers l'analyse de Luna"),
                                        (ref("luna", "hints"), ref("voice", "hints"),
                                         "Indications de Luna vers la surface vocale")):
            connections.append(Connection(source, target, Channel.EVENT, purpose, True, Mutability.REQUIRED_LOCKED,
                                          BINDING_VOICE_ARCH, Applies.VOICE_RESTART,
                                          locked_reason="Fait partie de l'architecture Front Brain. " + _ARCH_CHANGE_HINT))
    connections.append(Connection(
        ref("core", "speech"), ref("voice", "speech_in"), Channel.SPEECH,
        "Parole demandée par Core (rappels, résultats de travail)", True, Mutability.REQUIRED_LOCKED,
        "fixed:brain.speech.requested", Applies.LIVE,
        locked_reason="La parole de Core passe toujours par la surface vocale."))

    tool_enabled_persisted = tool_mode.value != "off"
    if live_mode is None:
        tool_enabled, tool_pending = tool_enabled_persisted, None
    else:
        tool_enabled = live_mode != "off"
        tool_pending = (Pending(tool_enabled_persisted, Applies.CORE_RESTART)
                        if tool_enabled != tool_enabled_persisted else None)
    connections.append(Connection(
        ref("core", "events"), ref("tool_brain", "wake"), Channel.EVENT,
        "Réveils du Tool Brain : tours, intentions d'interface, parole, changements d'écran", tool_enabled,
        Mutability.REQUIRED_LOCKED if tool_source == "env" else Mutability.TOGGLEABLE,
        BINDING_TOOL_BRAIN, Applies.CORE_RESTART, locked_reason=env_locked_reason, pending=tool_pending,
        impact_when_disabled="Le Tool Brain ne se réveille plus ; Jarvis garde seul la main sur l'écran."))
    connections.append(Connection(
        ref("core", "agents"), ref("subagents", "spawn"), Channel.TOOL_CALL,
        "Lancement de sous-agents (outil Agent) pour les rôles du registre", True, Mutability.GOVERNED,
        BINDING_SUBAGENTS, None, governed_by=GovernedBy("brain_config", "core", "delegation"),
        impact_when_disabled="Gouvernée par la tendance de délégation du cerveau Core (fenêtre du cerveau)."))

    snapshot = ArchitectureSnapshot(
        topology_revision(_revision_inputs(settings, env)),
        VoiceArchitectureRef(arch, ARCHITECTURE_LABELS.get(arch, arch), source=voice.source),
        tuple(nodes), tuple(connections))
    validate_snapshot(snapshot)
    return snapshot


def _revision_inputs(settings: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, object]:
    keys = (VOICE_ARCHITECTURE_SETTING, "voice_arch", "voice_stack", VOICE_SURFACE_SETTING, TOOL_BRAIN_SETTING)
    return {"settings": {key: settings.get(key) for key in keys},
            "env": {name: str(env.get(name, "") or "").strip()
                    for name in (TOOL_BRAIN_MODE_ENV, "JARVIS_VOICE_ARCH", "JARVIS_VOICE_STACK")}}


# ------------------------------------------------------------------ mutation

VoiceSwitchRequester = Callable[[Mapping[str, Any], Mapping[str, Any], RuntimeObservations], "dict[str, object] | None"]


def request_voice_switch(runtime_root: Path | str, env: Mapping[str, str]) -> VoiceSwitchRequester:
    """Demande à Voice de recharger sa configuration, selon la règle de `ControlCenter` (POST /api/settings) :
    source = configuration publiée par Voice si fraîche, sinon celle des réglages précédents ; rien si l'identité
    ne change pas ou si la cible n'a pas de modèle démarrable.

    TODO(Slice 07) : le Control Center a la même règle en ligne ; la monter une seule fois (ce module ou une
    fonction partagée) au moment de brancher les routes.
    """

    def issue(previous: Mapping[str, Any], updated: Mapping[str, Any],
              observations: RuntimeObservations) -> dict[str, object] | None:
        from jarvis.runtime.voice_switch import VoiceSwitchBus
        target = resolve_voice_composition(updated, environ=env)
        try:
            before = resolve_voice_composition(previous, environ=env)
        except (VoiceConfigError, ConfigurationError):
            return None  # same as the Control Center: no startable previous composition, nothing to switch from
        config = target.selection.config
        model = (config.reflex_model if isinstance(config, FrontBrainVoiceConfig) else config.conversation_model).model_id
        running = observations.voice.get("configuration_id") if observations.voice else None
        source = running if isinstance(running, str) else before.configuration_id
        if source == target.configuration_id or not model:
            return None
        issued = VoiceSwitchBus(Path(runtime_root)).request(
            source_configuration_id=source, target_configuration_id=target.configuration_id,
            target_architecture=config.architecture.value, target_model=model)
        return {"request_id": issued.request_id, "source_configuration_id": source,
                "target_configuration_id": target.configuration_id,
                "target_architecture": config.architecture.value, "target_model": model}

    return issue


_VOICE_BINDINGS = frozenset({BINDING_BRAIN_ORCHESTRATION, BINDING_VOICE_DELEGATION})
_WRITABLE_BINDINGS = _VOICE_BINDINGS | {BINDING_TOOL_BRAIN}


@dataclass(frozen=True, slots=True)
class MutationResult:
    snapshot: ArchitectureSnapshot
    changed: bool
    voice_switch: Mapping[str, object] | None = None


class ArchitectureGraphService:
    """Snapshot et écritures de topologie. Les écritures sont sérialisées dans le processus (verrou) ;
    une écriture concurrente d'une autre page est détectée par la révision calculée."""

    def __init__(self, runtime_root: Path | str, *, store: SettingsStore | None = None,
                 environ: Mapping[str, str] | None = None,
                 observe: Callable[[], RuntimeObservations] | None = None,
                 voice_switch: VoiceSwitchRequester | None = None, journal: Any = None) -> None:
        self.runtime_root = Path(runtime_root)
        self.store = store or FileSettingsStore(self.runtime_root)
        self._environ = environ
        self._observe = observe or (lambda: observe_runtime(self.runtime_root))
        self._voice_switch = voice_switch
        self.journal = journal
        self._lock = threading.Lock()

    @property
    def environ(self) -> Mapping[str, str]:
        return os.environ if self._environ is None else self._environ

    def snapshot(self) -> ArchitectureSnapshot:
        return project_architecture(self.store.read(), environ=self.environ, observations=self._observe())

    def set_connection_enabled(self, conn_id: str, *, base_revision: object, enabled: object) -> MutationResult:
        if type(enabled) is not bool:
            raise ArchitectureGraphError(REQUEST_INVALID, "« enabled » doit être un booléen.")
        with self._lock:
            settings = self.store.read()
            observations = self._observe()
            current = project_architecture(settings, environ=self.environ, observations=observations)
            conn = self._writable(current, conn_id, base_revision)
            if _persisted_value(settings, conn.binding, self.environ) == enabled:
                self._emit("architecture.connection.unchanged", "Liaison déjà dans l'état demandé",
                           {"connection_id": conn_id, "enabled": enabled, "binding": conn.binding})
                return MutationResult(current, False)
            return self._commit(settings, observations, conn, enabled)

    def create_connection(self, *, base_revision: object, source: object, target: object,
                          channel: object) -> MutationResult:
        with self._lock:
            current = self.snapshot()
            self._check_revision(current, base_revision)
            src, dst = _port_ref(source, "source"), _port_ref(target, "target")
            src_node, dst_node = current.node(src.node), current.node(dst.node)
            if src_node is None or dst_node is None:
                raise ArchitectureGraphError(CONNECTION_UNKNOWN, "Nœud absent de l'architecture courante.")
            src_port, dst_port = src_node.port(src.port), dst_node.port(dst.port)
            problem = port_incompatibility(src_port, dst_port)
            if problem is None and str(channel) != src_port.channel.value:  # type: ignore[union-attr]
                problem = f"Canal demandé « {channel} » différent de celui des ports ({src_port.channel.value})."  # type: ignore[union-attr]
            if problem:
                raise ArchitectureGraphError(CONNECTION_INCOMPATIBLE, problem)
            existing = current.connection(connection_id(src, dst))
            if existing is not None:
                raise ArchitectureGraphError(CONNECTION_UNBINDABLE, "Cette liaison existe déjà ; "
                                             + ("activez-la plutôt." if existing.mutability is Mutability.TOGGLEABLE
                                                else "elle ne se recrée pas."))
            raise ArchitectureGraphError(CONNECTION_UNBINDABLE, "Ports compatibles, mais aucun mécanisme du runtime "
                                         "ne peut porter cette liaison : elle n'aurait aucun effet réel.")

    def delete_connection(self, conn_id: str, *, base_revision: object) -> MutationResult:
        with self._lock:
            current = self.snapshot()
            conn = self._writable(current, conn_id, base_revision)
            if conn.mutability is not Mutability.CREATABLE_REMOVABLE:
                raise ArchitectureGraphError(CONNECTION_NOT_REMOVABLE,
                                             "Cette liaison ne se supprime pas ; désactivez-la plutôt.")
            raise ArchitectureGraphError(CONNECTION_UNBINDABLE, "Aucune liaison supprimable n'existe dans ce runtime.")

    # -- internals

    @staticmethod
    def _check_revision(current: ArchitectureSnapshot, base_revision: object) -> None:
        if base_revision != current.revision:
            raise ArchitectureGraphError(REVISION_STALE, "L'architecture a changé depuis votre lecture ; "
                                         "relisez-la avant de modifier une liaison.")

    def _writable(self, current: ArchitectureSnapshot, conn_id: str, base_revision: object) -> Connection:
        self._check_revision(current, base_revision)
        conn = current.connection(conn_id)
        if conn is None:
            raise ArchitectureGraphError(CONNECTION_UNKNOWN, f"Liaison inconnue dans l'architecture courante : {conn_id}.")
        if conn.mutability is Mutability.REQUIRED_LOCKED:
            raise ArchitectureGraphError(CONNECTION_LOCKED, conn.locked_reason)
        if conn.mutability is Mutability.GOVERNED:
            raise ArchitectureGraphError(CONNECTION_GOVERNED, "Liaison gouvernée par la tendance de délégation du "
                                         "cerveau : réglez-la dans la fenêtre du cerveau.")
        if conn.binding not in _WRITABLE_BINDINGS:  # a toggleable link without a writer is a projection defect
            raise ArchitectureGraphError(CONNECTION_UNBINDABLE, f"Aucun écrivain pour {conn.binding}.")
        return conn

    def _commit(self, settings: dict[str, Any], observations: RuntimeObservations, conn: Connection,
                enabled: bool) -> MutationResult:
        context = {"connection_id": conn.id, "binding": conn.binding, "enabled": enabled}
        try:
            updated = _flip_settings(settings, conn.binding, enabled)
            # Validation complète avant toute écriture : projection cohérente, et pour une liaison vocale,
            # composition cible démarrable (sinon Voice refuserait de démarrer sur ces réglages).
            project_architecture(updated, environ=self.environ, observations=observations)
            if conn.binding in _VOICE_BINDINGS:
                resolve_voice_composition(updated, environ=self.environ)
        except (VoiceConfigError, ConfigurationError, ValueError) as exc:
            self._emit("architecture.connection.rejected", "Configuration cible refusée, rien d'écrit",
                       {**context, "code": getattr(exc, "code", type(exc).__name__)}, level="warning")
            raise ArchitectureGraphError(APPLY_FAILED, f"Configuration refusée, rien n'a été écrit : {exc}") from exc
        try:
            self.store.write(updated)
        except OSError as exc:
            self._emit("architecture.connection.write_failed", "Écriture des réglages impossible, rien d'écrit",
                       {**context, "error_class": type(exc).__name__}, level="error")
            raise ArchitectureGraphError(APPLY_FAILED, f"Réglages non enregistrés : {type(exc).__name__}: {exc}") from exc
        switch = None
        if conn.binding in _VOICE_BINDINGS:
            requester = self._voice_switch or request_voice_switch(self.runtime_root, self.environ)
            try:
                switch = requester(settings, updated, observations)
            except (OSError, ValueError, VoiceConfigError, ConfigurationError) as exc:
                self._rollback(settings, context, exc)
                raise ArchitectureGraphError(APPLY_FAILED, "La voix n'a pas pu être relancée sur la nouvelle "
                                             f"configuration ; réglage précédent rétabli ({type(exc).__name__}).") from exc
        self._emit("architecture.connection.updated", "Liaison du graphe modifiée",
                   {**context, "applies": conn.applies.value if conn.applies else None,
                    "voice_switch_request_id": switch.get("request_id") if switch else None})
        if switch:
            self._emit("voice.switch.requested", "Voice architecture switch requested", dict(switch))
        return MutationResult(self.snapshot(), True, switch)

    def _rollback(self, previous: dict[str, Any], context: Mapping[str, object], cause: Exception) -> None:
        try:
            self.store.write(previous)
        except OSError as exc:
            self._emit("architecture.connection.rollback_failed",
                       "Bascule de Voice impossible ET réglages précédents non rétablis : état à vérifier",
                       {**context, "error_class": type(exc).__name__, "cause_class": type(cause).__name__},
                       level="error")
            raise ArchitectureGraphError(APPLY_FAILED, "Bascule de Voice impossible, et les réglages précédents n'ont "
                                         f"pas pu être rétablis ({type(exc).__name__}) : relisez l'architecture.") from exc
        self._emit("architecture.connection.rolled_back", "Bascule de Voice impossible, réglages précédents rétablis",
                   {**context, "cause_class": type(cause).__name__}, level="error")

    def _emit(self, kind: str, message: str, data: Mapping[str, object], *, level: str = "info") -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001
            pass  # argued: the journal is evidence, never authority over a committed or refused write


def _port_ref(raw: object, name: str) -> PortRef:
    if not isinstance(raw, dict) or not isinstance(raw.get("node"), str) or not isinstance(raw.get("port"), str):
        raise ArchitectureGraphError(REQUEST_INVALID, f"« {name} » doit être {{node, port}}.")
    return PortRef(raw["node"], raw["port"])

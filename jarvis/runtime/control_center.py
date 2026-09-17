from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlparse
import uuid

from aiohttp import web

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.adapters.webrtc_echo import echo_cancellation_installed
from jarvis.domain.errors import ConfigurationError
from jarvis.domain.voice_architecture import VoiceConfigError
from jarvis.runtime.voice_architecture_config import (
    parse_voice_mode, store_voice_architecture, voice_architecture_query,
)
from jarvis.runtime.voice_capabilities import VoiceCapabilityRegistry, default_voice_registry
from jarvis.domain.speaker import (
    DEFAULT_OWNER_BUFFER_MS,
    MAX_OWNER_BUFFER_MS,
    MIN_OWNER_BUFFER_MS,
    AuthorizationStatus,
    ConversationAuthorization,
    ConversationAuthorizationError,
    ConversationMode,
    SpeakerVerificationMode,
    VerifierAvailability,
    assess_authorization,
)
from jarvis.domain.routing import RoutingError
from jarvis.domain.v2 import BRAIN_NOT_ADDRESSED_ANSWER, AddressingDecision
from jarvis.runtime.audio_devices import AudioDiagnosticError, SoundDeviceAudioDiagnostics, normalize_device_id
from jarvis.runtime import (
    agent_behavior,
    agent_routing,
    barehands_test_mode as barehands,
    cli_catalog,
    credentials as creds,
    shortcuts as shortcut_registry,
    voice_settings_schema,
    voice_stack,
)
from jarvis.runtime.background_events import (
    CATEGORIES as BACKGROUND_CATEGORIES,
    MAX_ENTRIES,
    BackgroundEventLedger,
    TraceFollower,
    follow,
)
from jarvis.runtime.catalog_view import CatalogViewService, ProviderCatalogSnapshot, SUBAGENT_ROLES, VOICE_ROLES
from jarvis.runtime.claude_local import DEFAULT_PERMISSION_MODE, PERMISSION_MODES, ClaudeLocalAgent, normalize_permission_mode
from jarvis.runtime.codex_local import CodexLocalAgent, normalize_sandbox_mode
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.live_status import CoreLiveStatusView, project_live_status
from jarvis.runtime.model_catalog import CatalogError, ModelCatalog, filter_by_role
from jarvis.runtime.owner_voice import effective_verifier_settings, probe_remedy
from jarvis.runtime.self_dev import SelfDevError, apply_gate as apply_self_dev_gate, load_gate as load_self_dev_gate
from jarvis.runtime.scene_settings import SceneSettingsError, apply_gate as apply_scene_gate, load_gate as load_scene_gate
from jarvis.runtime.self_dev_service import SelfDevelopmentService
from jarvis.runtime.owner_voice import probe_from_settings as probe_owner_verifier
from jarvis.runtime.visual_signals import VisualSignalBus
from jarvis.runtime.work_brief import render_work_brief
from jarvis.runtime.work_ingress import TrackerWorkObserver, WorkIngressForwarder
from jarvis.runtime.work_view import NOT_CONFIGURED, CoreWorkView, unavailable_payload
from jarvis.protocol import scene_wire
from jarvis.protocol.strict_json import loads_strict_json
from jarvis.runtime.display_mcp import DisplayMcpTarget
from jarvis.runtime.scene_view import (
    CoreSceneView,
    ReportThrottle,
    SceneActorForbidden,
    unavailable_patches_payload,
    unavailable_snapshot_payload,
    user_command,
)
from jarvis.v2_config import (
    CONVERSATION_AUTHORIZATION_SETTINGS,
    MIN_ACTIVE_TIMEOUT_S,
    OWNER_EVIDENCE_MS_SETTING,
    OWNER_PROFILE_PATH_SETTING,
    OWNER_SHORT_EVIDENCE_MS_SETTING,
    OWNER_SHORT_MARGIN_SETTING,
    OWNER_THRESHOLD_SETTING,
    REALTIME_VOICES,
    SPEAKER_VERIFIER_SETTINGS,
    TURN_MODES,
    VoiceArchitecture,
    conversation_authorization_settings,
    default_voice_arch,
    parse_active_timeout,
    parse_conversation_authorization,
    parse_speaker_verifier_settings,
    parse_voice_arch,
)


VOICE_HEARTBEAT_MAX_AGE_S = 5.0
#: En-tête d'un refus d'enregistrement (HTTP 400) portant son code stable.
SETTINGS_ERROR_CODE_HEADER = "X-Jarvis-Error-Code"

#: Logique pure du panneau Agents, gardée à part pour être exécutée par les
#: tests (node) et insérée dans la page à la place de ce repère.
WORK_SCRIPT_FILE = "control_center_work.js"
WORK_SCRIPT_MARKER = "/*__CONTROL_CENTER_WORK_JS__*/"
LIVE_SCRIPT_FILE = "control_center_live.js"
LIVE_SCRIPT_MARKER = "/*__CONTROL_CENTER_LIVE_JS__*/"
CATALOG_SCRIPT_FILE = "control_center_catalog.js"
CATALOG_SCRIPT_MARKER = "/*__CONTROL_CENTER_CATALOG_JS__*/"
#: Pointeur à mains nues (Barehands, mode test) : logique pure testée par node,
#: plus son branchement navigateur. Même insertion que les scripts ci-dessus.
BAREHANDS_SCRIPT_FILE = "control_center_barehands.js"
BAREHANDS_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_JS__*/"
#: Client pur de la scène constellation (Slice 03) : application ordonnée des
#: patchs et détection de resynchronisation. Il n'expose que
#: `window.JarvisSceneClient` et ne touche pas au DOM ; le rendu vient en Slice 05.
SCENE_SCRIPT_FILE = "control_center_scene.js"
SCENE_SCRIPT_MARKER = "/*__CONTROL_CENTER_SCENE_JS__*/"
#: Rendu de la scène (Slice 05) : repère, AutoResolver et modèle de vue purs
#: (`window.JarvisSceneLayout`), puis boucle de lecture, validation des
#: placements et dessin (`window.JarvisScene`), inerte tant que `scene.enabled`
#: est faux dans `/api/status`.
SCENE_LAYOUT_SCRIPT_FILE = "control_center_scene_layout.js"
SCENE_LAYOUT_SCRIPT_MARKER = "/*__CONTROL_CENTER_SCENE_LAYOUT_JS__*/"
SCENE_PAGE_SCRIPT_FILE = "control_center_scene_page.js"
SCENE_PAGE_SCRIPT_MARKER = "/*__CONTROL_CENTER_SCENE_PAGE_JS__*/"
#: Interactions de l'utilisateur (Slice 08) : géométrie, menu, archivage
#: groupé, affichage optimiste (`window.JarvisSceneInteract`, logique pure).
SCENE_INTERACT_SCRIPT_FILE = "control_center_scene_interact.js"
SCENE_INTERACT_SCRIPT_MARKER = "/*__CONTROL_CENTER_SCENE_INTERACT_JS__*/"

#: Architectures vocales proposées dans l'onglet « Mode vocal ». Comme le reste
#: de l'écran, leur libellé vit ici et non dans la page. `{key}` est remplacé
#: par la touche de réveil courante.
_VOICE_ARCH_CHOICES: tuple[tuple[VoiceArchitecture, str, str], ...] = (
    (
        VoiceArchitecture.LEGACY,
        "Un tour par appui",
        "Un appui sur {key}, une question, une réponse, puis JARVIS repasse en arrière-plan. "
        "Le micro est fermé pendant que JARVIS parle.",
    ),
    (
        VoiceArchitecture.CONTINUOUS_BRAIN,
        "Conversation continue (jusqu'à {key})",
        "La session couvre plusieurs tours et le micro reste ouvert jusqu'à un nouvel appui sur "
        "{key} ou le délai d'inactivité (jamais s'il vaut 0). Exige la pile OpenAI Realtime et la fin de tour "
        "automatique ; préférez un casque, l'écho des haut-parleurs n'est pas filtré.",
    ),
)

#: Réglages du vérificateur que la page peut écrire (Solo Owner, tâche 08).
#: Pas `owner_profile_path` : un chemin arbitraire écrit depuis un navigateur
#: ferait lire — ou écraser, à l'enrôlement — n'importe quel fichier. Il reste
#: affiché en lecture seule ; le changer passe par le fichier de réglages.
_UI_VERIFIER_SETTINGS: tuple[str, ...] = (
    OWNER_THRESHOLD_SETTING,
    OWNER_EVIDENCE_MS_SETTING,
    OWNER_SHORT_EVIDENCE_MS_SETTING,
    OWNER_SHORT_MARGIN_SETTING,
)
_FLOAT_VERIFIER_SETTINGS = frozenset({OWNER_THRESHOLD_SETTING, OWNER_SHORT_MARGIN_SETTING})

#: État de l'annulation d'écho (tâche 08) : message affiché pour chaque code,
#: qu'il vienne de la sonde des réglages ou de ce que Voice a publié.
_AEC_PROBLEMS: dict[str, str] = {
    "aec_not_applicable": (
        "Sans objet : en « Un tour par appui », le micro est fermé pendant que JARVIS parle ; "
        "l'annulation d'écho ne sert qu'à la conversation continue (pile OpenAI Realtime)."
    ),
    "aec_disabled": (
        "Annulation d'écho désactivée dans les réglages de la pile : garde d'écho seule. JARVIS ne "
        "s'entend pas lui-même, mais il faut parler plus fort que lui pour le couper."
    ),
    "aec_not_installed": (
        "Annulation d'écho demandée, mais LiveKit (AEC3) n'est pas installé : Voice tournera en mode "
        "dégradé, avec la garde d'écho seule (il faudra parler plus fort que JARVIS pour le couper). "
        "Installez l'extra : .\\.venv\\Scripts\\python.exe -m pip install -e \".[voice]\", puis relancez Voice."
    ),
    "aec_unavailable": (
        "Annulation d'écho demandée, mais Voice n'a pas pu la construire (LiveKit AEC3 absent ou en échec "
        "au chargement) : mode dégradé, garde d'écho seule. Voir voice.duplex dans la trace."
    ),
    "aec_failed": (
        "L'annulation d'écho est tombée en cours de session : Voice continue en mode dégradé, avec la "
        "garde d'écho seule, jusqu'à son redémarrage (voice.duplex, code duplex_aec_failed, dans la trace)."
    ),
    "duplex_capture_unavailable": (
        "Traitement duplex du micro indisponible : mode dégradé, le micro part brut, sans annulation ni "
        "garde d'écho (voice.duplex_unavailable dans la trace). Relancez Voice."
    ),
}

#: Champs de l'état public de Core rendus dans la consigne, dans cet ordre.
#: Liste blanche assumée : le contexte est lu clé par clé, donc un champ inconnu
#: — ou ajouté un jour à la projection publique — n'atteint pas le modèle tant
#: que personne ne l'a inscrit ici. La consigne reste courte ; un état complet
#: recopié serait du bruit qui noie la demande.
_BRIEF_STATE_FIELDS: tuple[tuple[str, str], ...] = (
    ("current_user_intent", "Intention courante"),
    ("conversation_goal", "Objectif de la conversation"),
    ("active_work_ids", "Travaux en cours"),
    ("known_public_facts", "Déjà dit à l'utilisateur"),
    ("unresolved_questions", "Questions en suspens"),
)


#: Rappel ajouté à la consigne quand « Travaux en cours » n'est pas vide. La
#: règle complète vit dans le prompt système du brain (`BRAIN_SYSTEM_PROMPT`).
BRIEF_DELEGATION_REMINDER = (
    "Rappel : du travail est déjà en cours. Si cette demande n'a pas de réponse "
    "immédiate, lance-la en sous-agent d'arrière-plan (Agent, run_in_background) "
    "et réponds en une phrase ; ne la traite pas dans ce tour."
)


def _brief_value(value: Any) -> str:
    """Rendre un champ d'état sur une ligne, ou rien s'il est vide."""

    if isinstance(value, (list, tuple)):
        return " | ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def build_agent_brief(context: dict[str, Any], text: str) -> str:
    """Préfixer la demande de ce que Core sait, et de ce dont il doute.

    C'est ici que la marque d'adressage devient utile : un champ muet dans une
    charge utile n'apprend rien à un modèle, seule une consigne le fait. Sur un
    tour `uncertain`, l'agent reçoit donc l'autorisation explicite de conclure
    que le propos ne lui était pas adressé et de ne rien faire (Décision 44).

    Le Control Center possède l'agent (Décision 23) : la formulation de ce qu'on
    lui dit lui appartient, et Core n'envoie que des données.
    """

    lines = ["[Contexte Jarvis — lis-le avant de répondre]"]
    if str(context.get("addressing") or "") == AddressingDecision.UNCERTAIN.value:
        lines.append(
            "Adressage : INCERTAIN. La surface vocale n'a pas su si cette phrase t'était "
            "adressée ; elle a pu être captée à côté (conversation entre tiers, télévision, "
            "pensée à voix haute). C'est à toi d'en juger. Si ce n'était pas une demande "
            "pour toi, n'entreprends rien, n'utilise aucun outil, et réponds exactement "
            f"ceci et rien d'autre : {BRAIN_NOT_ADDRESSED_ANSWER}"
        )
    else:
        lines.append("Adressage : direct. La demande t'est adressée.")
    state = context.get("state")
    if isinstance(state, dict):
        for key, label in _BRIEF_STATE_FIELDS:
            rendered = _brief_value(state.get(key))
            if rendered:
                lines.append(f"{label} : {rendered}")
        # Du travail tourne déjà : c'est exactement le moment où un tour long
        # ferait attendre l'utilisateur. Rappel bref de la consigne système.
        if _brief_value(state.get("active_work_ids")):
            lines.append(BRIEF_DELEGATION_REMINDER)
    # Travail en cours tenu par Core (handoff work-state, tâche 12).
    lines.extend(render_work_brief(context.get("work")))
    lines.append("[Demande]")
    lines.append(text)
    return "\n".join(lines)


class ControlCenter:
    def __init__(
        self,
        *,
        runtime_root: Path,
        project_root: Path,
        visualizer_url: str | None = None,
        audio_diagnostics: SoundDeviceAudioDiagnostics | None = None,
        work_ingress: WorkIngressForwarder | None = None,
        work_view: CoreWorkView | None = None,
        live_view: CoreLiveStatusView | None = None,
        scene_view: CoreSceneView | None = None,
        display_mcp: DisplayMcpTarget | None = None,
        voice_registry: VoiceCapabilityRegistry | None = None,
        barehands_vendor_root: Path | None = None,
    ) -> None:
        self.runtime_root = runtime_root
        self.project_root = project_root
        self.visualizer_url = visualizer_url
        # Assets MediaPipe vendorisés par le bootstrap Barehands, servis à la
        # page pour le mode test. Absents, le mode test le dit et ne démarre pas.
        self.barehands_vendor_root = (
            barehands_vendor_root if barehands_vendor_root is not None else barehands.vendor_root(project_root)
        )
        self.journal = RuntimeJournal(runtime_root)
        # Notification discrète des événements d'arrière-plan (retour
        # utilisateur du 16/09/2026). Alimentée par la trace, le seul point
        # où les trois processus — UI, voix, Core — se rejoignent.
        self.background = BackgroundEventLedger()
        self._background_trace = TraceFollower(self.journal.trace_path)
        self.audio_diagnostics = audio_diagnostics or SoundDeviceAudioDiagnostics()
        self._audio_test_lock = asyncio.Lock()
        self.settings_path = runtime_root / "control-center-settings.json"
        self.catalog = ModelCatalog(runtime_root / "model-catalog.json")
        self._catalog_view_service = CatalogViewService()
        self._voice_registry = voice_registry
        # Relais des sous-tâches Claude vers l'état de travail Core (handoff
        # work-state, tâche 11). Absent, rien ne part : Core ne connaît pas
        # ces sous-tâches, et `/api/work` le dit (`subtasks_supported`).
        self.work_ingress = work_ingress
        # Lecture seule de l'état de travail Core pour le panneau Agents
        # (tâche 13). Absent, `/api/work` répond « Core indisponible ».
        self.work_view = work_view
        # Vue de lecture du bail Live détenu par Core. Elle conserve un état
        # non terminal lors d'une panne de lecture afin de ne jamais afficher
        # OFF tant qu'une clôture n'est pas prouvée.
        self.live_view = live_view
        # Proxy de la scène constellation tenue par Core (Slice 03). Absent,
        # `/api/scene*` répondent « non configuré ».
        self.scene_view = scene_view
        # Acteurs refusés : un avertissement par valeur par minute, avec le
        # nombre d'occurrences tues (une page en boucle ne remplit pas la trace).
        self._scene_forbidden_reports = ReportThrottle()
        # Où le serveur MCP d'affichage du cerveau joint Core (Slice 06). Remis
        # à l'agent Claude seulement quand `scene.enabled` est vrai.
        self.display_mcp = display_mcp
        self._display_unconfigured_reported = False

        settings = self._settings()
        self._agent_id = cli_catalog.normalize_agent_cli(settings.get("agent_cli"))
        self._self_dev: SelfDevelopmentService | None = None
        self._agents: dict[str, Any] = {}
        self._agent_lock = asyncio.Lock()
        self._apply_agent_settings(settings)

        self._app = web.Application(middlewares=[self._origin_guard])
        self._app.add_routes([
            web.get("/", self.index),
            web.get("/api/status", self.status),
            web.post("/api/live/stop", self.live_stop),
            web.get("/api/trace", self.trace),
            web.get("/api/errors", self.errors),
            web.post("/api/errors/archive", self.archive_errors),
            web.get("/api/settings", self.get_settings),
            web.post("/api/settings", self.save_settings),
            web.get("/api/prompts", self.get_prompts),
            web.post("/api/prompts/{prompt_id}", self.update_prompt),
            web.get("/api/credentials", self.get_credentials),
            web.post("/api/credentials", self.save_credential),
            web.post("/api/credentials/delete", self.remove_credential),
            web.post("/api/credentials/bind", self.bind_credential),
            web.get("/api/catalog", self.catalog_view),
            web.get("/api/models", self.models),
            web.get("/api/cli/agents", self.cli_agents),
            web.get("/api/routing/candidates", self.routing_candidates),
            web.get("/api/self-dev", self.self_dev_state),
            web.post("/api/self-dev", self.self_dev_start),
            web.post("/api/self-dev/deploy", self.self_dev_deploy),
            web.get("/api/shortcuts", self.get_shortcuts),
            web.post("/api/shortcuts", self.save_shortcuts),
            web.get("/api/barehands", self.get_barehands),
            web.post("/api/barehands", self.save_barehands),
            web.get(barehands.ASSET_ROUTE_PREFIX + "{asset:.+}", self.barehands_asset),
            web.get("/api/audio/devices", self.audio_devices),
            web.post("/api/audio/test", self.audio_test),
            web.get("/api/agent", self.agent_status),
            web.get("/api/agent/transcript", self.agent_transcript),
            web.get("/api/work", self.work),
            web.get("/api/scene", self.scene),
            web.get("/api/scene/patches", self.scene_patches),
            web.post("/api/scene/commands", self.scene_command),
            web.post("/api/jobs/cancel", self.job_cancel),
            web.get("/api/agent/tasks", self.agent_tasks),
            web.get("/api/agent/tasks/{task_id}/trace", self.agent_task_trace),
            web.post("/api/agent/console/open", self.agent_console_open),
            web.post("/api/agent/console/close", self.agent_console_close),
            web.post("/api/agent/start", self.agent_start),
            web.post("/api/agent/restart", self.agent_restart),
            web.post("/api/agent/kill", self.agent_kill),
            web.post("/api/agent/send", self.agent_send),
            web.post("/api/agent/ask", self.agent_ask),
            web.get("/api/agent/notices", self.agent_notices),
            web.get("/api/background", self.background_events),
            web.post("/api/background/ack", self.background_ack),
        ])
        self._runner: web.AppRunner | None = None

    # ------------------------------------------------------------------ agent

    @property
    def agent(self):  # noqa: ANN201 - ClaudeLocalAgent ou CodexLocalAgent
        """L'agent actif. Les deux implémentations offrent la même surface."""
        existing = self._agents.get(self._agent_id)
        if existing is not None:
            return existing
        if self._agent_id == "codex":
            agent = CodexLocalAgent(runtime_root=self.runtime_root, cwd=self.project_root, command="codex")
        else:
            agent = ClaudeLocalAgent(
                runtime_root=self.runtime_root,
                cwd=self.project_root,
                command=os.getenv("JARVIS_CLAUDE_CLI", "claude"),
                permission_mode=os.getenv("JARVIS_CLAUDE_PERMISSION_MODE", DEFAULT_PERMISSION_MODE),
            )
            if self.work_ingress is not None:
                # Seul Claude expose des sous-tâches : aucun format Codex n'est
                # vérifié, rien n'est inventé pour lui.
                observer = TrackerWorkObserver(agent.subtasks, self.work_ingress.offer)
                agent.subtasks.subscribe(observer.sync)
                self.work_ingress.on_resync = observer.resync
        self._agents[self._agent_id] = agent
        return agent

    def _agent_defaults(self, agent_id: str) -> dict[str, Any]:
        from jarvis.runtime.agent_settings import agent_defaults
        return agent_defaults(agent_id)

    def _agent_settings(self, settings: dict[str, Any], agent_id: str) -> dict[str, Any]:
        from jarvis.runtime.agent_settings import resolve_agent_settings
        return resolve_agent_settings(settings, agent_id)

    def _apply_agent_settings(self, settings: dict[str, Any]) -> None:
        from jarvis.runtime.prompt_overrides import prompt_override_document
        values = self._agent_settings(settings, self._agent_id)
        agent = self.agent
        agent.command = values["command"]
        agent.model = values["model"]
        agent.permission_mode = values["permission_mode"]
        if hasattr(agent, "display_mcp"):
            # Effectif au prochain (re)démarrage du cerveau : le CLI lit ses
            # serveurs MCP et sa consigne système à son lancement.
            scene = load_scene_gate(settings)
            agent.display_mcp = self.display_mcp if scene["enabled"] else None
            if scene["enabled"] and self.display_mcp is None and not self._display_unconfigured_reported:
                self._display_unconfigured_reported = True
                self.journal.emit(
                    "scene.display_mcp_unconfigured",
                    "scene.enabled est vrai mais le Control Center ne connaît pas Core : outils d'affichage non déclarés au cerveau",
                    level="warning",
                    data={"code": "display_mcp_unconfigured", "source": scene["source"]},
                )
        if callable(getattr(agent, "set_prompt_overrides", None)):
            agent.set_prompt_overrides(prompt_override_document(settings))

    async def _switch_agent(self, agent_id: str, settings: dict[str, Any]) -> None:
        """Changer de CLI : arrêter l'ancien avant d'armer le nouveau.

        Laisser deux agents vivants voudrait dire deux processus qui écrivent
        dans le même dépôt sans se voir.
        """
        async with self._agent_lock:
            if agent_id == self._agent_id:
                self._apply_agent_settings(settings)
                return
            previous = self._agents.get(self._agent_id)
            if previous is not None:
                try:
                    await previous.stop()
                except Exception as exc:  # noqa: BLE001 - l'arrêt ne doit pas bloquer la bascule
                    self.journal.emit(
                        "agent.stop",
                        f"Arrêt de l'agent précédent imparfait : {exc}",
                        level="warning",
                        data={"code": "agent_switch_stop_failed"},
                    )
            self._agent_id = agent_id
            self._apply_agent_settings(settings)
            self.journal.emit(
                "agent.switch",
                f"Agent actif : {cli_catalog.spec_for(agent_id).label}",
                data={"agent_cli": agent_id, "command": self.agent.command, "model": self.agent.model},
            )
            try:
                await self.agent.start()
            except RuntimeError as exc:
                self.journal.emit("agent.unavailable", str(exc), level="error", data={"agent_cli": agent_id})

    # ------------------------------------------------------------------ HTTP

    @web.middleware
    async def _origin_guard(self, request: web.Request, handler):  # noqa: ANN001
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("Origin")
            if origin:
                try:
                    host = urlparse(origin).hostname
                except ValueError:
                    raise web.HTTPForbidden(text="invalid origin")
                if host not in {"127.0.0.1", "localhost", "::1"}:
                    raise web.HTTPForbidden(text="forbidden origin")
        return await handler(request)

    async def start(self, *, host: str = "127.0.0.1", port: int = 17654) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self._apply_agent_settings(self._settings())
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        await web.TCPSite(self._runner, host, port).start()
        self.journal.emit("ui.start", "Jarvis Control Center started", data={"host": host, "port": port})
        if self.work_ingress is not None:
            self.work_ingress.start()
        try:
            await self.agent.start()
        except RuntimeError as exc:
            self.journal.emit("agent.unavailable", str(exc), level="error")

    async def stop(self) -> None:
        for agent in list(self._agents.values()):
            try:
                await agent.stop()
            except Exception:  # noqa: BLE001 - l'arrêt du serveur ne doit jamais rester bloqué
                pass
        if self.work_ingress is not None:
            # Après les agents : leurs sous-tâches interrompues partent vers
            # Core dans une dernière tentative bornée.
            await self.work_ingress.aclose()
        if self.work_view is not None:
            await self.work_view.aclose()
        if self.live_view is not None:
            await self.live_view.aclose()
        if self.scene_view is not None:
            await self.scene_view.aclose()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def index(self, request: web.Request) -> web.Response:
        del request
        page = Path(__file__).with_name("control_center.html")
        html = page.read_text(encoding="utf-8")
        # Logique pure du panneau Agents, tenue dans son propre fichier pour que
        # les tests l'exécutent (node) au lieu d'en relire la source : elle est
        # insérée ici telle quelle, la page restant un document unique sans
        # ressource externe — aucun cache ne peut donc en servir une autre
        # version que celle du serveur.
        html = html.replace(
            WORK_SCRIPT_MARKER, page.with_name(WORK_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            LIVE_SCRIPT_MARKER, page.with_name(LIVE_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            CATALOG_SCRIPT_MARKER, page.with_name(CATALOG_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            BAREHANDS_SCRIPT_MARKER, page.with_name(BAREHANDS_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            SCENE_SCRIPT_MARKER, page.with_name(SCENE_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            SCENE_LAYOUT_SCRIPT_MARKER, page.with_name(SCENE_LAYOUT_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            SCENE_INTERACT_SCRIPT_MARKER, page.with_name(SCENE_INTERACT_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            SCENE_PAGE_SCRIPT_MARKER, page.with_name(SCENE_PAGE_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        if self.visualizer_url:
            html = html.replace("__VISUALIZER_URL__", self.visualizer_url)
        else:
            html = re.sub(
                r'<iframe class="face"[^>]*></iframe>',
                '<div class="face"></div>',
                html,
            )
        return web.Response(text=html, content_type="text/html")

    async def status(self, request: web.Request) -> web.Response:
        del request
        voice_state = "idle"
        voice_online = False
        settings = self._settings()
        heartbeat_path = self.runtime_root / ".voice_heartbeat"
        try:
            heartbeat_at = float(heartbeat_path.read_text(encoding="utf-8").strip())
            heartbeat_age = max(0.0, time.time() - heartbeat_at)
            voice_online = heartbeat_age <= VOICE_HEARTBEAT_MAX_AGE_S
        except (OSError, ValueError):
            pass
        state_path = self.runtime_root / ".voice_state"
        if voice_online:
            try:
                voice_state = state_path.read_text(encoding="utf-8").strip() or "idle"
            except OSError:
                pass
        else:
            stale_paths = (
                state_path,
                self.runtime_root / ".voice_alert",
                self.runtime_root / ".voice_waveform",
            )
            try:
                stale_state = state_path.read_text(encoding="utf-8").strip()
            except OSError:
                stale_state = "idle"
            if stale_state != "idle" or any(path.exists() for path in stale_paths[1:]):
                VisualSignalBus(self.runtime_root).reset()
        stack = voice_stack.stack_spec(settings.get("voice_stack"))
        live = await self._live_status(settings, voice_online=voice_online)
        return web.json_response({
            "voice_state": voice_state,
            "voice_online": voice_online,
            "manual_wake_key": shortcut_registry.current(settings)["wake_toggle"],
            "voice_turn_mode": str(voice_stack.settings_for(settings).get("turn_mode") or "auto"),
            "voice_stack": stack.id,
            "voice_stack_label": stack.label,
            "agent_cli": self._agent_id,
            "agent": self.agent.snapshot(),
            # Le badge des sous-agents : le brain n'y est jamais compté.
            "subagents": self.agent.subtasks.counts(),
            "error_count": len(read_jsonl_tail(self.journal.error_path, limit=1000)),
            # Ce qui s'est passé derrière depuis le dernier coup d'œil. Le
            # sondage du statut est le seul battement régulier de la page :
            # c'est lui qui fait avancer le registre.
            "background": self._background_summary(),
            "live": live,
            # Interrupteur du rendu de la scène (Slice 05) : la page ne crée son
            # calque et n'ouvre sa lecture que s'il est vrai. Lu à chaque
            # sondage, sans E/S de plus que les réglages déjà lus.
            "scene": load_scene_gate(settings),
            # Bornes que la page affiche (Slice 08, reprise QA) : délai réel de
            # l'arrêt d'un job à travers ce Control Center, `null` sans Core.
            "scene_limits": {
                "job_cancel_timeout_s": self.scene_view.job_cancel_deadline_s if self.scene_view is not None else None,
            },
        })

    def _background_summary(self) -> dict[str, Any]:
        """Avancer le registre des événements de fond et en rendre le résumé.

        Ne lève jamais : un badge ne doit pas pouvoir faire tomber le statut,
        dont dépend tout l'affichage de la page.
        """
        try:
            follow(self.background, self._background_trace)
        except Exception:
            pass
        return {"seq": self.background.seq, "unread": self.background.unread,
                "counts": self.background.counts()}

    def _fresh_live_signal(self, name: str, *, voice_online: bool) -> dict[str, object] | None:
        if not voice_online:
            return None
        value = VisualSignalBus._read_json(self.runtime_root / name)
        timestamp = value.get("ts") if isinstance(value, dict) else None
        if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                or max(0.0, time.time() - float(timestamp)) > VOICE_HEARTBEAT_MAX_AGE_S):
            return None
        return value

    async def _live_status(self, settings: dict[str, Any], *, voice_online: bool) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        if self.live_view is None:
            return {"visible": False, "state": "unconfigured", "core_reachable": False,
                    "stale": False, "server_time": now.isoformat(),
                    "stop": {"pending": False, "failed": False, "available": False}}
        record, reachable, stale = await self.live_view.read()
        bus = VisualSignalBus(self.runtime_root)
        runtime = self._fresh_live_signal(bus.LIVE_RUNTIME_FILE, voice_online=voice_online)
        request = bus.read_live_stop_request()
        receipt = bus.live_stop_receipt()
        payload = project_live_status(
            record, now=now, runtime=runtime, pricing=settings.get("live_pricing"),
            core_reachable=reachable, stale=stale, request=request, receipt=receipt,
        )
        if not payload["visible"] and reachable:
            # A successful empty Core read is the only UI-side proof that no
            # unresolved session exists; old control files may now be removed.
            for path in (bus.LIVE_STOP_REQUEST_FILE, bus.LIVE_STOP_RECEIPT_FILE):
                (self.runtime_root / path).unlink(missing_ok=True)
        return payload

    async def live_stop(self, request: web.Request) -> web.Response:
        del request
        settings = self._settings()
        heartbeat = self.runtime_root / ".voice_heartbeat"
        try:
            voice_online = time.time() - float(heartbeat.read_text(encoding="utf-8")) <= VOICE_HEARTBEAT_MAX_AGE_S
        except (OSError, ValueError):
            voice_online = False
        live = await self._live_status(settings, voice_online=voice_online)
        if not live.get("visible"):
            return web.json_response(
                {"code": "live_not_active", "error": "Aucune session GPT-Live non résolue."}, status=409,
            )
        session_id = live.get("session_id")
        if not isinstance(session_id, str):
            return web.json_response(
                {"code": "live_core_unavailable",
                 "error": "Core est indisponible et l’identité de session Live n’est pas connue."}, status=503,
            )
        stop_request = VisualSignalBus(self.runtime_root).request_live_stop(session_id)
        self.journal.emit(
            "voice.live_stop_requested", "GPT-Live stop requested from Control Center",
            data={"request_id": stop_request["request_id"], "session_id": session_id},
        )
        live["stop"] = {**live["stop"], "pending": True,
                        "request_id": stop_request["request_id"]}
        return web.json_response({"ok": True, "live": live})

    async def trace(self, request: web.Request) -> web.Response:
        try:
            limit = min(max(int(request.query.get("limit", "100")), 1), 500)
        except ValueError:
            limit = 100
        return web.json_response(read_jsonl_tail(self.journal.trace_path, limit=limit))

    async def errors(self, request: web.Request) -> web.Response:
        try:
            limit = min(max(int(request.query.get("limit", "100")), 1), 500)
        except ValueError:
            limit = 100
        archived = str(request.query.get("archived", "")).strip().lower() in {"1", "true", "yes"}
        path = self.journal.archive_path if archived else self.journal.error_path
        return web.json_response(read_jsonl_tail(path, limit=limit))

    async def archive_errors(self, request: web.Request) -> web.Response:
        del request
        archived = self.journal.archive_errors()
        self.journal.emit("errors.archived", f"{archived} erreur(s) archivée(s)", data={"archived": archived})
        return web.json_response({"ok": True, "archived": archived})

    # -------------------------------------------------------------- réglages

    def _settings(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.settings_path.is_file():
            try:
                loaded = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass
        data.setdefault("claude_cli", os.getenv("JARVIS_CLAUDE_CLI", "claude"))
        # Volontairement, aucune valeur de clé n'est reprise de l'environnement
        # ici : elle serait aussitôt recopiée dans le fichier de réglages par le
        # premier enregistrement, et le .env cesserait d'être la source. La
        # retombée sur l'environnement est faite au moment de la lecture, par
        # `credentials.secret_for`.
        data.setdefault("manual_wake_key", os.getenv("JARVIS_MANUAL_WAKE_KEY", "f9"))
        data.setdefault("audio_input_device", os.getenv("JARVIS_AUDIO_INPUT_DEVICE", ""))
        data.setdefault("audio_output_device", os.getenv("JARVIS_AUDIO_OUTPUT_DEVICE", ""))
        data.setdefault("active_timeout_s", os.getenv("JARVIS_ACTIVE_TIMEOUT_S", "90"))
        data.setdefault("realtime_voice", os.getenv("OPENAI_REALTIME_VOICE", "cedar"))
        data.setdefault("voice_turn_mode", os.getenv("JARVIS_VOICE_TURN_MODE", "auto"))
        data.setdefault("claude_permission_mode", os.getenv("JARVIS_CLAUDE_PERMISSION_MODE", DEFAULT_PERMISSION_MODE))
        data.setdefault("voice_stack", os.getenv("JARVIS_VOICE_STACK", voice_stack.DEFAULT_VOICE_STACK))
        data.setdefault("agent_cli", os.getenv("JARVIS_AGENT_CLI", cli_catalog.DEFAULT_AGENT_CLI))
        # Vide veut dire « pas de choix dans l'interface » : Voice retombe alors
        # sur JARVIS_VOICE_ARCH, puis sur `default_voice_arch()`. La variable
        # n'est pas recopiée ici, sinon le premier enregistrement la figerait
        # dans le fichier et la retirer du .env ne ramènerait plus à `legacy`.
        data.setdefault("voice_arch", "")
        return data

    def _write_settings(self, settings: dict[str, Any]) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix(self.settings_path.suffix + ".tmp")
        tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        # Windows tient parfois le fichier cible quelques millisecondes
        # (antivirus, indexeur) et refuse le remplacement : réessayer plutôt
        # que de rendre une erreur 500 sur un simple enregistrement de réglage.
        # Jamais d'écriture en place : le fichier porte des secrets et doit
        # rester complet ou inchangé.
        try:
            replace_with_retry(tmp, self.settings_path)
        except OSError as exc:
            # Le temporaire porte les mêmes secrets que le fichier final (clé
            # OpenAI…) : il ne survit pas à un échec. Même règle que
            # `owner_voice_profile.save_profile`, et même verdict : les
            # réglages précédents sont intacts, rien n'est à moitié écrit.
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise web.HTTPServiceUnavailable(
                text=(
                    f"Réglages non enregistrés ({self.settings_path}) : {type(exc).__name__}. "
                    "Fermez ce qui tient le fichier (antivirus, éditeur) et recommencez ; "
                    "les réglages précédents sont inchangés."
                ),
                headers={SETTINGS_ERROR_CODE_HEADER: "settings_write_failed"},
            ) from None

    def _mirror_legacy(self, settings: dict[str, Any]) -> None:
        """Réécrire les anciens champs plats à partir des réglages structurés.

        `app.py`, la barre d'état et le processus Voice les lisent encore. Les
        garder synchronisés ici est le prix d'un seul écran de réglages : le
        format structuré est la source, ces champs n'en sont que le reflet.
        """
        active = voice_stack.settings_for(settings)
        settings["voice_turn_mode"] = str(active.get("turn_mode") or "auto")
        openai_values = voice_stack.settings_for(settings, voice_stack.OPENAI_REALTIME.id)
        voice = str(openai_values.get("voice") or "cedar")
        if voice in REALTIME_VOICES:
            settings["realtime_voice"] = voice
        claude_values = self._agent_settings(settings, "claude")
        settings["claude_cli"] = claude_values["command"]
        settings["claude_permission_mode"] = claude_values["permission_mode"]
        settings["manual_wake_key"] = shortcut_registry.current(settings)["wake_toggle"]

    # -------------------------------------------------- architecture vocale

    @staticmethod
    def _voice_arch_source(settings: dict[str, Any]) -> tuple[str, str]:
        """Valeur brute que Voice retiendra au démarrage, et d'où elle vient.

        Même ordre que `app._run_voice_v2` : le réglage de l'interface, puis
        JARVIS_VOICE_ARCH, puis le défaut calculé par `default_voice_arch()`.
        """
        stored = str(settings.get("voice_arch") or "").strip()
        if stored:
            return stored, "settings"
        env = os.getenv("JARVIS_VOICE_ARCH", "").strip()
        if env:
            return env, "env"
        return default_voice_arch().value, "default"

    @staticmethod
    def _store_voice_arch(current: dict[str, Any], raw: object) -> None:
        value = str(raw or "").strip().lower()
        if value:
            try:
                value = parse_voice_arch(value).value
            except ConfigurationError as exc:
                raise voice_stack.VoiceStackError(
                    "voice_unknown_arch", f"Architecture vocale inconnue : {value}."
                ) from exc
        current["voice_arch"] = value

    def _voice_arch_problem(self, settings: dict[str, Any]) -> str | None:
        """Pourquoi Voice refuserait de démarrer avec ces réglages, ou None.

        Ce sont les refus de `app._run_voice_v2` et de `PersistentVoiceRuntime`,
        dits ici avant qu'un redémarrage de Voice ne les découvre.
        """
        if isinstance(settings.get("voice_architecture"), dict) and settings["voice_architecture"].get("compatibility") is None:
            # Canonical selection is checked independently; inactive legacy
            # fields cannot veto an explicit selection or an unrelated Save.
            return None
        raw, source = self._voice_arch_source(settings)
        origin = " (valeur imposée par JARVIS_VOICE_ARCH)" if source == "env" else ""
        try:
            arch = parse_voice_arch(raw)
        except ConfigurationError:
            return f"Architecture vocale inconnue : « {raw} »{origin}. Voice refusera de démarrer."
        if arch is not VoiceArchitecture.CONTINUOUS_BRAIN:
            return None
        if voice_stack.normalize_stack(settings.get("voice_stack")) == voice_stack.GEMINI_LIVE.id:
            return (
                f"La conversation continue n'est possible qu'avec la pile OpenAI Realtime{origin} : "
                "Gemini Live ne sait pas piloter sa sortie audio. Choisissez OpenAI Realtime, "
                "ou l'architecture « Un tour par appui »."
            )
        if str(voice_stack.settings_for(settings).get("turn_mode") or "auto").strip().lower() == "manual":
            return (
                f"La conversation continue exige la fin de tour automatique{origin} : remettez "
                "« Fin de tour » sur « auto », ou choisissez l'architecture « Un tour par appui »."
            )
        return None

    def _voice_arch_is_continuous(self, settings: dict[str, Any]) -> bool:
        """Voice tournera-t-elle vraiment en `continuous_brain` avec ces réglages ?

        Pas seulement « l'architecture demandée est-elle celle-là » : une
        combinaison que Voice refuse au démarrage (pile Gemini Live, fin de
        tour manuelle — `_voice_arch_problem`) ne donne aucune conversation
        continue, donc ni Solo Owner ni annulation d'écho. Le fichier de
        réglages peut porter une telle paire s'il a été écrit à la main :
        l'écran doit alors dire « refusé », pas « appliqué ».
        """

        if isinstance(settings.get("voice_architecture"), dict) and settings["voice_architecture"].get("compatibility") is None:
            return True
        raw, _source = self._voice_arch_source(settings)
        try:
            if parse_voice_arch(raw) is not VoiceArchitecture.CONTINUOUS_BRAIN:
                return False
        except ConfigurationError:
            return False
        return self._voice_arch_problem(settings) is None

    def _voice_arch_payload(self, settings: dict[str, Any]) -> dict[str, Any]:
        key = shortcut_registry.current(settings)["wake_toggle"].upper()
        choices = [
            {"id": arch.value, "label": label.format(key=key), "hint": hint.format(key=key)}
            for arch, label, hint in _VOICE_ARCH_CHOICES
        ]
        raw, source = self._voice_arch_source(settings)
        try:
            effective = parse_voice_arch(raw).value
        except ConfigurationError:
            effective = ""
        labels = {choice["id"]: choice["label"] for choice in choices}
        fallback = labels.get(effective) or f"valeur invalide « {raw} »"
        # L'option vide rend la main à l'environnement : son libellé dit ce
        # qu'elle vaut réellement aujourd'hui.
        default_choice = {
            "id": "",
            "label": f"Selon JARVIS_VOICE_ARCH — {fallback}" if source == "env" else f"Par défaut — {fallback}",
            "hint": "Aucun choix enregistré ici : Voice suit JARVIS_VOICE_ARCH, "
            "ou l'architecture par défaut si la variable est absente.",
        }
        return {
            "arch": str(settings.get("voice_arch") or ""),
            "arch_effective": effective,
            "arch_source": source,
            "archs": [default_choice, *choices],
            "arch_problem": self._voice_arch_problem(settings),
        }

    # ------------------------------------------ autorisation de conversation

    @staticmethod
    def _store_authorization(current: dict[str, Any], values: dict[str, Any], *, runtime_root: Path) -> None:
        """Ranger l'autorisation de conversation, puis valider l'ensemble.

        Seules les clés reçues sont touchées ; une valeur vide retire la clé,
        qui retombe sur son défaut (la vérification suit alors le mode). La
        combinaison résultante est validée avant toute écriture : une valeur
        inconnue ou incohérente n'atteint pas le disque. Un Solo Owner que
        rien ne peut appliquer aujourd'hui est, lui, enregistré : ce n'est pas
        une erreur de réglage, et `_authorization_payload` le signale.

        Réglages fins du vérificateur (tâche 08) : même règle, même
        validateur que Voice (`parse_speaker_verifier_settings`), bornes
        croisées comprises (réponse brève plus courte que la fenêtre de
        preuve). Jamais le chemin du profil (`_UI_VERIFIER_SETTINGS`).
        """
        touched = [key for key in CONVERSATION_AUTHORIZATION_SETTINGS if values.get(key) is not None]
        tuning = [key for key in _UI_VERIFIER_SETTINGS if values.get(key) is not None]
        for key in (*touched, *tuning):
            raw = values[key]
            if isinstance(raw, str) and not raw.strip():
                current.pop(key, None)
            else:
                current[key] = raw
        if touched:
            canonical = conversation_authorization_settings(parse_conversation_authorization(current))
            for key in CONVERSATION_AUTHORIZATION_SETTINGS:
                if key in current:
                    current[key] = canonical[key]
        if tuning:
            parse_speaker_verifier_settings(current, runtime_root=runtime_root)
            for key in tuning:
                if key in current:
                    value = float(current[key])
                    current[key] = value if key in _FLOAT_VERIFIER_SETTINGS else int(value)

    @staticmethod
    def _authorization_payload(
        settings: dict[str, Any],
        runtime_root: Path,
        *,
        continuous: bool = True,
        continuous_problem: str | None = None,
        runtime_report: dict[str, Any] | None = None,
        capture_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Autorisation enregistrée, valeur effective, et ce qui s'applique vraiment.

        `status` vaut `ready`, `degraded` ou `refused` (`assess_authorization`,
        la fonction même dont Voice se sert, architecture comprise), ou
        `invalid` quand le fichier contient une valeur écrite à la main que la
        validation refuse — signalée ici plutôt que de bloquer l'écran. Voice
        refuse alors d'écouter.

        L'état du vérificateur vient d'une sonde de système de fichiers (module
        installé, fichier du modèle, métadonnées du profil) : le modèle n'est
        jamais chargé ici, et l'empreinte vocale n'apparaît jamais dans la
        réponse. Elle n'est pas gratuite pour autant : elle vérifie aussi le
        SHA-256 du modèle, donc le premier appel après une modification du
        fichier relit les `MODEL_SIZE` octets (28 281 164, soit ~27 Mio) sur la
        boucle aiohttp ; les suivants retombent sur le cache (taille, date de
        modification).

        `runtime` (tâche 07) : ce que Voice, en marche, a réellement appliqué
        à sa dernière activation (`ready` / `refused`, code, message, phase).
        Un refus que seule Voice pouvait voir — moteur qui ne charge pas,
        vérificateur tombé en cours de session — l'emporte sur la sonde tant
        qu'il porte sur le même mode : `status` passe à `refused`,
        `status_source` à `voice`.

        Tâche 08 (écran) : description des champs (`fields`, et
        `advanced_fields` pour les réglages fins R&D), origine de chaque valeur
        (`origin` : réglage enregistré ou défaut), vérifications compatibles
        avec chaque mode, réglages effectifs du vérificateur
        (`verifier_settings`, chemin du profil en lecture seule), commande qui
        lève l'indisponibilité (`verifier_remedy`), et, tant que Voice bat,
        l'état de son fil de vérification (`worker` : disponibilité, fenêtres
        perdues). Aucune clé de premier niveau n'est une clé enregistrable :
        un client qui renverrait cette description ne toucherait à rien.
        """
        probe = probe_owner_verifier(settings, runtime_root=runtime_root)
        detail = probe.payload()
        described: dict[str, Any] = {
            "verifier_detail": detail,
            "verifier_remedy": probe_remedy(str(detail.get("code") or "")),
            "stored": {key: settings.get(key, "") for key in CONVERSATION_AUTHORIZATION_SETTINGS},
            "origin": {
                key: "stored" if ControlCenter._is_set(settings.get(key)) else "default"
                for key in CONVERSATION_AUTHORIZATION_SETTINGS
            },
            "conversation_modes": [item.value for item in ConversationMode],
            "verification_modes": [item.value for item in SpeakerVerificationMode],
            # Règle de cohérence du domaine, dite pour chaque mode : la page ne
            # propose que ce que l'enregistrement accepterait.
            "verification_modes_by_mode": {
                mode.value: [
                    verification.value
                    for verification in SpeakerVerificationMode
                    if ControlCenter._coherent(mode, verification)
                ]
                for mode in ConversationMode
            },
            # Pas `owner_buffer_ms` : un client qui renverrait cette description
            # écrirait les bornes à la place de la valeur.
            "owner_buffer_ms_bounds": {
                "default": DEFAULT_OWNER_BUFFER_MS,
                "min": MIN_OWNER_BUFFER_MS,
                "max": MAX_OWNER_BUFFER_MS,
            },
            "fields": voice_stack.describe_fields(voice_stack.AUTHORIZATION_FIELDS),
            "advanced_fields": voice_stack.describe_fields(voice_stack.OWNER_TUNING_FIELDS),
            "verifier_settings": ControlCenter._verifier_settings_payload(settings, runtime_root),
            "restart_required": False,
        }
        if runtime_report is not None:
            described["runtime"] = runtime_report
        worker = (capture_report or {}).get("verifier")
        if capture_report is not None:
            described["worker"] = (
                {**worker, "phase": capture_report.get("phase"), "ts": capture_report.get("ts")}
                if isinstance(worker, dict)
                else None
            )
        try:
            authorization = parse_conversation_authorization(settings)
        except ConversationAuthorizationError as exc:
            return {**described, "effective": None, "status": "invalid", "code": exc.code, "problem": str(exc)}
        assessment = assess_authorization(authorization, probe.availability, continuous=continuous)
        payload = {
            **described,
            "effective": conversation_authorization_settings(authorization),
            "verifier": assessment.verifier.value,
            "status": assessment.status.value,
            "code": assessment.code or None,
            "problem": assessment.message or None,
            "status_source": "settings",
        }
        if continuous_problem and payload["code"] == "solo_owner_requires_continuous_brain":
            # La conversation continue est bien demandée, mais ces réglages
            # empêchent Voice de la démarrer : dire laquelle, plutôt que de
            # laisser le message générique parler d'« un tour par appui ».
            payload["problem"] = f"{continuous_problem} Solo Owner ne peut donc pas s'appliquer."
        if runtime_report is not None and runtime_report.get("conversation_mode") not in (None, authorization.mode.value):
            # Voice applique encore l'ancien mode : le nouveau attend son redémarrage.
            payload["restart_required"] = True
        if capture_report is not None and capture_report.get("speaker_verification") not in (
            None,
            authorization.verification.value,
        ):
            payload["restart_required"] = True
        if (
            runtime_report is not None
            and runtime_report.get("status") == AuthorizationStatus.REFUSED.value
            and runtime_report.get("conversation_mode") == authorization.mode.value
            and assessment.status is not AuthorizationStatus.REFUSED
        ):
            payload.update(
                status=AuthorizationStatus.REFUSED.value,
                code=runtime_report.get("code"),
                problem=runtime_report.get("problem"),
                status_source="voice",
            )
        elif (
            authorization.verification is SpeakerVerificationMode.SHADOW
            and assessment.status is AuthorizationStatus.READY
            and capture_report is not None
            and capture_report.get("speaker_verification") == SpeakerVerificationMode.SHADOW.value
            and (not isinstance(worker, dict) or worker.get("availability") != VerifierAvailability.READY.value)
        ):
            # Mesure en ombre demandée, mais Voice n'a aucun vérificateur en
            # marche (moteur qui ne se construit pas, panne en session) : rien
            # n'est mesuré, et seule Voice pouvait le voir.
            availability = worker.get("availability") if isinstance(worker, dict) else None
            payload.update(
                status=AuthorizationStatus.DEGRADED.value,
                code="speaker_verification_unavailable",
                problem=(
                    "Vérification du locuteur en observation demandée, mais Voice "
                    + (f"a un vérificateur « {availability} »" if availability else "n'a branché aucun vérificateur")
                    + " : rien n'est mesuré (voice.owner.unavailable dans la trace). La conversation reste "
                    "ouverte à toutes les voix, comme avant."
                ),
                status_source="voice",
            )
        return payload

    @staticmethod
    def _is_set(raw: object) -> bool:
        return raw is not None and not (isinstance(raw, str) and not raw.strip())

    @staticmethod
    def _coherent(mode: ConversationMode, verification: SpeakerVerificationMode) -> bool:
        try:
            ConversationAuthorization(mode, verification)
        except ConversationAuthorizationError:
            return False
        return True

    @staticmethod
    def _verifier_settings_payload(settings: dict[str, Any], runtime_root: Path) -> dict[str, Any]:
        """Réglages fins du vérificateur : enregistrés, origine, effectifs (tâche 08).

        Même lecture que Voice. Une valeur écrite à la main que la validation
        refuse est signalée (`status: invalid`) sans bloquer l'écran.
        """

        payload: dict[str, Any] = {
            "stored": {key: settings.get(key, "") for key in SPEAKER_VERIFIER_SETTINGS},
            "origin": {
                key: "stored" if ControlCenter._is_set(settings.get(key)) else "default"
                for key in SPEAKER_VERIFIER_SETTINGS
            },
            # Écrit depuis le fichier seulement, jamais depuis la page.
            "read_only": [OWNER_PROFILE_PATH_SETTING],
        }
        try:
            parsed = parse_speaker_verifier_settings(settings, runtime_root=runtime_root)
        except ConversationAuthorizationError as exc:
            return {**payload, "effective": None, "status": "invalid", "code": exc.code, "problem": str(exc)}
        return {**payload, "effective": effective_verifier_settings(parsed), "status": "valid", "code": None, "problem": None}

    def _echo_cancellation_payload(
        self,
        settings: dict[str, Any],
        capture_report: dict[str, Any] | None,
        effective_stack: str | None,
        configuration_id: str | None,
        compatibility_runtime: bool,
    ) -> dict[str, Any]:
        """Annulation d'écho : demandée, installée, et réellement appliquée (tâche 08).

        La demande est le champ « Annulation d'écho » de la pile OpenAI (le
        seul chemin de configuration) ; elle ne s'applique qu'en conversation
        continue. La sonde ne regarde que l'installation de LiveKit, sans
        charger sa bibliothèque native. Tant que Voice bat et applique la même
        demande, son constat (`runtime`, publié dans `.voice_capture`) fait foi
        (`status_source: voice`) : échec de construction, panne en session.
        """

        configured = bool(voice_stack.settings_for(settings, voice_stack.OPENAI_REALTIME.id).get("echo_cancellation", True))
        applicable = (
            self._voice_arch_is_continuous(settings)
            and effective_stack == voice_stack.OPENAI_REALTIME.id
        )
        installed = echo_cancellation_installed()
        if not applicable:
            status, code = "not_applicable", "aec_not_applicable"
        elif not configured:
            status, code = "off", "aec_disabled"
        elif not installed:
            status, code = "degraded", "aec_not_installed"
        else:
            status, code = "ready", ""
        payload: dict[str, Any] = {
            "configured": configured,
            "applicable": applicable,
            "installed": installed,
            "status": status,
            "code": code or None,
            "problem": _AEC_PROBLEMS.get(code),
            "status_source": "settings",
            "restart_required": False,
        }
        runtime = (capture_report or {}).get("echo_cancellation")
        if not isinstance(runtime, dict):
            return payload
        payload["runtime"] = {
            **runtime,
            "arch": capture_report.get("arch"),
            "architecture": capture_report.get("architecture"),
            "configuration_id": capture_report.get("configuration_id"),
            "phase": capture_report.get("phase"),
            "ts": capture_report.get("ts"),
        }
        # Seule une capture duplex publie cet état (conversation continue) : un
        # constat qui ne porte pas sur la demande courante vient de réglages
        # antérieurs, qui attendent le redémarrage de Voice.
        reported_configuration = capture_report.get("configuration_id")
        if reported_configuration is not None:
            same_configuration = reported_configuration == configuration_id
        else:
            # Compatibilité avec les processus Voice antérieurs au champ
            # `configuration_id`. Leur `arch=continuous_brain` est sans
            # ambiguïté uniquement pour le runtime de compatibilité ; une
            # architecture explicite doit attendre un rapport corrélé.
            same_configuration = (
                compatibility_runtime
                and capture_report.get("arch") == VoiceArchitecture.CONTINUOUS_BRAIN.value
            )
        if not applicable or runtime.get("requested") is not configured or not same_configuration:
            payload["restart_required"] = True
            return payload
        runtime_code = str(runtime.get("code") or "")
        if runtime_code == "duplex_capture_unavailable" or (configured and runtime.get("active") is not True):
            payload.update(
                status="degraded",
                code=runtime_code or "aec_unavailable",
                problem=_AEC_PROBLEMS.get(runtime_code, _AEC_PROBLEMS["aec_unavailable"]),
                status_source="voice",
            )
        elif configured:
            payload.update(status="ready", code=None, problem=None, status_source="voice")
        return payload

    def _voice_authorization_report(self) -> dict[str, Any] | None:
        """Dernier état d'autorisation publié par Voice, seulement si Voice bat encore.

        Clés connues seulement, texte borné : ce fichier est écrit par un
        autre processus.
        """

        if not self._voice_beating():
            return None
        try:
            raw = json.loads(
                (self.runtime_root / VisualSignalBus.AUTHORIZATION_FILE).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or raw.get("status") not in {item.value for item in AuthorizationStatus}:
            return None
        report: dict[str, Any] = {}
        for key in ("status", "code", "problem", "conversation_mode", "arch", "phase"):
            value = raw.get(key)
            report[key] = str(value)[:600] if value is not None else None
        ts = raw.get("ts")
        report["ts"] = float(ts) if isinstance(ts, (int, float)) and not isinstance(ts, bool) else None
        return report

    def _voice_beating(self) -> bool:
        try:
            heartbeat_at = float((self.runtime_root / ".voice_heartbeat").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        return max(0.0, time.time() - heartbeat_at) <= VOICE_HEARTBEAT_MAX_AGE_S

    def _voice_capture_report(self) -> dict[str, Any] | None:
        """Dernier état de la capture duplex publié par Voice (tâche 08), si Voice bat encore.

        Écrit par un autre processus : clés connues seulement, types vérifiés,
        texte borné. Scalaires seulement — ni audio ni empreinte n'y passent.
        """

        if not self._voice_beating():
            return None
        try:
            raw = json.loads((self.runtime_root / VisualSignalBus.CAPTURE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None

        def text(value: object) -> str | None:
            return str(value)[:64] if isinstance(value, str) and value else None

        report: dict[str, Any] = {
            key: text(raw.get(key))
            for key in ("arch", "architecture", "configuration_id", "phase", "speaker_verification")
        }
        ts = raw.get("ts")
        report["ts"] = float(ts) if isinstance(ts, (int, float)) and not isinstance(ts, bool) else None
        aec = raw.get("echo_cancellation")
        report["echo_cancellation"] = (
            {
                "requested": aec.get("requested") if isinstance(aec.get("requested"), bool) else None,
                "active": aec.get("active") is True,
                "code": text(aec.get("code")),
            }
            if isinstance(aec, dict)
            else None
        )
        verifier = raw.get("verifier")
        if isinstance(verifier, dict):
            availability = verifier.get("availability")
            dropped = verifier.get("dropped_ms")
            report["verifier"] = {
                "availability": availability if availability in {item.value for item in VerifierAvailability} else None,
                "dropped_ms": dropped if isinstance(dropped, int) and not isinstance(dropped, bool) and dropped >= 0 else None,
            }
        else:
            report["verifier"] = None
        return report

    def _voice_architecture_registry(self, settings: dict[str, Any]):
        if self._voice_registry is not None:
            return self._voice_registry
        try:
            cached = self.catalog.cached_for("google", creds.secret_for(settings, "google")) or {}
        except (TypeError, AttributeError, ValueError):
            # The optional on-disk catalog is not an authority for Settings.
            # Keep known capabilities usable, never expose corrupt raw data.
            cached = {"models": None}
        records = cached.get("models", ()) if isinstance(cached, dict) else ()
        valid = [item for item in records if isinstance(item, dict)
                 and isinstance(item.get("id"), str) and item["id"].strip()
                 and item["id"] == item["id"].strip()
                 and isinstance(item.get("methods"), (list, tuple))] if isinstance(records, (list, tuple)) else []
        if not isinstance(records, (list, tuple)) or len(valid) != len(records):
            self.journal.emit("voice.settings.catalog_rejected", "Optional voice catalog contains invalid records",
                              level="warning", data={"code": "voice_catalog_invalid", "provider": "google"})
        return default_voice_registry(google_models=valid)

    def _voice_architecture_payload(self, settings: dict[str, Any]) -> dict[str, Any]:
        registry = self._voice_architecture_registry(settings)
        try:
            result = voice_architecture_query(settings, registry=registry)
            if (not result["compatibility_runtime"] and result["selection"]["config"]["architecture"] != "duplex"
                    and voice_stack.settings_for(settings, voice_stack.OPENAI_REALTIME.id).get("turn_mode") == "manual"):
                result["problem"] = {"code": "voice_auto_turn_required", "message": "Simple et Front Brain exigent la fin de tour automatique."}
                result["new_runtime_ready"] = False
            return result
        except (VoiceConfigError, ConfigurationError) as exc:
            return {"selection": None, "compatibility_runtime": "voice_architecture" not in settings,
                    "new_runtime_ready": False, "problem": {"code": getattr(exc, "code", "voice_architecture_invalid"),
                    "message": str(exc)}, "architectures": registry.settings_architectures()}

    @staticmethod
    def _effective_voice_composition(settings: dict[str, Any]):
        """Composition réellement consommée, sans modifier les réglages enregistrés."""

        from jarvis.runtime.voice_composition import resolve_voice_composition

        try:
            return resolve_voice_composition(settings)
        except (VoiceConfigError, ConfigurationError):
            return None

    def _settings_payload(self, settings: dict[str, Any]) -> dict[str, Any]:
        stack_id = voice_stack.normalize_stack(settings.get("voice_stack"))
        agent_id = cli_catalog.normalize_agent_cli(settings.get("agent_cli"))
        capture_report = self._voice_capture_report()
        architecture_payload = self._voice_architecture_payload(settings)
        legacy_arch_payload = self._voice_arch_payload(settings)
        composition = self._effective_voice_composition(settings)
        effective_stack = composition.stack_id if composition is not None else None
        voice_schema = voice_settings_schema.describe_voice_settings(
            architecture_profiles=architecture_payload.get("architectures", []),
            legacy_arches=legacy_arch_payload.get("archs", []),
        )
        return {
            "voice": {
                "architecture": architecture_payload,
                "stack": stack_id,
                "effective_stack": effective_stack,
                "stacks": voice_stack.describe_stacks(),
                "settings": {
                    spec.id: voice_stack.settings_for(settings, spec.id) for spec in voice_stack.VOICE_STACKS
                },
                **legacy_arch_payload,
                **voice_schema,
                # Qui peut parler à JARVIS : réglage distinct de l'architecture,
                # mais Solo Owner n'existe qu'en continuous_brain (tâche 07).
                "authorization": self._authorization_payload(
                    settings,
                    self.runtime_root,
                    continuous=self._voice_arch_is_continuous(settings),
                    continuous_problem=self._voice_arch_problem(settings),
                    runtime_report=self._voice_authorization_report(),
                    capture_report=capture_report,
                ),
                # Annulation d'écho demandée face à ce que Voice applique (tâche 08).
                "echo_cancellation": self._echo_cancellation_payload(
                    settings,
                    capture_report,
                    effective_stack,
                    composition.configuration_id if composition is not None else None,
                    bool(composition is not None and composition.selection.uses_compatibility_runtime),
                ),
                "switch": self._voice_switch_payload(),
            },
            "cli": {
                "agent": agent_id,
                "delegation_mode": agent_routing.delegation_mode(settings),
                "delegation_mode_metadata": agent_routing.describe_delegation_modes(),
                "behavior": agent_behavior.describe(settings),
                "agents": [
                    cli_catalog.describe(spec, command=self._agent_settings(settings, spec.id)["command"], detection={})
                    for spec in cli_catalog.AGENT_CLIS
                ],
                "settings": {
                    spec.id: self._agent_settings(settings, spec.id) for spec in cli_catalog.AGENT_CLIS
                },
                "active_state": self.agent.snapshot()["state"],
            },
            # Aiguillage des sous-agents. Les candidats ne sont pas ici : les
            # lister demande de sonder les CLI et d'appeler les fournisseurs, ce
            # qui n'a pas sa place dans un GET qui doit rester immédiat.
            # `/api/routing/candidates` les donne, mesurés.
            "routing": agent_routing.describe(agent_routing.load_policy(settings), ()),
            # Auto-développement : deux crans, éteints tant que l'utilisateur ne
            # les ouvre pas. L'état des worktrees vit sur `/api/self-dev`.
            "self_development": load_self_dev_gate(settings),
            # Scène constellation (Slice 06) : rendu et outils d'affichage du
            # cerveau. Effectif au prochain démarrage du cerveau.
            "scene": load_scene_gate(settings),
            "audio": {
                "input_device": settings.get("audio_input_device", ""),
                "output_device": settings.get("audio_output_device", ""),
                "active_timeout_s": settings.get("active_timeout_s", "90"),
            },
            "credentials": creds.credentials_state(settings),
            "shortcuts": shortcut_registry.describe(settings),
            # Champs historiques : d'anciens clients et les tests les lisent.
            "claude_cli": self._agent_settings(settings, "claude")["command"],
            "openai_api_key_set": bool(creds.secret_for(settings, "openai")),
            "porcupine_access_key_set": bool(creds.secret_for(settings, "porcupine")),
            "manual_wake_key": shortcut_registry.current(settings)["wake_toggle"],
            "audio_input_device": settings.get("audio_input_device", ""),
            "audio_output_device": settings.get("audio_output_device", ""),
            "active_timeout_s": settings.get("active_timeout_s", "90"),
            "realtime_voice": voice_stack.settings_for(settings, voice_stack.OPENAI_REALTIME.id).get("voice", "cedar"),
            "realtime_voices": list(REALTIME_VOICES),
            "voice_turn_mode": str(voice_stack.settings_for(settings).get("turn_mode") or "auto"),
            "voice_turn_modes": sorted(TURN_MODES),
            "claude_permission_mode": self._agent_settings(settings, "claude")["permission_mode"],
            "claude_permission_modes": list(PERMISSION_MODES),
        }

    async def get_settings(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(self._settings_payload(self._settings()))

    # ------------------------------------------------- Barehands (mode test)

    async def get_barehands(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(barehands.describe(self._settings(), self.barehands_vendor_root))

    async def save_barehands(self, request: web.Request) -> web.Response:
        """Enregistrer l'interrupteur seul, dans le fichier de réglages commun.

        Route dédiée, comme les raccourcis : l'interrupteur s'applique à chaud
        et ne doit pas dépendre de la validité du reste des réglages (voix,
        CLI) qu'un enregistrement complet revaliderait.
        """

        try:
            payload = await request.json()
        except ValueError:
            payload = None
        current = self._settings()
        try:
            value = barehands.apply(current, payload)
        except barehands.BarehandsSettingsError as exc:
            self.journal.emit(
                "settings.barehands.rejected", "Barehands test mode setting rejected",
                level="warning", data={"code": exc.code},
            )
            raise web.HTTPBadRequest(text=str(exc), headers={SETTINGS_ERROR_CODE_HEADER: exc.code}) from exc
        self._write_settings(current)
        state = barehands.describe(current, self.barehands_vendor_root)
        self.journal.emit(
            "settings.barehands",
            f"Barehands (mode test) {'activé' if value['enabled'] else 'désactivé'}",
            data={"enabled": value["enabled"], "assets_installed": state["assets"]["installed"]},
        )
        return web.json_response(state)

    async def barehands_asset(self, request: web.Request) -> web.StreamResponse:
        found = barehands.asset_path(self.barehands_vendor_root, request.match_info["asset"])
        if found is None:
            raise web.HTTPNotFound(text="asset Barehands inconnu ou non installé")
        path, content_type = found
        return web.FileResponse(
            path,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )

    def _prompt_payload(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Project only programs active for the selected architecture and backend."""
        from jarvis.domain.prompt_registry import PromptTarget
        from jarvis.domain.voice_architecture import DuplexVoiceConfig, FrontBrainVoiceConfig
        from jarvis.runtime.prompt_catalog import default_prompt_registry
        from jarvis.runtime.prompt_overrides import stored_prompt_override_document
        from jarvis.runtime.prompt_runtime import resolve_prompt
        from jarvis.runtime.voice_composition import resolve_voice_composition

        composition = resolve_voice_composition(settings)
        selection, config = composition.selection, composition.selection.config
        targets: list[tuple[str, PromptTarget, dict[str, object]]] = []
        if selection.uses_compatibility_runtime:
            compatibility = selection.compatibility
            assert compatibility is not None
            conversation_model = config.conversation_model
            targets.append(("Conversation vocale", PromptTarget(
                "conversation", "simple", conversation_model.provider_id,
                conversation_model.model_id or None, compatibility.execution_mode, "session",
            ), {"context": {}}))
            if conversation_model.provider_id == "openai":
                targets.extend((
                    ("Réflexe de surface", PromptTarget("reflex", None, "openai", None, None, "reflex"),
                     {"transcript": "", "avoid": []}),
                    ("Lecture fidèle", PromptTarget("speech", None, "openai", None, None, "verbatim"),
                     {"text": ""}),
                ))
        elif isinstance(config, DuplexVoiceConfig):
            targets.append(("Conversation Duplex / GPT-Live", PromptTarget(
                "conversation", "duplex", "openai", config.conversation_model.model_id,
                "explicit", "session",
            ), {"context": {}}))
        else:
            conversation_model = config.reflex_model if isinstance(config, FrontBrainVoiceConfig) else config.conversation_model
            targets.extend((
                ("Conversation vocale", PromptTarget(
                    "conversation", config.architecture.value, conversation_model.provider_id,
                    conversation_model.model_id, "explicit", "session",
                ), {"context": {}}),
                ("Réflexe de surface", PromptTarget("reflex", None, "openai", None, None, "reflex"),
                 {"transcript": "", "avoid": []}),
                ("Lecture fidèle", PromptTarget("speech", None, "openai", None, None, "verbatim"),
                 {"text": ""}),
            ))
            if isinstance(config, FrontBrainVoiceConfig):
                targets.append(("Analyse Front Brain", PromptTarget(
                    "analysis", "front_brain", config.analysis_model.provider_id,
                    config.analysis_model.model_id, "explicit", "hint",
                ), {"observation": {}}))

        agent_id = cli_catalog.normalize_agent_cli(settings.get("agent_cli"))
        agent_model = self._agent_settings(settings, agent_id)["model"] or None
        if agent_id == "claude":
            targets.extend((
                ("Système du backend Claude", PromptTarget(
                    "backend", None, "claude", agent_model, None, "conversation_session"), {}),
                ("Exécution de travail Claude", PromptTarget(
                    "backend", None, "claude", agent_model, None, "job_result_session"), {}),
                ("Analyse spéculative Claude", PromptTarget(
                    "backend", None, "claude", agent_model, None, "speculative_session"), {}),
            ))
        targets.append(("Tour du backend", PromptTarget(
            "backend", None, agent_id, agent_model, None, "turn",
        ), {"context": {}, "request_text": ""}))

        overrides = stored_prompt_override_document(settings)
        programs = []
        active_ids: set[str] = set()
        for label, target, variables in targets:
            resolution = resolve_prompt(target, overrides=overrides, variables=variables)
            payload = resolution.to_payload()
            payload["label"] = label
            payload["preview"] = "empty_runtime_data"
            programs.append(payload)
            active_ids.update(str(item["prompt_id"]) for item in resolution.layers)
        inspection = default_prompt_registry().inspect(overrides)
        layers = []
        for layer in inspection["layers"]:
            if layer["prompt_id"] in active_ids:
                layer = dict(layer)
                layer["bindings"] = [item for item in layer["bindings"]
                                     if item["program_id"] in {program["program_id"] for program in programs}]
                layers.append(layer)
        return {
            "schema_version": 1,
            "selection": selection.to_dict(),
            "programs": programs,
            "layers": layers,
            "unknown_overrides": inspection["unknown_overrides"],
            "provider_internal_prompts": "unavailable",
            "application": "preview_only",
            "application_note": (
                "Saving changes does not update a running session. Session layers apply at the next Voice or "
                "Claude session; invocation layers apply when the next matching request is actually sent."
            ),
        }

    def _voice_switch_payload(self) -> dict[str, object]:
        from jarvis.runtime.voice_switch import VoiceSwitchBus
        bus = VoiceSwitchBus(self.runtime_root)
        request, receipt = bus.read_request(), bus.receipt()
        return {
            "pending": request is not None,
            "request_id": request.request_id if request else None,
            "target_configuration_id": request.target_configuration_id if request else (
                receipt.get("target_configuration_id") if isinstance(receipt, dict) else None
            ),
            "status": receipt.get("status") if isinstance(receipt, dict) else None,
            "message": receipt.get("message") if isinstance(receipt, dict) else None,
        }

    async def get_prompts(self, request: web.Request) -> web.Response:
        del request
        try:
            return web.json_response(self._prompt_payload(self._settings()))
        except Exception as exc:
            from jarvis.domain.prompt_registry import PromptError
            if isinstance(exc, (PromptError, VoiceConfigError, ConfigurationError)):
                code = getattr(exc, "code", "prompt_query_invalid")
                raise web.HTTPBadRequest(text=str(exc), headers={SETTINGS_ERROR_CODE_HEADER: code}) from exc
            raise

    async def update_prompt(self, request: web.Request) -> web.Response:
        from jarvis.domain.prompt_registry import PromptError
        from jarvis.runtime.prompt_catalog import default_prompt_registry
        from jarvis.runtime.prompt_overrides import PromptOverrideStore

        identifier = request.match_info["prompt_id"]
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise PromptError("prompt_request_invalid", "Prompt mutation must be an object")
            store = PromptOverrideStore(
                default_prompt_registry(), read_settings=self._settings,
                write_settings=self._write_settings, diagnostics=self.journal,
            )
            action = payload.get("action")
            if action == "reset":
                mutation = store.reset(identifier)
            elif action == "edit" and set(payload) <= {"action", "text", "base_revision", "expected_effective_revision"}:
                mutation = store.edit(
                    identifier,
                    text=payload.get("text"),
                    base_revision=payload.get("base_revision"),
                    expected_effective_revision=payload.get("expected_effective_revision"),
                )
            else:
                raise PromptError("prompt_request_invalid", "Use action edit or reset with the documented fields")
            return web.json_response({"mutation": mutation, "prompts": self._prompt_payload(self._settings())})
        except (PromptError, agent_behavior.AgentBehaviorError, TypeError) as exc:
            code = getattr(exc, "code", "prompt_request_invalid")
            raise web.HTTPBadRequest(text=str(exc), headers={SETTINGS_ERROR_CODE_HEADER: code}) from exc

    async def save_settings(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="settings must be an object")
        current = self._settings()
        from jarvis.runtime.voice_composition import resolve_voice_composition
        try:
            previous_composition = resolve_voice_composition(current)
        except (VoiceConfigError, ConfigurationError):
            previous_composition = None
        creds.migrate_legacy(current)
        switch_to: str | None = None

        try:
            self._validate_delegation_aliases(payload)
            self._apply_voice(current, payload)
            # Champ plat, pendant de `voice_turn_mode` ; vide = revenir au défaut.
            if payload.get("voice_arch") is not None:
                self._store_voice_arch(current, payload["voice_arch"])
            switch_to = self._apply_cli(current, payload)
            if payload.get("routing") is not None:
                agent_routing.apply(current, payload["routing"])
            if payload.get("self_development") is not None:
                apply_self_dev_gate(current, payload["self_development"])
            if payload.get("scene") is not None:
                apply_scene_gate(current, payload["scene"])
            # Behavior extends an editable prompt layer. Validate their
            # combined bound before any atomic settings replacement.
            from jarvis.runtime.prompt_overrides import prompt_override_document
            prompt_override_document(current)
        except (
            voice_stack.VoiceStackError,
            ConversationAuthorizationError,
            cli_catalog.CliSettingsError,
            agent_behavior.AgentBehaviorError,
            creds.CredentialError,
            RoutingError,
            SelfDevError,
            SceneSettingsError,
            VoiceConfigError,
        ) as exc:
            # Le corps reste le message en clair (ce que la page affiche) ; le
            # code stable voyage à côté, pour les clients et les tests.
            agent_error = isinstance(
                exc, (cli_catalog.CliSettingsError, agent_behavior.AgentBehaviorError, RoutingError, SelfDevError, SceneSettingsError)
            )
            self.journal.emit(
                "settings.agent.rejected" if agent_error else "voice.settings.rejected",
                "Settings validation rejected", level="warning", data={"code": exc.code},
            )
            raise web.HTTPBadRequest(text=str(exc), headers={SETTINGS_ERROR_CODE_HEADER: exc.code}) from exc

        # --- réglages plats, conservés pour les clients existants ------------
        if payload.get("realtime_voice") is not None:
            voice = str(payload["realtime_voice"]).strip().lower()
            if voice not in REALTIME_VOICES:
                raise web.HTTPBadRequest(text=f"unknown realtime voice: {voice}")
            voice_stack.store_for(current, voice_stack.OPENAI_REALTIME.id, {"voice": voice})
        if payload.get("voice_turn_mode") is not None:
            mode = str(payload["voice_turn_mode"]).strip().lower()
            if mode not in TURN_MODES:
                raise web.HTTPBadRequest(text=f"unknown voice turn mode: {mode}")
            voice_stack.store_for(current, voice_stack.normalize_stack(current.get("voice_stack")), {"turn_mode": mode})
        if payload.get("claude_permission_mode") is not None:
            mode = str(payload["claude_permission_mode"]).strip()
            if mode not in PERMISSION_MODES:
                raise web.HTTPBadRequest(text=f"unknown Claude permission mode: {mode}")
            self._store_agent(current, "claude", {"permission_mode": mode})
        if payload.get("claude_cli") is not None:
            self._store_agent(current, "claude", {"command": str(payload["claude_cli"]).strip()})
        if payload.get("manual_wake_key") is not None:
            try:
                shortcut_registry.apply(current, {"wake_toggle": payload["manual_wake_key"]})
            except shortcut_registry.ShortcutError as exc:
                raise web.HTTPBadRequest(text=str(exc)) from exc
        if payload.get("active_timeout_s") is not None:
            current["active_timeout_s"] = self._active_timeout(payload["active_timeout_s"])

        for key in ("audio_input_device", "audio_output_device"):
            if key in payload:
                try:
                    device = normalize_device_id(payload[key])
                except ValueError as exc:
                    raise web.HTTPBadRequest(text=str(exc)) from exc
                current[key] = "" if device is None else str(device)
        audio = payload.get("audio")
        if isinstance(audio, dict):
            for source, target in (("input_device", "audio_input_device"), ("output_device", "audio_output_device")):
                if source in audio:
                    try:
                        device = normalize_device_id(audio[source])
                    except ValueError as exc:
                        raise web.HTTPBadRequest(text=str(exc)) from exc
                    current[target] = "" if device is None else str(device)
            if audio.get("active_timeout_s") is not None:
                current["active_timeout_s"] = self._active_timeout(audio["active_timeout_s"])

        for key in ("openai_api_key", "porcupine_access_key"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                current[key] = value.strip()
                creds.migrate_legacy(current)

        self._mirror_legacy(current)
        # Une combinaison que Voice refuserait au démarrage n'est pas écrite :
        # l'erreur tombe ici, en clair, plutôt qu'au prochain lancement de Voice.
        problem = self._voice_arch_problem(current)
        if problem:
            raise web.HTTPBadRequest(text=problem)
        voice_payload = payload.get("voice")
        if isinstance(voice_payload, dict) and "architecture" in voice_payload:
            problem = self._voice_architecture_payload(current)["problem"]
            if problem:
                self.journal.emit("voice.settings.rejected", "Settings validation rejected", level="warning", data={"code": problem["code"]})
                raise web.HTTPBadRequest(text=problem["message"], headers={SETTINGS_ERROR_CODE_HEADER: problem["code"]})
        switch_values = None
        try:
            target = resolve_voice_composition(current)
        except (VoiceConfigError, ConfigurationError):
            # An injected/extended Settings registry may describe an adapter
            # this production composition root does not own.
            target = None
        if target is not None and previous_composition is not None:
            from jarvis.domain.voice_architecture import FrontBrainVoiceConfig
            from jarvis.runtime.voice_switch import VoiceSwitchBus
            config = target.selection.config
            model = (config.reflex_model if isinstance(config, FrontBrainVoiceConfig)
                     else config.conversation_model).model_id
            runtime = VisualSignalBus._read_json(self.runtime_root / VisualSignalBus.VOICE_RUNTIME_FILE)
            runtime_id = runtime.get("configuration_id") if isinstance(runtime, dict) else None
            runtime_ts = runtime.get("ts") if isinstance(runtime, dict) else None
            source_id = previous_composition.configuration_id
            if (isinstance(runtime_id, str) and isinstance(runtime_ts, (int, float))
                    and not isinstance(runtime_ts, bool)
                    and time.time() - float(runtime_ts) <= VOICE_HEARTBEAT_MAX_AGE_S):
                source_id = runtime_id
            # La projection de compatibilité conserve volontairement un
            # modèle Gemini manquant pour que Settings puisse être réparé.
            # Ce n'est pas encore une cible démarrable : ne pas arrêter Voice.
            if source_id != target.configuration_id and model:
                switch_values = (VoiceSwitchBus(self.runtime_root), source_id,
                                 target.configuration_id, config.architecture.value, model)
        self._write_settings(current)
        if switch_values is not None:
            bus, source_id, target_id, architecture, model = switch_values
            issued = bus.request(source_configuration_id=source_id,
                                 target_configuration_id=target_id,
                                 target_architecture=architecture, target_model=model)
            self.journal.emit(
                "voice.switch.requested", "Voice architecture switch requested",
                data={"request_id": issued.request_id,
                      "source_configuration_id": source_id,
                      "target_configuration_id": target_id,
                      "target_architecture": architecture, "target_model": model},
            )
        if switch_to is not None:
            await self._switch_agent(switch_to, current)
        else:
            self._apply_agent_settings(current)
        self.journal.emit("settings.update", "Control Center settings updated", data={"keys": sorted(payload.keys())})
        return web.json_response(self._settings_payload(current))

    @staticmethod
    def _active_timeout(raw: Any) -> str:
        """Valider le délai d'inactivité avant de l'écrire dans les réglages.

        `0` veut dire « jamais ». Un champ vidé est gardé vide : Voice retombe
        alors sur `JARVIS_ACTIVE_TIMEOUT_S`, comme avant. Tout le reste doit être
        un nombre d'au moins cinq secondes, sinon Voice l'ignorerait en silence.
        """
        text = str(raw).strip()
        if not text:
            return ""
        try:
            parse_active_timeout(text)
        except ConfigurationError as exc:
            raise web.HTTPBadRequest(
                text=(
                    f"Délai d'inactivité invalide (« {text} ») : indiquez 0 pour ne jamais "
                    f"mettre en veille, ou une durée d'au moins {MIN_ACTIVE_TIMEOUT_S:g} secondes."
                )
            ) from exc
        return text

    def _apply_voice(self, current: dict[str, Any], payload: dict[str, Any]) -> None:
        voice = payload.get("voice")
        if not isinstance(voice, dict):
            return
        if "architecture" in voice:
            registry = self._voice_architecture_registry(current)
            config = parse_voice_mode(voice["architecture"], registry)
            registry.validate(config, require_ready=True)
            store_voice_architecture(current, config, registry)
        if voice.get("stack") is not None:
            stack_id = str(voice["stack"]).strip().lower()
            if stack_id not in voice_stack.VOICE_STACK_IDS:
                raise voice_stack.VoiceStackError(
                    "voice_unknown_stack", f"Pile vocale inconnue : {stack_id}."
                )
            current["voice_stack"] = stack_id
        if voice.get("arch") is not None:
            self._store_voice_arch(current, voice["arch"])
        if isinstance(voice.get("authorization"), dict):
            self._store_authorization(current, voice["authorization"], runtime_root=self.runtime_root)
        values = voice.get("settings")
        if isinstance(values, dict):
            for stack_id, stack_values in values.items():
                if stack_id not in voice_stack.VOICE_STACK_IDS or not isinstance(stack_values, dict):
                    continue
                spec = voice_stack.stack_spec(stack_id)
                voice_stack.store_for(current, stack_id, voice_stack.coerce(spec, stack_values))

    def _store_agent(self, current: dict[str, Any], agent_id: str, values: dict[str, Any]) -> None:
        stored = current.get("agent_cli_settings")
        stored = dict(stored) if isinstance(stored, dict) else {}
        entry = dict(stored.get(agent_id) or {})
        entry.update(values)
        stored[agent_id] = entry
        current["agent_cli_settings"] = stored

    def _apply_cli(self, current: dict[str, Any], payload: dict[str, Any]) -> str | None:
        cli = payload.get("cli")
        if not isinstance(cli, dict):
            return None
        switch_to: str | None = None
        if cli.get("agent") is not None:
            agent_id = str(cli["agent"]).strip().lower()
            if agent_id not in cli_catalog.AGENT_CLI_IDS:
                raise cli_catalog.CliSettingsError("cli_unknown_agent", f"CLI inconnu : {agent_id}.")
            if agent_id != current.get("agent_cli"):
                switch_to = agent_id
            current["agent_cli"] = agent_id
        if cli.get("delegation_mode") is not None:
            agent_routing.apply_delegation_mode(current, cli["delegation_mode"])
        if cli.get("behavior") is not None:
            agent_behavior.apply(current, cli["behavior"])
        values = cli.get("settings")
        if isinstance(values, dict):
            for agent_id, entry in values.items():
                if agent_id not in cli_catalog.AGENT_CLI_IDS or not isinstance(entry, dict):
                    continue
                spec = cli_catalog.spec_for(agent_id)
                clean: dict[str, Any] = {}
                if entry.get("command") is not None:
                    command = str(entry["command"]).strip()
                    if not command:
                        raise cli_catalog.CliSettingsError(
                            "cli_empty_command", f"La commande {spec.label} ne peut pas être vide."
                        )
                    clean["command"] = command
                if entry.get("model") is not None:
                    clean["model"] = str(entry["model"]).strip()
                if entry.get("permission_mode") is not None:
                    mode = str(entry["permission_mode"]).strip()
                    if mode not in spec.permission_modes:
                        raise cli_catalog.CliSettingsError(
                            "cli_unknown_permission_mode",
                            f"« {mode} » n'est pas une valeur acceptée pour {spec.permission_label} ({spec.label}).",
                        )
                    clean["permission_mode"] = mode
                if clean:
                    self._store_agent(current, agent_id, clean)
        return switch_to

    @staticmethod
    def _validate_delegation_aliases(payload: dict[str, Any]) -> None:
        """Reject contradictory canonical and legacy routing switches atomically."""
        cli = payload.get("cli")
        routing_payload = payload.get("routing")
        if not isinstance(cli, dict) or "delegation_mode" not in cli:
            return
        if not isinstance(routing_payload, dict) or "enabled" not in routing_payload:
            return
        canonical_enabled = agent_routing.delegation_enabled(cli["delegation_mode"])
        if canonical_enabled != bool(routing_payload["enabled"]):
            raise RoutingError(
                "agent_settings_conflicting_delegation_mode",
                "Les modes de sous-agents canonique et historique se contredisent.",
            )

    # ------------------------------------------------------------ API keys

    async def get_credentials(self, request: web.Request) -> web.Response:
        del request
        settings = self._settings()
        if creds.migrate_legacy(settings):
            self._write_settings(settings)
        return web.json_response(creds.credentials_state(settings))

    async def save_credential(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="credential must be an object")
        settings = self._settings()
        creds.migrate_legacy(settings)
        credential_id = str(payload.get("id") or "")
        previous_providers = {
            str(item.get("provider") or "").strip().lower()
            for item in settings.get("credentials", ())
            if isinstance(item, dict) and str(item.get("id") or "") == credential_id
        }
        try:
            record = creds.upsert_credential(
                settings,
                credential_id=str(payload.get("id") or "") or None,
                provider=str(payload.get("provider") or ""),
                name=str(payload.get("name") or ""),
                value=payload.get("value"),
            )
        except creds.CredentialError as exc:
            return web.json_response({"ok": False, "code": exc.code, "error": str(exc)}, status=400)
        self._write_settings(settings)
        for provider in previous_providers | {str(record["provider"])}:
            if provider:
                self.catalog.invalidate(provider)
        self.journal.emit(
            "settings.credential",
            f"Clé {record['provider']} enregistrée : {record['name']}",
            data={"provider": record["provider"], "name": record["name"], "hint": record["hint"]},
        )
        return web.json_response({"ok": True, "credential": record, **creds.credentials_state(settings)})

    async def remove_credential(self, request: web.Request) -> web.Response:
        payload = await request.json()
        credential_id = str(payload.get("id") or "") if isinstance(payload, dict) else ""
        if not credential_id:
            raise web.HTTPBadRequest(text="id is required")
        settings = self._settings()
        creds.migrate_legacy(settings)
        providers = {
            str(item.get("provider") or "").strip().lower()
            for item in settings.get("credentials", ())
            if isinstance(item, dict) and str(item.get("id") or "") == credential_id
        }
        if not creds.delete_credential(settings, credential_id):
            return web.json_response({"ok": False, "code": "credential_not_found", "error": "Cette clé n'existe plus."}, status=404)
        self._write_settings(settings)
        for provider in providers:
            if provider:
                self.catalog.invalidate(provider)
        self.journal.emit("settings.credential", "Clé API supprimée", data={"id": credential_id})
        return web.json_response({"ok": True, **creds.credentials_state(settings)})

    async def bind_credential(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="binding must be an object")
        settings = self._settings()
        creds.migrate_legacy(settings)
        provider = str(payload.get("provider") or "").strip().lower()
        credential_id = str(payload.get("id") or "") or None
        previous_id = (settings.get("credential_bindings") or {}).get(provider)
        try:
            creds.bind_credential(settings, provider, credential_id)
        except creds.CredentialError as exc:
            return web.json_response({"ok": False, "code": exc.code, "error": str(exc)}, status=400)
        self._write_settings(settings)
        # Une clé qui change invalide le catalogue : les modèles visibles
        # dépendent du compte, pas seulement du fournisseur.
        if previous_id != credential_id:
            self.catalog.invalidate(provider)
        return web.json_response({"ok": True, **creds.credentials_state(settings)})

    # ------------------------------------------------------------- catalogues

    async def _catalog_sources(
        self,
        settings: dict[str, Any],
        providers: set[str],
        *,
        refresh: bool,
    ) -> dict[str, dict[str, Any]]:
        """Measure provider catalogs while preserving failures as evidence."""
        async def fetch(provider: str) -> tuple[str, dict[str, Any]]:
            api_key = creds.secret_for(settings, provider)
            try:
                result = await self.catalog.models(
                    provider,
                    api_key,
                    refresh=refresh,
                )
            except CatalogError as exc:
                stale = self.catalog.cached_for(provider, api_key)
                self.journal.emit(
                    "provider.models_failed",
                    str(exc),
                    level="warning",
                    data={"provider": provider, "code": exc.code},
                )
                if stale is not None:
                    return provider, {**stale, "source": "stale", "status_code": exc.code}
                return provider, {"models": [], "source": "unknown", "status_code": exc.code}
            return provider, result

        measured = await asyncio.gather(*(fetch(provider) for provider in sorted(providers)))
        return dict(measured)

    async def catalog_view(self, request: web.Request) -> web.Response:
        """Canonical sourced comparison view; never mutates routing or settings."""
        surface = str(request.query.get("surface", "")).strip().lower()
        if surface not in {"subagents", "voice"}:
            return web.json_response(
                {"ok": False, "code": "catalog_surface_invalid", "error": "surface must be subagents or voice"},
                status=400,
            )
        default_role = "subagent" if surface == "subagents" else ""
        role = str(request.query.get("role", default_role)).strip().lower()
        allowed_roles = SUBAGENT_ROLES if surface == "subagents" else VOICE_ROLES | {""}
        if role not in allowed_roles:
            return web.json_response(
                {"ok": False, "code": "catalog_role_invalid", "error": f"role is not valid for {surface}"},
                status=400,
            )
        refresh = str(request.query.get("refresh", "")).strip().lower() in {"1", "true", "yes"}
        settings = self._settings()

        if surface == "subagents":
            commands = {
                spec.id: self._agent_settings(settings, spec.id)["command"]
                for spec in cli_catalog.AGENT_CLIS
            }
            agents = await cli_catalog.detect_all(commands)
            providers = {spec.model_provider for spec in cli_catalog.AGENT_CLIS}
            catalogs = await self._catalog_sources(settings, providers, refresh=refresh)
            policy = agent_routing.load_policy(settings)
            saved = tuple(ref for profile in policy.profiles for ref in profile.candidates)
            view = self._catalog_view_service.subagents(
                agents=agents,
                catalogs=catalogs,
                saved=saved,
                role=role,
                active_agent=self._agent_id,
                routing_enabled=policy.enabled,
            )
        else:
            providers = {stack.credential_provider for stack in voice_stack.VOICE_STACKS}
            catalogs = await self._catalog_sources(settings, providers, refresh=refresh)
            view = self._catalog_view_service.voice(
                registry=self._voice_architecture_registry(settings),
                catalogs=catalogs,
                role=role,
            )
        return web.json_response({"ok": True, **view.to_dict()})

    async def models(self, request: web.Request) -> web.Response:
        provider = str(request.query.get("provider", "")).strip().lower()
        role = str(request.query.get("role", "")).strip().lower()
        refresh = str(request.query.get("refresh", "")).strip().lower() in {"1", "true", "yes"}
        settings = self._settings()
        api_key = creds.secret_for(settings, provider)
        try:
            result = await self.catalog.models(provider, api_key, refresh=refresh)
        except CatalogError as exc:
            stale = self.catalog.cached_for(provider, api_key)
            self.journal.emit(
                "provider.models_failed",
                str(exc),
                level="warning",
                data={"provider": provider, "code": exc.code},
            )
            body: dict[str, Any] = {"ok": False, "provider": provider, "code": exc.code, "error": str(exc)}
            if stale is not None:
                # Un catalogue périmé vaut mieux qu'une liste vide, à condition
                # de dire qu'il l'est : l'interface l'affiche comme tel.
                body["models"] = filter_by_role(list(stale.get("models") or []), role)
                body["fetched_at"] = stale.get("fetched_at")
                body["source"] = "stale"
            return web.json_response(body, status=200 if stale is not None else 424)
        return web.json_response(
            {
                "ok": True,
                "provider": provider,
                "role": role,
                "source": result.get("source"),
                "fetched_at": result.get("fetched_at"),
                "models": filter_by_role(list(result.get("models") or []), role),
            }
        )

    async def routing_candidates(self, request: web.Request) -> web.Response:
        """Les couples agent + modèle proposables maintenant, et leur état.

        Deux mesures, pas une supposition : quels CLI répondent à `--version`,
        et quels modèles texte le fournisseur déclare. Un catalogue injoignable
        ne vide pas l'écran — le dernier connu sert, dit périmé — et les
        préférences enregistrées restent visibles même devenues inutilisables.
        """
        del request
        settings = self._settings()
        policy = agent_routing.load_policy(settings)
        commands = {spec.id: self._agent_settings(settings, spec.id)["command"] for spec in cli_catalog.AGENT_CLIS}
        detected = await cli_catalog.detect_all(commands)
        agents = [
            {**entry, "capabilities": list(cli_catalog.spec_for(entry["id"]).capabilities)}
            for entry in detected
        ]

        models: dict[str, list[dict[str, Any]]] = {}
        sources: dict[str, str] = {}
        snapshots: dict[str, ProviderCatalogSnapshot] = {}
        for provider in sorted({spec.model_provider for spec in cli_catalog.AGENT_CLIS}):
            api_key = creds.secret_for(settings, provider)
            try:
                result = await self.catalog.models(provider, api_key)
            except CatalogError as exc:
                stale = self.catalog.cached_for(provider, api_key)
                sources[provider] = "stale" if stale is not None else exc.code
                result = (
                    {**stale, "source": "stale", "status_code": exc.code}
                    if stale is not None
                    else {"models": [], "source": "unknown", "status_code": exc.code}
                )
            else:
                sources[provider] = str(result.get("source") or "live")
            snapshot = ProviderCatalogSnapshot.from_payload(
                provider,
                result,
                now=datetime.now(timezone.utc),
            )
            snapshots[provider] = snapshot
            models[provider] = filter_by_role(list(snapshot.current_models("text")), "text")

        unavailable_reasons = {
            spec.id: "Disponibilité non vérifiée : catalogue fournisseur absent ou périmé."
            for spec in cli_catalog.AGENT_CLIS
            if not snapshots[spec.model_provider].authoritative
        }
        candidates = agent_routing.with_saved(
            agent_routing.build_candidates(agents, models),
            policy,
            unavailable_reasons_by_agent=unavailable_reasons,
        )
        return web.json_response({"ok": True, "sources": sources, **agent_routing.describe(policy, candidates)})

    # ------------------------------------------------- auto-développement

    @property
    def self_dev(self) -> SelfDevelopmentService:
        """Construit à la demande : rien ne tourne tant que personne ne demande."""
        if self._self_dev is None:
            self._self_dev = SelfDevelopmentService(
                project_root=self.project_root,
                runtime_root=self.runtime_root,
                settings=self._settings,
                journal=self.journal,
            )
        return self._self_dev

    async def self_dev_state(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(await self.self_dev.state())

    async def self_dev_start(self, request: web.Request) -> web.Response:
        """Ouvrir un chantier et rendre la main : le travail continue en fond."""
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="self-dev request must be an object")
        profile = str(payload.get("profile") or "code")
        try:
            job = self.self_dev.start(str(payload.get("request") or ""), profile=profile)
        except SelfDevError as exc:
            return web.json_response({"ok": False, "code": exc.code, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, "job": job.as_dict()})

    async def self_dev_deploy(self, request: web.Request) -> web.Response:
        payload = await request.json()
        job_id = str(payload.get("job_id") or "") if isinstance(payload, dict) else ""
        try:
            deployment = await self.self_dev.deploy(job_id)
        except SelfDevError as exc:
            return web.json_response({"ok": False, "code": exc.code, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, "deployment": deployment})

    async def cli_agents(self, request: web.Request) -> web.Response:
        del request
        settings = self._settings()
        commands = {spec.id: self._agent_settings(settings, spec.id)["command"] for spec in cli_catalog.AGENT_CLIS}
        detected = await cli_catalog.detect_all(commands)
        return web.json_response(
            {
                "ok": True,
                "active": self._agent_id,
                "agents": detected,
                "settings": {spec.id: self._agent_settings(settings, spec.id) for spec in cli_catalog.AGENT_CLIS},
            }
        )

    # ------------------------------------------------------------- raccourcis

    async def get_shortcuts(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(shortcut_registry.describe(self._settings()))

    async def save_shortcuts(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="shortcuts must be an object")
        values = payload.get("shortcuts") if isinstance(payload.get("shortcuts"), dict) else payload
        settings = self._settings()
        try:
            shortcut_registry.apply(settings, values)
        except shortcut_registry.ShortcutError as exc:
            return web.json_response({"ok": False, "code": exc.code, "error": str(exc)}, status=400)
        self._mirror_legacy(settings)
        self._write_settings(settings)
        self.journal.emit("settings.shortcuts", "Raccourcis mis à jour", data={"keys": sorted(values.keys())})
        return web.json_response({"ok": True, **shortcut_registry.describe(settings)})

    # ------------------------------------------------------------------ audio

    async def audio_devices(self, request: web.Request) -> web.Response:
        del request
        correlation_id = uuid.uuid4().hex
        try:
            result = await asyncio.to_thread(self.audio_diagnostics.list_devices)
        except AudioDiagnosticError as exc:
            self.journal.emit(
                "audio.devices.failed",
                str(exc),
                level="error",
                data={"correlation_id": correlation_id, "code": exc.code, **exc.context},
            )
            return web.json_response(
                {"ok": False, "correlation_id": correlation_id, "code": exc.code, "error": str(exc)},
                status=503,
            )
        self.journal.emit(
            "audio.devices.listed",
            "Audio devices enumerated",
            data={
                "correlation_id": correlation_id,
                "input_count": len(result.get("inputs", [])),
                "output_count": len(result.get("outputs", [])),
            },
        )
        return web.json_response({"ok": True, "correlation_id": correlation_id, **result})

    async def audio_test(self, request: web.Request) -> web.Response:
        correlation_id = uuid.uuid4().hex
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("audio test payload must be an object")
            input_device = normalize_device_id(payload.get("input_device"))
            output_device = normalize_device_id(payload.get("output_device"))
        except (ValueError, json.JSONDecodeError) as exc:
            self.journal.emit(
                "audio.test.failed",
                "Invalid audio test request",
                level="error",
                data={"correlation_id": correlation_id, "code": "audio_test_invalid_request"},
            )
            return web.json_response(
                {"ok": False, "correlation_id": correlation_id, "code": "audio_test_invalid_request", "error": str(exc)},
                status=400,
            )

        if self._audio_test_lock.locked():
            self.journal.emit(
                "audio.test.failed",
                "An audio test is already running",
                level="error",
                data={"correlation_id": correlation_id, "code": "audio_test_busy"},
            )
            return web.json_response(
                {"ok": False, "correlation_id": correlation_id, "code": "audio_test_busy", "error": "Un test audio est déjà en cours."},
                status=409,
            )

        self.journal.emit(
            "audio.test.started",
            "Audio record and playback test started",
            data={"correlation_id": correlation_id, "input_device": input_device, "output_device": output_device},
        )
        try:
            async with self._audio_test_lock:
                result = await asyncio.to_thread(
                    self.audio_diagnostics.test_record_and_playback,
                    input_device=input_device,
                    output_device=output_device,
                )
        except AudioDiagnosticError as exc:
            self.journal.emit(
                "audio.test.failed",
                str(exc),
                level="error",
                data={"correlation_id": correlation_id, "code": exc.code, **exc.context},
            )
            return web.json_response(
                {"ok": False, "correlation_id": correlation_id, "code": exc.code, "error": str(exc), **exc.context},
                status=422,
            )
        except Exception as exc:
            self.journal.emit(
                "audio.test.failed",
                "Unexpected audio diagnostic failure",
                level="error",
                data={"correlation_id": correlation_id, "code": "audio_test_unexpected", "exception_type": type(exc).__name__},
            )
            return web.json_response(
                {"ok": False, "correlation_id": correlation_id, "code": "audio_test_unexpected", "error": "Le test audio a échoué de manière inattendue."},
                status=500,
            )

        self.journal.emit(
            "audio.test.completed",
            "Audio record and playback test completed",
            data={"correlation_id": correlation_id, "peak_dbfs": result.get("peak_dbfs"), "rms_dbfs": result.get("rms_dbfs")},
        )
        return web.json_response({"correlation_id": correlation_id, **result})

    # ------------------------------------------------------------------ agent

    async def agent_status(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(self.agent.snapshot())

    async def agent_console_open(self, request: web.Request) -> web.Response:
        """Ouvrir la véritable console sur la conversation en cours."""
        del request
        try:
            return web.json_response(await self.agent.open_console())
        except RuntimeError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc

    async def agent_console_close(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(await self.agent.close_console())

    async def agent_transcript(self, request: web.Request) -> web.Response:
        """Historique lisible de l'agent, au-delà de l'extrait du statut."""
        try:
            limit = min(max(int(request.query.get("limit", "200")), 1), 500)
        except ValueError:
            limit = 200
        snapshot = self.agent.snapshot()
        return web.json_response({
            "name": snapshot.get("name"),
            "agent_cli": self._agent_id,
            "state": snapshot["state"],
            "pid": snapshot["pid"],
            "returncode": snapshot["returncode"],
            "command": self.agent.command,
            "cwd": str(self.agent.cwd),
            "session_id": self.agent.session_id,
            "console": self.agent.console_snapshot(),
            "events": self.agent.transcript(limit=limit),
        })

    async def work(self, request: web.Request) -> web.Response:
        """État de travail normalisé tenu par Core, projeté pour le panneau Agents (tâche 13).

        Source de vérité des cartes : statut, libellé, activité, modèle,
        dates, résumé, `error_class`. Lecture seule — aucune route du Control
        Center ne modifie l'état de travail de Core. `now_ms` (horloge de ce
        processus, comme `/api/agent/tasks`) sert au client à corriger son
        décalage ; les durées se calculent depuis `started_at` / `ended_at`.
        `subtasks_supported` dit si l'agent actif relaie ses sous-tâches à
        Core : faux pour Codex, dont aucun format n'est vérifié.
        """
        del request
        if self.work_view is None:
            body = unavailable_payload(NOT_CONFIGURED, "Lecture de l'état de travail Core non configurée.")
        else:
            body = await self.work_view.read()
        # Lecture seule jusqu'au bout : `self.agent` construirait l'agent au
        # premier appel (abonnement d'un observateur, reprise de
        # `work_ingress.on_resync`). Seul l'agent déjà bâti est lu ; sans lui,
        # l'horloge de ce processus — celle-là même que porte son suivi.
        agent = self._agents.get(self._agent_id)
        body["now_ms"] = agent.subtasks.now_ms() if agent is not None else int(time.time() * 1000)
        body["agent_cli"] = self._agent_id
        body["subtasks_supported"] = self._agent_id == "claude" and self.work_ingress is not None
        return web.json_response(body)

    # ------------------------------------------------------------------ scène

    @staticmethod
    def _scene_error(status: int, code: str, message: str) -> web.Response:
        return web.json_response(scene_wire.error_body(code, message), status=status)

    async def scene(self, request: web.Request) -> web.Response:
        """Instantané de la scène constellation tenue par Core (Slice 03).

        Toujours 200, comme `/api/work` : Core injoignable, réponse illisible
        ou scène indisponible donnent `snapshot: null` et `error` (`code`,
        `message`), avec `core_reachable` et `scene` (`state`, `code`).
        """

        if request.query:
            return self._scene_error(400, scene_wire.INVALID_REQUEST, "unexpected query")
        if self.scene_view is None:
            body = unavailable_snapshot_payload(NOT_CONFIGURED, "Lecture de la scène Core non configurée.")
        else:
            body = await self.scene_view.snapshot()
        return web.json_response(body, dumps=scene_wire.compact_json)

    async def scene_patches(self, request: web.Request) -> web.Response:
        """Long-poll des patchs de scène (`scene_id`, `epoch`, `after`, `wait_s` ≤ 25 s ici).

        Paramètres invalides : 400. Sinon 200 : patchs, `resync_required`
        (relire `/api/scene`), `more` (redemander aussitôt), ou forme dégradée
        avec `error`. L'attente est bornée côté Control Center aussi : un
        Core figé rend la main après l'attente demandée plus une marge.
        """

        try:
            query = scene_wire.parse_patch_query(request.query)
        except ValueError as exc:
            return self._scene_error(400, scene_wire.INVALID_REQUEST, str(exc))
        if self.scene_view is None:
            body = unavailable_patches_payload(NOT_CONFIGURED, "Lecture de la scène Core non configurée.")
        else:
            body = await self.scene_view.patches(query)
        return web.json_response(body, dumps=scene_wire.compact_json)

    async def scene_command(self, request: web.Request) -> web.Response:
        """Commande de scène du navigateur, relayée à Core avec l'acteur `user` imposé.

        Sans `actor`, `user` est posé ; tout autre acteur est refusé (403
        `scene_actor_forbidden`) : la page ne parle jamais au nom du cerveau.
        Corps illisible : 400 ; trop gros : 413. Refus du domaine : 200 avec
        `outcome`/`reason`. Voir `CoreSceneView.command` pour 502/503/504.
        """

        if request.query:
            return self._scene_error(400, scene_wire.INVALID_REQUEST, "unexpected query")
        try:
            raw = await scene_wire.read_bounded_body(request)
        except scene_wire.SceneBodyTooLarge:
            return self._scene_error(413, scene_wire.PAYLOAD_TOO_LARGE, f"scene command exceeds {scene_wire.MAX_SCENE_COMMAND_BYTES} bytes")
        try:
            command = user_command(loads_strict_json(raw, invalid_message="invalid scene command JSON"))
        except SceneActorForbidden as exc:
            suppressed = self._scene_forbidden_reports.admit(exc.actor)
            if suppressed is not None:
                self.journal.emit(
                    "scene.command_forbidden", f"commande de scène refusée : acteur {exc.actor} au lieu de user", level="warning",
                    data={"code": scene_wire.SCENE_ACTOR_FORBIDDEN, "actor": exc.actor, "suppressed": suppressed},
                )
            return self._scene_error(403, scene_wire.SCENE_ACTOR_FORBIDDEN, str(exc))
        except (TypeError, ValueError) as exc:
            return self._scene_error(400, scene_wire.INVALID_REQUEST, f"invalid scene command: {exc}")
        if self.scene_view is None:
            return self._scene_error(503, NOT_CONFIGURED, "Commande de scène Core non configurée.")
        status, body = await self.scene_view.command(command)
        return web.json_response(body, status=status, dumps=scene_wire.compact_json)

    async def job_cancel(self, request: web.Request) -> web.Response:
        """Arrêt d'une étoile `job` depuis son menu (Slice 08) : `{source, external_id}`.

        Origine vérifiée par le middleware (`_origin_guard`, comme tout POST).
        Seule la source `job` part vers Core (`POST /v1/work/cancel`) ; toute
        autre est refusée ici (409 `not_cancellable`) : un sous-agent Claude n'a
        pas d'arrêt individuel. Corps borné et strict (400), 503 sans Core.
        """

        if request.query:
            return self._scene_error(400, scene_wire.INVALID_REQUEST, "unexpected query")
        try:
            raw = await scene_wire.read_bounded_body(request, limit=scene_wire.MAX_WORK_CANCEL_BYTES)
        except scene_wire.SceneBodyTooLarge:
            return self._scene_error(413, scene_wire.PAYLOAD_TOO_LARGE, f"work cancel request exceeds {scene_wire.MAX_WORK_CANCEL_BYTES} bytes")
        try:
            body = loads_strict_json(raw, invalid_message="invalid work cancel JSON")
            if not isinstance(body, dict) or set(body) != {"source", "external_id"}:
                raise ValueError("work cancel request must be {source, external_id}")
            source, external_id = body["source"], body["external_id"]
            if not isinstance(source, str) or not isinstance(external_id, str) or not external_id.strip() or len(external_id) > 128:
                raise ValueError("source and external_id must be short non-empty strings")
        except ValueError as exc:
            return self._scene_error(400, scene_wire.INVALID_REQUEST, str(exc))
        if self.scene_view is None:
            return self._scene_error(503, NOT_CONFIGURED, "Arrêt de job : Core non configuré.")
        status, payload = await self.scene_view.cancel_work(source, external_id)
        return web.json_response(payload, status=status, dumps=scene_wire.compact_json)

    async def agent_tasks(self, request: web.Request) -> web.Response:
        """Le brain et ses sous-tâches. Toujours ceux de l'agent actif : après
        une bascule Claude ↔ Codex, c'est le nouvel agent qui répond.

        Depuis la tâche 13, diagnostic seulement pour les sous-tâches : le
        panneau lit leur état dans `/api/work` (Core) et ne prend ici que ce
        que Core ne porte pas (prompt, type de sous-agent, trace), joint par
        `work_key` = `external_id`. Conservé tel quel pour compatibilité."""
        del request
        return web.json_response(self.agent.tasks_snapshot())

    async def agent_task_trace(self, request: web.Request) -> web.Response:
        task_id = str(request.match_info.get("task_id") or "")
        try:
            limit = min(max(int(request.query.get("limit", "300")), 1), 500)
        except ValueError:
            limit = 300
        trace = self.agent.task_trace(task_id, limit=limit)
        if trace is None:
            return web.json_response(
                {"ok": False, "code": "agent_task_not_found", "error": f"Tâche inconnue : {task_id}"},
                status=404,
            )
        return web.json_response(trace)

    async def agent_start(self, request: web.Request) -> web.Response:
        del request
        try:
            return web.json_response(await self.agent.start())
        except RuntimeError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc

    async def agent_restart(self, request: web.Request) -> web.Response:
        del request
        try:
            return web.json_response(await self.agent.restart())
        except RuntimeError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc

    async def agent_kill(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(await self.agent.stop())

    async def agent_ask(self, request: web.Request) -> web.Response:
        """Aller-retour complet : c'est ce que consomme la boucle vocale."""
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="ask payload must be an object")
        text = str(payload.get("text") or "").strip()
        if not text:
            raise web.HTTPBadRequest(text="text is required")
        try:
            timeout_s = min(max(float(payload.get("timeout_s") or 600.0), 5.0), 1800.0)
        except (TypeError, ValueError):
            timeout_s = 180.0
        # `context` est optionnel et ne l'était pas avant : la passerelle legacy
        # et le panneau navigateur appellent sans, et reçoivent alors exactement
        # le texte d'avant. Seul Core, qui connaît l'état public, le remplit.
        context = payload.get("context")
        settings = self._settings()
        behavior_active = bool(agent_behavior.prompt_instruction(settings))
        if isinstance(context, dict) or behavior_active:
            from jarvis.runtime.prompt_overrides import prompt_override_document
            from jarvis.runtime.prompt_runtime import compose_agent_turn
            prompt, evidence = compose_agent_turn(
                agent_id=self._agent_id, model=self.agent.model or None, request_text=text,
                overrides=prompt_override_document(settings), behavior_active=behavior_active,
                context=context if isinstance(context, dict) else None,
            )
        else:
            prompt = text
            evidence = None
        from jarvis.runtime.prompt_runtime import accepts_keyword_argument, accepts_prompt_evidence
        supports_evidence = accepts_prompt_evidence(self.agent.ask)
        ask_kwargs: dict[str, object] = {"timeout_s": timeout_s}
        if evidence is not None and supports_evidence:
            ask_kwargs["prompt_evidence"] = evidence
        if evidence is not None and accepts_keyword_argument(self.agent.ask, "input_text"):
            # The composed model prompt may contain private saved instructions.
            # Native agents use this canonical input only for trace/UI history.
            ask_kwargs["input_text"] = text
        result = await self.agent.ask(prompt, **ask_kwargs)
        return web.json_response(result)

    async def background_events(self, request: web.Request) -> web.Response:
        """Ce qui s'est passé en arrière-plan, du plus récent au plus ancien."""
        try:
            limit = min(max(int(request.query.get("limit", "40")), 1), MAX_ENTRIES)
        except ValueError:
            limit = 40
        try:
            follow(self.background, self._background_trace)
        except Exception:
            pass
        return web.json_response({"ok": True, **self.background.to_payload(limit=limit)})

    async def background_ack(self, request: web.Request) -> web.Response:
        """Marquer vu. Sans `seq`, tout ce qui est connu à cet instant.

        Un `seq` explicite évite d'effacer un événement arrivé entre le rendu
        de la liste et le clic : on n'acquitte que ce qui a été affiché.
        Avec `category`, seule la pastille correspondante est acquittée.
        """
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            body = {}
        seq = body.get("seq") if isinstance(body, dict) else None
        category = body.get("category") if isinstance(body, dict) else None
        if category is not None and category not in BACKGROUND_CATEGORIES:
            return web.json_response({"ok": False, "error": f"catégorie inconnue : {category}"}, status=400)
        cursor = self.background.acknowledge(
            seq if isinstance(seq, int) and not isinstance(seq, bool) else None,
            category=category,
        )
        return web.json_response({"ok": True, "acknowledged": cursor, "unread": self.background.unread,
                                  "counts": self.background.counts()})

    async def agent_notices(self, request: web.Request) -> web.Response:
        """Réponses que le brain a produites sans question : relais de fin de sous-agent.

        Attente longue (`wait`, 25 s au plus) : Core interroge en boucle et
        reçoit une réponse dès qu'un relais existe. `epoch` identifie la file :
        un lecteur qui n'en a pas encore reçoit l'époque et le dernier numéro
        sans rien rejouer ; un lecteur dont l'époque a changé (agent recréé)
        reçoit tout ce que la nouvelle file contient déjà.
        """
        agent = self.agent
        if not callable(getattr(agent, "wait_notices", None)):
            # Codex n'ouvre pas de tour de lui-même : rien à relayer.
            return web.json_response({"ok": True, "supported": False, "notices": [], "epoch": "", "last_seq": 0})
        try:
            after = int(request.query.get("after", "0"))
            wait_s = min(max(float(request.query.get("wait", "25")), 0.0), 25.0)
        except ValueError:
            raise web.HTTPBadRequest(text="after and wait must be numbers") from None
        epoch = str(agent.notice_epoch)
        known = request.query.get("epoch", "")
        if not known:
            return web.json_response({"ok": True, "supported": True, "notices": [], "epoch": epoch, "last_seq": agent.last_notice_seq})
        if known != epoch:
            after, wait_s = 0, 0.0
        notices = await agent.wait_notices(after, timeout_s=wait_s)
        return web.json_response({"ok": True, "supported": True, "notices": notices, "epoch": epoch, "last_seq": agent.last_notice_seq})

    async def agent_send(self, request: web.Request) -> web.Response:
        payload = await request.json()
        text = str(payload.get("text") or "") if isinstance(payload, dict) else ""
        if not text.strip():
            raise web.HTTPBadRequest(text="message cannot be empty")
        try:
            settings = self._settings()
            behavior_active = bool(agent_behavior.prompt_instruction(settings))
            from jarvis.runtime.prompt_overrides import prompt_override_document
            from jarvis.runtime.prompt_runtime import compose_agent_turn
            prompt, evidence = compose_agent_turn(
                agent_id=self._agent_id, model=self.agent.model or None,
                request_text=text.strip() if behavior_active else text,
                overrides=prompt_override_document(settings), behavior_active=behavior_active,
            )
            from jarvis.runtime.prompt_runtime import accepts_keyword_argument, accepts_prompt_evidence
            send_kwargs: dict[str, object] = {}
            if evidence is not None and accepts_prompt_evidence(self.agent.send):
                send_kwargs["prompt_evidence"] = evidence
            if evidence is not None and accepts_keyword_argument(self.agent.send, "input_text"):
                # Keep saved/runtime instructions in memory; only the user's
                # canonical message is allowed into trace and snapshots.
                send_kwargs["input_text"] = text.strip()
            return web.json_response(await self.agent.send(prompt, **send_kwargs))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        except RuntimeError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc

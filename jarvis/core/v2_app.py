from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping
import dataclasses
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import jarvis
from jarvis.adapters.fake_calendar import InMemoryCalendarBackend
from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_conversation_events import SQLiteConversationEventStore
from jarvis.adapters.sqlite_mcp_plugins import SQLiteMcpPluginRepository
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.adapters.sqlite_session_context import SQLiteContextRepository
from jarvis.adapters.context_workspace import FileContextWorkspaces
from jarvis.adapters.board_memory_store import FileBoardMemoryStore
from jarvis.adapters.file_prefab_library import FilePrefabLibrary, FilePrefabRuntime
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.adapters.sqlite_board_artifact_links import SQLiteBoardArtifactLinks
from jarvis.adapters.artifact_payloads import FileArtifactPayloads
from jarvis.adapters.sqlite_artifacts import SQLiteArtifactRepository
from jarvis.adapters.sqlite_session_activity import SQLiteActivityLedger
from jarvis.adapters.sqlite_captures import SQLiteCaptureRepository
from jarvis.core.artifact_service import ArtifactService
from jarvis.core.capture_service import CaptureAssociation, CaptureService, NoCaptureSources
from jarvis.core.recording_transcriber import RecordingTranscriber
from jarvis.core.capture_api import CaptureApi
from jarvis.core.workspace_service import WorkspaceService
from jarvis.core.context_catchup import build_catchup
from jarvis.core.context_enrichment import ContextEnrichmentWorker
from jarvis.adapters.windows_notifications import NullNotificationDelivery
from jarvis.core.brain_context import ATTENTION_QUEUE_SIZE, DEFAULT_WAKE_INTERVAL_S, BrainContextBuilder, WorkAttentionPolicy
from jarvis.core.board_attribution import BoardAttributingSink
from jarvis.core.board_service import BoardService
from jarvis.core.brain_service import (
    BRAIN_NOTICE_DROPPED_KIND, BRAIN_NOTICE_POLL_FAILED_KIND, DEFAULT_TURN_BUDGET_S, BrainOrchestrator,
)
from jarvis.core.agenda_reminders import DEFAULT_TICK_S as DEFAULT_AGENDA_TICK_S, AgendaReminderService, events_from_outcome
from jarvis.core.calendar_service import CalendarService
from jarvis.domain.agenda_reminders import AgendaEvent, AgendaSettings
from jarvis.core.conversation_event_emitter import ConversationEventEmitter
from jarvis.core.conversation_event_query import ConversationEventQueryService
from jarvis.core.prefab_witness import ConversationUtteranceWitness
from jarvis.core.credential_vault import CredentialVault
from jarvis.core.drive_service import DriveService
from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.mcp_plugin_service import McpPluginService
from jarvis.core.prefab_events import PrefabEventService
from jarvis.core.prefab_service import PrefabService
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.core.presentation_working_set import PresentationWorkingSetStore
from jarvis.core.scene_capture import SceneCaptureBroker
from jarvis.core.scene_file_watcher import SceneFileWatcher
from jarvis.core.scene_projector import RESTART_GRACE_S, SceneProjector
from jarvis.core.scene_service import SceneService
from jarvis.core.session_manager import SessionManager
from jarvis.core.speech_authority import SpeechAuthority
from jarvis.core.v2_services import (
    ConversationService, CoreEventBus, JobService, NotificationService, NullDiagnosticSink, SchedulerService,
)
from jarvis.core.v2_tools import CoreToolRouter
from jarvis.core.work_state import WorkStateStore
from jarvis.core.voice_ledger import VoiceLedgerService
from jarvis.core.live_lifecycle import LiveLifecycleService
from jarvis.core.live_reaper import LiveLifecycleWatchdog
from jarvis.domain.brain_context import BrainPrefabEvent
from jarvis.domain.brain_notice import NOTICE_TYPING_FIELDS
from jarvis.domain.v2 import Device, Job, MissedRunPolicy, Notification, NotificationPriority, ProtocolEnvelope, ScheduledItem, ScheduledStatus, utc_now
from jarvis.domain.capture import CaptureChannel
from jarvis.ports.capture import CaptureRepair, CaptureSourceRegistry
from jarvis.ports.transcription import TranscriptionBackend
from jarvis.ports.context_enrichment import ContextEnrichmentModel
from jarvis.ports.mcp_plugins import RemoteMcpConnector, Sealer
from jarvis.ports.scene import SceneCaptureStore, SceneRepository
from jarvis.ports.v2 import DiagnosticSink


@dataclass(slots=True)
class CoreHealth:
    ready: bool = False
    status: str = "starting"
    detail: str = ""


class JarvisCoreApplication:
    """Long-lived provider-neutral v0.2 application container.

    Concrete adapters are injected. Defaults are deterministic/local so Core can
    start headlessly with no microphone, Realtime provider, Calendar credentials
    or Windows UI dependency.
    """

    def __init__(self, *, data_root: Path, timezone: str = "Europe/Paris", calendar_backend=None, drive_backend=None, brain_backend=None, notification_delivery=None, workers=None, diagnostics: DiagnosticSink | None = None, supersede_stale_replies: bool = False, brain_turn_budget_s: float = DEFAULT_TURN_BUDGET_S, live_sideband_closer=None, live_provider_max_session_s: float | None = None, work_attention_wake_interval_s: float = DEFAULT_WAKE_INTERVAL_S, scene_repository: SceneRepository | None = None, scene_restart_grace_s: float = RESTART_GRACE_S, scene_capture_store: SceneCaptureStore | None = None, sealer: Sealer | None = None, connector: RemoteMcpConnector | None = None, mcp_allow_loopback_http: bool = False, capture_sources: CaptureSourceRegistry | None = None, capture_repairs: Mapping[CaptureChannel, CaptureRepair] | None = None, recording_transcription: Callable[[], TranscriptionBackend | None] | None = None, context_enrichment: Callable[[], ContextEnrichmentModel | None] | None = None, context_enrichment_enabled: bool = True, file_change_notifier_factory=None, agenda_settings: Callable[[], AgendaSettings] | None = None, agenda_tick_s: float = DEFAULT_AGENDA_TICK_S, agenda_clock: Callable[[], datetime] | None = None) -> None:
        root = Path(data_root).resolve()
        # Slice 07 (board-session) : tout diagnostic qui nomme une conversation
        # liée porte son `board_id` (alertes d'arrière-plan attribuées). Le
        # résolveur est branché dès que `SessionManager` existe, plus bas.
        attributing = BoardAttributingSink(diagnostics) if diagnostics is not None else None
        diagnostics = attributing
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self.health = CoreHealth()
        self.state = SQLiteStateRepository(root / "state" / "jarvis.sqlite3")
        self.history = JsonlHistoryStore(root / "history")
        # Conversation Event log (handoff conversation-observability, Slice 02):
        # same state DB, connection and lifecycle as `self.state` (schema v2).
        # Core owns it. Slice 03a: Core producers (voice admission, brain,
        # outcomes) enqueue through one bounded non-blocking emitter, and
        # `POST /v1/conversation-events` appends batches from other processes.
        self.conversation_events = SQLiteConversationEventStore(self.state, diagnostics=diagnostics)
        self.conversation_event_emitter = ConversationEventEmitter(self.conversation_events, diagnostics=diagnostics)
        # Slice 04: read side for the authenticated `GET /v1/conversation-events...` routes.
        self.conversation_event_queries = ConversationEventQueryService(self.conversation_events,
                                                                        diagnostics=diagnostics)
        self.events = CoreEventBus(diagnostics=diagnostics)
        # Mode d'interaction (handoff jarvis-presentation-interaction-mode,
        # Slice 02) : Core possède la valeur effective vivante et sa révision.
        # Le service reste en mémoire : un mode effectif est un fait de cette
        # vie du processus. La préférence enregistrée vit sur le Board actif
        # (handoff board-session, Slice 02, `self.boards` ci-dessous) ; le
        # rejeu global du Control Center n'est plus qu'une entrée de
        # migration. Décision D15 : il
        # n'entre **pas** dans `VoiceComposition.configuration_id`, donc un
        # passage SIMPLE ⇄ PRESENTATION ne redémarre jamais Voice ; le
        # changement voyage par `interaction.mode.changed` sur `/v1/events`.
        self.interaction_mode = InteractionModeService(events=self.events, diagnostics=diagnostics)
        # Mémoire de séance PRESENTATION (Slice 04) : sujets, faits avec leur
        # provenance, ressources préparées, et un fil de parole récente qui
        # reste frais même quand l'analyse ambiante est en retard (Décision
        # D06). En mémoire seulement, bornée, liée à une séance : ce n'est
        # **pas** de la mémoire à long terme et rien n'en est versé
        # automatiquement dans la mémoire canonique (Décision D13). Aucun
        # producteur n'est câblé ici : la Slice 06 écrira, les Slices 08 et 10
        # liront. Le seul câblage de cette Slice est le retrait : dès que le
        # mode effectif n'est plus PRESENTATION, la séance est vidée, et
        # l'abonné est synchrone pour que cela arrive au moment du changement.
        self.presentation_working_set = PresentationWorkingSetStore(diagnostics=diagnostics)
        self.interaction_mode.add_listener(self.presentation_working_set.apply_interaction_mode)
        # Boards de travail (handoff board-session, Slice 02) : même base,
        # même connexion que `self.state` (schéma v3). `start()` migre vers le
        # Board `default`, réapplique son mode, puis enregistre chaque
        # changement de mode sur le Board actif (`jarvis/core/board_service.py`).
        self.boards = BoardService(
            SQLiteBoardRepository(self.state), interaction_mode=self.interaction_mode, diagnostics=diagnostics,
        )
        # Plugins MCP distants (handoff generic-mcp-plugin-runtime, Slice 02) :
        # même base, même connexion que `self.state` (schéma v4). Registre et
        # blobs scellés dans un seul adaptateur ; le `sealer` (DPAPI) et le
        # `connector` (Slice 03) sont injectés par `app.py:_run_core_v2`. Sans
        # sealer, aucun identifiant n'est accepté (`mcp_vault_unavailable`) ;
        # sans connecteur, `connect` répond `mcp_connector_unavailable`.
        mcp_store = SQLiteMcpPluginRepository(self.state)
        self.mcp_plugins = McpPluginService(
            mcp_store, CredentialVault(mcp_store, sealer, diagnostics=diagnostics), connector=connector,
            diagnostics=diagnostics, allow_loopback_http=mcp_allow_loopback_http,
        )
        self.conversations = ConversationService(self.state, self.history)
        # Autorité de parole (handoff board-session, Slice 04b) : la liaison
        # foreground de la Session ouverte, seule conversation qui parle. Son
        # verrou sérialise bascules de Board et nouvelles Sessions ; la porte
        # de `BrainOrchestrator` la lit à chaque parole.
        self.speech_authority = SpeechAuthority()
        # Hôte des cerveaux de Board : capacité optionnelle du backend
        # (`ControlCenterBrainBackend.board_host`), découverte comme
        # `next_notices`. Absent : les transitions n'activent aucun CLI.
        # Seul un `activate` coroutine est retenu : un double de test générique
        # (`MagicMock`) ne devient pas un hôte par accident.
        host = getattr(brain_backend, "board_host", None)
        self.board_host = host if inspect.iscoroutinefunction(getattr(host, "activate", None)) else None
        # Sessions Jarvis (handoff board-session, Slice 03) : liaison foreground
        # du Board actif = conversation de vérité de Voice
        # (`GET /v1/sessions/current`). Handoff session-context-recording,
        # Slice 03 : le démarrage **reprend** la Session ouverte (D02), et
        # chaque Session a un Context actif dont le dossier vit sous
        # `<data_root>/sessions/` (même base v5, même connexion). Handoff
        # board-memory-workspace-inspector, Slice 03 : le bloc `board` de chaque
        # tour porte la mémoire du Board, lue bornée sous `<data_root>/boards/`.
        self.sessions = SessionManager(
            SQLiteBoardRepository(self.state), boards=self.boards, conversations=self.conversations,
            diagnostics=diagnostics, authority=self.speech_authority, host=self.board_host, events=self.events,
            contexts=SQLiteContextRepository(self.state), workspaces=FileContextWorkspaces(root),
            board_memory=FileBoardMemoryStore(root), data_root=root,
        )
        # Registre d'Artifacts et ledger d'activité (handoff
        # session-context-recording, Slice 04) : même base v6, même connexion ;
        # payloads sous `<data_root>/artifacts/`. Les transitions de Session et
        # de Context écrivent leur activité par leurs propres transactions.
        self.artifacts = ArtifactService(
            SQLiteArtifactRepository(self.state), SQLiteActivityLedger(self.state), FileArtifactPayloads(root),
            diagnostics=diagnostics,
        )
        # Propriétaire des captures (handoff session-context-recording, Slice
        # 05, D-CAP) : seule vérité d'état ; même base v7, même connexion ;
        # association prise au Context actif du démarrage. Aucune source réelle
        # installée ici (Slices 06/07) : `NoCaptureSources` refuse
        # (`unsupported_source`). Il note chaque changement de Context.
        self.captures = CaptureService(
            SQLiteCaptureRepository(self.state), self.artifacts, capture_sources or NoCaptureSources(),
            association=self._capture_association, repairs=capture_repairs, diagnostics=diagnostics,
        )
        self.sessions.add_association_listener(self.captures.association_changed)
        # Transcription des enregistrements audio explicites depuis leur spool
        # durable (Slice 06, D-AUDIO). `recording_transcription` rend le
        # fournisseur du moment (relu à chaque essai) ou `None` : la
        # transcription est alors `unavailable` et relançable, l'enregistrement
        # n'en dépend jamais.
        self.transcripts = RecordingTranscriber(
            self.artifacts, self.captures.get, recording_transcription or (lambda: None), diagnostics=diagnostics)
        self.captures.add_started_listener(self.transcripts.on_capture_started)
        self.captures.add_stopped_listener(self.transcripts.on_capture_stopped)
        # Mémoire vivante du Context actif (Slice 08) : worker de Core, hors du
        # cerveau et des modes, qui tient `summary.md` depuis le ledger.
        # `context_enrichment` rend le modèle sans outil du moment ou `None` :
        # le worker est alors `unavailable`, rien ne plante.
        self.context_enrichment = ContextEnrichmentWorker(
            self.sessions, self.artifacts, context_enrichment or (lambda: None), diagnostics=diagnostics,
            enabled=context_enrichment_enabled)
        self.sessions.add_association_listener(self.context_enrichment.on_association_changed)
        # Surface HTTP des Contexts, captures, Artifacts et transcriptions (Slice 09) :
        # façade sans état sur les propriétaires ci-dessus, servie par
        # `jarvis/protocol/capture_routes.py` (UI et `jarvis-capture` via le CC).
        self.capture_api = CaptureApi(sessions=self.sessions, artifacts=self.artifacts, captures=self.captures,
                                      transcripts=self.transcripts, enrichment=self.context_enrichment)
        # Inspection du workspace (handoff board-memory-workspace-inspector, Slice 04) :
        # lectures sans effet de bord sur les magasins canoniques (même base, même
        # connexion), servies par `jarvis/protocol/workspace_routes.py`.
        self.workspace = WorkspaceService(
            boards=SQLiteBoardRepository(self.state), contexts=SQLiteContextRepository(self.state),
            artifacts=self.artifacts, links=SQLiteBoardArtifactLinks(self.state), memory=FileBoardMemoryStore(root),
            authority=self.speech_authority, diagnostics=diagnostics)
        if attributing is not None:
            attributing.resolve = self.sessions.cached_board_of
        self.boards.configure_transitions(sessions=self.sessions, authority=self.speech_authority,
                                          host=self.board_host, events=self.events)
        self.voice_ledger = VoiceLedgerService(self.conversations, diagnostics=diagnostics)
        self.live_lifecycle = LiveLifecycleService(
            self.state, diagnostics=diagnostics, accepting_new=lambda: self.health.ready,
        )
        self.live_reaper = LiveLifecycleWatchdog(
            self.live_lifecycle, closer=live_sideband_closer, diagnostics=diagnostics,
            provider_max_session_seconds=live_provider_max_session_s,
        )
        self.scheduler = SchedulerService(self.state, self.events)
        # État de travail détaillé, possédé par Core (handoff work-state, tâche
        # 11) : alimenté par les jobs et par l'ingress `/v1/work/observations`,
        # en mémoire seulement (voir `jarvis/core/work_state.py`).
        self.work_state = WorkStateStore(events=self.events, diagnostics=diagnostics)
        self.jobs = JobService(self.state, self.events, workers or {}, diagnostics=diagnostics, work_state=self.work_state,
                               board_of=self.sessions.board_of)
        # Scène constellation (handoff jarvis-constellation-scene-runtime,
        # Slice 02) : durable, contrairement à l'état de travail, dans son
        # propre fichier (`scene.sqlite3`, schéma et cycle de vie propres,
        # indépendants de `jarvis.sqlite3`). Un fichier
        # de scène refusé rend la scène indisponible, jamais Core. Hors du bus
        # à dessein : `/v1/events` relaie tout le bus à Voice (voir
        # `jarvis/core/scene_service.py`). `scene_repository` : injection de
        # test uniquement.
        # Prefabs de fenêtre (handoff jarvis-scene-window-prefab-foundation,
        # Slice 02) : catalogue = bases livrées dans le paquet
        # (`jarvis/prefabs/base/`, jamais écrit) + bibliothèque de cette
        # installation (`<data_root>/prefabs/`). Core est seule autorité de
        # validation. Construit avant la scène : Slice 04, il valide chaque
        # bloc `prefab` neuf ou changé (`SceneService.prefab_validator`). Slice
        # 07 : le témoin de la porte d'édition de base cherche la demande citée
        # dans les tours de l'utilisateur des 30 dernières minutes
        # (`ConversationUtteranceWitness`, Conversation Events).
        # Slice 03 : le runtime des cadres (`jarvis/prefabs/runtime/`) part avec chaque paquet de version.
        prefab_package = Path(jarvis.__file__).resolve().parent / "prefabs"
        self.prefabs = PrefabService(
            FilePrefabLibrary(prefab_package / "base", root),
            user_utterance_witness=ConversationUtteranceWitness(self.conversation_event_queries,
                                                                diagnostics=diagnostics),
            diagnostics=diagnostics,
            runtime=FilePrefabRuntime(prefab_package / "runtime"),
        )
        # Presentations du Studio (handoff jarvis-interactive-presentation-studio, Slice 02) : magasin de fichiers
        # `<data_root>/presentations/` (jamais SQLite : pas de migration, `docs/presentation-studio.md`), Core seul
        # écrivain. Indépendant de la scène : un état d'exécution (fenêtre, lecture) n'y entre jamais.
        self.presentation_studio = PresentationStudioService(FilePresentationStudioStore(root), diagnostics=diagnostics)
        self.scene = SceneService(
            scene_repository or SQLiteSceneRepository(root / "state" / "scene.sqlite3"),
            diagnostics=diagnostics,
            prefab_validator=self.prefabs,
        )
        # Événements des cadres (Slice 04) : `state` écrit `prefab.data` par le
        # réducteur (acteur `user`, `basis` contrôlée sous le verrou de la
        # scène), `notify` est consigné ; aucun n'exécute d'outil.
        self.prefab_events = PrefabEventService(self.scene, self.prefabs, diagnostics=diagnostics)
        # Projection runtime (Slice 04) : chaque sous-agent et chaque job
        # deviennent des étoiles sans tour du cerveau. Seul écrivain `runtime`
        # de la scène ; abonné tolérant de `core.work.updated`, il se
        # réconcilie depuis l'instantané de travail. Démarré après la scène,
        # arrêté avant sa fermeture. Slice 10 : au démarrage, il marque
        # « état inconnu » les étoiles d'une vie précédente, relit l'issue
        # persistée des jobs terminés, et interrompt après
        # `scene_restart_grace_s` celles qu'aucun producteur n'a redites.
        # Slice 09 (partie 2) : captures visuelles exceptionnelles, rendues par la
        # page meneuse visible du Control Center. Sans magasin injecté (tests,
        # outils), la route répond `capture_unavailable`.
        self.scene_captures = SceneCaptureBroker(scene_capture_store, diagnostics=diagnostics)
        self.scene_projector = SceneProjector(
            work=self.work_state, scene=self.scene, events=self.events, diagnostics=diagnostics,
            restart_grace_s=scene_restart_grace_s, job_outcomes=self.jobs.observe_persisted_outcomes,
        )
        # Fenêtres liées à un fichier (`ScenePayload.source_path`) : le résumé
        # suit le fichier, sans tour du cerveau.
        self.scene_file_watcher = SceneFileWatcher(self.scene, diagnostics=diagnostics, notifier_factory=file_change_notifier_factory)
        # Tâche 12 : le cerveau lit ce même magasin à chaque tour, et une
        # politique abonnée à `core.work.updated` retient pour lui les échecs,
        # interruptions et blocages (voir `jarvis/core/brain_context.py`).
        #
        # Le réveil est câblé. Sans lui, la politique n'était qu'un tampon :
        # un sous-agent pouvait mourir sans un mot, et l'utilisateur ne
        # l'apprenait qu'en reparlant de lui-même — donc jamais s'il se taisait.
        # Le rappel arrive par une fermeture, car `self.brain` n'existe que
        # plus bas ; il ne dit rien lui-même, il ouvre un tour et laisse le
        # cerveau choisir ses mots.
        # Slice 04b : portée par Board — seul le Board qui a la parole voit son
        # travail (plus le travail non attribué) et peut être réveillé.
        self.work_attention = WorkAttentionPolicy(
            diagnostics=diagnostics,
            wake=self._wake_brain_for_work,
            wake_interval_s=work_attention_wake_interval_s,
            active_board=lambda: self.speech_authority.board_id,
        )
        self.brain_context = BrainContextBuilder(
            reader=self.work_state,
            store_id=self.work_state.store_id,
            attention=self.work_attention,
            diagnostics=diagnostics,
            active_board=lambda: self.speech_authority.board_id,
        )
        self.notifications =NotificationService(self.state, notification_delivery or NullNotificationDelivery())
        self.calendar = CalendarService(calendar_backend or InMemoryCalendarBackend())
        # Pas de repli en mémoire pour Drive : un faux Drive donnerait à
        # l'utilisateur la certitude d'avoir déposé un fichier qui n'existe pas.
        self.drive = DriveService(drive_backend)
        # Le cerveau autoritaire vit dans Core (Décision 01). Le backend fort est
        # injecté depuis l'extérieur (Décision 28) : à défaut, l'objet nul défini
        # dans `brain_service` garde un démarrage headless possible sans jamais
        # faire croire qu'un tour a été traité.
        # `jobs` est la couture d'annulation (`WorkCanceller`) : une décision
        # explicite du cerveau doit arrêter le job qu'elle vise, sinon
        # l'annulation ne serait qu'une écriture d'état.
        self.brain = BrainOrchestrator(
            conversations=self.conversations,
            events=self.events,
            backend=brain_backend,
            jobs=self.jobs,
            diagnostics=diagnostics,
            supersede_stale_replies=supersede_stale_replies,
            turn_budget_s=brain_turn_budget_s,
            work_context=self.brain_context,
            voice_ledger=self.voice_ledger,
            conversation_events=self.conversation_event_emitter,
            speech_authority=self.speech_authority,
            board_of=self.sessions.board_of,
            board_context=self.sessions.board_context,
            session_context=self._session_context,
            prefab_events=self._take_prefab_events,
            prefab_events_requeue=self.prefab_events.requeue_notify,
        )
        self.outcomes = self.brain.outcomes
        self.voice_admission = self.brain.admission
        from jarvis.core.back_brain import BackBrainTaskService
        self.back_brain = BackBrainTaskService(self.jobs, self.conversations, self.voice_ledger)
        self.tools = CoreToolRouter(scheduler=self.scheduler, calendar=self.calendar, drive=self.drive, timezone=timezone)
        self._stopped = asyncio.Event()
        self._notification_task: asyncio.Task[None] | None = None
        self._notification_queue: asyncio.Queue[ProtocolEnvelope] | None = None
        # Relais spontanés du cerveau (fin d'un sous-agent) : capacité
        # optionnelle du backend, détectée structurellement comme les autres.
        self._brain_notices = getattr(brain_backend, "next_notices", None)
        # Mode d'interaction remis au backend cerveau (Slice 07) : le modèle
        # doit savoir qu'il présente, sinon il rédige des phrases que la porte
        # de parole du processus Voice jettera. Capacité optionnelle, détectée
        # comme `next_notices` ci-dessus ; l'abonné est synchrone, comme celui
        # de la mémoire de séance, pour que le tour suivant porte déjà la
        # bonne valeur.
        # Journal de diagnostic remis au backend (capacité optionnelle) : ce que
        # l'adaptateur retire de la réponse de l'agent doit se voir (Slice 04).
        attach_diagnostics = getattr(brain_backend, "attach_diagnostics", None)
        if callable(attach_diagnostics) and diagnostics is not None:
            attach_diagnostics(diagnostics)
        observe_mode = getattr(brain_backend, "observe_interaction_mode", None)
        if callable(observe_mode):
            self.interaction_mode.add_listener(observe_mode)
        # Rappels d'agenda proactifs : absents sans lecteur de réglages (tests, Core sans Control Center).
        self.agenda_reminders: AgendaReminderService | None = None
        if agenda_settings is not None:
            from zoneinfo import ZoneInfo
            self.agenda_reminders = AgendaReminderService(
                settings=agenda_settings, fetch=self._fetch_agenda, wake=self.brain.wake_for_agenda,
                memory_path=root / "agenda_reminders.json", zone=ZoneInfo(timezone), diagnostics=diagnostics or NullDiagnosticSink(),
                user_turn_at=lambda: self.brain.last_user_turn_at,
                **({"clock": agenda_clock} if agenda_clock is not None else {}), tick_s=agenda_tick_s)
        self._brain_notice_task: asyncio.Task[None] | None = None
        self._host_align_task: asyncio.Task[bool] | None = None
        self._work_attention_task: asyncio.Task[None] | None = None
        self._work_attention_queue: asyncio.Queue[ProtocolEnvelope] | None = None

    async def start(self) -> None:
        if self.health.ready:
            return
        try:
            await self.state.initialize()
            # Before any route or task can admit a turn: repair user events a
            # crash lost between the durable turn and the emitter commit.
            # Needs only `state` (same DB); never raises.
            await self.voice_admission.backfill_user_turns_accepted(self.conversation_events)
            # Avant toute route : Board `default` garanti (migration idempotente),
            # puis Session **reprise** (la restée ouverte, même conversation ;
            # sinon une neuve sur le dernier Board actif — la toute première
            # Session de la base adopte la conversation la plus récente) et son
            # Context actif garanti, puis mode de ce Board
            # réappliqué (`board_restore`) et abonnement au mode. Le serveur ne
            # démarre qu'après `start()` : aucune route ne voit Core sans
            # Session. Lève seulement si la base refuse.
            await self.boards.ensure_default()
            await self.sessions.start()
            # Captures restées ouvertes d'une vie précédente (Core mort avec
            # l'arbre) : réparation de famille puis `partial`/`failed`,
            # `capture.gap`, jamais relancées (Slice 05). **Avant** la reprise
            # générique : la réparation (en-tête WAV) doit précéder la
            # promotion du `.partial`. Ne lève pas.
            recovered = await self.captures.recover()
            # Transcriptions d'enregistrements reprises depuis leur curseur
            # (Slice 06) : leurs projections `pending` ont un propriétaire
            # vivant, la reprise générique les laisse. Les dernières captures
            # arrêtées par l'arrêt normal de Core (qui ne notifie pas) et
            # restées sans projection sont rattrapées. Ne lève pas.
            await self.transcripts.recover(recovered.partial + recovered.complete, recent=self.captures.recent)
            # Artifacts restés `pending` d'une vie précédente -> `partial` ou
            # `failed`, avant tout écrivain (Slice 04). Ne lève pas.
            await self.artifacts.recover_pending(owned=self.transcripts.owns)
            # Après les reprises : le worker reprend depuis le curseur de chaque Context.
            self.context_enrichment.start()
            await self.boards.start(ensure_default=False)
            # Plugins MCP : `connecting` laissé par un arrêt brutal remis à
            # `disconnected` avant toute route. Ne lève pas (registre illisible :
            # journalisé, chaque route le rendra 500).
            await self.mcp_plugins.start()
            # Ne lève pas : un refus est journalisé et la scène reste
            # indisponible pendant que le reste de Core démarre. Fichier
            # distinct de `state` : indépendante du rattrapage ci-dessus.
            await self.scene.start()
            # Balayage des publications interrompues puis chargement du
            # catalogue des prefabs. Ne lève pas (catalogue illisible :
            # journalisé, chaque demande relit).
            await self.prefabs.start()
            # Restes d'écritures interrompues des Presentations balayés. Ne lève pas.
            await self.presentation_studio.start()
            # Rétention des captures (5 fichiers, 24 h). Ne lève pas.
            await self.scene_captures.start()
            # Slice 10, avant toute écriture de la projection et toute route :
            # les étoiles non terminées d'une vie précédente passent à
            # `unknown`, la grâce est armée. Ne lève pas (scène indisponible :
            # la boucle reprend le marquage).
            await self.scene_projector.reconcile_restart()
            # Après la scène (même indisponible : la projection attend et le
            # journalise), avant `jobs.recover()` dont les interruptions
            # doivent atteindre la scène.
            self.scene_projector.start()
            self.scene_file_watcher.start()
            self.live_reaper.start()
            await self.state.save_device(Device())
            # Subscribe before recovery: overdue schedules and interrupted jobs
            # may emit events immediately during startup.
            self._notification_queue = self.events.subscribe()
            self._notification_task = asyncio.create_task(self._notification_loop(self._notification_queue), name="jarvis-v2-notifications")
            # Abonné tolérant : une éviction éteindrait l'attention pour la vie
            # du processus (rien ne se réabonne), alors qu'une rafale coûte au
            # pire une note — le statut du travail, lui, reste dans l'instantané.
            self._work_attention_queue = self.events.subscribe(max_queue=ATTENTION_QUEUE_SIZE, lossy=True)
            self._work_attention_task = asyncio.create_task(self.work_attention.run(self._work_attention_queue), name="jarvis-work-attention")
            await self.notifications.recover()
            await self.jobs.recover()
            await self._ensure_system_schedules()
            await self.scheduler.start()
            if self.agenda_reminders is not None:
                self.agenda_reminders.start()
            if callable(self._brain_notices):
                self._brain_notice_task = asyncio.create_task(self._brain_notice_loop(self._brain_notices), name="jarvis-brain-notices")
            if self.board_host is not None:
                # Slice 04b : le Control Center met au premier plan la liaison de
                # la Session neuve (CLI neuf). En tâche de fond, ne lève pas : un
                # Control Center absent se réalignera seul (`/v1/sessions/current`).
                self._host_align_task = asyncio.create_task(self.boards.align_host(), name="jarvis-board-host-align")
            self.health.ready = True
            self.health.status = "ok"
            self.health.detail = ""
        except Exception as exc:
            self.health.ready = False
            self.health.status = "fail"
            self.health.detail = f"{type(exc).__name__}: {exc}"
            await self.context_enrichment.close()
            await self.live_reaper.stop()
            await self._stop_notification_loop()
            await self._stop_work_attention()
            await self._stop_scene()
            try:
                await self.state.close()
            except Exception:
                pass
            raise

    def _take_prefab_events(self) -> tuple[BrainPrefabEvent, ...]:
        """Bloc `prefab_events` du tour (Slice 07 prefabs, D-EVENTS) : `notify` pas encore remis, marqués remis."""

        return tuple(BrainPrefabEvent(seq=entry.seq, at=entry.at, object_id=entry.object_id, prefab=entry.prefab,
                                      event=entry.event, payload=entry.payload_preview())
                     for entry in self.prefab_events.take_undelivered_notify())

    async def _session_context(self, conversation_id: str | None):
        """Bloc `session_context` du tour, complété du rattrapage du Context actif (Slice 08).

        Un registre illisible n'empêche pas le tour : le bloc part sans
        rattrapage, et l'échec est journalisé (`core.context.catchup_failed`).
        """

        block = await self.sessions.session_context(conversation_id)
        if block is None or block.workspace_error is not None:
            return block
        try:
            catchup = await build_catchup(self.artifacts, block.jarvis_session_id, block.context_id,
                                          self._live_capture_ids())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: logged, the turn leaves with the summary only
            self._diagnostics.emit("core.context.catchup_failed",
                                   f"Rattrapage du Context non assemblé : {type(exc).__name__}: {str(exc)[:200]}",
                                   level="error", data={"context_id": block.context_id,
                                                        "exception_type": type(exc).__name__})
            return block
        return dataclasses.replace(block, activity=catchup.activity, latest_seq=catchup.latest_seq,
                                   transcript_tail=catchup.transcript_tail, transcript_ref=catchup.transcript_ref,
                                   artifact_refs=catchup.artifact_refs)

    def _live_capture_ids(self) -> frozenset[str]:
        """Ids des captures **en cours** et de leurs Artifacts : seule leur parole entre au rattrapage."""

        return frozenset(value for record in self.captures.status().captures
                         for value in (record.capture_id, record.artifact_id) if value)

    async def _capture_association(self) -> CaptureAssociation:
        """Session et Context actifs au démarrage d'une capture (D-CAP, `docs/capture.md`)."""

        view = await self.sessions.current_context()
        return CaptureAssociation(view.context.jarvis_session_id, view.context.context_id)

    async def _wake_brain_for_work(self, notes) -> None:
        """Rappel de `WorkAttentionPolicy` : ouvrir un tour sur un changement de fond.

        Rien n'est dit ici, et rien n'est consommé : le cerveau décide s'il
        parle, et seuls les changements qu'un contexte de tour a vraiment
        portés sont retirés de l'attente (`take_delivered`). Une exception est
        déjà absorbée et signalée par la politique appelante
        (`core.work.attention_wake_failed`) ; le changement attend alors le
        tour suivant plutôt que d'éteindre la boucle.
        """

        await self.brain.wake_for_work_attention(tuple(notes))

    async def _fetch_agenda(self, start: datetime, end: datetime) -> list[AgendaEvent]:
        """Relire l'agenda par l'outil calendrier du plugin connecté (lecture seule).

        Aucun nom de plugin n'est figé : le premier outil `*calendar.list_events`
        d'un plugin actif et connecté. Aucun plugin calendrier = erreur claire,
        tracée une fois par la boucle (`core.agenda.fetch_failed`).
        """

        catalog = await self.mcp_plugins.external_tools()
        tool = next((item for item in catalog.get("tools", ()) if str(item.get("name", "")).endswith("calendar.list_events")), None)
        if tool is None:
            raise RuntimeError("aucun plugin connecté ne fournit calendar.list_events")
        outcome = await self.mcp_plugins.call(tool["tool_id"], {"start": start.isoformat(), "end": end.isoformat(), "limit": 200},
                                              caller={"agent": "core-agenda"})
        return events_from_outcome(outcome)

    async def _ensure_system_schedules(self) -> None:
        if "memory_maintenance" not in self.jobs.workers:
            return
        existing = await self.state.list_scheduled_items()
        if any(item.idempotency_key == "system:memory-maintenance-daily" and item.status is not ScheduledStatus.CANCELLED for item in existing):
            return
        item = ScheduledItem(
            kind="job",
            payload={"job_kind": "memory_maintenance", "payload": {}},
            next_fire_at=utc_now() + timedelta(days=1),
            recurrence_seconds=24 * 60 * 60,
            missed_run_policy=MissedRunPolicy.SKIP,
            idempotency_key="system:memory-maintenance-daily",
        )
        await self.scheduler.create(item)

    async def _notification_loop(self, queue: asyncio.Queue[ProtocolEnvelope]) -> None:
        try:
            while True:
                event = await queue.get()
                if event.message_type not in {"schedule.triggered", "schedule.triggered_late", "job.completed", "job.failed", "job.interrupted"}:
                    continue
                reference = str(event.payload.get("scheduled_item_id") or event.payload.get("job_id") or event.correlation_id)
                if event.message_type.startswith("schedule."):
                    payload = event.payload.get("payload") if isinstance(event.payload.get("payload"), dict) else {}
                    if event.payload.get("kind") == "job":
                        job_kind = str(payload.get("job_kind") or "").strip()
                        job_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
                        scheduled_for = str(event.payload.get("scheduled_for") or "unknown")
                        try:
                            await self.jobs.submit(Job(kind=job_kind, payload=job_payload, requested_by_conversation_id=event.conversation_id, idempotency_key=f"schedule:{reference}:{scheduled_for}"))
                        except Exception as exc:
                            notification = Notification(summary="Tâche planifiée Jarvis en échec", body=f"Impossible de lancer {job_kind or 'la tâche'} ({type(exc).__name__}).", priority=NotificationPriority.HIGH, originating_reference_id=reference, idempotency_key=f"schedule-dispatch-failed:{reference}:{scheduled_for}")
                            try:
                                await self.notifications.create(notification, deliver=True)
                            except Exception:
                                pass
                        continue
                    summary = "Rappel Jarvis"
                    body = str(payload.get("message") or "Un rappel est arrivé à échéance.")
                elif event.message_type == "job.completed":
                    summary, body = "Tâche Jarvis terminée", f"La tâche {event.payload.get('kind', '')} est terminée."
                else:
                    summary, body = "Tâche Jarvis à vérifier", f"État: {event.message_type}."
                notification = Notification(summary=summary, body=body, priority=NotificationPriority.NORMAL, originating_reference_id=reference, idempotency_key=f"event:{event.message_type}:{reference}")
                try:
                    await self.notifications.create(notification, deliver=True)
                except Exception:
                    # Notification state is persisted as FAILED by the service;
                    # the Core event loop must stay alive if the OS channel fails.
                    continue
        finally:
            self.events.unsubscribe(queue)

    async def _brain_notice_loop(self, next_notices) -> None:
        """Faire dire, dès qu'ils arrivent, les relais que le cerveau rédige seul.

        `next_notices()` attend (longuement) et ne lève pas en temps normal ;
        une exception inattendue est absorbée avec une pause, pour que la
        boucle survive à un backend fautif sans tourner à vide.

        Chaque relais est une notice typée (mapping `text`, `kind`,
        `supersedes_key`, `ttl_s`, `work_id` : `jarvis/domain/brain_notice.py`)
        transmise telle quelle à `announce_notice`, qui valide le genre et
        refuse en le traçant ce qui sort du contrat. Un backend qui rend encore
        de simples textes (ancien format) produit des `result` : compatibilité,
        `docs/legacy/untyped-brain-notices.md`.

        Aucune panne ne tue la boucle en silence : une lecture en échec est
        tracée (`core.brain.notice_poll_failed`) puis retentée ; un relais dont
        l'annonce lève est tracé (`core.brain.notice_dropped`,
        `reason=announce_failed`) et les suivants passent.
        """
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            try:
                notices = await next_notices()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the loop must outlive a faulty backend; captured, then retried
                self._diagnostics.emit(BRAIN_NOTICE_POLL_FAILED_KIND, "lecture des relais spontanés en échec : nouvel essai dans 5 s",
                                       level="error", data={"code": "notice_poll_failed", "exception_type": type(exc).__name__,
                                                            "error": str(exc)[:300]})
                await asyncio.sleep(5.0)
                continue
            for notice in notices or ():
                await self._announce_one_notice(notice)
            if not notices and loop.time() - started < 0.05:
                # Un backend qui rend la main aussitôt ne doit pas monopoliser la boucle.
                await asyncio.sleep(1.0)

    async def _announce_one_notice(self, notice: object) -> None:
        """Un relais : l'annoncer, et tracer au lieu de propager une panne d'annonce.

        La conversation d'origine (reprise QA 04a, clé `conversation_id` du
        relais) est transmise : un relais d'un Board qui n'a plus la parole est
        retenu par la porte de parole. Absente : la conversation qui parle.
        """
        try:
            if isinstance(notice, Mapping):
                origin = notice.get("conversation_id")
                await self.brain.announce_notice(
                    str(notice.get("text") or ""),
                    **{name: notice.get(name) for name in NOTICE_TYPING_FIELDS},
                    conversation_id=origin if isinstance(origin, str) and origin else None)
            else:
                await self.brain.announce_notice(str(notice), conversation_id=getattr(notice, "conversation_id", None))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad relay must not kill the loop; captured with its cause
            self._diagnostics.emit(BRAIN_NOTICE_DROPPED_KIND, "relais du cerveau non annoncé : l'annonce a échoué",
                                   level="error", data={"reason": "announce_failed", "code": "announce_failed",
                                                        "exception_type": type(exc).__name__, "error": str(exc)[:300]})

    async def _stop_brain_notice_loop(self) -> None:
        task, self._brain_notice_task = self._brain_notice_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _stop_notification_loop(self) -> None:
        task, self._notification_task = self._notification_task, None
        queue, self._notification_queue = self._notification_queue, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if queue is not None:
            self.events.unsubscribe(queue)

    async def _stop_work_attention(self) -> None:
        task, self._work_attention_task = self._work_attention_task, None
        queue, self._work_attention_queue = self._work_attention_queue, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if queue is not None:
            self.events.unsubscribe(queue)
        await self.work_attention.stop()

    async def _stop_scene(self) -> None:
        """Arrêter la projection, puis fermer la scène : aucun écrivain ne survit à la fermeture.

        `scene_projector.stop()` annule aussi la minuterie de grâce de
        redémarrage (Slice 10) : aucune tâche ne lui survit.

        Le cerveau n'écrit pas la scène dans cette Slice ; le transport HTTP
        (Slice 03) est arrêté par son serveur avant `stop()`, et une commande
        encore en vol termine sa transaction (`close` attend le verrou).
        """

        await self.scene_file_watcher.stop()
        await self.scene_projector.stop()
        await self.scene.close()

    async def stop(self) -> None:
        if self.health.status == "stopped":
            return
        self.health.ready = False
        self.health.status = "stopping"
        # Une capture en attente échoue aussitôt (`capture_cancelled`).
        self.scene_captures.close()
        # Captures explicites arrêtées et finalisées avant toute fermeture
        # (`core_shutdown`), bornées par l'échéance d'arrêt des sources.
        await self.captures.close()
        # Transcriptions arrêtées où elles sont : curseur durable, reprises au démarrage.
        await self.transcripts.close()
        # Enrichissement arrêté entre deux tours : curseur durable, rejeu borné au démarrage.
        await self.context_enrichment.close()
        self.back_brain.stopping = True
        self.jobs.owned.stopping = True
        await self.live_reaper.stop()
        # Le cerveau s'arrête en premier : ses tâches écrivent en base via
        # ConversationService et publient sur le bus, deux ressources fermées plus bas.
        # Le relais spontané le précède : il alimente le cerveau.
        await self._stop_brain_notice_loop()
        if self.agenda_reminders is not None:
            await self.agenda_reminders.stop()
        align, self._host_align_task = self._host_align_task, None
        if align is not None and not align.done():
            align.cancel()
            await asyncio.gather(align, return_exceptions=True)
        # La politique d'état de travail aussi : un réveil pourrait nourrir le cerveau.
        await self._stop_work_attention()
        await self.brain.stop()
        await self._stop_notification_loop()
        await self.scheduler.stop()
        try:
            if not await self.back_brain.stop():
                self.health.status = "state_persistence_unknown"
                self.health.detail = "back brain submission remains owned while storage completes"
                return
            if not await self.jobs.stop():
                self.health.status = "state_persistence_unknown" if self.jobs.owned.persistence_failures else "cleanup_unknown"
                self.health.detail = "back brain finalization remains owned and unconfirmed"
                return
        finally:
            # Sur tous les chemins, retours anticipés et exceptions compris : la
            # projection (dernier écrivain runtime) s'arrête après les jobs,
            # pour que leurs fins atteignent la scène, et avant la fermeture.
            await self._stop_scene()
        # Juste avant la fermeture de la base, après les arrêts qui peuvent
        # rendre la main sur une persistance incertaine (la vidange ne doit pas
        # allonger ce chemin-là) : vidange bornée, le reste est compté et tracé.
        # Après la scène : fichier distinct, aucun des deux n'écrit dans l'autre.
        await self.conversation_event_emitter.stop()
        # Écritures de mode sur le Board encore en vol : finies avant la fermeture.
        await self.boards.stop()
        # Aucune écriture de plugin en vol à la fermeture ; connexions fermées ≤ 5 s (Slice 03).
        await self.mcp_plugins.stop()
        await self.state.close()
        self.health.status = "stopped"
        self._stopped.set()

    async def wait(self) -> None:
        await self._stopped.wait()

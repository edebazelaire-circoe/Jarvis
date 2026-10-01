from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from collections.abc import Callable
from typing import Any, NamedTuple
from urllib.parse import urlparse
import uuid

import aiohttp
from aiohttp import web

from jarvis.adapters.control_center_brain import REDIT_MARKER
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
from jarvis.domain.v2 import BRAIN_NOT_ADDRESSED_ANSWER, AddressingDecision, SpeechKind
from jarvis.runtime.audio_devices import AudioDiagnosticError, SoundDeviceAudioDiagnostics, normalize_device_id
from jarvis.runtime import (
    agent_behavior,
    agent_routing,
    barehands_test_mode as barehands,
    barehands_benchmark,
    barehands_profile,
    barehands_trace,
    cli_catalog,
    credentials as creds,
    shortcuts as shortcut_registry,
    voice_settings_schema,
    voice_stack,
)
from jarvis.runtime.background_events import (
    CATEGORIES as BACKGROUND_CATEGORIES,
    MAX_ENTRIES,
    MAX_READ_BYTES as MAX_TRACE_READ_BYTES,
    STORE_FILE as BACKGROUND_STORE_FILE,
    BackgroundEventStore,
    follow,
)
from jarvis.runtime.catalog_view import CatalogViewService, ProviderCatalogSnapshot, SUBAGENT_ROLES, VOICE_ROLES
from jarvis.runtime.claude_local import DEFAULT_PERMISSION_MODE, PERMISSION_MODES, ClaudeLocalAgent, normalize_permission_mode
from jarvis.runtime.codex_local import CodexLocalAgent, normalize_sandbox_mode
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.domain.interaction_mode import DEFAULT_INTERACTION_MODE, InteractionMode
from jarvis.runtime import interaction_mode_settings
from jarvis.runtime.interaction_mode_view import CoreInteractionModeView, InteractionModeUnavailable
from jarvis.runtime.live_status import CoreLiveStatusView, project_live_status
from jarvis.runtime import mcp_catalog
from jarvis.runtime.model_catalog import CatalogError, ModelCatalog, filter_by_role
from jarvis.runtime.owner_voice import effective_verifier_settings, probe_remedy
from jarvis.runtime.self_dev import SelfDevError, apply_gate as apply_self_dev_gate, load_gate as load_self_dev_gate
from jarvis.runtime.scene_settings import (
    SceneSettingsError,
    apply_gate as apply_scene_gate,
    describe_gate as describe_scene_gate,
    load_gate as load_scene_gate,
)
from jarvis.runtime.self_dev_service import SelfDevelopmentService
from jarvis.runtime.owner_voice import probe_from_settings as probe_owner_verifier
from jarvis.runtime.visual_signals import VisualSignalBus
from jarvis.runtime.board_brief import render_board_brief
from jarvis.runtime.session_context_brief import render_session_context_brief, sessions_root
from jarvis.runtime.work_brief import render_work_brief
from jarvis.runtime.subagent_conversation import SubagentConversationScope
from jarvis.runtime.conversation_event_forwarder import ConversationEventForwarder
from jarvis.domain.conversation_event_export import EXPORT_MEDIA_TYPE, export_filename
from jarvis.domain.conversation_event_query import (
    CONVERSATIONS_PARAMS, EVENTS_PARAMS, EXPORT_PARAMS, LOOKUP_PARAMS, SESSIONS_PARAMS, TRANSCRIPT_PARAMS,
    check_event_id, conversations_query, encode_event_page, encode_event_response, encode_summary_page, events_query,
    export_query, lookup_query, query_params, sessions_query, transcript_query,
)
from jarvis.domain.conversation_event_search import SEARCH_PARAMS, encode_search_page, search_query
from jarvis.runtime.conversation_event_trace import TraceNotApplicable, drill_down
from jarvis.runtime.conversation_event_view import ConversationEventView, ConversationEventViewError
from jarvis.runtime.work_ingress import TrackerWorkObserver, WorkIngressForwarder
from jarvis.runtime.board_brains import BoardBrain, BoardBrainPool, agent_session_id
from jarvis.runtime.board_routes import BoardSessionRoutes
from jarvis.runtime.core_sessions import CoreSessionTransport, is_unsupported
from jarvis.runtime.mcp_plugin_routes import PLUGINS_ROUTE as MCP_PLUGINS_ROUTE, McpPluginRoutes
from jarvis.domain.workspace_board import BoardConversationBinding, BoardError, BoardErrorCode, InteractionModeOrigin
from jarvis.runtime.work_view import CORE_UNREACHABLE, NOT_CONFIGURED, CoreWorkView, unavailable_payload
from jarvis.protocol import scene_wire
from jarvis.protocol.client import CoreProtocolError
from jarvis.domain.barehands_command import (
    BAD_RECEIPT,
    BAD_REQUEST,
    COMMAND_UNKNOWN,
    FORBIDDEN_ORIGIN,
    MAX_COMMAND_REQUEST_BYTES,
    MAX_POLL_WAIT_S,
    MAX_RECEIPT_BYTES,
    RECEIPT_INVALID,
    RECEIPT_TOO_LARGE,
    BarehandsCommandError,
    parse_command_receipt,
    parse_command_request,
)
from jarvis.domain.barehands_calibration import (
    CALIBRATION_INACTIVE,
    CONSENT_MISSING,
    MAX_CALIBRATION_RECEIPT_BYTES,
    MAX_CALIBRATION_REQUEST_BYTES,
    commit_payload,
    consent_payload,
    is_calibration_command,
)
from jarvis.runtime.barehands_calibration import (
    ANALYSED_EVENT_TYPES,
    CALIBRATION_ACK_TTL_S,
    CALIBRATION_ANALYSIS_ACK,
    CalibrationSessionRegistry,
    calibration_notice_key,
    describe_calibration_event,
    parse_calibration_event,
    render_calibration_event,
)
from jarvis.runtime.barehands_commands import BarehandsCommandBroker
from jarvis.domain.scene_capture import INVALID_PNG, MAX_CAPTURE_BYTES, UNKNOWN_CAPTURE, check_capture_id, png_dimensions
from jarvis.protocol.strict_json import loads_strict_json
from jarvis.runtime.barehands_mcp import BarehandsMcpTarget
from jarvis.runtime.settings_mcp import ConsoleMcpTarget
from jarvis.runtime.tools_gateway_mcp import ToolsGatewayTarget
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
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
#: Préfixe des routes de lecture des Conversation Events (Slice 04).
CONVERSATIONS_ROUTE = "/api/conversations"
#: Préfixe des routes du Test Lab Catégorie 2 (`jarvis.testlab.http.TESTLAB_ROUTE`,
#: épinglé égal par `tests/unit/test_testlab_http.py`). Répété ici pour que le
#: middleware ne dépende pas de l'import du paquet testlab.
TESTLAB_ROUTE = "/api/testlab"
#: Canal de commandes Bare Hands (Slice 12). Un POST d'origine étrangère y est
#: refusé comme partout ailleurs, mais **avec la forme d'erreur du canal** :
#: sans elle, le garde lève un `HTTPForbidden` en texte brut, sans corps JSON ni
#: `X-Jarvis-Error-Code`, et le serveur MCP n'a plus de code à nommer — alors
#: que « tout refus porte un code stable » est une contrainte de cette Slice.
BAREHANDS_COMMANDS_ROUTE_PREFIX = "/api/barehands/commands"
#: Séance de calibration déclarée par la page (Slice 06 adaptative, décision 50).
#: Gardée comme le canal : elle donne au cerveau l'autorité des outils
#: `calibration_*`, donc une page étrangère ne doit pouvoir ni l'ouvrir ni la lire.
BAREHANDS_CALIBRATION_SESSION_ROUTE = "/api/barehands/calibration-session"
#: Événements du parcours (revue d'un exercice, rapport final) que la page
#: envoie pour que le cerveau les analyse à voix haute (retour du 28/09).
BAREHANDS_CALIBRATION_EVENT_ROUTE = "/api/barehands/calibration-event"
#: Borne du corps d'un événement : des mots d'écran, jamais des mesures brutes.
MAX_CALIBRATION_EVENT_BYTES = 16_384
#: Un tour d'analyse est court ; au-delà, il est abandonné et dit au journal.
CALIBRATION_EVENT_TIMEOUT_S = 180.0
BAREHANDS_BENCHMARKS_ROUTE = "/api/barehands/benchmarks"
_CALIBRATION_SESSION = re.compile(r"\A[A-Za-z0-9_-]{16,64}\Z")

#: Catalogue des outils MCP (Slice 06 du handoff MCP inspector) : GET seulement.
#: Hors de `READ_GUARDED_ROUTES`, comme `/api/catalog` et `/api/agent` : ni
#: transcription ni consommation, et rien de secret (contrat §9 de
#: `docs/mcp/tool-contract.md`, testé par sentinelles).
MCP_TOOLS_ROUTE = "/api/mcp/tools"
#: Tout chemin sous ce préfixe répond en JSON codé, même quand aucune route ne
#: l'apparie (404) ou que la méthode n'existe pas (405) : `_mcp_json_errors`.
MCP_ROUTE_PREFIX = "/api/mcp"

#: Préfixes dont TOUTES les méthodes sont gardées (Host de bouclage, Origin de
#: bouclage, jamais `Sec-Fetch-Site: cross-site`) : ils exposent des transcriptions
#: et des preuves de session, donc une lecture est aussi sensible qu'une écriture.
#:
#: Le canal de commandes y est pour une **troisième** raison, trouvée en Slice 11
#: et qui n'est ni la confidentialité ni l'intégrité : `BarehandsCommands.deliver`
#: marque la commande remise au **premier** long-poll qui la demande (remise une
#: fois, à une seule page). Un `GET` d'origine étrangère est parti en requête
#: simple — aucun préflight sur un GET sans en-tête — et le navigateur ne lui
#: rendait que le corps, pas le serveur : la page attaquante ne **lisait** rien
#: et **consommait** quand même. La vraie page attendait alors pour toujours une
#: commande déjà remise, et l'utilisateur voyait « JARVIS n'ouvre pas le
#: tutoriel » sans qu'aucun refus n'existe nulle part. Un déni de commande, pas
#: une fuite : c'est la consommation qui est l'arme, donc le refus doit arriver
#: **avant** le handler, et la méthode de lecture doit être gardée comme
#: l'écriture. `GET /api/scene/patches` a la même forme de long-poll mais pas la
#: même propriété — son curseur `after` vient de l'appelant et rien n'y est
#: consommé côté serveur, donc un appel étranger n'y prend rien à personne.

#:
#: Les résumés du banc d'essai Bare Hands (Slice 08 adaptative) y sont aussi :
#: ce sont des mesures de l'interaction d'une personne, relues pour
#: l'avant/après, et leur refus porte un code nommé comme celui du canal.
#: Route interne Core -> Control Center (Slice 04a) : activation du cerveau d'une
#: liaison. Aucun jeton, comme `/api/agent/ask` que Core appelle déjà : serveur
#: sur la boucle locale, et **toutes** ses méthodes gardées comme ci-dessus
#: (Host de bouclage, Origin de bouclage s'il existe, jamais cross-site) - plus
#: strict que `/api/agent/ask`.
AGENT_BINDINGS_ROUTE = "/api/agent/bindings"
#: Gestion des plugins MCP (generic-mcp-plugin-runtime, Slice 06) : toutes les
#: méthodes gardées — les adresses des plugins sont privées, et ces routes
#: écrivent. Le retour OAuth `/api/mcp/oauth/callback` n'y est **pas** : la
#: redirection du serveur d'autorisation arrive par une navigation inter-sites
#: (ARCH §14 C6) ; `mcp_plugin_routes.py` exige un Host de bouclage.
READ_GUARDED_ROUTES = (CONVERSATIONS_ROUTE, TESTLAB_ROUTE, BAREHANDS_COMMANDS_ROUTE_PREFIX,
                       BAREHANDS_CALIBRATION_SESSION_ROUTE, BAREHANDS_BENCHMARKS_ROUTE, AGENT_BINDINGS_ROUTE,
                       MCP_PLUGINS_ROUTE)
#: Corps de `POST /api/agent/bindings/activate` : une liaison sérialisée, bornée.
AGENT_BINDING_MAX_BYTES = 8 * 1024
#: Adoption de la liaison foreground au démarrage : Core peut démarrer après
#: nous. Délai croissant, plafonné ; s'arrête dès que le foreground est lié.
SESSION_ADOPT_RETRY_S = (1.0, 2.0, 5.0, 10.0, 30.0)


#: Characters that never belong to a plain `host[:port]` authority (userinfo,
#: fragment, path, query, spaces): their presence refuses the request outright.
_AUTHORITY_FORBIDDEN = frozenset("@#/?\\ \t%")
#: Concurrent trace drill-down scans (each one reads up to 64 MiB in a thread).
MAX_TRACE_DRILL_DOWNS = 2
TRACE_SLOT_WAIT_S = 10.0


def _authority_host(authority: str) -> str | None:
    """Exact host of `host[:port]` / `[v6][:port]`, lower-cased, or None when malformed."""
    if not authority or any(char in _AUTHORITY_FORBIDDEN for char in authority):
        return None
    if authority.startswith("["):
        close = authority.find("]")
        host, rest = (authority[1:close], authority[close + 1:]) if close > 0 else (None, "")
    elif authority.count(":") <= 1:
        host, _, port = authority.partition(":")
        rest = ":" + port if _ else ""
    else:
        return None  # bare IPv6 without brackets is not a valid Host
    if host is None or (rest and not (rest.startswith(":") and rest[1:].isascii() and rest[1:].isdigit())):
        return None
    return host.lower()


def _loopback_refusal(origin: str | None, host_header: str | None, fetch_site: str | None) -> str | None:
    """Why a conversation history request is refused, or None.

    Exact comparison after splitting the port, no URL parser quirks:
    `evil.com@127.0.0.1` or `127.0.0.1#.evil.com` are refused. `Sec-Fetch-Site:
    cross-site` is refused whatever the other headers say.
    """
    if (fetch_site or "").strip().lower() == "cross-site":
        return "cross-site request"
    if origin is not None:
        scheme, separator, authority = origin.partition("://")
        if not separator or scheme.lower() not in {"http", "https"} or _authority_host(authority) not in LOOPBACK_HOSTS:
            return "forbidden origin"
    if _authority_host(host_header or "") not in LOOPBACK_HOSTS:
        return "forbidden host"
    return None


#: En-tête d'un refus d'enregistrement (HTTP 400) portant son code stable.
SETTINGS_ERROR_CODE_HEADER = "X-Jarvis-Error-Code"

#: Panne Bare Hands remontée par la page (`/api/barehands/failures`) : un code
#: du vocabulaire `FAILURE_CODES` du contrat JS, et des textes bornés.
BAREHANDS_FAILURE_CODE = re.compile(r"[a-z][a-z_]{0,63}")
BAREHANDS_FAILURE_TEXT_LIMIT = 4000

#: Délai avant qu'un rattrapage de mode d'interaction puisse être réarmé. Le
#: statut bat chaque seconde ; sans ce répit, un Core joignable qui refuse
#: produirait une tentative d'écriture par battement de page.
INTERACTION_MODE_REPLAY_BACKOFF_S = 30.0

#: Longueur maximale d'une valeur brute recopiée dans le journal. Même borne
#: que celle des autres émetteurs de cette surface : un réglage trafiqué ne
#: doit pas pouvoir remplir `trace.jsonl`.
MAX_JOURNALLED_VALUE_CHARS = 64


def _short(value: object) -> str | None:
    """Valeur brute bornée pour le journal, ou `None` s'il n'y en avait pas."""

    return None if value is None else str(value)[:MAX_JOURNALLED_VALUE_CHARS]

#: Logique pure du panneau Agents, gardée à part pour être exécutée par les
#: tests (node) et insérée dans la page à la place de ce repère.
WORK_SCRIPT_FILE = "control_center_work.js"
WORK_SCRIPT_MARKER = "/*__CONTROL_CENTER_WORK_JS__*/"
LIVE_SCRIPT_FILE = "control_center_live.js"
LIVE_SCRIPT_MARKER = "/*__CONTROL_CENTER_LIVE_JS__*/"
CATALOG_SCRIPT_FILE = "control_center_catalog.js"
CATALOG_SCRIPT_MARKER = "/*__CONTROL_CENTER_CATALOG_JS__*/"
#: Contrats et schémas Bare Hands V1 (Slice 01) : identité de main et de
#: pointeur, HandFrame neutre, gestes, pincement, régions de cible,
#: interaction, outils, réglages et profil de calibration
#: (`window.JarvisBarehandsContracts`, logique pure). Inséré AVANT le pointeur
#: et la page de scène, qui lisent tous deux l'identité de pointeur.
BAREHANDS_CONTRACTS_SCRIPT_FILE = "control_center_barehands_contracts.js"
BAREHANDS_CONTRACTS_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_CONTRACTS_JS__*/"
#: Le § 12 du contrat, séparé à la Slice 10 adaptative : calibration
#: adaptative et banc d'essai (`window.JarvisBarehandsAdaptive`, logique pure,
#: tous les noms du contrat plus les siens). Inséré JUSTE APRÈS le contrat,
#: qu'il étend, et avant l'enregistreur, la calibration, le banc et le pointeur.
BAREHANDS_ADAPTIVE_SCRIPT_FILE = "control_center_barehands_adaptive.js"
BAREHANDS_ADAPTIVE_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_ADAPTIVE_JS__*/"
#: Vocabulaire de dessin des mains schématiques Bare Hands (décision 20) :
#: postures en données, un seul traceur, aucune dépendance
#: (`window.JarvisBarehandsHandArt`). Inséré APRÈS les contrats — pure
#: convention de rangement, il n'en lit rien — et surtout **AVANT la
#: calibration**, qui le lit pour dessiner ses mains virtuelles, et avant le
#: contrôle du haut-gauche, qui y prend son icône. Un seul jeu de mains pour
#: toute la fonctionnalité : deux auraient dérivé, et l'utilisateur n'aurait
#: pas reconnu dans la calibration la main apprise dans l'aide.
BAREHANDS_HAND_ART_SCRIPT_FILE = "control_center_barehands_hand_art.js"
BAREHANDS_HAND_ART_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_HAND_ART_JS__*/"
#: Cible sémantique Bare Hands (Slice 05) : collecte des candidates du DOM et
#: aperçu visuel des régions (`window.JarvisBarehandsTarget`). Inséré APRÈS les
#: contrats, qu'il lit, et AVANT le pointeur, qui le lit.
BAREHANDS_TARGET_SCRIPT_FILE = "control_center_barehands_target.js"
BAREHANDS_TARGET_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_TARGET_JS__*/"
#: Pointeur à mains nues (Barehands, mode test) : logique pure testée par node,
#: Parcours de calibration et coque de surimpression Bare Hands (Slice 08,
#: architecture §10 et §11, décisions 26 à 32). Inséré **après** les contrats
#: qu'il lit et **avant** le pointeur, qui le lit pour poser
#: `JarvisBarehands.calibrate()` sur sa surface gelée — une surface qu'on ne
#: peut pas compléter après coup, donc l'ordre casse à l'insertion et non trois
#: clics plus tard.
BAREHANDS_CALIBRATION_SCRIPT_FILE = "control_center_barehands_calibration.js"
BAREHANDS_CALIBRATION_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_CALIBRATION_JS__*/"
#: Enregistrement, rejeu et mesures Bare Hands (Slice 10, architecture §12,
#: décision 32) : schéma de trace, liste blanche, garde de forme au chargement,
#: enregistreur opt-in et rejeu déterministe (`window.JarvisBarehandsRecorder`).
#: Inséré **après** les contrats qu'il lit et **avant** le pointeur, qui le lit
#: pour poser `JarvisBarehands.record` sur sa surface gelée — une surface qu'on
#: ne peut pas compléter après coup.
BAREHANDS_RECORDER_SCRIPT_FILE = "control_center_barehands_recorder.js"
BAREHANDS_RECORDER_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_RECORDER_JS__*/"
#: La séance de l'agent de calibration (tâche adaptative, Slice 06) : retours,
#: hypothèses, essais, commandes de repli et déclaration de séance
#: (`window.JarvisBarehandsCalibrationAgent`). Inséré **après** les contrats et
#: **avant** le pointeur, qui la lit défensivement à l'ouverture d'une calibration.
BAREHANDS_CALIBRATION_AGENT_SCRIPT_FILE = "control_center_barehands_calibration_agent.js"
BAREHANDS_CALIBRATION_AGENT_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_CALIBRATION_AGENT_JS__*/"
#: Banc d'essai « Tester » (tâche adaptative, Slice 08) : plan, déroulé,
#: score et comparaison (`window.JarvisBarehandsBenchmark`). Inséré **après**
#: les contrats qu'il lit et avant le pointeur ; rien ne le lit au chargement.
BAREHANDS_BENCHMARK_SCRIPT_FILE = "control_center_barehands_benchmark.js"
BAREHANDS_BENCHMARK_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_BENCHMARK_JS__*/"
#: L'écran « Tester » (tâche adaptative, Slice 09) : le test court, son
#: rapport et l'avant/après (`window.JarvisBarehandsBenchmarkUi`). Inséré
#: **après** le banc qu'il lit et avant le pointeur, qui le branche.
BAREHANDS_BENCHMARK_UI_SCRIPT_FILE = "control_center_barehands_benchmark_ui.js"
BAREHANDS_BENCHMARK_UI_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_BENCHMARK_UI_JS__*/"

#: plus son branchement navigateur. Même insertion que les scripts ci-dessus.
BAREHANDS_SCRIPT_FILE = "control_center_barehands.js"
BAREHANDS_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_JS__*/"
#: Contrôle de cycle de vie Bare Hands de la barre du haut : bouton carré à
#: icône de main en haut à gauche et sélecteur visuel OFF/VEILLE/ACTIF
#: (`window.JarvisBarehandsHud`). Inséré APRÈS le pointeur, qui pose
#: `window.JarvisBarehands` **et** la couture de diffusion du cycle de vie
#: (`openLifecycleSeam`) à laquelle ce contrôle s'abonne : sans elle il ne
#: reflèterait ni le réveil en C, ni le retour en veille, ni la voix. Son bloc
#: navigateur les lit au chargement et **refuse de s'installer** sans elles,
#: pour que l'ordre casse à l'insertion et non trois clics plus tard.
BAREHANDS_HUD_SCRIPT_FILE = "control_center_barehands_hud.js"
BAREHANDS_HUD_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_HUD_JS__*/"
#: Canal de commandes du cerveau vers Bare Hands (Slice 12) : long-poll de
#: `GET /api/barehands/commands` et remise de chaque commande au **même** point
#: d'entrée que le bouton (`window.JarvisBarehands`). Inséré APRÈS le pointeur,
#: qui pose ce point d'entrée : son bloc navigateur le lit au chargement et
#: refuse de s'installer sans lui.
BAREHANDS_COMMANDS_SCRIPT_FILE = "control_center_barehands_commands.js"
BAREHANDS_COMMANDS_SCRIPT_MARKER = "/*__CONTROL_CENTER_BAREHANDS_COMMANDS_JS__*/"
#: Contrôle de mode d'interaction du bas-gauche (Slice 03 de
#: `jarvis-presentation-interaction-mode`) : bouton d'état compact montrant le
#: mode **en vigueur** (SIMPLE / PRESENTATION) et sélecteur à trois choix, où
#: REUNION est annoncé et réservé. Contrairement aux modules Bare Hands, il ne
#: dépend d'aucun autre module de page : sa seule source est le bloc
#: `interaction_mode` de `GET /api/status`, que `refreshStatus` lui remet une
#: fois par seconde (`gate`), et `statusLost` quand ce sondage tombe. Il n'a
#: donc pas d'ordre d'insertion à respecter vis-à-vis des autres scripts — il
#: lit `api` et `refreshStatus`, deux déclarations de fonction remontées du même
#: `<script>`. Son bloc navigateur **refuse de se dessiner** sous un nom
#: cherchable si son emplacement manque, et rattrape ce refus pour ne pas
#: emporter les autres modules avec lui.
INTERACTION_MODE_SCRIPT_FILE = "control_center_interaction_mode.js"
INTERACTION_MODE_SCRIPT_MARKER = "/*__CONTROL_CENTER_INTERACTION_MODE_JS__*/"
#: Avertissement flottant de vérification (Slice 09 de
#: `jarvis-presentation-interaction-mode`) : une carte discrète, posée en bas de
#: la pile d'infusions existante, pour une contradiction vérifiée. Il lit le
#: bloc `background.attention` de `GET /api/status` — donc le même battement à
#: 1 Hz que le contrôle de mode, et aucun second sondage — et il arbitre le
#: signal sonore entre onglets pour que `bgCue` ne sonne qu'une fois.
#:
#: Il ne dépend d'aucun autre module de page. Comme le contrôle de mode, il
#: refuse de s'installer sous un nom cherchable si la pile d'infusions manque,
#: et **rattrape ce refus** : la page servie concatène tous ses modules dans un
#: seul `<script>`, et une levée qui remonterait emporterait les autres.
#: Contrôle Boards du haut-droit (handoff `jarvis-board-session-context-runtime`,
#: Slice 06) : titre du Board actif toujours visible, liste, bascule, création,
#: renommage, archivage, nouvelle Session. Il suit le bloc `boards` de
#: `GET /api/status` (`gate` / `statusLost`, comme le contrôle de mode) et
#: n'appelle que `/api/boards*` / `/api/sessions*`. Deux emplacements déclarés
#: dans la page (`#boardsHud`, `#boardsPanel`) ; refus d'installation rattrapé.
BOARDS_SCRIPT_FILE = "control_center_boards.js"
BOARDS_SCRIPT_MARKER = "/*__CONTROL_CENTER_BOARDS_JS__*/"
PRESENTATION_ATTENTION_SCRIPT_FILE = "control_center_presentation_attention.js"
PRESENTATION_ATTENTION_SCRIPT_MARKER = "/*__CONTROL_CENTER_PRESENTATION_ATTENTION_JS__*/"
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
#: Capture visuelle exceptionnelle de la scène (Slice 09, partie 2) : dessin
#: du modèle de vue et réponse du meneur visible, logique pure
#: (`window.JarvisSceneCapture`), insérée avant le bloc de page qui l'utilise.
SCENE_CAPTURE_SCRIPT_FILE = "control_center_scene_capture.js"
#: Route d'envoi des captures : ses refus d'origine ont la forme d'erreur de scène.
SCENE_CAPTURE_ROUTE_PREFIX = "/api/scene/captures/"
SCENE_CAPTURE_SCRIPT_MARKER = "/*__CONTROL_CENTER_SCENE_CAPTURE_JS__*/"
#: Réglages d'affichage de la constellation (Slice 12) : définition des
#: réglages, normalisation, variables CSS et options de la dérive orbitale
#: (`window.JarvisSceneView`, logique pure). Le bouton et sa fenêtre vivent dans
#: le bloc navigateur du rendu, qui le lit : inséré avant lui.
SCENE_VIEW_SCRIPT_FILE = "control_center_scene_view.js"
SCENE_VIEW_SCRIPT_MARKER = "/*__CONTROL_CENTER_SCENE_VIEW_JS__*/"
#: Réglage `scene.enabled` à l'écran (Slice 11) : section de l'onglet
#: Expérimental (logique pure `window.JarvisSceneSettings` testée par node, puis
#: son branchement), insérée après Barehands, qui crée cet onglet.
SCENE_SETTINGS_SCRIPT_FILE = "control_center_scene_settings.js"
SCENE_SETTINGS_SCRIPT_MARKER = "/*__CONTROL_CENTER_SCENE_SETTINGS_JS__*/"
#: Chronologie de conversation plein écran (Slice 05) : logique pure testée par
#: node et branchement navigateur, insérés comme les scripts ci-dessus.
TIMELINE_SCRIPT_FILE = "control_center_timeline.js"
TIMELINE_SCRIPT_MARKER = "/*__CONTROL_CENTER_TIMELINE_JS__*/"
#: Test Lab plein écran (Slice 11 de jarvis-category2-test-lab) : logique pure
#: testée par node et branchement navigateur. Inséré APRÈS la chronologie, dont
#: le bloc navigateur réutilise le client HTTP de la page.
TESTLAB_SCRIPT_FILE = "control_center_testlab.js"
TESTLAB_SCRIPT_MARKER = "/*__CONTROL_CENTER_TESTLAB_JS__*/"
#: Inspecteur MCP plein écran, lecture seule (Slice 07 de
#: jarvis-mcp-semantic-batch-inspector) : logique pure testée par node et
#: branchement navigateur, qui ne lit que `MCP_TOOLS_ROUTE` en GET. Inséré après
#: le Test Lab, dont il partage la coquille plein écran.
MCP_INSPECTOR_SCRIPT_FILE = "control_center_mcp_inspector.js"
MCP_INSPECTOR_SCRIPT_MARKER = "/*__CONTROL_CENTER_MCP_INSPECTOR_JS__*/"
#: Gestion des plugins MCP externes (generic-mcp-plugin-runtime, Slice 06) :
#: onglet « Plugins externes » du même dialogue. SEUL module de la page qui
#: écrit sous `/api/mcp` (`/api/mcp/plugins*`) ; il réutilise le client en
#: lecture seule et le rendu de détail de l'inspecteur, donc inséré APRÈS lui.
MCP_PLUGINS_SCRIPT_FILE = "control_center_mcp_plugins.js"
MCP_PLUGINS_SCRIPT_MARKER = "/*__CONTROL_CENTER_MCP_PLUGINS_JS__*/"

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


#: Consigne de manifestation du mode PRESENTATION, apposée au tour lui-même et
#: non à la session : le mode change à chaud (Décision D15), une consigne de
#: session serait périmée au premier changement. Elle **double** le contrat
#: d'exécution, elle ne le remplace pas : `jarvis/runtime/presentation_speech_gate.py`
#: refuse la parole que cette consigne décrit, qu'elle ait été lue ou non.
BRIEF_PRESENTATION_MODE = (
    "Mode PRESENTATION. Tu accompagnes quelqu'un qui présente devant un public : "
    "l'écran répond, la voix se tait. Une demande d'affichage (montrer, ouvrir, "
    "masquer, épingler, ranger) s'exécute et se termine **sans un mot** : ne "
    "confirme pas, ne décris pas ce que tu affiches, ne lis pas ce que tu viens "
    "de montrer. Une vraie question, ou une demande explicite de parler, se "
    "répond à l'oral, utilement et avec ses réserves. Ce qui a échoué se dit "
    "toujours. Ce que tu n'as pas compris se demande toujours, et la question "
    "passe si — et seulement si — ta réponse est une seule phrase "
    "interrogative et rien d'autre : « De quel bilan parles-tu, le Q3 ou le "
    "Q4 ? ». Une phrase qui répond puis demande compte comme une réponse. "
    "Ceci n'est pas une consigne de politesse : hors de ces cas, le runtime ne "
    "délivrera pas ta phrase, et tu auras écrit pour rien."
)


#: Consigne du mode CALIBRATION (tâche adaptative Bare Hands, Slice 06,
#: décision 51). Même patron que le mode présentation : apposée **au tour**, parce
#: que la séance s'ouvre et se ferme à chaud, et doublée par le runtime — hors
#: séance les outils `calibration_*` refusent, une mesure ne s'écrit que par du
#: code déterministe de la page, une acceptation sans parole de l'utilisateur est
#: refusée par le serveur. Cette consigne n'est pas la règle ; elle évite que le
#: modèle rédige contre elle.
BRIEF_CALIBRATION_MODE = (
    "Mode CALIBRATION. Une séance de calibration Bare Hands est ouverte à l'écran et tu en es "
    "l'assistant. Le partage des rôles est strict : le runtime MESURE et CONSTATE (verdict, cause, "
    "interprétation de chaque résultat, valeurs effectives) ; toi, tu INTERPRÈTES et tu PROPOSES ; "
    "l'utilisateur DÉCIDE ; le panneau de calibration à gauche de l'écran rend tout visible.\n"
    "- Les mesures viennent de calibration_status et des événements de séance, et d'eux seuls. Tu les "
    "désignes par leurs références (ep-3, ex-2) ; le code les chiffre. N'invente, n'arrondis et ne recopie "
    "jamais un nombre qu'un outil ne t'a pas rendu. Une interprétation du runtime (bon, à surveiller, "
    "mauvais) ne se contredit pas.\n"
    "- Ce que l'utilisateur dit de son ressenti s'enregistre avec calibration_record_feedback, avec ses mots "
    "exacts. Un ressenti n'est pas un réglage.\n"
    "- Une cause est une hypothèse : calibration_propose_hypothesis, fondée sur les preuves et les retours "
    "cités, avec une confiance modeste.\n"
    "- PROPOSER n'est pas APPLIQUER. calibration_prepare_trial crée une proposition visible dans le panneau "
    "(summary : ce qu'elle change pour lui, en mots d'utilisateur ; untouched : ce que tu ne touches pas et "
    "pourquoi). RIEN n'est appliqué : l'utilisateur peut corriger les valeurs avant de valider. Puis tu "
    "ATTENDS sa décision.\n"
    "- Valider appartient à l'utilisateur : il clique « Appliquer et refaire » ou « Appliquer et continuer » "
    "dans le panneau, ou il te le dit. Seulement s'il te l'a dit lui-même (« oui, applique », « vas-y, on "
    "refait »), calibration_commit_proposal avec proposal_ref, action (rerun = appliquer puis refaire "
    "l'exercice ; continue = appliquer, garder sans refaire, étape soldée « accepté par l'utilisateur, non "
    "revérifié ») et user_quote, ses mots exacts. Le runtime fait toute la transaction (appliquer, relire le "
    "moteur, refaire ou avancer) : n'enchaîne pas d'autres appels pour la compléter.\n"
    "- N'annonce JAMAIS une application, une relance ou une validation avant le reçu qui la montre : "
    "« c'est appliqué, je relance » seulement quand calibration_commit_proposal a rendu steps avec applied, "
    "verified et rerun. Une proposition « stale » ne vaut plus : rien n'a été appliqué, dis-le.\n"
    "- Les décisions de l'écran t'arrivent par les événements de séance (décision, étape d'après, source) : "
    "crois-les, ne les redéduis pas.\n"
    "- Après un essai refait, juge-le avec calibration_resolve_trial sur les mesures d'avant et d'après prises "
    "sur ce même exercice. Un essai qui n'améliore rien baisse la confiance : ne le repropose pas sans preuve "
    "nouvelle. « annule » : calibration_rollback_trial tout de suite, note ce qu'il a dit, puis juge l'essai.\n"
    "- Chaque tour de la séance fait lui-même ses appels courts calibration_* : ne confie jamais la "
    "calibration à un sous-agent d'arrière-plan.\n"
    "- Pendant la séance, n'appelle ni settings_get ni settings_set, et ne lis ni ne cherche aucun "
    "fichier ni code (ni Read, ni Grep, ni Bash) : calibration_status te donne toutes les valeurs. "
    "calibration_accept_trial (garder un essai déjà refait et jugé) seulement quand il a dit vouloir le "
    "garder, en recopiant dans user_quote ses mots exacts ; une phrase qui nie, annule ou doute n'est pas un "
    "accord.\n"
    "- Le parcours n'avance jamais seul : calibration_next_exercise sans reason valide l'étape réussie ; avec "
    "la raison que l'utilisateur a donnée, l'exercice est passé ; annonce la décision que rend le reçu "
    "(decision : validated = validé, skipped = passé), jamais une autre ; calibration_rerun_exercise le refait.\n"
    "- Réponse à voix : DEUX phrases au plus, vingt-cinq mots au plus en tout, sans nom de paramètre "
    "ni jargon. Exemple : « Ton pincement se relâche un peu tôt ; je propose de l'assouplir. Je l'applique "
    "et on refait ? »"
)


def render_calibration_brief(calibration: object) -> list[str]:
    """Les lignes du mode calibration pour ce tour, ou rien hors séance."""

    if not isinstance(calibration, dict) or calibration.get("active") is not True:
        return []
    lines = [BRIEF_CALIBRATION_MODE]
    exercise = str(calibration.get("exercise") or "").strip()
    trial = str(calibration.get("trial") or "").strip()
    proposal = str(calibration.get("proposal") or "").strip()
    state = [f"exercice à l'écran : {exercise}" if exercise else "", f"essai en cours : {trial}" if trial else "",
             f"proposition en attente de l'utilisateur : {proposal}" if proposal else ""]
    if any(state):
        lines.append("Séance : " + " ; ".join(item for item in state if item) + ".")
    events = [str(item) for item in calibration.get("events") or [] if str(item).strip()]
    if events:
        lines.append(f"Derniers événements de la séance (révision {calibration.get('revision') or 0}, "
                     "le plus récent en dernier) :")
        lines.extend(f"- {item}" for item in events)
    return lines


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


def _seconds(ms: object) -> str:
    return f"{float(ms) / 1000:.1f}".replace(".", ",") + " s"


def render_interrupted_speech(items: object) -> list[str]:
    """Dire au cerveau ce que l'utilisateur a coupé, et ce qu'il en a entendu.

    Sa propre session garde le texte entier de ses réponses : sans ces lignes,
    il répond comme si tout avait été dit (17/09/2026).
    """

    lines: list[str] = []
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        heard = str(item.get("heard_text") or "").strip()
        played, total = item.get("played_ms") or 0, item.get("total_ms")
        if not heard:
            lines.append(
                f"COUPÉ : ta réponse « {text} » n'a pas été entendue du tout. "
                "L'utilisateur ne la connaît pas."
            )
            continue
        duration = f"au bout de {_seconds(played)}" + (f" sur environ {_seconds(total)}" if total else "")
        lines.append(
            f"COUPÉ : l'utilisateur t'a interrompu {duration} pendant ta réponse « {text} ». "
            f"Il n'en a entendu que le début, à peu près : « {heard}… ». "
            "La suite n'a PAS été dite : ne la tiens pas pour connue, et ne prends pas ce qu'il dit "
            "maintenant pour une réponse à ce qu'il n'a pas entendu. Redis ce qui compte encore, si c'est utile."
        )
    return lines


def render_pending_speech(items: object) -> list[str]:
    """Dire au cerveau ce qu'il avait rédigé et qui n'a pas été dit.

    Décision 48 (28/09/2026) : une formulation écrite pour une intention passée
    n'est plus prononçable d'elle-même ; la bouche la retient et elle ne sera
    dite que si le cerveau la redit maintenant, reformulée pour la situation
    actuelle. Sans ces lignes, il ne saurait pas ce que l'utilisateur n'a pas
    entendu.

    Le lien de réémission est nommé, jamais deviné : la ligne
    `[[jarvis:redit <speech_id>]]` (`REDIT_MARKER`), retirée avant la parole.
    """

    lines: list[str] = []
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        speech = str(item.get("speech_id") or "").strip()
        if not text or not speech:
            continue
        lines.append(
            f"PAS DIT : ta réponse « {text} », rédigée avant ce que l'utilisateur vient de dire, "
            "n'a pas été dite et ne le sera pas telle quelle. Redis ce qui reste utile, reformulé pour "
            "la situation actuelle ; sinon n'en dis rien. Si ta réponse la redit, ajoute seule sur une "
            f"ligne : {REDIT_MARKER}{speech}]]"
        )
    return lines


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
    # Slice 07 : le mode de manifestation, joint à chaque tour parce qu'il
    # change à chaud. La règle est tenue par le runtime (`PresentationSpeechGate`,
    # `jarvis/runtime/presentation_speech_gate.py`) ; cette ligne n'est pas la
    # règle, elle est ce qui évite que le modèle rédige contre elle.
    if str(context.get("interaction_mode") or "") == InteractionMode.PRESENTATION.value:
        lines.append(BRIEF_PRESENTATION_MODE)
    # Slice 06 adaptative : le mode calibration, joint par le Control Center
    # lui-même (`agent_ask`) pendant une séance déclarée par la page.
    lines.extend(render_calibration_brief(context.get("calibration")))
    # Board du tour (handoff board-session, Slice 08) : hydrate le CLI depuis
    # l'état durable du Board, jamais depuis une autre conversation.
    lines.extend(render_board_brief(context.get("board")))
    # Context actif de la Session (handoff session-context-recording, Slice 03) :
    # son dossier est le seul espace de travail implicite du cerveau.
    lines.extend(render_session_context_brief(context.get("session_context")))
    lines.extend(render_interrupted_speech(context.get("interrupted_speech")))
    lines.extend(render_pending_speech(context.get("pending_speech")))
    state = context.get("state")
    if isinstance(state, dict):
        # Une formulation remise (« PAS DIT ») reste un fait public connu de Core
        # (la vérité n'est pas touchée), mais la ranger aussi sous « Déjà dit à
        # l'utilisateur » contredirait la ligne qui dit qu'il ne l'a pas entendue
        # (traces réelles, suivi de la Slice 04) : seul le rendu l'omet ici.
        unsaid = {str(item.get("text") or "").strip() for item in context.get("pending_speech") or ()
                  if isinstance(item, dict)} - {""}
        for key, label in _BRIEF_STATE_FIELDS:
            value = state.get(key)
            if key == "known_public_facts" and unsaid and isinstance(value, (list, tuple)):
                value = [fact for fact in value if str(fact).strip() not in unsaid]
            rendered = _brief_value(value)
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


class _ActiveBoardRead(NamedTuple):
    """Une lecture de `GET /v1/boards/active` par battement de `/api/status` (Slice 06)."""

    #: Le Board actif (payload Core), `None` si la lecture a échoué ou si Core n'a pas de Boards.
    board: dict[str, Any] | None
    #: `{code, message}` quand `board` manque.
    error: dict[str, Any] | None
    #: `False` : pas de Core configuré, ou Core sans Boards (404 texte).
    supported: bool


class ControlCenter:
    def __init__(
        self,
        *,
        runtime_root: Path,
        project_root: Path,
        visualizer_url: str | None = None,
        audio_diagnostics: SoundDeviceAudioDiagnostics | None = None,
        work_ingress: WorkIngressForwarder | None = None,
        conversation_events: ConversationEventForwarder | None = None,
        conversation_event_view: ConversationEventView | None = None,
        work_view: CoreWorkView | None = None,
        live_view: CoreLiveStatusView | None = None,
        scene_view: CoreSceneView | None = None,
        interaction_mode_view: CoreInteractionModeView | None = None,
        display_mcp: DisplayMcpTarget | None = None,
        barehands_mcp: "BarehandsMcpTarget | None" = None,
        console_mcp: "ConsoleMcpTarget | None" = None,
        tools_mcp: "ToolsGatewayTarget | None" = None,
        voice_registry: VoiceCapabilityRegistry | None = None,
        barehands_vendor_root: Path | None = None,
        sessions: CoreSessionTransport | None = None,
        agent_factory: Callable[[str], Any] | None = None,
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
        #
        # Slice 07 (board-session) : registre, curseur d'acquittement et
        # position dans la trace persistés (`runtime/background-events.json`) :
        # un non-lu survit au redémarrage et à une nouvelle Session, et ce qui
        # a été écrit pendant l'arrêt est rattrapé. Un fichier illisible est
        # mis de côté, dit (journal `error` -> badge Errors, et
        # `store_warning` du bloc `background`), et le registre repart vide.
        self._background_store = BackgroundEventStore(runtime_root / BACKGROUND_STORE_FILE, self.journal.trace_path)
        loaded = self._background_store.load()
        self.background = loaded.ledger
        self._background_trace = loaded.follower
        self._background_store_warning = loaded.warning
        self._background_saved_offset = self._background_trace.offset
        self._background_saved_at = time.monotonic()
        self._background_save_failed = False
        #: `board_id -> titre`, pour étiqueter les alertes. Nourri par le Board
        #: actif de chaque battement et, pour les autres, par une relecture
        #: bornée de la liste de Core (`_refresh_board_titles`).
        self._board_titles: dict[str, str] = {}
        self._board_titles_read_at = float("-inf")
        self._board_titles_task: asyncio.Task[None] | None = None
        if loaded.warning:
            self.journal.emit("background.store_unreadable", loaded.warning, level="error",
                              data={"path": str(self._background_store.path),
                                    "quarantined": str(loaded.quarantined) if loaded.quarantined else None,
                                    "dropped_entries": loaded.ledger.dropped_entries})
        self.journal.emit("background.store_loaded", "Notifications d'arrière-plan relues", data={
            "resumed": loaded.resumed, "entries": len(loaded.ledger.entries), "unread": loaded.ledger.unread,
            "offset": self._background_trace.offset})
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
        # Conversation Events des sous-agents Claude (handoff
        # conversation-observability, Slice 03b). Absent, rien ne part.
        self.conversation_events = conversation_events
        # Lecture des Conversation Events tenus par Core (Slice 04), pour la
        # timeline : le navigateur ne parle jamais à Core. Absent, les routes
        # `/api/conversations...` répondent `not_configured`.
        self.conversation_event_view = conversation_event_view or ConversationEventView(None, journal=self.journal)
        self._trace_slots = asyncio.Semaphore(MAX_TRACE_DRILL_DOWNS)
        self._trace_failing = False
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
        # Mode d'interaction : Core en possède la valeur effective vivante,
        # ce Control Center en possède la préférence enregistrée (Slice 02).
        # Absente, la vue répond « non configuré » et l'écran affiche le
        # réglage enregistré en le nommant comme tel, jamais comme la vérité.
        self.interaction_mode_view = interaction_mode_view or CoreInteractionModeView(None, journal=self.journal)
        # Une seule ligne par processus pour une préférence écrite par une
        # version inconnue : `GET /api/interaction-mode` part à chaque sondage.
        self._interaction_mode_foreign_reported = False
        # Rattrapage armé par le statut, exécuté hors du chemin de lecture :
        # une écriture n'a rien à faire sur le battement de la page.
        self._interaction_mode_replay: asyncio.Task[None] | None = None
        # Un avertissement par cause par minute : un Core qui refuse pour
        # toujours ne doit pas écrire une ligne par seconde.
        self._interaction_mode_reports = ReportThrottle()
        # Acteurs refusés : un avertissement par valeur par minute, avec le
        # nombre d'occurrences tues (une page en boucle ne remplit pas la trace).
        self._scene_forbidden_reports = ReportThrottle()
        # Où le serveur MCP d'affichage du cerveau joint Core (Slice 06). Remis
        # à l'agent Claude seulement quand `scene.enabled` est vrai.
        self.display_mcp = display_mcp
        self._display_unconfigured_reported = False
        # Canal de commandes Bare Hands (Slice 12) : où le serveur MCP
        # `jarvis-barehands` joint **ce** Control Center, et le courtier qui
        # tient la commande en vol. Remis à l'agent Claude seulement quand
        # `barehands_test_mode.enabled` est vrai, comme `display_mcp` l'est sur
        # `scene.enabled`.
        self.barehands_mcp = barehands_mcp
        # `jarvis-console` joint lui aussi ce Control Center, mais il n'a pas
        # d'interrupteur : il est remis à l'agent tel quel, toujours. C'est le
        # serveur qui porte les interrupteurs des deux autres.
        self.console_mcp = console_mcp
        # `jarvis-tools` (plugins MCP, Slice 05) : la passerelle de découverte,
        # sans interrupteur elle non plus, remise aux **deux** CLI (Claude par
        # `--mcp-config`, Codex par overrides `-c`). Joint Core, pas ce Control Center.
        self.tools_mcp = tools_mcp
        self._barehands_unconfigured_reported = False
        # Une ligne « catalogue MCP construit » par processus (Slice 06).
        self._mcp_catalog_reported = False
        # Partie « plugins » de `/api/mcp/tools` (plugins MCP, Slice 04) : dernière
        # réponse de Core (cache par révision) et état de la panne (journal une fois).
        self._mcp_external_cache: dict[str, Any] | None = None
        self._mcp_external_down = False
        # Une seule ligne de journal par processus pour un bloc de réglages
        # illisible : `GET /api/barehands` part à chaque ouverture de l'onglet.
        self._barehands_foreign_reported = False
        # Même règle pour le profil : une ligne par processus.
        self._barehands_profile_foreign_reported = False
        # La séance de calibration telle que la page la déclare (décision 50) :
        # mode du cerveau, porte des outils `calibration_*`, accord de
        # l'utilisateur, et page à qui remettre ces commandes.
        self.barehands_calibration = CalibrationSessionRegistry(emit=self.journal.emit)
        # L'analyse d'un événement de parcours en cours, et le dernier arrivé
        # pendant qu'elle tourne (un seul attend : le plus récent remplace).
        self._calibration_event_task: asyncio.Task[None] | None = None
        self._calibration_event_next: dict[str, Any] | None = None
        self.barehands_commands = BarehandsCommandBroker(
            journal=self.journal,
            gate=lambda: bool(barehands.load(self._settings())["enabled"]),
            calibration_holder=self.barehands_calibration.holder,
        )

        settings = self._settings()
        self._agent_id = cli_catalog.normalize_agent_cli(settings.get("agent_cli"))
        self._self_dev: SelfDevelopmentService | None = None
        # Sessions et Boards de Core (Slice 04a) : adoption de la liaison
        # foreground au démarrage, nouvelle Session sur `restart`, rapport du
        # CLI réel. Absent (tests, Core antérieur) : comportement historique.
        self.sessions = sessions
        # Un agent par liaison, un seul foreground (`docs/boards.md`, pool).
        # `self.agent` est l'agent du foreground ; `self._agents` ses agents par
        # CLI, exactement comme l'ancien dictionnaire unique.
        self._work_observers: dict[int, TrackerWorkObserver] = {}
        #: `<data_root>/sessions` de Core (handoff session-context-recording,
        #: Slice 03), appris de `GET /v1/sessions/current` ou du bloc
        #: `session_context` d'un tour : accordé à chaque CLI par `--add-dir`.
        self._sessions_root: Path | None = None
        self.board_brains = BoardBrainPool(
            factory=agent_factory or self._build_agent,
            selected_cli=lambda: self._agent_id,
            journal=self.journal,
            on_agent=self._wire_agent,
            on_evict=self._forget_agents,
        )
        self._agent_lock = asyncio.Lock()
        #: Dernier `(agent_cli, agent_session_id)` rapporté à Core, par liaison.
        self._binding_reports: dict[tuple[str, str], tuple[str, str | None]] = {}
        self._session_tasks: set[asyncio.Task[None]] = set()
        # Core a déjà répondu `GET /v1/boards/active` dans cette vie : le mode
        # d'interaction appartient au Board, plus à la préférence globale.
        self._core_has_boards = False
        # Core répond 404 texte à `/v1/boards/active` : sans Boards pour cette vie.
        self._core_boards_unsupported = False
        self._replay_retired_reported = False
        # Tours `/api/agent/ask` en vol (Slice 04b) : une bascule ou une
        # nouvelle Session demandée par le cerveau pendant son tour attend sa fin.
        self._asks_in_flight = 0
        self._asks_idle = asyncio.Event()
        self._asks_idle.set()
        # Relais `/api/boards*`, `/api/sessions*` vers Core (Slice 04b) : les
        # routes de l'UI et de `jarvis-console`, jamais Core en direct.
        self.board_routes = BoardSessionRoutes(
            transport=sessions, journal=self.journal,
            ask_in_flight=lambda: self._asks_in_flight > 0, wait_asks_idle=self._asks_idle.wait,
        )
        # Gestion des plugins MCP (Slice 06 plugins) : relais vers Core, transport
        # relu à chaque requête (`self.sessions` peut être remplacé après coup).
        self.mcp_plugin_routes = McpPluginRoutes(
            transport=lambda: self.sessions, journal=self.journal,
            loopback_host=lambda host: _authority_host(host or "") in LOOPBACK_HOSTS,
        )
        self._apply_agent_settings(settings)

        self._app = web.Application(middlewares=[self._origin_guard, self._mcp_json_errors])
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
            # Catalogue des outils MCP (handoff MCP inspector, Slice 06) :
            # lecture seule, **aucune** route d'exécution sous `/api/mcp`
            # (contrat `docs/mcp/tool-contract.md` §8, testé).
            web.get(MCP_TOOLS_ROUTE, self.mcp_tools),
            web.get(MCP_TOOLS_ROUTE + "/{server}/{name}", self.mcp_tool_detail),
            # Gestion des plugins MCP (generic-mcp-plugin-runtime, Slice 06) :
            # relais vers Core, écritures comprises, et retour OAuth. Toujours
            # aucune route d'exécution d'outil (`call_tool` vit dans Core).
            *self.mcp_plugin_routes.routes(),
            web.get("/api/models", self.models),
            web.get("/api/cli/agents", self.cli_agents),
            web.get("/api/routing/candidates", self.routing_candidates),
            web.get("/api/self-dev", self.self_dev_state),
            web.post("/api/self-dev", self.self_dev_start),
            web.post("/api/self-dev/deploy", self.self_dev_deploy),
            web.get("/api/shortcuts", self.get_shortcuts),
            web.post("/api/shortcuts", self.save_shortcuts),
            # Mode d'interaction (Slice 02). Route **dédiée**, hors de
            # `/api/settings` : elle s'applique à chaud, elle ne doit pas
            # dépendre de la validité des réglages de voix, et surtout elle
            # ne doit jamais traverser `_apply_voice`, dont la première
            # branche supprime `voice_architecture` (constat G1).
            web.get("/api/interaction-mode", self.get_interaction_mode),
            web.post("/api/interaction-mode", self.save_interaction_mode),
            web.get("/api/barehands", self.get_barehands),
            web.post("/api/barehands", self.save_barehands),
            # Profil de calibration (Slice 08). Route **distincte** de celle des
            # réglages : un profil n'est pas un choix mais une mesure, il porte
            # son propre numéro de schéma, et l'écrire ne doit pas revalider les
            # neuf réglages. Déclarée avant `/api/barehands/commands` sans
            # ambiguïté : aiohttp apparie sur le chemin complet.
            web.get("/api/barehands/profile", self.get_barehands_profile),
            web.post("/api/barehands/profile", self.save_barehands_profile),
            web.delete("/api/barehands/profile", self.reset_barehands_profile),
            # Canal de commandes du cerveau (Slice 12) : long-poll de la page,
            # demande du serveur MCP, reçu de la page.
            # Traces de diagnostic (Slice 10). Déclarée avant
            # `/api/barehands/commands` pour la même raison que le profil :
            # les chemins littéraux passent avant les préfixes.
            web.post("/api/barehands/traces", self.save_barehands_trace),
            # Résumés du banc d'essai (Slice 08 adaptative, décision 64) :
            # métriques brutes par run, pour l'avant/après après rechargement.
            web.get(BAREHANDS_BENCHMARKS_ROUTE, self.get_barehands_benchmarks),
            web.post(BAREHANDS_BENCHMARKS_ROUTE, self.save_barehands_benchmark),
            web.delete(BAREHANDS_BENCHMARKS_ROUTE, self.clear_barehands_benchmarks),
            web.post("/api/barehands/failures", self.report_barehands_failure),
            web.get("/api/barehands/commands", self.barehands_commands_poll),
            web.post("/api/barehands/commands", self.barehands_command_request),
            web.post("/api/barehands/commands/{command_id}", self.barehands_command_receipt),
            web.get(BAREHANDS_CALIBRATION_SESSION_ROUTE, self.barehands_calibration_session_get),
            web.post(BAREHANDS_CALIBRATION_SESSION_ROUTE, self.barehands_calibration_session_report),
            web.post(BAREHANDS_CALIBRATION_EVENT_ROUTE, self.barehands_calibration_event),
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
            web.post("/api/scene/captures/{capture_id}", self.scene_capture_upload),
            web.get("/api/agent/tasks", self.agent_tasks),
            web.get("/api/agent/tasks/{task_id}/trace", self.agent_task_trace),
            web.post("/api/agent/console/open", self.agent_console_open),
            web.post("/api/agent/console/close", self.agent_console_close),
            web.post("/api/agent/start", self.agent_start),
            web.post("/api/agent/restart", self.agent_restart),
            web.post("/api/agent/kill", self.agent_kill),
            web.post("/api/agent/send", self.agent_send),
            web.post("/api/agent/ask", self.agent_ask),
            # Interne, appelée par Core (Slice 04a ; câblée côté Core en 04b).
            web.post(AGENT_BINDINGS_ROUTE + "/activate", self.agent_binding_activate),
            web.get("/api/agent/notices", self.agent_notices),
            *self.board_routes.routes(),
            web.get("/api/background", self.background_events),
            web.post("/api/background/ack", self.background_ack),
            web.get("/api/conversations", self.conversations_list),
            web.get("/api/conversations/sessions", self.conversation_sessions),
            web.get("/api/conversations/events", self.conversation_events_page),
            web.get("/api/conversations/lookup", self.conversation_events_lookup),
            web.get("/api/conversations/events/{event_id}", self.conversation_event_detail),
            web.get("/api/conversations/events/{event_id}/trace", self.conversation_event_trace),
            web.get("/api/conversations/transcript", self.conversation_transcript),
            web.get("/api/conversations/export", self.conversation_export),
            web.get("/api/conversations/search", self.conversation_search),
        ])
        # Test Lab Catégorie 2 (Slice 10) : ses routes, sa composition et son cycle de
        # vie vivent dans `jarvis/testlab/http.py` (contrat `docs/testlab.md`). Import
        # local : le paquet testlab n'est chargé que si un Control Center existe.
        from jarvis.testlab.http import install_testlab_routes
        install_testlab_routes(self._app, runtime_root=runtime_root, journal=self.journal)
        self._runner: web.AppRunner | None = None

    # ------------------------------------------------------------------ agent

    @property
    def agent(self):  # noqa: ANN201 - ClaudeLocalAgent ou CodexLocalAgent
        """L'agent **foreground** du pool des Boards, pour le CLI choisi.

        Les deux implémentations offrent la même surface. Construit au premier
        appel (et câblé par `_wire_agent`) ; les agents des autres liaisons ne
        passent jamais par ici.
        """
        return self.board_brains.foreground_agent()

    @property
    def _agents(self) -> dict[str, Any]:
        """Agents du foreground par CLI (l'ancien dictionnaire unique, même sens)."""
        return self.board_brains.foreground.agents

    def _build_agent(self, agent_id: str) -> Any:
        if agent_id == "codex":
            return CodexLocalAgent(runtime_root=self.runtime_root, cwd=self.project_root, command="codex")
        return ClaudeLocalAgent(
            runtime_root=self.runtime_root,
            cwd=self.project_root,
            command=os.getenv("JARVIS_CLAUDE_CLI", "claude"),
            permission_mode=os.getenv("JARVIS_CLAUDE_PERMISSION_MODE", DEFAULT_PERMISSION_MODE),
        )

    def _wire_agent(self, entry: BoardBrain, agent_id: str, agent: Any) -> None:
        """Câblage d'un agent du pool, quel que soit son Board (Slice 04a : par entrée)."""
        if self._sessions_root is not None and hasattr(agent, "add_dirs"):
            agent.add_dirs = (self._sessions_root,)
        if entry is not self.board_brains.foreground:
            # Le foreground reçoit ses réglages par `_apply_agent_settings` ;
            # un agent créé pour une autre liaison les reçoit ici, à sa naissance.
            self._configure_agent(agent, agent_id, self._settings())
        if agent_id == "codex":
            # Seul Claude expose des sous-tâches : aucun format Codex n'est
            # vérifié, rien n'est inventé pour lui.
            return
        agent.subtasks.conversation_events = self.conversation_events
        if self.work_ingress is not None:
            # Slice 04b : chaque observation porte le Board de son agent.
            observer = TrackerWorkObserver(agent.subtasks, self.work_ingress.offer,
                                           board_id=lambda: entry.board_id)
            agent.subtasks.subscribe(observer.sync)
            self._work_observers[id(agent)] = observer
            # Un seul abonné côté relais, qui renvoie l'état de **tous** les agents.
            self.work_ingress.on_resync = self._resync_work

    def _resync_work(self) -> int:
        """`work_ingress.on_resync` : tout renvoyer, pour chaque agent du pool.

        Un observateur qui échoue n'empêche pas les autres ; la première erreur
        est relevée après le parcours, pour que le relais la consigne.
        """
        emitted = 0
        errors: list[Exception] = []
        for observer in tuple(self._work_observers.values()):
            try:
                emitted += observer.resync()
            except Exception as exc:  # noqa: BLE001 - relevée ci-dessous, après les autres agents
                errors.append(exc)
        if errors:
            raise errors[0]
        return emitted

    def _forget_agents(self, entry: BoardBrain) -> None:
        """Entrée oubliée par le pool (Session close, CLI suspendu) : son relais part avec elle."""
        for agent in entry.agents.values():
            self._work_observers.pop(id(agent), None)
        if entry.binding is not None:
            # Liaison oubliée : son dernier rapport aussi (reprise QA 04a, borne mémoire).
            self._binding_reports.pop(entry.binding.key, None)

    def _agent_defaults(self, agent_id: str) -> dict[str, Any]:
        from jarvis.runtime.agent_settings import agent_defaults
        return agent_defaults(agent_id)

    def _agent_settings(self, settings: dict[str, Any], agent_id: str) -> dict[str, Any]:
        from jarvis.runtime.agent_settings import resolve_agent_settings
        return resolve_agent_settings(settings, agent_id)

    def _apply_agent_settings(self, settings: dict[str, Any]) -> None:
        """Réglages du CLI choisi : au foreground, et aux agents de même CLI des autres liaisons.

        Effectifs au prochain (re)démarrage de chacun ; un agent de fond qui
        travaille n'est pas redémarré pour autant.
        """
        self._configure_agent(self.agent, self._agent_id, settings)
        for entry in self.board_brains.entries():
            other = entry.agents.get(self._agent_id)
            if entry is not self.board_brains.foreground and other is not None:
                self._configure_agent(other, self._agent_id, settings)

    def _configure_agent(self, agent: Any, agent_id: str, settings: dict[str, Any]) -> None:
        from jarvis.runtime.prompt_overrides import prompt_override_document
        values = self._agent_settings(settings, agent_id)
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
        if hasattr(agent, "barehands_mcp"):
            # Même règle et même moment que l'affichage : effectif au prochain
            # (re)démarrage du cerveau. Éteint, le cerveau est lancé exactement
            # comme avant — ni serveur `jarvis-barehands`, ni consigne : il ne
            # peut donc pas prétendre piloter des mains qui n'existent pas.
            hands_on = bool(barehands.load(settings)["enabled"])
            agent.barehands_mcp = self.barehands_mcp if hands_on else None
            if hands_on and self.barehands_mcp is None and not self._barehands_unconfigured_reported:
                self._barehands_unconfigured_reported = True
                self.journal.emit(
                    "barehands.mcp_unconfigured",
                    "Bare Hands est allumé mais le Control Center ne connaît pas sa propre adresse : "
                    "outils Bare Hands non déclarés au cerveau",
                    level="warning",
                    data={"code": "barehands_mcp_unconfigured"},
                )
        if hasattr(agent, "console_mcp"):
            # **Sans interrupteur, et c'est délibéré.** Les deux blocs
            # au-dessus retirent un serveur quand son réglage est faux ; celui-ci
            # porte précisément ces réglages. Le conditionner à l'un d'eux
            # rendrait l'extinction irréversible pour le cerveau : il pourrait
            # éteindre Bare Hands et n'aurait plus l'outil pour le rallumer.
            agent.console_mcp = self.console_mcp
        if hasattr(agent, "tools_mcp"):
            # Claude et Codex (ARCH §16 E2) ; effectif au prochain lancement du CLI
            # (Claude) ou au prochain tour (Codex, un processus par tour).
            agent.tools_mcp = self.tools_mcp
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
                return
        # Bascule du foreground seulement (06 section B) : Core apprend le CLI réel de sa liaison.
        self._schedule_binding_report(self.board_brains.foreground)

    # ------------------------------------------------------------------ Sessions / Boards (Slice 04a)

    def _spawn_session_task(self, coro, name: str) -> None:  # noqa: ANN001 - coroutine
        task = asyncio.create_task(coro, name=name)
        self._session_tasks.add(task)
        task.add_done_callback(self._session_task_done)

    def _session_task_done(self, task: asyncio.Task[None]) -> None:
        self._session_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self._journal_quietly(
                "board_brain.session_task_failed",
                f"Tâche de liaison Board interrompue ({task.get_name()}) : {type(exc).__name__}: {str(exc)[:200]}",
                "error", {"code": "board_brain_session_task_failed", "task": task.get_name(),
                          "exception_type": type(exc).__name__},
            )

    async def _adopt_core_session(self) -> None:
        """Au démarrage : l'agent en cours devient le foreground de la liaison active de Core.

        Core peut démarrer après nous : on réessaie, délai croissant plafonné,
        jusqu'à ce que le foreground soit lié (par cette adoption ou par une
        activation). Un Core sans Sessions (404 texte) : comportement historique,
        dit une fois. Aucun processus n'est redémarré ici.
        """

        assert self.sessions is not None
        delays = iter(SESSION_ADOPT_RETRY_S)
        reported_failure = False
        # Lu au moins une fois, même si une activation de Core a déjà lié le
        # foreground : la réponse porte aussi le dossier des Sessions à
        # accorder au CLI (Slice 03 session-context), avant le premier tour.
        while True:
            try:
                payload = await self.sessions.current_session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - Core absent, jeton, refus : dit puis réessayé
                if is_unsupported(exc):
                    self.journal.emit("board_brain.sessions_unsupported",
                                      "Core sans Sessions : un seul cerveau, comportement historique",
                                      data={"code": "core_sessions_unsupported"})
                    return
                if not reported_failure:
                    reported_failure = True
                    self.journal.emit(
                        "board_brain.adopt_deferred",
                        f"Liaison foreground de Core illisible pour l'instant : {type(exc).__name__}: {str(exc)[:200]}",
                        level="warning",
                        data={"code": getattr(exc, "code", None) or "core_unreachable",
                              "status": getattr(exc, "status", None), "exception_type": type(exc).__name__},
                    )
                await asyncio.sleep(next(delays, SESSION_ADOPT_RETRY_S[-1]))
                continue
            try:
                binding = BoardConversationBinding.from_payload(
                    payload.get("binding") if isinstance(payload, dict) else None)
            except BoardError as exc:
                self.journal.emit("board_brain.adopt_failed",
                                  f"Liaison foreground de Core hors contrat : {exc}", level="error",
                                  data={"code": exc.code.value})
                return
            self._learn_sessions_root(sessions_root(payload.get("context")), source="sessions_current")
            async with self._agent_lock:
                entry = (self.board_brains.adopt(binding) if self.board_brains.foreground.key is None
                         else self.board_brains.find(binding.conversation_id))
                if entry is not None and entry is self.board_brains.foreground:
                    # Session reprise : le CLI lancé neuf au démarrage reprend le
                    # fil gardé par Core, et reçoit le dossier des Sessions.
                    await self._refresh_foreground_launch(entry, reason="session_resume")
            if entry is not None:
                await self._report_binding(entry)
            return

    def _learn_sessions_root(self, root: Path | None, *, source: str) -> None:
        """Retenir `<data_root>/sessions` de Core et l'accorder aux agents du pool (prochain lancement)."""

        if root is None or root == self._sessions_root:
            return
        self._sessions_root = root
        for entry in self.board_brains.entries():
            for agent in entry.agents.values():
                if hasattr(agent, "add_dirs"):
                    agent.add_dirs = (root,)
        self.journal.emit("agent.workspace_root_learned", "Dossier des Sessions accordé aux cerveaux",
                          data={"sessions_root": str(root), "source": source})

    def _lacks_workspace_grant(self, agent: Any) -> bool:
        """Le CLI vivant n'a pas reçu `--add-dir <sessions_root>` à son lancement (Claude seulement)."""

        if self._sessions_root is None or not hasattr(agent, "launched_add_dirs"):
            return False
        return getattr(agent, "state", None) == "running" and self._sessions_root not in agent.launched_add_dirs

    async def _refresh_foreground_launch(self, entry: BoardBrain, *, reason: str) -> bool:
        """Relancer le CLI du foreground s'il doit reprendre un fil gardé ou recevoir le dossier des Sessions.

        Appelé sous `_agent_lock`. Jamais pendant un tour (`_asks_in_flight`)
        ni pendant un travail (`relaunch` refuse) : remis au prochain point sûr,
        et dit. Un échec de relance est journalisé, jamais levé : le CLI de
        repli de `_bring_up` sert le tour.
        """

        agent = entry.agent
        if agent is None or not (self.board_brains.resume_pending(entry) or self._lacks_workspace_grant(agent)):
            return False
        if self._asks_in_flight > 0:
            self.journal.emit("agent.relaunch_deferred", "Relance du cerveau remise : un tour est en cours",
                              data={"reason": reason, "board_id": entry.board_id})
            return False
        try:
            return await self.board_brains.relaunch(entry, reason=reason)
        except Exception as exc:  # noqa: BLE001 - capture: said here, the next turn starts the CLI again
            self.journal.emit("agent.relaunch_failed", f"Relance du cerveau en échec : {type(exc).__name__}: {exc}"[:400],
                              level="error", data={"code": "agent_relaunch_failed", "reason": reason,
                                                   "board_id": entry.board_id, "exception_type": type(exc).__name__})
            return False

    def _schedule_binding_report(self, entry: BoardBrain) -> None:
        """Rapporter à Core le CLI réel et l'identifiant de reprise, s'ils ont changé."""

        if self.sessions is None or entry.binding is None or self._binding_report_due(entry) is None:
            return
        self._spawn_session_task(self._report_binding(entry), "jarvis-board-binding-report")

    def _binding_report_due(self, entry: BoardBrain) -> tuple[str, str | None] | None:
        if entry.binding is None:
            return None
        report = (entry.agent_cli, agent_session_id(entry.agent) or entry.resume_id(entry.agent_cli))
        return None if self._binding_reports.get(entry.binding.key) == report else report

    async def _report_binding(self, entry: BoardBrain) -> None:
        """`POST /v1/sessions/bindings/report`. Ne lève pas : un échec est journalisé et réessayé au prochain tour."""

        report = self._binding_report_due(entry)
        if self.sessions is None or report is None or entry.binding is None:
            return
        binding = entry.binding
        try:
            await self.sessions.report_binding_agent(
                jarvis_session_id=binding.jarvis_session_id, board_id=binding.board_id,
                agent_cli=report[0], agent_session_id=report[1],
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture : un rapport raté se refait au tour suivant
            if is_unsupported(exc):
                # Core antérieur : il ne l'apprendra jamais, inutile de réessayer.
                self._binding_reports[binding.key] = report
                return
            self.journal.emit(
                "board_brain.report_failed",
                f"CLI de la liaison non rapporté à Core : {type(exc).__name__}: {str(exc)[:200]}",
                level="warning",
                data={"code": getattr(exc, "code", None) or "core_unreachable", "status": getattr(exc, "status", None),
                      "board_id": binding.board_id, "jarvis_session_id": binding.jarvis_session_id},
            )
            return
        self._binding_reports[binding.key] = report
        self.journal.emit("board_brain.reported", "CLI de la liaison rapporté à Core",
                          data={"board_id": binding.board_id, "jarvis_session_id": binding.jarvis_session_id,
                                "agent_cli": report[0], "has_agent_session_id": report[1] is not None})

    async def _restart_in_new_session(self) -> dict[str, Any] | None:
        """`/api/agent/restart {new_conversation: true}` avec un Core à Sessions (Slice 04a).

        Core ouvre une Session neuve (`POST /v1/sessions/new`) ; sa liaison
        reçoit un CLI **neuf** ; l'ancien foreground est rétrogradé, jamais tué
        (ses sous-agents finissent). Rend `None` quand Core ne peut pas : le
        comportement historique s'applique alors (redémarrage sans reprise).
        """

        assert self.sessions is not None
        try:
            # Reprise QA 04a (S2) : la transaction de Core active le CLI neuf sur
            # ce Control Center (`/api/agent/bindings/activate`) **avant** de
            # valider la Session ; un échec laisse les deux côtés inchangés.
            payload = await self.sessions.new_session()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - old Core: historical restart; any other refusal: surfaced
            if is_unsupported(exc):
                self.journal.emit("agent.restart.session_unavailable",
                                  "Core sans Sessions : conversation neuve sans nouvelle Session",
                                  data={"code": "core_sessions_unsupported", "status": getattr(exc, "status", None)})
                return None
            if isinstance(exc, asyncio.TimeoutError):
                # Requête partie, pas de réponse : Core peut encore valider (QA 04b, S2).
                self.journal.emit(
                    "agent.restart.session_timeout",
                    "Core n'a pas répondu à la nouvelle Session dans le délai : issue inconnue",
                    level="error", data={"code": "core_transition_timeout"},
                )
                raise RuntimeError("Nouvelle Session sans réponse de Core (core_transition_timeout) : "
                                   "elle peut encore être validée, relire la Session courante") from exc
            code = getattr(exc, "code", None) or "core_unreachable"
            self.journal.emit(
                "agent.restart.session_failed",
                f"Nouvelle Session refusée par Core, rien n'a changé : {type(exc).__name__}: {str(exc)[:200]}",
                level="error", data={"code": code, "status": getattr(exc, "status", None)},
            )
            raise RuntimeError(f"Nouvelle Session impossible ({code}) : {str(exc)[:200]}") from exc
        try:
            binding = BoardConversationBinding.from_payload(
                payload.get("binding") if isinstance(payload, dict) else None)
        except BoardError as exc:
            self.journal.emit("agent.restart.session_invalid",
                              f"Nouvelle Session de Core hors contrat : {exc}", level="error",
                              data={"code": exc.code.value})
            return None
        entry = self.board_brains.foreground
        if entry.key != binding.conversation_id:
            # Core sans hôte (il n'a pas pu nous activer) : le CLI neuf est démarré ici.
            async with self._agent_lock:
                entry = await self.board_brains.start_fresh(binding, previous_closed=True)
        await self._report_binding(entry)
        return {**entry.agent.snapshot(), "board_brain": entry.to_payload()}

    async def _realign_foreground(self, conversation_id: str) -> BoardBrain | None:
        """Un tour vise une conversation inconnue du pool : Core a peut-être changé de Session sans nous (Slice 04b).

        Cas visé : Core a redémarré (nouvelle Session, conversation neuve) et
        n'a pas pu nous activer (`core.board.host_align_deferred`), ou nous
        avons redémarré entre-temps. On relit `GET /v1/sessions/current` ; si
        la conversation du tour est bien celle de la liaison active, elle est
        activée (CLI neuf ou repris) avant que le tour parte. Sinon, ou si Core
        ne répond pas, rien ne change : le foreground sert le tour, comme avant
        les Boards, et c'est journalisé. Ne lève pas.
        """

        foreground = self.board_brains.foreground
        if self.sessions is None or foreground.key is None or foreground.key == conversation_id:
            return None
        try:
            payload = await self.sessions.current_session()
            binding = BoardConversationBinding.from_payload(
                payload.get("binding") if isinstance(payload, dict) else None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: the turn is served by the foreground, said here
            if not is_unsupported(exc):
                self.journal.emit("board_brain.realign_failed",
                                  f"Liaison active de Core illisible : {type(exc).__name__}: {str(exc)[:200]}",
                                  level="warning", data={"code": getattr(exc, "code", None) or "core_unreachable",
                                                         "conversation_id": conversation_id})
            return None
        if binding.conversation_id != conversation_id:
            return None
        try:
            async with self._agent_lock:
                entry = await self.board_brains.activate(binding)
        except (BoardError, RuntimeError) as exc:
            self.journal.emit("board_brain.realign_failed",
                              f"Cerveau de la liaison active non activé : {exc}", level="error",
                              data={"code": getattr(getattr(exc, "code", None), "value", None)
                                    or BoardErrorCode.BOARD_ACTIVATION_FAILED.value,
                                    "conversation_id": conversation_id, "board_id": binding.board_id})
            return None
        self.journal.emit("board_brain.realigned", "Foreground réaligné sur la liaison active de Core",
                          data={"conversation_id": conversation_id, "board_id": binding.board_id,
                                "jarvis_session_id": binding.jarvis_session_id,
                                "previous_conversation_id": foreground.key})
        await self._report_binding(entry)
        return entry

    async def agent_binding_activate(self, request: web.Request) -> web.Response:
        """`POST /api/agent/bindings/activate` (interne, Core -> Control Center).

        Corps : la liaison sérialisée (`BoardConversationBinding.to_payload()`).
        Rend `{ok, agent_cli, agent_session_id, lifecycle, conversation_id,
        board_id, jarvis_session_id}` : Core enregistre `agent_session_id` sur la
        liaison. Refus : 400 `invalid_binding`, 409 `session_closed`, 413 corps
        trop gros, 502 `board_activation_failed` (CLI impossible à démarrer ;
        rien n'a changé, l'ancien foreground l'est toujours).
        """

        try:
            raw = await scene_wire.read_bounded_body(request, AGENT_BINDING_MAX_BYTES)
        except scene_wire.SceneBodyTooLarge:
            return self._binding_error(413, BoardErrorCode.INVALID_BINDING.value,
                                       f"binding body exceeds {AGENT_BINDING_MAX_BYTES} bytes")
        try:
            binding = BoardConversationBinding.from_payload(
                loads_strict_json(raw, invalid_message="binding body must be JSON"))
        except BoardError as exc:
            return self._binding_error(exc.status, exc.code.value, str(exc))
        except ValueError as exc:
            return self._binding_error(400, BoardErrorCode.INVALID_BINDING.value, str(exc))
        try:
            async with self._agent_lock:
                previous = self.board_brains.foreground
                entry = await self.board_brains.activate(binding)
        except BoardError as exc:
            self.journal.emit("board_brain.activation_refused", f"Activation refusée : {exc}", level="warning",
                              data={"code": exc.code.value, "board_id": binding.board_id,
                                    "jarvis_session_id": binding.jarvis_session_id})
            return self._binding_error(exc.status, exc.code.value, str(exc))
        except RuntimeError as exc:
            self.journal.emit(
                "board_brain.activation_failed",
                f"Cerveau du Board non démarré : {exc}", level="error",
                data={"code": BoardErrorCode.BOARD_ACTIVATION_FAILED.value, "board_id": binding.board_id,
                      "jarvis_session_id": binding.jarvis_session_id, "agent_cli": self._agent_id},
            )
            return self._binding_error(502, BoardErrorCode.BOARD_ACTIVATION_FAILED.value, str(exc))
        report = self._binding_report_due(entry)
        if report is not None and entry.binding is not None:
            # Core lit ces valeurs dans cette réponse : pas de rapport en double.
            self._binding_reports[entry.binding.key] = report
        payload = entry.to_payload()
        # Slice 04b : Core enregistre ce que l'ancien foreground est devenu
        # (`background_running` s'il travaille, `suspended` sinon).
        demoted = ({"conversation_id": previous.key, "lifecycle": previous.lifecycle.value}
                   if previous is not entry and previous.key is not None else None)
        return web.json_response({"ok": True, **payload, "previous": demoted})

    @staticmethod
    def _binding_error(status: int, code: str, message: str) -> web.Response:
        return web.json_response({"ok": False, "code": code, "error": message}, status=status)

    # ------------------------------------------------------------------ HTTP

    @web.middleware
    async def _origin_guard(self, request: web.Request, handler):  # noqa: ANN001
        if any(request.path == route or request.path.startswith(route + "/") for route in READ_GUARDED_ROUTES):
            # Conversation history (user transcripts) and Test Lab evidence are
            # read-sensitive: every method is guarded, and the Host must be loopback
            # too (DNS rebinding).
            refusal = _loopback_refusal(request.headers.get("Origin"), request.headers.get("Host"),
                                        request.headers.get("Sec-Fetch-Site"))
            if refusal is not None:
                if request.path.startswith((BAREHANDS_COMMANDS_ROUTE_PREFIX, BAREHANDS_CALIBRATION_SESSION_ROUTE,
                                            BAREHANDS_BENCHMARKS_ROUTE)):
                    # Le canal garde **sa** forme de refus, ici aussi : code stable
                    # dans le corps et dans l'en-tête, sinon le serveur MCP n'a plus
                    # de code à nommer. C'est la seule raison pour laquelle ce
                    # préfixe n'hérite pas du refus générique ci-dessous.
                    return self._barehands_error(403, FORBIDDEN_ORIGIN, refusal)
                return web.json_response({"ok": False, "code": "forbidden_origin", "error": refusal}, status=403)
        elif request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("Origin")
            if origin:
                try:
                    host = urlparse(origin).hostname
                except ValueError:
                    host = None
                    # La route qui sait rendre un refus **codé** le rend :
                    # `host = None` retombe plus bas sur sa propre forme d'erreur
                    # au lieu d'un texte brut sans code. Le canal de commandes
                    # n'est plus cité ici : toutes ses méthodes passent par
                    # `READ_GUARDED_ROUTES` ci-dessus, qui est strictement plus
                    # strict (Host de bouclage et `Sec-Fetch-Site` compris) et
                    # rend déjà `_barehands_error`.
                    if not request.path.startswith(SCENE_CAPTURE_ROUTE_PREFIX):
                        raise web.HTTPForbidden(text="invalid origin")
                if host not in LOOPBACK_HOSTS:
                    if request.path.startswith(SCENE_CAPTURE_ROUTE_PREFIX):
                        # Même forme d'erreur que les autres refus de la route de capture.
                        return self._scene_error(403, "forbidden_origin", "forbidden origin")
                    raise web.HTTPForbidden(text="forbidden origin")
        return await handler(request)

    @web.middleware
    async def _mcp_json_errors(self, request: web.Request, handler):  # noqa: ANN001
        """Sous `/api/mcp` : un chemin inconnu ou une méthode absente répond en JSON codé, pas en texte brut.

        Seulement ce préfixe : les autres routes gardent la forme d'erreur
        d'aiohttp dont leurs clients dépendent.
        """

        if not (request.path == MCP_ROUTE_PREFIX or request.path.startswith(MCP_ROUTE_PREFIX + "/")):
            return await handler(request)
        if McpPluginRoutes.owns(request.path):
            # Plugins et retour OAuth (ARCH §16 E8) : leurs 404/405 sont rendus
            # par `mcp_plugin_routes.py` ; « lecture seule » et `mcp_tool_unknown`
            # restent au catalogue.
            try:
                return await handler(request)
            except (web.HTTPMethodNotAllowed, web.HTTPNotFound) as exc:
                return McpPluginRoutes.refusal(exc)
        try:
            return await handler(request)
        except web.HTTPMethodNotAllowed as exc:
            return web.json_response(
                {"ok": False, "code": "method_not_allowed", "error": "the MCP catalog is read-only (GET)"},
                status=405, headers={"Allow": ", ".join(sorted(exc.allowed_methods))},
            )
        except web.HTTPNotFound:
            return web.json_response(
                {"ok": False, "code": mcp_catalog.TOOL_UNKNOWN, "error": "unknown MCP tool"}, status=404
            )

    async def start(self, *, host: str = "127.0.0.1", port: int = 17654) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self._apply_agent_settings(self._settings())
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        await web.TCPSite(self._runner, host, port).start()
        self.journal.emit("ui.start", "Jarvis Control Center started", data={"host": host, "port": port})
        if self.work_ingress is not None:
            self.work_ingress.start()
        if self.conversation_events is not None:
            self.conversation_events.start()
        # Réconciliation du mode d'interaction (Slice 02). Deux temps, et
        # **aucun des deux n'attend le réseau** : un Core qui accepte le TCP
        # puis se tait retarderait sinon le démarrage du Control Center de
        # plusieurs secondes, ce qui est exactement ce qu'un réglage n'a pas le
        # droit de faire.
        #
        # 1. dire tout de suite, et localement, si le réglage enregistré n'est
        #    pas celui qui s'appliquera (illisible, ou réservé) ;
        # 2. armer le rejeu vers Core en tâche de fond. Core peut démarrer
        #    après nous : l'échec est journalisé, jamais levé, et `/api/status`
        #    réarme dès qu'un Core neuf (révision 0) répond.
        self.report_interaction_mode_preference(self._settings(), source="startup")
        self._schedule_interaction_mode_replay("startup")
        try:
            await self.agent.start()
        except RuntimeError as exc:
            self.journal.emit("agent.unavailable", str(exc), level="error")
        if self.sessions is not None:
            # Slice 04a : l'agent qui tourne devient le foreground de la liaison
            # active de Core, sans redémarrer. En tâche de fond : Core peut
            # démarrer après nous, et le démarrage n'attend jamais le réseau.
            self._spawn_session_task(self._adopt_core_session(), "jarvis-board-brain-adopt")

    async def stop(self) -> None:
        # Avant tout le reste : un appel du cerveau qui attend une page rend la
        # main tout de suite avec sa cause, au lieu d'attendre son échéance
        # pendant que le serveur se ferme sous lui.
        self.barehands_commands.close()
        self.barehands_calibration.close()
        self._calibration_event_next = None
        analysis, self._calibration_event_task = self._calibration_event_task, None
        if analysis is not None and not analysis.done():
            analysis.cancel()
        replay, self._interaction_mode_replay = self._interaction_mode_replay, None
        if replay is not None and not replay.done():
            # Elle dort peut-être son délai de reprise : l'arrêt ne l'attend pas.
            replay.cancel()
        for task in tuple(self._session_tasks):
            task.cancel()
        await asyncio.gather(*self._session_tasks, return_exceptions=True)
        await self.board_routes.close()
        # Tous les agents du pool, pas seulement le foreground : ce sont des
        # processus enfants de ce Control Center (limite V1, `docs/boards.md`).
        await self.board_brains.aclose()
        if self.sessions is not None:
            try:
                await self.sessions.close()
            except Exception:  # noqa: BLE001 - argued: shutdown must never hang on a closing HTTP session
                pass
        if self.work_ingress is not None:
            # Après les agents : leurs sous-tâches interrompues partent vers
            # Core dans une dernière tentative bornée.
            await self.work_ingress.aclose()
        if self.conversation_events is not None:
            # Après les agents, pour la même raison : leurs sous-agents
            # interrompus sont des fins de span à remettre à Core.
            await self.conversation_events.aclose()
        # Avant l'arrêt du serveur : une lecture longue en cours vers Core est
        # interrompue au lieu de retenir l'arrêt jusqu'à son délai.
        await self.conversation_event_view.aclose()
        if self.work_view is not None:
            await self.work_view.aclose()
        if self.live_view is not None:
            await self.live_view.aclose()
        if self.scene_view is not None:
            await self.scene_view.aclose()
        titles, self._board_titles_task = self._board_titles_task, None
        if titles is not None and not titles.done():
            titles.cancel()
        # Après les agents (leurs sous-agents interrompus sont dans la trace) :
        # la dernière position et les derniers non-lus sont écrits.
        self._advance_background(force_save=True)
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
            BAREHANDS_CONTRACTS_SCRIPT_MARKER,
            page.with_name(BAREHANDS_CONTRACTS_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            BAREHANDS_ADAPTIVE_SCRIPT_MARKER,
            page.with_name(BAREHANDS_ADAPTIVE_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            BAREHANDS_HAND_ART_SCRIPT_MARKER,
            page.with_name(BAREHANDS_HAND_ART_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            BAREHANDS_TARGET_SCRIPT_MARKER,
            page.with_name(BAREHANDS_TARGET_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            BAREHANDS_CALIBRATION_SCRIPT_MARKER,
            page.with_name(BAREHANDS_CALIBRATION_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            BAREHANDS_RECORDER_SCRIPT_MARKER,
            page.with_name(BAREHANDS_RECORDER_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            BAREHANDS_CALIBRATION_AGENT_SCRIPT_MARKER,
            page.with_name(BAREHANDS_CALIBRATION_AGENT_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            BAREHANDS_BENCHMARK_SCRIPT_MARKER,
            page.with_name(BAREHANDS_BENCHMARK_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            BAREHANDS_BENCHMARK_UI_SCRIPT_MARKER,
            page.with_name(BAREHANDS_BENCHMARK_UI_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            BAREHANDS_SCRIPT_MARKER, page.with_name(BAREHANDS_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            BAREHANDS_HUD_SCRIPT_MARKER,
            page.with_name(BAREHANDS_HUD_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            BAREHANDS_COMMANDS_SCRIPT_MARKER,
            page.with_name(BAREHANDS_COMMANDS_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            INTERACTION_MODE_SCRIPT_MARKER,
            page.with_name(INTERACTION_MODE_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            BOARDS_SCRIPT_MARKER,
            page.with_name(BOARDS_SCRIPT_FILE).read_text(encoding="utf-8"),
        )
        html = html.replace(
            PRESENTATION_ATTENTION_SCRIPT_MARKER,
            page.with_name(PRESENTATION_ATTENTION_SCRIPT_FILE).read_text(encoding="utf-8"),
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
            SCENE_CAPTURE_SCRIPT_MARKER, page.with_name(SCENE_CAPTURE_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            SCENE_VIEW_SCRIPT_MARKER, page.with_name(SCENE_VIEW_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            SCENE_PAGE_SCRIPT_MARKER, page.with_name(SCENE_PAGE_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            SCENE_SETTINGS_SCRIPT_MARKER, page.with_name(SCENE_SETTINGS_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            TIMELINE_SCRIPT_MARKER, page.with_name(TIMELINE_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            TESTLAB_SCRIPT_MARKER, page.with_name(TESTLAB_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            MCP_INSPECTOR_SCRIPT_MARKER, page.with_name(MCP_INSPECTOR_SCRIPT_FILE).read_text(encoding="utf-8")
        )
        html = html.replace(
            MCP_PLUGINS_SCRIPT_MARKER, page.with_name(MCP_PLUGINS_SCRIPT_FILE).read_text(encoding="utf-8")
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
        # Les deux lectures de Core de ce battement partent **ensemble** : en
        # série, le pire cas additionnait leurs délais sur le seul pouls de la
        # page. Ni l'une ni l'autre ne lève, donc rien à récupérer ici.
        # Le Board actif est lu **une fois** par battement (`GET /v1/boards/active`)
        # et sert au mode d'interaction comme au bloc `boards` (Slice 06).
        async def mode_and_boards() -> tuple[dict[str, Any], dict[str, Any]]:
            active = await self._read_active_board()
            return await self._interaction_mode_status(settings, active=active), self._boards_status(active)

        live, (interaction_mode, boards) = await asyncio.gather(
            self._live_status(settings, voice_online=voice_online),
            mode_and_boards(),
        )
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
            # Interrupteur Bare Hands (Slice 12) : la page n'ouvre son canal de
            # commandes que s'il est vrai. Même raison et même battement que
            # `scene` juste au-dessus — c'est ce qui évite une seconde boucle
            # permanente dans la page pour apprendre un booléen (constat F1 :
            # `/api/status` ne portait aucun champ Bare Hands).
            "barehands": {"enabled": bool(barehands.load(settings)["enabled"])},
            # Mode d'interaction (Slice 02) : la valeur **effective** que Core
            # tient, sa révision, et la préférence enregistrée à côté. Les deux
            # sont nommées séparément parce qu'elles divergent sur exactement un
            # cas — un `meeting` enregistré, réservé et donc jamais effectif —
            # et que n'en publier qu'une ferait disparaître REUNION de l'écran
            # (Décision 02) ou ferait croire qu'il se comporte (Décision 14).
            "interaction_mode": interaction_mode,
            # Board actif, Session et liaisons vivantes (handoff board-session,
            # Slice 06) : le contrôle Boards du haut-droit suit ce bloc, donc
            # une bascule faite par la voix ou par MCP s'affiche au battement
            # suivant. Voir `_boards_status`.
            "boards": boards,
            # Bornes que la page affiche (Slice 08, reprise QA) : délai réel de
            # l'arrêt d'un job à travers ce Control Center, `null` sans Core.
            "scene_limits": {
                "job_cancel_timeout_s": self.scene_view.job_cancel_deadline_s if self.scene_view is not None else None,
            },
            # Pertes visibles (Slice 04) : compteurs du relais des Conversation
            # Events de ce processus ; ceux de Core sont dans `GET /v1/health`.
            "conversation_events": self._conversation_event_counters(),
        })

    async def _interaction_mode_status(self, settings: dict[str, Any], *,
                                       active: _ActiveBoardRead | None = None) -> dict[str, Any]:
        """Mode effectif + préférence + modes annoncés, pour `/api/status`.

        **Lecture seule.** Le sondage bat chaque seconde et porte tout
        l'affichage de la page : il ne lève pas, et il n'écrit pas non plus.
        Une écriture sur ce chemin rejouait la préférence vers Core à chaque
        battement tant qu'elle échouait, et remplissait le journal d'un
        avertissement par seconde. Le rattrapage est armé ici mais exécuté
        **à côté**, par `_schedule_interaction_mode_replay`.

        Core injoignable, la vue rend le repli local **nommé**
        (`source: "settings"`, `core_reachable: false`, un `error.code`), jamais
        une valeur présentée comme vivante.
        """

        stored = await self._board_stored_mode(active) or interaction_mode_settings.load(settings)
        live = await self.interaction_mode_view.read(stored)
        # Révision 0 sur un Core joignable = il n'a jamais entendu parler de la
        # préférence (démarré après nous, ou redémarré). Le rattrapage part en
        # tâche de fond ; ce battement-ci rend ce que Core dit aujourd'hui.
        if live["core_reachable"] and live["revision"] == 0:
            self._schedule_interaction_mode_replay("core_restart")
        return {
            **live,
            "stored": stored.value,
            "stored_label": stored.label,
            # Catalogue constant : `supported_modes()` directement, plutôt que
            # `describe()`, qui relirait `inspect` + `load` + `behaving` à
            # chaque seconde pour en extraire une valeur qui ne change jamais.
            "modes": interaction_mode_settings.supported_modes(),
        }

    def _schedule_interaction_mode_replay(self, source: str) -> None:
        """Armer un rattrapage hors du chemin de lecture, au plus un à la fois.

        Le sondage ne peut pas attendre une écriture, et un Core qui refuse
        pour toujours ne doit pas produire une tentative par seconde. Une seule
        tâche vit à la fois, et elle s'octroie un délai avant de réessayer.
        """

        if self._interaction_mode_replay is not None and not self._interaction_mode_replay.done():
            return
        if interaction_mode_settings.behaving(self._settings()) is DEFAULT_INTERACTION_MODE:
            # Rien à rejouer : Core est déjà en mode assistant à la révision 0.
            return
        self._interaction_mode_replay = asyncio.create_task(
            self._replay_interaction_mode(source), name="jarvis-interaction-mode-replay",
        )

    async def _read_active_board(self) -> _ActiveBoardRead:
        """`GET /v1/boards/active`, une fois par battement de `/api/status`. Ne lève pas.

        Core sans Boards (404 texte) est retenu pour la vie du processus ; un
        échec est dit (limité, `interaction.mode.board_unknown`) et le battement
        suivant réessaie.
        """

        if self.sessions is None:
            return _ActiveBoardRead(None, {"code": "core_unconfigured",
                                           "message": "the control center does not know Core"}, False)
        if self._core_boards_unsupported:
            return _ActiveBoardRead(None, {"code": "core_boards_unsupported",
                                           "message": "Core has no Boards"}, False)
        try:
            payload = await asyncio.wait_for(self.sessions.active_board(), timeout=1.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: the status falls back to the global preference, said
            if is_unsupported(exc):
                self._core_boards_unsupported = True
                return _ActiveBoardRead(None, {"code": "core_boards_unsupported", "message": "Core has no Boards"},
                                        False)
            code = getattr(exc, "code", None) or CORE_UNREACHABLE
            self._report_interaction_mode(
                "interaction.mode.board_unknown",
                f"Board actif de Core illisible : {type(exc).__name__}: {str(exc)[:160]}",
                level="warning",
                data={"code": code, "status": getattr(exc, "status", None)},
            )
            return _ActiveBoardRead(None, {"code": code, "message": f"{type(exc).__name__}: {str(exc)[:160]}"}, True)
        board = payload.get("board") if isinstance(payload, dict) else None
        if not isinstance(board, dict):
            return _ActiveBoardRead(None, {"code": "http_error", "message": "Core answered without a board"}, True)
        return _ActiveBoardRead(board, None, True)

    async def _board_stored_mode(self, active: _ActiveBoardRead | None = None) -> InteractionMode | None:
        """Mode enregistré sur le Board actif de Core, quand ce Board l'a choisi (reprise QA 04a, S3).

        Depuis les Boards, la préférence vit sur le Board : l'afficher depuis le
        réglage global montrait une divergence « CHOISI » périmée après chaque
        changement. `None` : Core sans Boards (retenu pour la vie du processus),
        Board `unset` (le réglage global reste l'entrée de migration), ou lecture
        en échec (dit, limité ; le battement suivant réessaie). Ne lève pas.
        `active` : la lecture déjà faite par ce battement (`status`), sinon relue.
        """

        if active is None:
            active = await self._read_active_board()
        board = active.board
        if board is None or board.get("interaction_mode_origin") in (None, InteractionModeOrigin.UNSET.value):
            return None
        self._core_has_boards = True
        try:
            return InteractionMode(board.get("interaction_mode"))
        except ValueError:
            return None  # argued: an out-of-contract Board is reported by `_core_boards_own_interaction_mode`

    def _boards_status(self, active: _ActiveBoardRead) -> dict[str, Any]:
        """Bloc `boards` de `/api/status` (handoff board-session, Slice 06). Ne lève pas, n'écrit rien.

        - `available` : Core a des Boards et ce Control Center le joint ;
        - `active` : `{board_id, title}` du Board actif selon Core, `null` si la
          lecture a échoué (`error` dit pourquoi) ;
        - `jarvis_session_id` : Session de la liaison foreground du pool de ce
          Control Center (celle qui parle) ;
        - `bindings` : les liaisons vivantes du pool, `{board_id, lifecycle,
          agent_cli, closed}` — `background_running` dit qu'un Board quitté
          travaille encore.
        """

        board = active.board
        self._remember_board_title(board)
        foreground = self.board_brains.foreground
        return {
            "available": active.supported and board is not None,
            "active": {"board_id": board.get("board_id"), "title": board.get("title")} if board else None,
            "jarvis_session_id": foreground.jarvis_session_id,
            "bindings": [
                {"board_id": row["board_id"], "lifecycle": row["lifecycle"], "agent_cli": row["agent_cli"],
                 "closed": row["closed"]}
                for row in self.board_brains.snapshot() if row.get("board_id")
            ],
            "error": active.error,
        }

    async def _core_boards_own_interaction_mode(self) -> bool | None:
        """Le mode d'interaction appartient-il au Board actif de Core ? (Slice 04a, reprise QA Slice 02)

        - `False` : Core sans Boards (pas de transport, 404 texte), ou Board
          actif encore `unset` : la préférence globale est l'entrée de migration
          et se rejoue (une fois : Core la marque `migrated`) ;
        - `True` : le Board a son mode (`migrated`/`user`) : plus de rejeu, plus
          d'écriture de la préférence globale — sinon chaque redémarrage de Core
          fait basculer le mode vivant deux fois ;
        - `None` : indéterminé (Core injoignable, réponse hors contrat).
        """

        if self.sessions is None:
            return False
        try:
            payload = await asyncio.wait_for(self.sessions.active_board(), timeout=5.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - dit (limité), puis décidé par l'appelant
            if is_unsupported(exc):
                return False
            self._report_interaction_mode(
                "interaction.mode.board_unknown",
                f"Board actif de Core illisible : {type(exc).__name__}: {str(exc)[:160]}",
                level="warning",
                data={"code": getattr(exc, "code", None) or CORE_UNREACHABLE, "status": getattr(exc, "status", None)},
            )
            return None
        board = payload.get("board") if isinstance(payload, dict) else None
        origin = board.get("interaction_mode_origin") if isinstance(board, dict) else None
        if origin not in {item.value for item in InteractionModeOrigin}:
            self._report_interaction_mode(
                "interaction.mode.board_unknown", "Board actif de Core hors contrat (origine du mode absente)",
                level="warning", data={"code": "invalid_board_snapshot"},
            )
            return None
        self._core_has_boards = True
        return origin != InteractionModeOrigin.UNSET.value

    async def _replay_interaction_mode(self, source: str) -> None:
        try:
            owned = await self._core_boards_own_interaction_mode()
            if owned is None:
                # Indéterminé : ne rien rejouer plutôt que risquer une bascule ;
                # le prochain sondage réarmera.
                pass
            elif owned:
                if not self._replay_retired_reported:
                    # Une fois par processus : le sondage réarme ce chemin toutes les 30 s.
                    self._replay_retired_reported = True
                    self.journal.emit(
                        "interaction.mode.replay_retired",
                        "Le Board actif porte son mode d'interaction : préférence globale non rejouée",
                        data={"source": source},
                    )
            else:
                await self._reconcile_interaction_mode(self._settings(), source=source)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - une tâche de fond ne remonte nulle part
            self.journal.emit(
                "interaction.mode.reconcile_failed",
                f"Rattrapage du mode d'interaction interrompu : {type(exc).__name__}: {exc}",
                level="error", data={"code": "interaction_mode_replay_failed", "source": source},
            )
        # Délai avant qu'un prochain sondage puisse en armer un autre : sans
        # lui, un Core joignable mais qui refuse produirait une tentative par
        # battement de page.
        await asyncio.sleep(INTERACTION_MODE_REPLAY_BACKOFF_S)

    async def _reconcile_interaction_mode(
        self, settings: dict[str, Any], *, source: str, fallback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Rejouer la préférence enregistrée vers Core. Ne bloque jamais, ne lève jamais.

        Le démarrage l'appelle une fois ; le statut arme un rattrapage quand un
        Core neuf apparaît. La valeur envoyée est la lecture de
        **comportement** : un `meeting` enregistré reste affiché, mais on ne
        demande jamais à Core un mode qui n'a aucun comportement — il le
        refuserait, à juste titre.

        C'est aussi **ici** que se dit un réglage illisible. Core ne voit jamais
        la valeur brute du disque (elle est normalisée avant de partir), donc
        c'est le propriétaire de la persistance qui doit nommer la perte :
        sinon « démarré en SIMPLE » et « son réglage était illisible » laissent
        exactement la même trace.
        """

        behaving = interaction_mode_settings.behaving(settings)
        stored = interaction_mode_settings.load(settings)
        self.report_interaction_mode_preference(settings, source=source)
        try:
            live = await self.interaction_mode_view.request(behaving, source=source)
        except InteractionModeUnavailable as exc:
            self._report_interaction_mode(
                "interaction.mode.reconcile_failed",
                f"Mode d'interaction {behaving.label} non appliqué à Core ({source}) : {exc}",
                level="warning",
                data={"code": exc.code, "mode": behaving.value, "source": source},
            )
            return fallback if fallback is not None else await self.interaction_mode_view.read(stored)
        self.journal.emit(
            "interaction.mode.reconciled",
            f"Mode d'interaction {behaving.label} rejoué vers Core ({source})",
            data={"mode": behaving.value, "revision": live["revision"], "source": source},
        )
        return live

    def report_interaction_mode_preference(self, settings: dict[str, Any], *, source: str) -> None:
        """Dire qu'un réglage enregistré n'est pas celui qui va s'appliquer.

        Core ne voit jamais la valeur brute du disque : le Control Center la lit
        et la normalise avant de la lui demander. C'est donc **ici**, chez le
        propriétaire de la persistance, que la perte se nomme — sinon
        « démarré en SIMPLE » et « son réglage était illisible » laissent
        exactement la même trace, et la seconde est une panne.

        Purement local, sans E/S : le démarrage peut l'appeler avant même de
        savoir si Core existe, et il le fait, parce qu'un réglage abîmé doit se
        voir même quand il n'y a rien à rejouer.
        """

        seen = interaction_mode_settings.inspect(settings)
        stored = interaction_mode_settings.load(settings)
        behaving = interaction_mode_settings.behaving(settings)
        # Les deux branches nomment **ce qui était enregistré**. Sans cela,
        # `fromage` et `gruyere` laissaient la même ligne, et la seule façon de
        # les distinguer était `GET /api/interaction-mode`, que rien n'appelle
        # avant la Slice 03. Une valeur de mode est un jeton court choisi par
        # l'opérateur, pas du contenu utilisateur — et elle est bornée comme
        # partout ailleurs ici, pour qu'un fichier trafiqué ne remplisse pas le
        # journal.
        stored_value = _short(seen["stored_value"])
        if seen["invalid_value"] or seen["unreadable"]:
            self._report_interaction_mode(
                "interaction.mode.defaulted",
                "Préférence de mode d'interaction illisible "
                f"({stored_value!r}) : mode SIMPLE appliqué",
                level="warning",
                data={"code": "interaction_mode_unreadable", "source": source,
                      "stored_value": stored_value,
                      "stored_schema_version": seen["stored_schema_version"]},
            )
        elif stored is not behaving:
            self._report_interaction_mode(
                "interaction.mode.defaulted",
                f"Le mode {stored.label} est enregistré mais n'a aucun comportement : mode SIMPLE appliqué",
                level="warning",
                data={"code": "interaction_mode_not_implemented", "source": source,
                      "mode": stored.value, "stored_value": stored_value},
            )

    def _report_interaction_mode(self, kind: str, message: str, *, level: str, data: dict[str, Any]) -> None:
        """Au plus une ligne par cause et par fenêtre, avec le nombre de tues.

        Le rattrapage repasse tant que Core refuse. Le même `ReportThrottle`
        que les acteurs de scène refusés sert ici : la panne reste visible, la
        trace reste lisible.
        """

        suppressed = self._interaction_mode_reports.admit(f"{kind}:{data.get('code')}")
        if suppressed is None:
            return
        self.journal.emit(
            kind, message + (f" ({suppressed} occurrences tues)" if suppressed else ""),
            level=level, data={**data, "suppressed": suppressed},
        )

    def _conversation_event_counters(self) -> dict[str, Any] | None:
        forwarder = self.conversation_events
        if forwarder is None:
            return None
        return {**asdict(forwarder.counters), "pending": forwarder.pending_count}

    #: Une position de trace qui avance sans nouvelle entrée n'est écrite
    #: qu'au plus toutes les `BACKGROUND_OFFSET_SAVE_S` secondes. Sans perte :
    #: les lignes relues après un arrêt brutal sont celles qui n'ont produit
    #: aucune entrée (sinon l'état aurait été écrit aussitôt).
    BACKGROUND_OFFSET_SAVE_S = 10.0
    #: Relecture de la liste des Boards (titres des alertes) au plus toutes les…
    BOARD_TITLES_REFRESH_S = 30.0

    def _board_of_conversation(self, conversation_id: str) -> str | None:
        """Board d'une conversation d'après les liaisons du pool (repli quand la trace n'en nomme pas)."""

        for row in self.board_brains.snapshot():
            if row.get("conversation_id") == conversation_id:
                return row.get("board_id")
        return None

    def _advance_background(self, *, force_save: bool = False) -> None:
        """Suivre la trace, titrer les alertes, persister. Ne lève jamais.

        Un badge ne doit pas pouvoir faire tomber le statut, dont dépend tout
        l'affichage de la page : chaque échec est capturé et dit (journal).
        """

        kept = 0
        skipped = self._background_trace.skipped_lines
        try:
            kept = follow(self.background, self._background_trace, resolve_board=self._board_of_conversation)
        except Exception as exc:  # noqa: BLE001 - capture: the badge must never break the status, said in the journal
            self.journal.emit("background.follow_failed",
                              f"Suivi de la trace en échec : {type(exc).__name__}: {exc}"[:300],
                              level="warning", data={"exception_type": type(exc).__name__})
        if self._background_trace.skipped_lines > skipped:
            self.journal.emit("background.trace_line_skipped",
                              "Ligne de trace trop longue pour le suivi des alertes : sautée",
                              level="warning", data={"code": "trace_line_too_long", "offset": self._background_trace.offset,
                                                     "limit_bytes": MAX_TRACE_READ_BYTES})
        if self.background.retitle(self._board_titles):
            self._schedule_board_titles()
        offset_moved = self._background_trace.offset != self._background_saved_offset
        stale = time.monotonic() - self._background_saved_at >= self.BACKGROUND_OFFSET_SAVE_S
        if force_save or kept or (offset_moved and stale):
            self._save_background()

    def _save_background(self) -> bool:
        try:
            self._background_store.save(self.background, self._background_trace)
        except OSError as exc:
            # capture: in-memory alerts stay correct; only their survival across a restart is at risk. Said once
            # per failure streak (error -> Errors badge), not once per second.
            if not self._background_save_failed:
                self.journal.emit("background.store_save_failed",
                                  f"Notifications d'arrière-plan non enregistrées : {type(exc).__name__}: {exc}"[:300],
                                  level="error", data={"path": str(self._background_store.path),
                                                       "exception_type": type(exc).__name__})
            self._background_save_failed = True
            return False
        if self._background_save_failed:
            self.journal.emit("background.store_save_recovered", "Notifications d'arrière-plan de nouveau enregistrées")
        self._background_save_failed = False
        self._background_saved_offset = self._background_trace.offset
        self._background_saved_at = time.monotonic()
        return True

    def _remember_board_title(self, board: dict[str, Any] | None) -> None:
        if isinstance(board, dict) and isinstance(board.get("board_id"), str) and board.get("title"):
            self._board_titles[board["board_id"]] = str(board["title"])

    def _schedule_board_titles(self) -> None:
        """Relire les titres des Boards (archivés compris), au plus toutes les 30 s, en tâche de fond."""

        if self.sessions is None or self._core_boards_unsupported:
            return
        if self._board_titles_task is not None and not self._board_titles_task.done():
            return
        if time.monotonic() - self._board_titles_read_at < self.BOARD_TITLES_REFRESH_S:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # intentional: called outside the loop (shutdown); the next beat retries
        self._board_titles_read_at = time.monotonic()
        self._board_titles_task = loop.create_task(self._refresh_board_titles(),
                                                   name="jarvis-background-board-titles")

    async def _refresh_board_titles(self) -> None:
        try:
            status, payload = await asyncio.wait_for(
                self.sessions.forward("GET", "/v1/boards", params={"include_archived": "true"}), timeout=2.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: the alert keeps its board id, retried in 30 s
            self.journal.emit("background.board_titles_failed",
                              f"Titres des Boards illisibles : {type(exc).__name__}: {exc}"[:300], level="warning",
                              data={"exception_type": type(exc).__name__})
            return
        boards = payload.get("boards") if status == 200 and isinstance(payload, dict) else None
        if not isinstance(boards, list):
            self.journal.emit("background.board_titles_failed", f"Liste des Boards refusée par Core (HTTP {status})",
                              level="warning", data={"status": status})
            return
        for board in boards:
            self._remember_board_title(board)
        self.background.retitle(self._board_titles)

    def _background_summary(self) -> dict[str, Any]:
        """Avancer le registre des événements de fond et en rendre le résumé.

        Ne lève jamais : un badge ne doit pas pouvoir faire tomber le statut,
        dont dépend tout l'affichage de la page.
        """
        self._advance_background()
        summary = {"seq": self.background.seq, "unread": self.background.unread,
                   "counts": self.background.counts()}
        # Slice 07 : non-vus par Board source, pour que les pastilles disent
        # qu'une alerte vient d'un autre Board. Absent quand aucun non-vu n'est
        # attribué (même règle que `attention` ci-dessous).
        sources = self.background.sources()
        if sources:
            summary["sources"] = sources
        if self._background_store_warning:
            summary["store_warning"] = self._background_store_warning
        # Slice 09 : la charge utile typée des points d'attention non vus, pour
        # que l'avertissement flottant se dessine sans ouvrir un second
        # battement. Bornée à trois ; le reste reste derrière la pastille et
        # `GET /api/background`.
        #
        # **Absente quand il n'y a rien à montrer**, et pas présente et vide :
        # ce bloc part chaque seconde, et la seconde ordinaire n'a aucun point
        # d'attention. Le payload reste donc identique à l'octet près pour tout
        # consommateur existant, et un serveur plus ancien se lit exactement
        # comme un serveur qui n'a rien à signaler — ce que la page traite déjà
        # de la même façon.
        attention = self.background.attention_digest()
        if attention:
            summary["attention"] = attention
        return summary

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
            # Scène constellation (Slice 06, écran Slice 11) : rendu immédiat,
            # outils d'affichage du cerveau à son prochain démarrage ; `stored`
            # et `env` disent ce que l'onglet Expérimental doit expliquer.
            "scene": describe_scene_gate(settings),
            # Mode d'interaction (Slice 02) : la **préférence** enregistrée, sa
            # version de schéma et les modes annoncés. La valeur effective
            # vivante n'est pas ici — elle appartient à Core et voyage par
            # `/api/status`, qui bat chaque seconde ; la recopier dans un GET
            # de réglages en ferait une seconde vérité périmée.
            "interaction_mode": interaction_mode_settings.describe(settings),
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

    # --------------------------------------------- mode d'interaction (Slice 02)

    async def get_interaction_mode(self, request: web.Request) -> web.Response:
        """La préférence enregistrée, la valeur effective de Core, et les modes annoncés.

        Les trois ensemble, et nommés : un écran qui ne verrait que la
        préférence mentirait pendant qu'un autre processus change le mode, et
        un écran qui ne verrait que la valeur effective perdrait ``REUNION``
        dès que l'utilisateur l'aurait choisi.
        """

        del request
        settings = self._settings()
        seen = interaction_mode_settings.inspect(settings)
        if seen["unreadable"] and not self._interaction_mode_foreign_reported:
            # Une préférence écrite par un Jarvis plus récent ne s'applique pas
            # — c'est le bon choix — mais elle ne doit pas se taire. La lecture
            # est fréquente, donc une ligne par processus ; ce qui reste visible
            # est dans la réponse (`unreadable`, `stored_value`) et ne s'épuise pas.
            self._interaction_mode_foreign_reported = True
            self.journal.emit(
                "interaction.mode.foreign_version",
                "Préférence de mode d'interaction écrite par une version plus récente (schéma "
                f"{seen['stored_schema_version']}) : non appliquée, gardée telle quelle ; "
                "le mode assistant s'applique en attendant",
                level="warning",
                data={"code": "interaction_mode_stored_version_unreadable",
                      "stored_schema_version": seen["stored_schema_version"],
                      "schema_version": interaction_mode_settings.SCHEMA_VERSION},
            )
        return web.json_response({
            **interaction_mode_settings.describe(settings),
            "effective": await self.interaction_mode_view.read(interaction_mode_settings.load(settings)),
        })

    async def save_interaction_mode(self, request: web.Request) -> web.Response:
        """Choisir le mode d'interaction : enregistrer la préférence, puis l'appliquer à chaud.

        Route dédiée, hors de `/api/settings` : elle s'applique immédiatement et
        ne dépend pas de la validité du reste des réglages. Elle ne traverse
        **jamais** `_apply_voice`, dont la première branche supprime
        `voice_architecture` : le mode est un axe à part, et un basculement de
        compatibilité vocale ne doit pas l'emporter (constat G1).

        **Aucun redémarrage de Voice** (Décision D15) : rien ici ne recalcule
        `VoiceComposition.configuration_id` ni n'écrit sur `VoiceSwitchBus`.
        Couper l'audio au milieu d'une présentation serait la pire panne que
        cette fonctionnalité pourrait introduire.

        L'ordre est délibéré : on enregistre **avant** de demander. Si Core est
        injoignable, le choix de l'utilisateur survit et sera rejoué au prochain
        démarrage ou dès que Core reparaît — et la réponse dit, en 503, que le
        mode est enregistré mais pas encore appliqué, au lieu de laisser croire
        qu'une présentation est armée.
        """

        try:
            payload = await request.json()
        except ValueError:
            payload = None
        current = self._settings()
        before = interaction_mode_settings.load(current)
        requested = payload.get("mode") if isinstance(payload, dict) else None
        self.journal.emit(
            "interaction.mode.requested", "Changement de mode d'interaction demandé",
            data={"requested": str(requested)[:64] if requested is not None else None,
                  "previous": before.value},
        )
        try:
            mode = interaction_mode_settings.apply(current, payload)
        except interaction_mode_settings.InteractionModeSettingsError as exc:
            self.journal.emit(
                "interaction.mode.refused", f"Mode d'interaction refusé : {exc.code}",
                level="warning", data={"code": exc.code, "requested": str(requested)[:64]},
            )
            # Un mode annoncé mais sans comportement est un conflit, pas une
            # requête malformée : l'écran doit pouvoir les distinguer sans lire
            # le texte. Le code stable, lui, voyage dans l'en-tête dans les deux cas.
            error = (web.HTTPConflict if exc.code == "interaction_mode_not_implemented" else web.HTTPBadRequest)
            raise error(text=str(exc), headers={SETTINGS_ERROR_CODE_HEADER: exc.code}) from exc
        # Slice 04a : un Core à Boards garde le mode sur le Board actif (son
        # écouteur l'y enregistre, origine `user`). La préférence globale n'est
        # plus écrite : elle ne sert plus que d'entrée de migration.
        # Boards déjà vus dans cette vie : pas d'aller-retour (jusqu'à 5 s) avant d'appliquer.
        owned = True if self._core_has_boards else await self._core_boards_own_interaction_mode()
        board_owned = owned is not False and (owned is True or self._core_has_boards)
        if not board_owned:
            self._write_settings(current)
        state = {
            **interaction_mode_settings.describe(current),
            "effective": None,
        }
        try:
            live = await self.interaction_mode_view.request(mode, source="control_center")
        except InteractionModeUnavailable as exc:
            # Deux échecs très différents arrivaient ici par la même porte. Une
            # panne de transport sera rattrapée ; un **refus** de Core (version
            # décalée qui répond 400) ne le sera jamais, et promettre « il sera
            # repris » ferait attendre l'utilisateur pour rien — pendant que le
            # rattrapage réessaierait en boucle une demande déjà refusée.
            retryable = exc.code in {CORE_UNREACHABLE, NOT_CONFIGURED} and not board_owned
            self.journal.emit(
                "interaction.mode.not_applied",
                f"Mode {mode.label} enregistré mais non appliqué : {exc}",
                level="error",
                data={"code": exc.code, "mode": mode.value, "previous": before.value,
                      "retryable": retryable},
            )
            if retryable:
                self._schedule_interaction_mode_replay("save_retry")
            # **Le corps de la réponse est lu par un humain, dans un bandeau.**
            # Y interpoler `exc` y déversait la phrase d'aiohttp telle quelle —
            # « Cannot connect to host 127.77.0.1:56456 ssl:default […] » —,
            # c'est-à-dire un détail de transport et un port de bouclage interne
            # à quelqu'un qui veut seulement savoir si son choix est perdu. La
            # cause réelle n'est pas effacée pour autant : elle est juste au
            # dessus, dans `interaction.mode.not_applied`, avec le code stable,
            # qui est l'endroit où l'on diagnostique. Le code voyage aussi dans
            # l'en-tête, donc l'écran garde de quoi distinguer les deux cas sans
            # lire cette phrase.
            raise web.HTTPServiceUnavailable(
                text=(
                    f"Mode {mode.label} non enregistré : le Board actif le garde, et Core ne l’a pas pris. "
                    "Réessayez quand Core répond."
                    if board_owned else
                    f"Mode {mode.label} enregistré. "
                    + ("Jarvis ne joint pas Core pour l’appliquer tout de suite ; "
                       "il le fera dès que Core répondra."
                       if retryable else
                       "Core a refusé de l’appliquer : il ne sera pas réessayé tel quel.")
                ),
                headers={SETTINGS_ERROR_CODE_HEADER: exc.code},
            ) from exc
        # Une réécriture qui ne change rien n'est **pas** un changement de mode,
        # et elle ne doit pas se compter comme tel : qui filtre `.applied` pour
        # savoir combien de fois le mode a bougé aurait lu un nombre faux. Le
        # verdict vient de Core (`disposition`), pas d'une comparaison de deux
        # préférences locales — elles peuvent différer de l'état vivant. Sans
        # verdict (Core plus ancien), on retombe sur la comparaison locale.
        disposition = live.get("disposition")
        changed = disposition == "applied" if disposition is not None else before is not mode
        self.journal.emit(
            "interaction.mode.applied" if changed else "interaction.mode.unchanged",
            f"Mode d'interaction {before.label} → {mode.label}" if changed
            else f"Mode d'interaction réenregistré sur {mode.label}, inchangé",
            data={"mode": mode.value, "previous": before.value, "revision": live["revision"],
                  "changed": changed, "disposition": disposition},
        )
        state["effective"] = live
        return web.json_response(state)

    async def get_barehands(self, request: web.Request) -> web.Response:
        del request
        settings = self._settings()
        # Un bloc écrit par un Jarvis plus récent ne s'applique pas — c'est le
        # bon choix — mais il se taisait : ni bandeau, ni journal, et la
        # première écriture ordinaire l'effaçait. La lecture est fréquente
        # (chaque ouverture de l'onglet), donc la ligne ne part qu'une fois par
        # processus ; ce qui reste visible, lui, est dans la réponse
        # (`unreadable`, `stored_schema_version`) et ne s'épuise pas.
        seen = barehands.inspect(settings)
        if seen["unreadable"] and not self._barehands_foreign_reported:
            self._barehands_foreign_reported = True
            self.journal.emit(
                "settings.barehands.foreign_version",
                "Réglages Bare Hands écrits par une version plus récente (schéma "
                f"{seen['stored_schema_version']}) : non appliqués, gardés tels quels ; "
                f"la prochaine écriture les rangera sous « {seen['archive_key']} »",
                level="warning",
                data={"code": "barehands_stored_version_unreadable",
                      "stored_schema_version": seen["stored_schema_version"],
                      "schema_version": barehands.SCHEMA_VERSION,
                      "archive_key": seen["archive_key"]},
            )
        return web.json_response(barehands.describe(settings, self.barehands_vendor_root))

    async def save_barehands(self, request: web.Request) -> web.Response:
        """Enregistrer les réglages Bare Hands, dans le fichier de réglages commun.

        Route dédiée, comme les raccourcis : ils s'appliquent à chaud et ne
        doivent pas dépendre de la validité du reste des réglages (voix, CLI)
        qu'un enregistrement complet revaliderait. Depuis la Slice 07 elle
        porte les neuf réglages du contrat § 9, pas le seul interrupteur ;
        ``enabled`` reste obligatoire et une charge utile réduite à lui seul
        reste valide (constat F5).
        """

        try:
            payload = await request.json()
        except ValueError:
            payload = None
        current = self._settings()
        # Ce qui était appliqué **avant** l'écriture : c'est la seule fenêtre
        # où on peut encore le lire, `apply` écrivant dans `current`.
        before = barehands.load(current)
        # Et ce que le bloc **était**, pour la même raison : `apply` archive
        # puis remplace, donc après lui plus rien ne dit qu'il était illisible.
        seen = barehands.inspect(current)
        replaced_archive = seen["archive_key"] in barehands.archived_keys(current)
        try:
            value = barehands.apply(current, payload)
        except barehands.BarehandsSettingsError as exc:
            self.journal.emit(
                "settings.barehands.rejected", "Barehands test mode setting rejected",
                level="warning", data={"code": exc.code},
            )
            raise web.HTTPBadRequest(text=str(exc), headers={SETTINGS_ERROR_CODE_HEADER: exc.code}) from exc
        self._write_settings(current)
        # L'interrupteur commande aussi la surface d'outils du cerveau (Slice
        # 12) : sans ce rappel, allumer Bare Hands laisserait le canal de
        # commandes sans outil jusqu'au prochain enregistrement des réglages.
        self._apply_agent_settings(current)
        state = barehands.describe(current, self.barehands_vendor_root)
        # Ce que cette écriture a **changé**, nommément. La route porte neuf
        # réglages : un message qui ne parle que de l'interrupteur écrivait la
        # même ligne « activé » pour trois déplacements de curseur, et aucun
        # des huit autres réglages n'apparaissait nulle part dans le journal.
        changed = {key: value[key] for key in barehands.SETTINGS_DEFAULTS if value[key] != before.get(key)}
        if "enabled" in changed and not value["enabled"]:
            # Éteint : plus de page, plus d'outils — la séance de calibration se
            # ferme **tout de suite**, sans attendre son échéance (reprise QA).
            self.barehands_calibration.close("disabled")
        if "enabled" in changed:
            summary = "Bare Hands {} (mode test)".format("activé" if value["enabled"] else "désactivé")
            rest = {key: changed[key] for key in changed if key != "enabled"}
            if rest:
                summary += " ; " + ", ".join(f"{key}={rest[key]}" for key in sorted(rest))
        elif changed:
            summary = "Réglages Bare Hands : " + ", ".join(f"{key}={changed[key]}" for key in sorted(changed))
        else:
            # Une écriture qui ne change rien arrive pour de bon (réenregistrer
            # la même valeur) : la taire ferait d'une route appelée et d'une
            # route muette la même trace.
            summary = "Réglages Bare Hands réécrits sans changement"
        self.journal.emit(
            "settings.barehands", summary,
            data={"enabled": value["enabled"], "assets_installed": state["assets"]["installed"],
                  "changed": changed},
        )
        # L'archivage a sa propre ligne : la précédente parle de ce qui a été
        # enregistré, celle-ci de ce qui a failli être détruit. Les mêler
        # rendrait la seconde invisible dans un filtre sur `settings.barehands`.
        if seen["unreadable"]:
            self.journal.emit(
                "settings.barehands.archived",
                f"Réglages Bare Hands en schéma {seen['stored_schema_version']} conservés sous "
                f"« {seen['archive_key']} » avant d'être remplacés par les valeurs d'usine"
                + (" (une archive de la même version a été remplacée)" if replaced_archive else ""),
                level="warning",
                data={"code": "barehands_stored_version_archived",
                      "stored_schema_version": seen["stored_schema_version"],
                      "schema_version": barehands.SCHEMA_VERSION,
                      "archive_key": seen["archive_key"],
                      "replaced_previous_archive": replaced_archive},
            )
        return web.json_response(state)

    # ------------------------------------------------- profil de calibration (Slice 08)

    async def report_barehands_failure(self, request: web.Request) -> web.Response:
        """Ranger dans `errors.jsonl` une panne Bare Hands constatée par la page.

        La caméra et MediaPipe tournent dans le navigateur : sans cette route,
        la cause réelle d'un « Suivi interrompu » ne vivait que dans la console
        de la page. Le serveur ne juge pas la panne, il la garde — bornée, pour
        qu'une page folle ne remplisse pas le journal d'une pile sans fin.
        """

        try:
            payload = await request.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="Panne Bare Hands illisible : objet JSON attendu.")
        code = str(payload.get("code") or "")
        if not BAREHANDS_FAILURE_CODE.fullmatch(code):
            raise web.HTTPBadRequest(text=f"Code de panne Bare Hands invalide : {code[:64]!r}")
        message = str(payload.get("message") or "")[:BAREHANDS_FAILURE_TEXT_LIMIT]
        stack = str(payload.get("stack") or "")[:BAREHANDS_FAILURE_TEXT_LIMIT]
        self.journal.emit(
            "barehands.failure",
            f"Bare Hands en panne ({code})" + (f" : {message}" if message else ""),
            level="error", data={"code": code, "message": message, "stack": stack},
        )
        return web.json_response({"ok": True})

    async def save_barehands_trace(self, request: web.Request) -> web.Response:
        """Ranger une trace de diagnostic Bare Hands (Slice 10, décision 32).

        Le serveur ne mesure rien et n'enregistre rien de lui-même : la caméra,
        les mains et l'écran sont dans la page, et l'enregistrement est une
        action explicite de l'utilisateur. Il **range** — et il refuse tout ce
        qui n'est pas une mesure dérivée, parce que le module JS est de notre
        côté et que cette route ne l'est pas.

        Une ligne de journal par trace, avec son code : sans elle, « personne
        n'a enregistré » et « l'enregistrement est mort » seraient la même
        absence dans `runtime/trace.jsonl`.
        """

        try:
            payload = await request.json()
        except ValueError:
            payload = None
        try:
            stored = barehands_trace.store(self.runtime_root, payload)
        except barehands_trace.BarehandsTraceError as exc:
            self.journal.emit(
                "barehands.trace_rejected", f"Trace de diagnostic Bare Hands refusée : {exc}",
                level="error", data={"code": exc.code},
            )
            raise web.HTTPBadRequest(
                text=str(exc), headers={SETTINGS_ERROR_CODE_HEADER: exc.code}) from exc
        # Le chemin **normal** se journalise aussi : un journal qui ne porte que
        # les échecs rend « rien dans le journal » indiscernable de « mort ».
        summary = (
            f"Trace de diagnostic Bare Hands enregistrée : {stored['frames']} image(s) "
            f"sur {stored['observed_frames']} vue(s), {round(stored['duration_ms'] / 1000)} s"
        )
        if stored["dropped_frames"]:
            summary += f" ; {stored['dropped_frames']} image(s) refusée(s) par le plafond"
        self.journal.emit(
            "barehands.trace_recorded", summary,
            data={"code": "barehands_trace_recorded", "trace_id": stored["trace_id"],
                  "frames": stored["frames"], "observed_frames": stored["observed_frames"],
                  "dropped_frames": stored["dropped_frames"],
                  "duration_ms": stored["duration_ms"],
                  "stopped_because": stored["stopped_because"], "bytes": stored["bytes"]},
        )
        return web.json_response(stored)

    async def get_barehands_benchmarks(self, request: web.Request) -> web.Response:
        """Les résumés de banc rangés (Slice 08 adaptative, décision 64).

        Un fichier illisible ou une entrée refusée par la liste blanche est
        écartée **et dite** (``skipped``, ligne de journal) : « rien de rangé »
        et « rangé mais illisible » ne sont pas la même absence.
        """

        del request
        try:
            loaded = barehands_benchmark.load(self.runtime_root)
        except Exception as exc:  # capture : panne de lecture, dite et journalisée (Error Logs)
            return self._benchmark_failure("lecture", exc)
        if loaded["skipped"]:
            self.journal.emit(
                "barehands.benchmark_unreadable",
                f"Résumés de banc Bare Hands : {loaded['skipped']} entrée(s) illisible(s) écartée(s)",
                level="warning", data={"code": "barehands_benchmark_unreadable", "skipped": loaded["skipped"]},
            )
        return web.json_response(loaded)

    async def save_barehands_benchmark(self, request: web.Request) -> web.Response:
        """Ranger le résumé d'un run du banc : un résultat du contrat,
        reconstruit clé par clé (`barehands_benchmark.normalize`), refusé avec
        son code sinon. Le chemin normal se journalise aussi."""

        try:
            payload = await request.json()
        except ValueError:
            payload = None
        try:
            stored = barehands_benchmark.store(self.runtime_root, payload)
        except barehands_benchmark.BarehandsBenchmarkError as exc:
            self.journal.emit(
                "barehands.benchmark_rejected", f"Résumé de banc Bare Hands refusé : {exc}",
                level="error", data={"code": exc.code},
            )
            raise web.HTTPBadRequest(
                text=str(exc), headers={SETTINGS_ERROR_CODE_HEADER: exc.code}) from exc
        except Exception as exc:  # capture : disque, ou panne imprévue — jamais un 500 sans code
            return self._benchmark_failure("écriture", exc)
        if stored["skipped"] or stored["backup"]:
            self.journal.emit(
                "barehands.benchmark_unreadable",
                f"Résumés de banc Bare Hands : {stored['skipped']} entrée(s) illisible(s) non recopiée(s)"
                + (f", fichier d'avant copié sous « {stored['backup']} »" if stored["backup"] else ""),
                level="warning",
                data={"code": "barehands_benchmark_unreadable", "skipped": stored["skipped"],
                      "backup": stored["backup"]},
            )
        self.journal.emit(
            "barehands.benchmark_recorded",
            "Résumé de banc Bare Hands rangé" + (" (déjà présent)" if stored["duplicate"] else "")
            + f" : {stored['stored']} rangé(s)"
            + (f", {stored['dropped']} plus ancien(s) retiré(s)" if stored["dropped"] else ""),
            data={"code": "barehands_benchmark_recorded", **stored},
        )
        return web.json_response(stored)

    async def clear_barehands_benchmarks(self, request: web.Request) -> web.Response:
        """Effacer tous les résumés de banc rangés."""

        del request
        try:
            cleared = barehands_benchmark.clear(self.runtime_root)
        except Exception as exc:  # capture : panne d'effacement, dite et journalisée
            return self._benchmark_failure("effacement", exc)
        self.journal.emit(
            "barehands.benchmark_cleared", f"Résumés de banc Bare Hands effacés : {cleared['cleared']}",
            data={"code": "barehands_benchmark_cleared", **cleared},
        )
        return web.json_response(cleared)

    def _benchmark_failure(self, action: str, exc: Exception) -> web.Response:
        """Une panne imprévue de la route des résumés : dite telle quelle
        (type et message), journalisée au niveau erreur (Error Logs), rendue
        avec un code nommé plutôt qu'un 500 sans explication."""

        code = "barehands_benchmark_store_failed"
        self.journal.emit(
            "barehands.benchmark_store_failed",
            f"Résumés de banc Bare Hands : {action} impossible ({type(exc).__name__}: {exc})",
            level="error", data={"code": code, "action": action, "error": type(exc).__name__},
        )
        return self._barehands_error(500, code, f"Résumés de banc : {action} impossible ({type(exc).__name__}: {exc})")

    async def get_barehands_profile(self, request: web.Request) -> web.Response:
        del request
        settings = self._settings()
        seen = barehands_profile.inspect(settings)
        if seen["unreadable"] and not self._barehands_profile_foreign_reported:
            self._barehands_profile_foreign_reported = True
            self.journal.emit(
                "settings.barehands.profile_foreign_version",
                "Profil de calibration Bare Hands écrit par une version plus récente (schéma "
                f"{seen['stored_schema_version']}) : non appliqué, gardé tel quel ; "
                f"la prochaine calibration le rangera sous « {seen['archive_key']} »",
                level="warning",
                data={"code": "barehands_profile_version_unreadable",
                      "stored_schema_version": seen["stored_schema_version"],
                      "schema_version": barehands_profile.SCHEMA_VERSION,
                      "archive_key": seen["archive_key"]},
            )
        return web.json_response(barehands_profile.describe(settings))

    async def save_barehands_profile(self, request: web.Request) -> web.Response:
        """Enregistrer le profil dérivé d'une calibration (décisions 28 à 32).

        Le serveur ne mesure rien : la caméra, les mains et l'écran sont dans la
        page. Il **range**, et il refuse tout ce qui n'est pas une mesure
        dérivée — c'est ici, et non dans le module JS, que la décision 32 se
        tient contre un appelant qu'on n'a pas écrit.
        """

        try:
            payload = await request.json()
        except ValueError:
            payload = None
        current = self._settings()
        seen = barehands_profile.inspect(current)
        replaced_archive = seen["archive_key"] in barehands_profile.archived_keys(current)
        try:
            value = barehands_profile.apply(current, payload)
        except barehands_profile.BarehandsProfileError as exc:
            self.journal.emit(
                "settings.barehands.profile_rejected", "Barehands calibration profile rejected",
                level="warning", data={"code": exc.code},
            )
            raise web.HTTPBadRequest(text=str(exc), headers={SETTINGS_ERROR_CODE_HEADER: exc.code}) from exc
        self._write_settings(current)
        # Ce que la calibration a **mesuré**, nommément. « Profil enregistré »
        # sans dire quoi rendrait une calibration complète et une calibration
        # qui a tout raté identiques dans le journal.
        # Les clés **calibrantes**, celles qui adaptent le moteur, et non toutes
        # les clés écrites : `quality` est une métrique de séance, présente dès
        # qu'une image a été vue. La compter faisait dire « 1 mesure(s) » à un
        # parcours dont les sept étapes avaient échoué, et la branche « sans
        # aucune mesure » ci-dessous ne tirait jamais.
        measured = sorted(
            f"{handedness}.{key}"
            for handedness in barehands_profile.HANDEDNESSES
            for key in barehands_profile.CALIBRATING_KEYS
            if value["hands"][handedness][key] is not None
        )
        # Les valeurs d'essai **acceptées** (décision 48) : elles adaptent le
        # moteur autant qu'une mesure, donc elles se comptent et se nomment.
        measured += sorted(
            f"tuning.{key}" for key in barehands_profile.TUNING_BOUNDS
            if value["tuning"][key] is not None
        )
        stages = {stage: value["stages"][stage]["status"] for stage in barehands_profile.STAGES}
        failed = sorted(stage for stage, status in stages.items() if status == "failed")
        summary = (
            "Profil de calibration Bare Hands enregistré : "
            f"{len(measured)} mesure(s), "
            f"{sum(1 for status in stages.values() if status == 'ok')}/{len(stages)} étape(s) réussie(s)"
        )
        if failed:
            summary += f" ; échouées : {', '.join(failed)}"
        if not measured:
            # Une calibration qui n'a rien mesuré est une nouvelle, pas un
            # silence : le moteur garde ses défauts et l'utilisateur l'a vu.
            summary = "Profil de calibration Bare Hands enregistré sans aucune mesure : le moteur garde ses défauts"
        self.journal.emit(
            "settings.barehands.profile", summary,
            data={"calibrated": value["calibrated"], "measured": measured, "stages": stages},
        )
        if seen["unreadable"]:
            self.journal.emit(
                "settings.barehands.profile_archived",
                f"Profil de calibration en schéma {seen['stored_schema_version']} conservé sous "
                f"« {seen['archive_key']} » avant d'être remplacé"
                + (" (une archive de la même version a été remplacée)" if replaced_archive else ""),
                level="warning",
                data={"code": "barehands_profile_version_archived",
                      "stored_schema_version": seen["stored_schema_version"],
                      "schema_version": barehands_profile.SCHEMA_VERSION,
                      "archive_key": seen["archive_key"],
                      "replaced_previous_archive": replaced_archive},
            )
        return web.json_response(barehands_profile.describe(current))

    async def reset_barehands_profile(self, request: web.Request) -> web.Response:
        """Rendre au moteur ses défauts d'usine (décision 31, « reset profile » du §9)."""

        del request
        current = self._settings()
        # **Un profil illisible n'est pas un profil absent**, et c'est ici que
        # les deux se confondaient : `load` rend un profil vierge pour un bloc
        # en version étrangère, donc `calibrated` valait `False` et le journal
        # annonçait « il n'y avait rien de calibré » **en détruisant** une
        # calibration écrite par un Jarvis plus récent. L'inverse exact de ce
        # que l'écriture fait déjà (constat R6) : on range avant de remplacer.
        # Une calibration coûte une minute à l'utilisateur.
        seen = barehands_profile.inspect(current)
        replaced_archive = seen["archive_key"] in barehands_profile.archived_keys(current)
        archived = barehands_profile.archive_unreadable(current)
        had = seen["unreadable"] or barehands_profile.load(current)["calibrated"]
        barehands_profile.clear(current)
        self._write_settings(current)
        self.journal.emit(
            "settings.barehands.profile_reset",
            "Profil de calibration Bare Hands réinitialisé"
            if had else "Profil de calibration Bare Hands réinitialisé (il n'y avait rien de calibré)",
            data={"had_profile": had, "unreadable": seen["unreadable"],
                  "stored_schema_version": seen["stored_schema_version"]},
        )
        if archived:
            self.journal.emit(
                "settings.barehands.profile_archived",
                f"Profil de calibration en schéma {seen['stored_schema_version']} conservé sous "
                f"« {archived} » avant d'être réinitialisé"
                + (" (une archive de la même version a été remplacée)" if replaced_archive else ""),
                level="warning",
                data={"code": "barehands_profile_version_archived",
                      "stored_schema_version": seen["stored_schema_version"],
                      "schema_version": barehands_profile.SCHEMA_VERSION,
                      "archive_key": archived,
                      "replaced_previous_archive": replaced_archive},
            )
        return web.json_response(barehands_profile.describe(current))

    # ------------------------------------------------- canal de commandes (Slice 12)

    @staticmethod
    def _barehands_error(status: int, code: str, message: str, command_id: str | None = None) -> web.Response:
        """Refus du canal de commandes : le code dans le corps **et** dans l'en-tête.

        Les deux idiomes du dépôt se rencontrent ici pour une raison précise :
        le corps JSON (`{"error": {code, message}}`, forme de la famille scène)
        est ce que la page lit, et l'en-tête `X-Jarvis-Error-Code` (forme de la
        famille réglages) est ce que le **serveur MCP** lit pour transformer un
        refus en erreur d'outil sans analyser une phrase française.

        `command_id` (l'identifiant **court**, quand le refus en concerne une)
        va dans le corps : c'est lui qui relie l'échec vu du serveur MCP aux
        lignes du courtier dans la même trace.
        """

        extra = {"id": command_id} if command_id else {}
        return web.json_response(
            scene_wire.error_body(code, message, **extra), status=status,
            headers={SETTINGS_ERROR_CODE_HEADER: code},
        )

    async def barehands_commands_poll(self, request: web.Request) -> web.Response:
        """Long-poll de la page : rend la commande en attente, ou rien.

        `wait_s` (0 à `MAX_POLL_WAIT_S`) ; 0 est une lecture courte. Toujours
        200 : `{"command": {...}}` ou `{"command": null}`. La page rouvre
        aussitôt — c'est elle qui tient la boucle, et seulement pendant que Bare
        Hands est allumé et que l'onglet est visible.
        """

        unknown = set(request.query) - {"wait_s", "calibration"}
        if unknown:
            return self._barehands_error(400, BAD_REQUEST, "paramètre inconnu : " + ", ".join(sorted(unknown)))
        # La séance de calibration que **cette** page tient (Slice 06
        # adaptative) : seule la page qui la présente reçoit les commandes
        # `calibration_*`. Hors forme : ignorée, jamais une erreur de poll.
        calibration_session = request.query.get("calibration")
        if calibration_session is not None and not _CALIBRATION_SESSION.match(calibration_session):
            calibration_session = None
        try:
            wait_s = float(request.query.get("wait_s", "0"))
        except ValueError:
            return self._barehands_error(400, BAD_REQUEST, "wait_s doit être un nombre")
        if not 0.0 <= wait_s <= MAX_POLL_WAIT_S:
            return self._barehands_error(400, BAD_REQUEST, f"wait_s doit être entre 0 et {MAX_POLL_WAIT_S:g}")
        broker = self.barehands_commands
        deadline = time.monotonic() + wait_s
        while True:
            # L'événement est pris **avant** la lecture : une commande créée
            # entre les deux lève l'événement déjà attendu, elle n'est pas perdue.
            wake = broker.wake_event()
            command = broker.deliver(calibration_session)
            if command is not None:
                return web.json_response({"command": command})
            # Rien à attendre d'autre qu'une **nouvelle** commande : la remise
            # est exclusive, donc une commande déjà emportée par un autre
            # onglet ne repassera jamais par ici. Aucune minuterie de
            # redistribution à retrancher de l'attente.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return web.json_response({"command": None})
            try:
                await asyncio.wait_for(wake.wait(), timeout=remaining)
            except TimeoutError:
                # Échéance du long-poll : la boucle retranche et décide, elle ne
                # suppose rien.
                continue

    async def barehands_command_request(self, request: web.Request) -> web.Response:
        """Demande du cerveau (serveur MCP `jarvis-barehands`) : une commande, attendue jusqu'à son échéance.

        Rend 200 et le reçu de la page (`outcome`, `lifecycle`, …), ou un refus
        codé. Jamais un succès par défaut : sans page visible, c'est 504
        `barehands_no_visible_page`, pas un 200 optimiste.

        Commandes de calibration (Slice 06 adaptative) : charge utile validée
        par `parse_command_request` ; refusées `barehands_calibration_inactive`
        (409) sans séance déclarée par la page ; `calibration_accept_trial`
        refusée `barehands_calibration_consent_missing` (409) quand la citation
        de l'utilisateur ne se retrouve pas dans ce qu'il a dit depuis l'essai
        — et sinon remplacée par l'accord que la page lit (décision 53).
        """

        if request.query:
            return self._barehands_error(400, BAD_REQUEST, "unexpected query")
        try:
            raw = await scene_wire.read_bounded_body(request, MAX_CALIBRATION_REQUEST_BYTES)
        except scene_wire.SceneBodyTooLarge:
            return self._barehands_error(413, BAD_REQUEST, f"la demande dépasse {MAX_CALIBRATION_REQUEST_BYTES} octets")
        try:
            name, payload = parse_command_request(json.loads(raw.decode("utf-8")) if raw else None)
        except RecursionError:
            return self._barehands_error(400, BAD_REQUEST, "demande illisible : imbrication excessive")
        except (UnicodeDecodeError, ValueError) as exc:
            code = getattr(exc, "code", BAD_REQUEST)
            status = getattr(exc, "status", 400)
            return self._barehands_error(status, code, str(exc))
        calibrating = is_calibration_command(name)
        if not calibrating and len(raw) > MAX_COMMAND_REQUEST_BYTES:
            # Les cinq commandes de cycle de vie gardent leur borne d'avant.
            return self._barehands_error(413, BAD_REQUEST, f"la demande dépasse {MAX_COMMAND_REQUEST_BYTES} octets")
        if calibrating and self.barehands_commands.enabled():
            refusal = self._calibration_gate(name, payload)
            if refusal is not None:
                return refusal
            if name == "calibration_accept_trial":
                payload = consent_payload(str((payload or {})["userQuote"]))
            elif name == "calibration_commit_proposal":
                payload = commit_payload(payload or {})
        try:
            answer = await self.barehands_commands.request(name, payload)
        except BarehandsCommandError as exc:
            return self._barehands_error(exc.status, exc.code, str(exc), exc.command_id)
        if calibrating:
            self._calibration_follow(name, answer)
        return web.json_response(answer)

    def _calibration_context(self) -> dict[str, Any] | None:
        """Le drapeau du mode calibration, ou `None`. Bare Hands éteint : la séance se ferme ici."""

        if not self.barehands_commands.enabled():
            self.barehands_calibration.close("disabled")
            return None
        return self.barehands_calibration.context()

    def _calibration_gate(self, name: str, payload: dict[str, Any] | None) -> web.Response | None:
        """Refus serveur d'une commande de calibration, ou `None` pour laisser passer."""

        registry = self.barehands_calibration
        if not registry.active():
            self.journal.emit("barehands.calibration_refused", f"{name} refusée : aucune séance de calibration ouverte",
                              level="warning", data={"code": CALIBRATION_INACTIVE, "command": name})
            return self._barehands_error(
                409, CALIBRATION_INACTIVE,
                "Aucune séance de calibration n'est ouverte à l'écran : les outils calibration_* ne servent "
                "que pendant une calibration. Propose de la lancer (barehands_calibrate) si l'utilisateur le veut.",
            )
        if name in ("calibration_accept_trial", "calibration_commit_proposal"):
            quote = str((payload or {}).get("userQuote") or "")
            found, why = registry.consent(quote, proposal=name == "calibration_commit_proposal")
            if not found:
                self.journal.emit("barehands.calibration_refused", f"{name} refusée : accord introuvable",
                                  level="warning", data={"code": CONSENT_MISSING, "command": name,
                                                         "quote_chars": len(quote)})
                if name == "calibration_commit_proposal":
                    return self._barehands_error(
                        409, CONSENT_MISSING,
                        f"Rien n'a été appliqué : {why}. Valider une proposition appartient à l'utilisateur ; "
                        "demande-lui s'il veut l'appliquer (ou qu'il clique dans le panneau), puis recopie ses "
                        "mots exacts.",
                    )
                return self._barehands_error(
                    409, CONSENT_MISSING,
                    f"Rien n'a été rangé : {why}. Garder un réglage exige que l'utilisateur l'ait demandé "
                    "lui-même ; demande-lui s'il veut garder ce réglage, puis recopie ses mots exacts.",
                )
        return None

    def _calibration_follow(self, name: str, answer: dict[str, Any]) -> None:
        """Tenir la fenêtre d'accord à jour d'après ce que la page a **constaté**."""

        if answer.get("outcome") != "applied":
            return
        result = answer.get("result") if isinstance(answer.get("result"), dict) else {}
        registry = self.barehands_calibration
        if name == "calibration_prepare_trial":
            proposal = result.get("proposal") if isinstance(result.get("proposal"), dict) else {}
            registry.proposal_prepared(str(proposal.get("ref") or "") or None)
        elif name == "calibration_commit_proposal":
            registry.proposal_closed()
            if result.get("action") == "rerun":
                registry.trial_applied(str(result.get("trialRef") or "") or None)
            else:
                registry.trial_closed()
        elif name == "calibration_accept_trial" or (name == "calibration_rollback_trial" and not result.get("active")):
            registry.trial_closed()

    async def barehands_calibration_session_get(self, request: web.Request) -> web.Response:
        """État de la séance vue par le serveur : `{active, session, exercise, age_ms, expires_in_ms, trial}`."""

        if request.query:
            return self._barehands_error(400, BAD_REQUEST, "unexpected query")
        return web.json_response(self.barehands_calibration.status())

    async def barehands_calibration_session_report(self, request: web.Request) -> web.Response:
        """La page déclare, confirme ou ferme sa séance : `{session, active, exercise?}`."""

        if request.query:
            return self._barehands_error(400, BAD_REQUEST, "unexpected query")
        try:
            raw = await scene_wire.read_bounded_body(request, MAX_COMMAND_REQUEST_BYTES)
        except scene_wire.SceneBodyTooLarge:
            return self._barehands_error(413, BAD_REQUEST, f"la déclaration dépasse {MAX_COMMAND_REQUEST_BYTES} octets")
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
            if not isinstance(body, dict) or set(body) - {"session", "active", "exercise", "trial"}:
                raise BarehandsCommandError(BAD_REQUEST, "corps attendu : {session, active, exercise?, trial?}", 400)
            if body.get("active") is True and not self.barehands_commands.enabled():
                # Éteint, pas de séance : le cerveau n'a pas d'outils Bare Hands.
                raise BarehandsCommandError("barehands_disabled", "Bare Hands est éteint : aucune séance.", 409)
            return web.json_response(self.barehands_calibration.report(
                body.get("session"), body.get("active"), body.get("exercise"), body.get("trial")))
        except BarehandsCommandError as exc:
            return self._barehands_error(exc.status, exc.code, str(exc))
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            return self._barehands_error(400, BAD_REQUEST, f"déclaration illisible : {type(exc).__name__}")

    async def barehands_calibration_event(self, request: web.Request) -> web.Response:
        """Un exercice vient de se terminer, ou le rapport s'affiche : le cerveau l'analyse à voix haute.

        Réponse immédiate (`{ok, queued}`) : l'analyse part en tâche de fond.
        Seule la page qui tient la séance peut en envoyer (409 sinon).
        """

        if request.query:
            return self._barehands_error(400, BAD_REQUEST, "unexpected query")
        try:
            raw = await scene_wire.read_bounded_body(request, MAX_CALIBRATION_EVENT_BYTES)
        except scene_wire.SceneBodyTooLarge:
            return self._barehands_error(413, BAD_REQUEST, f"l'événement dépasse {MAX_CALIBRATION_EVENT_BYTES} octets")
        try:
            event = parse_calibration_event(json.loads(raw.decode("utf-8")) if raw else None)
        except BarehandsCommandError as exc:
            return self._barehands_error(exc.status, exc.code, str(exc))
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            return self._barehands_error(400, BAD_REQUEST, f"événement illisible : {type(exc).__name__}")
        if self._calibration_context() is None or self.barehands_calibration.holder() != event["session"]:
            return self._barehands_error(409, "barehands_calibration_inactive",
                                         "Cette page ne tient pas la séance de calibration.")
        # Chaque événement entre dans le fil de la séance, que le cerveau lit à
        # chaque tour ; seuls la revue et le rapport ouvrent un tour d'analyse.
        self.barehands_calibration.record_event(event)
        self.journal.emit("barehands.calibration_event_recorded", describe_calibration_event(event),
                          data={"type": event["type"], "revision": event["revision"], "stage": event.get("stage"),
                                "source": event.get("source")})
        if event["type"] in ANALYSED_EVENT_TYPES:
            return web.json_response({"ok": True, "queued": self._queue_calibration_event(event),
                                      "revision": event["revision"]})
        return web.json_response({"ok": True, "queued": False, "revision": event["revision"]})

    def _queue_calibration_event(self, event: dict[str, Any]) -> bool:
        agent = self.agent
        if not callable(getattr(agent, "publish_notice", None)):
            # Codex n'a pas de voie de relais : l'analyse n'aurait personne pour la dire.
            self.journal.emit("barehands.calibration_event_unsupported",
                              "événement de calibration non analysé : l'agent ne sait pas parler de lui-même",
                              level="warning", data={"type": event["type"], "agent_cli": self._agent_id})
            return False
        self._calibration_event_next = event
        task = self._calibration_event_task
        if task is None or task.done():
            self._calibration_event_task = asyncio.create_task(self._calibration_event_loop())
        return True

    async def _calibration_event_loop(self) -> None:
        while (event := self._calibration_event_next) is not None:
            self._calibration_event_next = None
            try:
                await self._analyse_calibration_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - une analyse ratée ne doit pas tuer la suivante
                self.journal.emit("barehands.calibration_event_failed", f"analyse de calibration en échec : {exc}",
                                  level="error", data={"type": event["type"], "error": type(exc).__name__})

    async def _analyse_calibration_event(self, event: dict[str, Any]) -> None:
        """Accusé de réception dit tout de suite, puis un tour du cerveau dont la réponse est dite.

        Les deux relais sont typés (Slice 03, `jarvis/domain/brain_notice.py`) :
        l'accusé est un `ack` transitoire (`CALIBRATION_ACK_TTL_S`), l'analyse
        un `result`, et ils partagent `calibration_notice_key(event)` — l'analyse
        remplace l'accusé qui n'a pas encore démarré, un accusé resté en file
        expire au lieu d'être dit en retard. Le Control Center choisit le genre
        et la clé, jamais les mots de l'analyse (Décision 14).
        """

        calibration = self._calibration_context()
        if calibration is None:
            return
        agent = self.agent
        key = calibration_notice_key(event)
        agent.publish_notice(CALIBRATION_ANALYSIS_ACK, origin="calibration_ack", kind=SpeechKind.ACK,
                             supersedes_key=key, ttl_s=CALIBRATION_ACK_TTL_S)
        text = render_calibration_event(event)
        summary = (f"[calibration] {event.get('label') or event.get('stage') or 'exercice'} terminé"
                   if event["type"] == "review_ready" else "[calibration] rapport final")
        self.journal.emit("barehands.calibration_event", summary,
                          data={"type": event["type"], "stage": event.get("stage"), "status": event.get("status"),
                                "lines": len(event.get("lines") or event.get("stages") or [])})
        # `source: system` : ce tour n'est pas une parole de l'utilisateur, il
        # ne peut donc porter aucun accord de garder un réglage (décision 53).
        context = {"addressing": AddressingDecision.ADDRESSED.value, "source": "system", "calibration": calibration}
        settings = self._settings()
        from jarvis.runtime.prompt_overrides import prompt_override_document
        from jarvis.runtime.prompt_runtime import (
            accepts_keyword_argument,
            accepts_prompt_evidence,
            compose_agent_turn,
        )
        prompt, evidence = compose_agent_turn(
            agent_id=self._agent_id, model=agent.model or None, request_text=text,
            overrides=prompt_override_document(settings),
            behavior_active=bool(agent_behavior.prompt_instruction(settings)), context=context, agent=agent,
        )
        kwargs: dict[str, object] = {"timeout_s": CALIBRATION_EVENT_TIMEOUT_S}
        if evidence is not None and accepts_prompt_evidence(agent.ask):
            kwargs["prompt_evidence"] = evidence
        if accepts_keyword_argument(agent.ask, "input_text"):
            kwargs["input_text"] = summary
        result = await agent.ask(prompt, **kwargs)
        if not result.get("ok"):
            self.journal.emit("barehands.calibration_event_failed", "le cerveau n'a pas analysé les résultats",
                              level="warning", data={"type": event["type"], "code": result.get("code"),
                                                     "error": str(result.get("error") or "")[:200]})
            return
        # **Une analyse caduque se tait** (retour du 28/09) : si l'étape a été
        # validée, refaite ou passée pendant que le cerveau réfléchissait (ou
        # qu'une nouvelle revue est arrivée), sa réponse parle d'un écran qui
        # n'existe plus. Elle est journalisée, pas dite.
        if self.barehands_calibration.superseded(int(event["revision"])):
            self.journal.emit("barehands.calibration_analysis_stale",
                              "analyse de calibration périmée par une décision plus récente : non dite",
                              data={"type": event["type"], "revision": event["revision"]})
            return
        agent.publish_notice(str(result.get("text") or ""), origin="calibration_analysis", kind=SpeechKind.RESULT,
                             supersedes_key=key)

    async def barehands_command_receipt(self, request: web.Request) -> web.Response:
        """Reçu de la page pour une commande remise : ce qu'elle a **constaté**.

        Origine vérifiée par le middleware, comme tout POST. Identifiant de la
        forme attendue (404 sinon), corps borné, reçu strictement validé : un
        refus sans code connu est refusé ici plutôt que recopié au cerveau.

        La borne et le schéma sont ceux de **la commande attendue** : 1 Ko et
        quatre champs pour le cycle de vie (inchangé), 16 Ko et un `result`
        fermé pour la calibration (Slice 06 adaptative).
        """

        if request.query:
            return self._barehands_error(400, BAD_RECEIPT, "unexpected query")
        command_id = request.match_info["command_id"]
        expected = self.barehands_commands.expected(command_id)
        limit = MAX_CALIBRATION_RECEIPT_BYTES if is_calibration_command(expected) else MAX_RECEIPT_BYTES
        try:
            raw = await scene_wire.read_bounded_body(request, limit)
        except scene_wire.SceneBodyTooLarge:
            self._receipt_rejected(command_id, expected, RECEIPT_TOO_LARGE, f"le reçu dépasse {limit} octets")
            return self._barehands_error(413, BAD_RECEIPT, f"le reçu dépasse {limit} octets")
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
            # Commande inconnue ou déjà rendue : `parse_receipt` d'avant juge la
            # forme, puis le courtier refuse l'identifiant (404) avec sa ligne.
            receipt = parse_command_receipt(expected or COMMAND_UNKNOWN, body)
            return web.json_response(self.barehands_commands.complete(command_id, receipt))
        except BarehandsCommandError as exc:
            if exc.code == BAD_RECEIPT:
                self._receipt_rejected(command_id, expected, RECEIPT_INVALID, str(exc))
            return self._barehands_error(exc.status, exc.code, str(exc), exc.command_id)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            # `RecursionError` : un JSON imbriqué à l'extrême (8 000 crochets)
            # tient sous la borne d'octets ; c'est un reçu illisible, pas une panne.
            self._receipt_rejected(command_id, expected, RECEIPT_INVALID, f"reçu illisible : {type(exc).__name__}")
            return self._barehands_error(400, BAD_RECEIPT, f"reçu illisible : {type(exc).__name__}")

    def _receipt_rejected(self, command_id: str, expected: str | None, code: str, detail: str) -> None:
        """Le reçu de la commande attendue est refusé : le cerveau l'apprend **tout de suite**, nommé."""

        if expected is None:
            return
        self.barehands_commands.fail(command_id, BarehandsCommandError(
            code,
            f"La page a répondu à {expected}, mais son reçu a été refusé ({detail[:160]}). Elle a peut-être "
            "agi : n'annonce ni succès ni échec, relis l'état (calibration_status pour une calibration) "
            "avant toute autre chose.",
            502, command_id[:8]))

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
        # La consigne de la passerelle n'apparaît que là où elle est déclarée (ARCH E20).
        from jarvis.runtime.prompt_runtime import declares_tools_gateway
        if agent_id == "claude":
            targets.extend((
                ("Système du backend Claude", PromptTarget(
                    "backend", None, "claude", agent_model, None,
                    "conversation_tools_session" if self.tools_mcp is not None else "conversation_session"), {}),
                ("Exécution de travail Claude", PromptTarget(
                    "backend", None, "claude", agent_model, None, "job_result_session"), {}),
                ("Analyse spéculative Claude", PromptTarget(
                    "backend", None, "claude", agent_model, None, "speculative_session"), {}),
                ("Préparation Presentation Claude", PromptTarget(
                    "backend", None, "claude", agent_model, None, "presentation_preparation_session"), {}),
            ))
        targets.append(("Tour du backend", PromptTarget(
            "backend", None, agent_id, agent_model, None,
            "tools_turn" if agent_id == "codex" and declares_tools_gateway(self.agent) else "turn",
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
        if voice.get("brain_compatibility") is True:
            # Retour au mode continu où chaque tour part au cerveau Claude du
            # Control Center (sous-agents, historique de console). Le choix
            # explicite est retiré : sans lui, `load_voice_architecture`
            # reprend la projection de compatibilité. Aucun autre choix de
            # l'onglet ne mène à ce mode ; sans ce chemin, un clic sur
            # « Utiliser explicitement cette architecture » le perdait pour
            # de bon (17/09/2026).
            current.pop("voice_architecture", None)
            self._store_voice_arch(current, "continuous_brain")
        elif "architecture" in voice:
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

    # ------------------------------------------------------------------ catalogue MCP (Slice 06)

    #: États où une session cerveau est vivante, donc redémarrable pour prendre
    #: un changement : Claude tient un processus (`running`) ; Codex lance un
    #: processus par tour et reste `ready` entre deux tours (session ouverte).
    _LIVE_AGENT_STATES = frozenset({"running", "ready"})

    def _mcp_availability(self) -> dict[str, dict[str, Any]]:
        """Disponibilité de chaque serveur MCP, recalculée à chaque requête (contrat §4.3).

        Faits, jamais devinés :
        - `condition_value` : l'interrupteur dans les réglages (`load_scene_gate`,
          variable d'environnement comprise ; `barehands.load`), affiché ;
        - `declared` (→ `next_launch`) : la cible que **l'agent** tient
          (`agent.display_mcp`…), ce que son prochain lancement passera
          vraiment au CLI ; un agent sans l'attribut (Codex) n'en reçoit
          jamais → `False` ;
        - `advertised` : drapeau de l'instantané du processus en cours ; pour
          un agent qui ne reçoit jamais de serveur natif, `False` prouvé quel
          que soit son état ; instantané en panne → `None` (journalisé) ;
        - `live` : session vivante (`_LIVE_AGENT_STATES`), seule condition
          d'un `pending_restart`.
        Ni outil invoqué, ni serveur lancé, ni configuration utilisateur du CLI lue.
        """

        settings = self._settings()
        agent = self.agent
        try:
            snapshot: dict[str, Any] | None = agent.snapshot()
        except Exception as exc:  # noqa: BLE001 - un instantané illisible rend `advertised` inconnu, jamais un 500
            snapshot = None
            self.journal.emit(
                "mcp.availability_failed",
                f"Instantané de l'agent illisible pour le catalogue MCP : {type(exc).__name__}",
                level="warning",
                data={"code": "agent_snapshot_failed", "error": type(exc).__name__},
            )
        live = None if snapshot is None else snapshot.get("state") in self._LIVE_AGENT_STATES
        conditions = {
            "scene.enabled": bool(load_scene_gate(settings)["enabled"]),
            "barehands.enabled": bool(barehands.load(settings)["enabled"]),
        }
        # `jarvis-tools` : comme la console, sans interrupteur ; l'agent reçoit sa
        # cible `tools_mcp` à partir de la Slice 05 (plugins MCP), absente = `disabled`.
        attributes = {"jarvis-display": "display_mcp", "jarvis-barehands": "barehands_mcp",
                      "jarvis-console": "console_mcp", "jarvis-tools": "tools_mcp"}
        facts: dict[str, dict[str, Any]] = {}
        for meta in mcp_catalog.SERVERS:
            attribute = attributes.get(meta.server)
            declared: bool | None = None
            advertised = mcp_catalog.advertised_from_agent_snapshot(meta.server, snapshot)
            if attribute is not None:
                receives = hasattr(agent, attribute)
                declared = receives and getattr(agent, attribute) is not None
                if not receives:
                    advertised = False
            facts[meta.server] = mcp_catalog.availability(
                meta.server,
                condition_value=conditions.get(meta.condition) if meta.condition else None,
                declared=declared,
                advertised=advertised,
                live=live,
            )
        return facts

    async def _mcp_catalog(self) -> tuple[dict[str, Any] | None, web.Response | None]:
        """Le catalogue en cache, ou la réponse 503 codée qui dit pourquoi il manque (journalisée)."""

        try:
            catalog = await mcp_catalog.cached_catalog()
        except Exception as exc:  # noqa: BLE001 - toute panne de construction devient un refus codé, jamais un 500 muet
            self.journal.emit(
                "mcp.catalog_failed",
                f"Catalogue MCP impossible à construire : {type(exc).__name__}",
                level="error",
                data={"code": mcp_catalog.CATALOG_UNAVAILABLE, "error": type(exc).__name__},
            )
            # Classe seulement : un message d'import peut porter un chemin local.
            return None, web.json_response(
                {"ok": False, "code": mcp_catalog.CATALOG_UNAVAILABLE,
                 "error": f"MCP catalog could not be built ({type(exc).__name__})"},
                status=503,
            )
        if not self._mcp_catalog_reported:
            self._mcp_catalog_reported = True
            self.journal.emit(
                "mcp.catalog_built",
                f"Catalogue MCP : {len(catalog['tools'])} outils, {len(catalog['servers'])} serveurs décrits",
                data={"tools": len(catalog["tools"]), "servers": [entry["server"] for entry in catalog["servers"]],
                      "unavailable": [dict(entry) for entry in catalog["unavailable"]]},
            )
        return catalog, None

    #: Attente de Core pour la partie « plugins » de la vue fusionnée (ARCH §6.3).
    MCP_EXTERNAL_TIMEOUT_S = 2.0

    async def _mcp_external(self) -> dict[str, Any] | None:
        """Plugins et outils externes de Core (`GET /v1/mcp/tools`, cache par révision), ou `None` s'il ne répond pas.

        Core injoignable, lent (> 2 s) ou sans transport : les natifs restent
        servis, l'entrée `plugins` dit `core_unreachable`. Journalisé une fois par
        panne, une fois au retour.
        """

        if self.sessions is None:
            return None
        cached = self._mcp_external_cache
        try:
            payload = await asyncio.wait_for(
                self.sessions.mcp_tools(since_revision=None if cached is None else cached["catalog_revision"],
                                        timeout_s=self.MCP_EXTERNAL_TIMEOUT_S),
                self.MCP_EXTERNAL_TIMEOUT_S + 0.5)
        except (CoreProtocolError, aiohttp.ClientError, OSError, TimeoutError) as exc:
            if not self._mcp_external_down:
                self._mcp_external_down = True
                self.journal.emit("mcp.plugins_unreachable",
                                  f"Plugins MCP absents du catalogue : Core ne répond pas ({type(exc).__name__})",
                                  level="warning",
                                  data={"code": mcp_catalog.CORE_UNREACHABLE, "error": type(exc).__name__,
                                        "status": getattr(exc, "status", None)})
            return None
        if self._mcp_external_down:
            self._mcp_external_down = False
            self.journal.emit("mcp.plugins_restored", "Plugins MCP de nouveau dans le catalogue",
                              data={"catalog_revision": payload.get("catalog_revision")})
        if payload.get("unchanged") and cached is not None:
            return cached
        self._mcp_external_cache = payload
        return payload

    async def _mcp_merged(self) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]], web.Response | None]:
        """Catalogue natif (en cache) fusionné avec les plugins de Core, et les faits de disponibilité du moment."""

        catalog, refusal = await self._mcp_catalog()
        if refusal is not None:
            return None, {}, refusal
        skipped: list[str] = []
        merged = mcp_catalog.merge_external(catalog, await self._mcp_external(), skipped=skipped)
        # Une fois par ensemble ignoré, pas à chaque rafraîchissement de la page.
        if skipped and tuple(skipped) != getattr(self, "_mcp_skipped_logged", ()):
            self._mcp_skipped_logged = tuple(skipped)
            self.journal.emit("mcp.catalog.descriptor_skipped", "Descripteur d'outil de plugin illisible : ignoré",
                              level="warning", data={"code": mcp_catalog.TOOL_DESCRIPTOR_INVALID,
                                                     "count": len(skipped), "tool_ids": skipped[:20]})
        return merged, {**self._mcp_availability(), **mcp_catalog.plugin_facts(merged)}, None

    async def mcp_tools(self, request: web.Request) -> web.Response:
        """`GET /api/mcp/tools` : serveurs (natifs + plugins) + cartes compactes, ordre §8, disponibilité du moment."""

        del request
        merged, facts, refusal = await self._mcp_merged()
        if refusal is not None:
            return refusal
        return web.json_response(mcp_catalog.list_view(merged, facts))

    async def mcp_tool_detail(self, request: web.Request) -> web.Response:
        """`GET /api/mcp/tools/{server}/{name}` : descripteur complet §2 (natif ou plugin) + disponibilité ; inconnu → 404 codé."""

        merged, facts, refusal = await self._mcp_merged()
        if refusal is not None:
            return refusal
        status, body = mcp_catalog.detail_view(merged, request.match_info["server"], request.match_info["name"], facts)
        return web.json_response(body, status=status)

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

    async def scene_capture_upload(self, request: web.Request) -> web.Response:
        """PNG rendu par la page meneuse visible pour une capture demandée par le cerveau (Slice 09, partie 2).

        Origine vérifiée par le middleware (`_origin_guard`, comme tout POST).
        L'identifiant doit avoir la forme d'une capture (404 sinon) ; corps ≤ 2 MiB
        (413), PNG complet de 1280×720 au plus (400 `invalid_png`), vérifiés ici
        avant tout appel, puis relayés à Core, qui exige une capture en attente
        et non échue (404 `unknown_capture`, 410 `capture_expired`). Aucune
        route ne **demande** une capture : seul le cerveau le peut, par Core.
        """

        if request.query:
            return self._scene_error(400, scene_wire.INVALID_REQUEST, "unexpected query")
        capture_id = request.match_info.get("capture_id", "")
        try:
            check_capture_id(capture_id)
        except ValueError as exc:
            return self._scene_error(404, UNKNOWN_CAPTURE, str(exc))
        try:
            png = await scene_wire.read_bounded_body(request, MAX_CAPTURE_BYTES)
        except scene_wire.SceneBodyTooLarge:
            self.journal.emit("scene.capture_upload_refused", "capture refusée : trop grosse", level="warning",
                              data={"capture": capture_id[:8], "code": scene_wire.PAYLOAD_TOO_LARGE})
            return self._scene_error(413, scene_wire.PAYLOAD_TOO_LARGE, f"capture exceeds {MAX_CAPTURE_BYTES} bytes")
        try:
            width, height = png_dimensions(png)
        except ValueError as exc:
            self.journal.emit("scene.capture_upload_refused", "capture refusée : PNG invalide", level="warning",
                              data={"capture": capture_id[:8], "code": INVALID_PNG, "bytes": len(png)})
            return self._scene_error(400, INVALID_PNG, str(exc))
        if self.scene_view is None:
            return self._scene_error(503, NOT_CONFIGURED, "Capture de scène : Core non configuré.")
        status, body = await self.scene_view.upload_capture(capture_id, png, width=width, height=height)
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

    #: Corps de `POST /api/agent/restart` : `{}` ou `{"new_conversation": bool}`.
    AGENT_RESTART_MAX_BYTES = 256

    async def agent_restart(self, request: web.Request) -> web.Response:
        """Redémarrer le brain. Sans corps : même conversation reprise (comportement historique).

        `{"new_conversation": true}` (écran de la scène, Slice 11) : conversation
        neuve, seule façon qu'une consigne système changée s'applique ; le CLI
        fige la consigne d'une conversation reprise.
        """

        new_conversation = await self._restart_options(request)
        from jarvis.runtime.prompt_runtime import accepts_keyword_argument

        self.journal.emit("agent.restart", "Brain restart requested", data={"new_conversation": new_conversation})
        try:
            if new_conversation and self.sessions is not None:
                # Slice 04a : nouvelle Session Core, CLI neuf, ancien rétrogradé.
                fresh = await self._restart_in_new_session()
                if fresh is not None:
                    return web.json_response(fresh)
            if new_conversation and accepts_keyword_argument(self.agent.restart, "resume"):
                return web.json_response(await self.agent.restart(resume=False))
            # Codex repart toujours sur un fil neuf ; un agent sans l'option garde son redémarrage.
            return web.json_response(await self.agent.restart())
        except RuntimeError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc

    async def _restart_options(self, request: web.Request | None) -> bool:
        if request is None or not request.can_read_body:
            return False
        try:
            raw = await scene_wire.read_bounded_body(request, self.AGENT_RESTART_MAX_BYTES)
        except scene_wire.SceneBodyTooLarge as exc:
            raise web.HTTPRequestEntityTooLarge(max_size=self.AGENT_RESTART_MAX_BYTES, actual_size=request.content_length or 0,
                                                text="restart body too large") from exc
        if not raw.strip():
            return False
        try:
            payload = loads_strict_json(raw, invalid_message="restart body must be JSON")
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        if not isinstance(payload, dict) or set(payload) - {"new_conversation"} or not isinstance(payload.get("new_conversation", False), bool):
            raise web.HTTPBadRequest(text='restart body must be {} or {"new_conversation": true|false}')
        return payload.get("new_conversation", False)

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
        # Routage par conversation (Slice 04a) : Core nomme la conversation du
        # tour. Inconnue ou absente (passerelle legacy, panneau) -> foreground ;
        # celle d'une liaison rétrogradée -> 409, jamais servie par un autre cerveau.
        scope = SubagentConversationScope.from_payload(payload.get("conversation"))
        target = self.board_brains.find(scope.conversation_id if scope is not None else None)
        if target is None and scope is not None and scope.conversation_id:
            target = await self._realign_foreground(scope.conversation_id)
        if target is not None and target is not self.board_brains.foreground:
            self.journal.emit(
                "board_brain.ask_refused", "Tour adressé à un cerveau de Board qui n'est pas au premier plan",
                level="warning",
                data={"code": BoardErrorCode.BRAIN_NOT_FOREGROUND.value, "conversation_id": target.key,
                      "board_id": target.board_id, "lifecycle": target.lifecycle.value},
            )
            return self._binding_error(
                409, BoardErrorCode.BRAIN_NOT_FOREGROUND.value,
                f"le cerveau du Board {target.board_id} n'est pas au premier plan ({target.lifecycle.value})",
            )
        # `context` est optionnel et ne l'était pas avant : la passerelle legacy
        # et le panneau navigateur appellent sans, et reçoivent alors exactement
        # le texte d'avant. Seul Core, qui connaît l'état public, le remplit.
        context = payload.get("context")
        if isinstance(context, dict) and context.get("session_context") is not None:
            # Context actif (Slice 03 session-context) : son dossier doit être
            # accordé au CLI qui sert ce tour. Relancé avant le tour seulement si
            # rien d'autre n'est en vol ; sinon au prochain point sûr (et dit).
            self._learn_sessions_root(sessions_root(context.get("session_context")), source="turn")
            if self._lacks_workspace_grant(self.agent):
                async with self._agent_lock:
                    await self._refresh_foreground_launch(self.board_brains.foreground, reason="workspace_grant")
        # **Mode calibration** (Slice 06 adaptative, décision 51). La séance est
        # tenue ici — c'est la page qui la déclare au Control Center —, donc le
        # drapeau est joint ici plutôt que par Core : le faire transiter par Core
        # ajouterait un aller-retour et un second propriétaire d'un état qui
        # n'est pas le sien. Absent hors séance : le contexte est celui d'avant.
        calibration = self._calibration_context()
        if calibration is not None:
            base = dict(context) if isinstance(context, dict) else {"addressing": AddressingDecision.ADDRESSED.value}
            # Seule une phrase **adressée** de l'utilisateur peut porter l'accord
            # de garder un réglage : ni un tour incertain ou ambiant (télévision,
            # tiers), ni un tour que Core ouvre lui-même (`source: system`, le
            # réveil de travail de fond) — décision 53, reprise QA.
            if (str(base.get("addressing") or "") == AddressingDecision.ADDRESSED.value
                    and str(base.get("source") or "") != "system"):
                self.barehands_calibration.note_user_turn(text)
            context = {**base, "calibration": calibration}
        settings = self._settings()
        behavior_active = bool(agent_behavior.prompt_instruction(settings))
        # Toujours par le composeur : sans contexte ni comportement il rend le texte
        # tel quel, sauf si le tour déclare la passerelle (couche outils, E20).
        from jarvis.runtime.prompt_overrides import prompt_override_document
        from jarvis.runtime.prompt_runtime import compose_agent_turn
        prompt, evidence = compose_agent_turn(
            agent_id=self._agent_id, model=self.agent.model or None, request_text=text,
            overrides=prompt_override_document(settings), behavior_active=behavior_active,
            context=context if isinstance(context, dict) else None, agent=self.agent,
        )
        from jarvis.runtime.prompt_runtime import accepts_keyword_argument, accepts_prompt_evidence
        supports_evidence = accepts_prompt_evidence(self.agent.ask)
        ask_kwargs: dict[str, object] = {"timeout_s": timeout_s}
        if evidence is not None and supports_evidence:
            ask_kwargs["prompt_evidence"] = evidence
        if evidence is not None and accepts_keyword_argument(self.agent.ask, "input_text"):
            # The composed model prompt may contain private saved instructions.
            # Native agents use this canonical input only for trace/UI history.
            ask_kwargs["input_text"] = text
        # Conversation Events (Slice 03b): Core names the conversation of the
        # question explicitly; never given to the prompt composer above.
        if scope is not None and accepts_keyword_argument(self.agent.ask, "conversation_scope"):
            ask_kwargs["conversation_scope"] = scope
        self._asks_in_flight += 1
        self._asks_idle.clear()
        try:
            result = await self.agent.ask(prompt, **ask_kwargs)
        finally:
            self._asks_in_flight -= 1
            if self._asks_in_flight == 0:
                self._asks_idle.set()
        # L'identifiant de reprise naît au premier tour : Core l'apprend ici.
        self._schedule_binding_report(self.board_brains.foreground)
        return web.json_response(result)

    async def background_events(self, request: web.Request) -> web.Response:
        """Ce qui s'est passé en arrière-plan, du plus récent au plus ancien."""
        try:
            limit = min(max(int(request.query.get("limit", "40")), 1), MAX_ENTRIES)
        except ValueError:
            limit = 40
        self._advance_background()
        payload = {"ok": True, **self.background.to_payload(limit=limit)}
        if self._background_store_warning:
            payload["store_warning"] = self._background_store_warning
        return web.json_response(payload)

    def _ack_refused(self, reason: str) -> web.Response:
        self.journal.emit("background.ack_refused", f"Acquittement refusé : {reason}", level="warning",
                          data={"code": "invalid_request"})
        return web.json_response({"ok": False, "code": "invalid_request", "error": reason}, status=400)

    async def background_ack(self, request: web.Request) -> web.Response:
        """Marquer vu. Sans `seq`, tout ce qui est connu à cet instant.

        Un `seq` explicite évite d'effacer un événement arrivé entre le rendu
        de la liste et le clic : on n'acquitte que ce qui a été affiché.
        Avec `category`, seule la pastille correspondante est acquittée.
        """
        # Seul un `seq` **absent** veut dire « tout ». Un `seq` illisible (texte,
        # booléen, négatif, nul) acquittait tout, faute d'être un entier : il
        # est refusé (QA 06/07, point 8). Corps vide = `{}` ; JSON cassé = 400.
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            if getattr(request, "body_exists", False):
                return self._ack_refused("corps JSON illisible")
            body = {}
        if not isinstance(body, dict):
            return self._ack_refused("le corps doit être un objet JSON")
        seq = body.get("seq")
        if "seq" in body and (isinstance(seq, bool) or not isinstance(seq, int) or seq < 0):
            return self._ack_refused(f"seq doit être un entier positif ou nul, reçu {seq!r}"[:160])
        category = body.get("category")
        if category is not None and category not in BACKGROUND_CATEGORIES:
            return web.json_response({"ok": False, "code": "invalid_request",
                                      "error": f"catégorie inconnue : {category}"}, status=400)
        cursor = self.background.acknowledge(seq, category=category)
        # Un acquittement doit survivre au redémarrage autant qu'un non-lu. Un
        # échec d'écriture est dit (journal `error`) et rendu : l'état en
        # mémoire est juste, seul son maintien après redémarrage est en jeu.
        persisted = self._save_background()
        return web.json_response({"ok": True, "acknowledged": cursor, "unread": self.background.unread,
                                  "counts": self.background.counts(), "persisted": persisted})

    # ------------------------------------------------- Conversation Events (Slice 04)
    #
    # Contrat : `docs/conversation-events.md`, « Query and live API ». Même
    # forme de page que Core (`conversation_event_query`), lue par
    # `ConversationEventView`. Erreurs explicites `{"ok": false, "code",
    # "error", "core_status"}` : 400 paramètre invalide (jamais sa valeur),
    # 404 événement inconnu ou sans drill-down, 502/503 Core refusé ou injoignable.

    @staticmethod
    def _conversation_error(status: int, code: str, message: str) -> web.Response:
        return web.json_response({"ok": False, "code": code, "error": message, "core_status": None}, status=status)

    async def _conversation_read(self, request: web.Request, allowed: frozenset[str], parse, read) -> web.Response:
        try:
            query = parse(query_params(request.query.items(), allowed))
        except ValueError as exc:
            return self._conversation_error(400, "invalid_request", str(exc))
        try:
            return web.json_response(await read(query))
        except ConversationEventViewError as exc:
            return web.json_response(exc.to_payload(), status=exc.status)

    async def conversations_list(self, request: web.Request) -> web.Response:
        """Conversations par activité la plus récente ; page suivante : `before_sequence=next_cursor`."""
        view = self.conversation_event_view
        return await self._conversation_read(request, CONVERSATIONS_PARAMS, conversations_query,
                                             lambda q: self._encode(encode_summary_page, view.conversations(**q)))

    async def conversation_sessions(self, request: web.Request) -> web.Response:
        view = self.conversation_event_view
        return await self._conversation_read(request, SESSIONS_PARAMS, sessions_query, lambda q: self._encode(
            encode_summary_page, view.sessions(q.pop("conversation_id"), **q)))

    async def conversation_events_page(self, request: web.Request) -> web.Response:
        """Événements après `after_sequence` ; `wait_ms` (≤ 25 s) attend le prochain ajout (long-poll)."""
        view = self.conversation_event_view
        return await self._conversation_read(request, EVENTS_PARAMS, events_query, lambda q: self._encode(
            encode_event_page, view.events(q.pop("conversation_id"), **q, disconnected=lambda: (
                request.transport is None or request.transport.is_closing()))))

    async def conversation_events_lookup(self, request: web.Request) -> web.Response:
        view = self.conversation_event_view
        return await self._conversation_read(request, LOOKUP_PARAMS, lookup_query, lambda q: self._encode(
            encode_event_page, view.lookup(q.pop("field"), q.pop("value"), **q)))

    # -- Slice 06 : transcription lisible, export JSONL, recherche --------------
    #
    # Contrat : `docs/conversation-events.md`, « Readable transcript », « JSONL
    # export », « Search ». Le texte et l'export viennent de Core tels quels :
    # aucun second rendu ici ni dans la page.

    @staticmethod
    def _client_left(request: web.Request):
        return lambda: request.transport is None or request.transport.is_closing()

    async def conversation_transcript(self, request: web.Request) -> web.StreamResponse:
        """Transcription texte rendue par Core, relayée au fil de l'eau (jamais recopiée en entier).

        `mode` = `plain` ou `detailed`, `utc_offset_minutes` = décalage de l'heure
        locale du navigateur (écrit dans l'en-tête du texte). Un navigateur qui part
        annule la construction dans Core.
        """
        try:
            query = transcript_query(query_params(request.query.items(), TRANSCRIPT_PARAMS))
        except ValueError as exc:
            return self._conversation_error(400, "invalid_request", str(exc))
        try:
            stream = await self.conversation_event_view.open_transcript(
                query["conversation_id"], mode=query["mode"], utc_offset_minutes=query["utc_offset_minutes"],
                disconnected=self._client_left(request))
        except ConversationEventViewError as exc:
            return web.json_response(exc.to_payload(), status=exc.status)
        return await self._relay(request, stream, "transcript",
                                 {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"})

    async def conversation_search(self, request: web.Request) -> web.Response:
        """Recherche bornée (contenu public, métadonnées sûres), du plus récent au plus ancien.

        Un navigateur qui part annule la recherche dans Core ; une seule à la fois (429 `search_busy`).
        """
        view = self.conversation_event_view
        return await self._conversation_read(request, SEARCH_PARAMS, search_query, lambda q: self._encode(
            encode_search_page, view.search(q.pop("query"), **q, disconnected=self._client_left(request))))

    async def conversation_export(self, request: web.Request) -> web.StreamResponse:
        """Export JSONL relayé de Core au fil de l'eau (jamais chargé en entier en mémoire).

        Erreur avant l'en-tête : réponse JSON explicite. Coupure de Core ensuite :
        une ligne de journal par épisode et connexion du navigateur fermée, pour
        qu'un fichier incomplet ne passe jamais pour complet (pas de ligne finale).
        """
        try:
            query = export_query(query_params(request.query.items(), EXPORT_PARAMS))
        except ValueError as exc:
            return self._conversation_error(400, "invalid_request", str(exc))
        try:
            stream = await self.conversation_event_view.open_export(query["conversation_id"])
        except ConversationEventViewError as exc:
            return web.json_response(exc.to_payload(), status=exc.status)
        filename = export_filename(query["conversation_id"])
        return await self._relay(request, stream, "export", {
            "Content-Type": f"{EXPORT_MEDIA_TYPE}; charset=utf-8",
            "Content-Disposition": f"attachment; filename=\"{filename}\"", "Cache-Control": "no-store"})

    async def _relay(self, request: web.Request, stream, operation: str, headers: dict[str, str]) -> web.StreamResponse:
        """Relay Core's chunks to the browser; a Core break closes the browser connection (never a clean end)."""
        response = web.StreamResponse(headers=headers)
        try:
            await response.prepare(request)
            if stream.first:
                await response.write(stream.first)
            chunks = stream.rest.__aiter__()
            while True:
                try:
                    chunk = await chunks.__anext__()
                except StopAsyncIteration:
                    break
                except (aiohttp.ClientError, TimeoutError, OSError) as exc:  # Core's side of the relay broke
                    self.conversation_event_view.stream_interrupted(operation, exc)
                    if request.transport is not None:
                        request.transport.close()
                    return response
                await response.write(chunk)  # the browser's side: a reset propagates below
            await response.write_eof()
        except ConnectionResetError:
            # argued: the browser cancelled or closed the download; Core's stream is closed below
            pass
        finally:
            await stream.aclose()
        return response

    @staticmethod
    async def _encode(encode, read) -> dict[str, Any]:
        return encode(await read)

    async def _stored_event(self, request: web.Request):
        """(stored event, None) or (None, error response)."""
        try:
            query_params(request.query.items(), frozenset())
            event_id = check_event_id(request.match_info.get("event_id"))
        except ValueError as exc:
            return None, self._conversation_error(400, "invalid_request", str(exc))
        try:
            stored = await self.conversation_event_view.event(event_id)
        except ConversationEventViewError as exc:
            return None, web.json_response(exc.to_payload(), status=exc.status)
        if stored is None:
            return None, self._conversation_error(404, "conversation_event_not_found",
                                                  "Aucun Conversation Event lisible ne porte cet identifiant.")
        return stored, None

    async def conversation_event_detail(self, request: web.Request) -> web.Response:
        stored, error = await self._stored_event(request)
        return error if error is not None else web.json_response(encode_event_response(stored))

    async def conversation_event_trace(self, request: web.Request) -> web.Response:
        """Preuve diagnostique d'un événement **stocké** : lignes de trace jointes et expurgées.

        Toujours depuis l'événement relu dans Core, jamais depuis un identifiant
        lu dans une ligne de trace. Événement utilisateur : 404
        `trace_not_applicable`. Lecture bornée du fichier dans un thread.
        """
        stored, error = await self._stored_event(request)
        if error is not None:
            return error
        try:
            await asyncio.wait_for(self._trace_slots.acquire(), timeout=TRACE_SLOT_WAIT_S)
        except TimeoutError:
            return self._conversation_error(503, "trace_busy", f"{MAX_TRACE_DRILL_DOWNS} lectures de trace déjà en "
                                            f"cours depuis plus de {TRACE_SLOT_WAIT_S:.0f} s ; réessayez.")
        try:
            body = await asyncio.to_thread(drill_down, stored.event, self.journal.trace_path)
        except TraceNotApplicable:
            return self._conversation_error(404, "trace_not_applicable",
                                            "Les événements utilisateur n'ont pas de trace diagnostique.")
        except Exception as exc:  # noqa: BLE001 - an unreadable or malformed trace is shown, logged, never a bare 500
            code = "trace_unreadable" if isinstance(exc, OSError) else "trace_drill_down_failed"
            self._trace_failure(code, exc, stored.event.event_id)
            return self._conversation_error(503, code, f"Lecture de la trace impossible : {type(exc).__name__}.")
        finally:
            self._trace_slots.release()
        if self._trace_failing:
            self._trace_failing = False
            self._journal_quietly("ui.conversation_event_trace_recovered", "Drill-down de trace à nouveau possible",
                                  "info", {})
        return web.json_response({**body, "sequence": stored.sequence})

    def _trace_failure(self, code: str, exc: Exception, event_id: str) -> None:
        """One journal error per failure episode (a page retrying cannot flood the journal)."""
        if self._trace_failing:
            return
        self._trace_failing = True
        self._journal_quietly("ui.conversation_event_trace_unreadable", "Drill-down de trace en échec", "error",
                              {"code": code, "exception_type": type(exc).__name__, "event_id": event_id})

    def _journal_quietly(self, kind: str, message: str, level: str, data: dict[str, Any]) -> None:
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except Exception:  # noqa: BLE001 - argued: the error response already tells the user; a dead journal cannot be reported to itself
            pass

    async def agent_notices(self, request: web.Request) -> web.Response:
        """Réponses que le brain a produites sans question : relais de fin de sous-agent.

        Attente longue (`wait`, 25 s au plus) : Core interroge en boucle et
        reçoit une réponse dès qu'un relais existe. `epoch` identifie la file :
        un lecteur qui n'en a pas encore reçoit l'époque et le dernier numéro
        sans rien rejouer ; un lecteur dont l'époque a changé (agent recréé)
        reçoit tout ce que la nouvelle file contient déjà.
        """
        entry = self.board_brains.foreground
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
        # Filigrane de promotion (Slice 04a) : ce que cet agent a relayé pendant
        # qu'il était en arrière-plan n'est jamais rejoué comme parole.
        floor = self.board_brains.foreground.notice_floor
        if floor is not None and floor[0] == epoch:
            after = max(after, floor[1])
        notices = await agent.wait_notices(after, timeout_s=wait_s)
        if self.board_brains.foreground is not entry or self.agent is not agent:
            # Reprise QA 04a (B1) : le cerveau a été rétrogradé pendant l'attente.
            # Ses relais ne sont jamais dits ; le lecteur repart de la file du
            # nouveau foreground (époque et dernier numéro), sans rien rejouer.
            current = self.agent
            if notices:
                self.journal.emit("board_brain.notices_withheld",
                                  "Relais d'un cerveau rétrogradé pendant l'attente : non dits",
                                  data={"conversation_id": entry.key, "board_id": entry.board_id,
                                        "count": len(notices)})
            return web.json_response({
                "ok": True, "supported": callable(getattr(current, "wait_notices", None)), "notices": [],
                "epoch": str(getattr(current, "notice_epoch", "") or ""),
                "last_seq": int(getattr(current, "last_notice_seq", 0) or 0),
                "conversation_id": self.board_brains.foreground.key,
            })
        # `conversation_id` : la liaison dont viennent ces relais. Core les
        # passe à sa porte de parole, qui retient ceux d'un Board sans la parole.
        return web.json_response({"ok": True, "supported": True, "notices": notices, "epoch": epoch,
                                  "last_seq": agent.last_notice_seq, "conversation_id": entry.key})

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
                agent=self.agent,
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

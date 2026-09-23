from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import webbrowser

from jarvis.adapters.barehands_board import BarehandsBoardClient
from jarvis.audio.capture import SoundDeviceRecorder
from jarvis.audio.ptt import PTTKeyListener
from jarvis.config import AppConfig
from jarvis.domain.errors import JarvisError
from jarvis.environment import load_project_environment
from jarvis.runtime.crash_guard import install_asyncio_crash_guard, install_crash_guard, report_fatal
from jarvis.runtime.factory import create_runtime
from jarvis.runtime.health import run_health_checks
from jarvis.runtime.voice import VoiceRuntime
from jarvis.security.session_token import generate_session_token


ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="Jarvis local assistant")
    parser.add_argument("--config", help="Path to legacy jarvis.toml")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="Run legacy push-to-talk fallback")
    run.add_argument("--no-preflight", action="store_true")
    text = sub.add_parser("text", help="Run one legacy text turn")
    text.add_argument("message")
    health = sub.add_parser("health", help="Print legacy component health")
    health.add_argument("--skip-audio", action="store_true")
    sub.add_parser("reindex", help="Rebuild the disposable Markdown search index")
    sub.add_parser("core", help="Run persistent v0.2 Core daemon")
    sub.add_parser("voice", help="Run v0.2 wake-word + Realtime Voice client")
    sub.add_parser("control-center", help="Run Jarvis visualizer + Control Center + local Claude agent")
    sub.add_parser("drive-auth", help="Authorize Google Drive access once and store the token")
    sub.add_parser("drive-mcp", help="Serve the Google Drive MCP tools over stdio")
    # Lancée par le CLI du cerveau via `--mcp-config` (scene.enabled), pas par
    # un humain : stdout est le protocole MCP.
    sub.add_parser("display-mcp", help="Serve the brain scene display MCP tools over stdio")
    # Même chose pour Bare Hands (Slice 12), lancée quand l'interrupteur
    # `barehands_test_mode.enabled` est vrai : elle joint le Control Center.
    sub.add_parser("barehands-mcp", help="Serve the brain Bare Hands MCP tools over stdio")
    # Les réglages du Control Center, ouverts au cerveau (20/09/2026, règle de
    # l'utilisateur : ce qu'il fait dans l'interface, JARVIS doit le faire
    # aussi). Contrairement aux deux précédentes, celle-ci est déclarée
    # **sans condition** : c'est elle qui porte les interrupteurs maîtres, donc
    # la retirer avec l'un d'eux enfermerait le cerveau dans l'état éteint.
    sub.add_parser("console-mcp", help="Serve the Control Center settings MCP tools over stdio")
    # Le banc d'essai Bare Hands (Slice 10) : rejouer une trace enregistrée sous
    # plusieurs configurations et comparer des mesures, au lieu de changer un
    # seuil à l'estime et de refaire le geste. Appelée par un développeur.
    replay = sub.add_parser(
        "barehands-replay",
        help="Replay a recorded Bare Hands trace under several configurations and compare metrics")
    replay.add_argument("trace", help="Path to a trace under runtime/barehands-traces/, or the golden trace")
    replay.add_argument(
        "--config", action="append", default=[],
        metavar="NAME=JSON",
        help=("A configuration to replay, e.g. "
              "souple='{\"filter\":{\"minCutoffHz\":0.3}}'. Repeat it: comparing one "
              "configuration to itself says nothing, so at least two are required."))
    replay.add_argument("--json", action="store_true", help="Print the raw comparison as JSON")
    # Appelée par le CLI d'agent lui-même, pas par un humain : elle lit
    # l'appel d'outil sur stdin et rend la décision d'aiguillage sur stdout.
    routing_hook = sub.add_parser("routing-hook", help="Apply the sub-agent routing policy to one agent CLI tool call")
    routing_hook.add_argument("--runtime-root", default="")
    from jarvis.runtime.owner_voice import add_parser as add_owner_voice_parser

    add_owner_voice_parser(sub)
    return parser


def _barehands_replay(args) -> int:
    """Rejouer une trace sous plusieurs configurations, et dire ce qui change.

    RÈGLE ZÉRO, version terminal : la sortie nomme ce qui a **bougé** d'une
    configuration à l'autre. Une table de nombres identiques et un axe sans
    effet se lisent autrement pareil, et on conclurait « ce réglage ne change
    rien » d'un réglage qui n'a pas été appliqué. Un refus dit sa cause au lieu
    de rendre un tableau vide.
    """

    import json as _json

    from jarvis.runtime import barehands_replay

    configs = []
    for raw in args.config or []:
        name, _, body = raw.partition("=")
        if not _:
            print(f"--config attend NOM=JSON ; reçu « {raw} »", file=sys.stderr)
            return 2
        try:
            configs.append({"name": name, "config": _json.loads(body or "{}")})
        except ValueError as exc:
            print(f"--config {name} : JSON illisible ({exc})", file=sys.stderr)
            return 2
    if not configs:
        # Le défaut utile : l'usine contre elle-même ne dirait rien, donc on
        # propose l'usine contre un filtre plus doux, qui est la comparaison
        # que neuf développeurs sur dix veulent faire en premier.
        configs = [{"name": "usine", "config": {}},
                   {"name": "filtre-doux", "config": {"filter": {"minCutoffHz": 0.3}}}]
    try:
        report = barehands_replay.compare(Path(args.trace), configs)
    except barehands_replay.ReplayUnavailable as exc:
        print(f"Rejeu impossible : {exc}", file=sys.stderr)
        return 3
    except (barehands_replay.ReplayFailed, ValueError) as exc:
        print(f"Rejeu refusé : {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(_json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    names = [row["name"] for row in report["rows"]]
    width = max(len(key) for key in barehands_replay.METRIC_KEYS) + 2
    print(f"{'mesure':<{width}}" + "".join(f"{name:>22}" for name in names))
    for key in barehands_replay.METRIC_KEYS:
        cells = []
        for row in report["rows"]:
            value = row["metrics"][key]
            # `null` est une **absence**, et il s'écrit comme telle : « 0 » se
            # lirait « mesuré, et parfait ».
            cells.append("non mesuré" if value is None
                         else f"{value:.6g}" if isinstance(value, float) else str(value))
        moved = " *" if key in report["changed"] else "  "
        print(f"{key:<{width}}" + "".join(f"{cell:>22}" for cell in cells) + moved)
    if report["identical"]:
        print("\nAucune mesure n'a bougé : soit les configurations sont équivalentes, "
              "soit cette trace ne contient rien qui les distingue.")
    else:
        print(f"\n* a bougé : {', '.join(report['changed'])}")
    return 0


async def _drive_auth() -> int:
    from jarvis.adapters.google_drive import GoogleDriveBackend
    from jarvis.domain.drive import DriveQuery
    from jarvis.runtime.drive_mcp import credential_paths

    secret, token = credential_paths()
    print(f"Autorisation Google Drive : un navigateur va s'ouvrir.\nSecret client : {secret}\nJeton : {token}")
    # `run_local_server` bloque jusqu'au consentement : hors du fil principal,
    # la boucle asyncio reste libre d'être interrompue au clavier.
    backend = await asyncio.to_thread(GoogleDriveBackend.from_oauth_files, secret, token)
    files = await backend.list_files(DriveQuery(limit=1))
    print(f"Drive autorisé. Jeton écrit dans {token}.")
    print(f"Vérification : {len(files)} fichier(s) visible(s) dans le Drive.")
    return 0


async def _drive_mcp() -> int:
    from jarvis.runtime.drive_mcp import build_server

    # `run_stdio_async` plutôt que `run` : ce dernier ouvre sa propre boucle,
    # que la boucle du CLI rendrait invalide.
    await build_server().run_stdio_async()
    return 0


async def _display_mcp() -> int:
    from jarvis.runtime.display_mcp import serve_stdio

    return await serve_stdio()


async def _barehands_mcp() -> int:
    from jarvis.runtime.barehands_mcp import serve_stdio

    return await serve_stdio()


async def _console_mcp() -> int:
    from jarvis.runtime.settings_mcp import serve_stdio

    return await serve_stdio()


async def _run_voice(config: AppConfig, *, no_preflight: bool) -> int:
    runtime = create_runtime(config, speech_enabled=True)
    if not no_preflight:
        runtime.recorder.preflight()
    await runtime.state.initialize()
    voice = VoiceRuntime(recorder=runtime.recorder, transcriber=runtime.transcriber, orchestrator=runtime.orchestrator, logger=runtime.logger)
    ptt = PTTKeyListener(config.runtime.ptt_key, on_press=voice.press, on_release=voice.release)
    print(f"Jarvis PTT fallback prêt. Maintenez {config.runtime.ptt_key.upper()} pour parler.")
    try:
        await ptt.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        ptt.stop(); runtime.recorder.abort(); await runtime.state.cleanup()
    return 0


async def _run_text(config: AppConfig, message: str) -> int:
    runtime = create_runtime(config, speech_enabled=False)
    await runtime.state.initialize()
    try:
        result = await runtime.orchestrator.handle_text(message)
        print(result.text)
        if result.awaiting_confirmation:
            print(f"[confirmation:{result.action_id}]", file=sys.stderr)
        return 0
    finally:
        await runtime.state.cleanup()


async def _health(config: AppConfig, *, skip_audio: bool) -> int:
    token = generate_session_token()
    board = BarehandsBoardClient(config.board.url, token) if config.board.enabled else None
    recorder = SoundDeviceRecorder(sample_rate=config.audio.sample_rate, channels=config.audio.channels, input_device=config.audio.input_device)
    report = await run_health_checks(config, board=board, check_audio=not skip_audio, recorder=recorder)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 1 if report.status == "fail" else 0


async def _reindex(config: AppConfig) -> int:
    from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
    memory = MarkdownMemoryBackend(config.runtime.memory_dir)
    count = await memory.rebuild_index()
    print(f"Index reconstruit depuis Markdown: {count} document(s).")
    return 0


def _write_session_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(token, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _calendar_backend_from_env():
    provider = os.getenv("JARVIS_CALENDAR_PROVIDER", "fake").strip().lower()
    if provider in {"", "fake", "none"}:
        return None
    if provider != "google":
        raise RuntimeError(f"Unsupported calendar provider: {provider}")
    from jarvis.adapters.google_calendar import GoogleCalendarBackend
    secret = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET")
    token = os.getenv("GOOGLE_CALENDAR_TOKEN")
    if not secret or not token:
        raise RuntimeError("Google Calendar requires GOOGLE_CALENDAR_CLIENT_SECRET and GOOGLE_CALENDAR_TOKEN paths")
    return GoogleCalendarBackend.from_oauth_files(Path(secret), Path(token), calendar_id=os.getenv("GOOGLE_CALENDAR_ID", "primary"))


def _drive_backend_from_env():
    provider = os.getenv("JARVIS_DRIVE_PROVIDER", "none").strip().lower()
    if provider in {"", "none", "fake"}:
        return None
    if provider != "google":
        raise RuntimeError(f"Unsupported drive provider: {provider}")
    from jarvis.adapters.google_drive import GoogleDriveBackend
    # Le même client OAuth sert l'agenda et Drive; seuls les jetons diffèrent,
    # parce qu'un jeton porte les portées accordées.
    secret = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET") or os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET")
    token = os.getenv("GOOGLE_DRIVE_TOKEN")
    if not secret or not token:
        raise RuntimeError("Google Drive requires GOOGLE_DRIVE_CLIENT_SECRET and GOOGLE_DRIVE_TOKEN paths")
    return GoogleDriveBackend.from_oauth_files(Path(secret), Path(token))


def _control_center_url() -> str:
    """Boucle locale du Control Center, hôte de l'agent et de son endpoint."""
    return f"http://127.0.0.1:{int(os.getenv('JARVIS_UI_PORT', '17654'))}"


def _brain_backend_from_env():
    """Construire le `BrainBackend` injecté dans Core (Décisions 23 et 28).

    L'adaptateur vit dans `jarvis/adapters` et n'est jamais importé par
    `jarvis/core` : c'est ici, au composition root, qu'il est assemblé puis
    passé en paramètre, exactement comme l'agenda et Drive.

    Il vise la route agent-agnostique `POST /api/agent/ask` : le choix
    Claude/Codex reste une affaire du Control Center. Si celui-ci n'est pas
    lancé, le backend rend un échec prononçable plutôt qu'une exception.
    """
    from jarvis.adapters.control_center_brain import ControlCenterBrainBackend

    timeout = os.getenv("JARVIS_BRAIN_TIMEOUT_S") or os.getenv("JARVIS_CLAUDE_TIMEOUT_S") or "600"
    return ControlCenterBrainBackend(base_url=_control_center_url(), timeout_s=float(timeout))


def _brain_availability_from_env() -> dict[str, object]:
    """Réglages de disponibilité du cerveau pour Core, actifs par défaut.

    - `JARVIS_SUPERSEDE_STALE_REPLIES` (défaut 0 depuis le 19/09/2026) : une
      nouvelle intention périmait la parole des tours précédents encore en file
      (retour n° 8). L'utilisateur a écarté cette règle mécanique d'ancienneté :
      une réponse encore cohérente doit être dite, et seul le cerveau la retire,
      en nommant son travail. Poser `1` rétablit l'ancien comportement.
    - `JARVIS_BRAIN_TURN_BUDGET_S` (défaut 8) : au-delà, le tour est signalé
      dans la trace (`core.brain.turn_slow`, `core.brain.turn_over_budget`).
    - `JARVIS_WORK_WAKE_INTERVAL_S` (défaut 10) : écart minimal entre deux
      réveils du cerveau par un changement de travail de fond. `0` réveille
      aussi vite que les changements arrivent ; une valeur négative est
      ignorée. Le réveil ne se déclenche jamais pendant un tour en vol.
    """
    from jarvis.core.brain_context import DEFAULT_WAKE_INTERVAL_S
    from jarvis.core.brain_service import DEFAULT_TURN_BUDGET_S

    supersede = os.getenv("JARVIS_SUPERSEDE_STALE_REPLIES", "0").strip().lower() in {"1", "true", "yes", "on"}
    try:
        budget = float(os.getenv("JARVIS_BRAIN_TURN_BUDGET_S") or DEFAULT_TURN_BUDGET_S)
    except ValueError:
        budget = DEFAULT_TURN_BUDGET_S
    raw_wake = os.getenv("JARVIS_WORK_WAKE_INTERVAL_S")
    try:
        wake = DEFAULT_WAKE_INTERVAL_S if raw_wake is None or not raw_wake.strip() else float(raw_wake)
    except ValueError:
        wake = DEFAULT_WAKE_INTERVAL_S
    return {"supersede_stale_replies": supersede,
            "brain_turn_budget_s": budget if budget > 0 else DEFAULT_TURN_BUDGET_S,
            "work_attention_wake_interval_s": wake if wake >= 0 else DEFAULT_WAKE_INTERVAL_S}


#: Borne haute de `JARVIS_SCENE_RESTART_GRACE_S` : au-delà, une étoile morte
#: resterait « état inconnu » plus d'une heure.
MAX_SCENE_RESTART_GRACE_S = 3600.0


def _scene_restart_grace_from_env() -> tuple[float, str | None]:
    """Grâce de redémarrage de la scène (Slice 10) et, si la valeur est refusée, pourquoi.

    `JARVIS_SCENE_RESTART_GRACE_S` (défaut `RESTART_GRACE_S` = 60) : délai
    après le démarrage de Core avant qu'une étoile encore « état inconnu »
    soit interrompue. Réservé à la validation et au diagnostic : sous la
    période de renvoi des producteurs (30 s), un travail vivant serait
    interrompu à tort. Hors de ]0, 3600] ou illisible → défaut, et la raison
    est rendue pour être journalisée.
    """
    from jarvis.core.scene_projector import RESTART_GRACE_S

    raw = os.getenv("JARVIS_SCENE_RESTART_GRACE_S")
    if raw is None or not raw.strip():
        return RESTART_GRACE_S, None
    try:
        value = float(raw)
    except ValueError:
        return RESTART_GRACE_S, f"valeur illisible {raw[:40]!r}"
    if not 0 < value <= MAX_SCENE_RESTART_GRACE_S:
        return RESTART_GRACE_S, f"hors de ]0, {MAX_SCENE_RESTART_GRACE_S:g}] : {value:g}"
    return value, None


def _control_settings(runtime_root: Path) -> dict[str, object]:
    path = runtime_root / "control-center-settings.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _active_timeout_from(overrides: dict[str, object], default: float) -> float:
    """Délai d'activité utile retenu pour Voice, réglages avant environnement.

    "0" (délai désactivé) est une valeur, pas une absence : seul un champ vide
    retombe sur l'environnement. Une valeur invalide écrite à la main dans le
    fichier de réglages retombe elle aussi, plutôt que d'empêcher Voice de
    démarrer.
    """
    from jarvis.domain.errors import ConfigurationError
    from jarvis.v2_config import parse_active_timeout

    raw = overrides.get("active_timeout_s")
    if raw is None or not str(raw).strip():
        return default
    try:
        return parse_active_timeout(raw, name="active_timeout_s")
    except ConfigurationError:
        return default


def _speaker_verifier(overrides: dict[str, object], runtime_root: Path, journal=None):
    """Vérificateur de locuteur à brancher en ombre sur la capture duplex.

    Rien n'est branché — la capture reste exactement celle d'avant — tant que
    la vérification est `off` (défaut), que le réglage est invalide, ou que le
    moteur, son modèle ou le profil du propriétaire manquent (raison
    journalisée). Sinon, le moteur local (`jarvis/runtime/owner_voice.py`)
    observe la capture sans en changer un octet ; en Solo Owner, l'état du
    propriétaire qu'il publie décide seul du barge-in (tâche 05,
    `PersistentVoiceRuntime._barge_in_policy`) et seul ouvre le flux vers le
    fournisseur, que JARVIS parle (tâche 06) ou se taise (tâche 07). Sans
    vérificateur, Solo Owner est refusé à l'activation.
    """
    from jarvis.domain.errors import ConfigurationError
    from jarvis.domain.speaker import SpeakerVerificationMode
    from jarvis.v2_config import parse_conversation_authorization

    try:
        authorization = parse_conversation_authorization(overrides)
    except ConfigurationError:
        return None
    if authorization.verification is SpeakerVerificationMode.OFF:
        return None
    from jarvis.runtime.owner_voice import open_owner_verifier

    try:
        return open_owner_verifier(overrides, runtime_root=runtime_root, journal=journal)
    except Exception as exc:
        # L'ombre ne doit jamais coûter la capture duplex : une erreur ici
        # ferait retomber Voice sur le micro brut.
        if journal is not None:
            journal.emit(
                "voice.owner.unavailable",
                f"Vérificateur de locuteur non branché : {type(exc).__name__}",
                level="warning",
                data={"code": "verifier_open_failed", "error": type(exc).__name__},
            )
        return None


def _conversation_authorization(overrides: dict[str, object], journal=None):
    """Autorisation de conversation retenue par Voice, et l'erreur de réglage éventuelle.

    Rend `(autorisation, erreur)`. Un réglage invalide écrit à la main n'est
    ni deviné ni remplacé par la salle ouverte (tâche 07) : l'erreur part au
    runtime, qui refuse chaque activation en disant pourquoi — Voice reste
    lancée, le mot d'éveil aussi, rien n'écoute. L'autorisation rendue alors
    (salle ouverte) ne s'applique jamais.
    """
    from jarvis.domain.errors import ConfigurationError
    from jarvis.domain.speaker import ConversationAuthorization, ConversationAuthorizationError
    from jarvis.v2_config import parse_conversation_authorization

    try:
        return parse_conversation_authorization(overrides), None
    except ConfigurationError as exc:
        error = (
            exc
            if isinstance(exc, ConversationAuthorizationError)
            else ConversationAuthorizationError("conversation_authorization_invalid", str(exc))
        )
        if journal is not None:
            journal.emit(
                "voice.authorization_invalid",
                f"Réglage de conversation invalide : Voice n'écoutera pas tant qu'il n'est pas corrigé. {exc}",
                level="warning",
                data={"code": error.code},
            )
        return ConversationAuthorization(), error


def _announce_calendar_backend(core, runtime_root: Path) -> None:
    """Dire au démarrage si l'agenda est réel ou seulement en mémoire.

    Sans agenda configuré, Core retombe silencieusement sur un stockage en
    mémoire : `calendar_create` réussit, JARVIS annonce le rendez-vous, et rien
    n'apparaît jamais dans un vrai agenda.
    """
    from jarvis.runtime.journal import RuntimeJournal

    storage = core.calendar.storage
    journal = RuntimeJournal(runtime_root)
    if storage.get("persisted"):
        journal.emit("calendar.backend", f"Agenda connecté : {storage['backend']}", data=storage)
        return
    journal.emit(
        "calendar.backend",
        "Aucun agenda réel n'est configuré : les rendez-vous ne sont gardés qu'en "
        "mémoire et disparaissent à l'arrêt de Core. Définissez "
        "JARVIS_CALENDAR_PROVIDER=google pour les enregistrer réellement.",
        level="warning",
        data={**storage, "code": "calendar_backend_in_memory"},
    )


async def _run_core_v2() -> int:
    from jarvis.adapters.openai_live_sideband import (
        PROVIDER_MAX_SESSION_SECONDS, OpenAILiveSidebandCloser, aiohttp_live_sideband_connector,
    )
    from jarvis.adapters.windows_notifications import NullNotificationDelivery, WindowsNotificationDelivery
    # Slice 09 (partie 2) : captures visuelles de la scène sous runtime/scene-captures/.
    from jarvis.adapters.file_scene_captures import SCENE_CAPTURE_DIR, FileSceneCaptureStore
    from jarvis.core.memory_maintenance import MemoryMaintenanceWorker
    from jarvis.runtime.agent_settings import resolve_agent_execution
    from jarvis.runtime.back_brain_worker import BackBrainJobWorker
    from jarvis.core.v2_app import JarvisCoreApplication
    from jarvis.protocol.server import LocalProtocolServer
    from jarvis.runtime.journal import RuntimeJournal
    from jarvis.runtime import credentials as creds
    from jarvis.v2_config import V2Settings
    settings = V2Settings.load()
    token = generate_session_token()
    _write_session_token(settings.token_file, token)
    delivery = WindowsNotificationDelivery() if os.name == "nt" and os.getenv("JARVIS_WINDOWS_NOTIFICATIONS", "0") in {"1", "true", "yes"} else NullNotificationDelivery()
    agent_execution = resolve_agent_execution(
        _control_settings(settings.runtime_root), cwd=ROOT, runtime_root=settings.runtime_root)
    workers = {
        "memory_maintenance": MemoryMaintenanceWorker(settings.data_root / "memory"),
        "back_brain": BackBrainJobWorker(lambda: agent_execution),
    }
    # Le journal runtime sert de puits de diagnostic à Core : sans lui, l'éviction
    # d'un abonné saturé du bus resterait invisible en production (Décision 25).
    brain_backend = _brain_backend_from_env()
    openai_key = creds.secret_for(_control_settings(settings.runtime_root), "openai")
    live_closer = (OpenAILiveSidebandCloser(aiohttp_live_sideband_connector(openai_key))
                   if openai_key else None)
    scene_grace_s, scene_grace_error = _scene_restart_grace_from_env()
    if scene_grace_error is not None:
        RuntimeJournal(settings.runtime_root).emit(
            "core.scene.restart_grace_invalid",
            "JARVIS_SCENE_RESTART_GRACE_S refusée : grâce par défaut",
            level="warning", data={"error": scene_grace_error, "grace_s": scene_grace_s},
        )
    core = JarvisCoreApplication(data_root=settings.data_root, timezone=settings.timezone, calendar_backend=_calendar_backend_from_env(), drive_backend=_drive_backend_from_env(), brain_backend=brain_backend, notification_delivery=delivery, workers=workers, diagnostics=RuntimeJournal(settings.runtime_root), live_sideband_closer=live_closer, live_provider_max_session_s=PROVIDER_MAX_SESSION_SECONDS, scene_restart_grace_s=scene_grace_s, scene_capture_store=FileSceneCaptureStore(settings.runtime_root / SCENE_CAPTURE_DIR), **_brain_availability_from_env())
    server = LocalProtocolServer(core, host=settings.core_host, port=settings.core_port, token=token)
    _announce_calendar_backend(core, settings.runtime_root)
    RuntimeJournal(settings.runtime_root).emit("brain.backend", "Cerveau relié à l'agent du Control Center", data={"url": brain_backend.base_url})
    try:
        await core.start(); await server.start()
        print(f"Jarvis Core v0.2 ready on http://{settings.core_host}:{settings.core_port}")
        await core.wait()
    finally:
        # Le backend est fermé après Core : `core.stop()` annule d'abord les
        # tâches cerveau, qui tiennent encore la session HTTP à cet instant.
        await server.stop(); await core.stop(); await brain_backend.close(); settings.token_file.unlink(missing_ok=True)
    return 0


async def _run_voice_v2() -> int:
    from jarvis.adapters.gemini_live import GeminiLiveSession
    from jarvis.runtime.realtime_frontend_session import RealtimeFrontendSession
    from jarvis.runtime.live_frontend_session import LiveFrontendSession
    from jarvis.adapters.wakeword_composite import CompositeWakeWordBackend
    from jarvis.adapters.wakeword_keyboard import KeyboardWakeWordBackend
    from jarvis.adapters.wakeword_porcupine import PorcupineWakeWordBackend
    from jarvis.protocol.client import LocalCoreClient
    from jarvis.runtime import credentials as creds, realtime_tools, shortcuts as shortcut_registry, voice_stack
    from jarvis.runtime.audio_devices import normalize_device_id
    from jarvis.runtime.claude_gateway import ClaudeGateway
    from jarvis.runtime.journal import RuntimeJournal
    from jarvis.runtime.realtime_tools import REALTIME_TOOLS
    from jarvis.runtime.visual_signals import VisualSignalBus
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
    from jarvis.runtime.voice_switch import VoiceSwitchBus, VoiceSwitchCoordinator
    from jarvis.domain.errors import ConfigurationError
    from jarvis.v2_config import (DEFAULT_REFLEX_DELAY_MS, REFLEX_DELAY_SETTING, REFLEX_ENABLED_SETTING,
                                 V2Settings, VoiceArchitecture, parse_voice_arch,
                                 recommended_realtime_model, reflex_delay_s, reflex_enabled,
                                 reflex_requires_confirmed_work)
    from jarvis.runtime.voice_composition import resolve_voice_composition
    from jarvis.domain.voice_architecture import DuplexVoiceConfig, FrontBrainVoiceConfig, VoiceConfigError
    settings = V2Settings.load()
    signals = VisualSignalBus(settings.runtime_root)
    signals.offline()
    switch_bus = VoiceSwitchBus(settings.runtime_root)
    overrides = _control_settings(settings.runtime_root)
    from jarvis.runtime.prompt_overrides import prompt_override_document
    prompt_overrides = prompt_override_document(overrides)
    # L'architecture choisie dans le Control Center passe devant
    # JARVIS_VOICE_ARCH. Laissée vide, la variable puis `default_voice_arch()`
    # décident, exactement comme avant que le réglage n'existe.
    arch_override = str(overrides.get("voice_arch") or "").strip()
    try:
        composition = resolve_voice_composition(overrides)
        direct_conversation = composition.direct_conversation
        compatibility = composition.selection.compatibility
        operational_architecture = (
            compatibility.execution_mode
            if compatibility is not None
            else composition.selection.config.architecture.value
        )
        voice_arch = (VoiceArchitecture.LEGACY if direct_conversation else
                      parse_voice_arch(operational_architecture))
    except (ConfigurationError, VoiceConfigError) as exc:
        switch_bus.mark_pending_restart_failed(code="replacement_configuration_invalid")
        raise RuntimeError(
            f"Architecture vocale inconnue ou configuration invalide dans les réglages du Control Center : « {arch_override} ». "
            "Choisissez-la de nouveau dans l'onglet Mode vocal, puis relancez Voice."
        ) from exc
    arch_source = "settings" if arch_override else ("env" if os.getenv("JARVIS_VOICE_ARCH", "").strip() else "default")
    if not settings.token_file.exists():
        switch_bus.mark_pending_restart_failed(code="core_token_missing")
        raise RuntimeError("Core session token is missing; start `jarvis core` first")
    token = settings.token_file.read_text(encoding="utf-8").strip()
    stack = voice_stack.stack_spec(composition.stack_id)
    stack_values = voice_stack.settings_for(overrides, stack.id)
    api_key = creds.secret_for(overrides, stack.credential_provider)
    if not api_key:
        provider = creds.provider_spec(stack.credential_provider)
        env_names = " ou ".join(provider.env) or "la variable du fournisseur"
        switch_bus.mark_pending_restart_failed(code="replacement_credentials_missing")
        raise RuntimeError(
            f"La pile vocale « {stack.label} » a besoin d'une clé {provider.label}. "
            "Ajoutez-la dans l'onglet API Keys des réglages du Control Center, "
            f"ou définissez {env_names} dans le .env du projet, puis relancez Voice."
        )
    core = LocalCoreClient(host=settings.core_host, port=settings.core_port, token=token)
    health = await core.health()
    if not health.get("ready"):
        switch_bus.mark_pending_restart_failed(code="core_not_ready")
        await core.close(); raise RuntimeError(f"Core is not ready: {health}")

    manual_key = shortcut_registry.current(overrides)["wake_toggle"]
    input_raw = overrides.get("audio_input_device") if "audio_input_device" in overrides else os.getenv("JARVIS_AUDIO_INPUT_DEVICE", "")
    output_raw = overrides.get("audio_output_device") if "audio_output_device" in overrides else os.getenv("JARVIS_AUDIO_OUTPUT_DEVICE", "")
    audio_input_device = normalize_device_id(input_raw)
    audio_output_device = normalize_device_id(output_raw)
    wake_backends = [KeyboardWakeWordBackend(key_name=manual_key)]
    wake_key = creds.secret_for(overrides, "porcupine")
    if wake_key:
        wake_backends.append(
            PorcupineWakeWordBackend(
                access_key=wake_key,
                keyword=os.getenv("JARVIS_WAKE_KEYWORD", "jarvis"),
                device=audio_input_device,
            )
        )
    wake = CompositeWakeWordBackend(wake_backends)
    active_timeout = _active_timeout_from(overrides, settings.active_timeout_s)
    if isinstance(composition.selection.config, DuplexVoiceConfig):
        # GPT-Live owns a separately validated billing-idle contract.  The
        # legacy value may legitimately be zero and must never disable it.
        active_timeout = composition.selection.config.idle_timeout_s

    # Une voix vide enregistree (possible si le champ a ete vide a la main)
    # ferait refuser la session par le fournisseur : on retombe sur le defaut
    # declare par la pile, pas sur une chaine vide.
    realtime_voice = str(stack_values.get("voice") or "").strip() or str(stack.defaults().get("voice") or "")
    auto_turn = str(stack_values.get("turn_mode") or "auto").strip().lower() != "manual"
    if direct_conversation and not isinstance(composition.selection.config, DuplexVoiceConfig) and not auto_turn:
        raise ConfigurationError("Simple and Front Brain currently require automatic input segmentation")
    # Un modèle laissé vide dans les réglages veut dire « celui de la config » :
    # OPENAI_REALTIME_MODEL côté OpenAI. Gemini Live n'a pas de défaut connu.
    realtime_model = str(stack_values.get("model") or "").strip()
    if direct_conversation:
        config = composition.selection.config
        realtime_model = (config.reflex_model if isinstance(config, FrontBrainVoiceConfig) else config.conversation_model).model_id
    # Une seule lecture de l'architecture pour la surface : elle choisit à la
    # fois le jeu de règles et le catalogue d'outils, et les deux doivent dire la
    # même chose au modèle.
    continuous_brain = voice_arch is VoiceArchitecture.CONTINUOUS_BRAIN and not direct_conversation
    continuous_capture = continuous_brain or direct_conversation
    effective_model = realtime_model

    if stack.id == voice_stack.GEMINI_LIVE.id:
        if continuous_brain:
            # Décision 21 : Gemini reste sur le chemin legacy. Il n'implémente ni
            # le port de contrôle de sortie ni les règles de surface du mode
            # continu ; le laisser démarrer donnerait une voix qui commente le
            # travail du cerveau sans pouvoir être interrompue.
            raise RuntimeError(
                "La pile Gemini Live ne prend pas en charge l'architecture continuous_brain. "
                "Choisissez la pile OpenAI Realtime dans les réglages, ou repassez l'architecture "
                "sur « Un tour par appui » (onglet Mode vocal, ou JARVIS_VOICE_ARCH=legacy)."
            )
        if not realtime_model:
            raise RuntimeError(
                "Choisissez un modèle Gemini Live dans les réglages : Google ne définit pas "
                "de modèle Live par défaut."
            )

        async def realtime_factory(context: dict[str, object]):
            from jarvis.domain.prompt_registry import PromptTarget
            from jarvis.runtime.prompt_runtime import prompt_channel, prompt_evidence, resolve_prompt
            resolution = resolve_prompt(
                PromptTarget("conversation", "simple", "google", realtime_model, "legacy", "session"),
                overrides=prompt_overrides,
                variables={"context": context},
            )
            session = await GeminiLiveSession.connect(
                api_key=api_key,
                model=realtime_model,
                voice=realtime_voice,
                context=context,
                tools=REALTIME_TOOLS,
                instructions_override=prompt_channel(resolution, "session.instructions"),
                prompt_evidence=prompt_evidence(resolution, application="sent", channel="session.instructions"),
                auto_turn=auto_turn,
                input_transcription=bool(stack_values.get("input_transcription", True)),
                output_transcription=bool(stack_values.get("output_transcription", True)),
                start_sensitivity=str(stack_values.get("vad_start_sensitivity") or "LOW"),
                end_sensitivity=str(stack_values.get("vad_end_sensitivity") or "LOW"),
                prefix_padding_ms=int(stack_values.get("vad_prefix_padding_ms") or 300),
                silence_duration_ms=int(stack_values.get("vad_silence_duration_ms") or 1500),
            )
            journal.emit("voice.prompt", "Prompt application recorded", data=session.prompt_applications[0])
            return session
    else:
        # Sans OPENAI_REALTIME_MODEL, le modèle conseillé suit l'architecture
        # effective, et non celle que l'environnement seul aurait retenue.
        default_model = (
            settings.realtime_model
            if os.getenv("OPENAI_REALTIME_MODEL") is not None
            else recommended_realtime_model(voice_arch)
        )
        openai_model = realtime_model or default_model
        effective_model = openai_model
        from jarvis.runtime.back_brain_delegation import conversation_tools
        surface_tools = conversation_tools() if direct_conversation else realtime_tools.tools_for(continuous_brain=continuous_brain)

        async def realtime_factory(context: dict[str, object]):
            if isinstance(composition.selection.config, DuplexVoiceConfig):
                return await LiveFrontendSession.connect(
                    api_key=api_key, voice=realtime_voice, context=context,
                    architecture_config=composition.selection.config,
                    core=core,
                    prompt_overrides=prompt_overrides,
                )
            session = await RealtimeFrontendSession.connect(
                api_key=api_key,
                model=openai_model,
                voice=realtime_voice,
                context=context,
                tools=surface_tools,
                continuous_brain=continuous_capture,
                conversational=direct_conversation,
                architecture_config=composition.selection.config if direct_conversation else None,
                prompt_overrides=prompt_overrides,
                auto_turn=auto_turn,
                transcription_model=str(stack_values.get("transcription_model") or ""),
                transcription_language=str(stack_values.get("transcription_language") or ""),
                noise_reduction=str(stack_values.get("noise_reduction") or ""),
                vad_type=str(stack_values.get("vad_type") or ""),
                vad_eagerness=str(stack_values.get("vad_eagerness") or ""),
                vad_threshold=stack_values.get("vad_threshold"),
                vad_prefix_padding_ms=stack_values.get("vad_prefix_padding_ms"),
                vad_silence_duration_ms=stack_values.get("vad_silence_duration_ms"),
            )
            if direct_conversation and isinstance(composition.selection.config, FrontBrainVoiceConfig):
                from jarvis.runtime.front_brain_factory import attach_front_brain
                attach_front_brain(session, composition.selection.config, context, overrides=overrides, journal=journal)
            return session

    journal = RuntimeJournal(settings.runtime_root)
    # Mode legacy : l'agent Claude est hébergé par le Control Center, et Voice
    # le joint lui-même par la boucle locale.
    #
    # Mode continu : Voice ne possède plus le modèle fort (Décision 19). Core
    # le joint à travers son `BrainBackend`, et ne pas construire la passerelle
    # ici est ce qui rend l'ancien chemin réellement inaccessible.
    if continuous_capture:
        claude = None
        journal.emit("claude.gateway", "Direct conversation has no execution gateway" if direct_conversation else "Mode continu : le modèle fort est joint par Core, pas par Voice",
                     data={"arch": composition.selection.config.architecture.value if direct_conversation else voice_arch.value})
    else:
        claude = ClaudeGateway(
            base_url=_control_center_url(),
            timeout_s=float(os.getenv("JARVIS_CLAUDE_TIMEOUT_S", "600")),
        )
        journal.emit("claude.gateway", "Passerelle vers l'agent Claude configurée", data={"url": claude.base_url})
    # Mode continu : le micro reste ouvert pendant que JARVIS parle. La capture
    # duplex retire son écho et ne laisse passer l'utilisateur que s'il parle
    # vraiment (docs/fixes/voice-duplex/). Pile OpenAI seulement : Gemini est
    # refusé en continu plus haut.
    echo_cancellation = bool(stack_values.get("echo_cancellation", True))
    capture_factory = None
    if continuous_capture:

        def capture_factory():
            from jarvis.adapters.webrtc_echo import create_echo_canceller
            from jarvis.audio.duplex import CaptureProcessor

            canceller = (
                create_echo_canceller(capture_rate=stack.input_sample_rate, render_rate=stack.output_sample_rate)
                if echo_cancellation
                else None
            )
            journal.emit(
                "voice.duplex",
                "Annulation d'écho active" if canceller is not None else "Garde d'écho seule (sans annulation d'écho)",
                level="info" if canceller is not None or not echo_cancellation else "warning",
                data={
                    "echo_cancellation": canceller is not None,
                    "requested": echo_cancellation,
                    "code": "duplex_aec" if canceller is not None else "duplex_guard_only",
                },
            )
            # Vérification du locuteur en ombre : elle observe la capture
            # nettoyée dans son propre fil et journalise, sans rien changer à
            # ce qui part vers le fournisseur. Sans moteur, rien n'est branché.
            verifier = _speaker_verifier(overrides, settings.runtime_root, journal)
            observer = None
            if verifier is not None:
                from jarvis.audio.speaker_shadow import SpeakerVerificationWorker

                observer = SpeakerVerificationWorker(
                    verifier,
                    sample_rate=stack.input_sample_rate,
                    diagnostics=journal,
                    # Solo Owner appliqué : les candidats écartés sont tracés
                    # comme entrée écartée (`voice.input.non_owner_dropped`).
                    enforce=authorization.owner_enforced,
                )
            # Solo Owner (tâche 06) : tampon de rejeu du début de phrase, en
            # mémoire seulement. La salle ouverte n'en a pas.
            return CaptureProcessor(
                capture_rate=stack.input_sample_rate,
                render_rate=stack.output_sample_rate,
                canceller=canceller,
                observer=observer,
                owner_buffer_ms=authorization.owner_buffer_ms if authorization.owner_enforced else None,
            )

    # Cerveau réflexe : la phrase courte qui fait patienter pendant que le
    # cerveau réfléchit. Le réglage du Control Center prime, la variable
    # d'environnement n'est que le défaut de secours (`jarvis/v2_config.py`) —
    # et le réglage jamais enregistré laisse la variable décider.
    stored_stack_values = voice_stack.stored_for(overrides, stack.id)
    try:
        ack_delay_s = (reflex_delay_s(stored_stack_values.get(REFLEX_DELAY_SETTING))
                       if reflex_enabled(stored_stack_values.get(REFLEX_ENABLED_SETTING)) else 0.0)
        reflex_require_work = reflex_requires_confirmed_work()
    except ConfigurationError as exc:
        # Un réglage illisible ne doit pas empêcher la voix de démarrer : on
        # retombe sur le comportement par défaut, et on le dit dans le journal.
        journal.emit("voice.reflex.setting_invalid", str(exc), level="warning",
                     data={"code": "reflex_setting_invalid"})
        ack_delay_s, reflex_require_work = DEFAULT_REFLEX_DELAY_MS / 1000.0, False
    authorization, authorization_error = _conversation_authorization(overrides, journal)
    from jarvis.runtime.voice_metrics import VoiceSessionMetricRecorder
    metric_components = [{
        "role": "surface",
        "provider_id": stack.credential_provider,
        "model_id": effective_model or "(default)",
    }]
    if isinstance(composition.selection.config, FrontBrainVoiceConfig):
        metric_components.append({
            "role": "analysis",
            "provider_id": composition.selection.config.analysis_model.provider_id,
            "model_id": composition.selection.config.analysis_model.model_id,
        })
    from jarvis.runtime.agent_settings import resolve_agent_execution
    backend_execution = resolve_agent_execution(
        overrides, cwd=ROOT, runtime_root=settings.runtime_root,
    )
    metric_components.append({
        "role": "backend",
        "provider_id": backend_execution.provider,
        "model_id": backend_execution.model or "(provider-default)",
    })
    switch_handoff = switch_bus.handoff(composition.configuration_id)
    initial_conversation_id = (
        switch_handoff.get("conversation_id") if isinstance(switch_handoff, dict)
        else switch_bus.conversation_id()
    )
    # Conversation Events de la voix (Mouth, réflexes, outils) vers Core
    # (handoff conversation-observability, Slice 03b) : relais borné, par lots,
    # jeton relu à chaque reconnexion. Core absent, rien ne bloque la parole.
    from jarvis.runtime.conversation_event_forwarder import CoreConversationEventTransport, ConversationEventForwarder

    conversation_events = ConversationEventForwarder(
        transport=CoreConversationEventTransport(host=settings.core_host, port=settings.core_port,
                                                 token_file=settings.token_file),
        journal=journal,
    )
    voice = PersistentVoiceRuntime(
        conversation_events=conversation_events,
        wakeword=wake,
        core=core,
        realtime_factory=realtime_factory,
        active_timeout_s=active_timeout,
        signals=signals,
        journal=journal,
        audio_input_device=audio_input_device,
        audio_output_device=audio_output_device,
        auto_turn=auto_turn,
        claude=claude,
        input_sample_rate=stack.input_sample_rate,
        output_sample_rate=stack.output_sample_rate,
        voice_arch=voice_arch,
        conversation_architecture=composition.selection.config.architecture if direct_conversation else None,
        conversation_model=effective_model or None,
        configuration_id=composition.configuration_id,
        initial_conversation_id=initial_conversation_id if isinstance(initial_conversation_id, str) else None,
        switch_handoff=switch_handoff,
        switch_bus=switch_bus,
        metric_recorder_factory=lambda: VoiceSessionMetricRecorder(
            runtime_root=settings.runtime_root, journal=journal,
            architecture=operational_architecture,
            provider_id=stack.credential_provider, model_id=effective_model or "(default)",
            configuration_id=composition.configuration_id,
            pricing={"surface": overrides.get("live_pricing"),
                     "analysis": overrides.get("analysis_pricing"),
                     "backend": overrides.get("backend_pricing")},
            components=metric_components,
        ),
        capture_factory=capture_factory,
        reflex_delay_s=ack_delay_s if continuous_brain else 0.0,
        reflex_require_work=reflex_require_work,
        authorization=authorization,
        authorization_error=authorization_error,
        # Ce qui a été demandé, face à ce que la capture applique : publié au
        # Control Center (`.voice_capture`, tâche 08). Hors mode continu, sans objet.
        echo_cancellation=echo_cancellation if continuous_capture else None,
    )
    if switch_handoff is not None:
        switch_bus.mark_handoff_loaded(switch_handoff)
    switch_coordinator = VoiceSwitchCoordinator(
        voice=voice, core=core, bus=switch_bus, configuration_id=composition.configuration_id,
        architecture=operational_architecture,
        model=effective_model or "(default)", journal=journal,
    )
    timeout_task = asyncio.create_task(
        _voice_timeout_loop(voice, signals, journal, switch_coordinator), name="jarvis-voice-timeout",
    )
    key = manual_key.upper()
    wake_hint = f"Dites 'Jarvis' ou appuyez sur {key}" if wake_key else f"Appuyez sur {key}"
    banner = f"Jarvis Voice v0.2 en arrière-plan · {stack.label} · voix {realtime_voice}"
    journal.emit(
        "voice.stack",
        f"Pile vocale : {stack.label}",
        data={
            "stack": stack.id,
            "model": realtime_model or "(défaut)",
            "voice": realtime_voice,
            "auto_turn": auto_turn,
            "arch": composition.selection.config.architecture.value if direct_conversation else voice_arch.value,
            # D'où vient `arch` : réglage du Control Center, variable
            # d'environnement, ou défaut calculé.
            "arch_source": "voice_architecture" if direct_conversation else arch_source,
            "compatibility": composition.selection.uses_compatibility_runtime,
            "configuration_id": composition.configuration_id,
            "conversation_model": realtime_model or None,
            "analysis_model": composition.selection.config.analysis_model.model_id if direct_conversation and isinstance(composition.selection.config, FrontBrainVoiceConfig) else None,
            # Ce qui a réellement été envoyé au fournisseur : en continu la
            # surface est bornée aux réflexes et son catalogue d'outils est vide
            # (Décision 34).
            "surface_reflex_only": continuous_brain,
            "input_sample_rate": stack.input_sample_rate,
            "output_sample_rate": stack.output_sample_rate,
        },
    )
    if auto_turn:
        print(f"{banner}. {wake_hint} pour parler; "
              f"JARVIS répond dès que vous vous taisez. {key} de nouveau pour interrompre.")
    else:
        print(f"{banner}. {wake_hint} pour activer, puis à nouveau pour envoyer.")
    conversation_events.start()
    try:
        await voice.run()
    finally:
        timeout_task.cancel(); await asyncio.gather(timeout_task, return_exceptions=True)
        try:
            await voice.close()
        finally:
            # Après la voix : ses dernières paroles périmées sont des fins de span.
            await conversation_events.aclose()
    return 0


async def _run_control_center_v2() -> int:
    from jarvis.runtime.control_center import ControlCenter
    from jarvis.runtime.journal import RuntimeJournal
    from jarvis.v2_config import V2Settings

    settings = V2Settings.load()
    runtime_root = settings.runtime_root
    journal = RuntimeJournal(runtime_root)
    ui_port = int(os.getenv("JARVIS_UI_PORT", "17654"))
    # Avant tout sous-processus : le brain Claude hérite du dossier de retours
    # de cette session (`JARVIS_FEEDBACK_DIR`).
    from jarvis.runtime.feedback_sessions import feedback_session_dir
    try:
        feedback_dir = feedback_session_dir(ROOT)
        journal.emit("ui.feedback_session", "Dossier de retours utilisateur de la session", data={"path": str(feedback_dir)})
    except OSError as exc:
        journal.emit("ui.feedback_session", f"Dossier de retours utilisateur non créé: {type(exc).__name__}", level="warning",
                     data={"code": "feedback_session_dir_failed"})

    # Le visage ai-visualizer est lance des qu'il est installe : sans lui, le
    # Control Center n'affiche qu'un fond noir. Son absence ne doit pas pour
    # autant empecher le Control Center de demarrer ; JARVIS_VISUALIZER_ENABLED
    # force l'un ou l'autre choix.
    visualizer: asyncio.subprocess.Process | None = None
    visualizer_url: str | None = None
    visualizer_root = ROOT / "third_party" / "ai-visualizer"
    visualizer_installed = (visualizer_root / "server.py").is_file()
    visualizer_flag = os.getenv("JARVIS_VISUALIZER_ENABLED", "").strip().lower()
    visualizer_forced = visualizer_flag in {"1", "true", "yes", "on"}
    if visualizer_forced and not visualizer_installed:
        raise RuntimeError("ai-visualizer is not installed; run `python scripts/bootstrap_third_party.py` first")
    visualizer_enabled = visualizer_forced if visualizer_flag else visualizer_installed
    if visualizer_enabled:
        visualizer_port = int(os.getenv("JARVIS_VISUALIZER_PORT", "8790"))
        config = {
            "name": "JARVIS",
            "badge": "MVP",
            "face": "board",
            "port": visualizer_port,
            "bus_dir": str(runtime_root.resolve()),
            "thinking_sound": True,
        }
        (visualizer_root / "ai-visualizer.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        visualizer_env = os.environ.copy()
        visualizer_env.pop("OPENAI_API_KEY", None)
        visualizer_env.pop("PORCUPINE_ACCESS_KEY", None)
        visualizer = await asyncio.create_subprocess_exec(
            sys.executable,
            "server.py",
            "--no-open",
            cwd=str(visualizer_root),
            env=visualizer_env,
        )
        visualizer_url = f"http://127.0.0.1:{visualizer_port}/faces/board/"

    # Les sous-tâches de l'agent vivent ici, l'état de travail dans Core : un
    # relais borné les y porte (handoff work-state, tâche 11). Core absent,
    # rien ne bloque ; l'état attend puis est renvoyé en entier.
    from jarvis.runtime.work_ingress import CoreWorkTransport, WorkIngressForwarder

    work_ingress = WorkIngressForwarder(
        source="claude",
        transport=CoreWorkTransport(host=settings.core_host, port=settings.core_port, token_file=settings.token_file),
        journal=journal,
    )
    # Le panneau Agents lit l'état normalisé dans Core (tâche 13), par sa
    # propre connexion : lecture seule, jamais celle du relais.
    from jarvis.runtime.work_view import CoreWorkView
    from jarvis.runtime.live_status import CoreLiveStatusView

    work_view = CoreWorkView(
        CoreWorkTransport(host=settings.core_host, port=settings.core_port, token_file=settings.token_file),
        journal=journal,
    )
    live_view = CoreLiveStatusView(
        CoreWorkTransport(host=settings.core_host, port=settings.core_port, token_file=settings.token_file),
        journal=journal,
    )
    # Conversation Events des sous-agents Claude (Slice 03b), par le même
    # socle que le relais d'état de travail, sur sa propre connexion.
    from jarvis.runtime.conversation_event_forwarder import CoreConversationEventTransport, ConversationEventForwarder

    conversation_events = ConversationEventForwarder(
        transport=CoreConversationEventTransport(host=settings.core_host, port=settings.core_port,
                                                 token_file=settings.token_file),
        journal=journal,
    )
    # Lecture des Conversation Events pour la timeline (Slice 04) : le
    # navigateur passe par le Control Center, qui lit Core sur sa propre connexion.
    from jarvis.runtime.conversation_event_view import ConversationEventView, CoreConversationEventReader

    conversation_event_view = ConversationEventView(
        CoreConversationEventReader(host=settings.core_host, port=settings.core_port, token_file=settings.token_file),
        journal=journal,
    )
    # Scène constellation (Slice 03) : relais sans état, par sa propre
    # connexion ; les long-polls n'occupent pas celle du panneau Agents.
    from jarvis.runtime.scene_view import CoreSceneTransport, CoreSceneView

    scene_view = CoreSceneView(
        CoreSceneTransport(host=settings.core_host, port=settings.core_port, token_file=settings.token_file),
        journal=journal,
    )
    # Mode d'interaction (Slice 02) : Core possède la valeur effective, ce
    # Control Center la préférence enregistrée. Sa propre connexion, pour qu'un
    # jeton périmé ici ne ferme pas celle du panneau Agents.
    from jarvis.runtime.interaction_mode_view import CoreInteractionModeTransport, CoreInteractionModeView

    interaction_mode_view = CoreInteractionModeView(
        CoreInteractionModeTransport(host=settings.core_host, port=settings.core_port,
                                     token_file=settings.token_file),
        journal=journal,
    )
    # Outils d'affichage du cerveau (Slice 06) : déclarés au CLI seulement si
    # `scene.enabled` ; le serveur MCP joint Core avec ces coordonnées.
    from jarvis.runtime.display_mcp import DisplayMcpTarget
    # Outils Bare Hands du cerveau (Slice 12) : déclarés au CLI seulement si
    # l'utilisateur a allumé Bare Hands. Ce serveur MCP joint **ce** Control
    # Center, pas Core : Bare Hands n'existe nulle part dans Core.
    from jarvis.runtime.barehands_mcp import BarehandsMcpTarget
    # Réglages : même Control Center, mais déclaré au cerveau en toutes
    # circonstances (voir `settings_mcp`).
    from jarvis.runtime.settings_mcp import ConsoleMcpTarget

    control = ControlCenter(
        runtime_root=runtime_root,
        project_root=ROOT,
        visualizer_url=visualizer_url,
        work_ingress=work_ingress,
        conversation_events=conversation_events,
        conversation_event_view=conversation_event_view,
        work_view=work_view,
        live_view=live_view,
        scene_view=scene_view,
        interaction_mode_view=interaction_mode_view,
        display_mcp=DisplayMcpTarget(
            core_host=settings.core_host, core_port=settings.core_port,
            token_file=settings.token_file, runtime_root=runtime_root,
        ),
        barehands_mcp=BarehandsMcpTarget("127.0.0.1", ui_port, runtime_root),
        console_mcp=ConsoleMcpTarget("127.0.0.1", ui_port, runtime_root),
    )
    await control.start(port=ui_port)
    url = f"http://127.0.0.1:{ui_port}/"
    print(f"Jarvis Control Center ready on {url}")
    if visualizer is not None:
        journal.emit("ui.visualizer", "ai-visualizer launched", data={"url": visualizer_url, "pid": visualizer.pid})
    else:
        reason = "desactive par JARVIS_VISUALIZER_ENABLED" if visualizer_flag else "non installe"
        journal.emit("ui.visualizer", f"ai-visualizer {reason} ; pas de visage", data={"enabled": False, "installed": visualizer_installed})
    try:
        await asyncio.sleep(0.5)
        webbrowser.open(url)
        stop = asyncio.create_task(asyncio.Event().wait(), name="jarvis-control-center-wait")
        watched = {stop}
        waiter = None
        if visualizer is not None:
            waiter = asyncio.create_task(visualizer.wait(), name="jarvis-visualizer-wait")
            watched.add(waiter)
        done, pending = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if waiter is not None and waiter in done and visualizer.returncode not in (None, 0):
            raise RuntimeError(f"ai-visualizer exited with code {visualizer.returncode}")
        return 0
    finally:
        await control.stop()
        if visualizer is not None and visualizer.returncode is None:
            visualizer.terminate()
            try:
                await asyncio.wait_for(visualizer.wait(), timeout=3)
            except asyncio.TimeoutError:
                visualizer.kill(); await visualizer.wait()


async def _voice_timeout_loop(voice, signals, journal=None, switch_coordinator=None) -> None:
    """Publish the liveness heartbeat. A transient bus or timeout failure must
    never end this loop: the Control Center reads a missing heartbeat as
    "voice OFFLINE" and blanks the face while Voice is in fact still running."""
    reported = False
    handled_stop_request: str | None = None
    while True:
        await asyncio.sleep(1.0)
        try:
            signals.heartbeat()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not reported and journal is not None:
                journal.emit(
                    "voice.heartbeat_degraded",
                    f"Heartbeat publication failed, continuing: {type(exc).__name__}: {exc}",
                    level="warning",
                )
                reported = True
        else:
            reported = False
        runtime_reporter = getattr(voice, "voice_runtime_report", None)
        runtime_publisher = getattr(signals, "voice_runtime", None)
        if callable(runtime_reporter) and callable(runtime_publisher):
            try:
                runtime_publisher(runtime_reporter())
            except Exception:
                pass
        try:
            handled_stop_request = await _handle_live_ui_supervision(
                voice, signals, journal, handled_stop_request,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if journal is not None:
                journal.emit(
                    "voice.live_supervision_degraded",
                    f"Live UI supervision failed: {type(exc).__name__}", level="warning",
                    data={"code": "live_ui_supervision_degraded"},
                )
        if switch_coordinator is not None:
            try:
                await switch_coordinator.poll()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if journal is not None:
                    journal.emit(
                        "voice.switch.failed", "Voice switch coordination failed", level="error",
                        data={"code": "voice_switch_failed", "exception_type": type(exc).__name__},
                    )
        # Safety supervision is independent from the best-effort visual bus.
        # A locked heartbeat file must not keep a billable session alive.
        try:
            await voice.check_timeout()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if journal is not None:
                journal.emit(
                    "voice.timeout_check_failed",
                    f"Voice idle supervision failed: {type(exc).__name__}",
                    level="warning",
                )


async def _handle_live_ui_supervision(voice, signals, journal, handled_request_id: str | None):
    """Publish Duplex details and consume at most one idempotent Stop request."""
    reporter = getattr(voice, "live_runtime_report", None)
    publish_live = getattr(signals, "live_runtime", None)
    read_stop = getattr(signals, "read_live_stop_request", None)
    complete_stop = getattr(signals, "complete_live_stop", None)
    if not all(callable(value) for value in (reporter, publish_live, read_stop, complete_stop)):
        return handled_request_id
    report = reporter()
    publish_live(report)
    request = read_stop()
    request_id = request.get("request_id") if isinstance(request, dict) else None
    if not isinstance(request_id, str) or request_id == handled_request_id:
        return handled_request_id
    from jarvis.domain.voice_frontend import VoiceStopReason
    # Une session qui n'est pas celle de ce processus Voice est typiquement une
    # orpheline d'avant redémarrage : Voice n'a rien à couper, seul le reaper de
    # Core peut la conclure. Répondre « réessayez » enverrait dans une boucle qui
    # ne peut pas aboutir, alors l'interface n'offre plus le bouton (`manual`).
    if not isinstance(report, dict) or request.get("session_id") != report.get("session_id"):
        complete_stop(request, status="failed",
                      message="Session Live hors de ce processus Voice : Core la referme lui-même.")
        if journal is not None:
            journal.emit("voice.live_stop_not_owned",
                         "Control Center Live stop targeted another session", level="warning",
                         data={"code": "live_stop_not_owned"})
        return request_id
    try:
        await voice.mute(VoiceStopReason.USER)
    except Exception as exc:
        complete_stop(request, status="failed",
                      message=f"Arrêt Live non confirmé ({type(exc).__name__}). Réessayez.")
        if journal is not None:
            journal.emit("voice.live_stop_failed", "Control Center Live stop failed", level="error",
                         data={"code": "live_stop_failed", "exception_type": type(exc).__name__})
    else:
        complete_stop(request, status="accepted")
        if journal is not None:
            journal.emit("voice.live_stop_accepted", "Control Center Live stop accepted",
                         data={"request_id": request_id})
    return request_id


# Les rôles longue durée sont ceux qui peuvent mourir sans témoin ; les
# commandes ponctuelles rapportent déjà leur erreur au terminal.
_SUPERVISED_ROLES = {"core": "core", "voice": "voice", "control-center": "ui", "run": "run"}


def _arm_crash_capture(command: str) -> None:
    """Armer faulthandler et les hooks d'exception pour ce rôle.

    Sans cela un crash natif (0xC0000005 dans PortAudio ou Porcupine) tue le
    processus sans qu'aucun `except` ne s'exécute et sans qu'aucune trace
    n'atteigne le journal.
    """
    role = _SUPERVISED_ROLES.get(command)
    if role is None:
        return
    try:
        from jarvis.v2_config import V2Settings

        install_crash_guard(runtime_root=V2Settings.load().runtime_root, role=role)
        install_asyncio_crash_guard(asyncio.get_running_loop())
    except Exception as exc:
        # Le diagnostic ne doit jamais empêcher Jarvis de démarrer.
        print(f"Jarvis: capture de crash indisponible ({exc})", file=sys.stderr)


async def _amain(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    load_project_environment()
    command = args.command or "health"
    _arm_crash_capture(command)
    if command == "core": return await _run_core_v2()
    if command == "voice": return await _run_voice_v2()
    if command == "control-center": return await _run_control_center_v2()
    if command == "drive-auth": return await _drive_auth()
    if command == "drive-mcp": return await _drive_mcp()
    if command == "display-mcp": return await _display_mcp()
    if command == "barehands-mcp": return await _barehands_mcp()
    if command == "console-mcp": return await _console_mcp()
    if command == "barehands-replay": return _barehands_replay(args)
    if command == "routing-hook":
        from jarvis.runtime.routing_hook import main as routing_hook_main

        return routing_hook_main(["--runtime-root", args.runtime_root] if args.runtime_root else [])
    if command == "owner-voice":
        from jarvis.runtime.owner_voice import run_cli
        return run_cli(args)
    config = AppConfig.load(args.config)
    if command == "run": return await _run_voice(config, no_preflight=args.no_preflight)
    if command == "text": return await _run_text(config, message=args.message)
    if command == "health": return await _health(config, skip_audio=getattr(args, "skip_audio", False))
    if command == "reindex": return await _reindex(config)
    raise AssertionError(command)


def main() -> None:
    try:
        raise SystemExit(asyncio.run(_amain()))
    except SystemExit:
        raise
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (JarvisError, RuntimeError) as exc:
        report_fatal(exc, context={"source": "cli"})
        print(f"Jarvis: {exc}", file=sys.stderr); raise SystemExit(2) from None
    except BaseException as exc:
        # Une exception non prévue partait jusqu'ici dans la console sans jamais
        # rejoindre le journal : le Control Center n'en voyait rien.
        report_fatal(exc, context={"source": "cli"})
        raise


if __name__ == "__main__":
    main()

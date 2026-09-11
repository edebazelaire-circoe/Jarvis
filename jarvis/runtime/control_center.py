from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlparse
import uuid

from aiohttp import web

from jarvis.domain.errors import ConfigurationError
from jarvis.domain.v2 import BRAIN_NOT_ADDRESSED_ANSWER, AddressingDecision
from jarvis.runtime.audio_devices import AudioDiagnosticError, SoundDeviceAudioDiagnostics, normalize_device_id
from jarvis.runtime import cli_catalog, credentials as creds, shortcuts as shortcut_registry, voice_stack
from jarvis.runtime.claude_local import DEFAULT_PERMISSION_MODE, PERMISSION_MODES, ClaudeLocalAgent, normalize_permission_mode
from jarvis.runtime.codex_local import CodexLocalAgent, normalize_sandbox_mode
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.model_catalog import CatalogError, ModelCatalog, filter_by_role
from jarvis.runtime.visual_signals import VisualSignalBus
from jarvis.v2_config import (
    MIN_ACTIVE_TIMEOUT_S,
    REALTIME_VOICES,
    TURN_MODES,
    VoiceArchitecture,
    default_voice_arch,
    parse_active_timeout,
    parse_voice_arch,
)


VOICE_HEARTBEAT_MAX_AGE_S = 5.0

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
    ) -> None:
        self.runtime_root = runtime_root
        self.project_root = project_root
        self.visualizer_url = visualizer_url
        self.journal = RuntimeJournal(runtime_root)
        self.audio_diagnostics = audio_diagnostics or SoundDeviceAudioDiagnostics()
        self._audio_test_lock = asyncio.Lock()
        self.settings_path = runtime_root / "control-center-settings.json"
        self.catalog = ModelCatalog(runtime_root / "model-catalog.json")

        settings = self._settings()
        self._agent_id = cli_catalog.normalize_agent_cli(settings.get("agent_cli"))
        self._agents: dict[str, Any] = {}
        self._agent_lock = asyncio.Lock()
        self._apply_agent_settings(settings)

        self._app = web.Application(middlewares=[self._origin_guard])
        self._app.add_routes([
            web.get("/", self.index),
            web.get("/api/status", self.status),
            web.get("/api/trace", self.trace),
            web.get("/api/errors", self.errors),
            web.post("/api/errors/archive", self.archive_errors),
            web.get("/api/settings", self.get_settings),
            web.post("/api/settings", self.save_settings),
            web.get("/api/credentials", self.get_credentials),
            web.post("/api/credentials", self.save_credential),
            web.post("/api/credentials/delete", self.remove_credential),
            web.post("/api/credentials/bind", self.bind_credential),
            web.get("/api/models", self.models),
            web.get("/api/cli/agents", self.cli_agents),
            web.get("/api/shortcuts", self.get_shortcuts),
            web.post("/api/shortcuts", self.save_shortcuts),
            web.get("/api/audio/devices", self.audio_devices),
            web.post("/api/audio/test", self.audio_test),
            web.get("/api/agent", self.agent_status),
            web.get("/api/agent/transcript", self.agent_transcript),
            web.get("/api/agent/tasks", self.agent_tasks),
            web.get("/api/agent/tasks/{task_id}/trace", self.agent_task_trace),
            web.post("/api/agent/console/open", self.agent_console_open),
            web.post("/api/agent/console/close", self.agent_console_close),
            web.post("/api/agent/start", self.agent_start),
            web.post("/api/agent/restart", self.agent_restart),
            web.post("/api/agent/kill", self.agent_kill),
            web.post("/api/agent/send", self.agent_send),
            web.post("/api/agent/ask", self.agent_ask),
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
        self._agents[self._agent_id] = agent
        return agent

    def _agent_defaults(self, agent_id: str) -> dict[str, Any]:
        spec = cli_catalog.spec_for(agent_id)
        if agent_id == "codex":
            return {"command": spec.default_command, "model": "", "permission_mode": "danger-full-access"}
        return {
            "command": os.getenv("JARVIS_CLAUDE_CLI", spec.default_command),
            "model": os.getenv("JARVIS_CLAUDE_MODEL", ""),
            "permission_mode": os.getenv("JARVIS_CLAUDE_PERMISSION_MODE", DEFAULT_PERMISSION_MODE),
        }

    def _agent_settings(self, settings: dict[str, Any], agent_id: str) -> dict[str, Any]:
        values = self._agent_defaults(agent_id)
        # `claude_cli` et `claude_permission_mode` sont les anciens champs plats.
        # Ils passent avant l'environnement — une configuration antérieure à cet
        # écran ne doit pas être perdue — mais après le format structuré, qui
        # est désormais la source et dont ils ne sont que le reflet.
        if agent_id == "claude":
            if settings.get("claude_cli"):
                values["command"] = str(settings["claude_cli"])
            if settings.get("claude_permission_mode"):
                values["permission_mode"] = str(settings["claude_permission_mode"])
        stored = settings.get("agent_cli_settings")
        saved = stored.get(agent_id) if isinstance(stored, dict) and isinstance(stored.get(agent_id), dict) else {}
        values.update({key: saved[key] for key in values if key in saved and saved[key] is not None})
        values["command"] = str(values.get("command") or cli_catalog.spec_for(agent_id).default_command)
        values["model"] = str(values.get("model") or "")
        values["permission_mode"] = (
            normalize_sandbox_mode(values.get("permission_mode"))
            if agent_id == "codex"
            else normalize_permission_mode(values.get("permission_mode"))
        )
        return values

    def _apply_agent_settings(self, settings: dict[str, Any]) -> None:
        values = self._agent_settings(settings, self._agent_id)
        agent = self.agent
        agent.command = values["command"]
        agent.model = values["model"]
        agent.permission_mode = values["permission_mode"]

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
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def index(self, request: web.Request) -> web.Response:
        del request
        html = (Path(__file__).with_name("control_center.html")).read_text(encoding="utf-8")
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
        })

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
        tmp.replace(self.settings_path)

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

    def _settings_payload(self, settings: dict[str, Any]) -> dict[str, Any]:
        stack_id = voice_stack.normalize_stack(settings.get("voice_stack"))
        agent_id = cli_catalog.normalize_agent_cli(settings.get("agent_cli"))
        return {
            "voice": {
                "stack": stack_id,
                "stacks": voice_stack.describe_stacks(),
                "settings": {
                    spec.id: voice_stack.settings_for(settings, spec.id) for spec in voice_stack.VOICE_STACKS
                },
                **self._voice_arch_payload(settings),
            },
            "cli": {
                "agent": agent_id,
                "agents": [
                    cli_catalog.describe(spec, command=self._agent_settings(settings, spec.id)["command"], detection={})
                    for spec in cli_catalog.AGENT_CLIS
                ],
                "settings": {
                    spec.id: self._agent_settings(settings, spec.id) for spec in cli_catalog.AGENT_CLIS
                },
                "active_state": self.agent.snapshot()["state"],
            },
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

    async def save_settings(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="settings must be an object")
        current = self._settings()
        creds.migrate_legacy(current)
        switch_to: str | None = None

        try:
            self._apply_voice(current, payload)
            # Champ plat, pendant de `voice_turn_mode` ; vide = revenir au défaut.
            if payload.get("voice_arch") is not None:
                self._store_voice_arch(current, payload["voice_arch"])
            switch_to = self._apply_cli(current, payload)
        except (voice_stack.VoiceStackError, cli_catalog.CliSettingsError, creds.CredentialError) as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc

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
        self._write_settings(current)
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
        if voice.get("stack") is not None:
            stack_id = str(voice["stack"]).strip().lower()
            if stack_id not in voice_stack.VOICE_STACK_IDS:
                raise voice_stack.VoiceStackError(
                    "voice_unknown_stack", f"Pile vocale inconnue : {stack_id}."
                )
            current["voice_stack"] = stack_id
        if voice.get("arch") is not None:
            self._store_voice_arch(current, voice["arch"])
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
        if not creds.delete_credential(settings, credential_id):
            return web.json_response({"ok": False, "code": "credential_not_found", "error": "Cette clé n'existe plus."}, status=404)
        self._write_settings(settings)
        self.journal.emit("settings.credential", "Clé API supprimée", data={"id": credential_id})
        return web.json_response({"ok": True, **creds.credentials_state(settings)})

    async def bind_credential(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="binding must be an object")
        settings = self._settings()
        creds.migrate_legacy(settings)
        try:
            creds.bind_credential(settings, str(payload.get("provider") or ""), str(payload.get("id") or "") or None)
        except creds.CredentialError as exc:
            return web.json_response({"ok": False, "code": exc.code, "error": str(exc)}, status=400)
        self._write_settings(settings)
        # Une clé qui change invalide le catalogue : les modèles visibles
        # dépendent du compte, pas seulement du fournisseur.
        self.catalog.invalidate(str(payload.get("provider") or "").strip().lower())
        return web.json_response({"ok": True, **creds.credentials_state(settings)})

    # ------------------------------------------------------------- catalogues

    async def models(self, request: web.Request) -> web.Response:
        provider = str(request.query.get("provider", "")).strip().lower()
        role = str(request.query.get("role", "")).strip().lower()
        refresh = str(request.query.get("refresh", "")).strip().lower() in {"1", "true", "yes"}
        settings = self._settings()
        api_key = creds.secret_for(settings, provider)
        try:
            result = await self.catalog.models(provider, api_key, refresh=refresh)
        except CatalogError as exc:
            stale = self.catalog.cached(provider)
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

    async def agent_tasks(self, request: web.Request) -> web.Response:
        """Le brain et ses sous-tâches. Toujours ceux de l'agent actif : après
        une bascule Claude ↔ Codex, c'est le nouvel agent qui répond."""
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
        prompt = build_agent_brief(context, text) if isinstance(context, dict) else text
        return web.json_response(await self.agent.ask(prompt, timeout_s=timeout_s))

    async def agent_send(self, request: web.Request) -> web.Response:
        payload = await request.json()
        text = str(payload.get("text") or "") if isinstance(payload, dict) else ""
        try:
            return web.json_response(await self.agent.send(text))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        except RuntimeError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc

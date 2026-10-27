"""Préparation et premier lancement du produit, côté Control Center (Slice 07, `docs/product-install.md`).

Le Control Center est l'hôte de la page : il relève les faits (Core par le relais, la CLI Claude, le poste), les
remet au domaine pur (`jarvis/domain/product_readiness.py`) qui écrit le rapport, et exécute les **actions nommées**.
Une lecture du rapport ne change jamais rien (règle de la Slice : diagnostic sans effet de bord) ; seule une action
nommée agit, et elle ne supprime jamais une donnée canonique.

| Route (Control Center) | Effet |
| --- | --- |
| `GET /api/product/readiness` | rapport (`report_payload`) : aucune écriture |
| `POST /api/product/readiness/actions/{action_id}` | action nommée (`ActionId`) ; `{action_id, status, message, url?, report}` |
| `POST /api/product/onboarding/complete` | Board Présentation actif (jamais Assistant), premier lancement noté |
| `POST /api/product/quit` | demande au lanceur d'arrêter JARVIS (lanceur présent seulement) |

Faits lus sur Core (relais `LocalCoreClient`, liste blanche `FORWARDABLE_*`) : `/v1/health`, `/v1/boards/edition`,
`/v1/edition/connectors`, `/v1/local-capabilities/remotion`, `/v1/exports/root`. Une lecture tombée rend sa ligne
`unavailable` avec la cause, jamais `ready`.

Actions :

- `recheck` : oublie les relevés en cache (CLI, audio) ;
- `prepare_data` : crée `data\\`, `runtime\\`, `config\\` sous la maison du produit (I-002 point 3) ;
- `verify_installation` : vérification complète du paquet (`private_runtime.verify_package`), en tâche de fond ;
- `render_install|repair|update|enable` : opérations de la capacité locale `remotion` sur Core (I-007 point 1 : la
  réparation réinstalle après la remise d'un runtime ; Core répond 202 et l'état se relit) ;
- `brain_install_guide` : rend la page officielle d'Anthropic à ouvrir (HV-PACKAGE-02 : rien n'est téléchargé) ;
- `brain_sign_in` : ouvre `claude auth login` dans sa fenêtre ; l'état se relit toutes les quelques secondes ;
- `connect_circoe` : enregistre le plugin Circuit Toolbox s'il manque puis lance sa connexion ; rend l'adresse de
  consentement à ouvrir (`docs/mcp/plugins.md` §3.3) ;
- `open_connections` : navigation dans la page (rien côté serveur).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any

from aiohttp import web

from jarvis.domain.product_connectors import CIRCUIT_TOOLBOX_ENDPOINT
from jarvis.domain.product_readiness import (
    ActionId, BrainFacts, Probe, ReadinessFacts, report_payload,
)
from jarvis.installation import Installation, detect_installation
from jarvis.private_runtime import PackageLayout, package_layout, verify_package
from jarvis.protocol.client import ForwardRefused
from jarvis.runtime import brain_cli
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.product_launcher import launcher_alive

ONBOARDING_FILE = "product-onboarding.json"
ONBOARDING_SCHEMA = "jarvis.product-onboarding"
#: État publié par le lanceur (`product_launcher.py`) et sa boîte aux lettres d'arrêt.
LAUNCHER_STATE_FILE = "launcher.json"
LAUNCHER_STOP_FILE = "launcher-stop.request"
#: Délai d'une lecture de Core pour le rapport : la page relit, mieux vaut une ligne « illisible » qu'une attente.
CORE_READ_TIMEOUT_S = 6.0
#: Durée de validité des relevés coûteux (CLI Claude : deux processus ; audio : PortAudio).
BRAIN_CACHE_S = 30.0
BRAIN_CACHE_SIGNING_IN_S = 3.0
AUDIO_CACHE_S = 60.0
#: Au-delà, une connexion Claude encore ouverte n'est plus comptée « en cours » (la fenêtre reste à l'utilisateur).
SIGN_IN_DEADLINE_S = 600.0
CIRCOE_DISPLAY_NAME = "Compte CIRCOE (messagerie et agenda)"
PRESENTATION_BOARD_TITLE = "Mes présentations"
#: Statuts de la capacité `remotion` pendant lesquels Core travaille encore.
RENDER_BUSY = frozenset({"installing", "uninstalling", "starting", "stopping"})
RENDER_ACTIONS = frozenset({ActionId.RENDER_INSTALL.value, ActionId.RENDER_REPAIR.value, ActionId.RENDER_UPDATE.value,
                            ActionId.RENDER_ENABLE.value})
#: Au-delà, une préparation du moteur de rendu n'est plus comptée « en cours » (la ligne relit l'état de Core).
RENDER_RUNNING_DEADLINE_S = 900.0
RENDER_STARTED = {"install": "Préparation du moteur de rendu lancée : une à deux minutes.",
                  "repair": "Réparation du moteur de rendu lancée : une à deux minutes.",
                  "update": "Mise à jour du moteur de rendu lancée : une à deux minutes.",
                  "enable": "Réactivation du moteur de rendu lancée."}
RENDER_DONE = {"ready": "Moteur de rendu prêt.", "running": "Moteur de rendu prêt.",
               "disabled": "Le moteur de rendu reste désactivé.",
               "not_installed": "Le moteur de rendu n'est pas encore préparé."}
#: Actions qui créent quelque chose : jamais deux à la fois (double clic, deux onglets ; O4 de la revue).
SERIALIZED_ACTIONS = frozenset({ActionId.CONNECT_CIRCOE, ActionId.BRAIN_SIGN_IN})
NOT_INSTALLED = "Cette action ne concerne que le JARVIS installé."


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _error(status: int, code: str, message: str, detail: str = "") -> web.Response:
    return web.json_response({"error": {"code": code, "message": message, "detail": detail}}, status=status)


class ReadinessActionError(RuntimeError):
    """Refus d'une action : `message` en mots de produit (montré dans la ligne), `detail` technique (sous
    « Détails » et au journal), `code` stable (revue m3 : la ligne montrait « Core is unreachable: … »)."""

    def __init__(self, status: int, code: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.detail = detail


#: Phrase de produit d'un refus de Core relayé (le texte de Core, en anglais technique, va dans `detail`).
CORE_REFUSED = "Le moteur de JARVIS a refusé cette action. Réessayez ; si cela recommence, quittez puis relancez JARVIS."
CORE_UNREACHABLE = "Le moteur de JARVIS ne répond pas. Il redémarre en général seul ; sinon, quittez puis relancez JARVIS."


class ProductReadinessService:
    """Relevés, rapport, actions nommées et premier lancement. Une instance par Control Center."""

    def __init__(self, *, transport: Callable[[], Any], runtime_root: Path, journal: RuntimeJournal,
                 list_audio: Callable[[], Mapping[str, Any]] | None = None,
                 installation: Installation | None = None, layout: PackageLayout | None | object = ...,
                 environ: Mapping[str, str] | None = None,
                 locate_brain: Callable[[], str | None] | None = None,
                 probe_brain: Callable[[str | None, bool], BrainFacts] | None = None,
                 start_sign_in: Callable[[str], brain_cli.SignIn] | None = None,
                 find_browser: Callable[[], str | None] | None = None,
                 disk_free: Callable[[Path], int] | None = None,
                 verify: Callable[[PackageLayout], tuple[dict | None, list[str]]] = verify_package,
                 monotonic: Callable[[], float] = time.monotonic,
                 pid_alive: Callable[[int], bool] | None = None,
                 ref_alive: Callable[[str], bool] | None = None,
                 voice_view: Callable[[], Mapping[str, Any]] | None = None) -> None:
        self._transport = transport
        self._runtime_root = Path(runtime_root)
        self._journal = journal
        self._list_audio = list_audio
        self._installation = installation or detect_installation()
        self._layout = package_layout() if layout is ... else layout
        self._environ = os.environ if environ is None else environ
        self._locate_brain = locate_brain or (lambda: brain_cli.locate(environ=self._environ,
                                                                       installed=self._installation.installed))
        self._probe_brain = probe_brain or (lambda cli, signing: brain_cli.probe(cli, sign_in_running=signing))
        self._start_sign_in = start_sign_in or (lambda cli: brain_cli.start_sign_in(cli, clock=self._monotonic))
        self._find_browser = find_browser or _default_browser
        self._disk_free = disk_free or (lambda path: shutil.disk_usage(path).free)
        self._verify = verify
        self._monotonic = monotonic
        self._pid_alive = pid_alive or _pid_alive
        self._ref_alive = ref_alive or _ref_alive
        #: Projection Off / Sleep / Active du Control Center (`voice_lifecycle.project`) pour la ligne « Voix ».
        self._voice_view = voice_view
        self._brain_cache: tuple[float, BrainFacts] | None = None
        self._audio_cache: tuple[float, Probe] | None = None
        self._sign_in: brain_cli.SignIn | None = None
        self._integrity: Probe | None = None
        #: Actions nommées en cours : `ActionId` → instant de départ (monotone).
        self._running: dict[str, float] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._brain_lock = asyncio.Lock()

    # ------------------------------------------------------------------ relevés

    async def _core_get(self, path: str) -> Probe:
        transport = self._transport()
        if transport is None:
            return Probe(error="core_unconfigured: the control center does not know Core")
        try:
            status, payload = await transport.forward("GET", path, timeout_s=CORE_READ_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except ForwardRefused as exc:
            self._journal.emit("product.readiness.not_forwardable", f"Relais refusé pour {path}", level="error",
                               data={"code": "relay_path_not_forwardable", "path": path})
            return Probe(error=f"relay_path_not_forwardable: {exc}"[:300])
        except asyncio.TimeoutError:
            return Probe(error=f"core_unreachable: Core did not answer {path} in {CORE_READ_TIMEOUT_S:.0f} s")
        except Exception as exc:  # noqa: BLE001 - the cause becomes the line's detail; a report never raises
            return Probe(error=f"core_unreachable: {type(exc).__name__}: {str(exc)[:200]}")
        if not isinstance(payload, Mapping):
            return Probe(error=f"http_{status}: Core answered without JSON")
        if status >= 400:
            error = payload.get("error") if isinstance(payload.get("error"), Mapping) else {}
            return Probe(error=f"{error.get('code') or f'http_{status}'}: {str(error.get('message') or '')[:200]}")
        return Probe(value=payload)

    async def _brain(self, *, force: bool = False) -> BrainFacts:
        async with self._brain_lock:
            signing = self._signing_in()
            ttl = BRAIN_CACHE_SIGNING_IN_S if signing else BRAIN_CACHE_S
            cached = self._brain_cache
            if not force and cached is not None and self._monotonic() - cached[0] < ttl:
                facts = cached[1]
                return BrainFacts(**{**_facts_dict(facts), "sign_in_running": signing and not facts.logged_in})
            cli = await asyncio.to_thread(self._locate_brain)
            facts = await asyncio.to_thread(self._probe_brain, cli, signing)
            if facts.logged_in and self._sign_in is not None:
                self._journal.emit("product.brain.signed_in", "Claude Code connecté",
                                   data={"auth_method": facts.auth_method})
                self._sign_in = None
            self._brain_cache = (self._monotonic(), facts)
            return facts

    def _signing_in(self) -> bool:
        sign_in = self._sign_in
        if sign_in is None:
            return False
        if not sign_in.running() or self._monotonic() - sign_in.started_at > SIGN_IN_DEADLINE_S:
            self._sign_in = None
            return False
        return True

    async def _audio(self, *, force: bool = False) -> Probe:
        if self._list_audio is None:
            return Probe(error="audio_diagnostics_unavailable")
        cached = self._audio_cache
        if not force and cached is not None and self._monotonic() - cached[0] < AUDIO_CACHE_S:
            return cached[1]
        try:
            listed = await asyncio.to_thread(self._list_audio)
            probe = Probe(value={"inputs": len(listed.get("inputs") or []), "outputs": len(listed.get("outputs") or [])})
        except Exception as exc:  # noqa: BLE001 - optional line; its cause is shown, never hidden
            code = getattr(exc, "code", None) or type(exc).__name__
            probe = Probe(error=f"{code}: {str(exc)[:200]}")
        self._audio_cache = (self._monotonic(), probe)
        return probe

    def _voice(self) -> Probe:
        if self._voice_view is None:
            return Probe(error="voice_lifecycle_unavailable")
        try:
            return Probe(value=dict(self._voice_view()))
        except Exception as exc:  # noqa: BLE001 - optional line; its cause is shown, never hidden
            return Probe(error=f"voice_lifecycle_unreadable: {type(exc).__name__}")

    def _home_root(self) -> Path:
        home = self._installation.home
        return home.root if home is not None else self._runtime_root

    def _layout_missing(self) -> tuple[str, ...]:
        home = self._installation.home
        if home is None:
            return ()
        return tuple(name for name, path in (("data", home.data), ("runtime", home.runtime), ("config", home.config))
                     if not path.is_dir())

    def _disk(self) -> Probe:
        target = self._home_root()
        while not target.exists() and target.parent != target:
            target = target.parent
        try:
            return Probe(value=int(self._disk_free(target)))
        except OSError as exc:
            return Probe(error=f"disk_usage_failed: {type(exc).__name__}: {exc}"[:300])

    def _browser(self) -> Probe:
        try:
            return Probe(value=self._find_browser())
        except Exception as exc:  # noqa: BLE001 - line shows the cause
            return Probe(error=f"browser_lookup_failed: {type(exc).__name__}: {exc}"[:300])

    async def facts(self, *, force: bool = False) -> ReadinessFacts:
        core, edition, connectors, render, export_root, brain, audio = await asyncio.gather(
            self._core_get("/v1/health"), self._core_get("/v1/boards/edition"),
            self._core_get("/v1/edition/connectors"), self._core_get("/v1/local-capabilities/remotion"),
            self._core_get("/v1/exports/root"), self._brain(force=force), self._audio(force=force))
        if render.ok:
            render = Probe(value=(render.value or {}).get("capability"))
        if export_root.ok:
            export_root = Probe(value=(export_root.value or {}).get("root"))
        now = self._monotonic()
        self._settle_render(render, now)
        running = {key: round(now - started, 1) for key, started in self._running.items()}
        if self._signing_in():
            running[ActionId.BRAIN_SIGN_IN.value] = round(now - self._sign_in.started_at, 1)
        return ReadinessFacts(installed=self._installation.installed, core=core, edition=edition,
                              connectors=connectors, render=render, brain=brain, browser=self._browser(), audio=audio,
                              voice=self._voice(),
                              disk_free=self._disk(), layout_missing=self._layout_missing(), export_root=export_root,
                              integrity=self._integrity, running=running)

    def _settle_render(self, render: Probe, now: float) -> None:
        """Retire la marque d'une préparation du moteur de rendu quand Core a fini (QA runtime m1), ou passé
        `RENDER_RUNNING_DEADLINE_S` : une marque ne survit jamais à son travail."""

        status = str((render.value or {}).get("status") or "") if render.ok else ""
        for key in [key for key in self._running if key in RENDER_ACTIONS]:
            finished = render.ok and status not in RENDER_BUSY
            if finished or now - self._running[key] > RENDER_RUNNING_DEADLINE_S:
                self._running.pop(key, None)
                self._journal.emit("product.readiness.render_settled", f"Moteur de rendu : {status or 'illisible'}",
                                   level="info" if finished else "warning",
                                   data={"action_id": key, "capability_status": status, "deadline": not finished})

    async def report(self, *, force: bool = False) -> dict[str, Any]:
        facts = await self.facts(force=force)
        payload = report_payload(facts, checked_at=utc_now_iso(), onboarding=self.onboarding(),
                                 launcher=self.launcher())
        payload["running_elapsed_s"] = dict(facts.running)
        return payload

    # ------------------------------------------------------------------ premier lancement

    @property
    def onboarding_path(self) -> Path:
        return self._runtime_root / ONBOARDING_FILE

    def onboarding(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.onboarding_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"completed": False, "completed_at": None}
        except (OSError, ValueError) as exc:
            # Illisible : le premier lancement se rejoue (rien de perdu), et c'est dit au journal.
            self._journal.emit("product.onboarding.unreadable", f"{ONBOARDING_FILE} illisible : {type(exc).__name__}",
                               level="warning", data={"code": "onboarding_state_unreadable"})
            return {"completed": False, "completed_at": None, "unreadable": True}
        if not isinstance(raw, dict) or raw.get("schema") != ONBOARDING_SCHEMA:
            return {"completed": False, "completed_at": None, "unreadable": True}
        return {"completed": bool(raw.get("completed_at")), "completed_at": raw.get("completed_at")}

    async def complete_onboarding(self) -> dict[str, Any]:
        """Board Présentation actif (le Board actif s'il l'est, sinon le premier Présentation, sinon un nouveau), puis
        le premier lancement est noté. Jamais un Board Assistant : l'édition le refuserait de toute façon.
        Refus `readiness_not_ready` (409) tant qu'une ligne indispensable n'est pas prête : la page grise
        « Commencer » ; le serveur tient la même règle."""

        report = await self.report()
        if not report["ready"]:
            raise ReadinessActionError(409, "readiness_not_ready", "Terminez d'abord les étapes indispensables (en orange).",
                                       f"required items not ready: {', '.join(report['blocking'])}")
        board = await self._ensure_presentation_board()
        record = {"schema": ONBOARDING_SCHEMA, "schema_version": 1, "completed_at": utc_now_iso(),
                  "board_id": board.get("board_id")}
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        temp = self.onboarding_path.with_name(ONBOARDING_FILE + ".tmp")
        temp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.onboarding_path)
        self._journal.emit("product.onboarding.completed", "Premier lancement terminé",
                           data={"board_id": board.get("board_id"), "board_kind": board.get("board_kind")})
        return {"onboarding": self.onboarding(), "board": board}

    async def _core(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        transport = self._transport()
        if transport is None:
            raise ReadinessActionError(503, "core_unconfigured", CORE_UNREACHABLE, "the control center does not know Core")
        raw = json.dumps(body).encode("utf-8") if body is not None else None
        try:
            status, payload = await transport.forward(method, path, body=raw)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as exc:
            raise ReadinessActionError(504, "core_timeout", "Le moteur de JARVIS n'a pas répondu à temps. Réessayez "
                                       "dans un instant.", f"Core did not answer {method} {path} in time") from exc
        except ForwardRefused as exc:
            raise ReadinessActionError(500, "relay_path_not_forwardable", "Cette action n'est pas permise par le "
                                       "Control Center.", str(exc)[:300]) from exc
        except Exception as exc:  # noqa: BLE001 - re-raised typed with its cause
            raise ReadinessActionError(503, "core_unreachable", CORE_UNREACHABLE,
                                       f"Core is unreachable: {type(exc).__name__}: {str(exc)[:200]}") from exc
        if not isinstance(payload, Mapping):
            raise ReadinessActionError(502, "http_error", "Le moteur de JARVIS a rendu une réponse illisible.",
                                       f"Core answered HTTP {status} without JSON")
        if status >= 400:
            error = payload.get("error") if isinstance(payload.get("error"), Mapping) else {}
            raise ReadinessActionError(status, str(error.get("code") or f"http_{status}"), CORE_REFUSED,
                                       str(error.get("message") or f"Core answered HTTP {status}")[:300])
        return payload

    async def _ensure_presentation_board(self) -> dict[str, Any]:
        listed = await self._core("GET", "/v1/boards")
        boards = [row for row in listed.get("boards") or [] if isinstance(row, Mapping)]
        active_id = listed.get("active_board_id")
        active = next((row for row in boards if row.get("board_id") == active_id), None)
        if active is not None and active.get("board_kind") == "presentation":
            return dict(active)
        target = next((row for row in boards if row.get("board_kind") == "presentation"), None)
        if target is None:
            created = await self._core("POST", "/v1/boards", {"title": PRESENTATION_BOARD_TITLE,
                                                               "board_kind": "presentation"})
            target = created.get("board") if isinstance(created.get("board"), Mapping) else None
            if target is None:
                raise ReadinessActionError(502, "board_create_unreadable", "Le Board Présentation a été créé mais n'a pas "
                                           "pu être ouvert. Réessayez.", "Core created a Board without returning it")
            self._journal.emit("product.onboarding.board_created", "Board Présentation créé au premier lancement",
                               data={"board_id": target.get("board_id")})
        switched = await self._core("POST", "/v1/boards/switch", {"board_id": target.get("board_id")})
        board = switched.get("board") if isinstance(switched.get("board"), Mapping) else target
        return dict(board)

    # ------------------------------------------------------------------ lanceur

    def launcher(self) -> dict[str, Any]:
        """`managed` vrai si un lanceur vivant a publié son état (alors « Quitter JARVIS » a un sens) ; `voice` : ce que
        le lanceur dit de la Voix (`pid`, `running`, `held`, `abandoned`), `None` s'il ne la lance pas."""

        try:
            state = json.loads((self._runtime_root / LAUNCHER_STATE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"managed": False}
        if not launcher_alive(state, pid_alive=self._pid_alive, ref_alive=self._ref_alive):
            return {"managed": False}  # PID mort ou réemployé (I-009 point 2) : « Quitter JARVIS » n'a pas de sens
        roles = state.get("roles") if isinstance(state.get("roles"), dict) else {}
        voice = roles.get("voice") if isinstance(roles.get("voice"), dict) else None
        return {"managed": True, "started_at": state.get("started_at"), "voice": voice}

    def request_quit(self) -> dict[str, Any]:
        if not self.launcher().get("managed"):
            raise ReadinessActionError(409, "launcher_not_running", "JARVIS n'a pas été ouvert par son raccourci : "
                                       "fermez ses fenêtres pour l'arrêter.",
                                       "JARVIS was not started by its launcher; close its windows instead")
        path = self._runtime_root / LAUNCHER_STOP_FILE
        path.write_text(utc_now_iso() + "\n", encoding="utf-8")
        self._journal.emit("product.quit.requested", "Arrêt de JARVIS demandé depuis la page", data={})
        return {"status": "stopping"}

    # ------------------------------------------------------------------ actions nommées

    async def act(self, action_id: str) -> dict[str, Any]:
        try:
            action = ActionId(action_id)
        except ValueError:
            raise ReadinessActionError(404, "readiness_action_unknown", "Cette action n'existe pas dans cette version de "
                                       "JARVIS.", f"unknown readiness action {action_id[:40]!r}") from None
        if action.value in self._running:
            raise ReadinessActionError(409, "readiness_action_running", "Cette action est déjà en cours.",
                                       f"{action.value} is already running")
        self._journal.emit("product.readiness.action", f"Action de préparation : {action.value}",
                           data={"action_id": action.value})
        # Un double clic (ou deux onglets) ne lance jamais deux fois une action qui crée quelque chose (O4 de la revue :
        # `connect_circoe` enregistrait deux fois le compte). Les actions de fond tiennent leur propre marque.
        held = action in SERIALIZED_ACTIONS
        if held:
            self._running[action.value] = self._monotonic()
        handler = {
            ActionId.RECHECK: self._recheck,
            ActionId.PREPARE_DATA: self._prepare_data,
            ActionId.VERIFY_INSTALLATION: self._verify_installation,
            ActionId.RENDER_INSTALL: lambda: self._render("install"),
            ActionId.RENDER_REPAIR: lambda: self._render("repair"),
            ActionId.RENDER_UPDATE: lambda: self._render("update"),
            ActionId.RENDER_ENABLE: lambda: self._render("enable"),
            ActionId.BRAIN_INSTALL_GUIDE: self._brain_install_guide,
            ActionId.BRAIN_SIGN_IN: self._brain_sign_in,
            ActionId.CONNECT_CIRCOE: self._connect_circoe,
            ActionId.OPEN_CONNECTIONS: self._open_connections,
        }[action]
        try:
            outcome = await handler()
        except ReadinessActionError as exc:
            self._journal.emit("product.readiness.action_failed", f"Action {action.value} refusée : {exc}",
                               level="error", data={"action_id": action.value, "code": exc.code, "status": exc.status,
                                                    "detail": exc.detail[:300]})
            raise
        finally:
            if held:
                self._running.pop(action.value, None)
        outcome = {"action_id": action.value, **outcome}
        self._journal.emit("product.readiness.action_done", f"Action {action.value} : {outcome.get('status')}",
                           data={"action_id": action.value, "status": outcome.get("status")})
        outcome["report"] = await self.report(force=action is ActionId.RECHECK)
        return outcome

    async def _recheck(self) -> dict[str, Any]:
        self._brain_cache = None
        self._audio_cache = None
        return {"status": "done", "message": "Vérification refaite."}

    async def _prepare_data(self) -> dict[str, Any]:
        home = self._installation.home
        if home is None:
            raise ReadinessActionError(409, "not_installed_product", NOT_INSTALLED,
                                       "a development checkout has no product home to prepare")
        created = []
        try:
            for name, path in (("data", home.data), ("runtime", home.runtime), ("config", home.config)):
                if not path.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                    created.append(name)
        except OSError as exc:
            raise ReadinessActionError(500, "product_home_not_writable", "Windows refuse l'écriture dans le dossier de "
                                       "JARVIS (antivirus ou dossier protégé). Réessayez ; si cela recommence, "
                                       "redémarrez Windows.", f"{type(exc).__name__}: {exc.strerror or exc}"[:300]) from exc
        return {"status": "done", "message": "Dossier préparé." if created else "Dossier déjà complet.",
                "created": created}

    async def _verify_installation(self) -> dict[str, Any]:
        layout = self._layout
        if not isinstance(layout, PackageLayout):
            raise ReadinessActionError(409, "not_installed_product", NOT_INSTALLED,
                                       "a development checkout has no package to verify")
        self._running[ActionId.VERIFY_INSTALLATION.value] = self._monotonic()

        async def run() -> None:
            try:
                manifest, problems = await asyncio.to_thread(self._verify, layout)
                self._integrity = Probe(value=(manifest or {}).get("package_sha256")) if not problems else Probe(
                    error="; ".join(problems)[:600])
                level = "info" if not problems else "error"
                self._journal.emit("product.installation.verified",
                                   "Installation intacte" if not problems else f"Installation altérée : {len(problems)} problème(s)",
                                   level=level, data={"problems": problems[:20]})
            except Exception as exc:  # noqa: BLE001 - captured: shown as the line's detail and journaled
                self._integrity = Probe(error=f"verify_failed: {type(exc).__name__}: {exc}"[:300])
                self._journal.emit("product.installation.verify_failed", f"Vérification impossible : {type(exc).__name__}",
                                   level="error", data={"exception_type": type(exc).__name__})
            finally:
                self._running.pop(ActionId.VERIFY_INSTALLATION.value, None)

        self._spawn(run())
        return {"status": "started", "message": "Vérification des fichiers lancée."}

    async def _render(self, operation: str) -> dict[str, Any]:
        key = {"install": ActionId.RENDER_INSTALL, "repair": ActionId.RENDER_REPAIR, "update": ActionId.RENDER_UPDATE,
               "enable": ActionId.RENDER_ENABLE}[operation].value
        self._running[key] = self._monotonic()
        try:
            payload = await self._core("POST", f"/v1/local-capabilities/remotion/{operation}", {})
        except BaseException:
            self._running.pop(key, None)
            raise
        view = payload.get("capability") if isinstance(payload.get("capability"), Mapping) else {}
        status = str(view.get("status") or "")
        if status in RENDER_BUSY:
            # QA runtime m1 : la marque reste tant que Core prépare le moteur (relevé suivant : `facts` la retire),
            # pour que la ligne garde son compteur de secondes jusqu'à « Prêt ».
            return {"status": "started", "message": RENDER_STARTED.get(operation, "Préparation du moteur de rendu lancée."),
                    "capability_status": status}
        self._running.pop(key, None)
        return {"status": "done", "message": RENDER_DONE.get(status, "Moteur de rendu : état relevé, voyez la ligne."),
                "capability_status": status}

    async def _brain_install_guide(self) -> dict[str, Any]:
        return {"status": "open", "url": brain_cli.INSTALL_GUIDE_URL,
                "message": "Installez Claude Code depuis la page d'Anthropic, puis revenez ici et vérifiez à nouveau."}

    async def _brain_sign_in(self) -> dict[str, Any]:
        if self._signing_in():
            return {"status": "started", "message": "Une connexion est déjà ouverte dans sa fenêtre."}
        cli = await asyncio.to_thread(self._locate_brain)
        if cli is None:
            raise ReadinessActionError(409, "claude_cli_not_found", "Claude Code n'est pas encore installé : ouvrez "
                                       "d'abord la page d'installation.", "Claude Code is not installed yet")
        try:
            self._sign_in = await asyncio.to_thread(self._start_sign_in, cli)
        except OSError as exc:
            raise ReadinessActionError(500, "claude_sign_in_unstartable", "La fenêtre de connexion de Claude n'a pas "
                                       "pu s'ouvrir. Réessayez.", f"{type(exc).__name__}: {exc}"[:300]) from exc
        self._brain_cache = None
        return {"status": "started", "message": "Terminez la connexion dans la fenêtre de Claude."}

    async def _connect_circoe(self) -> dict[str, Any]:
        listed = await self._core("GET", "/v1/mcp/plugins")
        plugins = [row for row in listed.get("plugins") or [] if isinstance(row, Mapping)]
        plugin = next((row for row in plugins if row.get("endpoint") == CIRCUIT_TOOLBOX_ENDPOINT), None)
        if plugin is None:
            created = await self._core("POST", "/v1/mcp/plugins", {"endpoint": CIRCUIT_TOOLBOX_ENDPOINT,
                                                                   "display_name": CIRCOE_DISPLAY_NAME})
            plugin = created.get("plugin") if isinstance(created.get("plugin"), Mapping) else None
            if plugin is None:
                raise ReadinessActionError(502, "plugin_create_unreadable", "Le compte CIRCOE n'a pas pu être relié. "
                                           "Réessayez.", "Core registered the account without returning it")
        plugin_id = str(plugin.get("plugin_id") or plugin.get("id") or "")
        if not plugin_id:
            raise ReadinessActionError(502, "plugin_id_missing", "Le compte CIRCOE n'a pas pu être relié. Réessayez.",
                                       "the CIRCOE account has no identifier")
        answer = await self._core("POST", f"/v1/mcp/plugins/{plugin_id}/connect", {"strategy": "auto"})
        if answer.get("status") == "authorizing" and answer.get("authorization_url"):
            return {"status": "open", "url": str(answer["authorization_url"]),
                    "message": "Autorisez JARVIS dans la page CIRCOE qui s'ouvre, puis revenez ici."}
        if answer.get("status") == "connected":
            return {"status": "done", "message": "Compte CIRCOE relié."}
        return {"status": "done", "message": "Le compte CIRCOE n'est pas encore relié : ouvrez Connexions pour voir où "
                "il en est.", "connection_status": str(answer.get("status") or "")}

    async def _open_connections(self) -> dict[str, Any]:
        return {"status": "navigate", "target": "connections", "message": "Ouverture de Connexions."}

    def _spawn(self, coroutine: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


def _facts_dict(facts: BrainFacts) -> dict[str, Any]:
    return {"found": facts.found, "version": facts.version, "logged_in": facts.logged_in,
            "auth_method": facts.auth_method, "error": facts.error, "sign_in_running": facts.sign_in_running}


def _default_browser() -> str | None:
    from jarvis.adapters.remotion_render_runner import RemotionRenderRunner

    found = RemotionRenderRunner(lambda: Path(".")).find_browser()
    if found is None:
        return None
    return found.version if found.version != "unknown" else Path(found.path).stem


def _pid_alive(pid: int) -> bool:
    from jarvis.adapters import process_tree

    try:
        return bool(process_tree.pid_exists(pid))
    except Exception:  # noqa: BLE001 - argued: an unreadable pid means no managed launcher; "Quitter" stays hidden
        return False


def _ref_alive(ref: str) -> bool:
    from jarvis.adapters import process_tree

    try:
        return bool(process_tree.ref_alive(ref))
    except Exception:  # noqa: BLE001 - argued: an unreadable identity means no managed launcher; "Quitter" stays hidden
        return False


class ProductReadinessRoutes:
    """Routes `/api/product/*` du Control Center. Erreurs : `{"error": {"code", "message"}}`, journalisées."""

    def __init__(self, service: ProductReadinessService, *, journal: RuntimeJournal) -> None:
        self._service = service
        self._journal = journal

    def routes(self) -> list[web.RouteDef]:
        return [
            web.get("/api/product/readiness", self.readiness),
            web.post("/api/product/readiness/actions/{action_id}", self.action),
            web.post("/api/product/onboarding/complete", self.complete),
            web.post("/api/product/quit", self.quit),
        ]

    async def _guard(self, name: str, call: Callable[[], Awaitable[Any]]) -> web.Response:
        try:
            return web.json_response(await call())
        except ReadinessActionError as exc:
            return _error(exc.status, exc.code, str(exc), exc.detail)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced: 500 with its cause, journaled at error
            self._journal.emit(f"product.{name}.failed", f"{name} : {type(exc).__name__}: {str(exc)[:200]}",
                               level="error", data={"code": f"product_{name}_failed", "exception_type": type(exc).__name__})
            return _error(500, f"product_{name}_failed", "Une erreur inattendue est survenue. Réessayez ; le détail est "
                          "dans le journal de JARVIS.", f"{type(exc).__name__}: {str(exc)[:200]}")

    async def readiness(self, request: web.Request) -> web.Response:
        if set(request.query) - {"force"}:
            return _error(400, "invalid_request", "Demande mal formée.", "unexpected query parameters")
        return await self._guard("readiness", lambda: self._service.report(force=request.query.get("force") == "1"))

    async def action(self, request: web.Request) -> web.Response:
        return await self._guard("readiness_action", lambda: self._service.act(request.match_info["action_id"]))

    async def complete(self, request: web.Request) -> web.Response:
        del request
        return await self._guard("onboarding", self._service.complete_onboarding)

    async def quit(self, request: web.Request) -> web.Response:
        del request

        async def run() -> dict[str, Any]:
            return self._service.request_quit()

        return await self._guard("quit", run)

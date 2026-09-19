"""Serveur MCP stdio « jarvis-barehands » : le cerveau pilote les mains nues (handoff jarvis-bare-hands-v1, Slice 12).

Décision 6 : le bouton d'interface **et la voix** activent/désactivent Bare
Hands. Le constat F1 de la Slice 00 a établi le chemin réel d'une commande
vocale dans ce dépôt : parole → cerveau (CLI Claude) → **outil MCP** → Control
Center → page. La surface Realtime n'a aucun outil en `continuous_brain`
(Décision 34) et il n'existe ni registre de commandes vocales ni routeur
d'intention : ce serveur est donc le seul point d'entrée de la voix.

Le cerveau conversationnel le reçoit par un `--mcp-config` généré, seulement
quand `barehands_test_mode.enabled` est vrai — exactement comme `jarvis-display`
est donné seulement quand `scene.enabled` l'est. Éteint, **la surface est
absente** : pas d'outil grisé, pas de refus à expliquer, rien à halluciner.

Contrairement à `display_mcp`, ce serveur joint le **Control Center**, pas Core :
Bare Hands n'existe nulle part dans Core (ni interrupteur, ni réglages, ni page).
Il parle à la boucle locale. **Les deux POST** (`POST /api/barehands/commands`
et le reçu) sont protégés par le même garde d'origine que `POST /api/barehands`,
l'interrupteur que cette même route bascule déjà : pour eux, un appelant capable
d'atteindre l'une atteint l'autre, et ce canal n'ajoute aucune autorité.

**Le GET, lui, ne l'est pas** : `GET /api/barehands/commands` n'est pas dans
`READ_GUARDED_ROUTES`, donc une page tierce visitée pendant que Bare Hands est
allumé peut ouvrir le long-poll et **consommer une remise** — elle ne peut ni
lire la réponse (pas de CORS) ni forger un reçu (le POST est gardé, et
l'identifiant est imprévisible), mais elle peut faire disparaître une commande.
`GET /api/scene/patches` a exactement la même forme : c'est un motif préexistant
du dépôt, pas une invention de cette Slice, et le corriger vaut pour les deux à
la fois. La QA de la Slice 12 l'a relevé ; l'Issue est ouverte.

Catalogue V1, cinq outils, un par action (Slice 12) : `barehands_activate`,
`barehands_deactivate`, `barehands_calibrate`, `barehands_tutorial`,
`barehands_exit_overlay`.

**Aucun faux succès.** Un outil ne rend un succès que si la page a rapporté
l'état qu'elle a **constaté** après avoir appelé le point d'entrée. Tout le
reste — refus de la page, échéance, canal injoignable, Bare Hands éteint —
devient une erreur d'outil portant son code stable et une phrase qui dit quoi
faire. Les parcours de calibration et de tutoriel n'existent pas encore (Slices
08 et 09) : le transport les porte, la page les refuse avec
`barehands_flow_absent`, et le cerveau reçoit cette phrase-là.

Le module n'importe pas `mcp` : `build_server` le charge à la demande, comme
`display_mcp` et `drive_mcp`, pour que `ClaudeLocalAgent` puisse en lire les
constantes sans la dépendance facultative.
"""

# Pas de `from __future__ import annotations` : FastMCP lit les annotations des
# outils définis dans `build_server`.
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping

import aiohttp

from jarvis.domain.barehands_command import (
    CHANNEL_UNREACHABLE,
    COMMAND_DEADLINE_S,
    COMMANDS,
    PAGE_CODE_EXPLANATIONS,
)
from jarvis.runtime.journal import RuntimeJournal
from jarvis.v2_config import validate_loopback_host

SERVER_NAME = "jarvis-barehands"
#: Fichier `--mcp-config` écrit dans le dossier runtime au lancement du cerveau.
CONFIG_FILE_NAME = "barehands-mcp.json"
#: Un outil par action ; l'ordre est celui du contrat de la Slice.
TOOL_NAMES = (
    "barehands_activate",
    "barehands_deactivate",
    "barehands_calibrate",
    "barehands_tutorial",
    "barehands_exit_overlay",
)
#: Outil → commande du vocabulaire (`jarvis/domain/barehands_command.py`).
#: Table unique : un test vérifie qu'elle couvre `COMMANDS` exactement, donc
#: une commande ajoutée sans outil (ou l'inverse) tombe.
TOOL_COMMANDS: dict[str, str] = {
    "barehands_activate": "activate",
    "barehands_deactivate": "deactivate",
    "barehands_calibrate": "calibrate",
    "barehands_tutorial": "tutorial",
    "barehands_exit_overlay": "exit_overlay",
}

ENV_HOST = "JARVIS_CONTROL_CENTER_HOST"
ENV_PORT = "JARVIS_CONTROL_CENTER_PORT"
ENV_RUNTIME_DIR = "JARVIS_RUNTIME_DIR"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17654
ROUTE = "/api/barehands/commands"
#: Le Control Center attend la page au plus `COMMAND_DEADLINE_S` ; la lecture de
#: sa réponse a cette échéance plus une marge, jamais moins : couper plus tôt
#: que le serveur ferait disparaître la vraie cause derrière un délai de client.
READ_TIMEOUT_S = COMMAND_DEADLINE_S + 5.0
CONNECT_TIMEOUT_S = 3.0
#: En-tête où le Control Center reprend le code stable d'un refus.
ERROR_CODE_HEADER = "X-Jarvis-Error-Code"


class BarehandsConfigError(RuntimeError):
    """Environnement du serveur incomplet ou invalide : le serveur ne démarre pas."""


class BarehandsToolError(Exception):
    """Erreur rendue au cerveau comme erreur d'outil (`isError`). Le message se suffit à lui-même."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BarehandsMcpTarget:
    """Où le serveur Bare Hands joint le Control Center ; transmis par l'environnement du processus."""

    __slots__ = ("host", "port", "runtime_root")

    def __init__(self, host: str, port: int, runtime_root: Path | None = None) -> None:
        self.host = host
        self.port = port
        self.runtime_root = runtime_root

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BarehandsMcpTarget):
            return NotImplemented
        return (self.host, self.port, self.runtime_root) == (other.host, other.port, other.runtime_root)

    def __repr__(self) -> str:
        return f"BarehandsMcpTarget(host={self.host!r}, port={self.port!r}, runtime_root={self.runtime_root!r})"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def env(self) -> dict[str, str]:
        values = {ENV_HOST: self.host, ENV_PORT: str(self.port)}
        if self.runtime_root is not None:
            values[ENV_RUNTIME_DIR] = str(Path(self.runtime_root).resolve())
        return values

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "BarehandsMcpTarget":
        env = os.environ if environ is None else environ
        try:
            host = validate_loopback_host(env.get(ENV_HOST) or DEFAULT_HOST)
        except Exception as exc:  # noqa: BLE001 - message rendu tel quel, comme `DisplayMcpTarget`
            raise BarehandsConfigError(f"{ENV_HOST} invalide : {exc}") from exc
        raw_port = env.get(ENV_PORT) or str(DEFAULT_PORT)
        try:
            port = int(raw_port)
        except ValueError:
            raise BarehandsConfigError(f"{ENV_PORT} doit être un entier, reçu {raw_port[:20]!r}") from None
        if not 1 <= port <= 65535:
            raise BarehandsConfigError(f"{ENV_PORT} doit être entre 1 et 65535")
        runtime = env.get(ENV_RUNTIME_DIR)
        return cls(host, port, Path(runtime).expanduser().resolve() if runtime else None)


def mcp_config(target: BarehandsMcpTarget, *, python: str | None = None) -> dict[str, Any]:
    """Le document `--mcp-config` : ce seul serveur, même interpréteur, `-m jarvis barehands-mcp`."""

    return {
        "mcpServers": {
            SERVER_NAME: {
                "type": "stdio",
                "command": python or sys.executable,
                "args": ["-m", "jarvis", "barehands-mcp"],
                "env": target.env(),
            }
        }
    }


def write_mcp_config(target: BarehandsMcpTarget, directory: Path, *, python: str | None = None) -> Path:
    """Écrire le `--mcp-config` de façon atomique dans `directory` ; rend son chemin absolu.

    Même forme et mêmes raisons que `display_mcp.write_mcp_config` : un fichier
    plutôt que du JSON en ligne, parce qu'un shim `.cmd` réinterprète les
    guillemets. `OSError` à l'appelant.
    """

    from jarvis.adapters.file_replace import replace_with_retry

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target_path = directory / CONFIG_FILE_NAME
    text = json.dumps(mcp_config(target, python=python), ensure_ascii=False, indent=2) + "\n"
    handle, raw_tmp = tempfile.mkstemp(prefix=CONFIG_FILE_NAME + ".", suffix=".tmp", dir=directory)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        replace_with_retry(tmp, target_path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass  # intentional: the original failure is what the caller must see; a stray .tmp is harmless
        raise
    return target_path


#: Ce que le cerveau lit après un succès : l'état **constaté** par la page,
#: jamais l'état demandé.
_OUTCOME_SENTENCES = {
    "applied": "Fait.",
    "duplicate": "Rien à faire : Bare Hands était déjà dans cet état.",
}


class BarehandsCommandTools:
    """La logique des outils, indépendante de FastMCP : testable contre un vrai Control Center."""

    def __init__(
        self,
        target: BarehandsMcpTarget,
        *,
        journal: RuntimeJournal | None = None,
        session_factory: Any = None,
    ) -> None:
        self.target = target
        self.journal = journal
        self._session_factory = session_factory
        self._session: Any = None

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _http(self) -> Any:
        if self._session is None or self._session.closed:
            factory = self._session_factory or aiohttp.ClientSession
            self._session = factory()
        return self._session

    async def send(self, tool: str, command: str) -> dict[str, Any]:
        """Poster la commande et rendre ce que la page a constaté.

        Toute issue autre qu'un reçu `applied`/`duplicate` lève une
        `BarehandsToolError` : le cerveau ne reçoit jamais « c'est fait » pour
        une commande qui ne l'est pas.
        """

        timeout = aiohttp.ClientTimeout(total=READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
        session = await self._http()
        try:
            async with session.post(
                self.target.base_url + ROUTE, json={"command": command}, timeout=timeout
            ) as response:
                status = response.status
                header_code = response.headers.get(ERROR_CODE_HEADER)
                try:
                    body = await response.json(content_type=None)
                except ValueError:
                    body = None
        except aiohttp.ClientError as exc:
            self._emit("barehands.tool_failed", f"{tool} : Control Center injoignable", level="error",
                       data={"tool": tool, "command": command, "code": CHANNEL_UNREACHABLE,
                             "error": f"{type(exc).__name__}: {exc}"[:200]})
            raise BarehandsToolError(
                CHANNEL_UNREACHABLE,
                f"Le Control Center est injoignable ({type(exc).__name__}) : la commande n'a pas été envoyée. "
                "Dis à l'utilisateur que la fenêtre du Control Center doit être ouverte.",
            ) from None
        except TimeoutError:
            self._emit("barehands.tool_failed", f"{tool} : Control Center muet", level="error",
                       data={"tool": tool, "command": command, "code": CHANNEL_UNREACHABLE})
            raise BarehandsToolError(
                CHANNEL_UNREACHABLE,
                f"Le Control Center n'a pas répondu en {READ_TIMEOUT_S:g} s : la commande est perdue, rien n'a été appliqué.",
            ) from None
        if status != 200:
            error = body.get("error") if isinstance(body, dict) else None
            code = header_code or (error.get("code") if isinstance(error, dict) else None) or CHANNEL_UNREACHABLE
            message = (error.get("message") if isinstance(error, dict) else None) or f"HTTP {status}"
            command_id = error.get("id") if isinstance(error, dict) else None
            self._emit("barehands.tool_failed", f"{tool} : {code}", level="warning",
                       data={"tool": tool, "command": command, "id": command_id, "code": code,
                             "status": status})
            raise BarehandsToolError(code, self._explain(code, message))
        if not isinstance(body, dict) or body.get("outcome") not in _OUTCOME_SENTENCES:
            code = body.get("code") if isinstance(body, dict) else None
            reason = body.get("reason") if isinstance(body, dict) else None
            lifecycle = body.get("lifecycle") if isinstance(body, dict) else None
            self._emit("barehands.tool_failed", f"{tool} : refusé par la page ({code})", level="warning",
                       data={"tool": tool, "command": command, "id": body.get("id") if isinstance(body, dict) else None,
                             "code": code, "lifecycle": lifecycle, "reason": reason})
            detail = f"Bare Hands est en état « {lifecycle} »." if lifecycle else ""
            if reason:
                detail = (detail + " " + str(reason)).strip()
            raise BarehandsToolError(
                str(code or CHANNEL_UNREACHABLE),
                self._explain(str(code or ""), detail or "La page a refusé la commande sans la décrire."),
            )
        # `id` : l'identifiant court du courtier, recopié tel quel. C'est la
        # seule chose qui relie cette ligne aux `barehands.command_*` de la même
        # commande ; sans elle, deux commandes de même nom qui se suivent ne se
        # distinguent que par l'heure, et l'opérateur devine (QA de la Slice 12).
        self._emit("barehands.tool", f"{tool} : {body['outcome']}", data={
            "tool": tool, "command": command, "id": body.get("id"), "outcome": body["outcome"],
            "lifecycle": body.get("lifecycle"), "duration_ms": body.get("duration_ms"),
            "deliveries": body.get("deliveries")})
        return {
            "command": command,
            "outcome": body["outcome"],
            "lifecycle": body.get("lifecycle"),
            "note": _OUTCOME_SENTENCES[body["outcome"]],
        }

    @staticmethod
    def _explain(code: str, message: str) -> str:
        """La phrase du serveur, augmentée de l'explication du code quand il y en a une."""

        explanation = PAGE_CODE_EXPLANATIONS.get(code)
        return f"{message} {explanation}".strip() if explanation else message

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except OSError:
            pass  # intentional: a full disk must not turn a command the page applied into a tool failure


_SERVER_INSTRUCTIONS = (
    "Piloter Bare Hands, le pointeur à mains nues de la page du Control Center ouverte. "
    "Ces outils n'existent que quand l'utilisateur a allumé Bare Hands. "
    "Ils agissent sur la fenêtre visible : sans fenêtre visible, ils refusent au lieu de faire semblant."
)


def build_server(target: BarehandsMcpTarget | None = None, *, tools: BarehandsCommandTools | None = None):
    """Construire le serveur FastMCP. `tools` : injection pour les tests."""

    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError

    if tools is None:
        target = target or BarehandsMcpTarget.from_env()
        journal = RuntimeJournal(target.runtime_root) if target.runtime_root is not None else None
        tools = BarehandsCommandTools(target, journal=journal)
    hands = tools

    class StrictBarehandsMCP(FastMCP):
        """Arguments inconnus refusés, refus rendus tels quels.

        Même raison que `StrictDisplayMCP` : par défaut FastMCP ignore un
        argument inconnu et répond succès, donc un appel fantaisiste passerait
        pour appliqué. Ces outils n'ont aucun argument : *tout* argument est
        inconnu, et le dire vaut mieux que l'avaler.
        """

        async def list_tools(self):  # noqa: ANN201 - type de FastMCP
            listed = await super().list_tools()
            for tool in listed:
                tool.inputSchema = {**tool.inputSchema, "additionalProperties": False}
            return listed

        async def call_tool(self, name: str, arguments: dict[str, Any]):  # noqa: ANN201 - type de FastMCP
            if arguments:
                raise ToolError(
                    f"Arguments inconnus refusés, rien n'a été envoyé : {', '.join(sorted(arguments))}. "
                    f"{name} ne prend aucun argument."
                )
            try:
                return await super().call_tool(name, arguments)
            except ToolError as exc:
                cause = exc.__cause__
                if isinstance(cause, BarehandsToolError):
                    # Même forme pour toutes les erreurs de ces outils : le
                    # message, sans le préfixe « Error executing tool … ».
                    raise ToolError(str(cause)) from None
                raise

    mcp = StrictBarehandsMCP(SERVER_NAME, instructions=_SERVER_INSTRUCTIONS)

    _FLOW_NOTE = (
        "Le parcours lui-même n'est pas encore implanté : l'outil refuse avec barehands_flow_absent "
        "tant qu'il n'existe pas. N'annonce jamais qu'il a démarré."
    )

    @mcp.tool()
    async def barehands_activate() -> dict:
        """Réveiller Bare Hands : la main pilote l'interface tout de suite, sans faire la posture en C.

        À appeler quand l'utilisateur demande d'activer les mains, la main, le pointeur à la main,
        ou de pouvoir cliquer sans souris. Refus : barehands_disabled (l'utilisateur ne l'a pas allumé
        dans l'onglet Expérimental), barehands_no_visible_page (aucune fenêtre du Control Center visible),
        barehands_lifecycle_refused (la page n'a pas atteint l'état, caméra indisponible par exemple).
        """
        return await hands.send("barehands_activate", "activate")

    @mcp.tool()
    async def barehands_deactivate() -> dict:
        """Remettre Bare Hands en veille : la main ne pilote plus, la caméra reste prête.

        À appeler quand l'utilisateur demande d'arrêter, de désactiver ou de mettre en pause les mains.
        N'éteint pas Bare Hands (l'interrupteur appartient à l'utilisateur) : la veille se réveille
        par la posture en C ou par barehands_activate.
        """
        return await hands.send("barehands_deactivate", "deactivate")

    @mcp.tool(description=f"""Lancer la calibration de Bare Hands (mesure des seuils de la main de l'utilisateur).

{_FLOW_NOTE}""")
    async def barehands_calibrate() -> dict:
        return await hands.send("barehands_calibrate", "calibrate")

    @mcp.tool(description=f"""Lancer le tutoriel de Bare Hands (apprentissage des gestes).

{_FLOW_NOTE}""")
    async def barehands_tutorial() -> dict:
        return await hands.send("barehands_tutorial", "tutorial")

    @mcp.tool(description=f"""Fermer le panneau de calibration ou de tutoriel ouvert et revenir à l'interface.

{_FLOW_NOTE}""")
    async def barehands_exit_overlay() -> dict:
        return await hands.send("barehands_exit_overlay", "exit_overlay")

    return mcp


async def serve_stdio() -> int:
    """Point d'entrée de `python -m jarvis barehands-mcp` : stdout est le protocole, rien d'autre n'y écrit."""

    target = BarehandsMcpTarget.from_env()
    journal = RuntimeJournal(target.runtime_root) if target.runtime_root is not None else None
    if journal is not None:
        journal.emit("barehands.server_started", "Serveur MCP Bare Hands démarré",
                     data={"host": target.host, "port": target.port, "pid": os.getpid()})
    tools = BarehandsCommandTools(target, journal=journal)
    try:
        await build_server(target, tools=tools).run_stdio_async()
    finally:
        await tools.close()
        if journal is not None:
            journal.emit("barehands.server_stopped", "Serveur MCP Bare Hands arrêté", data={"pid": os.getpid()})
    return 0


#: Garde-fou de chargement : la table d'outils et le vocabulaire doivent se
#: couvrir exactement. Un nom ajouté d'un seul côté serait un outil sans
#: commande (refus HTTP à l'usage) ou une commande sans outil (invisible au
#: cerveau, donc indiscernable d'une capacité absente).
if tuple(TOOL_COMMANDS) != TOOL_NAMES or tuple(TOOL_COMMANDS.values()) != COMMANDS:
    raise RuntimeError("barehands_mcp : TOOL_COMMANDS ne couvre pas TOOL_NAMES × COMMANDS")

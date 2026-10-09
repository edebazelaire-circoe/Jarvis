"""Serveur MCP stdio « jarvis-barehands » : le cerveau pilote les mains nues (handoff jarvis-bare-hands-v1, Slice 12).

Décision 6 : le bouton d'interface **et la voix** activent/désactivent Bare
Hands. Le constat F1 de la Slice 00 a établi le chemin réel d'une commande
vocale dans ce dépôt : parole → cerveau (CLI Claude) → **outil MCP** → Control
Center → page. La surface Realtime n'a aucun outil en `continuous_brain`
(Décision 34) et il n'existe ni registre de commandes vocales ni routeur
d'intention : ce serveur est donc le seul point d'entrée de la voix.

Le cerveau conversationnel le reçoit par un `--mcp-config` généré, **sans
interrupteur** depuis le 2026-10-07 (comme `jarvis-console`) : éteint, les outils
sont là et refusent `barehands_disabled` avec la phrase qui dit d'appeler
`settings_set(barehands.enabled, true)`. Quand la surface disparaissait avec
l'interrupteur, « active Bare Hands » tombait sur un cerveau qui ne savait pas ce
que c'est, et l'allumer ne rendait les outils qu'au redémarrage suivant.

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
`barehands_exit_overlay` ; plus `barehands_test` (tâche adaptative, Slice 10),
qui ouvre le Tester par la porte de son bouton.

**Dix outils de calibration** (tâche adaptative, Slice 06, décisions 50 à 55 ;
`docs/barehands-contracts.md` § 17 ; propositions du 28/09) : `calibration_status`,
`calibration_record_feedback`, `calibration_propose_hypothesis`,
`calibration_prepare_trial` (une proposition visible, rien d'appliqué),
`calibration_commit_proposal` (sur l'accord vérifié de l'utilisateur),
`calibration_resolve_trial`,
`calibration_rollback_trial`, `calibration_accept_trial`,
`calibration_rerun_exercise`, `calibration_next_exercise`. Ils sont déclarés
**avec** le serveur (les outils d'un CLI sont figés à son lancement, READINESS
D1) et refusent `barehands_calibration_inactive` hors d'une séance ouverte à
l'écran. Ils ont des arguments, fermés et validés deux fois (schéma d'entrée
ici, schéma de charge utile au Control Center) ; ils rendent le résultat
structuré que la page a **constaté**.

**`barehands_tutorial` est déprécié depuis la Slice 07B** et ouvre la
calibration : le parcours de tutoriel séparé a été retiré (décisions 10 et 17),
il n'y a plus qu'un parcours guidé. L'outil n'est pas supprimé parce que son nom
est miroité sous assertion de parité au chargement (fin de ce module) et que le
retirer serait une rupture coordonnée sur trois fichiers ; il rend à la place ce
que la page a **constaté**, c'est-à-dire que la calibration s'est ouverte.

**Aucun faux succès.** Un outil ne rend un succès que si la page a rapporté
l'état qu'elle a **constaté** après avoir appelé le point d'entrée. Tout le
reste — refus de la page, échéance, canal injoignable, Bare Hands éteint —
devient une erreur d'outil portant son code stable et une phrase qui dit quoi
faire. Les trois parcours **existent** depuis les Slices 08 et 09 ; ce qu'un
succès affirme est qu'ils ont **démarré**, pas qu'ils sont finis — un parcours
dure des minutes et c'est l'utilisateur qui le mène à la main. Une page plus
ancienne que ce JARVIS les refuse encore avec `barehands_flow_absent`, et le
cerveau reçoit cette phrase-là.

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
from typing import Annotated, Any, Literal, Mapping, TypedDict

import aiohttp

from jarvis.domain.barehands_calibration import (
    CALIBRATION_COMMANDS,
    CALIBRATION_METRICS,
    COMMIT_ACTIONS,
    COMPARISONS_MAX,
    EVIDENCE_MAX,
    FEEDBACK_CATEGORIES,
    FEEDBACK_CATEGORIES_MAX,
    FEEDBACK_REFS_MAX,
    FEEDBACK_TEXT_MAX,
    HYPOTHESIS_CAUSES,
    METRIC_AGGREGATES,
    OUTCOME_REFS_MAX,
    PATCH_KEYS_MAX,
    PROPOSAL_TEXT_MAX,
    QUOTE_MAX,
    QUOTE_MIN,
    SOURCE_REFS_MAX,
    SKIP_REASONS,
    STAGES,
    TRIAL_KEYS,
    TRIAL_VERDICTS,
)
from jarvis.domain.barehands_command import (
    CHANNEL_UNREACHABLE,
    COMMAND_DEADLINE_S,
    COMMANDS,
    PAGE_CODE_EXPLANATIONS,
)
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.mcp_tool_meta import tool_annotations, tool_names
from jarvis.v2_config import validate_loopback_host

SERVER_NAME = "jarvis-barehands"
#: Fichier `--mcp-config` écrit dans le dossier runtime au lancement du cerveau.
CONFIG_FILE_NAME = "barehands-mcp.json"
#: Un outil par action ; l'ordre est celui du contrat de la Slice, tenu par les
#: métadonnées partagées (`mcp_tool_meta`).
TOOL_NAMES = tool_names(SERVER_NAME)
#: Outil → commande du vocabulaire (`jarvis/domain/barehands_command.py`).
#: Table unique : un test vérifie qu'elle couvre `COMMANDS` exactement, donc
#: une commande ajoutée sans outil (ou l'inverse) tombe.
TOOL_COMMANDS: dict[str, str] = {
    "barehands_activate": "activate",
    "barehands_deactivate": "deactivate",
    "barehands_calibrate": "calibrate",
    "barehands_tutorial": "tutorial",
    "barehands_exit_overlay": "exit_overlay",
    "barehands_test": "test",
}
#: Les outils de calibration (Slice 06 adaptative) : **une commande du même nom**
#: chacun (`jarvis/domain/barehands_calibration.CALIBRATION_COMMANDS`). Toujours
#: déclarés avec le serveur ; hors séance, le Control Center les refuse
#: (`barehands_calibration_inactive`) avant toute attente.
CALIBRATION_TOOLS: tuple[str, ...] = CALIBRATION_COMMANDS

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


#: Ce qu'un succès de calibration **affirme**, et rien de plus.
_CALIBRATION_NOTES: dict[str, str] = {
    "calibration_status": "État lu dans la page : ne cite que ces nombres, par leurs références.",
    "calibration_record_feedback": "Retour noté dans la séance. Ce n'est pas un réglage.",
    "calibration_propose_hypothesis": "Hypothèse ouverte ; les valeurs de ses preuves sont calculées par le code.",
    "calibration_prepare_trial": ("Proposition affichée dans le panneau, NON appliquée : rien n'a changé dans le "
                                  "moteur. Dis ce qu'elle changerait et demande à l'utilisateur s'il l'applique ; "
                                  "il peut aussi corriger les valeurs et valider dans le panneau."),
    "calibration_commit_proposal": ("Transaction faite par le runtime : steps dit ce qui est vrai (applied, "
                                    "verified = valeurs relues chez le moteur, rerun = exercice relancé, saved + "
                                    "advanced = gardé sans revérification, étape suivante). N'annonce que ces "
                                    "étapes-là."),
    "calibration_resolve_trial": "Essai jugé sur les mesures ; la confiance de l'hypothèse suit une règle fixe.",
    "calibration_rollback_trial": "Essai annulé : restored = valeurs d'avant, relues chez le moteur.",
    "calibration_accept_trial": "Réglage enregistré, sur l'accord de l'utilisateur : accepted = ce qui a été rangé.",
    "calibration_rerun_exercise": "L'exercice est relancé à l'écran.",
    "calibration_next_exercise": ("L'exercice suivant est à l'écran. decision dit ce qui a été fait : validated = "
                                  "l'étape est validée, skipped = elle est passée (mesure non gardée) — annonce celle-là."),
}
#: Phrases des refus de calibration, ajoutées au message comme celles de la page.
_CALIBRATION_EXPLANATIONS: dict[str, str] = {
    "barehands_calibration_inactive": (
        "Aucune séance de calibration n'est ouverte : ces outils ne servent que pendant une calibration."),
    "barehands_calibration_refused": (
        "Rien n'a été changé. Dis à l'utilisateur ce qui bloque sans nommer de paramètre."),
    "barehands_calibration_consent_missing": "Rien n'a été enregistré.",
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

        status, header_code, body = await self._post(tool, command, {"command": command})
        if status != 200:
            self._refused_by_server(tool, command, status, header_code, body)
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
        # **Ce que la page a dit de son propre parcours, recopié tel quel**
        # (Slice 07B). Le reçu d'un succès pouvait jusqu'ici porter un `reason`
        # que personne ne lisait ; il est devenu porteur le jour où une
        # commande a cessé d'ouvrir ce que son nom annonce. `barehands_tutorial`
        # ouvre la **calibration** : sans cette phrase, le cerveau lirait
        # « Fait. » sous le mot « tutoriel » et l'annoncerait à l'utilisateur —
        # le faux récit exact que ces outils existent pour empêcher. La phrase
        # n'est ni fabriquée ni complétée ici : elle vient du parcours.
        note = _OUTCOME_SENTENCES[body["outcome"]]
        said = body.get("reason")
        if isinstance(said, str) and said.strip():
            note = f"{note} {said.strip()}"
        return {
            "command": command,
            "outcome": body["outcome"],
            "lifecycle": body.get("lifecycle"),
            "note": note,
        }

    async def _post(self, tool: str, command: str, body: dict[str, Any]) -> tuple[int, str | None, Any]:
        """L'aller-retour HTTP d'une commande ; `BarehandsToolError(CHANNEL_UNREACHABLE)` sans réponse."""

        timeout = aiohttp.ClientTimeout(total=READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
        session = await self._http()
        try:
            async with session.post(self.target.base_url + ROUTE, json=body, timeout=timeout) as response:
                status = response.status
                header_code = response.headers.get(ERROR_CODE_HEADER)
                try:
                    answer = await response.json(content_type=None)
                except ValueError:
                    answer = None
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
        return status, header_code, answer

    def _refused_by_server(self, tool: str, command: str, status: int, header_code: str | None, body: Any) -> None:
        """Un refus HTTP du Control Center devient une erreur d'outil qui porte son code."""

        error = body.get("error") if isinstance(body, dict) else None
        code = header_code or (error.get("code") if isinstance(error, dict) else None) or CHANNEL_UNREACHABLE
        message = (error.get("message") if isinstance(error, dict) else None) or f"HTTP {status}"
        command_id = error.get("id") if isinstance(error, dict) else None
        self._emit("barehands.tool_failed", f"{tool} : {code}", level="warning",
                   data={"tool": tool, "command": command, "id": command_id, "code": code,
                         "status": status})
        raise BarehandsToolError(code, self._explain(code, message))

    async def calibrate(self, tool: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Une commande de calibration (Slice 06 adaptative) : ce que la page a **constaté**, à plat.

        Rend `{outcome, note, **result}` — `result` est le résultat structuré du
        reçu, déjà validé par le Control Center contre le schéma fermé de la
        commande. Un refus de la page (`barehands_calibration_inactive`,
        `barehands_calibration_refused`) devient une erreur d'outil qui nomme
        **chaque** faute précise du contrat : le cerveau doit pouvoir dire
        pourquoi, et ne jamais lire « fait » pour ce qui ne l'est pas.
        """

        command = tool
        body: dict[str, Any] = {"command": command}
        if payload is not None:
            body["payload"] = payload
        status, header_code, answer = await self._post(tool, command, body)
        if status != 200:
            self._refused_by_server(tool, command, status, header_code, answer)
        if not isinstance(answer, dict) or answer.get("outcome") not in _OUTCOME_SENTENCES:
            code = str(answer.get("code") or CHANNEL_UNREACHABLE) if isinstance(answer, dict) else CHANNEL_UNREACHABLE
            result = answer.get("result") if isinstance(answer, dict) else None
            errors = result.get("errors") if isinstance(result, dict) else None
            faults = "; ".join(f"{item.get('code')} : {item.get('message')}" for item in errors or []
                               if isinstance(item, dict))
            reason = answer.get("reason") if isinstance(answer, dict) else None
            self._emit("barehands.tool_failed", f"{tool} : refusé par la page ({code})", level="warning",
                       data={"tool": tool, "command": command, "code": code,
                             "id": answer.get("id") if isinstance(answer, dict) else None,
                             "faults": [item.get("code") for item in errors or [] if isinstance(item, dict)][:8]})
            detail = " ".join(part for part in (str(reason or "").strip(), faults) if part)
            raise BarehandsToolError(code, self._explain(code, detail or "La page a refusé sans dire pourquoi."))
        result = answer.get("result") if isinstance(answer.get("result"), dict) else {}
        self._emit("barehands.tool", f"{tool} : {answer['outcome']}", data={
            "tool": tool, "command": command, "id": answer.get("id"), "outcome": answer["outcome"],
            "duration_ms": answer.get("duration_ms"), "deliveries": answer.get("deliveries")})
        return {"outcome": answer["outcome"], "note": _CALIBRATION_NOTES[tool], **result}

    @staticmethod
    def _explain(code: str, message: str) -> str:
        """La phrase du serveur, augmentée de l'explication du code quand il y en a une."""

        explanation = PAGE_CODE_EXPLANATIONS.get(code) or _CALIBRATION_EXPLANATIONS.get(code)
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
    "Ces outils sont toujours là ; éteint, ils refusent barehands_disabled (allume avec settings_set(barehands.enabled, true)). "
    "Ils agissent sur la fenêtre visible : sans fenêtre visible, ils refusent au lieu de faire semblant. "
    "Les outils calibration_* ne servent que pendant une séance de calibration ouverte à l'écran."
)


def build_server(target: BarehandsMcpTarget | None = None, *, tools: BarehandsCommandTools | None = None):
    """Construire le serveur FastMCP. `tools` : injection pour les tests."""

    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError

    from pydantic import ConfigDict, Field, Strict, ValidationError, with_config

    from jarvis.runtime.mcp_results import (
        OUTPUT_CONTRACT_MESSAGE,
        BarehandsCommandResult,
        CalibrationAcceptResult,
        CalibrationExerciseResult,
        CalibrationFeedbackResult,
        CalibrationNextResult,
        CalibrationHypothesisResult,
        CalibrationResolveResult,
        CalibrationRollbackResult,
        CalibrationCommitResult,
        CalibrationProposalResult,
        CalibrationStatusResult,
        output_contract_fields,
    )

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
            if name in CALIBRATION_TOOLS:
                # Arguments **fermés** (même règle que `jarvis-display`) : une
                # clé inconnue n'est pas ignorée, elle est refusée.
                known = {tool.name: tool for tool in await self.list_tools()}
                allowed = set(known[name].inputSchema.get("properties", {})) if name in known else set()
                unknown = sorted(set(arguments or {}) - allowed)
                if unknown:
                    raise ToolError(
                        f"Arguments inconnus refusés, rien n'a été envoyé : {', '.join(unknown[:8])}. "
                        f"Arguments permis : {', '.join(sorted(allowed)) or 'aucun'}.")
            elif arguments:
                raise ToolError(
                    f"Arguments inconnus refusés, rien n'a été envoyé : {', '.join(sorted(arguments))}. "
                    f"{name} ne prend aucun argument."
                )
            try:
                return await super().call_tool(name, arguments)
            except ToolError as exc:
                cause = exc.__cause__
                broken = output_contract_fields(cause)
                if broken is not None:
                    raise ToolError(OUTPUT_CONTRACT_MESSAGE.format(fields=", ".join(broken[:6]))) from None
                if isinstance(cause, ValidationError):
                    errors = cause.errors(include_url=False, include_input=False, include_context=False)
                    parts = [".".join(str(part) for part in error.get("loc", ())) + " : " + str(error.get("msg", ""))[:80]
                             for error in errors[:6]]
                    raise ToolError("Argument invalide, rien n'a été envoyé : " + "; ".join(parts)) from None
                if isinstance(cause, BarehandsToolError):
                    # Même forme pour toutes les erreurs de ces outils : le
                    # message, sans le préfixe « Error executing tool … ».
                    raise ToolError(str(cause)) from None
                raise

    mcp = StrictBarehandsMCP(SERVER_NAME, instructions=_SERVER_INSTRUCTIONS)

    # Les trois parcours **existent** (Slices 08 et 09). Ce que ces notes
    # doivent dire n'est donc plus « ce n'est pas implanté » — ce serait faux,
    # et une consigne périmée fait refuser au cerveau un outil qui marche, ce
    # qui est indiscernable d'une panne — mais ce qu'une confirmation
    # **signifie**.
    #
    # Et elles sont **deux**, depuis la Slice 10. Une seule note collée aux
    # trois outils faisait dire à `barehands_exit_overlay` — dont le travail
    # est de **fermer** — « un succès veut dire que la surimpression est
    # ouverte […] dis que c'est ouvert ». L'utilisateur demandait « ferme la
    # surimpression », elle se fermait, et JARVIS répondait « c'est ouvert à
    # l'écran » devant un écran vide : le faux succès exact que ces outils
    # existent pour empêcher, à l'envers. Un outil qui ouvre et un outil qui
    # ferme ne peuvent pas partager la phrase qui dit ce qu'un succès affirme.
    _OPEN_FLOW_NOTE = (
        "Un succès veut dire que la surimpression est ouverte à l'écran, PAS que le parcours est "
        "terminé : il dure des minutes et c'est l'utilisateur qui le mène à la main. Ne dis donc "
        "jamais « c'est calibré » ; dis que c'est ouvert. Refus possibles, chacun avec la phrase "
        "de la page : barehands_calibration_lifecycle_off (Bare Hands éteint), "
        "barehands_calibration_disabled (calibration décochée dans les réglages), "
        "barehands_calibration_no_camera (caméra indisponible), barehands_flow_busy (le test est "
        "déjà à l'écran), barehands_flow_unconfirmed (le parcours n'a pas confirmé, sans cause "
        "connue), barehands_flow_absent (la page est plus ancienne que ce JARVIS et ne connaît pas "
        "ce parcours)."
    )
    # Le Tester (Slice 10 adaptative) : même contrat de confirmation, mais ce
    # qu'il ouvre est un **banc à lecture seule** — il ne change aucun réglage.
    _OPEN_TEST_NOTE = (
        "Un succès veut dire que l'écran d'accueil du test est ouvert : aucun run n'a commencé, "
        "c'est l'utilisateur qui clique « Commencer » et qui mène les exercices à la main (environ "
        "deux minutes). Le test ne change aucun réglage et n'enregistre qu'un résumé de résultat : "
        "ne dis donc jamais « c'est réglé » ni « c'est testé ». Un succès « Rien à faire » veut dire "
        "qu'il était déjà ouvert. Bare Hands éteint : le Control Center refuse avant la page, "
        "barehands_disabled — propose de l'allumer (settings_set(barehands.enabled, true) s'il "
        "accepte), puis rappelle cet outil. Refus de la page, chacun avec sa phrase : "
        "barehands_benchmark_lifecycle_off (Bare Hands vu éteint par la page alors que le serveur le "
        "croyait allumé — désaccord passager page/serveur), barehands_benchmark_no_camera "
        "(caméra indisponible), barehands_benchmark_unavailable (module du test absent de la page), "
        "barehands_flow_busy (la calibration est déjà à l'écran), barehands_flow_unconfirmed, "
        "barehands_flow_absent (page plus ancienne que ce JARVIS)."
    )
    # Celui qui ferme. Il **confirme toujours** — `exitOverlay()` rend
    # `{ok: true}` sans condition, délibérément : ce que l'appelant demande est
    # qu'il n'y ait pas de surimpression, et après lui il n'y en a pas, qu'il y
    # en ait eu une ou non. `barehands_flow_unconfirmed` ne peut donc pas
    # sortir d'ici, et le lister apprendrait au cerveau à se méfier d'un refus
    # qui n'arrive jamais.
    _EXIT_FLOW_NOTE = (
        "Un succès veut dire que la surimpression est fermée et que l'utilisateur a retrouvé son "
        "interface : dis que c'est fermé, jamais que c'est ouvert. Il réussit aussi quand rien "
        "n'était ouvert — le résultat demandé est le même — donc ne promets pas pour autant qu'un "
        "parcours a été interrompu. Il ne termine ni ne valide un parcours : une calibration fermée "
        "en cours de route n'a rien enregistré, et il faut la relancer pour le faire. "
        "Refus possible : barehands_flow_absent (la page est plus ancienne que ce JARVIS et ne "
        "connaît pas cette commande)."
    )

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "barehands_activate"))
    async def barehands_activate() -> BarehandsCommandResult:
        """Réveiller Bare Hands : la main pilote l'interface tout de suite, sans faire la posture en C.

        À appeler quand l'utilisateur demande d'activer les mains, la main, le pointeur à la main,
        ou de pouvoir cliquer sans souris. Refus : barehands_disabled (Bare Hands est éteint ;
        rallume-le avec settings_set(barehands.enabled, true), n'y renvoie pas l'utilisateur), barehands_no_visible_page (aucune fenêtre du Control Center visible),
        barehands_lifecycle_refused (la page n'a pas atteint l'état, caméra indisponible par exemple).
        """
        return await hands.send("barehands_activate", "activate")

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "barehands_deactivate"))
    async def barehands_deactivate() -> BarehandsCommandResult:
        """Remettre Bare Hands en veille : la main ne pilote plus, la caméra reste prête.

        À appeler quand l'utilisateur demande d'arrêter, de désactiver ou de mettre en pause les mains.
        C'est la **veille**, pas l'extinction : la caméra reste prête et la posture en C réveille.
        Si l'utilisateur veut éteindre Bare Hands pour de bon (« éteins complètement », « coupe la
        webcam »), ce n'est pas cet outil : appelle settings_set(barehands.enabled, false) du serveur
        jarvis-console, qui bascule le vrai interrupteur. Ne renvoie pas l'utilisateur au Control Center.
        """
        return await hands.send("barehands_deactivate", "deactivate")

    @mcp.tool(description=f"""Lancer la calibration de Bare Hands (mesure des seuils de la main de l'utilisateur).

{_OPEN_FLOW_NOTE}""", annotations=tool_annotations(SERVER_NAME, "barehands_calibrate"))
    async def barehands_calibrate() -> BarehandsCommandResult:
        return await hands.send("barehands_calibrate", "calibrate")

    # **Outil déprécié, gardé pour son nom** (Slice 07B, décisions 10 et 17).
    # Le parcours de tutoriel séparé a été retiré : il n'y a plus qu'un seul
    # parcours guidé, la calibration, et c'est elle qui enseigne les gestes.
    # L'outil reste exposé parce que `tutorial` est miroité sous assertion de
    # parité au chargement (fin de ce module) et que le retirer serait une
    # rupture coordonnée sur trois fichiers. Sa description **dit ce qu'il
    # fait**, pas ce que son nom promet : un cerveau qui lirait « lancer le
    # tutoriel » annoncerait un tutoriel à l'utilisateur, et l'utilisateur
    # verrait une calibration.
    @mcp.tool(description=f"""Déprécié : le tutoriel séparé n'existe plus, cet outil ouvre la CALIBRATION.

À n'appeler que si l'utilisateur demande explicitement « le tutoriel » ou « apprends-moi les gestes » :
c'est désormais la calibration qui enseigne. Préfère barehands_calibrate, qui est le vrai nom de ce
parcours. Après un succès, dis que la CALIBRATION est ouverte — jamais qu'un tutoriel l'est : la page
te renvoie dans sa note ce qui s'est réellement ouvert, et c'est cela que tu rapportes. Ses refus
portent des codes en barehands_calibration_* parce que c'est la calibration qui a refusé.

{_OPEN_FLOW_NOTE}""", annotations=tool_annotations(SERVER_NAME, "barehands_tutorial"))
    async def barehands_tutorial() -> BarehandsCommandResult:
        return await hands.send("barehands_tutorial", "tutorial")

    @mcp.tool(description=f"""Fermer le panneau de calibration ouvert et revenir à l'interface.

{_EXIT_FLOW_NOTE}""", annotations=tool_annotations(SERVER_NAME, "barehands_exit_overlay"))
    async def barehands_exit_overlay() -> BarehandsCommandResult:
        return await hands.send("barehands_exit_overlay", "exit_overlay")

    @mcp.tool(description=f"""Ouvrir le Tester de Bare Hands : un banc d'essai qui mesure la qualité de l'interaction à mains nues (sélection, clic, glisser-déposer, stabilité, faux clics), sans rien régler.

À appeler quand l'utilisateur demande de tester ses mains, de mesurer la qualité de Bare Hands, de comparer avant/après une calibration. Pour régler, c'est barehands_calibrate.

{_OPEN_TEST_NOTE}""", annotations=tool_annotations(SERVER_NAME, "barehands_test"))
    async def barehands_test() -> BarehandsCommandResult:
        return await hands.send("barehands_test", "test")

    # ------------------------------------------------------------ calibration (Slice 06 adaptative)
    #
    # Les vocabulaires viennent du miroir du contrat (`barehands_calibration`),
    # pour que le schéma **montre** au cerveau les mots permis. Les références
    # de séance (`ep-3`, `fb-1`, `hy-2`, `tr-1`) se lisent dans calibration_status.
    Number = Annotated[float, Strict()]
    Ref = Annotated[str, Field(pattern=r"^[a-z]{2}-[0-9]{1,9}$", description="Référence de séance, ex. ep-3.")]
    Category = Literal[FEEDBACK_CATEGORIES]  # type: ignore[valid-type]
    Cause = Literal[HYPOTHESIS_CAUSES]  # type: ignore[valid-type]
    Metric = Literal[CALIBRATION_METRICS]  # type: ignore[valid-type]
    Aggregate = Literal[METRIC_AGGREGATES]  # type: ignore[valid-type]
    Verdict = Literal[TRIAL_VERDICTS]  # type: ignore[valid-type]
    TrialKey = Literal[TRIAL_KEYS]  # type: ignore[valid-type]
    Stage = Literal[STAGES]  # type: ignore[valid-type]
    SkipReason = Literal[SKIP_REASONS]  # type: ignore[valid-type]

    @with_config(ConfigDict(extra="forbid"))
    class EvidenceArg(TypedDict):
        metric: Metric
        aggregate: Aggregate
        source_refs: Annotated[list[Ref], Field(min_length=1, max_length=SOURCE_REFS_MAX,
                                                description="Mesures citées (ep-N, ex-N, ng-N, se-N).")]

    @with_config(ConfigDict(extra="forbid"))
    class ComparisonArg(TypedDict):
        metric: Metric
        aggregate: Aggregate

    _SESSION_NOTE = ("Seulement pendant une séance de calibration ouverte à l'écran ; hors séance : "
                     "barehands_calibration_inactive.")

    @mcp.tool(description=f"""Lire la séance de calibration : exercice à l'écran, valeurs effectives / enregistrées / d'essai, mesures (par référence, chiffrées par la page), retours, preuves, hypothèses, essais, proposition en cours (proposal : pending = non appliquée, stale = périmée, committed = appliquée) et révision de séance.

C'est la seule source des nombres que tu peux citer. {_SESSION_NOTE}""",
              annotations=tool_annotations(SERVER_NAME, "calibration_status"))
    async def calibration_status() -> CalibrationStatusResult:
        return await hands.calibrate("calibration_status")

    @mcp.tool(description=f"""Noter ce que l'utilisateur dit de son ressenti, avec ses mots exacts et 1 à 3 catégories (fine et unclear seules).

Un retour n'est pas un réglage : il contraint l'interprétation des mesures. Rend les causes que ces catégories suggèrent (point de départ, pas conclusion). {_SESSION_NOTE}""",
              annotations=tool_annotations(SERVER_NAME, "calibration_record_feedback"))
    async def calibration_record_feedback(
        categories: Annotated[list[Category], Field(min_length=1, max_length=FEEDBACK_CATEGORIES_MAX)],
        text: Annotated[str, Field(min_length=1, max_length=FEEDBACK_TEXT_MAX,
                                   description="Ce que l'utilisateur a dit, mot pour mot.")],
    ) -> CalibrationFeedbackResult:
        return await hands.calibrate("calibration_record_feedback", {"categories": list(categories), "text": text})

    @mcp.tool(description=f"""Proposer une cause possible, à tester : cause, confiance initiale (0–1, modeste), preuves (métrique + résumé + mesures citées) et/ou retours cités.

La valeur de chaque preuve est calculée par le code à partir des références ; tu n'écris jamais un nombre. Une cause déjà démentie par un essai ne revient qu'avec une preuve ou un retour nouveau. {_SESSION_NOTE}""",
              annotations=tool_annotations(SERVER_NAME, "calibration_propose_hypothesis"))
    async def calibration_propose_hypothesis(
        cause: Cause,
        confidence: Annotated[Number, Field(ge=0, le=1)],
        evidence: Annotated[list[EvidenceArg], Field(max_length=EVIDENCE_MAX)] = [],  # noqa: B006
        feedback_refs: Annotated[list[Ref], Field(max_length=FEEDBACK_REFS_MAX)] = [],  # noqa: B006
    ) -> CalibrationHypothesisResult:
        return await hands.calibrate("calibration_propose_hypothesis", {
            "cause": cause, "confidence": confidence,
            "evidence": [{"metric": item["metric"], "aggregate": item["aggregate"],
                          "sourceRefs": list(item["source_refs"])} for item in evidence],
            "feedbackRefs": list(feedback_refs)})

    @mcp.tool(description=f"""PRÉPARER une proposition de réglage pour tester une hypothèse : elle s'affiche dans le panneau de calibration, NON appliquée. Rien ne change dans le moteur.

hypothesis_ref : l'hypothèse testée ; patch : 1 à {PATCH_KEYS_MAX} clés parmi celles de sa cause (trialKeys dans calibration_status) ; summary : en une phrase, en mots d'utilisateur, ce qu'elle change pour lui (« rendre le relâchement du pincement plus tolérant ») ; untouched : ce que tu ne touches pas et pourquoi (facultatif). Seulement sur la revue d'un exercice. Une nouvelle proposition remplace la précédente. Un essai à la fois : juge ou annule le précédent d'abord. Les invariants du moteur sont vérifiés tout de suite.

Ensuite tu ATTENDS : l'utilisateur valide dans le panneau (il peut corriger les valeurs), ou te le dit — alors calibration_commit_proposal.

Posture de réveil (étape c_pose) : depuis le 30/09/2026 l'étape ENREGISTRE la posture que l'utilisateur montre, et c'est elle qui réveille ensuite — il n'a plus à se conformer à un C imposé, et aucun seuil de repli ni d'écart n'est à régler pour qu'elle passe. Elle ne refuse que trois cas, chacun avec sa phrase : pouce presque au contact de l'index ou du majeur (ce serait un clic) ; posture que sa main au repos de l'étape 1 atteint déjà (réveils intempestifs) ; main qui bouge pendant la tenue. Dans ces cas, propose de refaire l'exercice avec une posture un peu plus marquée — ne propose pas d'élargir des seuils. Seule exception : un pincement refusé alors que l'utilisateur veut une posture très serrée : cause wake_too_strict, clé wakeGapMin avec releaseRatio sous elle (≈ wakeGapMin − 0,04), c_pose_gap_palms − 0,07 environ. {_SESSION_NOTE}""",
              annotations=tool_annotations(SERVER_NAME, "calibration_prepare_trial"))
    async def calibration_prepare_trial(
        hypothesis_ref: Ref,
        patch: Annotated[dict[TrialKey, Number], Field(min_length=1, max_length=PATCH_KEYS_MAX)],
        summary: Annotated[str, Field(min_length=2, max_length=PROPOSAL_TEXT_MAX,
                                      description="Ce que la proposition change pour l'utilisateur, en mots simples.")],
        untouched: Annotated[str | None, Field(max_length=PROPOSAL_TEXT_MAX,
                                               description="Ce que tu ne touches pas, et pourquoi.")] = None,
    ) -> CalibrationProposalResult:
        payload: dict[str, object] = {"hypothesisRef": hypothesis_ref, "patch": dict(patch), "summary": summary}
        if untouched:
            payload["untouched"] = untouched
        return await hands.calibrate("calibration_prepare_trial", payload)

    @mcp.tool(description=f"""VALIDER la proposition au nom de l'utilisateur — SEULEMENT quand il a dit lui-même vouloir l'appliquer (« oui, applique », « vas-y, on refait », « garde et continue »).

proposal_ref : la proposition (pr-N, dans calibration_status.proposal) ; action : rerun (appliquer, relire le moteur, refaire l'exercice) ou continue (appliquer, relire, garder sans refaire : l'étape est soldée « acceptée par l'utilisateur, non revérifiée ») ; user_quote : ses mots exacts. Le Control Center vérifie qu'il les a dits depuis la proposition (sinon barehands_calibration_consent_missing : rien n'est appliqué). Ce sont les valeurs AFFICHÉES qui s'appliquent, y compris celles que l'utilisateur a corrigées. Une proposition périmée (l'étape a changé) est refusée. Le runtime fait toute la transaction : n'appelle rien d'autre pour la compléter, annonce seulement ce que steps montre. {_SESSION_NOTE}""",
              annotations=tool_annotations(SERVER_NAME, "calibration_commit_proposal"))
    async def calibration_commit_proposal(
        proposal_ref: Annotated[str, Field(pattern=r"^pr-[0-9]{1,9}$", description="Proposition, ex. pr-2.")],
        action: Literal[COMMIT_ACTIONS],  # type: ignore[valid-type]
        user_quote: Annotated[str, Field(min_length=QUOTE_MIN, max_length=QUOTE_MAX,
                                         description="Mots de l'utilisateur, mot pour mot.")],
    ) -> CalibrationCommitResult:
        return await hands.calibrate("calibration_commit_proposal",
                                     {"proposalRef": proposal_ref, "action": action, "userQuote": user_quote})

    @mcp.tool(description=f"""Juger un essai : verdict (improved, no_change, worse, inconclusive), comparaisons (métrique + résumé), mesures d'avant (prises avant l'essai) et d'après (prises sous l'essai, après avoir refait l'exercice), retours dits depuis l'essai.

Le code calcule les deltas et refuse un verdict que les mesures ou les retours contredisent. La confiance de l'hypothèse testée monte ou baisse par une règle fixe ; un essai sans amélioration l'affaiblit. {_SESSION_NOTE}""",
              annotations=tool_annotations(SERVER_NAME, "calibration_resolve_trial"))
    async def calibration_resolve_trial(
        trial_ref: Ref,
        verdict: Verdict,
        comparisons: Annotated[list[ComparisonArg], Field(max_length=COMPARISONS_MAX)] = [],  # noqa: B006
        before_refs: Annotated[list[Ref], Field(max_length=OUTCOME_REFS_MAX)] = [],  # noqa: B006
        after_refs: Annotated[list[Ref], Field(max_length=OUTCOME_REFS_MAX)] = [],  # noqa: B006
        feedback_refs: Annotated[list[Ref], Field(max_length=FEEDBACK_REFS_MAX)] = [],  # noqa: B006
    ) -> CalibrationResolveResult:
        return await hands.calibrate("calibration_resolve_trial", {
            "trialRef": trial_ref, "verdict": verdict,
            "comparisons": [{"metric": item["metric"], "aggregate": item["aggregate"]} for item in comparisons],
            "beforeRefs": list(before_refs), "afterRefs": list(after_refs), "feedbackRefs": list(feedback_refs)})

    @mcp.tool(description=f"""Annuler le dernier essai : les valeurs d'avant reviennent et sont relues chez le moteur. {_SESSION_NOTE}""",
              annotations=tool_annotations(SERVER_NAME, "calibration_rollback_trial"))
    async def calibration_rollback_trial() -> CalibrationRollbackResult:
        return await hands.calibrate("calibration_rollback_trial")

    @mcp.tool(description=f"""Garder le réglage essayé : l'enregistre pour de bon. SEULEMENT quand l'utilisateur a dit lui-même vouloir le garder.

user_quote : ses mots exacts, recopiés de ce qu'il a dit depuis l'essai (« oui garde ça »). Le Control Center vérifie qu'il les a bien dits depuis l'essai et refuse sinon (barehands_calibration_consent_missing) : sans cet accord, propose, n'enregistre pas. {_SESSION_NOTE}""",
              annotations=tool_annotations(SERVER_NAME, "calibration_accept_trial"))
    async def calibration_accept_trial(
        user_quote: Annotated[str, Field(min_length=QUOTE_MIN, max_length=QUOTE_MAX,
                                         description="Mots de l'utilisateur, mot pour mot.")],
    ) -> CalibrationAcceptResult:
        return await hands.calibrate("calibration_accept_trial", {"userQuote": user_quote})

    @mcp.tool(description=f"""Refaire un exercice pour le mesurer sous le réglage actuel — c'est ce qui donne les mesures « après » d'un essai.

exercise : l'exercice à refaire (voir exercises de l'essai dans calibration_status / calibration_apply_trial). Absent : celui de l'essai non jugé en cours, sinon le dernier joué. Tant qu'un essai n'est pas jugé, le parcours s'arrête après le verdict de son exercice. {_SESSION_NOTE}""",
              annotations=tool_annotations(SERVER_NAME, "calibration_rerun_exercise"))
    async def calibration_rerun_exercise(exercise: Stage | None = None) -> CalibrationExerciseResult:
        return await hands.calibrate("calibration_rerun_exercise", {} if exercise is None else {"exercise": exercise})

    @mcp.tool(description=f"""Continuer la calibration : après la revue d'un exercice réussi, valide l'étape et passe à la suivante. Avec reason, l'exercice est **passé** (sa mesure n'est pas gardée), même réussi ; sans reason, une revue réussie est validée. Passer un exercice non terminé ou échoué exige reason, la raison que l'utilisateur a donnée : not_relevant (pas utile pour lui), cannot_perform (il n'arrive pas à faire le geste), tracking (la caméra le voit mal), later (plus tard) ; sans elle, refus barehands_calibration_skip_reason_required — demande-lui pourquoi. {_SESSION_NOTE}""",
              annotations=tool_annotations(SERVER_NAME, "calibration_next_exercise"))
    async def calibration_next_exercise(reason: SkipReason | None = None) -> CalibrationNextResult:
        return await hands.calibrate("calibration_next_exercise", {} if reason is None else {"reason": reason})

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
if tuple(TOOL_COMMANDS) + CALIBRATION_TOOLS != TOOL_NAMES or tuple(TOOL_COMMANDS.values()) != COMMANDS:
    raise RuntimeError("barehands_mcp : TOOL_COMMANDS + CALIBRATION_TOOLS ne couvrent pas TOOL_NAMES × COMMANDS")

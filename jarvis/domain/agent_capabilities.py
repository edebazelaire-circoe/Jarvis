"""Capacités des agents d'une édition produit : ce que le modèle peut appeler, et rien d'autre.

Contrat : `docs/product-capabilities.md` (Presentation Edition V1, Slice 04, décision D08).

Une seule table, indexée par l'édition (`ProductEdition`) comme `connector_policy` : elle ne
redit pas quels Boards existent, elle dit ce que le **cerveau et ses agents** reçoivent du CLI.

- `full` (développement) : `UNCONFINED`, rien n'est imposé ; les lancements sont ceux d'avant
  cette Slice, octet pour octet (réglages, `bypassPermissions`, `--chrome`, MCP personnels).
- `presentation` : `PRESENTATION_CAPABILITIES`, imposé au lancement par le CLI lui-même
  (`--restricted`, `--tools`, `--disallowedTools`, `--strict-mcp-config`, `dontAsk`), jamais par
  une consigne seule. Aucun outil natif d'écriture, de shell ou de processus ; les écritures
  passent par les serveurs MCP de JARVIS (mémoire de Board, sources de présentation, export).

Pur : aucune E/S. `jarvis.runtime.claude_local` traduit ce manifeste en `argv`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from jarvis.domain import routing
from jarvis.domain.product_edition import ProductEdition, ProductEditionPolicy

#: Mode de permission imposé à un agent confiné : refuse tout outil non listé dans `--allowedTools`,
#: sans demander à personne (`--permission-prompts none`). `--restricted` refuse de toute façon
#: `bypassPermissions` (CLI Claude Code 2.1.310, `claude --help`).
CONFINED_PERMISSION_MODE = "dontAsk"

#: Outils intégrés offerts à un agent confiné (`--tools`, la liste **exhaustive** de ce qui existe).
#: Lecture bornée aux dossiers de travail par `--restricted`, recherche web, délégation à des
#: sous-agents qui héritent de ce même ensemble (sonde du 2026-10-26, CLI 2.1.310 : un sous-agent
#: `general-purpose` ne voit que ces outils), chargement des outils MCP différés.
CONFINED_NATIVE_TOOLS = ("Read", "Glob", "Grep", "WebSearch", "WebFetch", "Agent", "ToolSearch", "TaskStop", "SendMessage")

#: Outils intégrés qui écrivent, exécutent du code, lancent un processus ou programment une action.
#: Absents de `--tools`, donc inexistants ; nommés **aussi** dans `--disallowedTools` (règle de refus
#: de la session, qui vaut pour chaque sous-agent) : défense en profondeur si une version future du
#: CLI ajoutait un outil par défaut. Un nom inconnu d'une version est ignoré par le CLI (constaté).
FORBIDDEN_NATIVE_TOOLS = (
    "Bash", "PowerShell", "REPL", "Write", "Edit", "MultiEdit", "NotebookEdit", "Monitor", "KillShell",
    "CronCreate", "CronDelete", "ScheduleWakeup", "RemoteTrigger", "Workflow", "EnterWorktree", "ExitWorktree",
    "Skill", "DesignSync", "PushNotification",
)

#: Outils intégrés qui écrivent un fichier : sans l'un d'eux, un agent n'écrit que par les outils JARVIS
#: (`board_memory_write`, `presentation_*`), et la capacité de routage `code` n'existe pas.
NATIVE_WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")

#: Ce qu'il faut au manifeste pour offrir chaque capacité de routage (`routing.CAPABILITIES`) qu'exige un profil de
#: tâche (`routing.TASK_PROFILES`) : `code` écrit des fichiers, `computer_use` pilote le navigateur (`--chrome`).
#: Une capacité absente de cette table ne dépend pas des outils de l'agent.
_CAPABILITY_NEEDS = {
    routing.CODE: lambda policy: any(tool in policy.native_tools for tool in NATIVE_WRITE_TOOLS),
    routing.COMPUTER_USE: lambda policy: policy.chrome,
}


class AgentCapabilityError(RuntimeError):
    """Un chemin d'agent refusé par l'édition (`code` stable, message lisible)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AgentCapabilityPolicy:
    """Manifeste de capacités des agents d'une édition."""

    edition: ProductEdition
    #: Vrai : le lancement est confiné (tout ce qui suit est imposé). Faux : comportement d'avant.
    confined: bool
    native_tools: tuple[str, ...] = ()
    forbidden_native_tools: tuple[str, ...] = ()
    permission_mode: str | None = None
    #: `--chrome` (Claude in Chrome) permis.
    chrome: bool = True
    #: CLIs d'agent permis (`cli_catalog.AGENT_CLI_IDS`). Codex n'a pas de confinement équivalent réel.
    agent_clis: tuple[str, ...] = ("claude", "codex")
    debug_console: bool = True
    self_development: bool = True
    #: Dossier de travail du CLI, relatif à la racine runtime ; `None` : celui de l'appelant (le code).
    workdir: str | None = None

    def allows_agent_cli(self, agent_id: str) -> bool:
        return str(agent_id or "").strip().lower() in self.agent_clis

    def ensure_agent_cli(self, agent_id: str) -> str:
        if not self.allows_agent_cli(agent_id):
            raise AgentCapabilityError(
                "agent_cli_unavailable_in_edition",
                f"Le CLI « {agent_id} » n'est pas disponible dans l'édition {self.edition.value} : "
                f"son confinement n'est pas garanti. CLI permis : {', '.join(self.agent_clis)}.")
        return str(agent_id).strip().lower()

    def ensure(self, capability: str) -> None:
        """`debug_console` ou `self_development` : refus typé quand l'édition les ferme."""

        if not getattr(self, capability):
            raise AgentCapabilityError(
                f"{capability}_unavailable_in_edition",
                f"{_LABELS[capability]} n'est pas disponible dans l'édition {self.edition.value}.")

    @property
    def writes_files(self) -> bool:
        """Vrai : l'agent a un outil intégré qui écrit un fichier. Faux en confiné : il écrit par les outils JARVIS."""

        return not self.confined or any(tool in self.native_tools for tool in NATIVE_WRITE_TOOLS)

    def offers_task_profile(self, profile: str) -> bool:
        """Le profil de tâche (`[code]`, `[desktop]`, …) a-t-il un sens ici ? Dérivé de ses capacités exigées.

        Non confiné : tous. Confiné : un profil dont une capacité exigée manque au manifeste n'est ni proposé au
        cerveau ni cité dans une consigne (`docs/product-capabilities.md`, « Consignes dérivées »).
        """

        if not self.confined:
            return True
        spec = routing.profile_spec(profile)
        return all(_CAPABILITY_NEEDS.get(need, lambda _policy: True)(self) for need in spec.requires)

    @property
    def offered_task_profiles(self) -> tuple[str, ...]:
        return tuple(profile for profile in routing.TASK_PROFILE_IDS if self.offers_task_profile(profile))

    def allowed_rules(self, mcp_servers: Iterable[str]) -> tuple[str, ...]:
        """`--allowedTools` : les outils intégrés offerts, puis chaque serveur MCP de JARVIS déclaré au lancement."""

        servers = tuple(dict.fromkeys(str(name) for name in mcp_servers if str(name).startswith("jarvis-")))
        return (*self.native_tools, *(f"mcp__{name}" for name in servers))

    def cli_args(self, mcp_servers: Iterable[str], *, extra_denied: Iterable[str] = ()) -> list[str]:
        """Les drapeaux du CLI Claude qui rendent ce manifeste réel. Vide hors confinement."""

        if not self.confined:
            return []
        denied = tuple(dict.fromkeys((*self.forbidden_native_tools, *extra_denied)))
        return ["--restricted", "--strict-mcp-config", "--disable-slash-commands", "--permission-prompts", "none",
                "--tools", ",".join(self.native_tools),
                "--allowedTools", ",".join(self.allowed_rules(mcp_servers)),
                "--disallowedTools", ",".join(denied)]

    def subagent_note(self) -> str | None:
        """Bloc apposé par le hook d'aiguillage sur la consigne de chaque sous-agent confiné, ou `None`.

        Un sous-agent ne voit pas la consigne du cerveau : sans ce bloc, la charte (« lis le code, l'historique
        git ») et une méthode éditée par l'utilisateur pourraient lui faire chercher un outil qui n'existe pas.
        """

        if self.writes_files:
            return None
        return (f"{SUBAGENT_CONFINED_MARK}\n"
                "Cette édition de JARVIS ne vous donne ni terminal, ni outil qui écrit, modifie ou supprime un fichier, "
                f"ni navigateur piloté. Outils intégrés : {', '.join(self.native_tools)} ; la lecture se limite aux "
                "dossiers de JARVIS. Vous écrivez uniquement par les outils JARVIS : board_memory_write pour la mémoire "
                "du Board (dossier de mission compris), les outils presentation_* pour une présentation. Ce que votre "
                "consigne dit du code, des tests, de git ou d'un fichier à modifier ne se fait que par ces outils ; "
                "sinon, dites dans votre compte rendu ce qui manque, sans chercher d'autre moyen.")

    def to_payload(self) -> dict[str, object]:
        """Ce que l'interface affiche (réglages verrouillés) et ce que les diagnostics citent."""

        return {"edition": self.edition.value, "confined": self.confined,
                "native_tools": list(self.native_tools), "forbidden_native_tools": list(self.forbidden_native_tools),
                "permission_mode": self.permission_mode, "permission_mode_locked": self.permission_mode is not None,
                "chrome": self.chrome, "agent_clis": list(self.agent_clis), "debug_console": self.debug_console,
                "self_development": self.self_development}


#: Tête du bloc `subagent_note` : présent dans une consigne, il n'est pas doublé.
SUBAGENT_CONFINED_MARK = "CAPACITÉS DE CETTE ÉDITION (SOUS-AGENT)"

_LABELS = {"debug_console": "La console de debug du CLI", "self_development": "L'auto-développement"}

UNCONFINED = AgentCapabilityPolicy(ProductEdition.FULL, confined=False)

PRESENTATION_CAPABILITIES = AgentCapabilityPolicy(
    ProductEdition.PRESENTATION, confined=True,
    native_tools=CONFINED_NATIVE_TOOLS, forbidden_native_tools=FORBIDDEN_NATIVE_TOOLS,
    permission_mode=CONFINED_PERMISSION_MODE, chrome=False, agent_clis=("claude",),
    debug_console=False, self_development=False, workdir="agent-workdir")

AGENT_CAPABILITY_POLICIES: Mapping[ProductEdition, AgentCapabilityPolicy] = MappingProxyType({
    ProductEdition.FULL: UNCONFINED,
    ProductEdition.PRESENTATION: PRESENTATION_CAPABILITIES,
})


def agent_capability_policy(edition: ProductEditionPolicy | ProductEdition | str) -> AgentCapabilityPolicy:
    key = edition.edition if isinstance(edition, ProductEditionPolicy) else ProductEdition(edition)
    return AGENT_CAPABILITY_POLICIES[key]

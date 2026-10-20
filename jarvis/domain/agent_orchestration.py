"""Orchestration organique des sous-agents : ce que le hook décide d'un appel `Agent` (Slice 05).

Handoff jarvis-organic-agent-orchestration. JARVIS ne lance aucun agent : c'est
l'outil `Agent` du CLI Claude qui le fait, depuis le cerveau ou depuis un
sous-agent (audit de readiness §8). Le seul point contraignant est le hook
`PreToolUse` (`jarvis/runtime/routing_hook.py`). Ce module pur dit ce que ce
hook décide, à partir des marqueurs de tête (`agent_markers`) et du registre
des rôles (`subagent_roles`) :

- **mission** (`decide_mission`) : un agent ouvre et possède une mission quand
  son rôle peut en porter une (`can_own_mission`) et que l'appel vient du
  cerveau (mission racine, l'objectif est le libellé de la tâche) ou porte
  `[mission]` (sous-mission de la mission de l'appelant, que Core résout par
  l'instance parente). Un agent éphémère n'en porte jamais ; un autre agent est
  membre de la mission de son appelant (Core l'en hérite). Rien n'est ouvert
  pour un agent qui n'est pas réellement lancé : le hook ne fait qu'écrire un
  fait, joint plus tard à la tâche suivie ;
- **méthode** (`decide_method`) : une Work Method nommée en tête remplace celle
  par défaut si le rôle la permet ; sinon le défaut s'applique, refus consigné ;
- **garde de lancement** (`decide_spawn_guard`) : un rôle qui ne lance pas
  d'agents (`can_spawn=False`) part sous le type d'agent restreint
  `NO_SPAWN_AGENT_TYPE`, déclaré au CLI sans l'outil `Agent` (sonde du
  2026-10-20, CLI 2.1.304 : la réécriture de `subagent_type` par le hook est
  honorée et le type restreint n'a pas `Agent`). Défense en profondeur : un
  appel `Agent` émis depuis ce type (`agent_type` de l'événement) est refusé ;
- **bornes de sûreté** : `MAX_SPAWNS_PER_WINDOW` lancements par
  `SPAWN_WINDOW_S` secondes, tous cerveaux confondus. C'est une borne de
  ressources, pas une politique de complexité minimale : la profondeur (3
  niveaux sous le cerveau, `NATIVE_MAX_SPAWN_DEPTH`), la concurrence et le
  budget sont bornés par le CLI lui-même (`subagent_stats.refused`) ;
- **consigne** (`mission_brief`) : ce que le hook appose sur la consigne d'un
  Mission Owner — l'appropriation du résultat et de sa qualité, et les outils
  qu'il peut utiliser quand ils servent, jamais une séquence imposée.

Contrat : `docs/agent-orchestration.md`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

from jarvis.domain import delivery_quality
from jarvis.domain.agent_markers import HeadMarkers
from jarvis.domain.subagent_roles import ROLES, SPAWN_TOOL, SubagentRole

#: Type d'agent restreint déclaré au CLI (`--agents`) : mêmes outils que `general-purpose`, sans `Agent`/`Task`.
NO_SPAWN_AGENT_TYPE = "jarvis-no-spawn"
#: Types que le hook peut remplacer par le type restreint. Un autre type (`Explore`, un type de l'utilisateur) est
#: laissé tel quel : le remplacer changerait ses outils et sa consigne ; la garde est alors consignée non appliquée.
#: `claude` (CLI 2.1.304) est le type fourre-tout, mêmes outils (`*`) que `general-purpose` : le remplacer par le
#: type restreint ne lui retire que `Agent`/`Task` (reprise QA). `fork` hérite du contexte de l'appelant : il n'est
#: pas équivalent et reste non garanti.
REWRITABLE_AGENT_TYPES = frozenset({"", "general-purpose", "claude"})
#: Outils retirés au type restreint : ceux qui lancent un sous-agent (`routing_hook.AGENT_TOOLS`).
SPAWN_TOOLS = (SPAWN_TOOL, "Task")
#: Activation de la garde (reprise QA M1) : variable d'environnement posée par `claude_local` sur le processus du
#: CLI, héritée par chaque hook (constaté sur le CLI 2.1.304, appel du cerveau et appel imbriqué). Jamais un drapeau
#: de ligne de commande : un hook d'une version antérieure (argparse strict) sortirait en 2 et le CLI refuserait
#: tout appel `Agent`. La valeur nomme le type et la version du contrat ; toute autre valeur laisse la garde éteinte.
SPAWN_GUARD_ENV = "JARVIS_SPAWN_GUARD"
SPAWN_GUARD_CONTRACT = 1
SPAWN_GUARD_VALUE = f"{NO_SPAWN_AGENT_TYPE}@{SPAWN_GUARD_CONTRACT}"


def spawn_guard_enabled(environ: Mapping[str, str]) -> bool:
    """Vrai si le CLI qui a lancé ce hook déclare le type restreint, dans cette version exacte du contrat."""

    return environ.get(SPAWN_GUARD_ENV) == SPAWN_GUARD_VALUE


#: Préfixe de l'id d'une mission ouverte par le hook : dérivé du `tool_use_id`, donc stable au rejeu.
MISSION_ID_PREFIX = "mis_"
#: Profondeur maximale de sous-agents sous le cerveau, imposée par le CLI (sonde du 2026-10-20, CLI 2.1.304 :
#: `spawn_depth` 3 atteint, l'agent de niveau 3 n'a plus l'outil `Agent`). Constat, pas réglage.
NATIVE_MAX_SPAWN_DEPTH = 3
#: Borne de sûreté des lancements, tous cerveaux du poste confondus.
SPAWN_WINDOW_S = 600
MAX_SPAWNS_PER_WINDOW = 120
#: Repli de l'objectif d'une mission dont la tâche n'a pas de libellé.
FALLBACK_OBJECTIVE = "Mission sans libellé"

#: Tête du bloc apposé sur la consigne d'un Mission Owner. Sert aussi à ne jamais le doubler.
MISSION_MARK = "RESPONSABILITÉ DE MISSION (JARVIS)"


def mission_id_for(tool_use_id: str) -> str:
    """L'id de la mission qu'ouvre l'appel `tool_use_id` : déterministe, donc identique à chaque rejeu."""

    return f"{MISSION_ID_PREFIX}{tool_use_id}"


@dataclass(frozen=True, slots=True)
class MissionDecision:
    """Ce que le hook déclare de la mission d'un agent lancé.

    - `mission_owner` / `mission_id` : l'agent ouvre et possède cette mission ;
    - `sub_mission` : vrai pour `[mission]` (la mission parente est celle de l'appelant, résolue par Core) ;
    - `handoff` : vrai pour `[relais]` (Slice 06) : l'agent reprend la mission de son appelant par le relais que
      celui-ci a préparé ; `mission_id` est alors celui du relais préparé, posé par le hook (`None` ici) ;
    - `refused` : code d'un `[mission]` qui n'a pas pu être honoré (`ephemeral_mission_owner`,
      `role_cannot_own_mission`), consigné par le hook ; l'agent part quand même, comme membre.
    """

    mission_owner: bool = False
    mission_id: str | None = None
    sub_mission: bool = False
    refused: str | None = None
    handoff: bool = False


def decide_mission(head: HeadMarkers, role: SubagentRole | None, *, tool_use_id: str | None,
                   nested: bool) -> MissionDecision:
    """La mission d'un agent lancé (voir le docstring du module). Ne lève jamais."""

    if head.ephemeral:
        return MissionDecision(refused="ephemeral_mission_owner" if head.mission or head.handoff else None)
    capable = role is not None and role.can_own_mission
    if (head.mission or head.handoff) and not capable:
        return MissionDecision(refused="role_cannot_own_mission")
    refused = None
    if head.handoff:
        # Slice 06 : un relais vient d'un Mission Owner qui passe la main, jamais du cerveau ; il n'ouvre rien.
        # Mal placé (`[mission]` en plus, ou appel du cerveau), il est ignoré et consigné : la règle d'avant joue.
        if head.mission:
            refused = "handoff_with_mission"
        elif not nested:
            refused = "handoff_from_brain"
        elif tool_use_id is not None:
            return MissionDecision(mission_owner=True, handoff=True)
    if not capable or tool_use_id is None or (nested and not head.mission):
        return MissionDecision(refused=refused)
    return MissionDecision(mission_owner=True, mission_id=mission_id_for(tool_use_id), sub_mission=nested,
                           refused=refused)


@dataclass(frozen=True, slots=True)
class MethodDecision:
    """La Work Method apposée : celle nommée en tête si le rôle la permet, sinon celle par défaut (`None` : aucune)."""

    method_id: str | None
    chosen: bool = False
    refused: str | None = None


def decide_method(head: HeadMarkers, role: SubagentRole | None) -> MethodDecision:
    if role is None:
        return MethodDecision(None, refused="method_without_role" if head.method else None)
    if head.method is None:
        return MethodDecision(role.default_work_method)
    if head.method in role.work_methods:
        return MethodDecision(head.method, chosen=True)
    return MethodDecision(role.default_work_method, refused="method_not_allowed")


@dataclass(frozen=True, slots=True)
class SpawnGuard:
    """Décision de la garde de lancement.

    - `deny` : l'appel est refusé (`reason` lisible, `code` stable) ;
    - `rewrite_agent_type` : le type d'agent à imposer (`NO_SPAWN_AGENT_TYPE`), ou `None` ;
    - `code` : aussi pour une garde non appliquée (`can_spawn_not_enforced`), consignée sans rien changer.
    """

    deny: bool = False
    rewrite_agent_type: str | None = None
    code: str | None = None
    reason: str = ""


def decide_spawn_guard(event: Mapping[str, Any], role: SubagentRole | None, *, enforce: bool,
                       recent_spawns: int | None = None, window_free_in_s: int | None = None) -> SpawnGuard:
    """La garde d'un appel `Agent`. `enforce` : le type restreint est déclaré au CLI qui a lancé ce hook.

    Ordre : l'appelant restreint (refus), la borne de sûreté (refus), puis le rôle lancé (type restreint).
    Sans `enforce`, rien n'est réécrit ni refusé pour le rôle : un CLI lancé sans le type restreint
    échouerait sur un type inconnu. `window_free_in_s` : dans combien de secondes la fenêtre de la borne libère
    une place (`agent_declarations.recent_window`), dit dans la raison du refus.

    Garanti : un rôle `can_spawn=False` lancé en `general-purpose` (toute casse) ou sans type part sous
    `NO_SPAWN_AGENT_TYPE`, et un appel émis depuis ce type est refusé. Non garanti (consigné
    `can_spawn_not_enforced`) : tout autre type demandé (`Explore`, `Plan`, `claude`, `fork`, types de
    l'utilisateur), qui garde ses propres outils. `claude` est remplacé comme `general-purpose`.
    """

    if enforce and str(event.get("agent_type") or "") == NO_SPAWN_AGENT_TYPE:
        return SpawnGuard(deny=True, code="caller_cannot_spawn",
                          reason="Ce rôle ne lance aucun autre agent (registre des rôles de JARVIS).")
    if recent_spawns is not None and recent_spawns >= MAX_SPAWNS_PER_WINDOW:
        return SpawnGuard(
            deny=True, code="spawn_rate_cap",
            reason=(f"Borne de sûreté de JARVIS : {recent_spawns} sous-agents lancés en {SPAWN_WINDOW_S // 60} min "
                    f"(au plus {MAX_SPAWNS_PER_WINDOW}). La fenêtre libère une place dans "
                    f"{max(1, window_free_in_s or SPAWN_WINDOW_S)} s : relancez après ce délai."),
        )
    if role is None or role.can_spawn or not enforce:
        return SpawnGuard()
    tool_input = event.get("tool_input")
    agent_type = str((tool_input if isinstance(tool_input, Mapping) else {}).get("subagent_type") or "")
    if agent_type.strip().casefold() not in REWRITABLE_AGENT_TYPES:
        return SpawnGuard(code="can_spawn_not_enforced")
    return SpawnGuard(rewrite_agent_type=NO_SPAWN_AGENT_TYPE, code="can_spawn_enforced")


def no_spawn_agent_definition() -> dict[str, Any]:
    """La définition du type restreint, passée au CLI par `--agents` (JSON)."""

    return {
        NO_SPAWN_AGENT_TYPE: {
            "description": ("Réservé à JARVIS : appliqué d'office aux sous-agents dont le rôle ne lance aucun autre "
                            "agent. Ne le choisissez pas vous-même."),
            "prompt": ("Vous êtes un sous-agent de JARVIS. Exécutez la consigne reçue avec les outils disponibles, "
                       "du début à la fin, puis rendez un compte rendu fidèle de ce que vous avez constaté et fait. "
                       "Vous ne lancez aucun autre agent."),
            "disallowedTools": list(SPAWN_TOOLS),
        }
    }


def agents_argument() -> str:
    """La valeur de `--agents` : le type restreint seul, en JSON compact."""

    return json.dumps(no_spawn_agent_definition(), ensure_ascii=False, separators=(",", ":"))


def _owner_markers(roles: Sequence[SubagentRole]) -> str:
    owners = [role for role in roles if role.enabled and role.can_own_mission and role.offered_to_subagents]
    return ", ".join(f"[{role.default_profile}] [{role.marker}]" for role in owners)


def mission_brief(decision: MissionDecision, roles: Sequence[SubagentRole] = ROLES) -> str | None:
    """Le bloc apposé sur la consigne d'un Mission Owner, ou `None` pour tout autre agent.

    Il enseigne quand les outils peuvent servir, jamais un ordre ni un nombre d'agents (D05) ; il rappelle que
    seul ce qui est réellement lancé laisse une trace (D15). La restitution (Slice 11, `delivery_quality`) vient
    en tête, juste après la portée : en fin de consigne elle pesait moins que les consignes de compte rendu.
    """

    if not decision.mission_owner:
        return None
    scope = ("Votre prédécesseur vous passe sa mission par un relais : vous l'organisez vous-même et lui en rendez "
             "le résultat." if decision.handoff else
             "Votre appelant vous confie une sous-mission : vous l'organisez vous-même et lui en rendez le résultat."
             if decision.sub_mission else
             "Le cerveau de JARVIS vous confie cette mission : vous l'organisez vous-même et lui en rendez le résultat.")
    return "\n".join((
        MISSION_MARK,
        scope,
        # Slice 11 : la restitution (règle de jugement, affichage, repli), paragraphe distinct de `delivery_quality`.
        "",
        delivery_quality.delivery_brief(),
        "",
        "Le résultat et sa qualité vous appartiennent. Personne n'a prévu d'équipe pour vous, et il n'en faut pas "
        "forcément une : une tâche nette se fait seul. Organisez-vous au fil de ce que vous découvrez.",
        "- Déléguez un morceau borné (outil Agent, description « [profil] [rôle] … ») quand il couvre du terrain "
        "que vous ne couvririez pas aussi bien seul.",
        "- Confiez une sous-mission qu'un autre organisera lui-même en ajoutant [mission] après son rôle (rôles qui "
        f"peuvent porter une mission : {_owner_markers(roles)}).",
        "- Choisissez la méthode d'un agent en ajoutant son id après le rôle, par exemple « [general] [research] "
        "[quick-research] … » ; sinon il suit la méthode de son rôle.",
        "- Gardez la main sur ce que vous lancez : SendMessage pour réorienter un agent, TaskStop pour arrêter un "
        "agent lancé en fond, et relisez chaque compte rendu avant de vous en servir.",
        "- Avant de rendre, jugez si la preuve suffit à l'enjeu. Sinon cherchez encore, demandez un second regard "
        "([code] [qa] …) ou comparez des approches : ne vous arrêtez pas à la première réponse plausible.",
        "- Rendez le résultat sous une forme lisible pour son usage ; une réponse simple reste simple.",
        "JARVIS retient les agents que vous lancez réellement, rien de ce que vous ne faites qu'envisager.",
    ))

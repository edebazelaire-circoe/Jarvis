"""Le point où la politique cesse d'être une intention et devient une contrainte.

JARVIS ne lance pas les sous-agents : c'est le CLI Claude qui le fait, avec son
outil `Agent`, en choisissant lui-même le `model`. Un prompt système peut le
prier ; il ne peut pas l'obliger. Le seul endroit où un choix de modèle peut
être *refusé ou corrigé* est le hook `PreToolUse` du CLI, qui voit l'appel
avant qu'il parte et peut en réécrire les arguments.

C'est donc ici que vit la règle « les réglages l'emportent sur le modèle
nommé par un LLM ». Le hook est un processus court, lancé à chaque appel
d'outil : il ne fait aucun appel réseau. Il lit les réglages, le dernier
catalogue connu et le PATH — trois lectures de disque — puis tranche.

Conduite en cas de doute :

- politique éteinte, profil sans candidat : le hook ne dit rien, le CLI garde
  la main. Le comportement d'avant est intact ;
- modèle hors politique : il est *réécrit*, pas refusé. Refuser ferait perdre
  le travail ; corriger le fait aboutir sur un modèle autorisé ;
- aucun candidat utilisable : là seulement, refus explicite et lisible ;
- panne du hook lui-même : il se tait. Une politique cassée ne doit pas
  paralyser le cerveau.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Mapping, Sequence

from jarvis.domain import (
    agent_markers, agent_orchestration, delivery_quality, model_family, relation_runtime, role_routing, routing,
)
from jarvis.domain.agent_capabilities import SUBAGENT_CONFINED_MARK, AgentCapabilityPolicy
from jarvis.domain.agent_charter import sign_brief
from jarvis.domain.brain_config import DelegationTendency
from jarvis.domain.loadout_view import MANIFEST_MARK
from jarvis.domain.agent_relations import QA_REVIEWER_ROLE_IDS
from jarvis.domain.mission_history import MissionHistoryError, fact_from_hook_event
from jarvis.domain.work_methods import WorkMethod, builtin_method
from jarvis.domain.subagent_roles import (
    ROLE_MARK, ROLE_UNAVAILABLE_CODE, SubagentRole, adapt_instructions, edition_role_refusal, effective_method,
    instructions_for, resolve_role, reuses_research, role_for, with_role_instructions,
)
# `ANNOUNCED_ROLES` : les rôles qu'une description peut annoncer (loadout, registre, alias), réexporté ici.
from jarvis.domain.agent_markers import ANNOUNCED_ROLES, WORD_PATTERN  # noqa: F401
from jarvis.domain.routing import (
    CandidateRef,
    ModelCandidate,
    NoEligibleCandidateError,
    RoutingDecision,
    RoutingError,
    RoutingIntent,
    RoutingPolicy,
)
from jarvis.runtime import (
    agent_declarations, agent_handoffs, brain_config_store, hook_failsafe, agent_routing, cli_catalog, credentials,
    loadout_snapshot,
    subagent_role_routing, subagent_roles_snapshot, work_methods_snapshot,
)
from jarvis.runtime.catalog_view import ProviderCatalogSnapshot
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.model_catalog import ModelCatalog, filter_by_role
from jarvis.runtime.presentation_playbooks import PLAYBOOK_ROLES, with_playbook

#: Outils du CLI qui lancent un sous-agent. Mêmes noms que ceux que le suivi
#: des tâches reconnaît (`agent_tasks.AGENT_TOOLS`).
AGENT_TOOLS = ("Agent", "Task")
#: Slice 06 : les outils de relation (`relation_runtime.RELATION_TOOLS`) passent aussi par le hook, qui y appose
#: l'identité de l'appelant. Le matcher du CLI est une expression régulière : il est **ancré** (reprise QA N3),
#: sinon `TaskStop`, `TaskOutput` contiendraient `Task` et lanceraient le hook (constaté sur le CLI 2.1.304 :
#: avec ce motif, `Glob` ne le lance pas, `Agent` et un outil MCP préfixé si).
RELATION_TOOLS_MATCHER = "^" + relation_runtime.RELATION_TOOL_PREFIX
HOOK_MATCHER = f"^({'|'.join(AGENT_TOOLS)})$|{RELATION_TOOLS_MATCHER}"

#: Le CLI qui exécute réellement les sous-agents. L'outil `Agent` tourne dans
#: le processus Claude : aucune politique ne peut en faire sortir un sous-agent.
HOST_AGENT = "claude"

#: Comment le cerveau annonce le profil : le premier mot entre crochets de la
#: description. Inventé ici plutôt que déduit du texte — deviner l'intention
#: d'une phrase serait exactement le genre de choix qu'on refuse au modèle.
#: La grammaire complète des marqueurs de tête (profil, rôle, `[éphémère]`) vit
#: dans `jarvis/domain/agent_markers.py`, partagée avec le suivi des tâches
#: (I-005) ; ces motifs n'en sont que les briques, gardées pour compatibilité.
PROFILE_PATTERN = re.compile(r"^\s*\[\s*(" + WORD_PATTERN + r")\s*\]\s*")
_BRACKET = re.compile(r"\[\s*(" + WORD_PATTERN + r")\s*\]\s*")

#: Ce que dit la règle des profils de chacun, dans l'ordre où elle les cite.
_PROFILE_USES = (
    ("code", "[code] pour écrire ou corriger du code"),
    ("desktop", "[desktop] pour piloter le navigateur ou des fichiers ouverts"),
    ("fast", "[fast] pour résumer, classer ou reformuler"),
)


def profile_rule(capabilities: AgentCapabilityPolicy | None = None) -> str:
    """La règle des profils du prompt du cerveau. `None` ou édition non confinée : `PROFILE_RULE`, octet pour octet.

    Édition confinée (`docs/product-capabilities.md`) : seuls les profils offerts par le manifeste
    (`AgentCapabilityPolicy.offers_task_profile`) sont cités ; `[code]` et `[desktop]` disparaissent sans outil
    d'écriture ni navigateur piloté.
    """
    offered = [use for profile, use in _PROFILE_USES if capabilities is None or capabilities.offers_task_profile(profile)]
    qa_profile = "code" if capabilities is None or capabilities.offers_task_profile("code") else "general"
    return (
        "Commence la description de chaque sous-agent par son profil entre crochets : "
        f"{', '.join(offered)}, [general] "
        "sinon. JARVIS choisit le modèle à partir de ce profil et de tes réglages. "
        f"Pour une relecture, ajoute [qa] après le profil ([{qa_profile}] [qa] ...) ; "
        "pour une recherche documentaire, [research] ([general] [research] ...) : "
        "JARVIS donne alors au sous-agent les savoirs de ce rôle."
    )


PROFILE_RULE = profile_rule()


def read_profile(tool_input: Mapping[str, Any]) -> str:
    """Le profil annoncé, ou « general ». Un profil inconnu n'en est pas un (`agent_markers`)."""
    return agent_markers.read_profile(tool_input)


def announced_profile(tool_input: Mapping[str, Any]) -> str | None:
    """Le profil réellement écrit en tête (`description`, sinon `prompt`), ou `None` s'il n'y en a pas.

    À la différence de `read_profile`, l'absence n'est pas « general » : un rôle annoncé seul
    (`[coder] ...`) prend alors le `default_profile` de son contrat (couche par rôle, C9).
    """
    for key in ("description", "prompt"):
        profile = agent_markers.parse_head(str(tool_input.get(key) or "")).profile
        if profile is not None:
            return profile
    return None


def _markers(text: str) -> tuple[int, str | None]:
    """Fin des marqueurs de tête consommés et rôle annoncé, selon `agent_markers.parse_head`.

    Un premier mot entre crochets est toujours consommé, profil connu ou non ; un second ne l'est que s'il
    nomme un rôle (ou un rôle de production, sans rôle de loadout). `[éphémère]` est transparent.
    """
    head = agent_markers.parse_head(text, extra_consumed=PLAYBOOK_ROLES)
    return head.head_end, head.role


def read_role(tool_input: Mapping[str, Any]) -> str | None:
    """Le rôle annoncé après le profil (ou seul), ou `None`. Un rôle inconnu n'en est pas un."""
    return agent_markers.read_role(tool_input)


def read_loadout_role(tool_input: Mapping[str, Any]) -> str | None:
    """Le rôle annoncé s'il a un loadout (`coder`, `reviewer`, `research`), sinon `None`.

    Un rôle du registre sans loadout (`interviewer`, `web-research`, `concept`) garde le loadout de son
    profil : une clé `general:interviewer` n'existe pas et ferait perdre celui de `general`.
    """
    return agent_markers.read_loadout_role(tool_input)


def read_playbook_role(tool_input: Mapping[str, Any]) -> str | None:
    """Le rôle de production (`presentation-brief`, `-author`, `-review`) annoncé en tête, ou `None`.

    Trois marqueurs de tête au plus, dans l'ordre où le cerveau les écrit : `[general] [presentation-brief] ...`
    ou `[presentation-author] ...`. `[éphémère]` ne compte pas parmi eux.
    """
    for key in ("description", "prompt"):
        # Parmi les trois premiers mots seulement, comme avant les modificateurs d'orchestration (Slice 05).
        for word in agent_markers.parse_head(str(tool_input.get(key) or "")).words[:agent_markers.LEGACY_HEAD_WORDS]:
            if word in PLAYBOOK_ROLES:
                return word
    return None


def strip_profile(text: str) -> str:
    """La description sans ses marqueurs (éphémère compris) : ce que l'utilisateur doit lire."""
    return agent_markers.parse_head(text, extra_consumed=PLAYBOOK_ROLES).label


# ------------------------------------------------------------------ décision


CHARTER_NOTE = "Charte du chantier apposée sur la consigne du sous-agent."
ROLE_NOTE = "Méthode du rôle apposée sur la consigne du sous-agent."
LOADOUT_NOTE = "Manifeste du loadout apposé sur la consigne du sous-agent."
#: Séparation entre la consigne du cerveau et le manifeste ajouté à sa suite.
BRIEF_GAP = "\n\n"


def _allow() -> dict[str, Any]:
    """Aucune opinion : le CLI fait ce qu'il avait prévu."""
    return {}


@dataclass(frozen=True, slots=True)
class Orchestration:
    """Ce que le hook lit et décide d'un appel `Agent` (Slice 05, `agent_orchestration`). Pur, sans E/S."""

    head: agent_markers.HeadMarkers
    role: SubagentRole | None
    nested: bool
    mission: agent_orchestration.MissionDecision
    method: agent_orchestration.MethodDecision


def orchestration_of(event: Mapping[str, Any]) -> Orchestration:
    """Marqueurs de la description, rôle actif, appel imbriqué ou non, mission et méthode décidées."""

    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, Mapping) else {}
    head = agent_markers.parse_head(str(tool_input.get("description") or ""), extra_consumed=PLAYBOOK_ROLES)
    role = role_for(read_role(tool_input))
    caller = event.get("agent_id")
    nested = isinstance(caller, str) and bool(caller)
    tool_use_id = event.get("tool_use_id")
    tool_use_id = tool_use_id if isinstance(tool_use_id, str) and tool_use_id else None
    return Orchestration(
        head=head, role=role, nested=nested,
        mission=agent_orchestration.decide_mission(head, role, tool_use_id=tool_use_id, nested=nested),
        method=agent_orchestration.decide_method(head, role),
    )


def charter_input(
    event: Mapping[str, Any], role_overrides: Mapping[str, str] | None = None,
    promoted: Mapping[str, WorkMethod] | None = None, capabilities: AgentCapabilityPolicy | None = None,
) -> dict[str, Any] | None:
    """La consigne signée de la charte du chantier, ou `None` si rien à changer.

    Même raison d'être que la réécriture de modèle : un prompt système peut
    prier le cerveau de bien briefer, il ne peut pas l'obliger. La charte, elle,
    est apposée ici, sur l'appel lui-même, donc à toute profondeur et quel que
    soit ce que le cerveau a rédigé.

    Fonction pure et sans entrée-sortie : elle ne lit ni réglage ni disque, pour
    que la charte survive à une politique d'aiguillage éteinte ou cassée. Les
    surcharges des méthodes de rôle (`role_overrides`, `{id: texte}`) sont lues
    par l'appelant ; sans elles, chaque rôle prend le défaut du code. De même les
    versions promues des Work Methods (`promoted`, Slice 12) : sans elles, la
    version livrée. De même le manifeste de capacités de l'édition (`capabilities`,
    `docs/product-capabilities.md`) : confiné, méthode du rôle, mission et relations
    ne citent que ce qui existe, et `subagent_note` dit les outils réels ; `None`
    ou non confiné : la consigne d'avant.
    """
    if str(event.get("tool_name") or "") not in AGENT_TOOLS:
        return None
    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, Mapping) else {}
    brief = tool_input.get("prompt")
    if not isinstance(brief, str) or not brief.strip():
        return None  # Sans consigne, il n'y a pas de chantier à cadrer.
    orchestration = orchestration_of(event)
    # Le marqueur de profil reste en tête : c'est là que le lit tout ce qui
    # relit la consigne après coup, et la charte ne doit pas l'enterrer.
    head = brief[:_markers(brief)[0]]
    # Charte consciente du rôle (Slice 05) : un rôle qui ne lance pas n'est pas invité à déléguer.
    can_spawn = orchestration.role is None or orchestration.role.can_spawn
    constrained = orchestration.role is not None and orchestration.role.constrained_output
    # Slice 11 : un Mission Owner lit, juste après la consigne de compte rendu de la charte, que la synthèse
    # s'affiche (même règle que le paragraphe « RESTITUTION (JARVIS) » de son bloc de mission).
    report_note = delivery_quality.REPORT_NOTE if orchestration.mission.mission_owner else None
    signed = head + sign_brief(brief[len(head):], can_spawn=can_spawn, constrained_output=constrained,
                               report_note=report_note)
    # La méthode de production d'une présentation : apposée ici, sur l'appel lui-même, parce qu'un sous-agent ne
    # voit pas le prompt du cerveau et que ce prompt demande des consignes courtes.
    # Édition Presentation (V1.2 Slice 04) : dossier de production et auteur partent des documents de recherche.
    signed = with_playbook(signed, read_playbook_role(tool_input),
                           research_sources=reuses_research(capabilities)) or signed
    # La méthode du rôle annoncé (`subagent_roles`), pour la même raison : texte enregistré par l'utilisateur,
    # sinon défaut du code ; Work Method choisie par l'appelant si le rôle la permet. Jamais doublée.
    signed = with_role_instructions(signed, read_role(tool_input), role_overrides,
                                    method=orchestration.method.method_id, promoted=promoted,
                                    capabilities=capabilities) or signed
    # La responsabilité de mission d'un Mission Owner (Slice 05), apposée en dernier. Jamais doublée.
    mission = agent_orchestration.mission_brief(orchestration.mission, capabilities=capabilities)
    if mission and agent_orchestration.MISSION_MARK not in signed:
        signed = f"{signed.rstrip()}\n\n{mission}"
    # Slice 06 : les relations entre agents, en bloc distinct après la responsabilité de mission ; et la revue
    # asymétrique pour un relecteur QA. Jamais doublés.
    if orchestration.mission.mission_owner and relation_runtime.RELATIONS_MARK not in signed:
        qa_profile = "code" if capabilities is None or capabilities.offers_task_profile("code") else "general"
        signed = f"{signed.rstrip()}\n\n{relation_runtime.relations_brief(qa_profile)}"
    if (orchestration.role is not None and orchestration.role.id in QA_REVIEWER_ROLE_IDS
            and relation_runtime.REVIEWER_MARK not in signed):
        signed = f"{signed.rstrip()}\n\n{relation_runtime.reviewer_brief()}"
    # Édition confinée : les outils réels, après tout le reste (la charte et une méthode éditée parlent de code).
    note = capabilities.subagent_note() if capabilities is not None else None
    if note and SUBAGENT_CONFINED_MARK not in signed:
        signed = f"{signed.rstrip()}\n\n{note}"
    return None if signed == brief else {"prompt": signed}


def loadout_input(event: Mapping[str, Any], runtime_root: Path, prompt: str) -> dict[str, Any] | None:
    """`prompt` suivi du manifeste du loadout du sous-agent, ou `None` si rien à ajouter.

    Le manifeste vient d'un instantané sur disque (`loadout_snapshot`) : aucun appel réseau, aucun
    appel à Core. Il ne contient que des identifiants et des versions, jamais un corps. Un
    manifeste déjà présent n'est pas doublé. Lève si l'instantané est illisible : `run` avale.
    """
    if str(event.get("tool_name") or "") not in AGENT_TOOLS or not prompt.strip():
        return None
    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, Mapping) else {}
    manifest = loadout_snapshot.read_manifest(runtime_root, read_profile(tool_input), read_loadout_role(tool_input))
    if not manifest or MANIFEST_MARK in prompt:
        return None
    return {"prompt": f"{prompt.rstrip()}{BRIEF_GAP}{manifest}"}


def _merge(
    event: Mapping[str, Any], output: dict[str, Any], *changes: Mapping[str, Any] | None, note: str = CHARTER_NOTE
) -> dict[str, Any]:
    """Réunir les réécritures dans un seul `updatedInput`, complet.

    L'entrée est renvoyée entière, pas seulement les clés changées : selon que
    le CLI remplace ou fusionne, une entrée partielle perdrait la consigne — le
    genre de doute qu'on ne laisse pas à l'exécution.
    """
    applied = {key: value for change in changes if change for key, value in change.items()}
    section = dict((output.get("hookSpecificOutput") or {})) if output else {}
    # Un refus reste un refus : rien ne part, il n'y a pas de consigne à cadrer.
    if not applied or section.get("permissionDecision") == "deny":
        return output
    tool_input = event.get("tool_input")
    tool_input = dict(tool_input) if isinstance(tool_input, Mapping) else {}
    updated = {**tool_input, **dict(section.get("updatedInput") or {}), **applied}
    reason = str(section.get("permissionDecisionReason") or "")
    if "prompt" in applied or "subagent_type" in applied:
        reason = f"{reason} {note}".strip()
    # `allow` est déjà la décision du hook quand il réécrit le modèle : rien de
    # nouveau n'est autorisé ici, seule l'entrée change.
    return _output(str(section.get("permissionDecision") or "allow"), reason, updated)


def _output(decision: str, reason: str, updated: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    if updated:
        payload["hookSpecificOutput"]["updatedInput"] = updated
    return payload


#: Valeurs que le paramètre `model` de l'outil `Agent` du CLI Claude accepte : une **famille**, pas un identifiant de
#: catalogue. Constat de la Slice 08 (CLI 2.1.309, bac à sable) : un `updatedInput` portant `claude-haiku-4-5`
#: est refusé par le CLI (« failed schema validation … expected one of sonnet|opus|haiku|fable ») et le sous-agent
#: ne part pas du tout.
#: Décision du Human du 2026-10-24 (HV-ARCH-007) : une famille vaut sa version courante dans le CLI (Sonnet = Sonnet 5.5
#: aujourd'hui). La règle de lecture vit dans `jarvis.domain.model_family`, partagée avec l'onglet Sous-agents.
AGENT_TOOL_MODELS = model_family.FAMILIES


def agent_tool_model(model: str) -> str:
    """La valeur à écrire dans `model` de l'outil `Agent` pour un modèle du catalogue.

    Un identifiant Claude (`claude-haiku-4-5`, `claude-3-5-haiku-…`) devient sa famille (`haiku`) : le CLI la résout
    vers la version courante de cette famille, ce que la trace dit à côté de l'identifiant choisi (`agent_model`).
    Une famille reste telle quelle ; un autre identifiant est rendu inchangé (rien n'est deviné pour lui)."""

    value = str(model or "").strip()
    return model_family.family_of(value) or value


def _model_phrase(decision: RoutingDecision) -> str:
    """Le modèle dit honnêtement : la famille et « version courante du CLI » pour Claude, l'id enregistré à côté."""
    applied = agent_tool_model(decision.model)
    if applied not in AGENT_TOOL_MODELS:
        return decision.model
    phrase = model_family.family_label(applied)
    saved = decision.saved_model or (decision.model if decision.model != applied else "")
    return f"{phrase}, enregistré « {saved} »" if saved else phrase


def decide(
    event: Mapping[str, Any],
    policy: RoutingPolicy,
    candidates: Sequence[ModelCandidate],
    *,
    host_agent: str = HOST_AGENT,
    role_policies: role_routing.RoleRoutingDocument | None = None,
) -> tuple[dict[str, Any], RoutingDecision | None]:
    """Ce que le hook répond au CLI, et la décision qui l'explique.

    Les candidats sont restreints au CLI hôte : l'outil `Agent` n'a pas d'autre
    moyen d'exécution, et prétendre router vers un autre CLI ici serait un
    mensonge de plus dans la trace.

    Un rôle connu annoncé en tête (`[code] [qa]`, `[coder]`) passe par la couche par rôle
    (`role_routing.resolve_for_role`) : sa politique explicite si elle existe, sinon l'héritage du
    profil (annoncé, à défaut `default_profile`). Sans rôle, comportement par profil inchangé.
    """
    if str(event.get("tool_name") or "") not in AGENT_TOOLS:
        return _allow(), None
    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, Mapping) else {}

    role = role_for(read_role(tool_input))
    profile = read_profile(tool_input)
    requested = str(tool_input.get("model") or "")
    local = [item for item in candidates if item.agent == host_agent]

    try:
        if role is not None:
            decision = role_routing.resolve_for_role(
                role, announced_profile(tool_input), role_policies or role_routing.EMPTY_DOCUMENT,
                policy, local, source="brain",
            )
            profile = decision.profile
        else:
            decision = resolve_for(profile, policy, local, source="brain")
    except NoEligibleCandidateError as exc:
        return _output("deny", f"{exc} Ouvrez les réglages d'aiguillage pour autoriser un modèle."), None
    except RoutingError:
        # Profil inconnu ou politique illisible : se taire vaut mieux que
        # bloquer le cerveau sur un détail de configuration.
        return _allow(), None

    if decision.reason == routing.REASON_COMPATIBILITY or not decision.model:
        return _allow(), decision
    applied_model = agent_tool_model(decision.model)
    if requested in (decision.model, applied_model):
        return _allow(), decision
    return (
        _output(
            "allow",
            f"{_scope(role, decision, profile)} : modèle imposé par les réglages de JARVIS ({_model_phrase(decision)}).",
            {"model": applied_model},
        ),
        decision,
    )


def _scope(role: SubagentRole | None, decision: RoutingDecision, profile: str) -> str:
    if role is None:
        return f"Profil « {profile} »"
    if decision.provenance == role_routing.PROVENANCE_EXPLICIT:
        return f"Rôle « {role.id} » (politique du rôle)"
    return f"Rôle « {role.id} » (hérité du profil {profile})"


def explicit_role_policy(event: Mapping[str, Any], role_policies: role_routing.RoleRoutingDocument) -> bool:
    """L'appel annonce-t-il un rôle qui a une politique explicite ? Elle lie même en mode Dupliqué."""
    tool_input = event.get("tool_input")
    role = role_for(read_role(tool_input if isinstance(tool_input, Mapping) else {}))
    return role is not None and role_policies.for_role(role.id) is not None


def resolve_for(
    profile: str,
    policy: RoutingPolicy,
    candidates: Sequence[ModelCandidate],
    *,
    source: str = "",
    override: CandidateRef | None = None,
) -> RoutingDecision:
    return routing.resolve(RoutingIntent(profile=profile, override=override, source=source), policy, candidates)


# ------------------------------------------------------------ état hors ligne


def local_agents() -> list[dict[str, Any]]:
    """Les CLI installés, mesurés par le PATH seul.

    Pas de `--version` ici : le hook s'exécute à chaque appel d'outil, et huit
    secondes d'attente possible par sonde en feraient un frein pour le cerveau.
    Un exécutable présent mais cassé sera vu à l'usage, pas ici.
    """
    agents: list[dict[str, Any]] = []
    for spec in cli_catalog.AGENT_CLIS:
        found = shutil.which(spec.default_command)
        agents.append(
            {
                "id": spec.id,
                "label": spec.label,
                "model_provider": spec.model_provider,
                "capabilities": list(spec.capabilities),
                "available": bool(found),
                "error": "" if found else f"« {spec.default_command} » est introuvable dans le PATH.",
            }
        )
    return agents


def offline_candidates(
    runtime_root: Path,
    policy: RoutingPolicy,
    *,
    now: datetime | None = None,
    settings: dict[str, Any] | None = None,
    extra_refs: Sequence[CandidateRef] = (),
) -> list[ModelCandidate]:
    """Offline candidates require a fresh cache for the active credential."""
    catalog = ModelCatalog(runtime_root / "model-catalog.json")
    models: dict[str, list[dict[str, Any]]] = {}
    reasons: dict[str, str] = {}
    current = now or datetime.now(timezone.utc)
    current_settings = settings if settings is not None else load_settings(runtime_root)
    for spec in cli_catalog.AGENT_CLIS:
        cached = catalog.cached_for(
            spec.model_provider,
            credentials.secret_for(current_settings, spec.model_provider),
        ) or {}
        # `cached_for()` labels every direct cache read stale because callers
        # often use it after a failed refresh. Here age is revalidated
        # explicitly by the same source envelope used by the comparison catalog.
        payload = {**cached, "source": "cache"} if cached else {}
        snapshot = ProviderCatalogSnapshot.from_payload(spec.model_provider, payload, now=current)
        models[spec.model_provider] = filter_by_role(list(snapshot.current_models("text")), "text")
        if not snapshot.authoritative:
            reasons[spec.id] = "Disponibilité non vérifiée : catalogue fournisseur absent ou périmé."
    return agent_routing.with_saved(
        agent_routing.build_candidates(local_agents(), models),
        policy,
        unavailable_reasons_by_agent=reasons,
        extra_refs=extra_refs,
    )


def load_settings(runtime_root: Path) -> dict[str, Any]:
    # `utf-8-sig` et non `utf-8` : un fichier de réglages réouvert dans le
    # Bloc-notes revient avec une marque d'ordre d'octets, et la refuser
    # éteindrait l'aiguillage sans que personne comprenne pourquoi.
    try:
        loaded = json.loads((runtime_root / "control-center-settings.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


# --------------------------------------------------------------- déclaration


#: Ancienne option de ligne de commande de la garde, encore acceptée en entrée mais jamais plus émise : la garde
#: s'active par `agent_orchestration.SPAWN_GUARD_ENV` (reprise QA M1).
SPAWN_GUARD_FLAG = "--spawn-guard"


def hook_settings(runtime_root: Path, *, python: str | None = None) -> str:
    """Le `--settings` passé au CLI : ce hook-ci, et rien d'autre.

    Déclaré en ligne de commande plutôt que dans le fichier de réglages de
    l'utilisateur : JARVIS n'a pas à modifier la configuration personnelle de
    quelqu'un pour appliquer la sienne, et le hook meurt avec le processus.
    La commande ne porte que `--runtime-root`, que toutes les versions du hook
    connaissent : l'activation de la garde passe par l'environnement du CLI
    (`agent_orchestration.SPAWN_GUARD_ENV`), qu'une version antérieure ignore.
    """
    executable = python or sys.executable
    command = f'"{executable}" -m jarvis routing-hook --runtime-root "{runtime_root}"'
    return json.dumps(
        {
            "hooks": {
                "PreToolUse": [
                    {"matcher": HOOK_MATCHER, "hooks": [{"type": "command", "command": command}]}
                ]
            }
        },
        ensure_ascii=False,
    )


# ------------------------------------------------------------------- exécution


GUARD_NOTE = "Type d'agent restreint imposé : ce rôle ne lance aucun autre agent."


def _edition_capabilities(journal: RuntimeJournal) -> AgentCapabilityPolicy | None:
    """Le manifeste de l'édition de ce processus (hérité de Core par le CLI), ou `None` s'il est illisible.

    Illisible (valeur d'édition inconnue) : la consigne part comme en `full`, et le journal le dit. Le
    confinement réel n'en dépend pas : il est imposé au lancement du CLI (`claude_local`), pas par ce texte.
    """
    from jarvis.domain.agent_capabilities import agent_capability_policy
    from jarvis.runtime.product_edition_env import process_edition

    try:
        return agent_capability_policy(process_edition())
    except Exception as exc:  # noqa: BLE001 - capture : une édition illisible ne vaut pas un outil perdu
        _emit(journal, "agent.capabilities.unreadable",
              f"Édition produit illisible ({type(exc).__name__}) : consignes des sous-agents non adaptées.",
              level="warning", data={"code": "agent_capabilities_unreadable", "exception_type": type(exc).__name__})
        return None


def _edition_role_guard(orchestration: Orchestration | None,
                        capabilities: AgentCapabilityPolicy | None) -> agent_orchestration.SpawnGuard | None:
    """Refus d'un rôle que l'édition n'offre pas (`subagent_roles.edition_role_refusal`), ou `None`.

    Édition confinée seulement : un `[coder]` forgé ne part pas, même sans outil d'écriture, parce qu'un rôle de
    développement n'a pas de sens dans une édition qui ne développe pas. Code stable `role_unavailable_in_edition`,
    consigné par `_log_declared` (`agent.spawn_refused`). `full` ou édition illisible : rien ne change.
    """
    if orchestration is None:
        return None
    reason = edition_role_refusal(orchestration.role, capabilities)
    if reason is None:
        return None
    return agent_orchestration.SpawnGuard(deny=True, code=ROLE_UNAVAILABLE_CODE, reason=reason)


def _log_confined_adaptation(journal: RuntimeJournal, event: Mapping[str, Any], role: SubagentRole,
                             role_overrides: Mapping[str, str], capabilities: AgentCapabilityPolicy | None) -> None:
    """Consigne les passages d'une méthode de rôle que l'édition confinée n'a pas pu réécrire (surcharge modifiée).

    Jamais en silence (reprise QA Slice 04, m6) : la méthode part avec le paragraphe confiné du dossier ajouté,
    mais une phrase éditée par l'utilisateur peut encore décrire un outil absent ; le code dit laquelle.
    """
    try:
        _text, missed = adapt_instructions(role, instructions_for(role, role_overrides), capabilities)
    except Exception as exc:  # noqa: BLE001 - capture : le diagnostic ne retient jamais l'appel
        missed = (f"adaptation_failed:{type(exc).__name__}",)
    if missed:
        _emit(journal, "agent.role.confined_adaptation_missed",
              f"Méthode du rôle « {role.id} » : passage(s) non adapté(s) à l'édition ({', '.join(missed)}).",
              level="warning",
              data={"code": "role_confined_adaptation_missed", "role_id": role.id, "missed": list(missed),
                    "source": "override" if role.id in role_overrides else "default",
                    "tool_use_id": str(event.get("tool_use_id") or "")[:128]})


def run(event: Mapping[str, Any], runtime_root: Path, *, spawn_guard: bool = False) -> dict[str, Any]:
    """Décider et consigner. Toute panne interne se solde par un silence.

    La charte du chantier est calculée d'abord, et apposée quoi qu'il arrive à
    l'aiguillage : elle ne dépend d'aucun réglage, et une politique éteinte ne
    doit pas rendre les sous-agents muets sur leur propre rôle.

    Slice 05 : la garde de lancement (`agent_orchestration.decide_spawn_guard`)
    refuse ou restreint avant tout ; puis, pour un appel qui part vraiment (pas
    refusé), le fait de déclaration est déposé dans le registre local
    (`agent_declarations`), sans réseau, pour que le Control Center le remette à
    Core. Une panne de ce dépôt est consignée et ne retient jamais l'appel.
    """
    journal = RuntimeJournal(runtime_root)
    if relation_runtime.is_relation_tool(event.get("tool_name")):
        return _stamp_relation_call(event, journal)
    try:
        orchestration = orchestration_of(event) if str(event.get("tool_name") or "") in AGENT_TOOLS else None
    except Exception:  # noqa: BLE001 - une lecture qui lève ne vaut pas un outil perdu ; rien n'est déclaré
        orchestration = None
    # Le manifeste de l'édition, lu une fois : il refuse d'abord un rôle que l'édition n'offre pas, puis adapte la
    # consigne de ce qui part.
    capabilities = _edition_capabilities(journal)
    guard = (_edition_role_guard(orchestration, capabilities) or _delegation_guard(event, runtime_root, journal)
             or _spawn_guard(event, runtime_root, journal, orchestration, enforce=spawn_guard))
    if guard.deny:
        _log_declared(journal, event, orchestration, guard, written=False)
        return _output("deny", guard.reason)
    if orchestration is not None and orchestration.head.handoff and not orchestration.mission.handoff:
        # Reprise QA B1 : un `[relais]` impossible à honorer est refusé, jamais ignoré en silence ; et avant toute
        # réclamation, pour que le billet reste à un appel correct.
        _emit(journal, "agent.handoff.failed", "[relais] impossible à honorer : appel refusé.", level="warning",
              data={"code": orchestration.mission.refused or "handoff_impossible",
                    "tool_use_id": str(event.get("tool_use_id") or "")[:128]})
        _log_declared(journal, event, orchestration, guard, written=False)
        return _output("deny", HANDOFF_IMPOSSIBLE_REASON)
    ticket = None
    if orchestration is not None and orchestration.mission.handoff:
        ticket, refusal = _claim_handoff(event, runtime_root, journal)
        if refusal:
            _log_declared(journal, event, orchestration, guard, written=False)
            return _output("deny", refusal)
    role_overrides = _role_overrides(event, runtime_root, journal)
    promoted = _promoted_methods(event, runtime_root, journal)
    try:
        charter = charter_input(event, role_overrides, promoted, capabilities)
    except Exception:  # noqa: BLE001 - une charte qui lève ne vaut pas un outil perdu
        charter = None
    if orchestration is not None and orchestration.role is not None:
        _log_confined_adaptation(journal, event, orchestration.role, role_overrides, capabilities)
    if ticket is not None:
        charter = _with_handoff_packet(event, charter, ticket)
    role = _log_role(journal, event, charter, role_overrides, promoted)
    brief, loadout = _brief_change(event, runtime_root, charter, journal)
    note = _brief_note(charter is not None, loadout, role=role)
    guarded = {"subagent_type": guard.rewrite_agent_type} if guard.rewrite_agent_type else None
    if guarded:
        # Sans réécriture de la consigne, la note de la garde est seule (reprise QA : elle était perdue).
        note = f"{note} {GUARD_NOTE}".strip() if brief else GUARD_NOTE
    output = _route(event, runtime_root, journal, charter is not None)
    # La note de la garde voyage avec celle de la consigne (`_merge` ne note que sa réécriture) ; la ligne
    # `agent.declared` consigne la garde dans tous les cas.
    final = _merge(event, output, brief, guarded, note=note)
    denied = ((final.get("hookSpecificOutput") or {}).get("permissionDecision") == "deny") if final else False
    if orchestration is not None and not denied:
        written = _declare(event, runtime_root, journal, orchestration, ticket, promoted)
        _log_declared(journal, event, orchestration, guard, written=written, ticket=ticket, promoted=promoted)
    return final


# ------------------------------------------------------------------ relations (Slice 06)


HANDOFF_IMPOSSIBLE_REASON = (
    "[relais] refusé : un relais se fait vers un rôle qui peut porter une mission (coder, research-lead), sans "
    "[éphémère] ni [mission], depuis le Mission Owner qui l'a préparé. Corrigez la description, par exemple "
    "« [code] [coder] [relais] Suite », puis relancez l'appel Agent : le relais préparé vous attend.")
HANDOFF_MISSING_REASON = (
    "[relais] demandé, mais aucun relais préparé par vous n'attend de successeur (ou il a expiré). Appelez d'abord "
    f"mcp__{relation_runtime.RELATION_SERVER}__relation_handoff avec le paquet de relais, puis relancez cet appel "
    "Agent avec [relais] après le rôle.")


def _stamp_relation_call(event: Mapping[str, Any], journal: RuntimeJournal) -> dict[str, Any]:
    """Apposer l'identité de l'appelant sur un outil de relation (écrase toute valeur écrite par le modèle).

    Sans réseau ni disque : l'`agent_id` vient de l'événement du CLI (`None` pour le cerveau). Le serveur MCP lit
    ce champ, absent du schéma montré au modèle ; sans lui il refuse (`relation_caller_unstamped`).
    """
    tool_input = event.get("tool_input")
    updated = dict(tool_input) if isinstance(tool_input, Mapping) else {}
    stamp = relation_runtime.caller_stamp(event)
    updated[relation_runtime.CALLER_STAMP_KEY] = stamp
    _emit(journal, "agent.relation_call", "Identité de l'appelant apposée sur un outil de relation.", level="info",
          data={"code": "relation_caller_stamped", "tool": str(event.get("tool_name") or "")[:96],
                "tool_use_id": str(event.get("tool_use_id") or "")[:128], "caller_agent_id": stamp["agent_id"]})
    return _output("allow", "Identité de l'appelant apposée par JARVIS.", updated)


def _claim_handoff(event: Mapping[str, Any], runtime_root: Path,
                   journal: RuntimeJournal) -> tuple[agent_handoffs.HandoffTicket | None, str]:
    """Le billet du relais que l'appelant a préparé, réclamé une fois ; sinon la raison du refus de l'appel."""
    caller = event.get("agent_id")
    if not isinstance(caller, str) or not caller:
        return None, HANDOFF_MISSING_REASON
    try:
        ticket = agent_handoffs.claim(runtime_root, caller)
    except OSError as exc:
        _emit(journal, "agent.handoff.failed", f"Billets de relais illisibles : {type(exc).__name__}", level="error",
              data={"code": "handoff_tickets_unreadable", "exception_type": type(exc).__name__})
        return None, ("Les relais préparés sont illisibles sur ce poste ; le successeur n'est pas lancé. Réessayez, "
                      "ou passez la suite dans votre compte rendu.")
    if ticket is None:
        _emit(journal, "agent.handoff.failed", "[relais] sans relais préparé : appel refusé.", level="warning",
              data={"code": "handoff_ticket_missing", "caller_agent_id": caller[:96],
                    "tool_use_id": str(event.get("tool_use_id") or "")[:128]})
        return None, HANDOFF_MISSING_REASON
    _emit(journal, "agent.handoff.claimed", "Relais préparé réclamé par son successeur.", level="info",
          data={"code": "handoff_ticket_claimed", "handoff_id": ticket.handoff_id, "mission_id": ticket.mission_id,
                "caller_agent_id": caller[:96], "tool_use_id": str(event.get("tool_use_id") or "")[:128]})
    return ticket, ""


def _with_handoff_packet(event: Mapping[str, Any], charter: Mapping[str, Any] | None,
                         ticket: agent_handoffs.HandoffTicket) -> dict[str, Any] | None:
    """La consigne du successeur avec son paquet de relais en bloc distinct (jamais doublé)."""
    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, Mapping) else {}
    base = charter["prompt"] if charter else tool_input.get("prompt")
    if not isinstance(base, str) or relation_runtime.HANDOFF_MARK in base:
        return dict(charter) if charter else None
    block = relation_runtime.handoff_brief(handoff_id=ticket.handoff_id, mission_id=ticket.mission_id,
                                           purpose=ticket.purpose, packet=ticket.packet)
    return {**(dict(charter) if charter else {}), "prompt": f"{base.rstrip()}\n\n{block}"}


def _route(event: Mapping[str, Any], runtime_root: Path, journal: RuntimeJournal, charter: bool) -> dict[str, Any]:
    """La décision d'aiguillage du modèle (inchangée), ou `{}` quand la politique se tait ou tombe en panne."""
    try:
        settings = load_settings(runtime_root)
        policy = agent_routing.load_policy(settings)
        # Couche par rôle : un fichier à part, lu hors réseau ; absent ou abîmé = tout hérite.
        role_policies = subagent_role_routing.load_document(runtime_root)
        if not policy.enabled and not explicit_role_policy(event, role_policies):
            # Dupliqué et aucun rôle réglé explicitement : comportement d'avant, le CLI garde la main.
            return _allow()
        candidates = offline_candidates(runtime_root, policy, settings=settings, extra_refs=role_policies.refs())
        output, decision = decide(event, policy, candidates, role_policies=role_policies)
    except Exception as exc:  # noqa: BLE001 - un hook qui lève bloquerait l'outil
        try:
            journal.emit(
                "agent.routing.failed",
                f"Aiguillage des sous-agents indisponible ({type(exc).__name__}) : le CLI garde la main.",
                level="error",
                data={"code": "routing_hook_failed", "exception_type": type(exc).__name__},
            )
        except OSError:
            pass
        return _allow()
    _log(journal, event, output, decision, charter=charter)
    return output


#: Code consigné (`agent.spawn_refused`) quand la tendance de délégation du cerveau Core vaut `never`.
DELEGATION_NEVER_CODE = "brain_delegation_never"
DELEGATION_NEVER_REASON = (
    "Délégation désactivée : la tendance de délégation du cerveau Core vaut « Jamais » "
    "(Réglages › Architecture & Agents › Architecture, fenêtre du cerveau Core). Faites-le dans ce tour ou dites à "
    "l'utilisateur ce qui demanderait un sous-agent."
)


def _delegation_guard(event: Mapping[str, Any], runtime_root: Path,
                      journal: RuntimeJournal) -> agent_orchestration.SpawnGuard | None:
    """Refus d'un appel `Agent` **du cerveau** quand sa tendance vaut `never` (docs/brain-config.md).

    Défense en profondeur : `claude_local` retire déjà l'outil au lancement du CLI ; ce refus couvre un CLI lancé
    avant le réglage (il garde l'outil jusqu'à sa relance) et s'applique dès l'appel suivant, le fichier étant relu
    à chaque appel. Seul l'appel du cerveau est visé (`agent_id` absent) : un sous-agent déjà lancé avant le
    réglage finit sa mission avec ses propres outils. Un fichier illisible se lit `standard` (le défaut), dit au
    journal : le hook ne refuse jamais sur une panne.
    """
    if str(event.get("tool_name") or "") not in AGENT_TOOLS:
        return None
    caller = event.get("agent_id")
    if isinstance(caller, str) and caller:
        return None
    loaded = brain_config_store.load(runtime_root)
    if loaded.error_code:
        _emit(journal, "agent.delegation.unreadable", "Configuration des cerveaux illisible : tendance standard.",
              level="warning", data={"code": loaded.error_code})
    if loaded.document.delegation_for("core") is not DelegationTendency.NEVER:
        return None
    return agent_orchestration.SpawnGuard(deny=True, code=DELEGATION_NEVER_CODE, reason=DELEGATION_NEVER_REASON)


def _spawn_guard(event: Mapping[str, Any], runtime_root: Path, journal: RuntimeJournal,
                 orchestration: Orchestration | None, *, enforce: bool) -> agent_orchestration.SpawnGuard:
    """La garde de lancement, avec le compte des lancements récents (registre local). Ne lève jamais.

    Le compte illisible laisse passer (la borne est une sûreté, pas une autorisation) et se dit au journal.
    L'élagage des faits anciens se fait ici, à chaque appel : le dossier reste borné même sans Control Center.
    """
    if orchestration is None:
        return agent_orchestration.SpawnGuard()
    recent = free = None
    try:
        agent_declarations.prune(runtime_root)
        stamps = agent_declarations.recent_stamps(runtime_root, agent_orchestration.SPAWN_WINDOW_S)
        recent = len(stamps)
        free = agent_declarations.free_in_s(stamps, agent_orchestration.SPAWN_WINDOW_S,
                                            agent_orchestration.MAX_SPAWNS_PER_WINDOW)
    except OSError as exc:
        _emit(journal, "agent.declaration.failed", "Registre des déclarations illisible : borne de sûreté non "
              "vérifiée pour ce lancement.", level="warning",
              data={"code": "declaration_ledger_unreadable", "exception_type": type(exc).__name__})
    try:
        return agent_orchestration.decide_spawn_guard(event, orchestration.role, enforce=enforce,
                                                      recent_spawns=recent, window_free_in_s=free)
    except Exception as exc:  # noqa: BLE001 - une garde qui lève ne vaut pas un outil perdu
        _emit(journal, "agent.declaration.failed", "Garde de lancement en panne : l'appel part sans garde.",
              level="error", data={"code": "spawn_guard_failed", "exception_type": type(exc).__name__})
        return agent_orchestration.SpawnGuard()


def _declare(event: Mapping[str, Any], runtime_root: Path, journal: RuntimeJournal,
             orchestration: Orchestration, ticket: agent_handoffs.HandoffTicket | None = None,
             promoted: Mapping[str, WorkMethod] | None = None) -> bool:
    """Déposer le fait de déclaration (contrat v1) ; rend s'il est écrit. Ne lève jamais, consigne chaque panne.

    Successeur d'un relais (Slice 06) : Mission Owner de la mission reprise, avec l'id du relais réclamé.
    """
    try:
        fact = fact_from_hook_event(event, declared_at=datetime.now(timezone.utc),
                                    mission_id=ticket.mission_id if ticket else orchestration.mission.mission_id,
                                    mission_owner=orchestration.mission.mission_owner,
                                    handoff_id=ticket.handoff_id if ticket else None,
                                    # Slice 12 : la méthode apposée devient une preuve d'usage durable.
                                    work_method=method_key(orchestration.method.method_id,
                                                           role=orchestration.role, promoted=promoted),
                                    work_method_chosen=orchestration.method.chosen
                                    and method_key(orchestration.method.method_id) is not None)
    except MissionHistoryError as exc:
        _emit(journal, "agent.declaration.failed", f"Déclaration du sous-agent hors contrat : {exc}", level="warning",
              data={"code": exc.code, "field": exc.field, "tool_use_id": str(event.get("tool_use_id") or "")[:128]})
        return False
    try:
        agent_declarations.write_fact(runtime_root, fact)
    except agent_declarations.DeclarationLedgerFull as exc:
        _emit(journal, "agent.declaration.failed", f"Registre des déclarations plein : {exc}", level="error",
              data={"code": "declaration_ledger_full", "tool_use_id": fact.tool_use_id})
        return False
    except OSError as exc:
        _emit(journal, "agent.declaration.failed", f"Déclaration du sous-agent non écrite : {type(exc).__name__}",
              level="error", data={"code": "declaration_write_failed", "tool_use_id": fact.tool_use_id,
                                   "exception_type": type(exc).__name__})
        return False
    return True


def _log_declared(journal: RuntimeJournal, event: Mapping[str, Any], orchestration: Orchestration | None,
                  guard: agent_orchestration.SpawnGuard, *, written: bool,
                  ticket: agent_handoffs.HandoffTicket | None = None,
                  promoted: Mapping[str, WorkMethod] | None = None) -> None:
    """`agent.declared` (fait déposé) ou `agent.spawn_refused` (garde) : des codes et des ids, jamais un texte."""
    if orchestration is None and not guard.deny:
        return
    role = orchestration.role if orchestration is not None else None
    mission = orchestration.mission if orchestration is not None else agent_orchestration.MissionDecision()
    method = orchestration.method if orchestration is not None else agent_orchestration.MethodDecision(None)
    caller = event.get("agent_id")
    data = {
        "code": guard.code if guard.deny else "agent_declared",
        "tool_use_id": str(event.get("tool_use_id") or "")[:128],
        "role_id": role.id if role is not None else None,
        "caller_agent_id": caller if isinstance(caller, str) and caller else None,
        "caller_agent_type": str(event.get("agent_type") or "") or None,
        # V1.2 Slice 03 : la topologie se lit dans la trace (qui lance qui, quel rôle, au premier plan ou en fond).
        "run_in_background": bool((event.get("tool_input") or {}).get("run_in_background"))
        if isinstance(event.get("tool_input"), Mapping) else False,
        "ephemeral": bool(orchestration and orchestration.head.ephemeral),
        "mission_owner": mission.mission_owner,
        "mission_id": ticket.mission_id if ticket else mission.mission_id,
        "sub_mission": mission.sub_mission,
        "handoff_id": ticket.handoff_id if ticket else None,
        "mission_refused": mission.refused,
        "work_method": method_key(method.method_id, role=role, promoted=promoted),
        "work_method_chosen": method.chosen,
        "work_method_refused": method.refused,
        "spawn_guard": guard.code,
        "written": written,
    }
    if guard.deny:
        _emit(journal, "agent.spawn_refused", f"Lancement refusé par JARVIS : {guard.reason}", level="warning",
              data=data)
    else:
        _emit(journal, "agent.declared", "Sous-agent déclaré pour Core.", level="info" if written else "warning",
              data=data)


def _emit(journal: RuntimeJournal, kind: str, message: str, *, level: str, data: dict[str, Any]) -> None:
    try:
        journal.emit(kind, message, level=level, data=data)
    except OSError:
        pass  # intentional: an unwritable journal never blocks the CLI tool call (module rule: the hook stays silent)


def _brief_change(
    event: Mapping[str, Any], runtime_root: Path, charter: Mapping[str, Any] | None, journal: RuntimeJournal
) -> tuple[Mapping[str, Any] | None, bool]:
    """La réécriture de la consigne : la charte, puis le manifeste du loadout à sa suite.

    Le manifeste vient d'un fichier d'instantané, jamais du réseau. Toute panne de cette
    lecture laisse la consigne comme la charte l'a faite (ou intacte), sans rien dire au CLI ;
    seule la trace en garde un code. Rend aussi si le manifeste a été apposé.
    """
    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, Mapping) else {}
    base = charter["prompt"] if charter else tool_input.get("prompt")
    try:
        added = loadout_input(event, runtime_root, base) if isinstance(base, str) else None
    except Exception as exc:  # noqa: BLE001 - un instantané illisible ne vaut pas un outil perdu
        try:
            journal.emit(
                "agent.loadout.failed",
                f"Loadout du sous-agent indisponible ({type(exc).__name__}) : la consigne part sans manifeste.",
                level="warning",
                data={"code": "loadout_snapshot_failed", "exception_type": type(exc).__name__},
            )
        except OSError:
            pass
        return charter, False
    if not added:
        return charter, False
    try:
        # La preuve de ce qui a été injecté : le couple et la taille, jamais le texte du manifeste.
        journal.emit(
            "agent.loadout.applied",
            "Manifeste du loadout ajouté à la consigne du sous-agent.",
            data={
                "code": "loadout_manifest_applied",
                "tool_use_id": str(event.get("tool_use_id") or ""),
                "profile": read_profile(tool_input),
                "role": read_loadout_role(tool_input),
                "manifest_chars": len(added["prompt"]) - len(base),
            },
        )
    except OSError:
        pass
    return added, True


def _brief_note(charter: bool, loadout: bool, *, role: bool = False) -> str:
    notes = ([CHARTER_NOTE] if charter or not loadout else []) + [ROLE_NOTE] * role + [LOADOUT_NOTE] * loadout
    return " ".join(notes)


def _role_overrides(event: Mapping[str, Any], runtime_root: Path, journal: RuntimeJournal) -> dict[str, str]:
    """Les surcharges des méthodes de rôle, lues dans l'instantané ; `{}` (défauts du code) si rien ou illisible.

    Lu seulement pour un appel qui annonce un rôle du registre : les autres n'en ont pas besoin. Un fichier
    illisible est consigné en avertissement et la consigne part avec le texte par défaut du rôle.
    """
    if str(event.get("tool_name") or "") not in AGENT_TOOLS:
        return {}
    tool_input = event.get("tool_input")
    if role_for(read_role(tool_input if isinstance(tool_input, Mapping) else {})) is None:
        return {}
    try:
        return subagent_roles_snapshot.read_overrides(runtime_root)
    except Exception as exc:  # noqa: BLE001 - un instantané illisible ne vaut pas un outil perdu
        try:
            journal.emit(
                "agent.role.failed",
                f"Instructions de rôle enregistrées illisibles ({type(exc).__name__}) : "
                "le rôle part avec son texte par défaut.",
                level="warning",
                data={"code": "subagent_roles_snapshot_failed", "exception_type": type(exc).__name__},
            )
        except OSError:
            pass
        return {}


def _log_role(
    journal: RuntimeJournal,
    event: Mapping[str, Any],
    charter: Mapping[str, Any] | None,
    role_overrides: Mapping[str, str],
    promoted: Mapping[str, WorkMethod] | None = None,
) -> bool:
    """Consigne `agent.role_applied` quand la méthode d'un rôle vient d'être apposée ; rend si elle l'a été.

    La preuve est faite de codes : le marqueur tel qu'écrit (`role`), l'id canonique et le statut de sa
    résolution (`reviewer` -> `qa`, `alias`), le profil, la source des instructions (`override` ou `default`),
    la Work Method apposée (`<id>@<version>` ou `None`), le rôle de loadout, la capacité de lancer des agents,
    l'`agent_id` de l'appelant quand l'appel est imbriqué (`caller_agent_id`, `None` pour le cerveau : de quoi
    vérifier après coup qu'un rôle qui ne lance pas n'a lancé personne), et deux tailles : `instructions_chars`
    = tout le texte apposé à partir de `ROLE_MARK` (instructions, capacités et méthode), et
    `role_instructions_chars` = les seules instructions effectives (surcharge ou défaut). Jamais le texte.
    """
    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, Mapping) else {}
    before = tool_input.get("prompt")
    after = charter.get("prompt") if charter else None
    if not isinstance(after, str) or ROLE_MARK not in after or (isinstance(before, str) and ROLE_MARK in before):
        return False
    role = read_role(tool_input)
    resolution = resolve_role(role)
    active = role_for(role)
    # La méthode réellement apposée : celle choisie par l'appelant si le rôle la permet, sinon le défaut (Slice 05).
    head = agent_markers.parse_head(str(tool_input.get("description") or ""), extra_consumed=PLAYBOOK_ROLES)
    method = agent_orchestration.decide_method(head, active).method_id
    # Diagnostic codé (reprise QA Slice 07) : un second mot de rôle reste dans le libellé, sans refus ni relecture.
    second = agent_markers.second_role_marker(head)
    caller = event.get("agent_id")
    try:
        journal.emit(
            "agent.role_applied",
            f"Méthode du rôle « {role} » ajoutée à la consigne du sous-agent.",
            data={
                "code": "subagent_role_applied",
                "tool_use_id": str(event.get("tool_use_id") or ""),
                "role": role,
                "role_id": resolution.role_id,
                "role_status": resolution.status.value,
                "profile": read_profile(tool_input),
                "source": "override" if resolution.role_id in role_overrides else "default",
                "work_method": method_key(method, role=active, promoted=promoted),
                "loadout_role": read_loadout_role(tool_input),
                "can_spawn": bool(active and active.can_spawn),
                "caller_agent_id": caller if isinstance(caller, str) and caller else None,
                "instructions_chars": len(after) - after.index(ROLE_MARK),
                "role_instructions_chars": len(instructions_for(active, role_overrides).strip()) if active else 0,
                "second_role_marker": second,
                "diagnostics": [agent_markers.SECOND_ROLE_MARKER] if second else [],
            },
            level="warning" if second else "info",
        )
    except OSError:
        pass
    return True


def method_key(method_id: str | None, *, role: SubagentRole | None = None,
               promoted: Mapping[str, WorkMethod] | None = None) -> str | None:
    """`<id>@<version>` de la Work Method apposée, ou `None` : la dernière version promue pour ce rôle quand
    l'instantané en porte une (`subagent_roles.effective_method`, Slice 12), sinon la version livrée."""
    if role is not None:
        method = effective_method(role, method_id, promoted)
    else:
        method = builtin_method(method_id) if method_id else None
    return method.key if method is not None else None


def _promoted_methods(event: Mapping[str, Any], runtime_root: Path, journal: RuntimeJournal) -> dict[str, WorkMethod]:
    """Les dernières versions promues des Work Methods, lues dans l'instantané (Slice 12) ; `{}` sinon.

    Lu seulement pour un appel `Agent` qui annonce un rôle du registre. Absent : `{}` sans bruit (aucune
    promotion, ou Control Center pas encore synchronisé). Illisible : consigné en avertissement, et la consigne
    part avec la version livrée de la méthode ; l'appel n'est jamais retenu.
    """
    if str(event.get("tool_name") or "") not in AGENT_TOOLS:
        return {}
    tool_input = event.get("tool_input")
    if role_for(read_role(tool_input if isinstance(tool_input, Mapping) else {})) is None:
        return {}
    try:
        return work_methods_snapshot.read_promoted(runtime_root)
    except Exception as exc:  # noqa: BLE001 - un instantané illisible ne vaut pas un outil perdu
        _emit(journal, "agent.work_method.failed",
              f"Versions promues des Work Methods illisibles ({type(exc).__name__}) : la version livrée s'applique.",
              level="warning", data={"code": "work_methods_snapshot_failed", "exception_type": type(exc).__name__})
        return {}


def _log(
    journal: RuntimeJournal,
    event: Mapping[str, Any],
    output: Mapping[str, Any],
    decision: RoutingDecision | None,
    *,
    charter: bool = False,
) -> None:
    """La preuve d'aiguillage dans la trace : des codes, jamais de raisonnement.

    Ce que l'on garde suffit à expliquer un mauvais choix — le profil, les
    candidats vus et leur verdict, celui retenu, ce que le cerveau demandait.
    """
    if decision is None and not output and not charter:
        return
    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, Mapping) else {}
    applied = (output.get("hookSpecificOutput") or {}).get("permissionDecision") if output else "unchanged"
    data: dict[str, Any] = {
        "code": "routing_decided",
        "tool": str(event.get("tool_name") or ""),
        "tool_use_id": str(event.get("tool_use_id") or ""),
        "requested_model": str(tool_input.get("model") or ""),
        "subagent_type": str(tool_input.get("subagent_type") or ""),
        "applied": applied or "unchanged",
        # La charte n'est pas une décision d'aiguillage : elle est consignée à
        # part pour qu'« unchanged » garde son sens (aucun modèle réécrit).
        "charter": charter,
    }
    if decision is not None:
        data.update(decision.as_dict())
        if decision.model:
            # Ce que l'outil `Agent` reçoit vraiment : la famille du modèle choisi (`agent_tool_model`).
            data["agent_model"] = agent_tool_model(decision.model)
            if data["agent_model"] in AGENT_TOOL_MODELS:
                # La famille demandée, que le CLI résout vers sa version courante (HV-ARCH-007) ; l'identifiant
                # enregistré dont elle vient reste dans `saved_model` (rôle) ou `model` (profil).
                data["model_family"] = data["agent_model"]
    message = (
        f"Sous-agent « {strip_profile(tool_input.get('description') or '') or 'sans description'} » : "
        f"profil {data.get('profile', routing.GENERAL_PROFILE)}"
    )
    if decision is not None and decision.role_id:
        message += f", rôle {decision.role_id} ({decision.provenance})"
    if decision is not None and decision.reason == role_routing.REASON_ROLE_PASSTHROUGH:
        message += ", aucun candidat du rôle utilisable : le CLI garde la main (Dupliqué)"
    if decision is not None and decision.model:
        message += f", modèle {_model_phrase(decision)}"
    try:
        passthrough = decision is not None and decision.reason == role_routing.REASON_ROLE_PASSTHROUGH
        level = "warning" if applied == "deny" or passthrough else "info"
        journal.emit("agent.routing.decided", message, level=level, data=data)
    except OSError:
        pass


def default_runtime_root() -> Path:
    """La racine runtime sans `--runtime-root` (ou avec une valeur vide) : `JARVIS_RUNTIME_DIR`, sinon le dossier
    `runtime/` du dépôt (ignoré par git). Jamais le répertoire courant : le journal et le registre des
    déclarations n'y tombent pas (reprise QA S12, `trace.jsonl` égaré à la racine d'un worktree)."""
    configured = (os.environ.get("JARVIS_RUNTIME_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    from jarvis.data_root import default_runtime_root  # produit installé : `<maison du produit>/runtime`
    return default_runtime_root(dev_default=Path(__file__).resolve().parents[2] / "runtime")


def main(argv: Sequence[str] | None = None) -> int:
    """Entrée du sous-commande `jarvis routing-hook`, branchée sur stdin/stdout."""
    args = list(argv if argv is not None else sys.argv[1:])
    runtime_root = default_runtime_root()
    if "--runtime-root" in args:
        index = args.index("--runtime-root")
        if index + 1 < len(args) and args[index + 1].strip():
            runtime_root = Path(args[index + 1])
    # Le manifeste porte des accents (Références, mémoire, rôle) : la sortie est de l'UTF-8
    # quelle que soit la page de code du poste, et une entrée mal codée ne fait pas tomber le hook.
    for stream, errors in ((sys.stdin, "replace"), (sys.stdout, "strict")):
        try:
            stream.reconfigure(encoding="utf-8", errors=errors)
        except (AttributeError, ValueError, OSError):
            pass  # flux remplacé (test, redirection) : on garde son codage
    try:
        # Sous Windows, ce qui arrive sur stdin peut porter une marque d'ordre
        # d'octets selon qui écrit. La refuser reviendrait à ne jamais aiguiller
        # sur cette machine, et en silence.
        event = json.loads(sys.stdin.read().lstrip("﻿") or "{}")
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        event = {}
    spawn_guard = SPAWN_GUARD_FLAG in args or agent_orchestration.spawn_guard_enabled(os.environ)
    try:
        output = run(event if isinstance(event, dict) else {}, runtime_root, spawn_guard=spawn_guard)
    except Exception as exc:  # noqa: BLE001 - la frontière du hook : toute panne laisse l'appel partir intact
        # Reprise QA : un hook qui lève ou sort autrement qu'en 0 ferait refuser l'appel `Agent` par le CLI. La
        # panne est consignée ; aucune sortie = le CLI garde la consigne d'origine. Exception (Slice 06, reprise
        # QA N2) : un outil de relation échoue FERMÉ, refus explicite, car il partirait sans identité apposée.
        relation = hook_failsafe.is_relation_call(event if isinstance(event, dict) else None)
        _emit(RuntimeJournal(runtime_root), "agent.routing.failed",
              f"Hook des sous-agents en panne ({type(exc).__name__}) : "
              + ("outil de relation refusé." if relation else "l'appel part sans réécriture."), level="error",
              data={"code": "routing_hook_crashed", "exception_type": type(exc).__name__, "fail_closed": relation})
        if relation:
            sys.stdout.write(json.dumps(hook_failsafe.deny(), ensure_ascii=False))
        return 0
    if output:
        sys.stdout.write(json.dumps(output, ensure_ascii=False))
    return 0

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

import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Mapping, Sequence

from jarvis.domain import routing
from jarvis.domain.routing import (
    CandidateRef,
    ModelCandidate,
    NoEligibleCandidateError,
    RoutingDecision,
    RoutingError,
    RoutingIntent,
    RoutingPolicy,
)
from jarvis.runtime import agent_routing, cli_catalog
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.model_catalog import ModelCatalog, filter_by_role

#: Outils du CLI qui lancent un sous-agent. Mêmes noms que ceux que le suivi
#: des tâches reconnaît (`agent_tasks.AGENT_TOOLS`).
AGENT_TOOLS = ("Agent", "Task")
HOOK_MATCHER = "|".join(AGENT_TOOLS)

#: Le CLI qui exécute réellement les sous-agents. L'outil `Agent` tourne dans
#: le processus Claude : aucune politique ne peut en faire sortir un sous-agent.
HOST_AGENT = "claude"

#: Comment le cerveau annonce le profil : le premier mot entre crochets de la
#: description. Inventé ici plutôt que déduit du texte — deviner l'intention
#: d'une phrase serait exactement le genre de choix qu'on refuse au modèle.
PROFILE_PATTERN = re.compile(r"^\s*\[\s*([A-Za-z_-]{2,24})\s*\]\s*")

PROFILE_RULE = (
    "Commence la description de chaque sous-agent par son profil entre crochets : "
    "[code] pour écrire ou corriger du code, [desktop] pour piloter le navigateur ou "
    "des fichiers ouverts, [fast] pour résumer, classer ou reformuler, [general] "
    "sinon. JARVIS choisit le modèle à partir de ce profil et de tes réglages."
)


def read_profile(tool_input: Mapping[str, Any]) -> str:
    """Le profil annoncé, ou « general ». Un profil inconnu n'en est pas un."""
    for key in ("description", "prompt"):
        match = PROFILE_PATTERN.match(str(tool_input.get(key) or ""))
        if match is not None and routing.is_profile(match.group(1)):
            return match.group(1).strip().lower()
    return routing.GENERAL_PROFILE


def strip_profile(text: str) -> str:
    """La description sans son marqueur : ce que l'utilisateur doit lire."""
    return PROFILE_PATTERN.sub("", str(text or "")).strip()


# ------------------------------------------------------------------ décision


def _allow() -> dict[str, Any]:
    """Aucune opinion : le CLI fait ce qu'il avait prévu."""
    return {}


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


def decide(
    event: Mapping[str, Any],
    policy: RoutingPolicy,
    candidates: Sequence[ModelCandidate],
    *,
    host_agent: str = HOST_AGENT,
) -> tuple[dict[str, Any], RoutingDecision | None]:
    """Ce que le hook répond au CLI, et la décision qui l'explique.

    Les candidats sont restreints au CLI hôte : l'outil `Agent` n'a pas d'autre
    moyen d'exécution, et prétendre router vers un autre CLI ici serait un
    mensonge de plus dans la trace.
    """
    if str(event.get("tool_name") or "") not in AGENT_TOOLS:
        return _allow(), None
    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, Mapping) else {}

    profile = read_profile(tool_input)
    requested = str(tool_input.get("model") or "")
    local = [item for item in candidates if item.agent == host_agent]

    try:
        decision = resolve_for(profile, policy, local, source="brain")
    except NoEligibleCandidateError as exc:
        return _output("deny", f"{exc} Ouvrez les réglages d'aiguillage pour autoriser un modèle."), None
    except RoutingError:
        # Profil inconnu ou politique illisible : se taire vaut mieux que
        # bloquer le cerveau sur un détail de configuration.
        return _allow(), None

    if decision.reason == routing.REASON_COMPATIBILITY or not decision.model:
        return _allow(), decision
    if decision.model == requested:
        return _allow(), decision
    return (
        _output(
            "allow",
            f"Profil « {profile} » : modèle imposé par les réglages de JARVIS ({decision.model}).",
            {"model": decision.model},
        ),
        decision,
    )


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


def offline_candidates(runtime_root: Path, policy: RoutingPolicy) -> list[ModelCandidate]:
    """Les candidats connus sans toucher au réseau : dernier catalogue en cache."""
    catalog = ModelCatalog(runtime_root / "model-catalog.json")
    models: dict[str, list[dict[str, Any]]] = {}
    for spec in cli_catalog.AGENT_CLIS:
        cached = catalog.cached(spec.model_provider) or {}
        models[spec.model_provider] = filter_by_role(list(cached.get("models") or []), "text")
    return agent_routing.with_saved(agent_routing.build_candidates(local_agents(), models), policy)


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


def hook_settings(runtime_root: Path, *, python: str | None = None) -> str:
    """Le `--settings` passé au CLI : ce hook-ci, et rien d'autre.

    Déclaré en ligne de commande plutôt que dans le fichier de réglages de
    l'utilisateur : JARVIS n'a pas à modifier la configuration personnelle de
    quelqu'un pour appliquer la sienne, et le hook meurt avec le processus.
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


def run(event: Mapping[str, Any], runtime_root: Path) -> dict[str, Any]:
    """Décider et consigner. Toute panne interne se solde par un silence."""
    journal = RuntimeJournal(runtime_root)
    try:
        settings = load_settings(runtime_root)
        policy = agent_routing.load_policy(settings)
        if not policy.enabled:
            return _allow()
        candidates = offline_candidates(runtime_root, policy)
        output, decision = decide(event, policy, candidates)
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

    _log(journal, event, output, decision)
    return output


def _log(
    journal: RuntimeJournal,
    event: Mapping[str, Any],
    output: Mapping[str, Any],
    decision: RoutingDecision | None,
) -> None:
    """La preuve d'aiguillage dans la trace : des codes, jamais de raisonnement.

    Ce que l'on garde suffit à expliquer un mauvais choix — le profil, les
    candidats vus et leur verdict, celui retenu, ce que le cerveau demandait.
    """
    if decision is None and not output:
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
    }
    if decision is not None:
        data.update(decision.as_dict())
    message = (
        f"Sous-agent « {strip_profile(tool_input.get('description') or '') or 'sans description'} » : "
        f"profil {data.get('profile', routing.GENERAL_PROFILE)}"
    )
    if decision is not None and decision.model:
        message += f", modèle {decision.model}"
    try:
        journal.emit("agent.routing.decided", message, level="warning" if applied == "deny" else "info", data=data)
    except OSError:
        pass


def main(argv: Sequence[str] | None = None) -> int:
    """Entrée du sous-commande `jarvis routing-hook`, branchée sur stdin/stdout."""
    args = list(argv if argv is not None else sys.argv[1:])
    runtime_root = Path.cwd()
    if "--runtime-root" in args:
        index = args.index("--runtime-root")
        if index + 1 < len(args):
            runtime_root = Path(args[index + 1])
    try:
        # Sous Windows, ce qui arrive sur stdin peut porter une marque d'ordre
        # d'octets selon qui écrit. La refuser reviendrait à ne jamais aiguiller
        # sur cette machine, et en silence.
        event = json.loads(sys.stdin.read().lstrip("﻿") or "{}")
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        event = {}
    output = run(event if isinstance(event, dict) else {}, runtime_root)
    if output:
        sys.stdout.write(json.dumps(output, ensure_ascii=False))
    return 0

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

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Mapping, Sequence

from jarvis.domain import routing
from jarvis.domain.agent_charter import sign_brief
from jarvis.domain.loadout_view import MANIFEST_MARK
from jarvis.domain.memory_settings import LOADOUT_ROLES
from jarvis.domain.routing import (
    CandidateRef,
    ModelCandidate,
    NoEligibleCandidateError,
    RoutingDecision,
    RoutingError,
    RoutingIntent,
    RoutingPolicy,
)
from jarvis.runtime import agent_routing, cli_catalog, credentials, loadout_snapshot
from jarvis.runtime.catalog_view import ProviderCatalogSnapshot
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

#: Un marqueur entre crochets sans ancre : le rôle (`coder`, `reviewer`, `research`) peut suivre
#: le profil (`[code] [reviewer] ...`) ou le remplacer (`[reviewer] ...`, profil `general`).
_BRACKET = re.compile(r"\[\s*([A-Za-z_-]{2,24})\s*\]\s*")

PROFILE_RULE = (
    "Commence la description de chaque sous-agent par son profil entre crochets : "
    "[code] pour écrire ou corriger du code, [desktop] pour piloter le navigateur ou "
    "des fichiers ouverts, [fast] pour résumer, classer ou reformuler, [general] "
    "sinon. JARVIS choisit le modèle à partir de ce profil et de tes réglages. "
    "Pour une relecture, ajoute [reviewer] après le profil ([code] [reviewer] ...) ; "
    "pour une recherche documentaire, [research] ([general] [research] ...) : "
    "JARVIS donne alors au sous-agent les savoirs de ce rôle."
)


def read_profile(tool_input: Mapping[str, Any]) -> str:
    """Le profil annoncé, ou « general ». Un profil inconnu n'en est pas un."""
    for key in ("description", "prompt"):
        match = PROFILE_PATTERN.match(str(tool_input.get(key) or ""))
        if match is not None and routing.is_profile(match.group(1)):
            return match.group(1).strip().lower()
    return routing.GENERAL_PROFILE


def _markers(text: str) -> tuple[int, str | None]:
    """Fin des marqueurs de tête et rôle annoncé : `[profil]`, `[profil] [rôle]` ou `[rôle]`.

    Un premier mot entre crochets est toujours consommé, profil connu ou non (comme avant
    le rôle) ; un second ne l'est que s'il nomme un rôle.
    """
    first = PROFILE_PATTERN.match(text)
    if first is None:
        return 0, None
    word = first.group(1).strip().lower()
    if word in LOADOUT_ROLES:
        return first.end(), word
    if routing.is_profile(word):
        second = _BRACKET.match(text, first.end())
        if second is not None and second.group(1).strip().lower() in LOADOUT_ROLES:
            return second.end(), second.group(1).strip().lower()
    return first.end(), None


def read_role(tool_input: Mapping[str, Any]) -> str | None:
    """Le rôle annoncé après le profil (ou seul), ou `None`. Un rôle inconnu n'en est pas un."""
    for key in ("description", "prompt"):
        role = _markers(str(tool_input.get(key) or ""))[1]
        if role is not None:
            return role
    return None


def strip_profile(text: str) -> str:
    """La description sans ses marqueurs : ce que l'utilisateur doit lire."""
    text = str(text or "")
    return text[_markers(text)[0]:].strip()


# ------------------------------------------------------------------ décision


CHARTER_NOTE = "Charte du chantier apposée sur la consigne du sous-agent."
LOADOUT_NOTE = "Manifeste du loadout apposé sur la consigne du sous-agent."
#: Séparation entre la consigne du cerveau et le manifeste ajouté à sa suite.
BRIEF_GAP = "\n\n"


def _allow() -> dict[str, Any]:
    """Aucune opinion : le CLI fait ce qu'il avait prévu."""
    return {}


def charter_input(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """La consigne signée de la charte du chantier, ou `None` si rien à changer.

    Même raison d'être que la réécriture de modèle : un prompt système peut
    prier le cerveau de bien briefer, il ne peut pas l'obliger. La charte, elle,
    est apposée ici, sur l'appel lui-même, donc à toute profondeur et quel que
    soit ce que le cerveau a rédigé.

    Fonction pure et sans entrée-sortie : elle ne lit ni réglage ni disque, pour
    que la charte survive à une politique d'aiguillage éteinte ou cassée.
    """
    if str(event.get("tool_name") or "") not in AGENT_TOOLS:
        return None
    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, Mapping) else {}
    brief = tool_input.get("prompt")
    if not isinstance(brief, str) or not brief.strip():
        return None  # Sans consigne, il n'y a pas de chantier à cadrer.
    # Le marqueur de profil reste en tête : c'est là que le lit tout ce qui
    # relit la consigne après coup, et la charte ne doit pas l'enterrer.
    head = brief[:_markers(brief)[0]]
    signed = head + sign_brief(brief[len(head):])
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
    manifest = loadout_snapshot.read_manifest(runtime_root, read_profile(tool_input), read_role(tool_input))
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
    if "prompt" in applied:
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


def offline_candidates(
    runtime_root: Path,
    policy: RoutingPolicy,
    *,
    now: datetime | None = None,
    settings: dict[str, Any] | None = None,
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
    """Décider et consigner. Toute panne interne se solde par un silence.

    La charte du chantier est calculée d'abord, et apposée quoi qu'il arrive à
    l'aiguillage : elle ne dépend d'aucun réglage, et une politique éteinte ne
    doit pas rendre les sous-agents muets sur leur propre rôle.
    """
    journal = RuntimeJournal(runtime_root)
    try:
        charter = charter_input(event)
    except Exception:  # noqa: BLE001 - une charte qui lève ne vaut pas un outil perdu
        charter = None
    brief, loadout = _brief_change(event, runtime_root, charter, journal)
    note = _brief_note(charter is not None, loadout)
    try:
        settings = load_settings(runtime_root)
        policy = agent_routing.load_policy(settings)
        if not policy.enabled:
            return _merge(event, _allow(), brief, note=note)
        candidates = offline_candidates(runtime_root, policy, settings=settings)
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
        return _merge(event, _allow(), brief, note=note)

    _log(journal, event, output, decision, charter=charter is not None)
    return _merge(event, output, brief, note=note)


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
                "role": read_role(tool_input),
                "manifest_chars": len(added["prompt"]) - len(base),
            },
        )
    except OSError:
        pass
    return added, True


def _brief_note(charter: bool, loadout: bool) -> str:
    if charter and loadout:
        return f"{CHARTER_NOTE} {LOADOUT_NOTE}"
    return LOADOUT_NOTE if loadout else CHARTER_NOTE


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
    output = run(event if isinstance(event, dict) else {}, runtime_root)
    if output:
        sys.stdout.write(json.dumps(output, ensure_ascii=False))
    return 0

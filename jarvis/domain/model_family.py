"""Les familles de modèles Claude : ce qu'un rôle de sous-agent règle vraiment sur le CLI Claude hôte.

L'outil `Agent` du CLI Claude ne prend pas un identifiant de catalogue (`claude-sonnet-4-5`) mais une
**famille** (`sonnet|opus|haiku|fable`), qu'il résout lui-même vers la version courante de cette famille
(constat de la Slice 08, CLI 2.1.309 ; décision du Human du 2026-10-24, HV-ARCH-007 : « Sonnet » veut dire la
version courante de Sonnet, aujourd'hui Sonnet 5.5). Proposer `claude-sonnet-4-5` comme choix distinct ferait
croire à l'utilisateur qu'il obtient Sonnet 4.5 : pour le CLI hôte, les candidats d'un rôle sont donc des
familles, une entrée par famille que le catalogue connaît.

La version courante n'est pas connue de façon fiable ici (elle dépend du CLI installé, pas du catalogue du
fournisseur) : le libellé dit « version courante du CLI », il n'invente pas de numéro.

Seul l'agent `claude` est concerné : un autre CLI (Codex…) garde ses identifiants tels quels, et un
identifiant Claude qui ne désigne aucune famille connue reste inchangé (rien n'est deviné). Aucune I/O ici.
Contrat : `docs/subagent-roles.md` § 10.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Iterable, Sequence

from jarvis.domain.routing import CandidateRef, ModelCandidate

#: L'agent dont l'outil `Agent` ne prend qu'une famille (`routing_hook.HOST_AGENT`).
CLAUDE_AGENT = "claude"
#: Valeurs que le paramètre `model` de l'outil `Agent` du CLI Claude accepte.
FAMILIES = ("sonnet", "opus", "haiku", "fable")
_FAMILY = re.compile(r"^claude-(?:[a-z0-9.\-]*-)?(sonnet|opus|haiku|fable)(?:-|$)")


def family_of(model: str) -> str | None:
    """La famille d'un identifiant Claude (`claude-haiku-4-5`, `claude-3-5-haiku-…`, `haiku`), sinon `None`."""
    value = str(model or "").strip().lower()
    if value in FAMILIES:
        return value
    match = _FAMILY.match(value)
    return match.group(1) if match else None


def family_label(family: str) -> str:
    """« Sonnet (version courante du CLI) » : la version n'est pas inventée, c'est le CLI qui la résout."""
    return f"{family.capitalize()} (version courante du CLI)"


def normalize_ref(ref: CandidateRef) -> CandidateRef:
    """Un candidat du CLI Claude désigné par un identifiant de famille devient cette famille ; le reste est rendu tel quel."""
    if ref.agent != CLAUDE_AGENT:
        return ref
    family = family_of(ref.model)
    return ref if family is None or family == ref.model else CandidateRef(agent=ref.agent, model=family)


def normalize_refs(refs: Iterable[CandidateRef]) -> tuple[CandidateRef, ...]:
    """`normalize_ref` sur une liste ordonnée, doublons retirés (le premier garde sa place)."""
    seen: set[CandidateRef] = set()
    out: list[CandidateRef] = []
    for ref in refs:
        normalized = normalize_ref(ref)
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return tuple(out)


def collapse_candidates(candidates: Sequence[ModelCandidate]) -> list[ModelCandidate]:
    """Les candidats, ceux du CLI Claude regroupés par famille : une entrée par famille, à la place du premier membre.

    Une famille est disponible si au moins un de ses identifiants l'est (le CLI choisit la version, pas nous) ;
    sinon elle garde la raison du premier. Idempotent : une entrée déjà nommée par sa famille est un membre.
    """
    out: list[ModelCandidate] = []
    index: dict[str, int] = {}
    for item in candidates:
        family = family_of(item.model) if item.agent == CLAUDE_AGENT else None
        if family is None:
            out.append(item)
            continue
        position = index.get(family)
        if position is None:
            label = family_label(family)
            index[family] = len(out)
            out.append(replace(item, model=family, model_label=label,
                               label=f"{item.agent_label or item.agent} · {label}"))
            continue
        current = out[position]
        if item.available and not current.available:
            out[position] = replace(current, available=True, unavailable_reason="",
                                    capabilities=item.capabilities or current.capabilities)
    return out

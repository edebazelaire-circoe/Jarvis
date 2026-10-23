"""Le routage par rôle : quels candidats servent un rôle de sous-agent, dans quel ordre.

Couche posée **au-dessus** de `routing` (profils, candidats, jugement) et du registre des rôles
(`subagent_roles`). Elle ne recopie ni l'un ni l'autre :

- un rôle est désigné par son id canonique, alias résolus (`reviewer` -> `qa`) par `subagent_roles` ;
- une liste de rôle est une suite ordonnée de `CandidateRef`, jugée par `routing.first_eligible` ;
- le repli réutilise la sémantique `allow_general_fallback` des profils : liste du rôle épuisée,
  la liste du profil `general` est tentée.

Migration non destructive (contrat : `docs/subagent-roles.md` § 10) : un rôle sans politique
explicite **hérite** de la politique par profil. Rien n'est écrit pour matérialiser cet héritage :
la politique par profil reste la seule vérité tant que l'utilisateur n'a pas choisi pour ce rôle.
Restaurer un rôle, c'est retirer sa politique explicite. Changer un rôle ne touche aucun autre rôle.

Le choix du modèle appartient à cette couche et au runtime ; il n'est jamais un champ de la
configuration d'un cerveau (le cerveau annonce un rôle, pas un modèle).

Aucune I/O ici : la persistance vit dans `jarvis.runtime.subagent_role_routing`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

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
from jarvis.domain.subagent_roles import ROLES, RoleStatus, SubagentRole, resolve_role, role_by_id

#: Provenance d'une liste de rôle : choisie pour ce rôle, ou héritée d'un profil.
PROVENANCE_EXPLICIT = "explicit"
PROVENANCE_INHERITED_PREFIX = "inherited:"
#: Rôle explicite sans aucun candidat utilisable, en mode Dupliqué : le hook laisse passer (le CLI garde
#: son modèle, comportement d'avant) au lieu de refuser, et le journalise sous ce motif.
REASON_ROLE_PASSTHROUGH = "role_passthrough"


def inherited(profile: str) -> str:
    return f"{PROVENANCE_INHERITED_PREFIX}{profile}"


@dataclass(frozen=True, slots=True)
class RolePolicy:
    """La politique explicite d'un rôle : l'ordre est la préférence, comme pour un profil."""

    role_id: str
    candidates: tuple[CandidateRef, ...]
    allow_general_fallback: bool = True

    def __post_init__(self) -> None:
        # Une liste explicite vide n'a pas de sens : revenir à l'héritage, c'est restaurer le rôle.
        if not self.candidates:
            raise RoutingError(
                "role_routing_empty_candidates",
                f"Le rôle « {self.role_id} » doit garder au moins un candidat ; restaurez-le pour hériter.",
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "candidates": [ref.as_dict() for ref in self.candidates],
            "allow_general_fallback": self.allow_general_fallback,
        }


@dataclass(frozen=True, slots=True)
class RoleRoutingDocument:
    """Toutes les politiques explicites de rôle, et la révision qui les date.

    `roles` ne contient **que** les rôles réglés explicitement : un rôle absent hérite.
    """

    revision: int = 0
    roles: Mapping[str, RolePolicy] = field(default_factory=dict)

    def for_role(self, role_id: str) -> RolePolicy | None:
        return self.roles.get(role_id)

    def refs(self) -> tuple[CandidateRef, ...]:
        return tuple(ref for entry in self.roles.values() for ref in entry.candidates)


EMPTY_DOCUMENT = RoleRoutingDocument()


@dataclass(frozen=True, slots=True)
class EffectiveRolePolicy:
    """Ce qui s'applique à un rôle quand il est annoncé avec son profil par défaut."""

    role_id: str
    provenance: str
    inherited_profile: str
    candidates: tuple[CandidateRef, ...]
    allow_general_fallback: bool
    #: Vrai si cette liste lie vraiment le hook aujourd'hui (voir `binding_state`).
    binding: bool
    binding_reason: str

    @property
    def explicit(self) -> bool:
        return self.provenance == PROVENANCE_EXPLICIT


def canonical_role(raw: object) -> SubagentRole:
    """Le rôle canonique désigné par un id ou un alias ; refus stable sinon.

    Un id inconnu n'est pas « général » : retomber en silence ferait régler un rôle qui n'existe pas.
    """
    resolution = resolve_role(raw)
    if resolution.status in (RoleStatus.DECLARED, RoleStatus.ALIAS):
        role = role_by_id(resolution.role_id)
        if role is not None and role.enabled:
            return role
    raise RoutingError("role_routing_unknown_role", f"Rôle de sous-agent inconnu : « {raw} ».")


def binding_state(
    role: SubagentRole, document: RoleRoutingDocument, profiles: RoutingPolicy,
) -> tuple[bool, str]:
    """La liste du rôle lie-t-elle le hook, et pourquoi (phrase affichable).

    Interaction avec `agent_routing.enabled` (Auto / Dupliqué, compatibilité) :

    - politique **explicite** de rôle : elle s'applique toujours, quel que soit l'interrupteur. C'est
      un choix délibéré fait pour ce rôle ; Dupliqué ne gouverne que les listes par profil ;
    - politique **héritée** : exactement le comportement par profil d'avant — liée seulement quand
      l'interrupteur est sur Auto et que le profil est actif et non vide.
    """
    if document.for_role(role.id) is not None:
        return True, "Politique du rôle appliquée à chaque lancement de ce rôle."
    entry = profiles.for_profile(role.default_profile)
    if not profiles.enabled:
        return False, "Héritée et inactive : le mode Dupliqué laisse le CLI choisir son modèle."
    if entry is None or not entry.enabled or not entry.candidates:
        return False, f"Héritée du profil « {role.default_profile} », qui n'impose aucun candidat."
    return True, f"Héritée du profil « {role.default_profile} »."


def effective_policy(
    role: SubagentRole, document: RoleRoutingDocument, profiles: RoutingPolicy,
) -> EffectiveRolePolicy:
    """La liste ordonnée d'un rôle : la sienne si elle existe, sinon celle de son `default_profile`."""
    binding, reason = binding_state(role, document, profiles)
    explicit = document.for_role(role.id)
    if explicit is not None:
        return EffectiveRolePolicy(
            role_id=role.id, provenance=PROVENANCE_EXPLICIT, inherited_profile=role.default_profile,
            candidates=explicit.candidates, allow_general_fallback=explicit.allow_general_fallback,
            binding=binding, binding_reason=reason,
        )
    entry = profiles.for_profile(role.default_profile)
    return EffectiveRolePolicy(
        role_id=role.id, provenance=inherited(role.default_profile), inherited_profile=role.default_profile,
        candidates=tuple(entry.candidates) if entry is not None else (),
        allow_general_fallback=entry.allow_general_fallback if entry is not None else True,
        binding=binding, binding_reason=reason,
    )


def effective_policies(document: RoleRoutingDocument, profiles: RoutingPolicy) -> list[EffectiveRolePolicy]:
    """Les sept rôles actifs, dans l'ordre du registre."""
    return [effective_policy(role, document, profiles) for role in ROLES if role.enabled]


def resolve_for_role(
    role: SubagentRole,
    announced_profile: str | None,
    document: RoleRoutingDocument,
    profiles: RoutingPolicy,
    candidates: list[ModelCandidate] | tuple[ModelCandidate, ...],
    *,
    source: str = "",
) -> RoutingDecision:
    """Choisir le candidat d'un rôle annoncé. Déterministe, sans I/O.

    Le profil de travail est celui que la description annonce, sinon le `default_profile` du rôle :
    c'est lui qui fixe les capacités exigées (`[code]` exige `code`), et, pour un rôle qui hérite,
    la liste appliquée. Un `[code] [qa]` documenté (`PROFILE_RULE`) garde donc exactement son routage
    d'avant tant que `qa` n'a pas de politique explicite.
    """
    profile = routing.profile_spec(announced_profile or role.default_profile).id
    explicit = document.for_role(role.id)
    if explicit is None:
        decision = routing.resolve(RoutingIntent(profile=profile, source=source), profiles, candidates)
        return replace(decision, role_id=role.id, provenance=inherited(profile))

    required = frozenset(routing.profile_spec(profile).requires)
    chosen, verdicts = routing.first_eligible(explicit.candidates, candidates, required)
    if chosen is not None:
        preferred = chosen == explicit.candidates[0]
        return RoutingDecision(
            profile=profile, agent=chosen.agent, model=chosen.model,
            reason=routing.REASON_PREFERRED if preferred else routing.REASON_FALLBACK,
            considered=verdicts,
            fallback_from=None if preferred else explicit.candidates[0],
            fallback_code="" if preferred else verdicts[0].code,
            source=source, role_id=role.id, provenance=PROVENANCE_EXPLICIT,
        )
    all_verdicts = list(verdicts)
    if explicit.allow_general_fallback:
        # Repli = la liste du profil général, comme pour un profil. L'interrupteur Auto/Dupliqué ne
        # l'éteint pas : le repli a été demandé pour ce rôle, explicitement.
        general = profiles.for_profile(routing.GENERAL_PROFILE)
        if general is not None and general.enabled and general.candidates:
            chosen, more = routing.first_eligible(general.candidates, candidates, required)
            all_verdicts.extend(more)
            if chosen is not None:
                return RoutingDecision(
                    profile=profile, agent=chosen.agent, model=chosen.model,
                    reason=routing.REASON_GENERAL_FALLBACK, considered=tuple(all_verdicts),
                    fallback_from=explicit.candidates[0], fallback_code=verdicts[0].code if verdicts else "",
                    source=source, role_id=role.id, provenance=PROVENANCE_EXPLICIT,
                )
    if not profiles.enabled:
        # Dupliqué : un catalogue périmé (tous les candidats Claude dits indisponibles) ne doit pas
        # bloquer les lancements de ce rôle. Le CLI garde la main, comme avant la couche par rôle ; la
        # décision porte les verdicts pour la trace. En Auto, le refus des profils est conservé.
        return RoutingDecision(
            profile=profile, agent="", model=routing.DEFAULT_MODEL, reason=REASON_ROLE_PASSTHROUGH,
            considered=tuple(all_verdicts), fallback_from=explicit.candidates[0],
            fallback_code=verdicts[0].code if verdicts else "", source=source,
            role_id=role.id, provenance=PROVENANCE_EXPLICIT,
        )
    raise NoEligibleCandidateError(
        f"Aucun candidat autorisé n'est utilisable pour le rôle « {role.name} ».", tuple(all_verdicts),
    )

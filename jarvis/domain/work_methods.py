"""Les Work Methods : façons de travailler d'un rôle, heuristiques et non workflow.

Une Work Method dit **comment bien travailler** — principes, réflexes de
qualité, relations utiles à envisager — jamais **dans quel ordre** : elle ne
porte ni étape, ni séquence, ni graphe (décision D06 du handoff
jarvis-organic-agent-orchestration). Le Mission Owner reste seul juge de
l'organisation pendant l'exécution (D05).

Ce module fixe le contrat (Slice 01) :

- `WorkMethod` : définition versionnée, bornée, figée ;
- `MethodProvenance` : d'où vient une version (`builtin`, `user`, ou
  `promoted` depuis un candidat, D24 : promotion explicite, jamais silencieuse) ;
- `check_revision` : une nouvelle version n'écrase jamais l'ancienne en douce ;
- `check_role_methods` : les rôles ne citent que des méthodes qui existent et
  qui s'appliquent à eux.

Le catalogue des méthodes livrées (Slice 04) est `BUILTIN_METHODS`, rendu sur
une consigne par `render_method` ; les candidats appris et leur promotion sont dans
`work_method_learning` (Slice 12). Contrat : `docs/work-methods.md`. Module pur, sans E/S.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import re
from typing import Any

from jarvis.domain._checks import ROLE_ID as _ROLE_ID
from jarvis.domain._checks import check_aware, parse_dt, parse_enum, preview, recode, strict_keys
from jarvis.domain._checks import check_id as _check_id
from jarvis.domain._checks import check_text as _check_text
from jarvis.domain.agent_relations import RELATION_KINDS

#: Identifiant d'une méthode : minuscules ASCII, chiffres et tirets, 2 à 48 caractères.
METHOD_ID = re.compile(r"[a-z][a-z0-9-]{1,47}\Z")
MAX_METHOD_NAME_CHARS = 80
MAX_METHOD_SUMMARY_CHARS = 300
MAX_HEURISTIC_CHARS = 300
MAX_PRINCIPLES = 12
MAX_QUALITY_CHECKS = 12
MAX_METHOD_ROLES = 16
MAX_EVIDENCE_REFS = 16
MAX_METHOD_VERSION = 9999
#: Un id de rôle cité par une méthode : le motif partagé `_checks.ROLE_ID` (celui de `subagent_roles._MARKER`).
ROLE_ID = _ROLE_ID

#: Les types de relation qu'une méthode peut suggérer (D09) : le vocabulaire canonique des relations
#: (`agent_relations.AgentRelationKind`), importé, jamais redéfini ici.
USEFUL_RELATION_KINDS: tuple[str, ...] = RELATION_KINDS

#: Clés refusées avec un message explicite : une méthode n'est pas un plan d'exécution (D06).
FORBIDDEN_PLAN_KEYS = frozenset({"steps", "sequence", "order", "graph", "dag", "nodes", "edges", "workflow", "plan"})


#: Seule personne qui promeut aujourd'hui : l'utilisateur du Control Center (Slice 12). Un rôle d'agent n'est jamais un
#: promoteur valable ; une version promue par un autre nom n'est ni publiée ni apposée.
HUMAN_PROMOTERS = frozenset({"user"})


class MethodError(ValueError):
    """Méthode invalide, refusée avec un code stable."""

    def __init__(self, message: str, *, code: str = "work_method_invalid") -> None:
        super().__init__(message)
        self.code = code


def _fail(message: str) -> MethodError:
    return MethodError(message)


def _coded_id(name: str, value: object, *, required: bool) -> None:
    recode(_fail, _check_id, name, value, required=required)


def _coded_text(name: str, value: object, limit: int) -> None:
    recode(_fail, _check_text, name, value, limit)


def is_method_id(value: object) -> bool:
    return isinstance(value, str) and bool(METHOD_ID.fullmatch(value))


#: Référence exacte d'une version, `<method_id>@<version>` (`WorkMethod.key`).
METHOD_KEY = re.compile(r"(?P<id>[a-z][a-z0-9-]{1,47})@(?P<version>[1-9][0-9]{0,3})\Z")


def parse_method_key(value: object) -> tuple[str, int] | None:
    """`(method_id, version)` d'une clé `<id>@<version>`, ou `None` si la valeur n'en est pas une."""

    match = METHOD_KEY.fullmatch(value) if isinstance(value, str) else None
    return (match["id"], int(match["version"])) if match else None


class MethodOrigin(StrEnum):
    BUILTIN = "builtin"
    USER = "user"
    PROMOTED = "promoted"


@dataclass(frozen=True, slots=True)
class MethodProvenance:
    """D'où vient une version de méthode.

    `promoted` exige le candidat d'origine, qui l'a promu (`promoted_by`, une personne ou un rôle explicite,
    jamais vide) et quand : la promotion est un acte, pas un effet de bord (D24). Les preuves (`evidence_refs`)
    sont des références bornées (ids de mission, de relation QA, d'artefact), pas du texte de raisonnement.
    """

    origin: MethodOrigin = MethodOrigin.BUILTIN
    candidate_id: str | None = None
    promoted_by: str | None = None
    promoted_at: datetime | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.origin, MethodOrigin):
            raise _fail("origin must be a MethodOrigin")
        if not isinstance(self.evidence_refs, tuple) or len(self.evidence_refs) > MAX_EVIDENCE_REFS:
            raise _fail(f"evidence_refs must be a tuple of at most {MAX_EVIDENCE_REFS} references")
        for ref in self.evidence_refs:
            _coded_id("evidence_refs[]", ref, required=True)
        promoted = (self.candidate_id, self.promoted_by, self.promoted_at)
        if self.origin is MethodOrigin.PROMOTED:
            _coded_id("candidate_id", self.candidate_id, required=True)
            _coded_id("promoted_by", self.promoted_by, required=True)
            check_aware(_fail, "promoted_at", self.promoted_at)
        elif any(item is not None for item in promoted) or self.evidence_refs:
            raise _fail("candidate_id, promoted_by, promoted_at and evidence_refs belong to a promoted method only")

    def to_payload(self) -> dict[str, Any]:
        return {
            "origin": self.origin.value,
            "candidate_id": self.candidate_id,
            "promoted_by": self.promoted_by,
            "promoted_at": self.promoted_at.isoformat() if self.promoted_at else None,
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_payload(cls, payload: object) -> MethodProvenance:
        data = strict_keys(_fail, "provenance", payload, _PROVENANCE_KEYS, required=frozenset({"origin"}))
        refs = data.get("evidence_refs") or []
        if not isinstance(refs, list):
            raise _fail("evidence_refs must be a list")
        return cls(
            origin=parse_enum(_fail, "origin", data["origin"], MethodOrigin),
            candidate_id=data.get("candidate_id"),
            promoted_by=data.get("promoted_by"),
            promoted_at=parse_dt(_fail, "promoted_at", data.get("promoted_at"), required=False),
            evidence_refs=tuple(refs),
        )


_PROVENANCE_KEYS = frozenset({"origin", "candidate_id", "promoted_by", "promoted_at", "evidence_refs"})


def _heuristics(name: str, values: object, limit: int, *, required: bool) -> None:
    if not isinstance(values, tuple):
        raise _fail(f"{name} must be a tuple")
    if required and not values:
        raise _fail(f"{name} needs at least one entry")
    if len(values) > limit:
        raise _fail(f"{name} holds at most {limit} entries")
    for value in values:
        _coded_text(f"{name}[]", value, MAX_HEURISTIC_CHARS)
        if not str(value).strip():
            raise _fail(f"{name} entries cannot be blank")
    if len(set(values)) != len(values):
        raise _fail(f"{name} entries must be unique")


@dataclass(frozen=True, slots=True)
class WorkMethod:
    """Une version de méthode de travail. Aucun champ n'ordonne le travail : `principles` et `quality_checks`
    sont des ensembles de réflexes, `useful_relations` des relations à envisager quand elles servent."""

    method_id: str
    version: int
    name: str
    summary: str
    role_ids: tuple[str, ...]
    principles: tuple[str, ...]
    quality_checks: tuple[str, ...] = ()
    useful_relations: tuple[str, ...] = ()
    provenance: MethodProvenance = field(default_factory=MethodProvenance)

    def __post_init__(self) -> None:
        if not is_method_id(self.method_id):
            raise _fail(f"method_id must match {METHOD_ID.pattern}, got {preview(self.method_id)}")
        if type(self.version) is not int or not 1 <= self.version <= MAX_METHOD_VERSION:
            raise _fail(f"version must be an integer between 1 and {MAX_METHOD_VERSION}")
        for name, limit in (("name", MAX_METHOD_NAME_CHARS), ("summary", MAX_METHOD_SUMMARY_CHARS)):
            _coded_text(name, getattr(self, name), limit)
            if not getattr(self, name).strip():
                raise _fail(f"{name} is required")
        if not isinstance(self.role_ids, tuple) or not self.role_ids or len(self.role_ids) > MAX_METHOD_ROLES:
            raise _fail(f"role_ids must be a non-empty tuple of at most {MAX_METHOD_ROLES} role ids")
        for role_id in self.role_ids:
            if not isinstance(role_id, str) or not ROLE_ID.fullmatch(role_id):
                raise _fail(f"role_ids[] must be a role id, got {preview(role_id)}")
        if len(set(self.role_ids)) != len(self.role_ids):
            raise _fail("role_ids must be unique")
        _heuristics("principles", self.principles, MAX_PRINCIPLES, required=True)
        _heuristics("quality_checks", self.quality_checks, MAX_QUALITY_CHECKS, required=False)
        if not isinstance(self.useful_relations, tuple):
            raise _fail("useful_relations must be a tuple")
        for kind in self.useful_relations:
            if kind not in USEFUL_RELATION_KINDS:
                raise _fail(f"useful_relations[] must be one of {list(USEFUL_RELATION_KINDS)}, got {preview(kind)}")
        if len(set(self.useful_relations)) != len(self.useful_relations):
            raise _fail("useful_relations must be unique")
        if not isinstance(self.provenance, MethodProvenance):
            raise _fail("provenance must be a MethodProvenance")

    @property
    def key(self) -> str:
        """`<method_id>@<version>` : la référence exacte d'une version."""

        return f"{self.method_id}@{self.version}"

    def applies_to(self, role_id: str) -> bool:
        return role_id in self.role_ids

    def to_payload(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "version": self.version,
            "name": self.name,
            "summary": self.summary,
            "role_ids": list(self.role_ids),
            "principles": list(self.principles),
            "quality_checks": list(self.quality_checks),
            "useful_relations": list(self.useful_relations),
            "provenance": self.provenance.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: object) -> WorkMethod:
        """Décodage strict : aucune clé inconnue, et une clé de plan nommée comme telle."""

        if isinstance(payload, dict):
            plan = sorted(FORBIDDEN_PLAN_KEYS & payload.keys())
            if plan:
                raise MethodError(
                    f"a Work Method is heuristic, not a workflow: {plan} is not allowed", code="work_method_is_not_a_plan",
                )
        data = strict_keys(_fail, "work method", payload, _METHOD_KEYS, required=_METHOD_REQUIRED)

        def strings(key: str) -> tuple[str, ...]:
            value = data.get(key) or []
            if not isinstance(value, list):
                raise _fail(f"{key} must be a list")
            return tuple(value)

        provenance = data.get("provenance")
        return cls(
            method_id=data["method_id"],
            version=data["version"],
            name=data["name"],
            summary=data["summary"],
            role_ids=strings("role_ids"),
            principles=strings("principles"),
            quality_checks=strings("quality_checks"),
            useful_relations=strings("useful_relations"),
            provenance=MethodProvenance() if provenance is None else MethodProvenance.from_payload(provenance),
        )


_METHOD_KEYS = frozenset({
    "method_id", "version", "name", "summary", "role_ids", "principles", "quality_checks", "useful_relations",
    "provenance",
})
_METHOD_REQUIRED = frozenset({"method_id", "version", "name", "summary", "role_ids", "principles"})


def check_revision(previous: WorkMethod, candidate: WorkMethod) -> None:
    """Refuse qu'une version en remplace une autre en silence.

    Même clé `id@version` : le contenu doit être identique (republier n'est pas réécrire). Sinon la nouvelle
    version suit exactement la précédente, pour la même méthode.
    """

    if candidate.method_id != previous.method_id:
        raise MethodError("a revision keeps the method_id", code="work_method_revision_invalid")
    if candidate.version == previous.version:
        if candidate != previous:
            raise MethodError(
                f"{previous.key} already exists with other content: publish version {previous.version + 1}",
                code="work_method_version_conflict",
            )
        return
    if candidate.version != previous.version + 1:
        raise MethodError(
            f"next version of {previous.method_id} is {previous.version + 1}, got {candidate.version}",
            code="work_method_revision_invalid",
        )


def latest_methods(methods: Iterable[WorkMethod]) -> Mapping[str, WorkMethod]:
    """La dernière version de chaque méthode ; deux contenus pour une même clé `id@version` sont refusés."""

    by_key: dict[str, WorkMethod] = {}
    latest: dict[str, WorkMethod] = {}
    for method in methods:
        known = by_key.get(method.key)
        if known is not None and known != method:
            raise MethodError(f"{method.key} is defined twice with different content", code="work_method_version_conflict")
        by_key[method.key] = method
        if method.method_id not in latest or latest[method.method_id].version < method.version:
            latest[method.method_id] = method
    return latest


def check_role_methods(
    roles: Iterable[Any], methods: Iterable[WorkMethod],
) -> None:
    """Chaque rôle (`subagent_roles.SubagentRole`) ne cite que des méthodes existantes qui s'appliquent à lui."""

    latest = latest_methods(methods)
    for role in roles:
        for method_id in role.work_methods:
            method = latest.get(method_id)
            if method is None:
                raise MethodError(f"role {role.id} cites unknown work method {method_id!r}", code="work_method_unknown")
            if not method.applies_to(role.id):
                raise MethodError(
                    f"work method {method_id!r} does not apply to role {role.id}", code="work_method_not_applicable",
                )


# ------------------------------------------------------------- catalogue livré (Slice 04)

#: Libellés français des relations, pour le texte apposé sur la consigne d'un agent.
RELATION_LABELS: Mapping[str, str] = {
    "delegation": "délégation",
    "communication": "échange entre agents",
    "adversary": "confrontation",
    "qa": "contrôle qualité",
    "handoff": "relais",
}
if set(RELATION_LABELS) != set(USEFUL_RELATION_KINDS):
    raise ValueError("RELATION_LABELS must name every relation kind")

#: Les méthodes livrées avec JARVIS. Des réflexes, jamais des étapes : chaque entrée se lit seule, dans n'importe
#: quel ordre (D06). Les rôles qui les citent sont vérifiés par `subagent_roles` au chargement.
BUILTIN_METHODS: tuple[WorkMethod, ...] = (
    WorkMethod(
        method_id="quick-research",
        version=1,
        name="Recherche rapide",
        summary="Répondre vite à une question ciblée avec une ou deux sources sûres, sans élargir le sujet.",
        role_ids=("research", "web-research", "research-lead"),
        principles=(
            "Viser la source la plus directe : la documentation officielle, le fichier, la page qui fait foi.",
            "S'arrêter dès que la réponse est sourcée et sans contradiction visible.",
            "Dire ce qui n'a pas été vérifié plutôt que de le combler.",
        ),
        quality_checks=(
            "La réponse cite sa source.",
            "Une limite ou un doute est dit, pas tu.",
        ),
    ),
    WorkMethod(
        method_id="deep-research",
        version=1,
        name="Recherche approfondie",
        summary="Faire le tour d'un sujet large jusqu'à une synthèse qui tient, en jugeant quand les preuves suffisent.",
        role_ids=("research-lead", "research", "web-research"),
        principles=(
            "Juger l'ampleur de la question : quels angles et quelles sources changeraient la réponse.",
            "Préférer les sources primaires, récentes et indépendantes de celui qui vend.",
            "Chercher activement ce qui contredit la première réponse trouvée.",
            "Répartir les angles entre plusieurs agents quand ils sont vraiment indépendants.",
            "Arrêter quand une source de plus ne change plus la conclusion.",
        ),
        quality_checks=(
            "Chaque affirmation de la synthèse a sa source.",
            "Les contradictions entre sources sont exposées, pas tranchées en silence.",
            "Ce qui reste incertain est dit.",
        ),
        useful_relations=("delegation", "qa"),
    ),
    WorkMethod(
        method_id="comparative-research",
        version=1,
        name="Recherche comparative",
        summary="Comparer des options sur des critères explicites et dire laquelle convient à quel usage.",
        role_ids=("research-lead", "web-research", "research"),
        principles=(
            "Rendre les critères explicites avant de juger, et les mêmes pour chaque option.",
            "Croiser caractéristiques, avis indépendants, prix et retours dans la durée.",
            "Faire défendre une option contre une autre quand l'écart est mince.",
            "Dire quand des usages différents donnent des gagnants différents.",
        ),
        quality_checks=(
            "Chaque option est jugée sur les mêmes critères.",
            "La recommandation dit pour qui et pourquoi, avec ses limites.",
        ),
        useful_relations=("delegation", "adversary", "qa"),
    ),
    WorkMethod(
        method_id="bug-investigation",
        version=1,
        name="Enquête sur un bug",
        summary="Trouver la cause réelle d'un défaut avant de le corriger, et prouver la correction.",
        role_ids=("coder", "qa"),
        principles=(
            "Reproduire le défaut avant de chercher sa cause.",
            "Lire la trace et le journal réels plutôt que deviner.",
            "Distinguer la cause du symptôme : un correctif qui masque le symptôme n'en est pas un.",
            "Écrire le test qui échoue avant le correctif et passe après.",
            "Chercher les autres endroits où la même cause produit le même défaut.",
        ),
        quality_checks=(
            "La cause est nommée avec sa preuve (fichier, ligne, sortie).",
            "Un test échoue sans le correctif et passe avec.",
        ),
        useful_relations=("qa",),
    ),
    WorkMethod(
        method_id="result-review",
        version=1,
        name="Revue d'un résultat",
        summary="Dire si le résultat d'un autre agent tient, preuves à l'appui, sans refaire son travail.",
        role_ids=("qa",),
        principles=(
            "Partir de la demande d'origine et de ses critères de réussite, pas du résultat.",
            "Vérifier par soi-même : relancer, ouvrir les sources, relire le changement.",
            "Séparer le bloquant du souhaitable.",
            "Un doute non vérifié se dit doute, jamais défaut.",
        ),
        quality_checks=(
            "Chaque constat porte sa preuve.",
            "Le verdict est l'un de : tient, à corriger, ne tient pas.",
        ),
    ),
)

_BUILTIN = latest_methods(BUILTIN_METHODS)
if len(_BUILTIN) != len(BUILTIN_METHODS):
    raise ValueError("builtin work methods must have distinct ids")


def builtin_method(method_id: object) -> WorkMethod | None:
    """La méthode livrée de cet id, ou `None`."""

    return _BUILTIN.get(str(method_id or ""))


def promotion_refusal(method: WorkMethod) -> str | None:
    """Pourquoi une version ne peut pas être apposée comme version promue (Slice 12, reprise QA R-1), ou `None`.

    Gardes de vérité de la clé déclarée : une version qui se dit promue doit l'avoir été par une personne
    (`HUMAN_PROMOTERS`) et suivre strictement la version livrée de la même méthode ; sinon un instantané forgé
    `@1` remplacerait le texte livré alors que le fait déclarerait toujours `@1`.
    """

    provenance = method.provenance
    if provenance.origin is not MethodOrigin.PROMOTED:
        return "work_method_not_promoted"
    if provenance.promoted_by not in HUMAN_PROMOTERS:
        return "work_method_promoter_not_human"
    builtin = builtin_method(method.method_id)
    if builtin is not None and method.version <= builtin.version:
        return "work_method_version_not_after_builtin"
    return None


def render_method(method: WorkMethod) -> str:
    """Le texte d'une méthode tel qu'il est apposé sur une consigne : des réflexes, explicitement pas un plan."""

    lines = [
        f"MÉTHODE DE TRAVAIL : {method.name} ({method.key})",
        f"{method.summary} Ce sont des réflexes, pas des étapes : vous organisez le travail selon ce que vous "
        "découvrez.",
        "Principes :",
        *(f"- {item}" for item in method.principles),
    ]
    if method.quality_checks:
        lines += ["Critères de qualité :", *(f"- {item}" for item in method.quality_checks)]
    if method.useful_relations:
        labels = ", ".join(RELATION_LABELS[kind] for kind in method.useful_relations)
        lines.append(f"Relations à envisager quand elles servent : {labels}.")
    return "\n".join(lines)

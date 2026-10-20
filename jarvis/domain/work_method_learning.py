"""Candidats de Work Method appris de l'historique, et leur promotion explicite (Slice 12, D06, D24).

Une façon de travailler adaptée en cours de mission peut devenir **candidate** à
la réutilisation quand elle **revient** et que ses issues sont **bonnes**. Elle
ne devient une Work Method qu'à la **promotion**, un acte d'une personne : rien
n'est promu, appliqué ni modifié en silence, aucun agent ne promeut.

Ce module, pur et sans E/S, fixe :

- `MethodUse` : un usage observé, lu dans l'historique durable des missions
  (`mission_history.MissionTree`) seulement — mission close, rôle et Work Method
  de son premier Mission Owner (`AgentDeclarationFact.work_method`), natures
  des relations réellement nouées et closes, verdict QA. Jamais Conversation
  Events, jamais le raisonnement d'un agent, jamais Work State (vivant, non
  durable) ;
- `ApproachSignature` : la clé de répétition. Elle décrit une **approche**
  (rôle, méthode apposée, ensemble des natures de relation employées), jamais
  une topologie : pas d'ordre, pas de nombre d'agents, pas d'arête ;
- `rate_use` : la qualité d'un usage, sur preuve explicite seulement. Une
  mission terminée sans verdict reste « non notée » : le silence n'est jamais
  une approbation ;
- `CandidateThresholds` / `DEFAULT_THRESHOLDS` : les seuils, des données
  documentées (`docs/work-methods.md` › *Candidats*) ;
- `detect_candidates` : l'agrégation des usages en candidats, avec leur statut
  et la raison de ce statut ;
- `promoted_method` : la version que produit une promotion, vérifiée contre le
  schéma (`WorkMethod.from_payload`, clés de plan refusées), la révision
  (`check_revision`) et la provenance (`MethodProvenance` `promoted`).

Les candidats ne sont pas persistés : ils se recalculent depuis l'historique,
seule source, et la promotion les recalcule avant d'écrire.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import hashlib
from typing import Any

from jarvis.domain.agent_relations import RELATION_KINDS, AgentRelation, AgentRelationKind, RelationOutcome, RelationStatus
from jarvis.domain.mission_history import MissionTree, StoredInstance
from jarvis.domain.missions import Mission, MissionStatus
from jarvis.domain.work_methods import HUMAN_PROMOTERS as _HUMAN_PROMOTERS
from jarvis.domain.work_methods import (
    FORBIDDEN_PLAN_KEYS, MAX_EVIDENCE_REFS, MethodError, MethodOrigin, MethodProvenance, WorkMethod,
    check_revision, parse_method_key,
)

#: `work_methods.HUMAN_PROMOTERS`, réexporté : un rôle d'agent n'est jamais un promoteur (`work_method_promoter_not_human`).
HUMAN_PROMOTERS = _HUMAN_PROMOTERS
#: Préfixe des ids de candidat, dérivés de leur signature (stables d'une lecture à l'autre).
CANDIDATE_PREFIX = "wmc-"


class QualityRating(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    UNRATED = "unrated"


class CandidateStatus(StrEnum):
    #: Seuils atteints : la promotion est possible (par une personne).
    CANDIDATE = "candidate"
    #: L'approche revient, mais pas encore assez, ou sans assez de preuves de qualité.
    OBSERVING = "observing"
    #: L'approche revient avec de mauvaises issues : jamais proposée.
    INSUFFICIENT_QUALITY = "insufficient_quality"
    #: L'approche est déjà exactement celle de la méthode apposée : rien à apprendre.
    MATCHES_METHOD = "matches_method"
    #: Une version promue cite déjà ce candidat.
    PROMOTED = "promoted"


@dataclass(frozen=True, slots=True)
class CandidateThresholds:
    """Les seuils d'un candidat. Des données, pas de la magie : lisibles par la route et documentées.

    - `min_uses` : missions closes de même signature (une réussite isolée ne suffit jamais) ;
    - `min_positive` : parmi elles, celles dont la qualité est prouvée bonne ;
    - `min_positive_share` : part des usages notés (bons + mauvais) qui sont bons ;
    - `scan_root_missions` : fenêtre de lecture, en missions racines les plus récentes.
    """

    min_uses: int = 3
    min_positive: int = 2
    min_positive_share: float = 0.75
    scan_root_missions: int = 64

    def __post_init__(self) -> None:
        if type(self.min_uses) is not int or self.min_uses < 2:
            raise ValueError("min_uses must be an integer of at least 2: one run is never enough")
        if type(self.min_positive) is not int or not 1 <= self.min_positive <= self.min_uses:
            raise ValueError("min_positive must be an integer between 1 and min_uses")
        if not isinstance(self.min_positive_share, float) or not 0.5 < self.min_positive_share <= 1.0:
            raise ValueError("min_positive_share must be a float in ]0.5, 1]")
        if type(self.scan_root_missions) is not int or not 1 <= self.scan_root_missions <= 200:
            raise ValueError("scan_root_missions must be an integer between 1 and 200")

    def to_payload(self) -> dict[str, Any]:
        return {"min_uses": self.min_uses, "min_positive": self.min_positive,
                "min_positive_share": self.min_positive_share, "scan_root_missions": self.scan_root_missions}


DEFAULT_THRESHOLDS = CandidateThresholds()

#: Verdicts QA qui notent un usage ; `findings` (constats sans verdict d'adéquation) ne note pas.
_QA_POSITIVE = frozenset({RelationOutcome.APPROVED})
_QA_NEGATIVE = frozenset({RelationOutcome.REJECTED, RelationOutcome.CORRECTION_REQUESTED})


@dataclass(frozen=True, slots=True)
class ApproachSignature:
    """La clé de répétition : rôle du Mission Owner, méthode apposée (id, sans version), natures employées."""

    role_id: str
    method_id: str | None
    relation_kinds: tuple[str, ...]

    @property
    def candidate_id(self) -> str:
        text = f"{self.role_id}|{self.method_id or '-'}|{','.join(self.relation_kinds)}"
        return CANDIDATE_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def to_payload(self) -> dict[str, Any]:
        return {"role_id": self.role_id, "method_id": self.method_id, "relation_kinds": list(self.relation_kinds)}


@dataclass(frozen=True, slots=True)
class MethodUse:
    """Un usage : une mission close, son premier Mission Owner, son approche et sa qualité prouvée (ou non)."""

    mission_id: str
    owner_instance_id: str
    signature: ApproachSignature
    method_key: str | None
    method_chosen: bool
    mission_status: MissionStatus
    closed_at: datetime
    rating: QualityRating
    rating_reason: str
    #: Les ids qui prouvent la note : la relation QA du verdict retenu (jamais un texte).
    quality_refs: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "owner_instance_id": self.owner_instance_id,
                "method_key": self.method_key, "method_chosen": self.method_chosen,
                "mission_status": self.mission_status.value, "closed_at": self.closed_at.isoformat(),
                "rating": self.rating.value, "rating_reason": self.rating_reason,
                "quality_refs": list(self.quality_refs)}


def _ordered_kinds(kinds: Iterable[str]) -> tuple[str, ...]:
    present = set(kinds)
    return tuple(kind for kind in RELATION_KINDS if kind in present)


def used_relation_kinds(relations: Iterable[AgentRelation]) -> tuple[str, ...]:
    """Les natures réellement employées : relations closes, sauf retirées (un lien retiré n'a rien produit)."""

    return _ordered_kinds(
        relation.kind.value for relation in relations
        if relation.status is RelationStatus.CLOSED and relation.outcome is not RelationOutcome.WITHDRAWN
    )


def rate_use(mission: Mission, relations: Sequence[AgentRelation]) -> tuple[QualityRating, str, tuple[str, ...]]:
    """La qualité d'une mission close, sur preuve explicite seulement.

    - mission `failed` / `cancelled` -> mauvaise ;
    - sinon le **dernier** verdict QA de la mission (par date de clôture) : `approved` -> bonne,
      `rejected` / `correction_requested` -> mauvaise, `findings` seul -> non notée ;
    - terminée sans verdict -> non notée (`no_quality_evidence`) : aucune approbation déduite du silence.
    """

    if mission.status is MissionStatus.FAILED:
        return QualityRating.NEGATIVE, "mission_failed", ()
    if mission.status is MissionStatus.CANCELLED:
        return QualityRating.NEGATIVE, "mission_cancelled", ()
    verdicts = sorted(
        (relation for relation in relations
         if relation.kind is AgentRelationKind.QA and relation.mission_id == mission.mission_id
         and relation.status is RelationStatus.CLOSED and relation.outcome is not RelationOutcome.WITHDRAWN),
        key=lambda relation: (relation.closed_at, relation.relation_id),
    )
    if not verdicts:
        return QualityRating.UNRATED, "no_quality_evidence", ()
    last = verdicts[-1]
    if last.outcome in _QA_POSITIVE:
        return QualityRating.POSITIVE, "qa_approved", (last.relation_id,)
    if last.outcome in _QA_NEGATIVE:
        return QualityRating.NEGATIVE, f"qa_{last.outcome.value}", (last.relation_id,)
    return QualityRating.UNRATED, f"qa_{last.outcome.value}", (last.relation_id,)


@dataclass(slots=True)
class ScanReport:
    """Ce qu'une lecture a vu : missions lues, usages retenus, missions écartées par raison."""

    root_missions: int = 0
    missions: int = 0
    uses: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    truncated: bool = False
    #: Vrai quand une partie de l'historique n'a pas pu être lue (ligne illisible) : le reste est rendu.
    partial: bool = False

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def to_payload(self) -> dict[str, Any]:
        return {"root_missions": self.root_missions, "missions": self.missions, "uses": self.uses,
                "skipped": dict(sorted(self.skipped.items())), "truncated": self.truncated, "partial": self.partial}


def uses_from_tree(tree: MissionTree, report: ScanReport | None = None) -> tuple[MethodUse, ...]:
    """Les usages d'un arbre de missions : une par mission close dont le premier propriétaire est connu.

    Écartées, comptées par raison : mission ouverte (`mission_open`), propriétaire ou déclaration absents
    (`owner_unknown`, `declaration_missing`). Un Mission Owner a toujours un rôle déclaré qui peut posséder une
    mission (`missions.AgentInstance`) : aucun rôle réservé n'arrive ici.
    """

    report = report if report is not None else ScanReport()
    report.truncated = report.truncated or tree.truncated
    instances: dict[str, StoredInstance] = {stored.instance.instance_id: stored for stored in tree.instances}
    first_owner: dict[str, str] = {}
    for change in tree.ownership:
        first_owner.setdefault(change.mission_id, change.owner_instance_id)
    relations_of: dict[str, list[AgentRelation]] = {}
    for relation in tree.relations:
        relations_of.setdefault(relation.mission_id, []).append(relation)
    uses: list[MethodUse] = []
    for mission in tree.missions:
        report.missions += 1
        if not mission.status.is_closed or mission.closed_at is None:
            report.skip("mission_open")
            continue
        owner = instances.get(first_owner.get(mission.mission_id, mission.owner_instance_id))
        if owner is None:
            report.skip("owner_unknown")
            continue
        fact = owner.declaration
        if fact is None:
            report.skip("declaration_missing")
            continue
        parsed = parse_method_key(fact.work_method)
        relations = relations_of.get(mission.mission_id, [])
        rating, reason, refs = rate_use(mission, relations)
        uses.append(MethodUse(
            mission_id=mission.mission_id, owner_instance_id=owner.instance.instance_id,
            signature=ApproachSignature(owner.instance.role_id, parsed[0] if parsed else None,
                                        used_relation_kinds(relations)),
            method_key=fact.work_method, method_chosen=fact.work_method_chosen, mission_status=mission.status,
            closed_at=mission.closed_at, rating=rating, rating_reason=reason, quality_refs=refs,
        ))
    report.uses += len(uses)
    return tuple(uses)


@dataclass(frozen=True, slots=True)
class MethodCandidate:
    """Une approche qui revient, avec ses comptes, son statut, ses preuves et le brouillon qu'elle propose."""

    signature: ApproachSignature
    status: CandidateStatus
    reason: str
    uses: int
    positive: int
    negative: int
    unrated: int
    chosen: int
    first_seen: datetime
    last_seen: datetime
    #: Missions bonnes et leurs relations QA approbatrices, bornées (`MAX_EVIDENCE_REFS`) : la provenance promue.
    evidence_refs: tuple[str, ...]
    #: La version que la promotion publierait sans retouche (`WorkMethod.to_payload` sans provenance), ou
    #: `None` sans méthode de base : la personne écrit alors nom, résumé et principes.
    draft: Mapping[str, Any] | None
    base_method_key: str | None
    #: Les versions promues qui citent ce candidat.
    promoted_keys: tuple[str, ...] = ()

    @property
    def candidate_id(self) -> str:
        return self.signature.candidate_id

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, **self.signature.to_payload(), "status": self.status.value,
            "reason": self.reason, "uses": self.uses, "positive": self.positive, "negative": self.negative,
            "unrated": self.unrated, "chosen": self.chosen, "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(), "evidence_refs": list(self.evidence_refs),
            "base_method_key": self.base_method_key, "draft": dict(self.draft) if self.draft is not None else None,
            "promoted_keys": list(self.promoted_keys),
        }


def _draft(signature: ApproachSignature, base: WorkMethod | None) -> dict[str, Any] | None:
    if base is None:
        return None
    payload = base.to_payload()
    payload.pop("provenance")
    payload["version"] = base.version + 1
    payload["useful_relations"] = list(_ordered_kinds((*base.useful_relations, *signature.relation_kinds)))
    if signature.role_id not in base.role_ids:
        payload["role_ids"] = [*base.role_ids, signature.role_id]
    return payload


def _status(uses: int, positive: int, negative: int, thresholds: CandidateThresholds) -> tuple[CandidateStatus, str]:
    if uses < thresholds.min_uses:
        return CandidateStatus.OBSERVING, "not_enough_uses"
    rated = positive + negative
    if rated and positive / rated < thresholds.min_positive_share:
        return CandidateStatus.INSUFFICIENT_QUALITY, "positive_share_below_threshold"
    if positive < thresholds.min_positive:
        return CandidateStatus.OBSERVING, "not_enough_quality_evidence"
    return CandidateStatus.CANDIDATE, "thresholds_met"


def detect_candidates(
    uses: Iterable[MethodUse], catalogue: Mapping[str, WorkMethod], *,
    thresholds: CandidateThresholds = DEFAULT_THRESHOLDS, promoted: Iterable[WorkMethod] = (),
) -> tuple[MethodCandidate, ...]:
    """Les approches observées, chacune avec son statut. `catalogue` : dernière version de chaque méthode.

    Ordre : candidats d'abord, puis par nombre d'usages décroissant, puis par id (stable).
    """

    groups: dict[ApproachSignature, list[MethodUse]] = {}
    for use in uses:
        groups.setdefault(use.signature, []).append(use)
    cited: dict[str, list[str]] = {}
    for method in promoted:
        if method.provenance.candidate_id:
            cited.setdefault(method.provenance.candidate_id, []).append(method.key)
    candidates = []
    for signature, items in groups.items():
        positive = [use for use in items if use.rating is QualityRating.POSITIVE]
        negative = sum(1 for use in items if use.rating is QualityRating.NEGATIVE)
        base = catalogue.get(signature.method_id) if signature.method_id else None
        status, reason = _status(len(items), len(positive), negative, thresholds)
        if signature.candidate_id in cited:
            status, reason = CandidateStatus.PROMOTED, "already_promoted"
        elif status is CandidateStatus.CANDIDATE and base is not None and signature.role_id in base.role_ids \
                and set(signature.relation_kinds) <= set(base.useful_relations):
            status, reason = CandidateStatus.MATCHES_METHOD, "nothing_beyond_the_method"
        refs: list[str] = []
        for use in sorted(positive, key=lambda use: use.closed_at, reverse=True):
            for ref in (use.mission_id, *use.quality_refs):
                if ref not in refs and len(refs) < MAX_EVIDENCE_REFS:
                    refs.append(ref)
        times = [use.closed_at for use in items]
        candidates.append(MethodCandidate(
            signature=signature, status=status, reason=reason, uses=len(items), positive=len(positive),
            negative=negative, unrated=len(items) - len(positive) - negative,
            chosen=sum(1 for use in items if use.method_chosen), first_seen=min(times), last_seen=max(times),
            evidence_refs=tuple(refs), draft=_draft(signature, base), base_method_key=base.key if base else None,
            promoted_keys=tuple(cited.get(signature.candidate_id, ())),
        ))
    return tuple(sorted(candidates, key=lambda c: (c.status is not CandidateStatus.CANDIDATE, -c.uses,
                                                   c.candidate_id)))


def promoted_method(
    candidate: MethodCandidate, payload: object, *, latest: WorkMethod | None, expected_version: int,
    promoted_by: str, promoted_at: datetime,
) -> WorkMethod:
    """La version qu'une promotion publie, ou `MethodError` codée. Ne promeut rien elle-même.

    - le promoteur est une personne (`HUMAN_PROMOTERS`), jamais un agent ;
    - le candidat atteint ses seuils au moment de la promotion (`candidate`) ;
    - `payload` est une méthode sans provenance (posée ici), sans clé de plan (`work_method_is_not_a_plan`) ;
    - révision optimiste : `expected_version` est la dernière version que la personne a vue (0 : aucune) ;
      elle doit être l'actuelle, et la nouvelle version la suit exactement (`check_revision`) ;
    - la méthode s'applique au rôle du candidat ;
    - la méthode publiée est celle du candidat : sa méthode de base (`method_id` imposé), ou, sans base, une
      méthode neuve dont l'id n'existe pas encore (`work_method_not_candidate_base` sinon).
    """

    if promoted_by not in HUMAN_PROMOTERS:
        raise MethodError(f"only a person promotes a work method, not {promoted_by!r}",
                          code="work_method_promoter_not_human")
    if candidate.status is not CandidateStatus.CANDIDATE:
        raise MethodError(f"candidate {candidate.candidate_id} is {candidate.status.value} ({candidate.reason}): "
                          "it cannot be promoted", code="work_method_candidate_not_eligible")
    if isinstance(payload, dict):
        plan = sorted(FORBIDDEN_PLAN_KEYS & payload.keys())
        if plan:
            raise MethodError(f"a Work Method is heuristic, not a workflow: {plan} is not allowed",
                              code="work_method_is_not_a_plan")
        if "provenance" in payload:
            raise MethodError("provenance is set by the promotion, not by the caller", code="work_method_invalid")
        payload = {**payload, "provenance": MethodProvenance(
            origin=MethodOrigin.PROMOTED, candidate_id=candidate.candidate_id, promoted_by=promoted_by,
            promoted_at=promoted_at, evidence_refs=candidate.evidence_refs).to_payload()}
    method = WorkMethod.from_payload(payload)
    base = candidate.signature.method_id
    if (base is not None and method.method_id != base) or (base is None and latest is not None):
        expected = base or "a method id that does not exist yet"
        raise MethodError(f"candidate {candidate.candidate_id} publishes {expected}, not {method.method_id}",
                          code="work_method_not_candidate_base")
    current = latest.version if latest is not None else 0
    if type(expected_version) is not int or expected_version != current:
        raise MethodError(f"{method.method_id} is now at version {current}, not {expected_version}: reload the "
                          "candidate", code="work_method_revision_conflict")
    if latest is None:
        if method.version != 1:
            raise MethodError(f"a new work method starts at version 1, got {method.version}",
                              code="work_method_revision_invalid")
    else:
        if method.version == latest.version:
            raise MethodError(f"{latest.key} already exists: publish version {latest.version + 1}",
                              code="work_method_version_conflict")
        check_revision(latest, method)
    if not method.applies_to(candidate.signature.role_id):
        raise MethodError(f"work method {method.method_id!r} must apply to role {candidate.signature.role_id}",
                          code="work_method_not_applicable")
    return method

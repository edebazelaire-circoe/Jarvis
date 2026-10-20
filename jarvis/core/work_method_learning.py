"""Service Core des candidats de Work Method et de leur promotion explicite (organic-agent-orchestration, Slice 12).

- **Lire** : `catalogue()` (versions livrées + versions promues, la dernière de
  chaque méthode) et `candidates()` (recalculés depuis l'historique durable des
  missions à chaque lecture : `work_method_learning.uses_from_tree`, puis
  `detect_candidates`). Rien n'est écrit par une lecture.
- **Promouvoir** : `promote(candidate_id, method, expected_version, promoted_by)`
  recalcule le candidat, vérifie seuils, schéma, révision et promoteur
  (`work_method_learning.promoted_method`), puis ajoute la version
  (`WorkMethodRepository.publish`, append-only). Un verrou sérialise les
  promotions de ce processus ; la clé primaire refuse une course restante.

Aucun agent n'atteint `promote` : seule la route Core `POST /v1/work-methods/promotions`
l'appelle, relayée par le Control Center pour l'utilisateur (`promoted_by="user"`).
Une version promue n'est pas encore apposée par le hook (suite documentée,
`docs/work-methods.md` › *État*). Journal : `work_methods.candidates_read`,
`work_methods.promoted`, `work_methods.promotion_refused`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jarvis.core.v2_services import NullDiagnosticSink, SystemClock
from jarvis.domain.work_method_learning import (
    DEFAULT_THRESHOLDS, CandidateThresholds, MethodCandidate, ScanReport, detect_candidates, promoted_method,
    uses_from_tree,
)
from jarvis.domain.work_methods import BUILTIN_METHODS, MethodError, WorkMethod, latest_methods
from jarvis.ports.mission_history import MissionHistoryRepository
from jarvis.ports.v2 import Clock, DiagnosticSink
from jarvis.ports.work_methods import WorkMethodRepository

CANDIDATES_READ_KIND = "work_methods.candidates_read"
PROMOTED_KIND = "work_methods.promoted"
PROMOTION_REFUSED_KIND = "work_methods.promotion_refused"
#: Missions lues pour retrouver les racines récentes (borne de l'adaptateur).
_MISSION_LIST_LIMIT = 200


@dataclass(frozen=True, slots=True)
class CandidateReading:
    candidates: tuple[MethodCandidate, ...]
    report: ScanReport
    thresholds: CandidateThresholds

    def to_payload(self) -> dict[str, Any]:
        return {"candidates": [candidate.to_payload() for candidate in self.candidates],
                "scan": self.report.to_payload(), "thresholds": self.thresholds.to_payload()}


class WorkMethodLearningService:
    """Voir le docstring du module."""

    def __init__(
        self, history: MissionHistoryRepository, methods: WorkMethodRepository, *,
        diagnostics: DiagnosticSink | None = None, clock: Clock | None = None,
        thresholds: CandidateThresholds = DEFAULT_THRESHOLDS,
    ) -> None:
        self._history = history
        self._methods = methods
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self._clock: Clock = clock or SystemClock()
        self.thresholds = thresholds
        self._lock = asyncio.Lock()

    async def _all_versions(self) -> tuple[tuple[WorkMethod, ...], tuple[WorkMethod, ...]]:
        promoted = await self._methods.promoted_methods()
        return (*BUILTIN_METHODS, *promoted), promoted

    async def catalogue(self) -> dict[str, Any]:
        """Toutes les versions (livrées et promues) et la dernière de chaque méthode."""

        versions, _ = await self._all_versions()
        latest = latest_methods(versions)
        return {"methods": [method.to_payload() for method in versions],
                "latest": {method_id: method.key for method_id, method in sorted(latest.items())}}

    async def candidates(self) -> CandidateReading:
        versions, promoted = await self._all_versions()
        report = ScanReport()
        uses = []
        roots: list[str] = []
        for mission in await self._history.list_missions(limit=_MISSION_LIST_LIMIT):
            if mission.root_mission_id not in roots:
                roots.append(mission.root_mission_id)
        if len(roots) > self.thresholds.scan_root_missions:
            report.truncated = True
            roots = roots[:self.thresholds.scan_root_missions]
        for root in roots:
            tree = await self._history.mission_tree(root)
            if tree is None:  # intentional: a root listed a moment ago and gone now cannot happen (no delete); counted
                report.skip("root_missing")
                continue
            report.root_missions += 1
            uses.extend(uses_from_tree(tree, report))
        candidates = detect_candidates(uses, latest_methods(versions), thresholds=self.thresholds, promoted=promoted)
        reading = CandidateReading(candidates, report, self.thresholds)
        self._emit(CANDIDATES_READ_KIND, "candidats de Work Method relus depuis l'historique", level="info",
                   data={**report.to_payload(), "candidates": len(candidates),
                         "eligible": sum(1 for c in candidates if c.status.value == "candidate")})
        return reading

    async def promote(self, candidate_id: str, method: Mapping[str, Any], *, expected_version: int,
                      promoted_by: str) -> WorkMethod:
        """Publier la version promue d'un candidat, ou lever `MethodError` codée (rien n'est écrit)."""

        async with self._lock:
            try:
                reading = await self.candidates()
                candidate = next((c for c in reading.candidates if c.candidate_id == candidate_id), None)
                if candidate is None:
                    raise MethodError(f"candidate {candidate_id} is not observed in the mission history",
                                      code="work_method_candidate_unknown")
                versions, _ = await self._all_versions()
                method_id = method.get("method_id") if isinstance(method, Mapping) else None
                latest = latest_methods(versions).get(method_id) if isinstance(method_id, str) else None
                published = await self._methods.publish(promoted_method(
                    candidate, dict(method) if isinstance(method, Mapping) else method, latest=latest,
                    expected_version=expected_version, promoted_by=promoted_by, promoted_at=self._clock.now()))
            except MethodError as exc:
                self._emit(PROMOTION_REFUSED_KIND, f"promotion de Work Method refusée : {exc.code}",
                           level="warning", data={"candidate_id": str(candidate_id)[:64], "code": exc.code})
                raise
        self._emit(PROMOTED_KIND, f"Work Method {published.key} promue par une personne", level="info",
                   data={"candidate_id": candidate_id, "method": published.key,
                         "promoted_by": published.provenance.promoted_by,
                         "evidence_refs": len(published.provenance.evidence_refs)})
        return published

    def _emit(self, kind: str, message: str, *, level: str, data: dict[str, Any]) -> None:
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            pass  # intentional: an unavailable journal never turns a read or a promotion into a failure

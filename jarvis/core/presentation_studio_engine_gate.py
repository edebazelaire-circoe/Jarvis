"""Porte du moteur d'une Presentation du Studio (handoff jarvis-remotion-presentation-integration, Slice 10 ;
`docs/presentation-engine.md` > *Runtime wiring status*).

Le seul point de Core qui lit la disponibilité d'un moteur : `StudioEngineGate.require(engine, action)` appelle
`resolve_engine` avec l'état que les adaptateurs rapportent. Avant **lire** (play), **éditer** (edit) et **prévisualiser**
(preview), le service du Studio demande la porte pour le moteur PROPRE de la Presentation. Un moteur qui n'est pas prêt lève
`presentation_studio_engine_unavailable` avec la raison et la réparation de son adaptateur ; **rien ne joue** à la place :
ni Slidecar pour un document `remotion`, ni l'inverse. Elle ne lit jamais l'état de l'autre moteur.

`require_compatible(declared, engine, what)` est le contrôle scène/moteur à l'ajout d'une scène : une source dont la
déclaration `{moteur: support}` est `unsupported` pour le moteur de la Presentation est refusée (`engine_unsupported`), jamais
aplatie en capture ni devinée.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from jarvis.domain.presentation_studio_checks import PresentationStudioError
from jarvis.domain.presentation_studio_engine import (
    Engine, EngineAvailability, EngineResolution, Support, require_compatible, resolve_engine,
)
from jarvis.ports.v2 import DiagnosticSink

TRACE = "core.presentation_studio"


class StudioEngineGate:
    def __init__(self, availability: Callable[[], Mapping[Engine, EngineAvailability]], *,
                 diagnostics: DiagnosticSink | None = None) -> None:
        self._availability = availability
        self._diagnostics = diagnostics

    def require(self, engine: Engine, action: str, *, presentation_id: str | None = None) -> EngineResolution:
        """Le moteur demandé, ou `engine_unavailable` (journalisé en `warning` avec la vraie raison)."""

        try:
            resolution = resolve_engine(engine, self._availability())
        except PresentationStudioError as exc:
            self._trace("engine_refused", "Moteur indisponible : l'action est refusee, rien ne joue a la place", level="warning",
                        data={"engine": engine.value, "action": action, "presentation_id": presentation_id,
                              "code": exc.code.value, "reason": exc.message[:240]})
            raise
        self._trace("engine_resolved", "Moteur de la Presentation pret",
                    data={"engine": engine.value, "action": action, "presentation_id": presentation_id})
        return resolution

    def require_compatible(self, declared: Mapping[Any, Any] | None, engine: Engine, *, what: str) -> Support:
        return require_compatible(declared, engine, what=what)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(f"{TRACE}.{kind}", message, level=level, data=data)
        except Exception:  # noqa: BLE001 - intentional: a failing journal never turns a refusal into a crash
            pass

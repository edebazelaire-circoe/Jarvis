"""Choix humain du moteur et observabilité de Slidecar (handoff jarvis-remotion-presentation-integration, Slice 20).

`docs/presentation-engine.md` > *Human engine control*. Deux responsabilités, séparées du service des Presentations pour qu'il
reste lisible :

- `EngineChoice.decide(request)` : le seul appelant de `POLICY.select` pour une création. Un moteur nommé par un autre acteur que
  l'utilisateur est refusé (`presentation_studio_engine_selection_refused`, 403) et journalisé en `warning` ; Slidecar sans
  confirmation explicite est refusé (400). Un Slidecar enregistré est journalisé en `info` (`slidecar_created`, par le service, APRÈS l'écriture) avec moteur, acteur et raison.
- `SlidecarLedger` : la mémoire bornée de ces journaux (création, copie « expérience », première utilisation par action), lue par
  `GET /v1/presentation-studio/engine`. Le journal durable est `DiagnosticSink` ; le registre garde seulement de quoi AFFICHER
  « Slidecar a été utilisé » depuis la dernière ouverture de Core. Ce qui survit à un redémarrage est le document lui-même : son
  `engine` est dans chaque listage.

Aucun contenu de présentation n'entre ici : ids, moteur, acteur, raison saisie (une ligne bornée), action.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import time
from typing import Any

from jarvis.domain.presentation_studio_checks import PresentationStudioError
from jarvis.domain.presentation_studio_engine import DEFAULT_ENGINE, POLICY, Engine
from jarvis.domain.presentation_studio_engine_request import CreateRequest, parse_create_request, require_slidecar_confirmation
from jarvis.ports.v2 import DiagnosticSink

TRACE = "core.presentation_studio"
MAX_EVENTS = 100
#: Why a stored Slidecar document exists, as far as Core can tell (the creation diagnostic says who; the document itself carries only the engine).
USE_REASONS = {
    "human": "stored engine is slidecar: created by the user as an experiment in this Core run",
    "legacy": "stored engine is slidecar: legacy document (created before the engine was recorded, by agent authoring before Remotion scenes, or by an earlier run)",
}
#: Une utilisation répétée du même moteur sur la même Presentation et la même action n'est journalisée qu'une fois par minute :
#: une modification par seconde ne doit pas noyer le registre, la première utilisation et chaque reprise après pause restent vues.
USE_WINDOW_S = 60.0


class SlidecarLedger:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._last_use: dict[tuple[str, str], float] = {}
        self._clock = clock
        self._now = now
        self.total = 0

    def add(self, kind: str, data: Mapping[str, Any]) -> dict[str, Any]:
        row = {"kind": kind, "at": self._now().isoformat(timespec="seconds"), **data}
        self._events.append(row)
        self.total += 1
        return row

    def should_note_use(self, presentation_id: str, action: str) -> bool:
        key, now = (presentation_id, action), self._clock()
        last = self._last_use.get(key)
        if last is not None and now - last < USE_WINDOW_S:
            return False
        if len(self._last_use) > 512:
            self._last_use.clear()
        self._last_use[key] = now
        return True

    def view(self) -> dict[str, Any]:
        return {"events": list(self._events)[::-1], "total": self.total, "kept": len(self._events), "durable": False}


class EngineChoice:
    def __init__(self, diagnostics: DiagnosticSink | None, ledger: SlidecarLedger | None = None) -> None:
        self._diagnostics = diagnostics
        self.ledger = ledger or SlidecarLedger()
        #: presentation id -> `human`, for documents created in THIS run; the rest read as `legacy` (Slice 15: an agent never makes a Slidecar).
        self.origins: dict[str, str] = {}

    def parse(self, raw: object) -> CreateRequest:
        """`parse_create_request` + le journal d'un acteur inconnu (refuse a la lecture du corps, avant toute politique)."""

        try:
            return parse_create_request(raw)
        except PresentationStudioError as exc:
            if exc.code.value == "presentation_studio_engine_selection_refused":
                self._emit("engine_selection_refused", "Choix de moteur refuse (acteur inconnu)", level="warning",
                           data={"actor": None, "code": exc.code.value})
            raise

    def decide(self, request: CreateRequest) -> Engine:
        try:
            engine = POLICY.select(request.requested, request.actor)
            require_slidecar_confirmation(engine, request)
        except PresentationStudioError as exc:
            data = {"requested": str(request.requested)[:40] if request.requested is not None else None,
                    "actor": request.actor.value, "code": exc.code.value}
            if exc.code.value == "presentation_studio_engine_selection_refused":
                self._emit("engine_selection_refused", "Choix de moteur refuse", level="warning", data=data)
            else:  # a typo or a missing confirmation is a validation error of the caller, not a policy refusal
                self._emit("engine_request_invalid", "Demande de moteur invalide", data=data)
            raise
        if request.requested is not None:
            self._emit("engine_chosen", "Moteur choisi par l'utilisateur",
                       data={"engine": engine.value, "actor": request.actor.value, "experimental": engine is Engine.SLIDECAR})
        return engine

    def note(self, kind: str, data: Mapping[str, Any], message: str) -> None:
        row = self.ledger.add(kind, data)
        self._emit(kind, message, data=dict(data) | {"at": row["at"]})

    def note_use(self, presentation_id: str, action: str, origin: str = "legacy") -> None:
        """Une Presentation Slidecar sert (lire, éditer, prévisualiser) : visible, jamais silencieux."""

        if self.ledger.should_note_use(presentation_id, action):
            self.note("slidecar_used", {"engine": Engine.SLIDECAR.value, "presentation_id": presentation_id, "action": action,
                                        "origin": origin, "reason": USE_REASONS.get(origin, USE_REASONS["legacy"])},
                      "Presentation Slidecar utilisee")

    def remember_origin(self, presentation_id: str, origin: str) -> None:
        self.origins[presentation_id] = origin

    def default_engine(self) -> str:
        return DEFAULT_ENGINE.value

    def _emit(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(f"{TRACE}.{kind}", message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a studio operation (same rule as the service)
            pass

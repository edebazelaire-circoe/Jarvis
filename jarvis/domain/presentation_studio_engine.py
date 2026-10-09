"""Presentation engine semantics (handoff jarvis-remotion-presentation-integration, Slice 02).

One Presentation is played, edited and exported by exactly ONE engine, named on its document. This module is the
contract (Level 2 in `docs/presentation-engine.md`, Level 3 by its conformance tests). It is pure: no I/O, no
adapter, no Remotion code. The adapters arrive in later Slices; they obey what is decided here.

Decisions (PM, 2026-10-09, not to be re-asked):

- `remotion` is the forced default for every NEW presentation and every scene the agent makes.
- A stored document with no engine reads as `slidecar` (legacy): preserved as is, never converted, and it is NOT a
  fallback because nothing was ever asked of Remotion for it.
- Only a HUMAN actor may select `slidecar`. An agent actor cannot select ANY engine (not even `remotion`): the agent
  tools carry no engine argument and the policy refuses a request that names one.
- No silent fallback, in any direction: `resolve_engine` returns the engine that was asked for or raises a typed
  `PresentationStudioError` naming that engine. There is no function here that maps one engine to another.
- Canonical spelling is `Slidecar` (never `Sidecar`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode as _C


class Engine(StrEnum):
    SLIDECAR = "slidecar"
    REMOTION = "remotion"


#: Engine of every new presentation and of every scene the agent makes (forced default).
DEFAULT_ENGINE = Engine.REMOTION
#: Engine of a stored document that names none: the pre-Remotion presentations. Read, never converted.
LEGACY_ENGINE = Engine.SLIDECAR


class EngineActor(StrEnum):
    #: A person acting through the Control Center (the only door to an explicit Slidecar choice).
    HUMAN = "human"
    #: The brain / a sub-agent / any tool call. Never chooses an engine.
    AGENT = "agent"
    #: Core itself (migration, recovery): reads the stored engine, chooses nothing.
    SYSTEM = "system"


class Capability(StrEnum):
    """What an engine may do. Deliberately coarse: a finer split is a later Slice's decision, not a guess."""

    RENDERING = "rendering"   # live preview / playback of a scene
    AUTHORING = "authoring"   # props patch and source edit
    MOTION = "motion"         # frame-deterministic timeline
    EXPORT = "export"         # MP4 / still / PDF derived from a frozen source


class Support(StrEnum):
    #: Done by the engine itself.
    NATIVE = "native"
    #: Possible only through an explicit adapter step (a source change the user can see); never implied.
    ADAPTER = "adapter"
    #: Not possible: reported, never guessed, never flattened to a screenshot.
    UNSUPPORTED = "unsupported"


#: Capability matrix (design contract; availability at runtime is a separate matter, see `EngineAvailability`).
#: Slidecar is the existing HTML engine: live DOM rendering and controls, no deterministic frame clock, no export.
CAPABILITIES: Mapping[Engine, Mapping[Capability, Support]] = {
    Engine.SLIDECAR: {Capability.RENDERING: Support.NATIVE, Capability.AUTHORING: Support.NATIVE,
                      Capability.MOTION: Support.ADAPTER, Capability.EXPORT: Support.UNSUPPORTED},
    Engine.REMOTION: {Capability.RENDERING: Support.NATIVE, Capability.AUTHORING: Support.NATIVE,
                      Capability.MOTION: Support.NATIVE, Capability.EXPORT: Support.NATIVE},
}


def capability_of(engine: Engine, capability: Capability) -> Support:
    return CAPABILITIES[engine][capability]


def coerce_engine(value: object, *, where: str = "engine") -> Engine:
    """A stored or requested value -> `Engine`, or `invalid` naming the field. Case and spelling are exact."""

    if isinstance(value, Engine):
        return value
    if isinstance(value, str):
        try:
            return Engine(value)
        except ValueError:
            pass
    allowed = ", ".join(e.value for e in Engine)
    raise PresentationStudioError(_C.INVALID_PRESENTATION, f"{where} must be one of: {allowed}")


def engine_of_document(value: object) -> Engine:
    """Engine named by a stored document: absent (`None`) is the legacy `slidecar`; anything else must be valid."""

    return LEGACY_ENGINE if value is None else coerce_engine(value)


# ------------------------------------------------------------------ selection policy

@dataclass(frozen=True, slots=True)
class EngineSelectionPolicy:
    """Who may pick which engine at creation time. Stateless; the instance exists so a caller can be tested against it."""

    def select(self, requested: object, actor: EngineActor | str) -> Engine:
        """`requested` is what the caller NAMED (`None` = nothing named). Returns the engine of a NEW presentation.

        - nothing named -> `DEFAULT_ENGINE` (any actor);
        - the agent names anything -> refused (`engine_selection_refused`), even the default: an agent has no say;
        - a human names `remotion` -> allowed; names `slidecar` -> allowed (the experimental option);
        - system names anything -> refused: Core reads stored engines, it does not choose one.
        """

        who = _actor(actor)
        if requested is None:
            return DEFAULT_ENGINE
        engine = coerce_engine(requested, where="requested engine")
        if who is not EngineActor.HUMAN:
            raise PresentationStudioError(
                _C.ENGINE_SELECTION_REFUSED,
                f"only a person can choose the engine of a presentation; a {who.value} cannot (asked: {engine.value}). "
                f"New presentations use {DEFAULT_ENGINE.value}.")
        return engine


def _actor(actor: object) -> EngineActor:
    try:
        return EngineActor(actor)
    except ValueError:
        # An unknown actor is not trusted with a choice: fail closed with the real cause.
        raise PresentationStudioError(_C.ENGINE_SELECTION_REFUSED, f"unknown actor {str(actor)[:40]!r}: no engine choice") from None


POLICY = EngineSelectionPolicy()


# ------------------------------------------------------------------ availability and typed failure (no fallback)

@dataclass(frozen=True, slots=True)
class EngineAvailability:
    """Runtime state of one engine as its adapter reports it. `reason` and `repair` are the adapter's real words."""

    ready: bool
    reason: str = ""
    repair: str = ""

    def __post_init__(self) -> None:
        if not self.ready and not self.reason.strip():
            raise ValueError("an engine that is not ready must say why (reason)")


@dataclass(frozen=True, slots=True)
class EngineResolution:
    """The engine that will run. Always the one asked for; carries no alternative."""

    engine: Engine
    version: str | None = None


def resolve_engine(engine: Engine, availability: Mapping[Engine, EngineAvailability]) -> EngineResolution:
    """Gate before any run of a presentation. `engine` is the presentation's own engine.

    Not ready, or not reported at all -> `engine_unavailable` naming THAT engine, its real reason and repair. The state
    of the other engine is never read: there is no fallback to make.
    """

    state = availability.get(engine)
    if state is None:
        raise PresentationStudioError(_C.ENGINE_UNAVAILABLE, f"{engine.value} reports no state: its adapter is not installed in this Core")
    if not state.ready:
        repair = f" Repair: {state.repair}" if state.repair.strip() else ""
        raise PresentationStudioError(_C.ENGINE_UNAVAILABLE, f"{engine.value} is unavailable: {state.reason}.{repair}")
    return EngineResolution(engine)


def require_capability(engine: Engine, capability: Capability) -> Support:
    """`native` or `adapter` pass (the caller decides what an adapter step means); `unsupported` raises `engine_unsupported`."""

    support = capability_of(engine, capability)
    if support is Support.UNSUPPORTED:
        raise PresentationStudioError(_C.ENGINE_UNSUPPORTED, f"{engine.value} does not support {capability.value}")
    return support


# ------------------------------------------------------------------ compatibility triage (a prefab / source vs an engine)

def classify_compatibility(declared: Mapping[Any, Any] | None, engine: Engine) -> Support:
    """Triage of a source for an engine from what the source DECLARES: `{engine: support}`.

    Undeclared is `unsupported`, never guessed. The one exception is the legacy HTML prefab (declares nothing, predates
    engines): see `legacy_html_compatibility()`; callers pass that explicitly, it is not an implicit default.
    """

    if not declared:
        return Support.UNSUPPORTED
    for key, value in declared.items():
        if coerce_engine(key, where="compatibility key") is engine:
            try:
                return Support(value)
            except ValueError:
                raise PresentationStudioError(
                    _C.INVALID_PRESENTATION, f"compatibility for {engine.value} must be native, adapter or unsupported") from None
    return Support.UNSUPPORTED


def legacy_html_compatibility() -> Mapping[Engine, Support]:
    """What every pre-Remotion HTML prefab bundle is: native in Slidecar; in Remotion only if someone adapts it explicitly."""

    return {Engine.SLIDECAR: Support.NATIVE, Engine.REMOTION: Support.UNSUPPORTED}


def require_compatible(declared: Mapping[Any, Any] | None, engine: Engine, *, what: str = "this source") -> Support:
    """`native` / `adapter` -> returned; `unsupported` -> `engine_unsupported` (no silent flattening, no guess)."""

    support = classify_compatibility(declared, engine)
    if support is Support.UNSUPPORTED:
        raise PresentationStudioError(_C.ENGINE_UNSUPPORTED, f"{what} is not supported by {engine.value}")
    return support


# ------------------------------------------------------------------ manifest engine metadata

@dataclass(frozen=True, slots=True)
class EngineIdentity:
    """Engine metadata a frozen source / export manifest carries: which engine, and its pinned version once known."""

    engine: Engine
    version: str | None = None

    def __post_init__(self) -> None:
        if self.version is not None and (not isinstance(self.version, str) or not 0 < len(self.version) <= 40
                                         or not self.version.isprintable()):
            raise PresentationStudioError(_C.INVALID_PRESENTATION, "engine version must be a short printable string")

    def to_dict(self) -> dict[str, Any]:
        return {"engine": self.engine.value, "engine_version": self.version,
                "capabilities": {c.value: s.value for c, s in CAPABILITIES[self.engine].items()}}

    @classmethod
    def from_dict(cls, raw: object) -> "EngineIdentity":
        if not isinstance(raw, dict) or set(raw) - {"engine", "engine_version", "capabilities"} or "engine" not in raw:
            raise PresentationStudioError(_C.INVALID_PRESENTATION, "engine identity must be {engine, engine_version?}")
        identity = cls(coerce_engine(raw["engine"]), raw.get("engine_version"))
        if "capabilities" in raw and raw["capabilities"] != identity.to_dict()["capabilities"]:
            # Capabilities are derived, never trusted from a document.
            raise PresentationStudioError(_C.INVALID_PRESENTATION, "engine capabilities do not match the contract")
        return identity

"""Playback service of the Presentation Studio (handoff jarvis-interactive-presentation-studio, Slice 12).

Core owns the run, in memory (R6: position, reveal progress, detours and the auxiliary stack are **never persisted**;
the only thing on disk is the stage ledger of object ids, which exists to take objects back). The decision logic is the
pure machine `jarvis/domain/presentation_studio_playback.py`; this service

1. serialises the commands (one lock: a click and a cue never interleave),
2. runs the machine and then executes its **effects** through existing services only:
   the one stable stage window and the auxiliary windows through `SceneStage` (scene commands inside
   `SceneService.apply_if`), the values of the score through `PresentationStudioEditService.render_overlay`,
   the interaction mode through `InteractionModeService.request` with the Slice 01c helper,
3. keeps the reality honest: a failed stage sync pauses the run with a visible problem; a crash, a stop, a foreign
   mode change and a Core restart all end with the auxiliary windows retired and the stage released.

Playback never writes the variant. Values a score sets (`control_set`, control-bound reveals) are an **ephemeral overlay**
rendered in memory by the edit engine and shown on the stage window; the variant file is byte-identical after a full run.
Only an **explicit edit instruction** (`edit`) commits, through the Slice 05 service, and it pauses the run first;
improvisation (what the presenter says) never writes anything.

Art direction: `require_art_direction` is a port (`ArtDirectionGate`, the signature of
`PresentationStudioService.require_art_direction` of Slice 09). Without one wired the run says so on screen
(`art_direction: "unchecked"`, `docs/legacy/presentation-studio-art-direction-gate.md`).

Contract: `docs/presentation-studio.md` > *Playback runtime contract*.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
import secrets
import time
from typing import Any, Protocol

from jarvis.core.presentation_studio_stage import StageError
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_armed_set import (
    ARMED_CHANGED, ARMED_SET_TTL_S, ReportCode, ReportLedger, ReportLimiter, build_armed_set, changed_payload,
    parse_cue_report,
)
from jarvis.domain.presentation_studio_edit import EditStatus, StudioActor
from jarvis.domain.presentation_studio_playback import (
    AuxRef, Effect, EventKind, Phase, PlaybackEvent, PlaybackPlan, PlaybackState, RefusalCode, apply, check_invariants,
    compile_plan, idle_state, progress_of, rebase, settle_after_rebase, where_are_we,
)
from jarvis.domain.presentation_studio_playback_requests import (
    Verb, parse_actor_only, parse_anchor, parse_detour, parse_edit, parse_goto, parse_start,
)
from jarvis.domain.presentation_studio_roles import (
    STUDIO_RUN_MODE_SOURCE, ModeEventKind, RestoreAction, StudioRole, classify_mode_event, decide_restore,
    plan_mode_entry, requirements,
)
from jarvis.domain.presentation_studio_score import parse_score
from jarvis.domain.scene import ScenePrefabRef
from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.ports.v2 import DiagnosticSink

TRACE = "core.presentation_studio"
#: What `render_overlay` is given per scene: the score's values are few, but the engine takes 16 ops per chunk.
MAX_NOTICES = 8


class ArtDirectionGate(Protocol):
    """Slice 09's `PresentationStudioService.require_art_direction`: returns `{status, fallback, art_direction}` or raises a
    `PresentationStudioError` (`art_direction_required`, `unknown_art_direction`). The run starts only when it returns."""

    async def require_art_direction(self, presentation_id: str, variant_id: str, *,
                                    serious: bool = True) -> Mapping[str, Any]: ...


class Stage(Protocol):
    """What the service needs of `SceneStage` (a recording fake in tests)."""

    @property
    def stage_object_id(self) -> str | None: ...

    def begin(self, run_id: str) -> None: ...

    async def show(self, payload: Any) -> bool: ...

    async def release(self) -> None: ...

    async def stage_aux(self, aux_id: str, title: str, block: ScenePrefabRef) -> str: ...

    async def reveal_aux(self, object_id: str) -> None: ...

    async def retire(self, object_ids: Sequence[str]) -> None: ...

    async def reclaim(self) -> tuple[str, ...]: ...


class PlaybackStatus(StrEnum):
    APPLIED = "applied"
    REFUSED = "refused"
    #: The transition happened but the stage could not follow: the run is paused with a visible problem.
    STAGE_FAILED = "stage_failed"


@dataclass(frozen=True, slots=True)
class PlaybackResult:
    status: PlaybackStatus
    command: str
    state: Mapping[str, Any]
    #: Stable `RefusalCode` (or stage code) when not applied.
    reason: str | None = None
    message: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def http_status(self) -> int:
        return {PlaybackStatus.APPLIED: 200, PlaybackStatus.REFUSED: 409, PlaybackStatus.STAGE_FAILED: 500}[self.status]

    def to_dict(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"status": self.status.value, "command": self.command, "state": dict(self.state),
                                **dict(self.extra)}
        if self.status is not PlaybackStatus.APPLIED:
            code = C.PLAYBACK_REFUSED if self.status is PlaybackStatus.REFUSED else C.PLAYBACK_STAGE_FAILED
            wire.update({"reason": self.reason, "message": self.message,
                         "error": {"code": code.value, "message": self.message, "reason": self.reason}})
        return wire


@dataclass(slots=True)
class _ModeMemory:
    previous: InteractionMode
    epoch: str
    revision: int


class PresentationStudioPlaybackService:
    def __init__(self, studio: Any, edit: Any, stage: Stage, mode: Any, *, gate: ArtDirectionGate | None = None,
                 bus: Any | None = None, events: Any | None = None, diagnostics: DiagnosticSink | None = None,
                 monotonic: Callable[[], float] = time.monotonic,
                 new_run_id: Callable[[], str] = lambda: secrets.token_hex(6),
                 armed_ttl_s: float = ARMED_SET_TTL_S) -> None:
        self._studio, self._edit, self._stage, self._mode = studio, edit, stage, mode
        self._gate, self._bus, self._events, self._diagnostics = gate, bus, events, diagnostics
        self._monotonic, self._new_run_id, self._armed_ttl_s = monotonic, new_run_id, armed_ttl_s
        self._lock = asyncio.Lock()
        self._state: PlaybackState = idle_state()
        self._plan: PlaybackPlan | None = None
        self._scenes: dict[str, Any] = {}
        self._presentation_id: str | None = None
        self._variant_id: str | None = None
        self._required_mode: InteractionMode | None = None
        self._memory: _ModeMemory | None = None
        self._aux_objects: dict[str, str] = {}
        self._aux_blocks: dict[str, tuple[str, ScenePrefabRef]] = {}
        self._orphans: list[str] = []
        self._aux_counter = 0
        self._notices: list[str] = []
        self._art_direction = "none"
        self._da_revision: int | None = None
        self._armed_until = 0.0
        self._reports, self._limiter = ReportLedger(), ReportLimiter()
        self._own_edit = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._event_seq = 0
        self._last_ended: dict[str, Any] | None = None
        edit.add_commit_listener(self._on_edit_committed)
        if hasattr(mode, "add_listener"):
            mode.add_listener(self._on_mode, with_state=True)

    # ------------------------------------------------------------------ lifecycle

    async def start_service(self) -> None:
        """Core start: take back what a killed life left on the scene (by id list). Never raises: a failure is an error row."""

        try:
            taken = await self._stage.reclaim()
        except Exception as exc:  # noqa: BLE001 - captured as an error row; Core starts regardless, the leak risk is said
            self._trace("playback_reclaim_failed", "Reprise des objets de scene du Studio impossible", level="error",
                        data={"error_class": type(exc).__name__, "error": _clip(exc)})
            return
        self._trace("playback_reclaimed", "Objets de scene d'une vie precedente repris", data={"count": len(taken)})

    async def close(self) -> None:
        """Core shutdown: end a live run (aux retired, stage released, mode restored) before the scene closes."""

        if self._state.active:
            await self.stop({"actor": "user"}, reason="shutdown")
        for task in tuple(self._tasks):
            task.cancel()

    # ------------------------------------------------------------------ reads

    @property
    def state(self) -> PlaybackState:
        return self._state

    def where(self) -> dict[str, Any]:
        """The bounded "where are we" answer, always available (no lock: a read of immutable values)."""

        return self._view()

    def armed_set(self) -> dict[str, Any]:
        """What the cue follower pulls. A pull renews the follower's authority for `armed_ttl_s`."""

        self._armed_until = self._monotonic() + self._armed_ttl_s
        message = build_armed_set(self._plan, self._state, ttl_s=self._armed_ttl_s)
        self._trace("armed_set_pulled", "Ensemble arme lu par le suiveur",
                    data={"run_id": self._state.run_id, "generation": self._state.generation, "count": len(message.cues)})
        return message.to_dict()

    # ------------------------------------------------------------------ commands

    async def start(self, raw: object) -> PlaybackResult:
        request = parse_start(raw)
        async with self._lock:
            return await self._guarded("start", self._start(request))

    async def stop(self, raw: object, *, reason: str = "user") -> PlaybackResult:
        parse_actor_only(raw, "stop")
        async with self._lock:
            return await self._guarded("stop", self._dispatch("stop", EventKind.STOP, stop_reason=reason))

    async def pause(self, raw: object) -> PlaybackResult:
        parse_actor_only(raw, "pause")
        return await self._command("pause", EventKind.PAUSE)

    async def resume(self, raw: object) -> PlaybackResult:
        parse_actor_only(raw, "resume")
        async with self._lock:
            return await self._guarded("resume", self._resume())

    async def next(self, raw: object) -> PlaybackResult:
        parse_actor_only(raw, "next")
        return await self._command("next", EventKind.NEXT)

    async def previous(self, raw: object) -> PlaybackResult:
        parse_actor_only(raw, "previous")
        return await self._command("previous", EventKind.PREVIOUS)

    async def goto(self, raw: object) -> PlaybackResult:
        _, target = parse_goto(raw)
        return await self._command("goto", EventKind.GOTO, **target)

    async def reveal(self, raw: object) -> PlaybackResult:
        _, anchor = parse_anchor(raw, "reveal")
        return await self._command("reveal", EventKind.REVEAL, anchor_id=anchor)

    async def hide(self, raw: object) -> PlaybackResult:
        _, anchor = parse_anchor(raw, "hide")
        return await self._command("hide", EventKind.HIDE, anchor_id=anchor)

    async def detour(self, raw: object) -> PlaybackResult:
        _, title, block = parse_detour(raw)
        async with self._lock:
            self._aux_counter += 1
            aux = AuxRef(f"a{self._aux_counter}", title, block.prefab_id, block.version)
            self._aux_blocks[aux.aux_id] = (title, block)
            result = await self._guarded("detour", self._dispatch("detour", EventKind.DETOUR, aux=aux))
            if result.status is PlaybackStatus.REFUSED:
                self._aux_blocks.pop(aux.aux_id, None)
            return result

    async def back_from_detour(self, raw: object) -> PlaybackResult:
        parse_actor_only(raw, "return")
        return await self._command("return", EventKind.RETURN)

    async def edit(self, raw: object) -> PlaybackResult:
        """An explicit edit instruction during a run: **pause**, commit through the Slice 05 edit service, follow."""

        actor, basis, ops = parse_edit(raw)
        async with self._lock:
            return await self._guarded("edit", self._edit_during_run(actor, basis, ops))

    async def notify(self, kind: EventKind, **fields: Any) -> PlaybackResult:
        """Reports of the timeline owners (Slice 14's locked-sequence executor, speech state). Not an HTTP surface."""

        allowed = {EventKind.SEQUENCE_STEP, EventKind.SEQUENCE_DONE, EventKind.SEQUENCE_ABORT, EventKind.SPEAKING,
                   EventKind.BOUNDARY}
        if kind not in allowed:
            raise ValueError(f"{kind.value} is not a timeline report")
        return await self._command(kind.value, kind, **fields)

    async def report_cue(self, raw: object) -> dict[str, Any]:
        """`POST .../cues/satisfied`: a typed report from the cue follower. Never text; judged against Core's state now."""

        report = parse_cue_report(raw)
        now_s = self._monotonic()
        async with self._lock:
            cached = self._reports.get(report)
            if cached is not None:
                self._trace("cue_report_duplicate", "Rapport de cue deja traite (idempotent)",
                            data={"run_id": report.run_id, "generation": report.generation})
                return {**cached, "duplicate": True}
            refusal: tuple[ReportCode, str, int] | None = None
            if not self._limiter.allow(now_s):
                refusal = (ReportCode.RATE_LIMITED, "too many cue reports: slow down", 429)
            elif not self._state.active or self._state.run_id != report.run_id:
                refusal = (ReportCode.STALE_RUN, "this run is not the current one", 409)
            elif report.generation != self._state.generation:
                refusal = (ReportCode.STALE_GENERATION, "the armed set has moved on: pull it again", 409)
            elif now_s > self._armed_until:
                refusal = (ReportCode.EXPIRED, "the armed set expired: pull it again", 409)
            if refusal is not None:
                code, message, http = refusal
                self._trace("cue_report_refused", "Rapport de cue refuse", level="warning" if http == 429 else "info",
                            data={"code": code.value, "run_id": report.run_id, "generation": report.generation})
                return {"status": "refused", "code": code.value, "message": message, "http_status": http,
                        "error": {"code": code.value, "message": message}}
            result = await self._guarded("cue", self._dispatch("cue", EventKind.CUE_SATISFIED, cue_id=report.cue_id))
            if result.status is PlaybackStatus.REFUSED:
                code = ReportCode.NOT_ARMED
                return {"status": "refused", "code": code.value, "message": result.message, "http_status": 409,
                        "reason": result.reason, "error": {"code": code.value, "message": result.message}}
            answer = {"status": "fired", "run_id": report.run_id, "generation": self._state.generation,
                      "position": self._state.position + 1, "http_status": 200}
            self._reports.remember(report, answer)
            return answer

    # ------------------------------------------------------------------ internals: commands

    async def _command(self, name: str, kind: EventKind, **fields: Any) -> PlaybackResult:
        async with self._lock:
            return await self._guarded(name, self._dispatch(name, kind, **fields))

    async def _guarded(self, name: str, work: Awaitable[PlaybackResult]) -> PlaybackResult:
        """A crash inside a command ends the run cleanly (aux retired, stage released, mode restored) and then propagates."""

        try:
            return await work
        except asyncio.CancelledError:
            if self._state.active:
                await asyncio.shield(self._crash(name, asyncio.CancelledError()))
            raise
        except PresentationStudioError:
            raise
        except Exception as exc:  # noqa: BLE001 - run ended cleanly below, then re-raised to the route boundary
            await self._crash(name, exc)
            raise

    async def _crash(self, name: str, exc: BaseException) -> None:
        self._trace("playback_crashed", "Lecture interrompue par une erreur : fin propre de la seance", level="error",
                    data={"command": name, "error_class": type(exc).__name__, "error": _clip(exc)})
        if not self._state.active:
            return
        transition = apply(self._plan, self._state, PlaybackEvent(EventKind.STOP, self._ms())) if self._plan else None
        if transition is not None and transition.ok:
            self._state = transition.state
        await self._teardown("crashed")

    async def _dispatch(self, name: str, kind: EventKind, *, stop_reason: str = "user", **fields: Any) -> PlaybackResult:
        if self._plan is None:
            return self._refused(name, RefusalCode.NOT_RUNNING, "no presentation is running")
        before = self._state
        transition = apply(self._plan, before, PlaybackEvent(kind, self._ms(), **fields))
        if not transition.ok:
            refusal = transition.refusal
            self._trace("playback_refused", "Commande de lecture refusee", data={
                "command": name, "code": refusal.code.value, "phase": before.phase.value, "run_id": before.run_id})
            return self._refused(name, refusal.code, refusal.message)
        self._commit(transition.state, name)
        return await self._execute(name, before, transition.effects, stop_reason=stop_reason)

    async def _resume(self) -> PlaybackResult:
        """Resume re-reads the plan first: a score or variant edited while paused is picked up, never played stale."""

        if self._plan is not None and self._state.phase is Phase.PAUSED:
            await self._refresh_plan("resume")
            await self._check_art_direction_revision()
        return await self._dispatch("resume", EventKind.RESUME)

    def _commit(self, state: PlaybackState, name: str) -> None:
        problems = check_invariants(self._plan, state) if self._plan is not None else []
        if problems:  # a bug in the machine, never a user error: said loudly, the state is still taken (it was computed)
            self._trace("playback_invariant_broken", "Etat de lecture incoherent", level="error",
                        data={"command": name, "problems": problems[:3]})
        previous = self._state
        self._state = state
        self._trace("playback_transition", "Transition de lecture", data={
            "command": name, "from": previous.phase.value, "to": state.phase.value, "position": state.position + 1,
            "run_id": state.run_id, "generation": state.generation})

    async def _execute(self, name: str, before: PlaybackState, effects: Sequence[Effect], *,
                       stop_reason: str = "user") -> PlaybackResult:
        failures: list[tuple[str, str]] = []
        status_event: str | None = _STATUS_OF.get(name)
        queue = list(effects)
        while queue:
            effect = queue.pop(0)
            try:
                if effect is Effect.SYNC_STAGE:
                    await self._sync_stage()
                    if self._state.phase is Phase.RESUMING:
                        queue.extend(self._feed(EventKind.STAGE_SYNCED))
                elif effect is Effect.SHOW_AUX:
                    await self._show_aux()
                elif effect is Effect.RETIRE_AUX:
                    await self._retire_aux(before.aux[-1] if before.aux else None)
                elif effect is Effect.RETIRE_ALL:
                    failures += await self._retire_all()
                elif effect is Effect.ARM_CHANGED:
                    await self._publish_armed()
                elif effect is Effect.END_RUN:
                    failures += await self._teardown(stop_reason)
                    status_event = "stopped"
            except (StageError, PresentationStudioError) as exc:
                code = exc.code if isinstance(exc, StageError) else exc.code.value
                failures.append((code, exc.message))
                self._trace("playback_stage_failed", "La fenetre de scene n'a pas suivi : lecture en pause", level="error",
                            data={"command": name, "code": code, "error": _clip(exc.message), "run_id": self._state.run_id})
                if effect is Effect.SYNC_STAGE:
                    queue = self._feed(EventKind.STAGE_FAILED, problem=_problem_code(code))
                    status_event = "stage_failed"
                else:
                    self._add_problem("aux_stage_failed" if effect is Effect.SHOW_AUX else "aux_retire_failed")
        if self._state.phase is Phase.ENDED and before.phase is not Phase.ENDED:
            status_event = "ended"
        if status_event is not None:
            await self._announce(status_event)
        if failures:
            code, message = failures[0]
            return PlaybackResult(PlaybackStatus.STAGE_FAILED, name, self._view(), code, message)
        return PlaybackResult(PlaybackStatus.APPLIED, name, self._view())

    def _feed(self, kind: EventKind, **fields: Any) -> list[Effect]:
        """An internal event (the stage's own acknowledgement or failure): applied like any other, effects returned."""

        transition = apply(self._plan, self._state, PlaybackEvent(kind, self._ms(), **fields))
        if transition.ok:
            self._commit(transition.state, kind.value)
        return list(transition.effects) if transition.ok else []

    # ------------------------------------------------------------------ internals: start and teardown

    async def _start(self, request: Any) -> PlaybackResult:
        if self._state.active:
            return self._refused("start", RefusalCode.ALREADY_RUNNING, "a presentation is already running")
        presentation_id = request.presentation_id
        variant_id = request.variant_id or (await self._studio.get(presentation_id)).presentation.active_variant_id
        variant = await self._studio.get_variant(presentation_id, variant_id)
        plan, scenes = await self._compile(presentation_id, variant_id, variant)
        serious = request.role is not StudioRole.REHEARSAL
        art = "unchecked"
        da_revision = None
        if self._gate is not None:
            resolution = await self._gate.require_art_direction(presentation_id, variant_id, serious=serious)
            art = "fallback" if resolution.get("fallback") else "checked"
            da_revision = (resolution.get("art_direction") or {}).get("revision")
        else:
            self._trace("playback_art_direction_unchecked", "Direction artistique non verifiee : aucun controle cable",
                        level="warning", data={"presentation_id": presentation_id, "variant_id": variant_id})
        needs = requirements(request.role, jarvis_speaks=request.jarvis_speaks)
        before_mode = self._mode.mode
        entry = plan_mode_entry(request.role, request.origin, before_mode, jarvis_speaks=request.jarvis_speaks)
        if not entry.allowed:
            return self._refused("start", RefusalCode.MODE_SWITCH_REFUSED,
                                 "only an explicit user request may start a run that needs another interaction mode",
                                 extra={"mode_code": entry.code})
        memory: _ModeMemory | None = None
        if entry.switch_needed:
            try:
                state, disposition = await self._mode.request(entry.target, source=entry.source)
            except ValueError as exc:  # InteractionModeError: refused loudly, the mode is unchanged, the run does not start
                return self._refused("start", RefusalCode.MODE_SWITCH_REFUSED, str(exc),
                                     extra={"mode_code": getattr(exc, "code", "interaction_mode_refused")})
            if disposition.value == "applied":
                memory = _ModeMemory(before_mode, state.epoch, state.revision)
        self._memory, self._required_mode = memory, needs.mode  # before anything else can fail: `_abandon_start` restores
        run_id = self._new_run_id()
        try:
            self._plan, self._scenes = plan, scenes
            self._presentation_id, self._variant_id = presentation_id, variant_id
            self._art_direction, self._da_revision = art, da_revision
            self._notices, self._aux_objects, self._aux_blocks, self._orphans = [], {}, {}, []
            self._aux_counter, self._last_ended = 0, None
            self._reports.clear()
            self._stage.begin(run_id)
            transition = apply(plan, self._state, PlaybackEvent(
                EventKind.START, self._ms(), run_id=run_id, role=request.role, jarvis_speaks=request.jarvis_speaks))
            if not transition.ok:
                await self._abandon_start()
                return self._refused("start", transition.refusal.code, transition.refusal.message)
            self._commit(transition.state, "start")
        except Exception:
            await self._abandon_start()
            raise
        self._trace("playback_started", "Lecture demarree", data={
            "presentation_id": presentation_id, "variant_id": variant_id, "run_id": run_id, "role": request.role.value,
            "items": len(plan), "mode_switched": memory is not None, "art_direction": art})
        result = await self._execute("start", self._state, transition.effects)
        if result.status is PlaybackStatus.STAGE_FAILED:
            # A run that cannot show its first scene is not a run: end it cleanly and tell the real cause.
            code, message = result.reason or "stage_failed", result.message or "the stage did not appear"
            await self._end_after_failed_start()
            raise PresentationStudioError(C.PLAYBACK_STAGE_FAILED, f"{code}: {message}")
        return result

    async def _compile(self, presentation_id: str, variant_id: str, variant: Any) -> tuple[PlaybackPlan, dict[str, Any]]:
        document = await self._studio.get_score(presentation_id, variant_id)
        problems = document["problems"]
        if problems:
            raise PresentationStudioError(
                C.SCORE_INCOMPATIBLE,
                f"the score has {len(problems)} reference(s) that no longer resolve (first: {problems[0]}): fix them before playing")
        score = parse_score(document["score"])
        plan = compile_plan(score, variant.scenes, variant_revision=variant.revision)
        return plan, {scene.scene_id: scene for scene in variant.scenes}

    async def _abandon_start(self) -> None:
        await self._restore_mode("start_abandoned")
        self._plan, self._state, self._memory, self._required_mode = None, idle_state(), None, None

    async def _end_after_failed_start(self) -> None:
        transition = apply(self._plan, self._state, PlaybackEvent(EventKind.STOP, self._ms()))
        if transition.ok:
            self._commit(transition.state, "stop")
        await self._retire_all()
        await self._teardown("start_failed")

    async def _teardown(self, reason: str) -> list[tuple[str, str]]:
        """Every exit path of a run. Each step is tried even if the one before failed; each failure is a visible problem."""

        problems: list[tuple[str, str]] = []
        run_id = self._state.run_id
        try:
            await self._stage.retire([*self._aux_objects.values(), *self._orphans])
            self._aux_objects, self._orphans = {}, []
        except Exception as exc:  # noqa: BLE001 - captured as an error row; the ids stay in the ledger for the next start
            problems.append(("aux_retire_failed", _clip(exc)))
            self._trace("playback_aux_retire_failed", "Ressources auxiliaires non retirees de la scene", level="error",
                        data={"run_id": run_id, "error_class": type(exc).__name__, "error": _clip(exc)})
        try:
            await self._stage.release()
        except Exception as exc:  # noqa: BLE001 - captured as an error row; the id stays in the ledger for the next start
            problems.append(("stage_release_failed", _clip(exc)))
            self._trace("playback_stage_release_failed", "Fenetre de scene du Studio non retiree", level="error",
                        data={"run_id": run_id, "error_class": type(exc).__name__, "error": _clip(exc)})
        problems += await self._restore_mode(reason)
        if self._state.phase is not Phase.STOPPED and self._state.active:
            self._state = replace(self._state, phase=Phase.STOPPED, aux=(), armed=(), sequence=None, pending=None)
        codes = [code for code, _ in problems]
        self._last_ended = {"run_id": run_id, "reason": reason, "problems": codes}
        self._trace("playback_stopped", "Lecture terminee", data={"run_id": run_id, "reason": reason, "problems": codes})
        self._required_mode, self._memory = None, None
        return problems

    async def _restore_mode(self, reason: str) -> list[tuple[str, str]]:
        memory = self._memory
        decision = decide_restore(
            previous_mode=memory.previous if memory else None, applied_epoch=memory.epoch if memory else None,
            applied_revision=memory.revision if memory else None, current_mode=self._mode.mode,
            current_epoch=self._mode.epoch, current_revision=self._mode.revision)
        self._trace("playback_mode_decision", "Mode d'interaction apres la lecture", data={
            "action": decision.action.value, "code": decision.code, "reason": reason})
        if decision.action is not RestoreAction.RESTORE:
            return []
        try:
            await self._mode.request(decision.target, source=STUDIO_RUN_MODE_SOURCE)
        except Exception as exc:  # noqa: BLE001 - captured: the mode is left as is and the problem is visible, no retry loop
            self._trace("mode_restore_failed", "Le mode d'interaction n'a pas pu etre restaure", level="error",
                        data={"error_class": type(exc).__name__, "error": _clip(exc), "target": decision.target.value})
            return [("mode_restore_failed", _clip(exc))]
        return []

    # ------------------------------------------------------------------ internals: stage and aux

    async def _sync_stage(self) -> None:
        """Bring the stage window to the state: the position's scene with the score's overlay (never written)."""

        state, plan = self._state, self._plan
        scene_id = plan.item_at(state.position).scene_id
        scene = self._scenes[scene_id]
        progress = progress_of(plan, state)
        explicit = [_set_op(s, c, v) for (s, c), (v, anchored) in progress.values.items() if s == scene_id and not anchored]
        anchored = [_set_op(s, c, v) for (s, c), (v, a) in progress.values.items() if s == scene_id and a]
        shown = scene
        if explicit or anchored:
            render = await self._render(explicit + anchored)
            if render.status is not EditStatus.APPLIED and anchored:
                # a control-bound anchor whose control is not a toggle: the marker still counts, the pixels do not move
                self._notice("anchor_control_not_toggle")
                render = await self._render(explicit) if explicit else None
            if render is not None:
                if render.status is not EditStatus.APPLIED:
                    raise StageError(render.code or "overlay_refused", render.message or "the overlay was refused")
                shown = next(s for s in render.scenes if s.scene_id == scene_id)
        await self._stage.show(shown.payload())

    async def _render(self, ops: list[dict[str, Any]]) -> Any:
        render = await self._edit.render_overlay(self._presentation_id, self._variant_id, self._plan.variant_revision, ops)
        if render.status is EditStatus.STALE:
            await self._refresh_plan("stale_overlay")
            render = await self._edit.render_overlay(self._presentation_id, self._variant_id,
                                                     self._plan.variant_revision, ops)
        return render

    async def _show_aux(self) -> None:
        aux = self._state.aux[-1]
        if aux.aux_id in self._aux_objects:
            return
        title, block = self._aux_blocks[aux.aux_id]
        object_id = await self._stage.stage_aux(aux.aux_id, title, block)
        self._aux_objects[aux.aux_id] = object_id
        await self._stage.reveal_aux(object_id)

    async def _retire_aux(self, aux: AuxRef | None) -> None:
        if aux is None:
            return
        self._aux_blocks.pop(aux.aux_id, None)
        object_id = self._aux_objects.pop(aux.aux_id, None)
        if object_id is None:
            return
        try:
            await self._stage.retire([object_id])
        except Exception:
            self._orphans.append(object_id)  # kept in the ledger, retried at stop and at the next start
            raise

    async def _retire_all(self) -> list[tuple[str, str]]:
        ids = [*self._aux_objects.values(), *self._orphans]
        self._aux_blocks.clear()
        if not ids:
            return []
        try:
            await self._stage.retire(ids)
        except Exception as exc:  # noqa: BLE001 - captured as an error row; ids stay in the ledger, the stop goes on
            self._orphans = ids
            self._trace("playback_aux_retire_failed", "Ressources auxiliaires non retirees de la scene", level="error",
                        data={"error_class": type(exc).__name__, "error": _clip(exc), "count": len(ids)})
            return [("aux_retire_failed", _clip(exc))]
        self._aux_objects, self._orphans = {}, []
        return []

    # ------------------------------------------------------------------ internals: plan refresh, edits

    async def _refresh_plan(self, why: str) -> None:
        """Re-read variant and score; rebase the run on the same item. A score that no longer resolves keeps the old plan,
        pauses the run and says why (the removed scene stays a visible problem, not a crash)."""

        old, state = self._plan, self._state
        variant = await self._studio.get_variant(self._presentation_id, self._variant_id)
        document = await self._studio.get_score(self._presentation_id, self._variant_id)
        if document["problems"]:
            self._notice("score_problems")
            # The last good plan keeps playing (the problem stays on screen); only its base moves, so the overlay of the
            # scenes that still exist is rendered against the variant as it is now.
            self._plan = replace(old, variant_revision=variant.revision)
            self._pause_for_problem("score_problems")
            self._trace("playback_plan_problems", "Partition incoherente apres modification", level="warning",
                        data={"why": why, "problems": len(document["problems"])})
            return
        new = compile_plan(parse_score(document["score"]), variant.scenes, variant_revision=variant.revision)
        if (new.score_revision, new.variant_revision) == (old.score_revision, old.variant_revision):
            return
        rebased, problem = rebase(old, state, new)
        self._plan, self._scenes = new, {scene.scene_id: scene for scene in variant.scenes}
        transition = settle_after_rebase(new, state, rebased)
        self._state = replace(transition.state, problems=(*transition.state.problems, *([problem] if problem else []))[-8:])
        self._trace("playback_plan_refreshed", "Plan de lecture relu", data={
            "why": why, "score_revision": new.score_revision, "variant_revision": new.variant_revision,
            "position": self._state.position + 1, "problem": problem})
        if Effect.ARM_CHANGED in transition.effects:
            await self._publish_armed()

    def _add_problem(self, code: str) -> None:
        if code not in self._state.problems:
            self._state = replace(self._state, problems=(*self._state.problems, code)[-8:])

    def _pause_for_problem(self, code: str) -> None:
        if self._state.phase in (Phase.PLAYING, Phase.RESUMING):
            self._feed(EventKind.STAGE_FAILED, problem=code)
        else:
            self._add_problem(code)

    async def _check_art_direction_revision(self) -> None:
        """Art direction is saved apart from the variant (`variant.revision` does not move): compare its own revision."""

        if self._gate is None or self._da_revision is None:
            return
        resolution = await self._gate.require_art_direction(self._presentation_id, self._variant_id,
                                                            serious=self._state.role is not StudioRole.REHEARSAL)
        revision = (resolution.get("art_direction") or {}).get("revision")
        if revision != self._da_revision:
            self._trace("playback_art_direction_changed", "La direction artistique a change pendant la lecture",
                        level="warning", data={"was": self._da_revision, "now": revision})
            self._notice("art_direction_changed")
            self._da_revision = revision

    async def _edit_during_run(self, actor: StudioActor, basis: int | None, ops: list[Any]) -> PlaybackResult:
        if self._plan is None or not self._state.active:
            return self._refused("edit", RefusalCode.NOT_RUNNING, "no presentation is running")
        if self._state.phase in (Phase.PLAYING, Phase.RESUMING):
            pause = await self._dispatch("edit_pause", EventKind.PAUSE)
            if pause.status is PlaybackStatus.REFUSED:
                return self._refused("edit", RefusalCode(pause.reason), pause.message or "the run cannot be paused now")
        await self._refresh_plan("edit")
        request = {"actor": actor.value, "mode": "commit", "ops": ops,
                   "basis": {"variant_revision": basis if basis is not None else self._plan.variant_revision}}
        self._own_edit = True
        try:
            result = await self._edit.edit(self._presentation_id, self._variant_id, request)
        finally:
            self._own_edit = False
        if result.committed and result.changed:
            await self._refresh_plan("edit_committed")
            if self._state.phase in (Phase.PAUSED,):
                try:
                    await self._sync_stage()
                except (StageError, PresentationStudioError) as exc:
                    self._notice("stage_sync_after_edit_failed")
                    self._trace("playback_stage_failed", "La fenetre de scene n'a pas suivi l'edition", level="error",
                                data={"command": "edit", "error": _clip(exc.message)})
            await self._announce("edit_committed")
        self._trace("playback_edit", "Edition explicite pendant la lecture", data={
            "run_id": self._state.run_id, "status": result.status.value, "committed": result.committed,
            "ops": len(ops), "actor": actor.value})
        return PlaybackResult(PlaybackStatus.APPLIED if result.status is EditStatus.APPLIED else PlaybackStatus.REFUSED,
                              "edit", self._view(), None if result.status is EditStatus.APPLIED else result.code,
                              None if result.status is EditStatus.APPLIED else result.message,
                              extra={"edit": result.to_dict()})

    async def _on_edit_committed(self, presentation_id: str, variant_id: str, revision: int) -> None:
        """An edit that did not come through `edit` (the inspector, undo/redo): the run pauses and follows, never plays stale."""

        if self._own_edit or not self._state.active or (presentation_id, variant_id) != (self._presentation_id, self._variant_id):
            return
        async with self._lock:
            if not self._state.active:
                return
            if self._state.phase in (Phase.PLAYING, Phase.RESUMING):
                await self._dispatch("edit_pause", EventKind.PAUSE)  # refused by an item that cannot be interrupted: it plays on
            await self._refresh_plan("foreign_edit")
            if self._state.phase is Phase.PAUSED or self._state.phase is Phase.PLAYING:
                try:
                    await self._sync_stage()
                except (StageError, PresentationStudioError) as exc:
                    self._notice("stage_sync_after_edit_failed")
                    self._trace("playback_stage_failed", "La fenetre de scene n'a pas suivi l'edition", level="error",
                                data={"command": "foreign_edit", "error": _clip(exc.message)})
            await self._announce("edit_committed")

    # ------------------------------------------------------------------ internals: mode, events, views

    def _on_mode(self, state: Any) -> None:
        """A mode change that is not ours stops the run: scripted lines would be withheld (or the room heard) in the wrong mode."""

        if not self._state.active or self._required_mode is None or state.source == STUDIO_RUN_MODE_SOURCE:
            return
        memory = self._memory
        if memory is not None:
            kind = classify_mode_event(applied_epoch=memory.epoch, applied_revision=memory.revision,
                                       event_epoch=state.epoch, event_revision=state.revision, event_source=state.source)
            if kind is not ModeEventKind.FOREIGN_CHANGE:
                return
        elif state.mode is self._required_mode:
            return
        try:
            task = asyncio.get_running_loop().create_task(self._stop_foreign(state.mode.value))
        except RuntimeError:
            return  # no running loop: Core is shutting down, `close` ends the run
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _stop_foreign(self, mode: str) -> None:
        try:
            async with self._lock:
                if self._state.active:
                    self._trace("playback_mode_changed", "Mode change par l'utilisateur : la lecture s'arrete",
                                level="warning", data={"mode": mode, "run_id": self._state.run_id})
                    await self._guarded("stop", self._dispatch("stop", EventKind.STOP, stop_reason="mode_changed_by_user"))
        except Exception as exc:  # noqa: BLE001 - captured as an error row: this runs in a background task, nothing awaits it
            self._trace("playback_foreign_stop_failed", "Arret apres changement de mode en echec", level="error",
                        data={"error_class": type(exc).__name__, "error": _clip(exc)})

    async def _publish_armed(self) -> None:
        self._armed_until = self._monotonic() + self._armed_ttl_s
        self._reports.clear()
        if self._bus is None:
            return
        try:
            await self._bus.publish(ProtocolEnvelope(message_type=ARMED_CHANGED, payload=changed_payload(self._state)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the follower pulls on subscribe: a lost message is recovered, but said
            self._trace("armed_publish_failed", "Changement d'ensemble arme non diffuse", level="error",
                        data={"error_class": type(exc).__name__, "generation": self._state.generation})

    async def _announce(self, status: str) -> None:
        if self._events is None:
            return
        self._event_seq += 1
        try:
            self._events.changed(presentation_id=self._presentation_id, variant_id=self._variant_id, status=status,
                                 role=self._state.role.value if self._state.role else None,
                                 depth=len(self._state.aux), run_id=self._state.run_id or "none", seq=self._event_seq)
        except Exception as exc:  # noqa: BLE001 - observability never undoes a playback command; the failure is journaled
            self._trace("event_failed", "Evenement de lecture non pose", level="warning",
                        data={"error_class": type(exc).__name__, "status": status})

    def _view(self) -> dict[str, Any]:
        state = self._state
        view = where_are_we(self._plan, state, self._ms())
        if self._plan is None or state.phase is Phase.IDLE:
            return view
        view.update({"presentation_id": self._presentation_id, "variant_id": self._variant_id,
                     "stage_object_id": self._stage.stage_object_id if state.active else None,
                     "art_direction": self._art_direction if state.active else None,
                     "notices": list(self._notices), "mode": self._required_mode.value if self._required_mode else None})
        if self._last_ended is not None and not state.active:
            view["last_run"] = dict(self._last_ended)
        return view

    def _refused(self, name: str, code: RefusalCode, message: str, *, extra: Mapping[str, Any] | None = None) -> PlaybackResult:
        return PlaybackResult(PlaybackStatus.REFUSED, name, self._view(), code.value, message, extra or {})

    def _notice(self, code: str) -> None:
        if code not in self._notices:
            self._notices = [*self._notices, code][-MAX_NOTICES:]

    def _ms(self) -> int:
        return int(self._monotonic() * 1000)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(f"{TRACE}.{kind}", message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a playback command
            pass


#: Command name -> the status word of the conversation event it produces (`None`: no event, movement is not news).
_STATUS_OF = {"start": "started", "pause": "paused", "resume": "resumed", "detour": "detour", "return": "returned",
              "edit_pause": "paused"}


def _set_op(scene_id: str, control_id: str, value: Any) -> dict[str, Any]:
    return {"op": "control.set", "scene_id": scene_id, "control_id": control_id, "value": value}


def _problem_code(code: str) -> str:
    return ("stage_" + code)[:64] if not code.startswith("stage") else code[:64]


def _clip(value: object, limit: int = 300) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"

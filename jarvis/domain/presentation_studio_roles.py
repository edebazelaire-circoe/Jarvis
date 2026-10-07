"""Playback roles of the Presentation Studio and the speech authority they need (Slice 01c, decision A).

Pure contract, no I/O, no service. It answers three questions that Slices 12, 14
and 15 would otherwise each answer in their own way:

1. **Which interaction mode must a playback role run in?** (`requirements`)
2. **May this request switch the mode at all?** (`plan_mode_entry`; only an
   explicit user request may, ambient text and everything else never)
3. **What must happen to the mode when the run ends or someone else changed it?**
   (`classify_mode_event`, `decide_restore`)

plus the one argument set a scripted Jarvis line is sent with
(`ScoreLineNotice` -> `BrainOrchestrator.announce_notice`).

Decision A (PM, 2026-10-08, Human standing autonomy): a Jarvis-presented run, and a
rehearsal in which Jarvis speaks, run **outside** PRESENTATION (ASSISTANT, user label
SIMPLE). Nothing here touches the authority matrix (`presentation_policy.py`),
`LOCKED_DECISIONS` or `PresentationSpeechGate`: outside PRESENTATION the gate is inert
(`mode_not_presentation`). The contract is `docs/presentation-studio.md` >
*Playback roles and speech authority*.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from jarvis.domain.brain_notice import MAX_NOTICE_TTL_S, MIN_NOTICE_TTL_S, NoticeTyping
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.v2 import BRAIN_NOT_ADDRESSED_ANSWER, SpeechKind

#: `source` sent to `InteractionModeService.request` by a studio run, for the switch **and** the
#: restore. `BoardService` must not persist it as the Board preference (see
#: `TRANSIENT_MODE_SOURCES`), otherwise a Core restart mid-run would keep the temporary mode.
STUDIO_RUN_MODE_SOURCE = "presentation_studio_run"
#: Sources that are a temporary, run-scoped mode and never a user preference.
TRANSIENT_MODE_SOURCES = frozenset({STUDIO_RUN_MODE_SOURCE})

#: Kind of every scripted line. `progress` is transient: it carries a deadline, is never retained as a
#: public outcome or fact (so a rehearsal leaves nothing durable) and dies as `stale_source` when the
#: user starts a new intention. `result` would be retained and handed back to the brain; `error` and
#: `question` are safety kinds the notice contract refuses.
SCORE_LINE_KIND = SpeechKind.PROGRESS
#: Default deadline of a scripted line, counted from its creation in Core. A line is issued just in
#: time (one at a time), so this only has to cover the queue wait, not the script.
DEFAULT_SCORE_LINE_TTL_S = 30.0
SUPERSEDES_PREFIX = "presentation_studio:"

_RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class StudioRole(StrEnum):
    """Who delivers the presentation (docs/06 R-playback; Slice 12 owns the state machine)."""

    USER_PRESENTER = "user_presenter"
    JARVIS_PRESENTER = "jarvis_presenter"
    REHEARSAL = "rehearsal"


class AmbientLanePolicy(StrEnum):
    #: Ambient room speech may satisfy a pre-armed cue id and nothing else (R5, Slice 13).
    ARMED_CUES_ONLY = "armed_cues_only"
    #: No ambient lane at all: the mode is not PRESENTATION, the session is stopped (nothing of the room survives).
    OFF = "off"


class SpeechPolicy(StrEnum):
    #: The PRESENTATION matrix as it is: silence unless explicitly addressed; the only non-spoken
    #: output is an authorized visual cue action (Slice 13).
    PRESENTATION_SILENCE = "presentation_silence"
    #: Core speaks the score's lines verbatim through `announce_notice` (`ScoreLineNotice`).
    SCORE_LINES = "score_lines"


class SwitchOrigin(StrEnum):
    """Where a request to enter a role (hence maybe to switch the mode) came from."""

    #: The user asked, in so many words or by a click, to present or rehearse (voice turn admitted as
    #: addressed, or Control Center action). The only origin that may switch the mode.
    EXPLICIT_USER_REQUEST = "explicit_user_request"
    #: Room speech heard by the ambient lane. Never has authority (D03/HD3).
    AMBIENT_TEXT = "ambient_text"
    #: Text carried by a score, a cue or a scene (content is data, not a command).
    SCORE_CONTENT = "score_content"
    #: The brain on its own initiative (no user request in the turn).
    BRAIN_SPONTANEOUS = "brain_spontaneous"
    #: Core start, Board restore, retries: they replay a stored preference, they do not start a run.
    SYSTEM_REPLAY = "system_replay"


#: The allow-list. A new `SwitchOrigin` member is refused until it is added here on purpose.
_MODE_SWITCH_ORIGINS = frozenset({SwitchOrigin.EXPLICIT_USER_REQUEST})


@dataclass(frozen=True, slots=True)
class RoleRequirements:
    role: StudioRole
    jarvis_speaks: bool
    mode: InteractionMode
    ambient_lane: AmbientLanePolicy
    speech: SpeechPolicy


def requirements(role: StudioRole, *, jarvis_speaks: bool | None = None) -> RoleRequirements:
    """Mode, ambient-lane and speech policy a role needs.

    `jarvis_speaks` only matters for `REHEARSAL` (default: Jarvis silent). `JARVIS_PRESENTER` always
    speaks; `USER_PRESENTER` never does (Jarvis is a sidekick: visual cue actions only).
    """

    role = StudioRole(role)
    if role is StudioRole.USER_PRESENTER:
        if jarvis_speaks:
            raise ValueError("the user presenter role has a silent Jarvis (visual cue actions only)")
        speaks = False
    elif role is StudioRole.JARVIS_PRESENTER:
        if jarvis_speaks is False:
            raise ValueError("the Jarvis presenter role speaks by definition")
        speaks = True
    else:
        speaks = bool(jarvis_speaks)
    if speaks:
        return RoleRequirements(role, True, InteractionMode.ASSISTANT, AmbientLanePolicy.OFF, SpeechPolicy.SCORE_LINES)
    return RoleRequirements(role, False, InteractionMode.PRESENTATION, AmbientLanePolicy.ARMED_CUES_ONLY,
                            SpeechPolicy.PRESENTATION_SILENCE)


def mode_switch_allowed(origin: SwitchOrigin) -> bool:
    """Only an explicit user request may switch the interaction mode for a run. Everything else: no."""

    try:
        return SwitchOrigin(origin) in _MODE_SWITCH_ORIGINS
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class ModePlan:
    allowed: bool
    #: `ok`, `already_in_mode` or `mode_switch_origin_refused` (stable, loggable).
    code: str
    #: Mode the run needs, `None` when refused.
    target: InteractionMode | None
    #: True when `InteractionModeService.request(target, source=STUDIO_RUN_MODE_SOURCE)` must be called.
    switch_needed: bool
    source: str = STUDIO_RUN_MODE_SOURCE


def plan_mode_entry(role: StudioRole, origin: SwitchOrigin, current_mode: InteractionMode, *,
                    jarvis_speaks: bool | None = None) -> ModePlan:
    """Decide whether a run may start and whether the mode has to change first."""

    needed = requirements(role, jarvis_speaks=jarvis_speaks).mode
    if not mode_switch_allowed(origin):
        return ModePlan(False, "mode_switch_origin_refused", None, False)
    if InteractionMode(current_mode) is needed:
        return ModePlan(True, "already_in_mode", needed, False)
    return ModePlan(True, "ok", needed, True)


class ModeEventKind(StrEnum):
    #: The event is the run's own switch (or an older one): nothing to do.
    OWN_OR_STALE = "own_or_stale"
    #: Someone else (Control Center click, Board switch, retry) changed the mode during the run.
    FOREIGN_CHANGE = "foreign_change"
    #: Core restarted (different epoch): the run's in-memory state is gone, the stored preference rules.
    CORE_RESTARTED = "core_restarted"


def classify_mode_event(*, applied_epoch: str, applied_revision: int, event_epoch: str, event_revision: int,
                        event_source: str) -> ModeEventKind:
    """Read one `interaction.mode.changed` payload against the revision the run's own switch produced."""

    if event_epoch != applied_epoch:
        return ModeEventKind.CORE_RESTARTED
    if event_revision <= applied_revision or event_source in TRANSIENT_MODE_SOURCES:
        return ModeEventKind.OWN_OR_STALE
    return ModeEventKind.FOREIGN_CHANGE


class RestoreAction(StrEnum):
    #: Call `request(previous_mode, source=STUDIO_RUN_MODE_SOURCE)`.
    RESTORE = "restore"
    #: Nothing to do (no switch was applied, or the mode is already the previous one).
    NONE = "none"
    #: The user changed the mode meanwhile: their choice wins, the remembered mode is dropped.
    LEAVE_USER_CHOICE = "leave_user_choice"
    #: Core restarted: Board preference was reapplied by `BoardService`, restoring would be a second writer.
    CORE_RESTARTED = "core_restarted"


@dataclass(frozen=True, slots=True)
class RestoreDecision:
    action: RestoreAction
    code: str
    target: InteractionMode | None = None


def decide_restore(*, previous_mode: InteractionMode | None, applied_epoch: str | None,
                   applied_revision: int | None, current_mode: InteractionMode, current_epoch: str,
                   current_revision: int) -> RestoreDecision:
    """What to do with the mode when the run ends, stops or crashes.

    `previous_mode`/`applied_*` are what the run remembered **only if its own switch was `APPLIED`**
    (`None` when the mode already matched: `UNCHANGED`, nothing to restore).
    """

    if previous_mode is None or applied_revision is None or applied_epoch is None:
        return RestoreDecision(RestoreAction.NONE, "no_switch_applied")
    if current_epoch != applied_epoch:
        return RestoreDecision(RestoreAction.CORE_RESTARTED, "core_restarted")
    if current_revision != applied_revision:
        return RestoreDecision(RestoreAction.LEAVE_USER_CHOICE, "mode_changed_during_run")
    if InteractionMode(current_mode) is InteractionMode(previous_mode):
        return RestoreDecision(RestoreAction.NONE, "already_previous_mode")
    return RestoreDecision(RestoreAction.RESTORE, "ok", InteractionMode(previous_mode))


@dataclass(frozen=True, slots=True)
class ScoreLineNotice:
    """The exact `announce_notice` call of one scripted Jarvis line.

    `announce_notice(text, **notice.call_kwargs())`. There is no `verbatim` argument: the text is
    never rephrased by construction (Decision 13); `work_id` is left out on purpose (a work id wires the
    line into the work-dependency machinery of a brain job that does not exist).
    """

    text: str
    run_id: str
    ttl_s: float = DEFAULT_SCORE_LINE_TTL_S

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("a score line has text")
        if self.text.strip().casefold() == BRAIN_NOT_ADDRESSED_ANSWER.casefold():
            # `announce_notice` would drop it silently as the agreed "not for me" reply.
            raise ValueError("a score line cannot be the not-addressed marker")
        if not isinstance(self.run_id, str) or not _RUN_ID.fullmatch(self.run_id):
            raise ValueError("run_id is 1-64 characters of [A-Za-z0-9_-]")
        if not MIN_NOTICE_TTL_S <= self.ttl_s <= MAX_NOTICE_TTL_S:
            raise ValueError(f"ttl_s must be in [{MIN_NOTICE_TTL_S:g}, {MAX_NOTICE_TTL_S:g}]")
        # Same validation as the runtime (kind, key grammar, deadline).
        NoticeTyping(**self.call_kwargs())

    @property
    def supersedes_key(self) -> str:
        """One speech slot per run: a new line replaces an unstarted one (seek, skip), never another run's."""

        return f"{SUPERSEDES_PREFIX}{self.run_id}"

    def call_kwargs(self) -> dict[str, object]:
        return {"kind": SCORE_LINE_KIND, "supersedes_key": self.supersedes_key, "ttl_s": float(self.ttl_s)}

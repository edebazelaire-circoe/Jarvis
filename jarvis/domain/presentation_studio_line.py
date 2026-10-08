"""Progress of one scripted Jarvis line, pure (handoff jarvis-interactive-presentation-studio, Slice 14).

The Jarvis presenter issues a score line through `BrainOrchestrator.announce_notice` and then **only observes** what the
existing speech stack says about it: the facts are the conversation events the Voice process already records
(`brain.speech.requested`, `mouth.speech.started / completed / interrupted / superseded / expired / failed / unconfirmed`,
`mouth.floor.taken`). This module folds those facts into a `SpeechLine`, with the same phase vocabulary as
`jarvis/runtime/tool_brain_speech.py` (pending, playing, heard, interrupted, obsolete, unconfirmed): one source of truth
for "what happened to this speech", not a second one. `tests/unit/test_presentation_studio_line.py` pins the parity.

A fact carries ids, a kind and a time. **Never the text**: a mouth event stored by Core carries the spoken text as its
`content`; the presenter's listener copies none of it, and this module has no field that could hold it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from jarvis.domain.conversation_events import ConversationEventType as T


class LinePhase(StrEnum):
    #: Handed to Core (`announce_notice` returned True), not started by the mouth yet. Same word as tool_brain_speech.PENDING.
    PENDING = "pending"
    PLAYING = "playing"
    HEARD = "heard"
    INTERRUPTED = "interrupted"
    #: Superseded or expired before it started (replaced by a later line, a new intention, a deadline).
    OBSOLETE = "obsolete"
    UNCONFIRMED = "unconfirmed"
    #: The speech stack failed to speak it (`mouth.speech.failed`).
    FAILED = "failed"


class FactKind(StrEnum):
    REQUESTED = "requested"
    STARTED = "started"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    FAILED = "failed"
    UNCONFIRMED = "unconfirmed"
    #: The user took the floor: not tied to one speech.
    FLOOR_TAKEN = "floor_taken"
    #: An admitted user turn (explicit address): not tied to one speech.
    USER_TURN = "user_turn"


#: The conversation events the presenter listens to, and nothing else.
FACT_OF_EVENT: dict[T, FactKind] = {
    T.BRAIN_SPEECH_REQUESTED: FactKind.REQUESTED,
    T.MOUTH_SPEECH_STARTED: FactKind.STARTED,
    T.MOUTH_SPEECH_COMPLETED: FactKind.COMPLETED,
    T.MOUTH_SPEECH_INTERRUPTED: FactKind.INTERRUPTED,
    T.MOUTH_SPEECH_SUPERSEDED: FactKind.SUPERSEDED,
    T.MOUTH_SPEECH_EXPIRED: FactKind.EXPIRED,
    T.MOUTH_SPEECH_FAILED: FactKind.FAILED,
    T.MOUTH_SPEECH_UNCONFIRMED: FactKind.UNCONFIRMED,
    T.MOUTH_FLOOR_TAKEN: FactKind.FLOOR_TAKEN,
    T.USER_TRANSCRIPT_ACCEPTED: FactKind.USER_TURN,
}

_PHASE_OF_TERMINAL = {
    FactKind.COMPLETED: LinePhase.HEARD, FactKind.INTERRUPTED: LinePhase.INTERRUPTED,
    FactKind.SUPERSEDED: LinePhase.OBSOLETE, FactKind.EXPIRED: LinePhase.OBSOLETE,
    FactKind.FAILED: LinePhase.FAILED, FactKind.UNCONFIRMED: LinePhase.UNCONFIRMED,
}
TERMINAL = frozenset({LinePhase.HEARD, LinePhase.INTERRUPTED, LinePhase.OBSOLETE, LinePhase.UNCONFIRMED, LinePhase.FAILED})


@dataclass(frozen=True, slots=True)
class SpeechFact:
    """One observed fact, stamped with the presenter's own monotonic clock when it arrived."""

    kind: FactKind
    at_ms: int
    speech_id: str | None = None
    #: A token (`user_barge_in`, `delivery_not_complete`...), never a sentence.
    reason: str | None = None
    played_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SpeechLine:
    """A line handed to the speech stack. `tag` names what it belongs to (an item id, or `item:step`), never its text."""

    tag: str
    issued_ms: int
    chars: int
    speech_id: str | None = None
    phase: LinePhase = LinePhase.PENDING
    started_ms: int | None = None
    ended_ms: int | None = None
    reason: str | None = None
    played_ms: int | None = None

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL

    @property
    def started(self) -> bool:
        return self.started_ms is not None

    def wait_ms(self, now_ms: int) -> int:
        return max(0, now_ms - self.issued_ms)


def observe(line: SpeechLine, fact: SpeechFact) -> SpeechLine:
    """Fold one fact. A fact for another speech, or after the end of this one, changes nothing.

    `REQUESTED` binds the speech id (the presenter only passes it for its own `supersedes_key`), once.
    """

    if fact.kind is FactKind.REQUESTED:
        return line if line.speech_id is not None or fact.speech_id is None else replace(line, speech_id=fact.speech_id)
    if fact.kind in (FactKind.FLOOR_TAKEN, FactKind.USER_TURN) or line.terminal:
        return line
    if line.speech_id is None or fact.speech_id != line.speech_id:
        return line
    if fact.kind is FactKind.STARTED:
        return replace(line, phase=LinePhase.PLAYING, started_ms=fact.at_ms) if not line.started else line
    # A line that was said (or cut while being said) has started, even if the `started` fact was lost: the earliest instant we know.
    started = line.started_ms if line.started_ms is not None else (
        fact.at_ms if fact.kind in (FactKind.COMPLETED, FactKind.INTERRUPTED) else None)
    return replace(line, phase=_PHASE_OF_TERMINAL[fact.kind], started_ms=started, ended_ms=fact.at_ms, reason=fact.reason,
                   played_ms=fact.played_ms if fact.played_ms is not None else line.played_ms)

"""Doubles and score contents for the Jarvis presenter tests (jarvis-interactive-presentation-studio, Slice 14).

`FakeBrain` is `BrainOrchestrator.announce_notice` as far as the presenter can tell: it records the call and, like Core, records a
`brain.speech.requested` fact carrying the `supersedes_key`. `Voice` plays the part of the Voice process: the `mouth.speech.*` and
`mouth.floor.taken` facts the existing speech stack records. Nothing here is a second speech stack; the real one is exercised in
`test_presentation_studio_presenter_speech.py`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from jarvis.core.presentation_studio_events import StudioPresenterEvents
from jarvis.core.presentation_studio_presenter import PresentationStudioPresenter
from jarvis.domain.conversation_events import ConversationEventType as T
from tests.unit.test_presentation_studio_playback_service import I1, I2, I3, I4, S1, S2, S3

#: Markers that must never appear in a log, a trace, an event or a view: they stand for the spoken script and the user's notes.
SECRET = "ZXQV-LIGNE"
NOTE_SECRET = "ZXQV-NOTE"

TEXT_A, TEXT_D = f"Bonjour {SECRET} un.", f"Merci {SECRET} fin."
SEQ_INTRO, SEQ_WRAP = f"Regardez {SECRET} intro.", f"Voila {SECRET} wrap."


def lines_content() -> dict:
    """I1 Jarvis line -> I2 explicit silence (2000 ms, with a bound action) -> I3 the user's -> I4 Jarvis line."""

    return {
        "start_item_id": I1,
        "items": [
            {"item_id": I1, "scene_id": S1, "presenter": "jarvis", "kind": "speech", "text": TEXT_A, "label": "Ouverture",
             "visual": [{"kind": "control_set", "scene_id": S1, "control_id": "headline", "value": "Un"}], "next_item_id": I2},
            {"item_id": I2, "scene_id": S2, "presenter": "none", "kind": "silence", "target_duration_ms": 2000,
             "motion": [{"kind": "control_set", "scene_id": S2, "control_id": "density", "value": "compact"}],
             "next_item_id": I3},
            {"item_id": I3, "scene_id": S2, "presenter": "user", "kind": "speech", "note": f"Explique {NOTE_SECRET}",
             "next_item_id": I4},
            {"item_id": I4, "scene_id": S3, "presenter": "jarvis", "kind": "speech", "text": TEXT_D,
             "visual": [{"kind": "reveal", "scene_id": S3, "anchor_id": "reveal"}]}],
        "cues": [], "sequences": [], "recovery_points": []}


def locked_content(*, interruption: str = "at_boundary", on_interrupt: str = "pause_resume", recovery: str = "continue_item") -> dict:
    """I1 line -> I2 host of the locked sequence `demo` (9000 ms) -> I3 line.

    Steps: `intro` @0 (Jarvis, reveals marker), `mid` @3000 (silent, density), `wrap` @6500 (Jarvis, headline)."""

    steps = [
        {"step_id": "intro", "offset_ms": 0, "speaker": "jarvis", "text": SEQ_INTRO,
         "visual": [{"kind": "reveal", "scene_id": S2, "anchor_id": "marker"}]},
        {"step_id": "mid", "offset_ms": 3000,
         "motion": [{"kind": "control_set", "scene_id": S2, "control_id": "density", "value": "compact"}]},
        {"step_id": "wrap", "offset_ms": 6500, "speaker": "jarvis", "text": SEQ_WRAP,
         "visual": [{"kind": "control_set", "scene_id": S2, "control_id": "headline", "value": "Fin"}]}]
    host = {"item_id": I2, "scene_id": S2, "presenter": "jarvis", "kind": "speech", "label": "Demo",
            "visual": [{"kind": "sequence", "sequence_id": "demo"}], "timing": "locked", "interruption": interruption,
            "target_duration_ms": 9000, "recovery": recovery, "next_item_id": I3}
    sequence = {"sequence_id": "demo", "label": "Demo", "duration_ms": 9000, "on_interrupt": on_interrupt, "steps": steps}
    recovery_points = []
    if on_interrupt == "abort_to_recovery":
        sequence["recovery_id"] = "demo_start"
        recovery_points = [{"recovery_id": "demo_start", "label": "Demo start", "item_id": I2}]
    if recovery == "recovery_point":
        host["recovery_point_id"] = "demo_start"
        recovery_points = [{"recovery_id": "demo_start", "label": "Demo start", "item_id": I2}]
    return {
        "start_item_id": I1,
        "items": [
            {"item_id": I1, "scene_id": S1, "presenter": "jarvis", "kind": "speech", "text": TEXT_A, "next_item_id": I2},
            host,
            {"item_id": I3, "scene_id": S3, "presenter": "jarvis", "kind": "speech", "text": TEXT_D}],
        "cues": [], "sequences": [sequence], "recovery_points": recovery_points}


def item_content(*, interruption: str = "allow", recovery: str = "continue_item", recovery_point: bool = False) -> dict:
    """I1 line with the given interruption / recovery -> I2 line -> I3 line (a plain item can allow interruption)."""

    first = {"item_id": I1, "scene_id": S1, "presenter": "jarvis", "kind": "speech", "text": TEXT_A,
             "interruption": interruption, "recovery": recovery, "next_item_id": I2}
    points = []
    if recovery == "recovery_point":
        first["recovery_point_id"] = "back"
        points = [{"recovery_id": "back", "label": "Back", "item_id": I1}]
    return {
        "start_item_id": I1,
        "items": [first,
                  {"item_id": I2, "scene_id": S2, "presenter": "jarvis", "kind": "speech", "text": f"Deux {SECRET}.",
                   "next_item_id": I3},
                  {"item_id": I3, "scene_id": S3, "presenter": "jarvis", "kind": "speech", "text": TEXT_D}],
        "cues": [], "sequences": [], "recovery_points": points}


class Ev(SimpleNamespace):
    """A conversation event as the presenter's listener reads it: type, speech id, attributes; `content` is the spoken text
    (a stored mouth/brain event carries it), so a leak of it is detectable."""


class FakeBrain:
    """`announce_notice` of Core, as far as the presenter can tell."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.published = True
        self.error: Exception | None = None
        self.presenter: PresentationStudioPresenter | None = None
        self.count = 0
        self.last_id: str | None = None

    async def announce_notice(self, text: str, **kwargs: Any) -> bool:
        self.calls.append((text, dict(kwargs)))
        if self.error is not None:
            raise self.error
        if not self.published:
            return False
        self.count += 1
        self.last_id = f"sp-{self.count:04d}"
        if self.presenter is not None:
            self.presenter.on_event(Ev(event_type=T.BRAIN_SPEECH_REQUESTED, speech_id=self.last_id, content=text,
                                       attributes={"kind": "progress", "supersedes_key": kwargs.get("supersedes_key")}))
        return True

    @property
    def texts(self) -> list[str]:
        return [text for text, _ in self.calls]


class Voice:
    """The facts the Voice process records about the line Core just handed over."""

    def __init__(self, presenter: PresentationStudioPresenter, brain: FakeBrain) -> None:
        self.presenter, self.brain = presenter, brain

    def _send(self, event_type: T, speech_id: str | None, **attributes: Any) -> None:
        self.presenter.on_event(Ev(event_type=event_type, speech_id=speech_id, attributes=attributes, content=SECRET))

    def started(self, speech_id: str | None = None) -> None:
        self._send(T.MOUTH_SPEECH_STARTED, speech_id or self.brain.last_id)

    def completed(self, speech_id: str | None = None) -> None:
        self._send(T.MOUTH_SPEECH_COMPLETED, speech_id or self.brain.last_id)

    def interrupted(self, speech_id: str | None = None, *, played_ms: int = 800) -> None:
        self._send(T.MOUTH_SPEECH_INTERRUPTED, speech_id or self.brain.last_id, reason="user_barge_in", played_ms=played_ms)

    def terminal(self, event_type: T, speech_id: str | None = None) -> None:
        self._send(event_type, speech_id or self.brain.last_id)

    def floor(self) -> None:
        self._send(T.MOUTH_FLOOR_TAKEN, None, **{"while": "speaking"})

    def user_turn(self) -> None:
        self._send(T.USER_TRANSCRIPT_ACCEPTED, None)

    def other_speech(self, speech_id: str = "answer-1") -> None:
        """Speech that is not ours (the brain answering the user)."""

        self._send(T.MOUTH_SPEECH_STARTED, speech_id)
        self._send(T.MOUTH_SPEECH_COMPLETED, speech_id)


def make_presenter(rig, *, gap_ms: int = 0, **kwargs: Any) -> tuple[PresentationStudioPresenter, FakeBrain, Voice]:
    """A presenter on the rig's playback service and clock, driven by hand (`pump()`), with Core's event sink."""

    brain = FakeBrain()
    presenter = PresentationStudioPresenter(
        rig.service, brain, events=StudioPresenterEvents(rig.conversation, lambda: "conv-1"), diagnostics=rig.env.sink,
        monotonic=rig.mono, gap_ms=gap_ms, run_loop=False, **kwargs)
    brain.presenter = presenter
    return presenter, brain, Voice(presenter, brain)


def set_ms(rig, ms: int) -> None:
    rig.mono.t = ms / 1000


def now_ms(rig) -> int:
    return round(rig.mono.t * 1000)


def advance(rig, ms: int) -> int:
    set_ms(rig, now_ms(rig) + ms)
    return now_ms(rig)

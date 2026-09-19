"""The guided interaction contract: how a Test Lab run asks a human to do something.

Binding contract: `docs/testlab.md` ("Guided runs"). Locked decision 11: on
`hardware:guided` the human is an explicit scenario actor. This module is the whole
vocabulary and the whole seam of that, and it contains no terminal, no HTTP and no UI:
a runner runs in a worker process that has no console, so it cannot assume one.

Four pieces:

- `GuidedPrompt` — one instruction addressed to the human: a STABLE id, an expected
  action, the sentence to show, a deadline, and whether the step is timing-critical.
- `GuidedPrompter` — the seam. One method: show this prompt and come back when the
  human answered. `HeadlessPrompter` is the test double; `jarvis.testlab.hardware.channel`
  is the implementation a worker actually uses, and Slices 10 (CLI) and 11 (UI) write
  the presenters that face the human.
- `PromptRecord` — the evidence: shown-at, acknowledged-at, how long it took, what the
  human did, and what the microphone observed while they did it.
- `GuidedSession` — drives the prompts, stamps them, records them, and decides what an
  unanswered, refused or late prompt means.

**The human is never a defect.** A human who does not answer, answers late, or refuses
produces `MeasurementUnavailable` — we could not measure — never a `failed` run. Only
the product can fail a diagnostic. A human who does something OTHER than what was asked
(speaks during "remain silent") is recorded as an observation and handed to the
diagnostic: for one diagnostic that invalidates the measurement, for another it IS the
measurement, and the two are told apart by the declaration, not by this module.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import json
import time
from typing import Any, Protocol

from jarvis.testlab.primitives import IDENTIFIER
from jarvis.testlab.runners import MeasurementUnavailable, RunCancelled, RunContext
from jarvis.testlab.runs import ArtifactKind
from jarvis.testlab.validation import (
    check_number,
    check_open_key,
    check_scalar_value,
    check_text,
    fail,
)

#: How long a human gets, by default, before a prompt is considered unanswered.
DEFAULT_PROMPT_DEADLINE_S = 30.0
MAX_PROMPT_DEADLINE_S = 600.0
#: Extra time an answer may take and still arrive, recorded as LATE instead of lost. A
#: human who was reaching for the keyboard has not refused; the run says it was late.
LATE_GRACE_S = 15.0
MAX_PROMPT_TEXT_CHARS = 240
MAX_PROMPT_NOTE_CHARS = 200
MAX_PROMPT_ID_CHARS = 64
#: One guided run addresses a human a bounded number of times. A scenario that needs
#: more is not a diagnostic, it is a chore.
MAX_PROMPTS_PER_RUN = 64

# Stable failure codes (docs/testlab.md, "Errors"). All `MeasurementUnavailable`.
PROMPT_TIMED_OUT = "testlab_guided_prompt_timed_out"
PROMPT_REFUSED = "testlab_guided_prompt_refused"
PROMPT_LATE = "testlab_guided_prompt_late"
PROMPTER_FAILED = "testlab_guided_prompter_failed"
PROMPT_LIMIT = "testlab_guided_prompt_limit"

TRANSCRIPT_ARTIFACT = "guided_prompts.json"
TRANSCRIPT_SCHEMA = "jarvis.testlab.guided_transcript"
TRANSCRIPT_SCHEMA_VERSION = 1


class GuidedAction(StrEnum):
    """What the human is asked to do. Closed: a UI renders one affordance per action."""

    #: Say nothing at all until the step ends. The control condition of any acoustic claim.
    REMAIN_SILENT = "remain_silent"
    #: Say the given phrase, out loud, at a normal volume.
    SAY_PHRASE = "say_phrase"
    #: Start speaking WHILE Jarvis is speaking. Timing is the measurement.
    INTERRUPT = "interrupt"
    #: Confirm that the previous step happened as described. No acoustics.
    ACKNOWLEDGE = "acknowledge"


class PromptOutcome(StrEnum):
    """How one prompt ended. Only the first is a step that went as asked."""

    ACKNOWLEDGED = "acknowledged"
    #: Answered, but after the deadline. Evidence; whether it voids the step is declared.
    LATE = "late"
    #: Never answered within the deadline and its grace.
    TIMED_OUT = "timed_out"
    #: The human declined this step. A legitimate answer, and never a product failure.
    REFUSED = "refused"
    #: The presenter itself broke. Ours, not the human's — but still "could not measure".
    PROMPTER_FAILED = "prompter_failed"


#: Outcomes that mean the human did the step. Everything else stops the measurement.
USABLE_OUTCOMES = frozenset({PromptOutcome.ACKNOWLEDGED, PromptOutcome.LATE})


@dataclass(frozen=True, slots=True)
class GuidedPrompt:
    """One instruction addressed to the human, with everything a presenter needs to show it.

    `prompt_id` is stable and authored: it is how a CLI, a UI and the stored evidence
    all name the same step, and how an acknowledgement is matched to what it answers.
    `deadline_s` is part of the CONTRACT, not a hint: a presenter must show the human how
    long they have and how much of it is left, because a step with no visible countdown
    is indistinguishable from a frozen run.
    """

    prompt_id: str
    action: GuidedAction
    #: The sentence shown to the human. Authored, bounded, and never user data.
    text: str
    deadline_s: float = DEFAULT_PROMPT_DEADLINE_S
    #: The exact words to say, for `say_phrase` and `interrupt`.
    phrase: str | None = None
    #: The human is expected to make sound during this step.
    expects_voice: bool = False
    #: A late answer voids this step's measurement (the timing IS the measurement).
    strict_timing: bool = False

    def __post_init__(self) -> None:
        # Exactly the scenario `prompt_id` argument type (`jarvis.testlab.primitives`,
        # `ArgKind.IDENTIFIER`, as for `turn_id` and `checkpoint_id`), so an id a
        # scenario is allowed to author is an id this prompt accepts.
        if not isinstance(self.prompt_id, str) or len(self.prompt_id) > MAX_PROMPT_ID_CHARS \
                or IDENTIFIER.fullmatch(self.prompt_id) is None:
            raise fail(f"prompt.prompt_id must be a safe identifier of at most {MAX_PROMPT_ID_CHARS} characters")
        if not isinstance(self.action, GuidedAction):
            raise fail("prompt.action must be a GuidedAction")
        check_text(self.text, "prompt.text", max_chars=MAX_PROMPT_TEXT_CHARS)
        check_text(self.phrase, "prompt.phrase", max_chars=MAX_PROMPT_TEXT_CHARS, optional=True)
        check_number(self.deadline_s, "prompt.deadline_s", minimum=0.1, maximum=MAX_PROMPT_DEADLINE_S)
        for name in ("expects_voice", "strict_timing"):
            if type(getattr(self, name)) is not bool:
                raise fail(f"prompt.{name} must be a boolean")
        if self.action in (GuidedAction.SAY_PHRASE, GuidedAction.INTERRUPT) and not self.phrase:
            raise fail(f"prompt.phrase is required for {self.action.value}")

    def to_dict(self) -> dict[str, Any]:
        return {"prompt_id": self.prompt_id, "action": self.action.value, "text": self.text,
                "deadline_s": self.deadline_s, "phrase": self.phrase,
                "expects_voice": self.expects_voice, "strict_timing": self.strict_timing}

    @classmethod
    def from_dict(cls, payload: object) -> GuidedPrompt:
        if not isinstance(payload, Mapping):
            raise fail("prompt must be an object")
        unknown = sorted(set(payload) - _PROMPT_FIELDS)
        if unknown:
            raise fail(f"prompt has unknown field(s): {unknown}")
        action = payload.get("action")
        if not isinstance(action, str) or action not in tuple(item.value for item in GuidedAction):
            raise fail("prompt.action is not a guided action")
        return cls(prompt_id=payload.get("prompt_id"), action=GuidedAction(action), text=payload.get("text"),
                   deadline_s=float(payload.get("deadline_s", DEFAULT_PROMPT_DEADLINE_S)),
                   phrase=payload.get("phrase"), expects_voice=bool(payload.get("expects_voice", False)),
                   strict_timing=bool(payload.get("strict_timing", False)))


_PROMPT_FIELDS = frozenset({"prompt_id", "action", "text", "deadline_s", "phrase", "expects_voice",
                            "strict_timing"})


# ------------------------------------------------------------- default texts

#: What each action says when a scenario authors no sentence of its own. French, because
#: the human at this workstation is addressed in French everywhere else in Jarvis.
DEFAULT_PROMPT_TEXT: Mapping[GuidedAction, str] = {
    GuidedAction.REMAIN_SILENT: "Ne dites rien et restez immobile jusqu'à la fin de cette étape.",
    GuidedAction.SAY_PHRASE: "Dites la phrase indiquée, à voix normale, puis validez.",
    GuidedAction.INTERRUPT: "Dès que Jarvis commence à parler, coupez-le en disant la phrase indiquée.",
    GuidedAction.ACKNOWLEDGE: "Confirmez que l'étape précédente s'est bien passée.",
}


def prompt_for(action: GuidedAction, prompt_id: str, *, text: str | None = None, phrase: str | None = None,
               deadline_s: float = DEFAULT_PROMPT_DEADLINE_S) -> GuidedPrompt:
    """A prompt with this action's defaults: its sentence, whether it expects voice, its timing rule."""
    voice = action in (GuidedAction.SAY_PHRASE, GuidedAction.INTERRUPT)
    return GuidedPrompt(prompt_id=prompt_id, action=action, text=text or DEFAULT_PROMPT_TEXT[action],
                        deadline_s=deadline_s, phrase=phrase, expects_voice=voice,
                        strict_timing=action is GuidedAction.INTERRUPT)


# ----------------------------------------------------------------- the seam

@dataclass(frozen=True, slots=True)
class PromptReply:
    """What a presenter brings back. It reports the human's answer, never the timing.

    Timing is stamped by `GuidedSession` around the call, so a presenter cannot
    understate how long a human took, and a slow presenter cannot be mistaken for a slow
    human — the run measures the whole round trip, which is what the human experienced.
    """

    acknowledged: bool = True
    #: The human declined this step. Honest, and never a product failure.
    refused: bool = False
    #: One bounded line the human or the presenter added.
    note: str | None = None

    def __post_init__(self) -> None:
        for name in ("acknowledged", "refused"):
            if type(getattr(self, name)) is not bool:
                raise fail(f"reply.{name} must be a boolean")
        check_text(self.note, "reply.note", max_chars=MAX_PROMPT_NOTE_CHARS, optional=True)


class GuidedPrompter(Protocol):
    """Show one prompt to a human and come back with their answer.

    The ONLY thing a guided runner knows about the outside world. A presenter must, for
    the whole time it holds the call: show the prompt text, show what the human must do,
    show the deadline and how much of it is left, and offer a way to refuse. It must not
    enforce the deadline itself — `GuidedSession` does, so every prompt is bounded the
    same way whoever is presenting.

    An implementation may raise; the session records `prompter_failed` and stops, because
    a run that cannot reach the human has stopped measuring.
    """

    async def present(self, prompt: GuidedPrompt) -> PromptReply:
        ...


class HeadlessPrompter:
    """The test double: a scripted human, with no terminal and no waiting.

    Every default suite test of the guided profile runs against this. It can answer at
    once, answer after a delay (which the session reads as late), never answer at all, or
    refuse — which is the whole space of human behaviour a guided run has to survive.
    """

    def __init__(self, *, replies: Mapping[str, PromptReply] | None = None,
                 default: PromptReply | None = PromptReply(),
                 delays: Mapping[str, float] | None = None, delay: float = 0.0,
                 raises: Sequence[str] = ()) -> None:
        self._replies = dict(replies or {})
        self._default = default
        self._delays = dict(delays or {})
        self._delay = float(delay)
        self._raises = frozenset(raises)
        #: Every prompt this double was shown, in order.
        self.shown: list[GuidedPrompt] = []

    async def present(self, prompt: GuidedPrompt) -> PromptReply:
        self.shown.append(prompt)
        if prompt.prompt_id in self._raises:
            raise RuntimeError(f"the scripted presenter cannot show {prompt.prompt_id}")
        delay = self._delays.get(prompt.prompt_id, self._delay)
        if delay:
            await asyncio.sleep(delay)
        reply = self._replies.get(prompt.prompt_id, self._default)
        if reply is None:
            # "The human is not there": never answers. The session's deadline ends it.
            await asyncio.Event().wait()
        return reply


# ---------------------------------------------------------------- evidence

@dataclass(slots=True)
class PromptRecord:
    """One prompt as run evidence: what was asked, when, what came back, what was heard.

    Times are UTC milliseconds, the wire form Conversation Events already use, so a
    guided transcript joins the rest of a run's evidence without conversion.
    """

    prompt: GuidedPrompt
    shown_at: int
    acknowledged_at: int | None
    response_ms: int | None
    outcome: PromptOutcome
    note: str | None = None
    #: What the microphone observed while the step was open, when the runner measured it.
    observed_voice: bool | None = None
    observed_peak_dbfs: float | None = None
    #: WHY `observed_voice` says what it says: the levels and the flag that decided it, so
    #: a reader can tell a person from Jarvis's own echo without rerunning anything. Free
    #: JSON scalars, bounded, supplied by the runner (`RoomVoice.to_dict`).
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.outcome in USABLE_OUTCOMES

    @property
    def followed(self) -> bool | None:
        """Did the human do what the step asked? `None` when nothing was observed.

        This is an OBSERVATION, not a verdict: a mismatch is handed to the diagnostic,
        which decides whether it voids the measurement (speech during "remain silent"
        voids a self-echo claim) or IS the measurement (speech during "interrupt").
        """
        if self.observed_voice is None or not self.usable:
            return None
        return self.observed_voice == self.prompt.expects_voice

    def to_dict(self) -> dict[str, Any]:
        return {**self.prompt.to_dict(), "shown_at": self.shown_at, "acknowledged_at": self.acknowledged_at,
                "response_ms": self.response_ms, "outcome": self.outcome.value, "note": self.note,
                "observed_voice": self.observed_voice, "observed_peak_dbfs": self.observed_peak_dbfs,
                "followed": self.followed, **self.evidence}


class GuidedPromptUnavailable(MeasurementUnavailable):
    """The human did not perform a step, so there is nothing to measure.

    Never `failed`: only the product can fail a diagnostic. Never `crashed`: a human who
    stepped away, declined, or answered a beat too late is a fact about the session, and
    a lab that recorded it as its own defect would be lying about who did what.
    """


# ------------------------------------------------------------- the session

@dataclass(slots=True)
class GuidedSession:
    """Drives the prompts of one run: asks, stamps, records, and decides what an answer means.

    It owns the deadline, so every presenter is bounded identically; it owns the clock,
    so no presenter can understate a delay; and it owns the failure vocabulary, so every
    way a human can not do a step lands on `MeasurementUnavailable` with its own code.
    """

    context: RunContext
    prompter: GuidedPrompter
    #: Extra time an answer may still arrive in, recorded as late. A factory, not a
    #: literal default, so the module constant is read when a session is BUILT: a caller
    #: (or a test) that lowers `LATE_GRACE_S` gets the value it set.
    grace_s: float = field(default_factory=lambda: LATE_GRACE_S)
    #: UTC seconds. Injected so a test can pin the transcript's stamps.
    clock: Any = time.time
    records: list[PromptRecord] = field(default_factory=list)

    @property
    def prompt_count(self) -> int:
        return len(self.records)

    @property
    def late_count(self) -> int:
        return sum(1 for record in self.records if record.outcome is PromptOutcome.LATE)

    @property
    def unfollowed(self) -> tuple[str, ...]:
        """Prompt ids where what the microphone observed is not what the step asked for."""
        return tuple(record.prompt.prompt_id for record in self.records if record.followed is False)

    def record_of(self, prompt_id: str) -> PromptRecord | None:
        for record in self.records:
            if record.prompt.prompt_id == prompt_id:
                return record
        return None

    async def ask(self, prompt: GuidedPrompt) -> PromptRecord:
        """Show one prompt, wait for the human within the deadline, and record what happened.

        Raises `GuidedPromptUnavailable` when the step did not happen: no answer, a
        refusal, a presenter that broke, or a late answer on a timing-critical step. The
        record is appended BEFORE the raise, so the transcript the runner commits always
        contains the step that stopped the run.
        """
        if len(self.records) >= MAX_PROMPTS_PER_RUN:
            raise GuidedPromptUnavailable(
                PROMPT_LIMIT, f"a guided run may address the human at most {MAX_PROMPTS_PER_RUN} times")
        self.context.check_cancelled()
        loop = asyncio.get_running_loop()
        shown_at = self._now_ms()
        started = loop.time()
        self.context.log(f"guided prompt {prompt.prompt_id} ({prompt.action.value}): "
                         f"{prompt.deadline_s:.0f}s - {prompt.text}")
        outcome, reply = await self._present(prompt, budget=prompt.deadline_s + max(0.0, self.grace_s))
        elapsed_ms = max(0, round((loop.time() - started) * 1000))
        if outcome is PromptOutcome.ACKNOWLEDGED and elapsed_ms > prompt.deadline_s * 1000:
            outcome = PromptOutcome.LATE
        record = PromptRecord(
            prompt=prompt, shown_at=shown_at,
            acknowledged_at=None if reply is None else shown_at + elapsed_ms,
            response_ms=None if reply is None else elapsed_ms,
            outcome=outcome, note=None if reply is None else reply.note)
        self.records.append(record)
        self.context.log(f"guided prompt {prompt.prompt_id}: {outcome.value} after {elapsed_ms} ms")
        self._require(record)
        return record

    def observe(self, prompt_id: str, *, voice: bool | None = None, peak_dbfs: float | None = None,
                **evidence: Any) -> None:
        """Attach what the microphone heard while a step was open. Evidence, never a verdict.

        `evidence` is the PROVENANCE of `voice`: the levels and flags the runner decided on.
        Without it a stored record says `voice: true` and a reader has no way to tell a
        person from Jarvis's own echo, which is exactly how an empty room once certified
        the one claim only a person can make.
        """
        record = self.record_of(prompt_id)
        if record is None:
            raise fail(f"no guided prompt {prompt_id} was shown in this run")
        record.observed_voice = voice
        record.observed_peak_dbfs = None if peak_dbfs is None else round(float(peak_dbfs), 1)
        for key, value in evidence.items():
            check_open_key(key, "observation")
            check_scalar_value(value, f"observation.{key}")
        record.evidence = dict(sorted(evidence.items()))

    def transcript(self) -> dict[str, Any]:
        """The bounded evidence document committed as `guided_prompts.json`."""
        return {
            "schema": TRANSCRIPT_SCHEMA, "schema_version": TRANSCRIPT_SCHEMA_VERSION,
            "run_id": self.context.run_id, "profile": self.context.profile.value,
            "prompt_count": self.prompt_count,
            "acknowledged_count": sum(1 for item in self.records
                                      if item.outcome is PromptOutcome.ACKNOWLEDGED),
            "late_count": self.late_count,
            "unfollowed": list(self.unfollowed),
            "records": [record.to_dict() for record in self.records],
        }

    def commit(self) -> None:
        """Store the transcript as a `report` artifact. Called in a `finally`: the evidence
        of a run a human abandoned is exactly the evidence worth keeping."""
        if not self.records:
            return
        payload = json.dumps(self.transcript(), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        self.context.put_artifact(TRANSCRIPT_ARTIFACT, kind=ArtifactKind.REPORT,
                                  media_type="application/json", data=payload)

    # ------------------------------------------------------------- internals

    def _now_ms(self) -> int:
        return int(self.clock() * 1000)

    async def _present(self, prompt: GuidedPrompt, *, budget: float) -> tuple[PromptOutcome, PromptReply | None]:
        """Race the presenter against the deadline AND against a run cancellation.

        Both losers are cancelled before returning: a presenter task left running would
        hold the prompt file, the console or the UI open after the run is over.
        """
        presenting = asyncio.ensure_future(self.prompter.present(prompt))
        cancelled = asyncio.ensure_future(self.context.cancelled.wait())
        try:
            done, _ = await asyncio.wait({presenting, cancelled}, timeout=budget,
                                         return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (presenting, cancelled):
                if not task.done():
                    task.cancel()
            await asyncio.gather(presenting, cancelled, return_exceptions=True)
        if cancelled in done:
            raise RunCancelled()
        if presenting not in done:
            return PromptOutcome.TIMED_OUT, None
        try:
            reply = presenting.result()
        except Exception as exc:
            # Captured with its type: a presenter that breaks is OUR problem, but the run
            # still only learnt "we could not reach the human", so it stays a measurement
            # failure rather than becoming a crash blamed on the product.
            self.context.log(f"guided prompter failed on {prompt.prompt_id}: {type(exc).__name__}: {exc}")
            return PromptOutcome.PROMPTER_FAILED, None
        if not isinstance(reply, PromptReply):
            self.context.log(f"guided prompter returned {type(reply).__name__} for {prompt.prompt_id}")
            return PromptOutcome.PROMPTER_FAILED, None
        if reply.refused or not reply.acknowledged:
            return PromptOutcome.REFUSED, reply
        return PromptOutcome.ACKNOWLEDGED, reply

    def _require(self, record: PromptRecord) -> None:
        """Turn a step the human did not perform into an honest measurement failure."""
        prompt = record.prompt
        if record.outcome is PromptOutcome.TIMED_OUT:
            raise GuidedPromptUnavailable(
                PROMPT_TIMED_OUT,
                f"the human did not answer '{prompt.prompt_id}' within {prompt.deadline_s:.0f} s "
                f"(+{self.grace_s:.0f} s grace), so the step never happened")
        if record.outcome is PromptOutcome.REFUSED:
            raise GuidedPromptUnavailable(
                PROMPT_REFUSED, f"the human declined '{prompt.prompt_id}', so this run measured nothing")
        if record.outcome is PromptOutcome.PROMPTER_FAILED:
            raise GuidedPromptUnavailable(
                PROMPTER_FAILED, f"the guided presenter could not show '{prompt.prompt_id}' to a human")
        if record.outcome is PromptOutcome.LATE and prompt.strict_timing:
            raise GuidedPromptUnavailable(
                PROMPT_LATE,
                f"'{prompt.prompt_id}' was acknowledged after {record.response_ms} ms, past its "
                f"{prompt.deadline_s:.0f} s deadline, and its timing IS the measurement")


# -------------------------------------------------------- presence opt-in

#: A guided run needs a human at this keyboard NOW. Nothing derives this and nothing
#: defaults it on: it is the operator saying "I am here", exactly as `JARVIS_TESTLAB_LIVE`
#: is the operator saying "spend money". The supervisor refuses the reservation without
#: it, before a worker exists.
GUIDED_OPT_IN_ENV = "JARVIS_TESTLAB_GUIDED"


def guided_opt_in(environ: Any = None) -> bool:
    """Is a human declared present for guided runs in this environment?"""
    import os

    source = environ if environ is not None else os.environ
    return source.get(GUIDED_OPT_IN_ENV) == "1"

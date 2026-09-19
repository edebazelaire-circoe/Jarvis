"""The guided-run presenter for a terminal: show the prompt, the deadline and a live countdown.

Binding contract: `docs/testlab.md` ("Guided runs", "Native API, CLI and HTTP"). Slice 09
built the channel (`FilePrompter` on the worker side, `PromptWatcher` on this side) and
stated the rule this module exists to honour: *the deadline is part of the contract, not
a hint — a step with no visible countdown is indistinguishable from a frozen run*.

So this presenter, for the whole time a prompt is open, shows four things at once:

1. THAT it is waiting — a bar and a spinner that move every tick;
2. WHAT the human must do — the authored prompt text and, for a spoken step, the phrase;
3. HOW LONG is left — counted from the WORKER's `shown_at`, never from when this process
   happened to look, so it can never promise time the run will not wait;
4. HOW TO GET OUT — `Enter` to confirm, `r` to refuse, both always on screen.

An empty line is a human pressing Enter; end of file is nobody there. `NO_INPUT` keeps
the two apart, and a reader that reaches it takes this presenter out of the answering
business for good — a presenter with no terminal attached must never confirm, in a
human's name, the one claim a guided run exists to make.

The presenter reports the ANSWER and never the timing (Slice 09's rule): `GuidedSession`
inside the worker stamps both sides and owns the deadline, so a slow presenter is
measured, not trusted. When the deadline passes here, this module stops accepting an
answer for that step and says so; it never sends a late answer, and an answer typed after
the run moved on is discarded out loud instead of being applied to the next step.

The rendering functions are pure, so the exact text a human sees is asserted by tests
rather than reviewed by eye.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import time
from typing import Any

from jarvis.testlab.hardware.prompts import GuidedAction, GuidedPrompt

#: Characters of the countdown bar. ASCII only: this runs in a Windows console whose code
#: page is not always UTF-8, and a prompt that raises `UnicodeEncodeError` shows nothing.
BAR_WIDTH = 24
SPINNER = "|/-\\"
#: How often the countdown line is redrawn. Fast enough to read as motion, slow enough
#: that a ten-minute prompt does not flood a terminal.
TICK_S = 0.5
#: How often the presenter looks for a new prompt on disk.
POLL_INTERVAL_S = 0.2

#: What the human types. Anything else is taken as a free-text note with a confirmation.
REFUSE_WORDS = frozenset({"r", "refuse", "n", "no", "non", "skip"})


class _NoInput:
    """Type of `NO_INPUT`."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "NO_INPUT"


#: "Nobody can answer through this reader": end of file, a closed or unreadable stdin, a
#: reader that raised. It is NOT an empty line — an empty line is a human pressing Enter,
#: which ACKNOWLEDGES the step. Conflating the two is how a presenter with no terminal
#: attached confirms, in a human's name, every step of a guided run; the guided profile
#: exists to make exactly that one claim, so the two must never share a value.
NO_INPUT = _NoInput()

_ACTION_HINTS = {
    GuidedAction.REMAIN_SILENT: "Stay silent until this step ends, then press Enter.",
    GuidedAction.SAY_PHRASE: "Say the phrase out loud, then press Enter.",
    GuidedAction.INTERRUPT: "Wait until Jarvis is speaking, say the phrase over it, then press Enter.",
    GuidedAction.ACKNOWLEDGE: "Press Enter when you have done this.",
}


@dataclass(frozen=True, slots=True)
class PromptAnswer:
    """One answered (or missed) step, as the presenter saw it."""

    prompt_id: str
    sequence: int
    #: False when the human declined, or when the deadline passed with no answer.
    acknowledged: bool
    refused: bool
    note: str | None = None
    #: True when the deadline passed before anything was typed. Nothing was sent.
    expired: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"prompt_id": self.prompt_id, "sequence": self.sequence, "acknowledged": self.acknowledged,
                "refused": self.refused, "note": self.note, "expired": self.expired}


# ------------------------------------------------------------------ rendering

def render_header(prompt: GuidedPrompt) -> str:
    """The block shown once when a step opens: what to do, and how to answer."""
    lines = ["", "=" * (BAR_WIDTH + 34),
             f"GUIDED STEP  {prompt.prompt_id}  [{prompt.action.value}]",
             prompt.text]
    if prompt.phrase:
        lines.append(f'Phrase to say: "{prompt.phrase}"')
    lines.append(_ACTION_HINTS.get(prompt.action, "Press Enter when you have done this."))
    if prompt.strict_timing:
        lines.append("This step is TIMED: answering late voids its measurement.")
    lines.append(f"You have {prompt.deadline_s:.0f} s.  [Enter] done   [r] refuse")
    return "\n".join(lines)


def render_countdown(prompt: GuidedPrompt, remaining_s: float, tick: int) -> str:
    """The live line: a moving bar, a spinner, the seconds left, and the way out.

    `tick` advances the spinner, so the line changes even when the terminal rounds the
    same second twice: a frozen character is what a stuck run looks like.
    """
    total = max(prompt.deadline_s, 0.001)
    # Clamped both ways: a countdown that showed more than the deadline would promise
    # time the run will not wait, and a negative one would read as a defect.
    remaining = min(max(0.0, float(remaining_s)), total)
    filled = max(0, min(BAR_WIDTH, round(BAR_WIDTH * remaining / total)))
    bar = "#" * filled + "-" * (BAR_WIDTH - filled)
    spinner = SPINNER[tick % len(SPINNER)]
    return (f"  {spinner} [{bar}] {remaining:5.1f} s left of {total:.0f} s"
            f"   [Enter] done   [r] refuse")


def render_expired(prompt: GuidedPrompt, waited_s: float) -> str:
    """What is shown when the deadline passes: how long it waited, and what happens now."""
    return (f"  !! {prompt.prompt_id}: no answer after {waited_s:.1f} s of {prompt.deadline_s:.0f} s. "
            "The run decides this step (it ends as 'could not measure'); nothing was sent.")


def render_no_input(prompt: GuidedPrompt) -> str:
    """What is shown when the input channel closes: nothing was answered, and why."""
    return (f"  !! {prompt.prompt_id}: this terminal can no longer be read (end of input). "
            "No step will be acknowledged from here; each one ends as 'could not measure' "
            "when its deadline passes.")


def render_answer(answer: PromptAnswer) -> str:
    if answer.refused:
        return f"  -> {answer.prompt_id}: refused. The run records this and stops measuring that claim."
    note = f" (note: {answer.note})" if answer.note else ""
    return f"  -> {answer.prompt_id}: acknowledged{note}."


def read_answer(line: str) -> tuple[bool, str | None]:
    """`(refused, note)` from what the human typed. Enter alone confirms."""
    text = (line or "").strip()
    if not text:
        return False, None
    if text.lower() in REFUSE_WORDS:
        return True, None
    return False, text[:200]


# ----------------------------------------------------------------- presenter

class GuidedPresenter:
    """Drive one run's guided prompts from a terminal, through a `PromptWatcher`.

    `watcher` only has to answer `pending_shown()` and `acknowledge()`, so a test drives
    this against a fake without any file or any worker.
    """

    def __init__(self, watcher: Any, *, write: Callable[[str], None],
                 write_live: Callable[[str], None] | None = None,
                 read_line: Callable[[], str | _NoInput] | None = None,
                 clock: Callable[[], float] = time.time,
                 tick_s: float = TICK_S, poll_interval_s: float = POLL_INTERVAL_S) -> None:
        self._watcher = watcher
        self._write = write
        #: Where the countdown goes. It is REDRAWN in place, not appended: at one line
        #: every `TICK_S` a 30-second step would scroll its own header, and the phrase the
        #: operator has to say, off the screen — which is the one thing they are reading.
        #: Defaults to `write`, so a test double needs only one sink.
        self._write_live = write_live if write_live is not None else write
        self._read_line = read_line if read_line is not None else stdin_line
        self._clock = clock
        self._tick_s = max(0.05, float(tick_s))
        self._poll_s = max(0.01, float(poll_interval_s))
        self._answers: list[PromptAnswer] = []
        #: False once the reader has said it can answer nothing more. From then on no
        #: reader is started, every step is left to its own deadline, and the presenter
        #: is a display: it will not answer in a human's name.
        self._readable = True

    @property
    def answers(self) -> tuple[PromptAnswer, ...]:
        return tuple(self._answers)

    @property
    def readable(self) -> bool:
        return self._readable

    async def serve(self, stop: asyncio.Event) -> tuple[PromptAnswer, ...]:
        """Show and answer prompts until `stop` is set (the run became terminal).

        One reader task at a time, kept across steps: a human who types after a deadline
        must not have that keystroke applied to the next step, so the answer carries the
        step it was started for and is discarded, visibly, when they no longer match.

        A reader that reaches end of file, or raises, ANSWERS NOTHING and takes the
        presenter out of the answering business for good: `NO_INPUT` is not an empty
        line. Each step then ends on its own deadline, which is the honest outcome when
        there is nobody at the keyboard.
        """
        reading: asyncio.Task[str | _NoInput] | None = None
        reading_for: tuple[str, int] | None = None
        shown: tuple[str, int] | None = None
        #: The step whose expiry has already been announced; without it the same dead
        #: step is re-announced on every poll until the worker gives up on it.
        expired_for: tuple[str, int] | None = None
        tick = 0
        try:
            while not stop.is_set():
                pending = self._watcher.pending_shown()
                if pending is None:
                    shown = None
                    await self._sleep_or_stop(stop, self._poll_s)
                    continue
                prompt, sequence, shown_at = pending
                key = (prompt.prompt_id, sequence)
                if key == expired_for:
                    # Said once. The worker owns the deadline and will move on.
                    await self._sleep_or_stop(stop, self._poll_s)
                    continue
                if key != shown:
                    shown = key
                    tick = 0
                    self._write(render_header(prompt))
                if reading is None and self._readable:
                    reading = asyncio.ensure_future(asyncio.to_thread(self._read_line))
                    reading_for = key
                remaining = prompt.deadline_s - max(0.0, self._clock() - shown_at)
                if reading is not None and reading.done():
                    line, answered_for = _read_result(reading), reading_for
                    reading, reading_for = None, None
                    if line is NO_INPUT:
                        self._readable = False
                        self._write(render_no_input(prompt))
                        continue
                    if answered_for == key and remaining > 0:
                        self._answer(prompt, sequence, line)
                        shown = None
                        continue
                    self._write(f"  .. ignored: that answer was for {(answered_for or key)[0]}, "
                                "and the run has moved past it.")
                    continue
                if remaining <= 0:
                    self._expired(prompt, sequence)
                    expired_for = key
                    shown = None
                    await self._sleep_or_stop(stop, self._poll_s)
                    continue
                self._write_live(render_countdown(prompt, remaining, tick))
                tick += 1
                if reading is None:
                    await self._sleep_or_stop(stop, min(self._tick_s, max(remaining, 0.01)))
                else:
                    await self._wait_input(reading, min(self._tick_s, max(remaining, 0.01)))
        finally:
            if reading is not None:
                reading.cancel()
        return tuple(self._answers)

    # ------------------------------------------------------------- internals

    def _answer(self, prompt: GuidedPrompt, sequence: int, line: str) -> None:
        refused, note = read_answer(line)
        answer = PromptAnswer(prompt.prompt_id, sequence, acknowledged=not refused, refused=refused, note=note)
        self._watcher.acknowledge(prompt.prompt_id, sequence, refused=refused, note=note)
        self._answers.append(answer)
        self._write(render_answer(answer))

    def _expired(self, prompt: GuidedPrompt, sequence: int) -> None:
        self._answers.append(PromptAnswer(prompt.prompt_id, sequence, acknowledged=False, refused=False,
                                          expired=True))
        self._write(render_expired(prompt, prompt.deadline_s))

    @staticmethod
    async def _wait_input(reading: asyncio.Future[Any], timeout_s: float) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(reading), timeout=timeout_s)
        except asyncio.TimeoutError:
            # Intentional: the timeout IS the tick. `shield` keeps the reader alive, so
            # the keystroke a human is halfway through typing survives the redraw.
            pass
        except Exception:
            # Captured, argued: `wait_for` re-raises whatever the reader raised, which
            # would take the presenter down over an unreadable stdin. The loop reads the
            # SAME future through `_read_result` on the next turn and treats it as
            # `NO_INPUT`, so the failure is reported there, once, and nothing is answered.
            pass

    @staticmethod
    async def _sleep_or_stop(stop: asyncio.Event, timeout_s: float) -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            pass


def _read_result(reading: asyncio.Future[Any]) -> str | _NoInput:
    """What the reader produced, or `NO_INPUT` when it produced nothing it could stand behind.

    Cancelled, raised, a non-string result — and the EMPTY STRING — all mean the same
    thing: no human answered. `""` is included deliberately. A real `readline()` gives
    `"
"` for Enter and `""` only at end of file, so nothing a human typed is lost; and
    every other presenter that will exist (the Slice 11 UI, a websocket or SSH reader, a
    test double) ends its stream with `""` too. Mapping it here, at the seam, is what
    stops the next presenter from resurrecting the defect this sentinel was added for.
    """
    if reading.cancelled() or reading.exception() is not None:
        return NO_INPUT
    line = reading.result()
    return line if isinstance(line, str) and line != "" else NO_INPUT


def stdin_line() -> str | _NoInput:
    """One line from the real stdin, or `NO_INPUT` at end of file. Blocking, hence a thread.

    `readline()` returns `"\\n"` for a bare Enter and `""` only at EOF, which is the whole
    distinction: an operator pressing Enter acknowledges a step, and a pipe that ran dry
    must not.
    """
    import sys

    try:
        line = sys.stdin.readline()
    except (OSError, ValueError):
        # Captured, argued: a detached or closed stdin cannot answer. Raising here would
        # cross a thread boundary to no purpose; `NO_INPUT` is the same fact, typed.
        return NO_INPUT
    return NO_INPUT if not line else line


def presenter_input_available(isatty: bool, headless: bool) -> bool:
    """May a presenter be attached here? A terminal, or an operator who said so explicitly.

    Pure, so the CLI's refusal is tested without a tty. Without this check, running a
    guided diagnostic from a script or from CI attaches a presenter whose stdin is at end
    of file, and the run's evidence would record steps nobody performed.
    """
    return bool(isatty) or bool(headless)

"""Slice 10: the guided presenter, against a fake `PromptWatcher` — no worker, no file.

Contract: `docs/testlab.md` ("Guided runs"). The rule under test is Slice 09's: a step
with no visible countdown is indistinguishable from a frozen run. So the countdown is
asserted, not looked at, and so is what happens when nobody answers: the presenter never
sends a late acknowledgement, and an answer typed after the run moved on is discarded
instead of being applied to the next step.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import queue
import sys

import pytest

from jarvis.testlab.hardware.prompts import GuidedAction, GuidedPrompt
from jarvis.testlab.presenter import (
    BAR_WIDTH,
    NO_INPUT,
    GuidedPresenter,
    PromptAnswer,
    read_answer,
    render_answer,
    render_countdown,
    render_expired,
    render_header,
    presenter_input_available,
    stdin_line,
)

SHOWN_AT = 1_000_000.0


def prompt(action: GuidedAction = GuidedAction.ACKNOWLEDGE, prompt_id: str = "step_one",
           **changes) -> GuidedPrompt:
    fields = {"prompt_id": prompt_id, "action": action, "text": "Do the thing.", "deadline_s": 20.0}
    if action in (GuidedAction.SAY_PHRASE, GuidedAction.INTERRUPT):
        fields["phrase"] = "jarvis quelle heure est-il"
    return GuidedPrompt(**{**fields, **changes})


class FakeWatcher:
    """The two methods a presenter needs, and a record of what it sent."""

    def __init__(self) -> None:
        self.open: tuple[GuidedPrompt, int, float] | None = None
        self.acknowledgements: list[dict] = []

    def show(self, item: GuidedPrompt, sequence: int = 1, shown_at: float = SHOWN_AT) -> None:
        self.open = (item, sequence, shown_at)

    def clear(self) -> None:
        self.open = None

    def pending_shown(self):
        return self.open

    def acknowledge(self, prompt_id: str, sequence: int, *, refused: bool = False, note=None) -> None:
        self.acknowledgements.append({"prompt_id": prompt_id, "sequence": sequence,
                                      "refused": refused, "note": note})
        # The real `FilePrompter` removes the prompt as soon as it has its answer.
        self.open = None


class Keyboard:
    """A blocking `read_line`, driven from the test. Released in `typing()`'s `finally`."""

    def __init__(self) -> None:
        self._lines: queue.Queue[str] = queue.Queue()

    def type(self, line: str) -> None:
        self._lines.put(line)

    def read_line(self) -> str:
        return self._lines.get()


#: What `readline()` returns for a bare Enter. A double that sends `""` is saying "end of
#: stream", which the presenter must never read as an acknowledgement (`_read_result`).
ENTER = "\n"


@contextmanager
def typing():
    """A keyboard whose reader thread is always released, so the loop can shut down."""
    keyboard = Keyboard()
    try:
        yield keyboard
    finally:
        keyboard.type("")  # end of stream: unblocks the reader thread, answers nothing


class Screen:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, text: str) -> None:
        self.lines.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


async def wait_until(predicate, *, timeout_s: float = 5.0) -> None:
    """Bounded wait: a test that hangs proves nothing about a presenter that must not."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the presenter never reached the expected state")
        await asyncio.sleep(0.01)


def build(watcher, keyboard, screen, clock) -> GuidedPresenter:
    return GuidedPresenter(watcher, write=screen.write, read_line=keyboard.read_line, clock=clock,
                           tick_s=0.02, poll_interval_s=0.01)


# ----------------------------------------------------------------- rendering

def test_the_header_states_the_action_the_phrase_the_deadline_and_the_way_out():
    text = render_header(prompt(GuidedAction.SAY_PHRASE, "say_it"))
    assert "say_it" in text and "say_phrase" in text
    assert "jarvis quelle heure est-il" in text
    assert "20 s" in text and "[Enter]" in text and "[r]" in text


def test_a_timed_step_says_so_because_answering_late_voids_its_measurement():
    assert "TIMED" in render_header(prompt(GuidedAction.INTERRUPT, "cut_in", strict_timing=True))
    assert "TIMED" not in render_header(prompt())


def test_the_countdown_shows_the_time_left_a_moving_bar_and_the_way_out():
    item = prompt()
    line = render_countdown(item, 12.5, tick=0)
    assert "12.5 s left of 20 s" in line and "[Enter]" in line and "[r]" in line
    assert line.count("#") + line.count("-") >= BAR_WIDTH


def test_the_bar_empties_and_the_spinner_turns_so_a_frozen_run_looks_different():
    item = prompt()
    full, empty = render_countdown(item, 20.0, 0), render_countdown(item, 0.0, 0)
    assert full.count("#") == BAR_WIDTH and empty.count("#") == 0
    assert render_countdown(item, 10.0, 0) != render_countdown(item, 10.0, 1), "the spinner never moved"


def test_the_countdown_never_shows_more_than_the_deadline_or_less_than_zero():
    item = prompt()
    assert "20.0 s left of 20 s" in render_countdown(item, 999.0, 0)
    assert "0.0 s left of 20 s" in render_countdown(item, -5.0, 0)


def test_the_expiry_line_says_how_long_it_waited_and_what_happens_now():
    text = render_expired(prompt(), 20.0)
    assert "20.0 s" in text and "could not measure" in text and "nothing was sent" in text


def test_an_answer_is_read_the_way_a_human_types_it():
    assert read_answer("") == (False, None)
    assert read_answer("\n") == (False, None)
    assert read_answer("r") == (True, None)
    assert read_answer("REFUSE") == (True, None)
    assert read_answer("le micro etait coupe") == (False, "le micro etait coupe")
    assert read_answer("x" * 400)[1] == "x" * 200


def test_a_refusal_is_reported_as_a_refusal_not_as_a_failure():
    assert "refused" in render_answer(PromptAnswer("s", 1, acknowledged=False, refused=True))
    assert "acknowledged" in render_answer(PromptAnswer("s", 1, acknowledged=True, refused=False))


# ----------------------------------------------------------------- behaviour

async def test_enter_acknowledges_the_open_step():
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    with typing() as keyboard:
        presenter = build(watcher, keyboard, screen, lambda: SHOWN_AT)
        serving = asyncio.ensure_future(presenter.serve(stop))
        watcher.show(prompt())
        keyboard.type(ENTER)
        await wait_until(lambda: watcher.acknowledgements)
        stop.set()
        answers = await serving
    assert watcher.acknowledgements == [{"prompt_id": "step_one", "sequence": 1, "refused": False, "note": None}]
    assert answers == (PromptAnswer("step_one", 1, acknowledged=True, refused=False),)
    assert "GUIDED STEP  step_one" in screen.text


async def test_r_refuses_and_the_refusal_reaches_the_run():
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    with typing() as keyboard:
        presenter = build(watcher, keyboard, screen, lambda: SHOWN_AT)
        serving = asyncio.ensure_future(presenter.serve(stop))
        watcher.show(prompt())
        keyboard.type("r")
        await wait_until(lambda: watcher.acknowledgements)
        stop.set()
        answers = await serving
    assert watcher.acknowledgements[0]["refused"] is True
    assert answers[0].refused is True and answers[0].acknowledged is False


async def test_free_text_is_carried_to_the_run_as_a_note():
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    with typing() as keyboard:
        presenter = build(watcher, keyboard, screen, lambda: SHOWN_AT)
        serving = asyncio.ensure_future(presenter.serve(stop))
        watcher.show(prompt())
        keyboard.type("j'ai parle trop tot")
        await wait_until(lambda: watcher.acknowledgements)
        stop.set()
        await serving
    assert watcher.acknowledgements[0]["note"] == "j'ai parle trop tot"


async def test_the_countdown_is_drawn_while_nobody_answers():
    """RULE ZERO: visible motion and a live counter for as long as the step is open."""
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    now = [SHOWN_AT]
    with typing() as keyboard:
        presenter = build(watcher, keyboard, screen, lambda: now[0])
        serving = asyncio.ensure_future(presenter.serve(stop))
        watcher.show(prompt())
        await wait_until(lambda: sum("s left of" in line for line in screen.lines) >= 3)
        now[0] = SHOWN_AT + 5.0
        await wait_until(lambda: any("15.0 s left" in line for line in screen.lines))
        stop.set()
        await serving
    assert not watcher.acknowledgements, "a countdown must not answer for the human"


async def test_a_deadline_that_passes_sends_nothing_and_says_how_long_it_waited():
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    now = [SHOWN_AT]
    with typing() as keyboard:
        presenter = build(watcher, keyboard, screen, lambda: now[0])
        serving = asyncio.ensure_future(presenter.serve(stop))
        watcher.show(prompt())
        await wait_until(lambda: any("s left of" in line for line in screen.lines))
        now[0] = SHOWN_AT + 21.0
        await wait_until(lambda: any("no answer after" in line for line in screen.lines))
        stop.set()
        answers = await serving
    assert watcher.acknowledgements == [], "a late acknowledgement would lie about the timing"
    assert answers[0].expired is True and answers[0].acknowledged is False


async def test_an_answer_typed_after_the_deadline_is_not_applied_to_the_next_step():
    """The failure a naive presenter produces on every second prompt."""
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    now = [SHOWN_AT]
    with typing() as keyboard:
        presenter = build(watcher, keyboard, screen, lambda: now[0])
        serving = asyncio.ensure_future(presenter.serve(stop))
        watcher.show(prompt(prompt_id="first"))
        await wait_until(lambda: any("s left of" in line for line in screen.lines))
        now[0] = SHOWN_AT + 21.0
        await wait_until(lambda: any("no answer after" in line for line in screen.lines))
        watcher.clear()
        # The human types now — too late for `first`, and the run has opened `second`.
        now[0] = SHOWN_AT + 30.0
        watcher.show(prompt(prompt_id="second"), sequence=2, shown_at=now[0])
        keyboard.type(ENTER)
        await wait_until(lambda: any("ignored" in line for line in screen.lines))
        stop.set()
        await serving
    assert [item["prompt_id"] for item in watcher.acknowledgements] == [], "a stale keystroke answered a new step"
    assert "that answer was for first" in screen.text


async def test_the_presenter_stops_when_the_run_ends():
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    with typing() as keyboard:
        presenter = build(watcher, keyboard, screen, lambda: SHOWN_AT)
        serving = asyncio.ensure_future(presenter.serve(stop))
        stop.set()
        assert await asyncio.wait_for(serving, timeout=5) == ()


async def test_two_steps_in_a_row_are_each_shown_and_each_answered():
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    with typing() as keyboard:
        presenter = build(watcher, keyboard, screen, lambda: SHOWN_AT)
        serving = asyncio.ensure_future(presenter.serve(stop))
        watcher.show(prompt(prompt_id="first"), sequence=1)
        keyboard.type(ENTER)
        await wait_until(lambda: len(watcher.acknowledgements) == 1)
        watcher.show(prompt(prompt_id="second"), sequence=2)
        keyboard.type("r")
        await wait_until(lambda: len(watcher.acknowledgements) == 2)
        stop.set()
        answers = await serving
    assert [item["prompt_id"] for item in watcher.acknowledgements] == ["first", "second"]
    assert [item["sequence"] for item in watcher.acknowledgements] == [1, 2]
    assert answers[1].refused is True
    assert screen.text.count("GUIDED STEP") == 2


def test_the_answer_shape_is_stable_for_a_caller_that_stores_it():
    assert PromptAnswer("s", 2, acknowledged=True, refused=False, note="ok").to_dict() == {
        "prompt_id": "s", "sequence": 2, "acknowledged": True, "refused": False, "note": "ok", "expired": False}


@pytest.mark.parametrize("action", list(GuidedAction))
def test_every_guided_action_has_a_sentence_telling_the_human_what_to_do(action):
    text = render_header(prompt(action, "step"))
    assert "Enter" in text and len(text.splitlines()) >= 5


# --------------------------------- rework B1/B2/S3: nobody at the keyboard

async def test_a_reader_at_end_of_file_acknowledges_nothing():
    """The defect this is here for: `--guided` from a script or CI silently confirmed every
    step in a human's name. `NO_INPUT` is not an empty line."""
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    now = [SHOWN_AT]
    presenter = GuidedPresenter(watcher, write=screen.write, read_line=lambda: NO_INPUT,
                                clock=lambda: now[0], tick_s=0.02, poll_interval_s=0.01)
    serving = asyncio.ensure_future(presenter.serve(stop))
    watcher.show(prompt())
    await wait_until(lambda: any("no longer be read" in line for line in screen.lines))
    now[0] = SHOWN_AT + 21.0
    await wait_until(lambda: any("no answer after" in line for line in screen.lines))
    stop.set()
    answers = await serving
    assert watcher.acknowledgements == [], "a presenter with no input answered for the human"
    assert answers[0].expired is True and answers[0].acknowledged is False
    assert presenter.readable is False


async def test_a_bare_newline_acknowledges_because_that_is_a_human_pressing_enter():
    """The other half of the distinction: `readline()` gives `"
"` for Enter."""
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    presenter = GuidedPresenter(watcher, write=screen.write, read_line=lambda: ENTER,
                                clock=lambda: SHOWN_AT, tick_s=0.02, poll_interval_s=0.01)
    serving = asyncio.ensure_future(presenter.serve(stop))
    watcher.show(prompt())
    await wait_until(lambda: watcher.acknowledgements)
    stop.set()
    await serving
    assert watcher.acknowledgements[0]["refused"] is False


async def test_a_reader_that_returns_the_empty_string_acknowledges_nothing():
    """S-A, the seam the next presenter will hit: `""` is end of stream, not Enter.

    Today's CLI cannot reach it (`stdin_line` maps EOF itself), but the Slice 11 UI, a
    websocket or SSH reader, or any test double that returns `""` at end of stream would
    otherwise confirm the step — which is exactly B1 again, one layer out.
    """
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    now = [SHOWN_AT]
    presenter = GuidedPresenter(watcher, write=screen.write, read_line=lambda: "",
                                clock=lambda: now[0], tick_s=0.02, poll_interval_s=0.01)
    serving = asyncio.ensure_future(presenter.serve(stop))
    watcher.show(prompt())
    await wait_until(lambda: any("no longer be read" in line for line in screen.lines))
    now[0] = SHOWN_AT + 21.0
    await wait_until(lambda: any("no answer after" in line for line in screen.lines))
    stop.set()
    answers = await serving
    assert watcher.acknowledgements == [], "an empty string was read as a human pressing Enter"
    assert answers[0].expired is True and presenter.readable is False


async def test_the_countdown_is_redrawn_in_place_and_the_durable_lines_are_not():
    """S-B: at one appended line every tick, a 30 s step scrolls away its own header and
    the phrase the operator has to say — which is the thing they are reading."""
    watcher, stop = FakeWatcher(), asyncio.Event()
    durable, live = Screen(), Screen()
    with typing() as keyboard:
        presenter = GuidedPresenter(watcher, write=durable.write, write_live=live.write,
                                    read_line=keyboard.read_line, clock=lambda: SHOWN_AT,
                                    tick_s=0.02, poll_interval_s=0.01)
        serving = asyncio.ensure_future(presenter.serve(stop))
        watcher.show(prompt(GuidedAction.SAY_PHRASE, "say_it"))
        await wait_until(lambda: len(live.lines) >= 4)
        keyboard.type(ENTER)
        await wait_until(lambda: watcher.acknowledgements)
        stop.set()
        await serving
    assert all("s left of" in line for line in live.lines), "only the countdown is redrawn"
    assert not any("s left of" in line for line in durable.lines)
    assert "GUIDED STEP  say_it" in durable.text and "jarvis quelle heure est-il" in durable.text
    assert "acknowledged" in durable.text


def test_the_live_sink_defaults_to_the_durable_one():
    """One sink is enough for a double; the CLI is what splits them."""
    presenter = GuidedPresenter(FakeWatcher(), write=print)
    assert presenter._write_live is presenter._write


async def test_a_closed_reader_never_answers_the_steps_that_follow_either():
    """One `NO_INPUT` takes the presenter out of the answering business for the whole run."""
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    now = [SHOWN_AT]
    presenter = GuidedPresenter(watcher, write=screen.write, read_line=lambda: NO_INPUT,
                                clock=lambda: now[0], tick_s=0.02, poll_interval_s=0.01)
    serving = asyncio.ensure_future(presenter.serve(stop))
    watcher.show(prompt(prompt_id="first"), sequence=1)
    await wait_until(lambda: any("no longer be read" in line for line in screen.lines))
    now[0] = SHOWN_AT + 21.0
    await wait_until(lambda: any("first: no answer after" in line for line in screen.lines))
    watcher.clear()
    now[0] = SHOWN_AT + 30.0
    watcher.show(prompt(prompt_id="second"), sequence=2, shown_at=now[0])
    await wait_until(lambda: any("GUIDED STEP  second" in line for line in screen.lines))
    now[0] = SHOWN_AT + 60.0
    await wait_until(lambda: any("second: no answer after" in line for line in screen.lines))
    stop.set()
    await serving
    assert watcher.acknowledgements == []


async def test_a_reader_that_raises_is_handled_inside_the_presenter():
    """`wait_for(shield(...))` re-raises what the reader raised; that must not escape."""
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    now = [SHOWN_AT]

    def unreadable_stdin() -> str:
        raise OSError("stdin is detached")

    presenter = GuidedPresenter(watcher, write=screen.write, read_line=unreadable_stdin,
                                clock=lambda: now[0], tick_s=0.02, poll_interval_s=0.01)
    serving = asyncio.ensure_future(presenter.serve(stop))
    watcher.show(prompt())
    await wait_until(lambda: any("no longer be read" in line for line in screen.lines))
    now[0] = SHOWN_AT + 21.0
    await wait_until(lambda: any("no answer after" in line for line in screen.lines))
    stop.set()
    answers = await asyncio.wait_for(serving, timeout=5)
    assert watcher.acknowledgements == [] and answers[0].expired is True


async def test_an_expired_step_is_announced_once_not_on_every_poll():
    """25 headers and 25 expiries for one step is what the operator used to see scroll past."""
    watcher, screen, stop = FakeWatcher(), Screen(), asyncio.Event()
    now = [SHOWN_AT]
    with typing() as keyboard:
        presenter = build(watcher, keyboard, screen, lambda: now[0])
        serving = asyncio.ensure_future(presenter.serve(stop))
        watcher.show(prompt())
        await wait_until(lambda: any("s left of" in line for line in screen.lines))
        now[0] = SHOWN_AT + 21.0
        await wait_until(lambda: any("no answer after" in line for line in screen.lines))
        await asyncio.sleep(0.4)  # many poll periods with the prompt still on disk
        stop.set()
        answers = await serving
    assert sum("no answer after" in line for line in screen.lines) == 1
    assert sum("GUIDED STEP" in line for line in screen.lines) == 1
    assert len(answers) == 1, "one dead step produced several records"


def test_the_real_stdin_reader_tells_enter_from_end_of_file(monkeypatch):
    """`readline()` gives "\n" for Enter and "" only at EOF: that IS the distinction."""
    class Stream:
        def __init__(self, value): self.value = value
        def readline(self): return self.value

    monkeypatch.setattr(sys, "stdin", Stream("\n"))
    assert stdin_line() == "\n"
    monkeypatch.setattr(sys, "stdin", Stream(""))
    assert stdin_line() is NO_INPUT

    class Detached:
        def readline(self): raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(sys, "stdin", Detached())
    assert stdin_line() is NO_INPUT


def test_a_presenter_is_only_attached_where_somebody_can_answer():
    assert presenter_input_available(True, False) is True
    assert presenter_input_available(False, True) is True, "--headless is the operator saying so"
    assert presenter_input_available(False, False) is False

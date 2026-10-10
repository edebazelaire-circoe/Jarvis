"""Locked-sequence executor, pure (jarvis-interactive-presentation-studio, Slice 14).

What is proven with a fake clock and no I/O: every step is due at exactly `t0 + shift + offset` (from the start, never from the
previous step), a late poll never accumulates into drift (1000+ steps), a pause preserves every remaining offset, the
interruption policy table (`allow` / `at_boundary` / `refuse`) agrees with the playback machine on every cell, and the same score
on the same clock yields the same action log whatever the key order of the document.
Contract: `docs/presentation-studio.md` > *Jarvis presenter and locked sequences*.
"""

from __future__ import annotations

import json
import random

import pytest

from jarvis.domain.presentation_studio_score import Interruption, LockedSequence, SequenceInterrupt
from jarvis.domain.presentation_studio_sequence import (
    InputKind, SequenceSchedule, Verdict, begin, due, elapsed_ms, end_due, end_ms, finish, input_verdict, interruption_plan,
    log_entry, next_deadline_ms, pause, release, resume, scheduled_ms, start,
)

def schedule(offsets=(0, 1000, 2500, 4000), duration=6000) -> SequenceSchedule:
    return SequenceSchedule("demo", tuple(f"s{i}" for i in range(len(offsets))), tuple(offsets), duration)


def run_to_end(clock, polls):
    """Poll at the given instants; release everything due; returns (clock, [(index, scheduled, released)])."""

    out = []
    for now in polls:
        for step in due(clock, now):
            clock = release(clock, step.index)
            out.append((step.index, step.scheduled_ms, now))
    return clock, out


# ------------------------------------------------------------------ exact offsets, from t0 and never from the previous step

def test_every_step_is_due_exactly_at_t0_plus_its_offset():
    clock = start(begin(schedule()), 10_000)
    assert [d.scheduled_ms for d in due(clock, 10_000 + 6000)] == [10_000, 11_000, 12_500, 14_000]
    assert [d.index for d in due(clock, 10_000)] == [0]
    assert [d.index for d in due(clock, 10_999)] == [0]
    assert [d.index for d in due(clock, 11_000)] == [0, 1]


def test_a_step_is_never_released_early_and_nothing_is_due_before_the_start():
    assert due(begin(schedule()), 99_999) == ()
    clock = start(begin(schedule()), 5000)
    assert due(clock, 4999) == ()


def test_a_late_poll_delays_one_release_and_moves_nothing_else():
    clock = start(begin(schedule()), 0)
    clock = release(clock, 0)
    # polled 400 ms late for step 1: step 2 is still due at its own exact offset, not 1400 + 1500
    late = due(clock, 1400)
    assert [(d.index, d.scheduled_ms) for d in late] == [(1, 1000)]
    clock = release(clock, 1)
    assert [(d.index, d.scheduled_ms) for d in due(clock, 2500)] == [(2, 2500)]


def test_no_drift_over_a_thousand_steps_with_random_jitter():
    rng = random.Random(14)
    total, late_max = 0, 0
    for run in range(40):                       # 40 sequences x 32 steps = 1280 steps
        offsets = tuple(range(0, 32 * 700, 700))
        clock = start(begin(schedule(offsets, 32 * 700 + 300)), run * 100_000)
        now = clock.t0_ms
        released = []
        while clock.released < len(offsets):
            now += rng.randint(1, 300)         # a jittery poller
            for step in due(clock, now):
                clock = release(clock, step.index)
                released.append((step.index, step.scheduled_ms, now))
        for index, scheduled, at in released:
            assert scheduled == clock.t0_ms + offsets[index]            # exact, whatever the jitter before it
            assert 0 <= at - scheduled < 300 + 1                        # lateness is bounded by ONE poll interval, never cumulative
            late_max = max(late_max, at - scheduled)
        total += len(released)
    assert total == 1280 and late_max <= 300


def test_the_end_is_the_exact_length_after_the_last_release():
    clock = start(begin(schedule()), 1000)
    clock, _ = run_to_end(clock, [1000, 2000, 3500, 5000])
    assert not end_due(clock, 6999) and end_due(clock, 7000) and end_ms(clock) == 7000
    assert next_deadline_ms(clock) == 7000
    done = finish(clock)
    assert next_deadline_ms(done) is None and not end_due(done, 99_999)


def test_the_end_waits_for_every_step_to_be_released():
    clock = start(begin(schedule()), 0)
    assert not end_due(clock, 99_999)           # nothing released yet: the end is not "due", the steps are


# ------------------------------------------------------------------ pause and resume preserve the remaining offsets

def test_a_pause_preserves_every_remaining_offset_exactly():
    clock = start(begin(schedule()), 0)
    clock, _ = run_to_end(clock, [0, 1000])                  # steps 0 and 1 released; step 2 due at 2500
    clock = pause(clock, 1700)                               # 800 ms before step 2
    assert due(clock, 50_000) == () and next_deadline_ms(clock) is None
    clock = resume(clock, 21_700)                            # 20 s later
    assert (clock.shift_ms, clock.paused) == (20_000, False)
    assert scheduled_ms(clock, 2500) == 22_500               # still 800 ms after the resume
    assert due(clock, 22_499) == () and [d.index for d in due(clock, 22_500)] == [2]
    assert next_deadline_ms(clock) == 22_500


def test_several_pauses_add_up_and_the_elapsed_time_is_frozen_while_paused():
    clock = start(begin(schedule()), 0)
    clock = pause(clock, 500)
    assert elapsed_ms(clock, 9999) == 500
    clock = resume(clock, 1500)
    clock = pause(clock, 2000)                               # sequence time 1000
    clock = resume(clock, 5000)                              # +3000
    assert clock.shift_ms == 4000 and elapsed_ms(clock, 5200) == 1200
    assert scheduled_ms(clock, 4000) == 8000
    assert elapsed_ms(clock, 10 ** 9) == 6000                # never beyond the length


def test_pausing_twice_or_resuming_twice_changes_nothing():
    clock = start(begin(schedule()), 0)
    once = pause(clock, 100)
    assert pause(once, 900) == once
    assert resume(clock, 900) == clock
    assert resume(resume(once, 600), 700) == resume(once, 600)


def test_a_pause_at_the_boundary_before_a_late_step_leaves_it_due_on_resume():
    clock = start(begin(schedule()), 0)
    clock = release(clock, 0)
    clock = pause(clock, 1200)                               # step 1 (1000) was due, a boundary pause took the run first
    clock = resume(clock, 31_200)
    assert [d.index for d in due(clock, 31_200)] == [1]      # released at once: as late as it was, no more, no less


def test_a_paused_or_unstarted_or_finished_clock_has_no_deadline():
    clock = begin(schedule())
    assert next_deadline_ms(clock) is None and elapsed_ms(clock, 1000) == 0
    assert pause(clock, 5) == clock                           # nothing to pause before t0
    clock = start(clock, 0)
    with pytest.raises(ValueError):
        start(clock, 10)                                      # t0 is set once: a second start would move every due time


def test_steps_are_released_in_order_once():
    clock = start(begin(schedule()), 0)
    with pytest.raises(ValueError):
        release(clock, 1)
    clock = release(clock, 0)
    with pytest.raises(ValueError):
        release(clock, 0)


def test_the_schedule_refuses_offsets_that_are_not_strictly_increasing_from_zero():
    for offsets, duration in (((1, 2), 10), ((0, 5, 5), 10), ((0, 5), 5), ((), 5)):
        with pytest.raises(ValueError):
            SequenceSchedule("x", tuple(f"s{i}" for i in range(len(offsets))), offsets, duration)


# ------------------------------------------------------------------ determinism

def sequence_document(order: list[str]) -> dict:
    step = {"step_id": "a", "offset_ms": 0, "speaker": "jarvis", "text": "Un.", "visual": [], "motion": []}
    base = {"sequence_id": "demo", "label": "Demo", "duration_ms": 5000, "on_interrupt": "pause_resume", "recovery_id": None,
            "steps": [step, {"step_id": "b", "offset_ms": 1500, "speaker": "none", "text": "",
                             "visual": [{"kind": "reveal", "scene_id": "pss_000000000001", "anchor_id": "m"}], "motion": []},
                      {"step_id": "c", "offset_ms": 3000, "speaker": "none", "text": "",
                       "visual": [{"kind": "control_set", "scene_id": "pss_000000000001", "control_id": "h", "value": "X"}],
                       "motion": []}]}
    return {key: base[key] for key in order}


def test_the_same_sequence_on_the_same_clock_gives_the_same_action_log_whatever_the_key_order():
    keys = ["sequence_id", "label", "duration_ms", "on_interrupt", "recovery_id", "steps"]
    logs = []
    for seed in range(12):
        shuffled = keys[:]
        random.Random(seed).shuffle(shuffled)
        document = json.loads(json.dumps(sequence_document(shuffled)))
        document["steps"] = [dict(random.Random(seed + i).sample(sorted(s.items()), len(s))) for i, s in enumerate(document["steps"])]
        sequence = LockedSequence.from_dict(document)
        sched = SequenceSchedule.of(sequence)
        clock = start(begin(sched), 50_000)
        entries = []
        for now in range(50_000, 56_000, 250):
            for d in due(clock, now):
                spec = sequence.steps[d.index]
                clock = release(clock, d.index)
                entries.append(log_entry(clock, d, now, tuple(a.key() for a in (*spec.visual, *spec.motion))).key())
        logs.append(entries)
    assert all(log == logs[0] for log in logs) and len(logs[0]) == 3


def test_a_timeline_is_the_written_order_with_increasing_offsets():
    sequence = LockedSequence.from_dict(sequence_document(["sequence_id", "label", "duration_ms", "steps"]))
    assert [offset for offset, _ in sequence.timeline()] == [0, 1500, 3000]
    assert SequenceSchedule.of(sequence).offsets_ms == (0, 1500, 3000)


# ------------------------------------------------------------------ the interruption policy as data

@pytest.mark.parametrize("policy, kind, expected", [
    (Interruption.ALLOW, InputKind.PAUSE, Verdict.NOW), (Interruption.ALLOW, InputKind.DETOUR, Verdict.NOW),
    (Interruption.AT_BOUNDARY, InputKind.PAUSE, Verdict.AT_BOUNDARY), (Interruption.AT_BOUNDARY, InputKind.DETOUR, Verdict.AT_BOUNDARY),
    (Interruption.REFUSE, InputKind.PAUSE, Verdict.REFUSE), (Interruption.REFUSE, InputKind.DETOUR, Verdict.REFUSE),
])
def test_pause_and_detour_follow_the_declared_policy_exactly(policy, kind, expected):
    assert input_verdict(policy, kind) is expected


@pytest.mark.parametrize("policy", list(Interruption))
def test_navigation_is_refused_whatever_the_policy_and_stop_and_skip_always_go_through(policy):
    assert input_verdict(policy, InputKind.NAVIGATE) is Verdict.REFUSE
    assert input_verdict(policy, InputKind.STOP) is Verdict.NOW
    assert input_verdict(policy, InputKind.SKIP) is Verdict.NOW


def test_the_interruption_plan_says_where_a_continue_lands():
    assert interruption_plan(Interruption.AT_BOUNDARY, SequenceInterrupt.PAUSE_RESUME).recover_on_resume is False
    assert interruption_plan(Interruption.AT_BOUNDARY, SequenceInterrupt.ABORT_TO_RECOVERY).recover_on_resume is True
    assert interruption_plan(Interruption.REFUSE, SequenceInterrupt.ABORT_TO_RECOVERY).verdict is Verdict.REFUSE

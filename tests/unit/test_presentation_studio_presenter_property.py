"""Random scores and random interruptions never reach an illegal state through the Jarvis presenter (jarvis-interactive-presentation-studio, Slice 14).

Seeded, so a failure is a seed to replay. For each seed: a random valid score (Jarvis lines, silences, user items, locked sequences
with random steps and interruption policies), a random walk of clock jumps, speech facts (ours and not ours, normal and failing),
user floor takes and turns, user commands, a speech stack that refuses sometimes. After EVERY action the invariants hold:

- the playback machine's own invariants (`check_invariants`);
- the presenter speaks only the text of `presenter=jarvis` items and Jarvis steps, never a user item's note, never when the run
  does not make Jarvis speak, and only while the run is PLAYING;
- a paused run is never resumed by the presenter (only by the harness's explicit `resume`);
- one item entry is spoken once, plus once per explicit continue (never twice for one item);
- every pump terminates; at the end the stop restores the mode.
"""

from __future__ import annotations

import random

import pytest

from jarvis.domain import presentation_studio_playback as pb
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.interaction_mode import InteractionMode
from tests.fakes.presentation_studio_presenter import FakeBrain, NOTE_SECRET, SECRET, advance, make_presenter, set_ms
from tests.unit.test_presentation_studio_playback_service import Rig, S1, S2, S3, applied

SEEDS = range(24)
STEPS = 70
#: What the walks actually did, summed over the seeds: `test_the_walks_were_not_vacuous` checks they exercised the presenter.
STATS = {"lines": 0, "steps": 0, "pauses": 0, "interrupts": 0, "failures": 0, "advances": 0}


def item_id(n: int) -> str:
    return f"psi_{n:012x}"


def random_content(rng: random.Random) -> tuple[dict, set[str]]:
    count = rng.randint(3, 7)
    items, sequences, points, jarvis_texts = [], [], [], set()
    for n in range(1, count + 1):
        base = {"item_id": item_id(n), "scene_id": rng.choice([S1, S2, S3]),
                "next_item_id": item_id(n + 1) if n < count else None,
                "interruption": rng.choice(["allow", "at_boundary", "refuse"])}
        kind = rng.choices(["line", "silence", "user", "host"], [4, 2, 2, 2])[0]
        if n == 1 and kind == "user":
            kind = "line"
        if kind == "line":
            text = f"L{n} {SECRET}."
            jarvis_texts.add(text)
            items.append({**base, "presenter": "jarvis", "kind": "speech", "text": text,
                          "recovery": rng.choice(["continue_item", "restart_item", "skip_to_next"])})
        elif kind == "silence":
            items.append({**base, "presenter": "none", "kind": "silence", "target_duration_ms": rng.choice([500, 1500, 3000])})
        elif kind == "user":
            items.append({**base, "presenter": "user", "kind": "speech", "note": f"N{n} {NOTE_SECRET}"})
        else:
            offsets = sorted(rng.sample(range(500, 9000, 500), rng.randint(1, 3)))
            steps = []
            spoken = rng.randrange(len(offsets) + 1)
            for j, offset in enumerate([0, *offsets]):
                step = {"step_id": f"st{j}", "offset_ms": offset}
                if j == spoken:
                    text = f"S{n}{j} {SECRET}."
                    jarvis_texts.add(text)
                    step.update({"speaker": "jarvis", "text": text})
                else:
                    step["motion"] = [{"kind": "control_set", "scene_id": S2, "control_id": "density", "value": "compact"}]
                steps.append(step)
            duration = offsets[-1] + 1000
            sequence = {"sequence_id": f"seq{n}", "label": "Seq", "duration_ms": duration, "steps": steps,
                        "on_interrupt": rng.choice(["pause_resume", "abort_to_recovery"])}
            if sequence["on_interrupt"] == "abort_to_recovery":
                sequence["recovery_id"] = f"rp{n}"
                points.append({"recovery_id": f"rp{n}", "label": "Back", "item_id": item_id(n)})
            sequences.append(sequence)
            items.append({**base, "presenter": "jarvis", "kind": "speech", "timing": "locked",
                          "visual": [{"kind": "sequence", "sequence_id": f"seq{n}"}], "target_duration_ms": duration,
                          "interruption": rng.choice(["at_boundary", "refuse"]), "recovery": "continue_item"})
    if not jarvis_texts:
        items[0] = {**items[0], "presenter": "jarvis", "kind": "speech", "text": f"L1 {SECRET}.", "recovery": "continue_item"}
        items[0].pop("note", None)
        items[0].pop("target_duration_ms", None)
        jarvis_texts.add(f"L1 {SECRET}.")
    return {"start_item_id": item_id(1), "items": items, "cues": [], "sequences": sequences, "recovery_points": points}, jarvis_texts


class WatchedBrain(FakeBrain):
    """Records the phase and the run's role at the instant of every call."""

    def __init__(self, rig) -> None:
        super().__init__()
        self.rig, self.seen = rig, []

    async def announce_notice(self, text, **kwargs):
        state = self.rig.service.state
        self.seen.append((state.phase, state.jarvis_speaks, state.position, state.epoch))
        return await super().announce_notice(text, **kwargs)


@pytest.mark.parametrize("seed", SEEDS)
async def test_random_scores_and_interruptions_never_reach_an_illegal_state(tmp_path, seed):
    rng = random.Random(seed)
    content, jarvis_texts = random_content(rng)
    rig = await Rig(tmp_path).open(content=content, mode=InteractionMode.PRESENTATION)
    set_ms(rig, 1_000_000)
    presenter, _, voice = make_presenter(rig, gap_ms=rng.choice([0, 200]))
    brain = WatchedBrain(rig)
    brain.presenter = presenter
    presenter._brain = brain
    voice.brain = brain
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    resumes: dict[tuple[int, int], int] = {}
    try:
        for step in range(STEPS):
            before = rig.service.state
            explicit = None
            action = rng.choices(
                ["pump", "tick", "started", "completed", "interrupted", "failed", "floor", "turn", "other", "pause", "resume",
                 "next", "previous", "skip", "goto", "refuse", "accept"],
                [2, 6, 7, 7, 2, 1, 2, 2, 2, 2, 4, 2, 1, 1, 1, 1, 2])[0]
            if action == "tick":
                advance(rig, rng.choice([1, 100, 500, 1000, 2500, 5000, 12_000]))
            elif action in ("started", "completed", "interrupted", "failed"):
                ids = [f"sp-{i:04d}" for i in range(1, brain.count + 1)]
                if ids:
                    sid = brain.last_id if rng.random() < 0.85 else rng.choice(ids)
                    if action == "started":
                        voice.started(sid)
                    elif action == "completed":
                        voice.completed(sid)
                    elif action == "interrupted":
                        voice.interrupted(sid)
                    else:
                        voice.terminal(rng.choice([T.MOUTH_SPEECH_FAILED, T.MOUTH_SPEECH_EXPIRED, T.MOUTH_SPEECH_UNCONFIRMED]), sid)
            elif action == "floor":
                voice.floor()
            elif action == "turn":
                voice.user_turn()
            elif action == "other":
                voice.other_speech()
            elif action == "refuse":
                brain.published = False
            elif action == "accept":
                brain.published = True
            elif action in ("pause", "resume", "next", "previous"):
                explicit = action
                result = await rig.run(action)
                if action == "resume" and result.status.value == "applied" and before.phase in (pb.Phase.PAUSED, pb.Phase.DETOUR):
                    key = (before.position, before.epoch)
                    resumes[key] = resumes.get(key, 0) + 1
            elif action == "skip":
                explicit = action
                await rig.run("skip_sequence")
            elif action == "goto" and rig.service.plan is not None:
                explicit = action
                await rig.run("goto", position=rng.randint(1, len(rig.service.plan)))
            await presenter.pump()
            after = rig.service.state
            if after.active:
                assert pb.check_invariants(rig.service.plan, after) == [], (seed, step, action)
            if before.phase in (pb.Phase.PAUSED, pb.Phase.DETOUR) and after.phase is pb.Phase.PLAYING:
                assert explicit == "resume", (seed, step, action, "the presenter resumed a paused run")
            if not after.active:
                break
        # speech discipline over the whole walk
        assert all(text in jarvis_texts for text in brain.texts), (seed, [t for t in brain.texts if t not in jarvis_texts])
        assert all(NOTE_SECRET not in text for text in brain.texts)
        assert all(phase is pb.Phase.PLAYING and speaks for phase, speaks, _, _ in brain.seen), (seed, brain.seen)
        counts: dict[tuple, int] = {}
        for key, tag in presenter.issue_log:
            counts[(key, tag)] = counts.get((key, tag), 0) + 1
        for (key, tag), issued in counts.items():
            assert issued <= 1 + resumes.get(key, 0), (seed, key, tag, issued, resumes)
        STATS["lines"] += len(brain.calls)
        STATS["steps"] += len(presenter.action_log)
        STATS["pauses"] += sum(1 for k, _, a in rig.conversation.recorded if a.get("status") == "paused")
        STATS["interrupts"] += sum(1 for k, _, a in rig.conversation.recorded if a.get("status") == "interrupted")
        STATS["failures"] += sum(1 for k, _, a in rig.conversation.recorded if a.get("status") == "line_failed")
        if rig.service.state.active:
            applied(await rig.run("stop"))
        await presenter.pump()
        assert rig.mode.mode is InteractionMode.PRESENTATION and presenter.view() is None      # restored, detached
    finally:
        await rig.close()


async def test_a_run_that_does_not_make_jarvis_speak_never_gets_a_line_whatever_happens(tmp_path):
    rng = random.Random(99)
    content, _ = random_content(rng)
    rig = await Rig(tmp_path).open(content=content)
    set_ms(rig, 1_000_000)
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("user_presenter")))
    for _ in range(30):
        advance(rig, rng.choice([100, 1000, 9000]))
        rng.choice([voice.floor, voice.user_turn, voice.other_speech])()
        await presenter.pump()
        if rig.service.state.phase is pb.Phase.PLAYING and rng.random() < 0.5:
            await rig.run("next")
    assert brain.calls == []
    await rig.close()


def test_the_walks_were_not_vacuous():
    """The walks above spoke, ran sequence steps, were interrupted and saw failures: they did not pass by doing nothing."""

    assert STATS["lines"] >= 60 and STATS["steps"] >= 15, STATS
    assert STATS["interrupts"] >= 5 and STATS["failures"] >= 3, STATS

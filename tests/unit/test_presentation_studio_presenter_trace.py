"""Trace evidence of a replayed scripted presentation through the REAL speech path (jarvis-interactive-presentation-studio, Slice 14).

Agent-trace-analysis for the Jarvis presenter. A whole scripted presentation is replayed in process: Jarvis starts from PRESENTATION mode
(the switch reaches the Voice observer), says a line, holds a silence, runs a locked sequence with two spoken steps, is interrupted by the
user in the middle of it, waits, is told to continue, finishes, and the mode is restored. Everything on the speech side is the product's
code (`BrainOrchestrator.announce_notice`, the Conversation Event emitter, the Voice `SpeechScheduler`, its gate and mode observer); only
the voice surface is a recorder. The test asserts the properties of the trace (one hand-over per line, no retry, no duplicate, the order of
the facts, the exact schedule of the steps, no text anywhere) and, with `JARVIS_WRITE_TRACE_EVIDENCE=1`, writes the redacted evidence to
`tasks/jarvis-interactive-presentation-studio/slices/14-jarvis-presenter-locked-sequences/evidence/scripted-presentation-trace.json`.

Redaction targets (the user name, the home directory, the temporary folders, every id) are derived at run time, never hard-coded. The
evidence holds ids as ordinals, kinds, counts and times: never a spoken text, never a local path.

NOT run live: nothing was spoken on a real voice stack; the surface is a recorder, the clock of the presenter is a fake.
"""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import re
import tempfile

from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.v2 import BrainTurnInput, PlaybackCursor
from tests.fakes.presentation_studio_presenter import (
    NOTE_SECRET, SECRET, SEQ_INTRO, SEQ_WRAP, TEXT_A, TEXT_D, advance, locked_content, now_ms,
)
from tests.unit.test_brain_delegation import _idle
from tests.unit.test_presentation_studio_playback_service import applied
from tests.unit.test_presentation_studio_presenter_speech import build, close, forward_mode_change
from tests.unit.test_v2_speech_scheduler import finish_speech, wait_for
import tests.unit.test_v2_speech_scheduler as scheduler_tests

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (ROOT / "tasks/jarvis-interactive-presentation-studio/slices/14-jarvis-presenter-locked-sequences/evidence"
            / "scripted-presentation-trace.json")
SCRIPT_TEXTS = (TEXT_A, TEXT_D, SEQ_INTRO, SEQ_WRAP)


def redaction_targets() -> list[str]:
    """Everything that identifies this machine or this run, found at run time."""

    targets = {getpass.getuser(), os.environ.get("USERNAME", ""), os.environ.get("USER", ""), Path.home().name,
               str(Path.home()), str(Path.home()).replace("\\", "/"), tempfile.gettempdir(), tempfile.gettempdir().replace("\\", "/"),
               str(ROOT), str(ROOT).replace("\\", "/")}
    return sorted((t for t in targets if t and len(t) > 2), key=len, reverse=True)


class Ordinals:
    """`speech-1`, `speech-2`...: the first time an id is seen it gets the next ordinal, so two replays give the same evidence."""

    def __init__(self) -> None:
        self.seen: dict[str, str] = {}

    def __call__(self, prefix: str, value: str | None) -> str | None:
        if value is None:
            return None
        return self.seen.setdefault(f"{prefix}:{value}", f"{prefix}-{sum(1 for k in self.seen if k.startswith(prefix + ':')) + 1}")


async def replay(tmp_path) -> dict:
    scheduler_tests.ORIGIN = __import__("jarvis.domain.v2", fromlist=["utc_now"]).utc_now()
    world = await build(tmp_path, core_mode=InteractionMode.PRESENTATION, content=locked_content())
    calls: list[dict] = []
    real_announce = world.brain.announce_notice

    async def recording_announce(text, **kwargs):
        result = await real_announce(text, **kwargs)
        calls.append({"at_ms": now_ms(world.rig) - 1_000_000, "chars": len(text), "published": result,
                      "kind": kwargs["kind"].value, "ttl_s": kwargs["ttl_s"], "slot": "presentation_studio:<run>"})
        return result

    world.presenter._brain = type("Recording", (), {"announce_notice": staticmethod(recording_announce)})()
    rig, presenter, session, scheduler = world.rig, world.presenter, world.session, world.scheduler
    marks: list[dict] = []

    def mark(label: str, **extra) -> None:
        state = rig.service.where()
        marks.append({"at_ms": now_ms(rig) - 1_000_000, "step": label, "phase": state.get("phase"),
                      "position": (state.get("position") or {}).get("index"), "owner": state.get("owner"),
                      "speaking": state.get("speaking"), "sequence": (state.get("sequence") or {}).get("step"),
                      "problems": list(state.get("problems") or []), "mode": rig.mode.mode.value,
                      "voice_mode": world.observer.mode.value, **extra})

    async def sent(kind: str, count: int) -> None:
        await wait_for(lambda: sum(1 for e in scheduler.conversation_events.sent if e.event_type.value == kind) >= count)

    try:
        mark("before_start")
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        forward_mode_change(world)
        mark("started")
        await presenter.pump()
        await wait_for(lambda: len(session.spoken) == 1)
        await sent("mouth.speech.started", 1)
        await presenter.pump()
        mark("line_1_playing")
        await finish_speech(scheduler, session)
        await sent("mouth.speech.completed", 1)
        await presenter.pump()
        mark("line_1_heard_then_the_sequence_waits_for_its_first_words")
        await wait_for(lambda: len(session.spoken) == 2)
        await sent("mouth.speech.started", 2)
        await presenter.pump()
        t0 = now_ms(rig)
        mark("sequence_t0_is_the_first_words_started", t0_ms=0)
        await finish_speech(scheduler, session)
        await sent("mouth.speech.completed", 2)
        advance(rig, 3000)
        await presenter.pump()
        mark("step_mid_released_at_3000", offset_ms=now_ms(rig) - t0)
        advance(rig, 1000)
        scheduler.note_floor_taken("speaking")                      # the user takes the floor, between two steps
        await sent("mouth.floor.taken", 1)
        await presenter.pump()
        mark("user_took_the_floor_pause_pending_until_the_boundary")
        advance(rig, 2500)
        await presenter.pump()
        mark("boundary_reached_run_paused_before_step_wrap", offset_ms=now_ms(rig) - t0)
        await world.brain.submit(BrainTurnInput(conversation_id=world.conversation_id, text="Une question en passant."))
        await _idle(world.brain)                                    # the user's turn is answered by a new intention
        scheduler.note_floor_decided("addressed")
        advance(rig, 20_000)
        await presenter.pump()
        mark("twenty_seconds_later_still_paused_never_resumes_alone")
        applied(await rig.run("resume"))
        await presenter.pump()
        mark("explicit_continue_step_wrap_released_at_once")
        await wait_for(lambda: len(session.spoken) == 3)
        await sent("mouth.speech.started", 3)
        await presenter.pump()
        await finish_speech(scheduler, session)
        await sent("mouth.speech.completed", 3)
        rig.mono.t = (t0 + 9000 + 20_000) / 1000                    # the exact length, plus the 20 s the run was paused
        await presenter.pump()
        mark("sequence_done_at_its_exact_length_plus_the_pause", offset_ms=now_ms(rig) - t0)
        log = [{"step": e.step_id, "offset_ms": e.offset_ms, "scheduled_rel_t0_ms": e.scheduled_ms - t0, "released_rel_t0_ms": e.released_ms - t0,
                "late_ms": e.late_ms, "actions": len(e.actions)} for e in presenter.action_log]
        await presenter.pump()
        await wait_for(lambda: len(session.spoken) == 4)
        await sent("mouth.speech.started", 4)
        await presenter.pump()
        await finish_speech(scheduler, session)
        await sent("mouth.speech.completed", 4)
        await presenter.pump()
        forward_mode_change(world)                                  # the restore reaches the Voice observer as the switch did
        mark("last_line_heard_run_completed")
        return {"world": world, "calls": calls, "marks": marks, "log": log, "t0": t0}
    except BaseException:
        await close(world)
        raise


def build_evidence(result: dict) -> dict:
    world = result["world"]
    ordinal = Ordinals()
    rig, scheduler = world.rig, world.scheduler
    facts = []
    for event in scheduler.conversation_events.sent:
        attributes = dict(event.attributes)
        facts.append({"type": event.event_type.value, "speech": ordinal("speech", event.speech_id),
                      **{k: attributes[k] for k in ("reason", "played_ms", "kind", "while") if k in attributes}})
    diagnostics = [{"kind": kind.removeprefix("core.presentation_studio."), "level": level,
                    **{k: v for k, v in data.items() if k in ("tag", "chars", "why", "applied", "step_id", "offset_ms", "late_ms", "actions", "steps",
                                                              "duration_ms", "code", "source", "verdict", "recover_on_resume", "frozen_ms", "recovery",
                                                              "lines", "position", "lag_ms", "kind")}}
                   for kind, level, data in rig.env.sink.rows if kind.startswith("core.presentation_studio.presenter_")]
    presenter_events = [{"status": a.get("status"), "code": a.get("code"), "count": a.get("count")}
                        for k, _, a in rig.conversation.recorded if k.value.endswith("presenter_changed")]
    playback_events = [a.get("status") for k, _, a in rig.conversation.recorded if k.value.endswith("playback_changed")]
    transitions = sum(1 for kind, *_ in rig.env.sink.rows if kind == "core.presentation_studio.playback_transition")
    journal_kinds: dict[str, int] = {}
    for entry in world.journal.events:
        journal_kinds[entry["kind"]] = journal_kinds.get(entry["kind"], 0) + 1
    evidence = {
        "scenario": "Jarvis presents a 4-line score with a silence and a locked sequence; interrupted mid-sequence; explicit continue; completes",
        "path": ["BrainOrchestrator.announce_notice (real)", "Conversation Event emitter (real)", "SpeechScheduler + PresentationSpeechGate + "
                 "InteractionModeObserver (real)", "voice surface (recorder)", "playback service, edit service, scene (real)"],
        "clock": "presenter and playback share a fake monotonic clock (ms); the scheduler runs on its own clock",
        "not_run_live": ["no audible output on a real voice stack", "no real microphone barge-in", "no Voice process boundary (events are handed over in process)",
                         "the presenter's real wake-up loop (driven by hand with pump())", "latency of a real provider"],
        "marks": result["marks"], "announce_notice_calls": result["calls"], "action_log": result["log"],
        "mouth_and_floor_facts": facts, "presenter_diagnostics": diagnostics, "presenter_events": presenter_events,
        "playback_events": playback_events,
        "counts": {"announce_calls": len(result["calls"]), "lines_spoken_by_the_voice_surface": len(world.session.spoken),
                   "playback_transitions": transitions, "scheduler_journal_by_kind": dict(sorted(journal_kinds.items())),
                   "withheld_by_the_gate": journal_kinds.get("voice.presentation.speech_withheld", 0)},
        "analysis": {
            "correctness": "every line was handed over once and said once; the sequence steps were released at t0 + offset exactly, the one after the "
                           "pause at its offset plus the time paused; the run never resumed alone; the mode was switched and restored",
            "efficiency": "one announce_notice per line, no retry, no duplicate; playback transitions are the machine's own bookkeeping "
                          "(speaking on/off, step reports), no stage write beyond the item or step that changed",
            "optimization": ["speaking on/off is one machine transition each (2 per line): could be folded into the line facts if transitions ever matter",
                             "each pump re-reads the state: the loop wakes on every playback commit, including its own (idempotent, one extra look)"],
            "risks": ["the presenter learns the speech id from brain.speech.requested: a Core without a Conversation Event recorder looks like a "
                      "speech stack that never starts (visible: speech_not_started)", "audio latency after issue is the voice stack's (not measured here)"],
        },
    }
    return redact(evidence)


def redact(value):
    """Strip every identifying string found at run time; ids are already ordinals."""

    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    for target in redaction_targets():
        text = text.replace(json.dumps(target)[1:-1], "<redacted>").replace(target, "<redacted>")
    text = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", text)
    return json.loads(text)


async def test_the_replayed_presentation_has_the_trace_it_should_and_no_text_or_path(tmp_path):
    result = await replay(tmp_path)
    world = result["world"]
    try:
        evidence = build_evidence(result)
        serialized = json.dumps(evidence, ensure_ascii=False)
        # 1. one hand-over per line, in order, with the 01c arguments, nothing retried
        calls = evidence["announce_notice_calls"]
        assert [c["chars"] for c in calls] == [len(t) for t in (TEXT_A, SEQ_INTRO, SEQ_WRAP, TEXT_D)]
        assert all(c["published"] and c["kind"] == "progress" and c["ttl_s"] == 30.0 for c in calls)
        assert evidence["counts"]["lines_spoken_by_the_voice_surface"] == 4 and evidence["counts"]["withheld_by_the_gate"] == 0
        # 2. the facts, in order, for the 4 lines
        kinds = [f["type"] for f in evidence["mouth_and_floor_facts"]]
        assert kinds.count("mouth.speech.started") == 4 and kinds.count("mouth.speech.completed") == 4
        assert kinds.count("mouth.floor.taken") == 1 and "mouth.speech.interrupted" not in kinds
        # 3. the schedule: exact from t0, the step after the pause shifted by exactly the time paused
        assert [(e["step"], e["scheduled_rel_t0_ms"]) for e in evidence["action_log"]] == [("intro", 0), ("mid", 3000), ("wrap", 6500 + 20_000)]
        assert [e["late_ms"] for e in evidence["action_log"]] == [0, 0, 0]
        by_step = {m["step"]: m for m in evidence["marks"]}
        assert by_step["user_took_the_floor_pause_pending_until_the_boundary"]["phase"] == "playing"
        assert by_step["boundary_reached_run_paused_before_step_wrap"]["phase"] == "paused"
        assert by_step["twenty_seconds_later_still_paused_never_resumes_alone"]["phase"] == "paused"
        assert by_step["before_start"]["mode"] == "presentation" and by_step["started"]["mode"] == "assistant" == by_step["started"]["voice_mode"]
        assert by_step["last_line_heard_run_completed"]["phase"] == "stopped"
        assert by_step["last_line_heard_run_completed"]["mode"] == by_step["last_line_heard_run_completed"]["voice_mode"] == "presentation"
        assert world.rig.mode.mode is InteractionMode.PRESENTATION
        assert [e["status"] for e in evidence["presenter_events"]] == ["interrupted", "sequence_done", "completed"]
        # 4. no text, no path, no name
        for secret in (*SCRIPT_TEXTS, SECRET, NOTE_SECRET, "Bonjour", "Regardez", "Voila", "Merci", "Une question"):
            assert secret not in serialized, secret
        for target in redaction_targets():
            assert target not in serialized, "a local path or name reached the evidence"
        if os.environ.get("JARVIS_WRITE_TRACE_EVIDENCE") == "1":
            EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
            EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    finally:
        await close(world)


async def test_two_replays_give_the_same_evidence(tmp_path):
    shots = []
    for name in ("one", "two"):
        folder = tmp_path / name
        folder.mkdir()
        result = await replay(folder)
        try:
            evidence = build_evidence(result)
        finally:
            await close(result["world"])
        shots.append(json.dumps({k: evidence[k] for k in ("marks", "announce_notice_calls", "action_log", "presenter_events", "playback_events")},
                                sort_keys=True))
    assert shots[0] == shots[1]

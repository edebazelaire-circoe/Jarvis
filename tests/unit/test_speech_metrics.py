"""Slice 06 speech presentation metrics (`jarvis/testlab/speech_metrics.py`) on a synthetic journal.

The journal is written by the repository's own store (`SQLiteStateRepository` +
`SQLiteConversationEventStore`) and read back through the Test Lab read-only
reader, exactly as the tool reads the real Core journal. No real database.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import hashlib
import json
import shutil

import pytest

from jarvis.core.brain_service import BRAIN_NOTICE_RELAYED_KIND
from jarvis.core.conversation_event_emitter import journal_trace
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.testlab import speech_metrics as sm
from jarvis.testlab.bundle_builder import SessionSelector, TraceLine
from jarvis.testlab.bundle_capture import StateDatabaseEventSource, read_session_events
from tests.fakes.conversation_events import BASE, make_event, open_store

CONV = "conv-metrics"
START, END = BASE, BASE + timedelta(minutes=10)


def _parent(tag: str) -> str:
    return "cev-" + hashlib.sha256(tag.encode()).hexdigest()


def ev(event_type, source, ms, **fields):
    return make_event(event_type, source, conversation_id=CONV, ms=ms, **fields)


def speech(sid, corr, *, queued=None, started=None, end=None, terminal=T.MOUTH_SPEECH_COMPLETED, kind="result",
           chain=None, held=None, session=None, **attributes):
    """The `mouth.speech.*` facts of one speech (times in ms after BASE)."""
    common = {"correlation_id": corr, "speech_id": sid, "session_id": session,
              "parent_event_id": _parent(chain or sid)}
    events = []
    if queued is not None:
        events.append(ev(T.MOUTH_SPEECH_QUEUED, f"{sid}-q", queued, attributes={"kind": kind}, **common))
    if held is not None:
        events.append(ev(T.MOUTH_SPEECH_HELD, f"{sid}-h", held, attributes={"kind": kind, "reason": "held_for_brain"},
                         **common))
    if started is not None:
        events.append(ev(T.MOUTH_SPEECH_STARTED, f"{sid}-s", started, attributes={"kind": kind}, **common))
    if end is not None:
        events.append(ev(terminal, f"{sid}-e", end, attributes={"kind": kind, **attributes}, **common))
    return events


def turn(corr, ms, addressing="addressed"):
    return ev(T.BRAIN_TURN_ACCEPTED, f"turn-{corr}", ms, correlation_id=corr, attributes={"addressing": addressing})


async def write_journal(path, events):
    state, store = await open_store(path)
    try:
        for index in range(0, len(events), 32):
            await store.append_many(events[index:index + 32])
    finally:
        await state.close()


async def measure_db(path, trace=None, *, start=START, end=END):
    report, warnings = await sm.read_window(path, sm.Window("w", start, end), trace)
    return report, warnings


def target(report, metric):
    return next(item for item in report["targets"] if item["metric"] == metric)


# ------------------------------------------------------------------ end of speech

async def test_live_and_realtime_endings_are_counted_per_surface(tmp_path):
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [
        turn("live:c:1", 0),
        *speech("l-ok", "live:c:1", queued=100, started=200, end=2400, completion_basis="local_quiescence",
                release_after_quiescence_ms=520, status="completed"),
        *speech("l-stuck", "live:c:1", queued=2500, started=2600, end=32610, terminal=T.MOUTH_SPEECH_INTERRUPTED,
                reason="delivery_not_complete", played_ms=0),
        *speech("l-mute", "live:c:1", queued=33000, started=33100, end=41100, terminal=T.MOUTH_SPEECH_UNCONFIRMED,
                code="speech_output_unconfirmed", completion_basis="unconfirmed"),
        turn("realtime:c:2", 50000),
        *speech("r-ok", "realtime:c:2", queued=50100, started=50200, end=53000,
                completion_basis="provider_response_done"),
    ])
    report, warnings = await measure_db(db)
    live, realtime = report["surfaces"]["live"], report["surfaces"]["realtime"]
    assert (live["started"], live["completed"], live["unconfirmed"]) == (3, 1, 1)
    assert live["completed_by_basis"] == {"local_quiescence": 1}
    assert live["delivery_not_complete_near_30s"] == 1
    assert live["release_after_quiescence_ms"]["p95"] == 520
    assert live["duration_ms_by_end"]["interrupted/delivery_not_complete"]["max"] == pytest.approx(30010, abs=1)
    assert realtime["completed_by_basis"] == {"provider_response_done": 1}
    assert target(report, "live_release_after_quiescence_p95_ms")["verdict"] == "pass"
    assert target(report, "live_delivery_not_complete_near_30s")["verdict"] == "fail"
    # No trace given: stalls are not measured, never reported as 0.
    assert live["output_stalled"] is None and target(report, "live_output_stalled")["verdict"] == "n/a"
    assert report["sources"]["journal"]["status"] == "available" and not warnings


async def test_a_slow_live_release_fails_its_target(tmp_path):
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [turn("live:c:1", 0), *speech(
        "l-slow", "live:c:1", queued=10, started=20, end=3000, completion_basis="local_quiescence",
        release_after_quiescence_ms=1400)])
    report, _ = await measure_db(db)
    assert target(report, "live_release_after_quiescence_p95_ms") | {"label": None} == {
        "metric": "live_release_after_quiescence_p95_ms", "label": None, "target": "< 1000 ms", "value": 1400.0,
        "verdict": "fail"}


# ------------------------------------------------------------ outdated formulations

async def test_a_formulation_started_after_a_newer_turn_is_outdated(tmp_path):
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [
        turn("live:c:1", 0),
        *speech("old", "live:c:1", queued=100, started=5000, end=6000),        # turn 2 current at 5 s
        turn("live:c:2", 3000),
        *speech("fresh", "live:c:2", queued=3100, started=6100, end=7000),
        turn("live:c:3", 8000, addressing="uncertain"),                         # does not change the intent
        *speech("still-current", "live:c:2", queued=7500, started=9000, end=9500),
        *speech("ack", "live:c:1", queued=200, started=9600, end=9700, kind="ack"),  # transient: not a formulation
    ])
    report, _ = await measure_db(db)
    assert report["outdated_started"] == 1
    assert target(report, "outdated_started")["verdict"] == "fail"


async def test_the_rest_of_a_chain_already_speaking_is_not_outdated(tmp_path):
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [
        turn("realtime:c:1", 0),
        *speech("a1", "realtime:c:1", queued=100, started=200, end=2000, chain="chain-a"),
        turn("realtime:c:2", 1000),
        *speech("a2", "realtime:c:1", queued=100, started=2050, end=3000, chain="chain-a"),
    ])
    report, _ = await measure_db(db)
    assert report["outdated_started"] == 0 and target(report, "outdated_started")["verdict"] == "pass"


async def test_held_formulations_their_verdicts_and_a_held_one_that_started(tmp_path):
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [
        turn("live:c:1", 0), turn("live:c:2", 1000),
        *speech("kept", "live:c:1", queued=100, held=1100, end=4000, terminal=T.MOUTH_SPEECH_SUPERSEDED,
                reason="revalidated_as", revalidated_as="new-id"),
        *speech("dropped", "live:c:1", queued=110, held=1100, end=4000, terminal=T.MOUTH_SPEECH_SUPERSEDED,
                reason="not_revalidated"),
        *speech("timeout", "live:c:1", queued=120, held=1100, end=121100, terminal=T.MOUTH_SPEECH_EXPIRED,
                reason="held_for_brain_timeout"),
        *speech("leak", "live:c:1", queued=130, held=1100, started=5000, end=6000,
                completion_basis="local_quiescence"),
    ])
    report, _ = await measure_db(db)
    held = report["held"]
    assert held["speeches"] == 4 and held["by_reason"] == {"held_for_brain": 4}
    assert held["verdicts"] == {"revalidated_as": 1, "not_revalidated": 1, "held_for_brain_timeout": 1,
                                "completed/-": 1}
    assert held["held_then_started"] == 1 and target(report, "held_then_started")["verdict"] == "fail"


# ------------------------------------------------------------------- queue wait

async def test_queue_wait_counts_only_beyond_the_speech_in_progress_and_the_floor(tmp_path):
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [
        turn("realtime:c:1", 0),
        *speech("first", "realtime:c:1", queued=100, started=200, end=5000),
        *speech("second", "realtime:c:1", queued=300, started=5300, end=6000),     # 300 ms after `first` ended
        ev(T.MOUTH_FLOOR_TAKEN, "floor-1", 6100, attributes={"while": "speaking"}),
        ev(T.MOUTH_FLOOR_RELEASED, "floor-1r", 8000, attributes={"while": "speaking", "reason": "noise",
                                                                  "duration_ms": 1900}),
        *speech("third", "realtime:c:1", queued=6050, started=8400, end=9000),     # 400 ms after the floor came back
        *speech("late", "realtime:c:1", queued=9500, started=12500, end=13000),    # 3 s with nothing in progress
        # Held for the brain and yet started: excluded from the waits (it is a defect counted elsewhere).
        *speech("held", "realtime:c:1", queued=13100, held=13200, started=16000, end=16500),
    ])
    report, _ = await measure_db(db)
    waits = report["surfaces"]["realtime"]["current_intent_queue_wait_ms"]
    # Waits 100 (first), 300 (after `first`), 400 (after the freeze, not 2350), 3000 (late).
    assert waits == {"count": 4, "p50": 350.0, "p95": pytest.approx(2610.0), "max": 3000.0}
    assert report["held"]["held_then_started"] == 1
    assert report["floor"] == {"taken_by_while": {"speaking": 1}, "released_by_reason": {"noise": 1},
                               "duration_ms": {"count": 1, "p50": 1900.0, "p95": 1900.0, "max": 1900.0},
                               "timeouts": 0}
    assert target(report, "current_intent_queue_wait_p95_ms")["verdict"] == "fail"


# ---------------------------------------------------------------------- relays

async def test_relays_without_kind_or_ttl_are_violations(tmp_path):
    db = tmp_path / "state.sqlite3"
    relayed = journal_trace(BRAIN_NOTICE_RELAYED_KIND, "conversation_id", "speech_id")

    def request(source, ms, **fields):
        return ev(T.BRAIN_SPEECH_REQUESTED, source, ms, producer="core.brain_service", speech_id=f"sp-{source}",
                  **fields)

    await write_journal(db, [
        request("ack-ok", 100, trace_ref=relayed, attributes={
            "kind": "ack", "priority": "normal", "supersedes_key": "calibration:s:5",
            "expires_at": (BASE + timedelta(seconds=15)).isoformat()}),
        request("ack-eternal", 200, trace_ref=relayed, attributes={"kind": "ack", "priority": "normal"}),
        request("analysis", 300, trace_ref=relayed, attributes={"kind": "result", "priority": "normal",
                                                                "supersedes_key": "calibration:s:5"}),
        request("old-path", 400, attributes={"kind": "result", "priority": "normal"}),
        request("turn-answer", 500, work_id="brain-turn:x", attributes={"kind": "result", "priority": "high"}),
    ])
    report, _ = await measure_db(db)
    # A typed relay is seen: from then on relays are identified positively, and the
    # workless `old-path` answer is not a relay.
    assert report["relays"] == {"typed_by_kind": {"ack": 2, "result": 1}, "without_kind": 0,
                                "transient_without_ttl": 1, "legacy_heuristic": 0,
                                "cutoff": (BASE + timedelta(milliseconds=100)).isoformat(), "violations": 1}
    assert target(report, "relay_violations")["verdict"] == "fail"


def _request(source, at, **fields):
    return make_event(T.BRAIN_SPEECH_REQUESTED, source, conversation_id=CONV,
                      ms=int((at - BASE).total_seconds() * 1000), producer="core.brain_service",
                      speech_id=f"sp-{source}", **fields)


async def test_a_workless_brain_answer_after_the_slice_03_cut_off_is_not_a_relay(tmp_path):
    """QA probe P2: after Slice 03 a plain answer without work has the old relay shape."""
    db = tmp_path / "state.sqlite3"
    after = sm.SLICE_03_CUTOFF + timedelta(hours=1)
    await write_journal(db, [_request("answer", after, correlation_id="realtime:c:1",
                                      attributes={"kind": "result", "priority": "normal"})])
    report, _ = await measure_db(db, start=after - timedelta(minutes=1), end=after + timedelta(minutes=1))
    assert report["relays"]["violations"] == 0 and report["relays"]["legacy_heuristic"] == 0
    assert target(report, "relay_violations") | {"label": None} == {
        "metric": "relay_violations", "label": None, "target": "0", "value": 0, "verdict": "n/a"}


async def test_before_the_cut_off_untyped_relays_are_reported_as_legacy_heuristic(tmp_path):
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [_request("old-relay", BASE + timedelta(seconds=1),
                                      attributes={"kind": "result", "priority": "normal"})])
    report, _ = await measure_db(db)
    assert (report["relays"]["legacy_heuristic"], report["relays"]["violations"]) == (1, 0)
    assert target(report, "relay_violations")["value"] == 1
    assert target(report, "relay_violations")["verdict"] == "fail"


# --------------------------------------------------------- promoted uncertain turns

async def test_the_answer_of_a_promoted_uncertain_turn_is_not_outdated(tmp_path):
    """QA probe P1: an uncertain turn the brain answers is the current intent from its first speech."""
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [
        turn("realtime:c:1", 0),
        *speech("a1", "realtime:c:1", queued=100, started=200, end=900),
        turn("realtime:c:2", 2000, addressing="uncertain"),
        *speech("a2", "realtime:c:2", queued=4000, started=4100, end=5000),
    ])
    report, _ = await measure_db(db)
    assert report["outdated_started"] == 0


async def test_an_old_answer_started_after_a_promoted_uncertain_turn_spoke_is_outdated(tmp_path):
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [
        turn("realtime:c:1", 0),
        *speech("old", "realtime:c:1", queued=100, started=6000, end=7000),
        turn("realtime:c:2", 2000, addressing="uncertain"),
        *speech("new", "realtime:c:2", queued=4000, started=4100, end=5000),   # promoted at 4 s
        turn("realtime:c:3", 8000, addressing="uncertain"),                     # never speaks: never current
        *speech("still-c2", "realtime:c:2", queued=8500, started=9000, end=9500),
    ])
    report, _ = await measure_db(db)
    assert report["outdated_started"] == 1


# ------------------------------------------------------ Live silence after a barge-in

async def test_live_silence_after_a_barge_in_is_measured_to_the_next_heard_speech(tmp_path):
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [
        turn("live:c:1", 0),
        *speech("cut", "live:c:1", queued=10, started=100, end=1000, terminal=T.MOUTH_SPEECH_INTERRUPTED,
                reason="user_barge_in", played_ms=800, session="sess-1"),
        ev(T.MOUTH_FLOOR_TAKEN, "floor-1", 1000, session_id="sess-1", correlation_id="live:c:1",
           attributes={"while": "speaking"}),
        *speech("muted", "live:c:1", queued=2000, started=2100, end=10100, terminal=T.MOUTH_SPEECH_UNCONFIRMED,
                session="sess-1"),
        *speech("heard", "live:c:1", queued=20000, started=20100, end=21000, completion_basis="local_quiescence",
                session="sess-1"),
    ])
    report, _ = await measure_db(db)
    silence = report["live_silence_after_barge_in"]
    assert silence["barge_ins"] == 1  # the interrupted speech and its floor are one barge-in
    assert silence["next_heard_ms"]["max"] == pytest.approx(20000, abs=1)
    assert (silence["never_heard_again"], silence["unconfirmed_before_next_heard"]) == (0, 1)


# ------------------------------------------------------------------ stalls (trace)

async def test_stalls_come_from_the_trace_by_surface(tmp_path):
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [turn("live:c:1", 0), *speech("l", "live:c:1", queued=10, started=20, end=30030,
                                                         terminal=T.MOUTH_SPEECH_INTERRUPTED,
                                                         reason="delivery_not_complete")])
    lines = [TraceLine(offset=0, ts=BASE + timedelta(seconds=30), kind="voice.speech.output_stalled", level="warning",
                       data={"correlation_id": "live:c:1", "code": "speech_output_stalled"}),
             TraceLine(offset=100, ts=BASE + timedelta(seconds=31), kind="voice.speech.output_stalled",
                       level="warning", data={"correlation_id": "realtime:c:9"})]
    events = (await read_session_events(StateDatabaseEventSource(db), SessionSelector(start=START, end=END))).events
    report = sm.measure(events, start=START, end=END, trace_lines=lines)
    assert report["surfaces"]["live"]["output_stalled"] == 1
    assert target(report, "live_output_stalled")["verdict"] == "fail"


async def test_a_trace_that_does_not_cover_the_window_measures_nothing(tmp_path):
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [turn("live:c:1", 0), *speech("l", "live:c:1", queued=10, started=20, end=900,
                                                         completion_basis="local_quiescence")])
    trace = tmp_path / "trace.jsonl"
    trace.write_text(json.dumps({"ts": "2026-01-01T00:00:00+00:00", "kind": "voice.speech.output_stalled",
                                 "level": "warning", "message": "", "data": {"correlation_id": "live:x:y"}}) + "\n",
                     encoding="utf-8")
    report, warnings = await measure_db(db, trace)
    assert report["surfaces"]["live"]["output_stalled"] is None
    assert any("non mesuré" in warning for warning in warnings)


# ---------------------------------------------------------------- CLI, read-only

def test_the_cli_reads_without_touching_the_journal_and_compares_windows(tmp_path, capsys):
    # Synchronous: the CLI runs its own event loop, as it does from a shell.
    db = tmp_path / "state.sqlite3"
    asyncio.run(write_journal(db, [
        turn("live:c:1", 0),
        *speech("before", "live:c:1", queued=10, started=20, end=30030, terminal=T.MOUTH_SPEECH_INTERRUPTED,
                reason="delivery_not_complete"),
        turn("live:c:2", 400_000),
        *speech("after", "live:c:2", queued=400_010, started=400_020, end=402_000,
                completion_basis="local_quiescence", release_after_quiescence_ms=510),
    ]))
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    code = sm.main(["--db", str(db), "--json",
                    "--window", f"avant={BASE.isoformat()}..{(BASE + timedelta(minutes=5)).isoformat()}",
                    "--window", f"apres={(BASE + timedelta(minutes=5)).isoformat()}..{END.isoformat()}"])
    document = json.loads(capsys.readouterr().out)
    assert code == sm.EXIT_OK and hashlib.sha256(db.read_bytes()).hexdigest() == digest
    before, after = document["windows"]
    assert before["window"]["name"] == "avant" and target(before, "live_delivery_not_complete_near_30s")["value"] == 1
    assert target(after, "live_delivery_not_complete_near_30s")["verdict"] == "pass"
    assert target(after, "live_release_after_quiescence_p95_ms")["value"] == 510
    assert sm.main(["--db", str(db), "--from", "2026-09-16", "--to", "2026-09-16"]) == sm.EXIT_OK
    human = capsys.readouterr().out
    assert "## Cibles (Slice 06)" in human and "Libération bouche Live" in human


def test_the_cli_refuses_a_missing_journal_and_an_empty_request(tmp_path, capsys):
    assert sm.main(["--db", str(tmp_path / "absent.sqlite3"), "--baseline"]) == sm.EXIT_INCONCLUSIVE
    assert "state_database_missing" in capsys.readouterr().err
    with pytest.raises(SystemExit) as refused:
        sm.main(["--db", str(tmp_path / "absent.sqlite3")])
    assert refused.value.code == sm.EXIT_USAGE
    with pytest.raises(SystemExit):
        sm.main(["--db", "x", "--window", "bad"])


def test_window_parsing_treats_a_date_end_as_the_end_of_that_day():
    window = sm.parse_window("b=2026-09-18..2026-09-21")
    assert (window.start.isoformat(), window.end.isoformat()) == ("2026-09-18T00:00:00+00:00",
                                                                  "2026-09-22T00:00:00+00:00")
    assert sm.parse_instant("2026-09-28T12:54Z").isoformat() == "2026-09-28T12:54:00+00:00"


# ------------------------------------------------------------------- snapshots

async def _journal_with_unchecked_wal(tmp_path):
    """Main file + a `-wal` holding events the main file lacks (copied while the writer is open)."""
    live = tmp_path / "live" / "state.sqlite3"
    live.parent.mkdir()
    await write_journal(live, [turn("live:c:1", 0)])
    state, store = await open_store(live)
    source = tmp_path / "copy" / "state.sqlite3"
    source.parent.mkdir()
    try:
        await store.append_many([*speech("in-wal", "live:c:1", queued=10, started=20, end=900,
                                         completion_basis="local_quiescence", release_after_quiescence_ms=500)])
        shutil.copyfile(live, source)
        shutil.copyfile(live.with_name("state.sqlite3-wal"), source.with_name("state.sqlite3-wal"))
    finally:
        await state.close()
    return source


async def test_a_file_only_snapshot_warns_about_events_left_in_the_wal(tmp_path):
    source = await _journal_with_unchecked_wal(tmp_path)
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.parent.iterdir()}
    snap = sm.snapshot_journal(source, tmp_path / "snap")
    assert snap.info["measured"] == "file_only"
    assert snap.info["with_wal"]["events"] > snap.info["file_only"]["events"]
    assert any("absents du fichier seul" in warning for warning in snap.warnings)
    report, _ = await measure_db(snap.path)
    assert report["speeches"] == 0  # the file alone does not hold them
    with_wal = sm.snapshot_journal(source, tmp_path / "snap2", with_wal=True)
    report, _ = await measure_db(with_wal.path)
    assert with_wal.info["measured"] == "with_wal" and report["surfaces"]["live"]["completed"] == 1
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.parent.iterdir()}
    assert after == before  # the source files are only ever copied


async def test_a_malformed_wal_view_is_reported_and_never_measured(tmp_path, monkeypatch):
    source = await _journal_with_unchecked_wal(tmp_path)
    real_view = sm._view

    def view(path):
        result = real_view(path)
        return ("*** in database main *** / malformed", *result[1:]) if path.parent.name == "with-wal" else result

    monkeypatch.setattr(sm, "_view", view)
    snap = sm.snapshot_journal(source, tmp_path / "snap")
    assert snap.info["measured"] == "file_only"
    assert any("échoue à l'intégrité" in warning for warning in snap.warnings)
    with pytest.raises(sm.MeasureError, match="wal_view_malformed"):
        sm.snapshot_journal(source, tmp_path / "snap2", with_wal=True)


# ------------------------------------------------------- Live pauses (Slice 06 part B)

async def test_live_pauses_between_sentences_are_reported_with_those_near_the_grace(tmp_path):
    db = tmp_path / "state.sqlite3"
    await write_journal(db, [
        turn("live:c:1", 0),
        *speech("calm", "live:c:1", queued=10, started=20, end=3000, completion_basis="local_quiescence",
                release_after_quiescence_ms=500, live_pause_count=2, live_pause_max_ms=300,
                live_pauses_ms=[200, 300]),
        *speech("risky", "live:c:1", queued=3100, started=3200, end=8000, completion_basis="local_quiescence",
                release_after_quiescence_ms=500, live_pause_count=1, live_pause_max_ms=450, live_pauses_ms=[450]),
        *speech("one-go", "live:c:1", queued=8100, started=8200, end=9000, completion_basis="local_quiescence",
                release_after_quiescence_ms=500, live_pause_count=0, live_pause_max_ms=0, live_pauses_ms=[]),
        *speech("before-part-b", "live:c:1", queued=9100, started=9200, end=9900,
                completion_basis="local_quiescence", release_after_quiescence_ms=500),
    ])
    report, _ = await measure_db(db)
    pauses = report["surfaces"]["live"]["live_pauses"]
    assert (pauses["speeches_measured"], pauses["speeches_with_pause"], pauses["pauses"]) == (3, 2, 3)
    assert pauses["pauses_ms"] == {"count": 3, "p50": 300.0, "p95": 435.0, "max": 450.0}
    assert pauses["max_per_speech_ms"]["max"] == 450.0
    assert pauses["grace_ms"] == 500 and pauses["speeches_with_pause_near_grace"] == 1  # 450 >= 0.8 x 500
    assert "pauses entre phrases: 3 dans 2/3 paroles" in sm.render({"warnings": [], "windows": [report]})

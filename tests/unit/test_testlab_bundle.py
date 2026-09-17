"""DiagnosticBundle schema, codec, pure builder and anomaly rules (docs/testlab.md, "DiagnosticBundle")."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json
import random

import pytest

from jarvis.domain.conversation_event_store import StoredConversationEvent
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.testlab.bundle import (
    MAX_BUNDLE_BYTES,
    DiagnosticBundle,
    SourceStatus,
    bundle_content_fingerprint,
    derive_bundle_id,
)
from jarvis.testlab.bundle_builder import (
    BundleOptions,
    EventEvidence,
    ReportEvidence,
    SessionSelector,
    TraceEvidence,
    VoiceSessionReport,
    build_diagnostic_bundle,
)
from jarvis.testlab.bundle_capture import read_session_trace
from jarvis.testlab.bundle_rules import DEFAULT_RULES, AnomalyRule, check_rules
from jarvis.testlab.identity import id_timestamp
from jarvis.testlab.runs import CodeIdentity
from jarvis.testlab.validation import TestLabError, TestLabRedactionError, canonical_json, format_time
from tests.fakes import testlab_bundle as fx
from tests.fakes.conversation_events import make_event

MARGIN = timedelta(seconds=30)


def _events() -> EventEvidence:
    events = fx.session_events()
    return EventEvidence(SourceStatus.AVAILABLE, origin="export", events=tuple(events), export_complete=True)


def _trace(tmp_path, events: EventEvidence | None = None) -> TraceEvidence:
    path = tmp_path / "trace.jsonl"
    if not path.exists():
        fx.write_trace(path)
    moments = [item.event.occurred_at for item in (events or _events()).events]
    return read_session_trace(path, fx.selector(), start=min(moments) - MARGIN, end=max(moments) + MARGIN).evidence


def build(tmp_path, *, events: EventEvidence | None = None, trace: TraceEvidence | None = None, **kwargs):
    events = _events() if events is None else events
    trace = _trace(tmp_path, events) if trace is None else trace
    kwargs.setdefault("context", fx.context())
    return build_diagnostic_bundle(fx.selector(), events=events, trace=trace, **kwargs)


def by(items, key, value):
    return next(item for item in items if item[key] == value)


# ---------------------------------------------------------------- sections

def test_speech_outcomes_played_ms_and_terminals(tmp_path):
    speech = build(tmp_path).to_dict()["speech"]
    assert [item["speech_id"] for item in speech] == ["s1", "s2", "s3", "s4", "s7", "s5", "s6"]
    outcomes = {item["speech_id"]: item["outcome"] for item in speech}
    assert outcomes == {"s1": "spoken", "s2": "interrupted", "s3": "superseded", "s4": "spoken", "s7": "spoken",
                        "s5": "interrupted", "s6": "queued"}
    assert (by(speech, "speech_id", "s4")["spoken_divergences"], by(speech, "speech_id", "s4")["spoken_diverged_at"]) == (
        1, "2026-09-16T10:00:21.000Z")
    s2 = by(speech, "speech_id", "s2")
    assert s2["played_ms"] == 1800 and s2["reason"] == "user_barge_in" and s2["output_ids"] == ["o2"]
    s3 = by(speech, "speech_id", "s3")
    assert [terminal["outcome"] for terminal in s3["terminals"]] == ["superseded", "spoken"]
    assert s3["reason"] == "dependency_revoked"
    s1 = by(speech, "speech_id", "s1")
    assert s1["queue_wait_ms"] == 38.0 and s1["kind"] == "result" and s1["priority"] == "high"
    assert s1["requested_at"] == "2026-09-16T10:00:01.200Z" and s1["ended_at"] == "2026-09-16T10:00:04.000Z"
    for item in speech:
        assert item["evidence"], item["speech_id"]


def test_turns_playback_barge_in_and_provider_sections(tmp_path):
    document = build(tmp_path).to_dict()
    turns = document["turns"]
    assert {(item["actor"], item["kind"]) for item in turns} >= {
        ("user", "user_turn"), ("brain", "turn_accepted"), ("brain", "turn_failed"), ("mouth", "speech")}
    user = by(turns, "item_id", "user:c1")
    assert user["status"] == "accepted" and user["at"] == "2026-09-16T09:59:59.980Z"  # trace submit before Core
    assert len(user["evidence"]) == 2 and user["turn_id"] == "brain-turn-1"
    assert by(turns, "item_id", "mouth:s2")["status"] == "interrupted"
    playback = by(document["playback"], "output_id", "o1")
    assert (playback["end_status"], playback["drain_ms"], playback["source"]) == ("completed", 180.0, "brain.speech")
    assert by(document["playback"], "output_id", "o2")["end_status"] == "interrupted"
    episodes = document["barge_in"]
    assert [item["outcome"] for item in episodes] == ["confirmed", "confirmed", "rejected"]
    real, self_cut, rejected = episodes
    assert real["authority"] == "acoustic" and len(real["evidence"]) == 2  # pending resolved into the episode
    # the VAD commit at 14.2 s closes an utterance already under way at the barge-in (no onset in between)
    assert (real["jarvis_speaking"], real["audible"], real["next_user_activity_ms"], real["next_user_activity_basis"]) == (
        True, True, 0, "closed_without_onset")
    assert (self_cut["speech_id"], self_cut["audible"], self_cut["next_user_activity_ms"]) == ("s5", True, None)
    assert rejected["codes"] == ["barge_in_not_confirmed"] and rejected["jarvis_speaking"] is False
    assert [item["event"] for item in document["provider"]] == ["connecting", "connected", "models_failed", "error",
                                                                 "disconnected"]
    assert by(document["provider"], "event", "models_failed")["provider"] == "anthropic"
    assert by(document["provider"], "event", "error")["code"] == "input_audio_buffer_commit_empty"


def test_latency_join_stages_measures_and_reported_values(tmp_path):
    join = by(build(tmp_path).to_dict()["latency"], "join_id", "speech:s1")
    assert [stage["stage"] for stage in join["stages"]] == [
        "user_turn_end", "brain_turn_accepted", "speech_requested", "speech_queued", "speech_queue_free",
        "speech_dispatched", "speech_started", "provider_first_pcm", "first_audio", "speech_ended"]
    measures = {item["name"]: item["ms"] for item in join["measures"]}
    assert measures["user_turn_end_to_first_audio_ms"] == 1620
    assert measures["speech_queued_to_started_ms"] == 90 and measures["speech_queue_free_to_started_ms"] == 90
    assert {(item["measure"], item["ms"]) for item in join["reported"]} == {("provider_first_pcm", 199.0),
                                                                            ("output_first_write", 300.0)}
    for stage in join["stages"]:
        assert stage["evidence"]


def test_identity_session_and_coverage(tmp_path):
    document = build(tmp_path).to_dict()
    assert document["identity"] == {"status": "evidence", "voice_configuration_ids": [fx.CONFIGURATION],
                                    "architectures": ["continuous_brain"],
                                    "evidence": document["identity"]["evidence"]}
    session = document["session"]
    assert session["conversation_ids"] == ["conv-lab"] and session["session_ids"] == ["sess-lab"]
    journal = document["coverage"]["runtime_journal"]
    assert journal["status"] == "available" and journal["corrupt_lines"] == 1 and journal["oversized_lines"] == 1
    assert journal["stopped_by"] == "window_end" and journal["truncated"] is False
    assert document["coverage"]["conversation_events"]["export_complete"] is True
    assert document["capture"]["code"] == {"status": "unknown", "git_revision": None, "dirty": None}


# ------------------------------------------------------------------ rules

def test_every_default_rule_fires_once_on_the_fixture_with_resolvable_evidence(tmp_path):
    document = build(tmp_path).to_dict()
    findings = document["anomalies"]["findings"]
    subjects = {(item["rule_id"], item["subject_id"]) for item in findings}
    assert {rule for rule, _ in subjects} == {rule.rule_id for rule in DEFAULT_RULES}
    assert ("voice.self_barge_in", by(document["barge_in"], "speech_id", "s5")["episode_id"]) in subjects
    assert ("speech.delivered_after_supersession", "s3") in subjects
    assert ("speech.duplicate_payload", "s4") in subjects
    assert ("speech.missing_delivery_outcome", "s6") in subjects
    assert ("latency.above_threshold", "speech:s5#user_turn_end_to_first_audio_ms") in subjects
    assert len(findings) == 6  # speech.spoken_diverged is counted on the speech, never a finding
    missing = by(findings, "rule_id", "speech.missing_delivery_outcome")
    assert {item["name"]: item["value"] for item in missing["measured"]} == {
        "state": "queued", "silent_ms": 32990, "cause": "native_failed", "segment_end": "voice.stop"}
    declared = ({item["ref"] for item in document["references"]["conversation_events"]}
                | {item["ref"] for item in document["references"]["trace_lines"]})
    for finding in findings:
        assert finding["evidence"] and set(finding["evidence"]) <= declared
        assert finding["rule_version"] == 1
    rows = document["anomalies"]["rules"]
    assert [row["rule_id"] for row in rows] == [rule.rule_id for rule in DEFAULT_RULES]
    assert all(row["evaluated"] for row in rows)
    assert by(rows, "rule_id", "voice.self_barge_in")["thresholds"] == [{"name": "user_activity_window_ms",
                                                                        "value": 20000}]


def test_thresholds_are_data(tmp_path):
    rules = tuple(replace(rule, thresholds={**rule.thresholds, "user_turn_end_to_first_audio_ms": 10000})
                  if rule.rule_id == "latency.above_threshold" else rule for rule in DEFAULT_RULES)
    document = build(tmp_path, options=BundleOptions(rules=rules)).to_dict()
    assert "latency.above_threshold" not in {item["rule_id"] for item in document["anomalies"]["findings"]}
    row = by(document["anomalies"]["rules"], "rule_id", "latency.above_threshold")
    assert {"name": "user_turn_end_to_first_audio_ms", "value": 10000} in row["thresholds"]


def test_rules_are_listed_unevaluated_without_their_sources(tmp_path):
    document = build(tmp_path, trace=TraceEvidence(SourceStatus.MISSING, reason="trace_file_missing")).to_dict()
    rows = {row["rule_id"]: row for row in document["anomalies"]["rules"]}
    assert rows["voice.self_barge_in"] == {**rows["voice.self_barge_in"], "evaluated": False,
                                           "skipped_reason": "source_unavailable"}
    assert rows["speech.duplicate_payload"]["evaluated"] is True
    empty = build_diagnostic_bundle(fx.selector(), context=fx.context()).to_dict()
    assert not any(row["evaluated"] for row in empty["anomalies"]["rules"])
    assert empty["anomalies"]["findings"] == []
    assert {name: value["status"] for name, value in empty["coverage"].items() if isinstance(value, dict)
            and "status" in value} == {"conversation_events": "not_requested", "runtime_journal": "not_requested",
                                       "voice_session_reports": "not_requested"}
    assert empty["identity"]["status"] == "unknown"
    assert empty["bundle_id"].split("-")[1] == id_timestamp(fx.CAPTURED_AT)


def test_rule_table_validation():
    with pytest.raises(TestLabError):
        check_rules((AnomalyRule("unknown.rule", 1, frozenset({"runtime_journal"})),))
    with pytest.raises(TestLabError):
        check_rules((AnomalyRule("voice.self_barge_in", 1, frozenset({"runtime_journal"})),))  # threshold missing
    with pytest.raises(TestLabError):
        check_rules(DEFAULT_RULES + DEFAULT_RULES[:1])
    with pytest.raises(TestLabError):
        AnomalyRule("voice.x", 1, frozenset({"somewhere"}))
    with pytest.raises(TestLabError):
        AnomalyRule("voice.x", 1, frozenset({"runtime_journal"}), {"window_ms": -1})


# ---------------------------------------------------- determinism, identity

def test_same_inputs_give_byte_identical_bundles_whatever_the_input_order(tmp_path):
    events, trace = _events(), _trace(tmp_path)
    first = build(tmp_path, events=events, trace=trace)
    shuffled_events = list(events.events)
    shuffled_lines = list(trace.lines)
    random.Random(7).shuffle(shuffled_events)
    random.Random(7).shuffle(shuffled_lines)
    second = build(tmp_path, events=replace(events, events=tuple(shuffled_events)),
                   trace=replace(trace, lines=tuple(shuffled_lines)))
    assert first.encode() == second.encode()
    assert first.encode() == canonical_json(json.loads(first.encode())).encode("utf-8")


def test_capture_context_is_outside_the_fingerprint_so_reimport_is_idempotent(tmp_path):
    first = build(tmp_path)
    later = build(tmp_path, context=fx.context(captured_at=fx.CAPTURED_AT + timedelta(days=3),
                                               code=CodeIdentity("0" * 40, True), config_fingerprint="c" * 64))
    assert later.bundle_id == first.bundle_id and later.content_fingerprint == first.content_fingerprint
    assert later.encode() != first.encode()
    assert first.bundle_id.split("-")[1] == id_timestamp(first.started_at)
    assert first.bundle_id.endswith(first.content_fingerprint[:16])


def test_different_evidence_gives_a_different_bundle_id(tmp_path):
    events = _events()
    fewer = replace(events, events=events.events[:-1])
    assert build(tmp_path, events=fewer).bundle_id != build(tmp_path, events=events).bundle_id


# ------------------------------------------------------------------ codec

def test_codec_round_trip(tmp_path):
    bundle = build(tmp_path)
    decoded = DiagnosticBundle.decode(bundle.encode())
    assert decoded == bundle and decoded.encode() == bundle.encode()
    assert DiagnosticBundle.from_dict(bundle.to_dict()).bundle_id == bundle.bundle_id


def _resealed(document: dict) -> dict:
    document["content_fingerprint"] = bundle_content_fingerprint(document)
    document["bundle_id"] = derive_bundle_id(document, document["content_fingerprint"])
    return document


@pytest.mark.parametrize("mutate, code", [
    (lambda d: d.update(extra=1), "testlab_fields_mismatch"),
    (lambda d: d["speech"][0].pop("played_ms"), "testlab_fields_mismatch"),
    (lambda d: d.update(schema_version=2), "testlab_schema_unsupported"),
    (lambda d: d["speech"][0].update(outcome="maybe"), "testlab_field_invalid"),
    (lambda d: d["turns"][0].update(content="edited after capture"), "testlab_reference_invalid"),
    (lambda d: d.update(bundle_id="tlb-20260916T095955000Z-0000000000000000"), "testlab_reference_invalid"),
])
def test_codec_rejects_unknown_missing_invalid_or_tampered_content(tmp_path, mutate, code):
    document = build(tmp_path).to_dict()
    mutate(document)
    with pytest.raises(TestLabError) as caught:
        DiagnosticBundle.from_dict(document)
    assert caught.value.code == code


def test_codec_requires_resolvable_provenance(tmp_path):
    document = build(tmp_path).to_dict()
    document["speech"][0]["evidence"] = ["trace:999999999"]
    with pytest.raises(TestLabError) as caught:
        DiagnosticBundle.from_dict(_resealed(document))
    assert caught.value.code == "testlab_reference_invalid"
    document = build(tmp_path).to_dict()
    document["provider"][0]["evidence"] = []
    with pytest.raises(TestLabError) as caught:
        DiagnosticBundle.from_dict(_resealed(document))
    assert caught.value.code == "testlab_reference_invalid"


def test_codec_refuses_private_names_duplicate_keys_and_oversize(tmp_path):
    document = build(tmp_path).to_dict()
    document["speech"][0]["hidden_reasoning"] = "x"
    with pytest.raises(TestLabRedactionError):
        DiagnosticBundle.from_dict(document)
    text = build(tmp_path).encode().decode("utf-8")
    with pytest.raises(TestLabError) as caught:
        DiagnosticBundle.decode(text[:-1] + ',"schema":"jarvis.testlab.bundle"}')
    assert caught.value.code == "testlab_json_invalid"
    with pytest.raises(TestLabError) as caught:
        DiagnosticBundle.decode(b"x" * (MAX_BUNDLE_BYTES + 1))
    assert caught.value.code == "testlab_limit_exceeded"


# ---------------------------------------------------------------- privacy

def test_no_raw_payload_hidden_content_or_identifying_text_is_copied(tmp_path):
    encoded = build(tmp_path).encode().decode("utf-8")
    for marker in fx.SECRET_MARKERS:
        assert marker not in encoded, marker
    user = by(build(tmp_path).to_dict()["turns"], "item_id", "user:c1")
    assert "<email>" in user["content"] and "https://meteo.fr/x" in user["content"]
    assert "Voici une histoire courte" not in encoded  # diagnostic (never played) speech text


def test_public_content_is_opt_out_and_bounded(tmp_path):
    none = build(tmp_path, options=BundleOptions(include_public_content=False)).to_dict()
    assert all(turn["content"] is None for turn in none["turns"])
    assert none["coverage"]["content"] == {"included": False, "max_chars": 512, "items": 0, "truncated_items": 0,
                                           "redactions": 0}
    short = build(tmp_path, options=BundleOptions(max_content_chars=10)).to_dict()
    assert all(turn["content"] is None or len(turn["content"]) <= 10 for turn in short["turns"])
    assert short["coverage"]["content"]["truncated_items"] > 0
    assert any(turn["content_truncated"] for turn in short["turns"])
    with pytest.raises(TestLabError):
        BundleOptions(max_content_chars=0)


# ---------------------------------------------------------- other shapes

def test_section_caps_are_recorded(tmp_path, monkeypatch):
    from jarvis.testlab import bundle_builder

    monkeypatch.setattr(bundle_builder, "SECTION_LIMITS", {**bundle_builder.SECTION_LIMITS, "speech": 2})
    document = build(tmp_path).to_dict()
    assert len(document["speech"]) == 2
    assert {"section": "speech", "kept": 2, "dropped": 5} in document["coverage"]["limits"]


def test_voice_session_reports_and_trace_summary_aggregates(tmp_path):
    report = VoiceSessionReport(sha256="d" * 64, session_id=fx.SESSION, architecture="continuous_brain",
                                configuration_id=fx.CONFIGURATION, terminal_status="stopped",
                                trace_evidence_complete=True, latency=(("speech_queue_wait_ms", 3, 1.0, 9.0, 4.5),),
                                counts=(("user_interruption", 2),))
    document = build(tmp_path, reports=ReportEvidence(SourceStatus.AVAILABLE, reports=(report,)),
                     trace_summary={"barge_in": {"owner_cuts": 1, "stop_ms": {"p50": 2.5}},
                                    "events": {"voice.speech.started": 4}, "window": {"first": None}}).to_dict()
    aggregate = document["aggregates"]["voice_session_reports"][0]
    assert aggregate["evidence"] == ["report:" + "d" * 16]
    assert aggregate["latency"] == [{"name": "speech_queue_wait_ms", "count": 3, "min_ms": 1.0, "max_ms": 9.0,
                                     "mean_ms": 4.5}]
    assert document["references"]["voice_session_reports"] == [{"ref": "report:" + "d" * 16, "sha256": "d" * 64}]
    assert "report:" + "d" * 16 in document["identity"]["evidence"]
    assert document["aggregates"]["trace_summary"] == [
        {"path": "barge_in.owner_cuts", "value": 1}, {"path": "barge_in.stop_ms.p50", "value": 2.5},
        {"path": "events.voice.speech.started", "value": 4}, {"path": "window.first", "value": None}]


def test_chunked_request_links_its_chunks(tmp_path):
    request = make_event(T.BRAIN_SPEECH_REQUESTED, "long", conversation_id=fx.CONVERSATION, ms=0,
                         producer="core.brain_service", correlation_id="cl", speech_id="long", content="A.\n\nB.")
    chunk = make_event(T.MOUTH_SPEECH_STARTED, "chunk-1", conversation_id=fx.CONVERSATION, ms=100,
                       producer="voice.speech_scheduler", correlation_id="cl", speech_id="long-1",
                       parent_event_id=request.event_id, content="A.")
    events = EventEvidence(SourceStatus.AVAILABLE, origin="store", events=tuple(
        StoredConversationEvent(index + 1, event.occurred_at, event) for index, event in enumerate((request, chunk))))
    document = build_diagnostic_bundle(fx.selector(), context=fx.context(), events=events).to_dict()
    parent, child = by(document["speech"], "speech_id", "long"), by(document["speech"], "speech_id", "long-1")
    assert parent["outcome"] == "chunked" and parent["chunk_speech_ids"] == ["long-1"]
    assert child["parent_speech_id"] == "long" and child["outcome"] == "started"
    join = by(document["latency"], "join_id", "speech:long-1")
    assert [stage["stage"] for stage in join["stages"]] == ["speech_requested", "speech_started"]


def test_request_without_voice_evidence_is_unknown_not_dropped():
    request = make_event(T.BRAIN_SPEECH_REQUESTED, "lonely", conversation_id=fx.CONVERSATION, ms=0,
                         producer="core.brain_service", correlation_id="cx", speech_id="lonely", content="Bonjour.")
    events = EventEvidence(SourceStatus.AVAILABLE, origin="store",
                           events=(StoredConversationEvent(1, request.occurred_at, request),))
    unknown = build_diagnostic_bundle(fx.selector(), context=fx.context(), events=events).to_dict()
    assert unknown["speech"][0]["outcome"] == "unknown"
    dropped = build_diagnostic_bundle(fx.selector(), context=fx.context(), events=events,
                                      trace=TraceEvidence(SourceStatus.EMPTY)).to_dict()
    assert dropped["speech"][0]["outcome"] == "dropped"


@pytest.mark.parametrize("kwargs", [
    {}, {"start": fx.CAPTURED_AT}, {"conversation_id": ""},
    {"conversation_id": "c", "start": fx.CAPTURED_AT, "end": fx.CAPTURED_AT},
])
def test_selector_validation(kwargs):
    with pytest.raises(TestLabError):
        SessionSelector(**kwargs)


# ---------------------------------------------------------- rework: latency (R4)

def test_serial_playback_is_not_queue_latency_and_turn_first_audio_is_measured_once(tmp_path):
    document = build(tmp_path).to_dict()
    s7 = by(document["latency"], "join_id", "speech:s7")
    measures = {item["name"]: item["ms"] for item in s7["measures"]}
    # queued at 20.02 s while s4 played until 22.0 s (its first terminal), started at 24.05 s
    assert measures["speech_queued_to_started_ms"] == 4030 and measures["speech_queue_free_to_started_ms"] == 2050
    free = by(s7["stages"], "stage", "speech_queue_free")
    assert free["at"] == "2026-09-16T10:00:22.000Z" and free["evidence"]
    # s4 produced the first audio of turn c4: s7 (first audio 28 s) does not repeat the turn measure
    assert "user_turn_end_to_first_audio_ms" not in measures
    assert "user_turn_end_to_first_audio_ms" in {item["name"] for item in by(document["latency"], "join_id",
                                                                               "speech:s4")["measures"]}
    subjects = {item["subject_id"] for item in document["anomalies"]["findings"]}
    assert not any(subject.startswith("speech:s7#") for subject in subjects)


# ------------------------------------------------- rework: evidence mapping (R5)

def test_user_activity_lifecycle_brain_and_usage_sections(tmp_path):
    document = build(tmp_path).to_dict()
    assert [(item["event"], item["at"]) for item in document["user_activity"]] == [
        ("turn_submitted", "2026-09-16T09:59:59.980Z"), ("input_submitted", "2026-09-16T10:00:09.500Z"),
        ("turn_submitted", "2026-09-16T10:00:09.990Z"), ("input_submitted", "2026-09-16T10:00:14.200Z"),
        ("turn_submitted", "2026-09-16T10:00:14.500Z"), ("turn_submitted", "2026-09-16T10:00:20.990Z"),
        ("transcript_dropped", "2026-09-16T10:00:31.500Z")]
    assert by(document["user_activity"], "event", "transcript_dropped")["near_playback"] is True
    assert [item["event"] for item in document["lifecycle"]] == ["started", "native_failed", "stopped"]
    assert by(document["lifecycle"], "event", "native_failed")["code"] == "audio_native_failed"
    superseded = by(document["brain"], "event", "replies_superseded")
    assert superseded["work_ids"] == ["w2", "w3"] and superseded["correlation_id"] == "c3"
    budget = by(document["brain"], "event", "turn_over_budget")
    assert (budget["ms"], budget["budget_ms"]) == (9200, 8000)
    assert [(item["input_tokens"], item["output_tokens"]) for item in document["usage"]] == [(136, 115)]
    journal = document["coverage"]["runtime_journal"]
    kinds = {item["kind"] for item in document["references"]["trace_lines"]}
    assert "voice.state.updated" not in kinds  # unmapped kinds are not selected
    assert journal["lines_selected"] < journal["lines_in_window"]


# ------------------------------------------------- rework: segments (R1, R7)

def _line(ms, kind, **data):
    from jarvis.testlab.bundle_builder import TraceLine

    return TraceLine(offset=ms * 10 + 1_000_000, ts=fx.at(ms), kind=kind, level="info", data=data)


def _journal(*lines):
    return TraceEvidence(SourceStatus.AVAILABLE, lines=tuple(lines), lines_in_window=len(lines),
                         stopped_by="window_end")


def test_segments_split_on_session_end_session_change_start_and_idle_gap():
    conv = {"conversation_id": fx.CONVERSATION}
    lines = (
        _line(0, "voice.start"), _line(100, "voice.connecting"), _line(200, "voice.active", **conv, session_id="a"),
        _line(1000, "voice.speech.queued", **conv, speech_id="q1"),
        _line(2000, "voice.stop"),
        _line(3000, "voice.active", **conv, session_id="b"),
        _line(4000, "voice.speech.started", **conv, session_id="c", speech_id="x"),
        _line(5000, "voice.start"),
        _line(5000 + 11 * 60 * 1000, "voice.speech.queued", **conv, speech_id="late"),
    )
    document = build_diagnostic_bundle(fx.selector(), context=fx.context(), trace=_journal(*lines)).to_dict()
    segments = document["coverage"]["segments"]
    assert segments["count"] == 5 and segments["idle_gap_ms"] == 600000
    assert [(item["session_id"], item["end_kind"], item["items"]) for item in segments["items"]] == [
        ("a", "voice.stop", 5), ("b", None, 1), ("c", None, 1), (None, None, 1), (None, None, 1)]
    assert document["coverage"]["warnings"] == ["multi_session_selection"]
    missing = {item["subject_id"]: {m["name"]: m["value"] for m in item["measured"]}
               for item in document["anomalies"]["findings"] if item["rule_id"] == "speech.missing_delivery_outcome"}
    # q1: its segment was closed by voice.stop one second later; silent_ms stops at the segment end
    assert missing["q1"] == {"state": "queued", "silent_ms": 1000, "cause": "stopped", "segment_end": "voice.stop"}
    assert "late" not in missing  # alone in its segment: no grace elapsed, no session end


def test_a_line_days_later_does_not_decide_an_undecidable_barge_in():
    conv = {"conversation_id": fx.CONVERSATION, "session_id": "s1"}
    session = (
        _line(0, "voice.active", **conv),
        _line(1500, "voice.speech.started", **conv, speech_id="sp1", output_id="o1"),
        _line(2700, "voice.barge_in", **conv, speech_id="sp1", output_id="o1", played_ms=400, stop_latency_ms=20),
        _line(3300, "voice.speech.completed", **conv, speech_id="sp2", output_id="o2"),
    )
    later = session + (_line(2 * 86_400_000, "voice.speech.queued", conversation_id=fx.CONVERSATION,
                             speech_id="late"),)
    for lines in (session, later):
        document = build_diagnostic_bundle(fx.selector(), context=fx.context(), trace=_journal(*lines)).to_dict()
        assert "voice.self_barge_in" not in {item["rule_id"] for item in document["anomalies"]["findings"]}
    assert document["coverage"]["segments"]["count"] == 2
    assert set(document["coverage"]["warnings"]) == {"multi_session_selection", "long_selection"}
    # the late line is alone in its own segment: no grace elapsed there, so no absurd silent_ms either
    assert "speech.missing_delivery_outcome" not in {item["rule_id"] for item in document["anomalies"]["findings"]}


def test_open_window_is_marked(tmp_path):
    closed = build(tmp_path).to_dict()
    assert closed["coverage"]["runtime_journal"]["window_open"] is False and closed["coverage"]["warnings"] == []
    open_trace = replace(_trace(tmp_path), window_open=True)
    document = build(tmp_path, trace=open_trace).to_dict()
    assert document["coverage"]["runtime_journal"]["window_open"] is True
    assert "open_window" in document["coverage"]["warnings"]
    future = SessionSelector(conversation_id=fx.CONVERSATION, start=fx.at(0), end=fx.CAPTURED_AT + timedelta(hours=1))
    assert build_diagnostic_bundle(future, context=fx.context()).to_dict()["coverage"]["warnings"] == ["open_window"]


# ------------------------------------------------- rework: codec consistency (R2)

def _rows(document, rule_id):
    return by(document["anomalies"]["rules"], "rule_id", rule_id)


def _tamper_version(d):
    d["anomalies"]["findings"][0]["rule_version"] = 7


def _tamper_unknown_rule(d):
    d["anomalies"]["findings"][0]["rule_id"] = "made.up_rule"


def _tamper_duplicate_row(d):
    d["anomalies"]["rules"].append(dict(d["anomalies"]["rules"][0]))


def _tamper_unevaluated_row(d):
    row = _rows(d, "latency.above_threshold")
    row["evaluated"], row["skipped_reason"] = False, "source_unavailable"


def _tamper_threshold(d):
    row = _rows(d, "latency.above_threshold")
    next(item for item in row["thresholds"] if item["name"] == "user_turn_end_to_first_audio_ms")["value"] = 999999


def _tamper_skipped_reason(d):
    d["anomalies"]["rules"][0]["skipped_reason"] = "source_unavailable"


def _tamper_spoken_without_terminal(d):
    d["speech"][0]["terminals"] = []


def _tamper_source_status(d):
    d["coverage"]["runtime_journal"]["status"] = "not_requested"


def _tamper_unavailable_events(d):
    d["coverage"]["conversation_events"]["status"] = "unavailable"


@pytest.mark.parametrize("tamper", [_tamper_version, _tamper_unknown_rule, _tamper_duplicate_row,
                                    _tamper_unevaluated_row, _tamper_threshold, _tamper_skipped_reason,
                                    _tamper_spoken_without_terminal, _tamper_source_status,
                                    _tamper_unavailable_events])
def test_codec_refuses_resealed_inconsistent_documents(tmp_path, tamper):
    document = build(tmp_path).to_dict()
    tamper(document)
    with pytest.raises(TestLabError) as caught:
        DiagnosticBundle.from_dict(_resealed(document))
    assert caught.value.code == "testlab_reference_invalid"


# ------------------------------------------ second rework: rule plausibility (Q1-Q5)

def _session(*lines, end_ms=60_000, selector=None):
    lines = (_line(-20_000, "voice.active", conversation_id=fx.CONVERSATION, session_id="S"), *lines,
             _line(end_ms, "voice.stop"))
    return build_diagnostic_bundle(selector or fx.selector(), context=fx.context(), trace=_journal(*lines))


def _rule_ids(bundle):
    return [item["rule_id"] for item in bundle.to_dict()["anomalies"]["findings"]]


def _unaudible_barge_in_during_user_turn():
    """Real shape 2026-09-14 14:55:06: output superseded before any audible write, user mid-turn."""
    c = {"conversation_id": fx.CONVERSATION, "session_id": "S"}
    return (
        _line(-6807, "voice.speech_started", conversation_id=fx.CONVERSATION),
        _line(-5066, "voice.input_submitted", conversation_id=fx.CONVERSATION),
        _line(-4704, "voice.transcript", conversation_id=fx.CONVERSATION, addressing="uncertain"),
        _line(-4664, "voice.brain_turn_submitted", **c, correlation_id="c9"),
        _line(-1189, "voice.speech.queued", **c, speech_id="sp", correlation_id="c9"),
        _line(-1188, "voice.speech.queued", **c, speech_id="sp-next", correlation_id="c9"),
        _line(-1186, "voice.speech.dispatched", **c, speech_id="sp", output_id="o-real"),
        _line(-1169, "voice.speech.started", **c, speech_id="sp", output_id="o-real"),
        _line(-1033, "voice.output_started", conversation_id=fx.CONVERSATION, speech_id="sp", output_id="o-real"),
        _line(-20, "voice.latency.provider_first_pcm", **c, speech_id="sp", output_id="o-real", elapsed_ms=6786.7),
        _line(-18, "voice.latency.playback_attempted", **c, speech_id="sp", output_id="o-real", elapsed_ms=6788.7),
        _line(-7, "audio.output_stopped"),
        _line(-5, "voice.speech.superseded", **c, speech_id="sp-next", reason="interrupted_chain"),
        _line(0, "voice.barge_in", **c, speech_id="sp", output_id="sp", played_ms=0, stop_latency_ms=4.8),
        _line(223, "voice.barge_in_degraded", conversation_id=fx.CONVERSATION, code="response_cancel_not_active"),
        _line(245, "voice.speech.interrupted", **c, speech_id="sp", output_id="o-real", played_ms=0),
        _line(2335, "voice.transcript", conversation_id=fx.CONVERSATION, addressing="addressed"),
        _line(2375, "voice.brain_turn_submitted", **c, correlation_id="c10"),
    )


def test_real_shape_unaudible_barge_in_while_the_user_is_mid_turn_is_not_a_self_barge_in():
    bundle = _session(*_unaudible_barge_in_during_user_turn())
    episode = by(bundle.to_dict()["barge_in"], "outcome", "confirmed")
    assert (episode["played_ms"], episode["audible"], episode["jarvis_speaking"]) == (0, False, True)
    assert (episode["next_user_activity_ms"], episode["next_user_activity_basis"]) == (0, "closed_without_onset")
    assert "voice.self_barge_in" not in _rule_ids(bundle)
    # unaudible alone is enough: with no later user activity it is still not a finding
    quiet = _session(*[line for line in _unaudible_barge_in_during_user_turn() if line.ts <= fx.at(245)])
    assert "voice.self_barge_in" not in _rule_ids(quiet)


def _audible_barge_in_then_long_utterance(commit_ms: int):
    """Real shape 2026-09-14 14:41:33: audible output cut, the VAD commit arrives 19 s later, no onset traced."""
    c = {"conversation_id": fx.CONVERSATION, "session_id": "S"}
    return (
        _line(-15000, "voice.speech.started", **c, speech_id="sp", output_id="o1"),
        _line(-7391, "voice.latency.first_audible_write", **c, speech_id="sp", output_id="o1", elapsed_ms=14899.2),
        _line(0, "voice.barge_in_pending", conversation_id=fx.CONVERSATION, authority="acoustic"),
        _line(207, "audio.output_stopped"),
        _line(209, "voice.barge_in", **c, speech_id="sp", output_id="sp", played_ms=7818, stop_latency_ms=25.0),
        _line(215, "voice.speech.interrupted", **c, speech_id="sp", output_id="o1", played_ms=7818),
        _line(commit_ms, "voice.input_submitted", conversation_id=fx.CONVERSATION),
        _line(commit_ms + 1030, "voice.transcript", conversation_id=fx.CONVERSATION, addressing="uncertain"),
        _line(commit_ms + 1068, "voice.brain_turn_submitted", **c, correlation_id="c11"),
    )


def test_real_shape_long_utterance_after_an_audible_barge_in_is_user_activity_whatever_the_window():
    narrow = tuple(replace(rule, thresholds={"user_activity_window_ms": 5000}) if rule.rule_id == "voice.self_barge_in"
                   else rule for rule in DEFAULT_RULES)
    lines = _audible_barge_in_then_long_utterance(19049)
    for options in (BundleOptions(), BundleOptions(rules=narrow)):
        bundle = build_diagnostic_bundle(fx.selector(), context=fx.context(), options=options, trace=_journal(
            _line(-20_000, "voice.active", conversation_id=fx.CONVERSATION, session_id="S"), *lines,
            _line(60_000, "voice.stop")))
        episode = by(bundle.to_dict()["barge_in"], "outcome", "confirmed")
        assert (episode["audible"], episode["next_user_activity_ms"], episode["next_user_activity_basis"]) == (
            True, 0, "closed_without_onset")
        assert "voice.self_barge_in" not in _rule_ids(bundle)
    # a commit more than a minute later is not the same utterance: the audible cut is a self barge-in
    late = _session(*_audible_barge_in_then_long_utterance(70_000), end_ms=120_000)
    assert "voice.self_barge_in" in _rule_ids(late)


def test_a_user_holding_the_floor_is_not_queue_latency():
    """Real shapes 2026-09-14 14:45:00 and 2026-09-16 08:23:18: queued while the user spoke, dispatched at the commit."""
    c = {"conversation_id": fx.CONVERSATION, "session_id": "S"}
    bundle = _session(
        _line(-2627, "voice.speech_started", conversation_id=fx.CONVERSATION),
        _line(1, "voice.speech.queued", **c, speech_id="q", correlation_id="c1"),
        _line(5700, "voice.input_submitted", conversation_id=fx.CONVERSATION),
        _line(5751, "voice.speech.dispatched", **c, speech_id="q", output_id="oq"),
        _line(5753, "voice.speech.started", **c, speech_id="q", output_id="oq"),
        _line(6000, "voice.speech.completed", **c, speech_id="q", output_id="oq"),
    )
    join = by(bundle.to_dict()["latency"], "join_id", "speech:q")
    measures = {item["name"]: item["ms"] for item in join["measures"]}
    assert measures["speech_queued_to_started_ms"] == 5752 and measures["speech_queue_free_to_started_ms"] == 53
    assert by(join["stages"], "stage", "speech_queue_free")["at"] == format_time(fx.at(5700))
    assert "latency.above_threshold" not in _rule_ids(bundle)
    # the same wait with no user speaking is queue latency
    idle = _session(_line(1, "voice.speech.queued", **c, speech_id="q", correlation_id="c1"),
                    _line(5753, "voice.speech.started", **c, speech_id="q", output_id="oq"),
                    _line(6000, "voice.speech.completed", **c, speech_id="q", output_id="oq"))
    assert "latency.above_threshold" in _rule_ids(idle)


@pytest.mark.parametrize("stop_ms, stop_session", [(601_000, "S"), (603_000, "S"), (603_000, None)])
def test_a_long_silent_identified_session_keeps_its_hung_speech_decidable(stop_ms, stop_session):
    c = {"conversation_id": fx.CONVERSATION, "session_id": "S"}
    stop = {"session_id": stop_session} if stop_session else {}
    lines = (_line(0, "voice.connecting", **c), _line(1000, "voice.speech.queued", **c, speech_id="hung"),
             _line(stop_ms, "voice.stop", **stop))
    document = build_diagnostic_bundle(fx.selector(), context=fx.context(), trace=_journal(*lines)).to_dict()
    assert document["coverage"]["segments"]["count"] == 1
    finding = by(document["anomalies"]["findings"], "rule_id", "speech.missing_delivery_outcome")
    assert {item["name"]: item["value"] for item in finding["measured"]} == {
        "state": "queued", "silent_ms": stop_ms - 1000, "cause": "stopped", "segment_end": "voice.stop"}


def test_an_unidentified_line_after_the_idle_gap_still_splits():
    c = {"conversation_id": fx.CONVERSATION, "session_id": "S"}
    lines = (_line(0, "voice.connecting", **c), _line(1000, "voice.speech.queued", **c, speech_id="hung"),
             _line(603_000, "voice.speech.queued", conversation_id=fx.CONVERSATION, speech_id="later"))
    document = build_diagnostic_bundle(fx.selector(), context=fx.context(), trace=_journal(*lines)).to_dict()
    assert document["coverage"]["segments"]["count"] == 2


def test_spoken_divergence_is_counted_never_a_finding(tmp_path):
    document = build(tmp_path).to_dict()
    assert by(document["speech"], "speech_id", "s4")["spoken_divergences"] == 1
    assert "speech.spoken_diverged" not in {row["rule_id"] for row in document["anomalies"]["rules"]}
    assert "speech.spoken_diverged" not in {item["rule_id"] for item in document["anomalies"]["findings"]}


def _multi_segment_document():
    conv = {"conversation_id": fx.CONVERSATION}
    lines = (_line(0, "voice.active", **conv, session_id="a"), _line(1000, "voice.speech.queued", **conv, speech_id="q1"),
             _line(2000, "voice.stop"), _line(3000, "voice.active", **conv, session_id="b"),
             _line(4000, "voice.speech.started", **conv, session_id="c", speech_id="x"))
    return build_diagnostic_bundle(fx.selector(), context=fx.context(), trace=_journal(*lines)).to_dict()


def _segments(d):
    return d["coverage"]["segments"]["items"]


SEGMENT_TAMPERS = {
    "segments out of order": lambda d: _segments(d).reverse(),
    "overlapping segments": lambda d: _segments(d)[1].__setitem__("started_at", _segments(d)[0]["started_at"]),
    "segment ends before it starts": lambda d: _segments(d)[0].__setitem__("ended_at", "2026-09-01T00:00:00.000Z"),
    "segment index gap": lambda d: _segments(d)[2].__setitem__("index", 99),
    "segment without items": lambda d: _segments(d)[2].__setitem__("items", 0),
    "multi-session warning removed": lambda d: d["coverage"].__setitem__("warnings", []),
    "open_window warning without window_open": lambda d: d["coverage"].__setitem__(
        "warnings", sorted(d["coverage"]["warnings"] + ["open_window"])),
    "finding segment_end differs from its segment": lambda d: [
        item.__setitem__("value", "voice.failure") for finding in d["anomalies"]["findings"]
        if finding["rule_id"] == "speech.missing_delivery_outcome" for item in finding["measured"]
        if item["name"] == "segment_end"],
}


@pytest.mark.parametrize("name", sorted(SEGMENT_TAMPERS))
def test_codec_refuses_inconsistent_segments_and_warnings(name):
    document = _multi_segment_document()
    SEGMENT_TAMPERS[name](document)
    with pytest.raises(TestLabError) as caught:
        DiagnosticBundle.from_dict(_resealed(document))
    assert caught.value.code == "testlab_reference_invalid"


FIXTURE_TAMPERS = {
    "missing outcome finding on a spoken speech": lambda d: [
        finding.__setitem__("subject_id", "s1") for finding in d["anomalies"]["findings"]
        if finding["rule_id"] == "speech.missing_delivery_outcome"],
    "self barge-in finding on an unknown episode": lambda d: [
        finding.__setitem__("subject_id", "barge:0") for finding in d["anomalies"]["findings"]
        if finding["rule_id"] == "voice.self_barge_in"],
    "self barge-in episode with activity inside the window": lambda d: [
        episode.__setitem__("next_user_activity_ms", 0) for episode in d["barge_in"] if episode["speech_id"] == "s5"],
    "lifecycle unsorted": lambda d: d["lifecycle"].reverse(),
    "findings unsorted": lambda d: d["anomalies"]["findings"].reverse(),
    "latency ms not the stage difference": lambda d: d["latency"][0]["measures"][0].__setitem__(
        "ms", d["latency"][0]["measures"][0]["ms"] + 1),
    "latency stages out of order": lambda d: d["latency"][0]["stages"].reverse(),
    "latency finding ms differs from the join": lambda d: [
        item.__setitem__("value", 1) for finding in d["anomalies"]["findings"]
        if finding["rule_id"] == "latency.above_threshold" for item in finding["measured"] if item["name"] == "ms"],
}


@pytest.mark.parametrize("name", sorted(FIXTURE_TAMPERS))
def test_codec_refuses_findings_whose_subject_or_order_disagrees(tmp_path, name):
    document = build(tmp_path).to_dict()
    FIXTURE_TAMPERS[name](document)
    with pytest.raises(TestLabError) as caught:
        DiagnosticBundle.from_dict(_resealed(document))
    assert caught.value.code == "testlab_reference_invalid"

"""Progression de la parole pour le Tool Brain (Slice 4) : projection en lecture seule, interruption, budget.

Deux niveaux : snapshots fabriqués (cas limites, déterministes) et un vrai `SpeechScheduler` piloté par les
doubles de `test_v2_speech_scheduler` (la projection lit bien ce que le planificateur publie).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.domain.speech_presentation import presentation_chunk_ids, semantic_text_spans
from jarvis.domain.v2 import SpeechKind, SpeechRequest
from jarvis.domain.voice_events import VoiceGenerationStatus, VoicePlaybackStatus
from jarvis.domain.voice_frontend import VoiceCorrelation
from jarvis.domain.voice_state import VoiceSpeechRecord, VoiceSpeechState
from jarvis.runtime.tool_brain_perception import MAX_PERCEPTION_BYTES, SpeechSection, build_perception
from jarvis.runtime.tool_brain_choices import UiState
from jarvis.runtime.tool_brain_speech import (
    BASIS_CHUNK_END, BASIS_CHUNK_START, BASIS_PROPORTIONAL, MAX_SPEECH_SECTION_BYTES, SPEECH_SCHEMA, ChunkEvidence,
    SpeechProgressTracker, evidence_from_voice_records,
)
from tests.fakes.speech_context import source
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION, FakeCore, FakeVoiceSession, build_scheduler, finish_speech, wait_for,
)

TEXT = "Premier paragraphe.\n\nSecond paragraphe plus long.\n\nTroisieme."
REQUEST_ID = "req-1"


def snapshot_for(statuses, *, text=TEXT, request_id=REQUEST_ID, floor=None, correlation="corr-1"):
    """Snapshot au format de `SpeechScheduler.presentation_snapshot()`, un statut par morceau."""

    spans = semantic_text_spans(text)
    ids = presentation_chunk_ids(request_id, spans)
    return {"source_complete": True, "current_source": None, "floor": floor, "candidates": [
        {"speech_id": ids[i], "correlation_id": correlation, "status": status, "reason": "x",
         "chunk": {"chain_id": request_id, "index": i, "count": len(spans), "span": span.to_payload()}}
        for i, (span, status) in enumerate(zip(spans, statuses))]}, ids, spans


def only_chain(progress):
    chains = progress.data["chains"]
    assert len(chains) == 1
    return chains[0]


def test_current_and_upcoming_chunks_are_bounded_and_point_to_canonical_ids():
    snap, ids, spans = snapshot_for(["completed", "started", "deferred"])
    chain = only_chain(SpeechProgressTracker().observe(snap, {ids[1]: ChunkEvidence(1000, 4000)}))
    assert chain["state"] == "playing" and chain["heard"] == 1 and chain["pending"] == 1
    playing, upcoming = chain["chunks"]
    assert (playing["id"], playing["ph"], playing["played_ms"]) == (ids[1], "playing", 1000)
    assert (upcoming["id"], upcoming["ph"]) == (ids[2], "pending")
    assert chain["corr"] == "corr-1" and chain["chain"] == REQUEST_ID
    # curseur : 25 % du morceau joue, proportionnel, jamais au-dela de son span
    expected = spans[1].start + int((spans[1].end - spans[1].start) * 0.25)
    assert (chain["cursor"], chain["basis"]) == (expected, BASIS_PROPORTIONAL)
    assert spans[1].start <= chain["cursor"] <= spans[1].end


def test_cursor_is_chunk_start_while_total_duration_is_unknown_then_chunk_end_when_heard():
    snap, ids, spans = snapshot_for(["started", "deferred", "deferred"])
    progress = SpeechProgressTracker().observe(snap, {ids[0]: ChunkEvidence(500, None)})
    chain = only_chain(progress)
    assert (chain["cursor"], chain["basis"]) == (spans[0].start, BASIS_CHUNK_START)
    done, *_ = snapshot_for(["completed", "completed", "completed"])
    chain = only_chain(SpeechProgressTracker().observe(done))
    assert (chain["state"], chain["cursor"], chain["basis"]) == ("done", spans[2].end, BASIS_CHUNK_END)


def test_cursor_is_monotonic_across_observations_and_never_reads_texts_it_was_not_given():
    tracker = SpeechProgressTracker()
    cursors = []
    for played in (0, 800, 2000, 1500):  # une preuve qui recule ne fait pas reculer le curseur
        snap, ids, _ = snapshot_for(["started", "deferred", "deferred"])
        cursors.append(only_chain(tracker.observe(snap, {ids[0]: ChunkEvidence(played, 4000)}))["cursor"])
    assert cursors == sorted(cursors) and cursors[-1] == cursors[2]
    snap, ids, _ = snapshot_for(["completed", "started", "deferred"])
    assert only_chain(tracker.observe(snap, {ids[1]: ChunkEvidence(1, 9000)}))["cursor"] >= cursors[-1]


def test_a_chain_back_to_pending_after_progress_is_an_explicit_restart():
    tracker = SpeechProgressTracker()
    snap, ids, spans = snapshot_for(["completed", "started", "deferred"])
    tracker.observe(snap, {ids[1]: ChunkEvidence(2000, 4000)})
    again, *_ = snapshot_for(["deferred", "deferred", "deferred"])
    chain = only_chain(tracker.observe(again))
    assert chain["restarts"] == 1 and chain["cursor"] == 0  # redemarrage dit, curseur reparti de zero
    assert chain["state"] == "queued"


def test_interruption_makes_the_unplayed_tail_obsolete_and_keeps_the_cut_chunk_visible():
    snap, ids, _ = snapshot_for(["completed", "interrupted", "deferred"], floor={"while": "speaking", "decision": None})
    progress = SpeechProgressTracker().observe(snap, {ids[1]: ChunkEvidence(1200, 3000)})
    chain = only_chain(progress)
    assert chain["state"] == "interrupted" and chain["obsolete"] == 1 and chain["pending"] == 0
    assert progress.data["obsolete_chunk_ids"] == [ids[2]]
    assert progress.data["floor"] == {"while": "speaking", "decision": None}
    cut = chain["chunks"][0]
    assert (cut["id"], cut["ph"], cut["played_ms"]) == (ids[1], "interrupted", 1200)
    assert chain["basis"] == BASIS_PROPORTIONAL


def test_superseded_and_expired_chunks_are_obsolete_and_unconfirmed_is_never_claimed_heard():
    snap, ids, _ = snapshot_for(["unconfirmed", "superseded", "expired"])
    progress = SpeechProgressTracker().observe(snap)
    chain = only_chain(progress)
    assert chain["heard"] == 0 and chain["obsolete"] == 2
    assert set(progress.data["obsolete_chunk_ids"]) == {ids[1], ids[2]}


def test_frozen_queue_is_reported_while_the_user_holds_the_floor():
    snap, *_ = snapshot_for(["deferred", "deferred", "deferred"], floor={"while": "thinking", "decision": None})
    assert only_chain(SpeechProgressTracker().observe(snap))["state"] == "frozen"


def test_a_chain_leaving_the_scheduler_drops_its_tracker_state():
    tracker = SpeechProgressTracker()
    snap, ids, _ = snapshot_for(["started", "deferred", "deferred"])
    tracker.observe(snap, {ids[0]: ChunkEvidence(500, 1000)})
    tracker.observe({"candidates": []})
    assert tracker._high == {} and tracker._restarts == {}
    assert tracker.observe({"candidates": []}).data["chains"] == []


def test_conversation_candidates_are_not_speech_of_the_brain():
    snap = {"candidates": [{"candidate_id": "c1", "status": "eligible", "chunk": {
        "chain_id": "c1", "index": 0, "count": 1, "span": {"start": 0, "end": 3}}}]}
    assert SpeechProgressTracker().observe(snap).data["chains"] == []


def test_preview_is_one_line_bounded_and_only_when_the_caller_supplies_the_text():
    snap, ids, spans = snapshot_for(["started", "deferred", "deferred"])
    tracker = SpeechProgressTracker()
    assert "preview" not in only_chain(tracker.observe(snap))["chunks"][0]
    chunk = only_chain(tracker.observe(snap, texts={REQUEST_ID: TEXT}))["chunks"][0]
    assert chunk["preview"] == TEXT[spans[0].start:spans[0].end].strip()
    long_text = "mot " * 80
    snap2, _, _ = snapshot_for(["started"], text=long_text)
    preview = only_chain(SpeechProgressTracker().observe(snap2, texts={REQUEST_ID: long_text}))["chunks"][0]["preview"]
    assert len(preview) <= 60 and "\n" not in preview


def test_voice_records_become_evidence_with_total_only_once_generation_is_complete():
    def record(speech_id, status, played, received):
        return VoiceSpeechRecord(
            correlation=VoiceCorrelation(session_id="vs-1", speech_id=speech_id), state=VoiceSpeechState.PLAYING, generation_status=status,
            playback_status=VoicePlaybackStatus.PARTIAL if played else VoicePlaybackStatus.UNPLAYED, played_ms=played, received_audio_ms=received,
            first_played_order=1 if played else None, local_active=True)

    evidence = evidence_from_voice_records([
        record("a", VoiceGenerationStatus.COMPLETED, 700, 3000),
        record("b", VoiceGenerationStatus.INCOMPLETE, 400, 900),
        VoiceSpeechRecord(correlation=VoiceCorrelation(session_id="vs-1", provider_output_id="o-only")),
    ])
    assert evidence == {"a": ChunkEvidence(700, 3000), "b": ChunkEvidence(400, None)}


def test_budget_is_hard_even_for_three_sixteen_chunk_chains_and_feeds_perception_under_8kib():
    candidates = []
    for chain_index in range(4):
        text = "\n\n".join(f"Paragraphe numero {n} de la chaine {chain_index}." for n in range(16))
        snap, ids, _ = snapshot_for(["started"] + ["deferred"] * 15, text=text, request_id=f"req-{chain_index}")
        candidates.extend(snap["candidates"])
    texts = {f"req-{i}": "\n\n".join(f"Paragraphe numero {n} de la chaine {i}." for n in range(16)) for i in range(4)}
    progress = SpeechProgressTracker().observe({"candidates": candidates}, texts=texts)
    assert len(progress.serialize().encode()) <= MAX_SPEECH_SECTION_BYTES
    assert len(progress.data["chains"]) <= 3 and progress.data["more_chains"] >= 1
    section = progress.to_section()
    assert isinstance(section, SpeechSection) and section.status == "wired"
    perception = build_perception(UiState(scene=None, epoch=None, boards=(), active_board_id=None), speech=section)
    assert len(perception.serialize().encode()) <= MAX_PERCEPTION_BYTES
    assert perception.data["speech"]["data"]["schema"] == SPEECH_SCHEMA


def test_oversized_budget_that_no_reduction_can_meet_raises_instead_of_truncating_silently():
    snap, *_ = snapshot_for(["started", "deferred", "deferred"])
    with pytest.raises(ValueError, match="exceeds"):
        SpeechProgressTracker().observe(snap, max_bytes=40)


def test_projection_is_deterministic_and_carries_no_clock_or_secret():
    snap, ids, _ = snapshot_for(["completed", "started", "deferred"])
    one = SpeechProgressTracker().observe(snap, {ids[1]: ChunkEvidence(10, 100)}).serialize()
    two = SpeechProgressTracker().observe(snap, {ids[1]: ChunkEvidence(10, 100)}).serialize()
    assert one == two
    for forbidden in ("reasoning", "prompt", "thinking", "token"):
        assert forbidden not in one


# --- vrai planificateur ---------------------------------------------------------------------------------


def request(text, *, correlation="corr-1"):
    return SpeechRequest(CONVERSATION, text, correlation_id=correlation, source=source(correlation),
                         kind=SpeechKind.RESULT, chunks=semantic_text_spans(text), id=REQUEST_ID)


async def test_a_real_scheduler_snapshot_projects_a_long_answer_then_its_interruption():
    session = FakeVoiceSession()
    scheduler = build_scheduler(FakeCore(), session)
    tracker = SpeechProgressTracker()
    await scheduler.start()
    try:
        scheduler._enqueue(request(TEXT))
        await wait_for(lambda: len(session.spoken) == 1)
        spoken = session.spoken[0].id
        ids = presentation_chunk_ids(REQUEST_ID, semantic_text_spans(TEXT))
        assert spoken == ids[0]
        chain = only_chain(tracker.observe(scheduler.presentation_snapshot(), {spoken: ChunkEvidence(300, 1200)},
                                           texts={REQUEST_ID: TEXT}))
        assert chain["state"] == "playing" and chain["n"] == 3 and chain["corr"] == "corr-1"
        assert [chunk["id"] for chunk in chain["chunks"]] == [ids[0], ids[1], ids[2]]
        scheduler.note_floor_taken("speaking")
        scheduler.note_interruption(None)
        await finish_speech(scheduler, session, status="cancelled")
        await asyncio.sleep(.02)
        progress = tracker.observe(scheduler.presentation_snapshot(), {spoken: ChunkEvidence(300, 1200)})
        chain = only_chain(progress)
        assert chain["state"] == "interrupted" and chain["pending"] == 0
        assert set(progress.data["obsolete_chunk_ids"]) == {ids[1], ids[2]}
        assert progress.data["floor"]["while"] == "speaking"
        assert json.loads(progress.serialize())["schema"] == SPEECH_SCHEMA
    finally:
        await scheduler.stop()

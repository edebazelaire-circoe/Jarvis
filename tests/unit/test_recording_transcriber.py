"""Transcription durable d'un enregistrement explicite : segments immuables, projection, relance, reprise.

Handoff session-context-recording, Slice 06. Contrat : `docs/capture.md` › *Transcription*.
Fournisseur factice (lent, délai dépassé, panne puis succès, réponse vide),
micro factice (`FakeInput` de `test_audio_recording_source`), base et
dossiers sous `tmp_path`. Aucun appel réseau, aucun vrai micro.
"""

from __future__ import annotations

import ast
import array
import asyncio
import math
from pathlib import Path
import sqlite3
import time

import pytest

from jarvis.adapters.artifact_payloads import FileArtifactPayloads
from jarvis.adapters.sounddevice_recording import AudioRecordingSources, OpenedInput
from jarvis.adapters.sqlite_artifacts import SQLiteArtifactRepository
from jarvis.adapters.sqlite_session_activity import SQLiteActivityLedger
from jarvis.adapters.sqlite_session_context import SQLiteContextRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.audio.wav_pcm import pcm16_wav
from jarvis.core.artifact_service import ArtifactService
from jarvis.core.recording_transcriber import (
    SOURCE, RecordingTranscriber, TranscriptionState, projection_id_of, segment_id_of,
)
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.artifacts import ArtifactKind, ArtifactRelationKind, ArtifactState
from jarvis.domain.capture import (
    CaptureChannel, CaptureErrorCode, CaptureMode, CaptureState, StopReason, activate, attach_artifact, finish,
    new_capture, request_stop,
)
from jarvis.domain.errors import ProviderError
from jarvis.domain.results import TranscriptionResult
from jarvis.domain.session_activity import ActivityKind, ActivityQuery
from jarvis.domain.session_context import create_context
from jarvis.domain.v2 import utc_now
from jarvis.domain.workspace_board import default_board, open_session
from jarvis.ports.artifacts import RelationDirection

RATE = 16_000
ROOT = Path(__file__).resolve().parents[2]


def pcm(ms: int, amplitude: int) -> bytes:
    count = RATE * ms // 1000
    return array.array("h", [int(amplitude * math.sin(2 * math.pi * 180 * i / RATE)) for i in range(count)]).tobytes()


def speech(ms: int) -> bytes:
    return pcm(ms, 9000)


def silence(ms: int) -> bytes:
    return pcm(ms, 15)


#: Deux phrases : parole 1,0-2,5 s et 3,5-5,0 s.
TWO_PHRASES = silence(1000) + speech(1500) + silence(1000) + speech(1500) + silence(1000)


async def until(predicate, timeout: float = 5.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


class FakeSTT:
    """Fournisseur scripté : chaque appel prend l'issue suivante (`ok` par défaut)."""

    def __init__(self, *outcomes: object, gate: asyncio.Event | None = None) -> None:
        self.outcomes = list(outcomes)
        self.gate = gate
        self.calls: list[int] = []

    async def transcribe(self, audio) -> TranscriptionResult:  # noqa: ANN001
        self.calls.append(audio.duration_ms)
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if self.gate is not None:
            await self.gate.wait()
        if outcome == "hang":
            await asyncio.sleep(30)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome == "empty":
            raise ProviderError("openai", "transcription", "Empty transcription response")
        return TranscriptionResult(text=f"phrase {len(self.calls)}", duration_ms=5, provider="fake", model="fake-stt")


class Env:
    def __init__(self, root: Path, state: SQLiteStateRepository, artifacts: ArtifactService, session_id: str,
                 context_id: str) -> None:
        self.root, self.state, self.artifacts = root, state, artifacts
        self.session_id, self.context_id = session_id, context_id
        self.captures: dict = {}

    async def reader(self, capture_id: str):  # noqa: ANN201
        return self.captures[capture_id]

    def transcriber(self, backend, **options) -> RecordingTranscriber:  # noqa: ANN001, ANN003
        options = {"attempt_backoff_s": (0.0,), "retry_wait_s": (0.05,), "poll_s": 0.02, **options}
        return RecordingTranscriber(self.artifacts, self.reader, lambda: backend, **options)

    async def recording(self, audio: bytes, *, state: CaptureState = CaptureState.COMPLETE):  # noqa: ANN201
        """Un enregistrement fini (WAV final), sa ligne de capture et son Artifact."""

        now = utc_now()
        record = new_capture(channel=CaptureChannel.AUDIO, mode=CaptureMode.CONTINUOUS, source="microphone", now=now,
                             jarvis_session_id=self.session_id, context_id=self.context_id)
        artifact = await self.artifacts.create(kind=ArtifactKind.AUDIO_RECORDING, source="capture.audio",
                                               jarvis_session_id=self.session_id, context_id=self.context_id,
                                               payload_name="source.wav", started_at=now, mime_type="audio/wav",
                                               metadata={"capture_id": record.capture_id})
        record = activate(attach_artifact(record, artifact.artifact_id, now=now), now=now)
        await self.artifacts.store_payload(artifact.artifact_id, pcm16_wav(audio, sample_rate=RATE),
                                           state=ArtifactState(state.value), duration_ms=len(audio) * 500 // RATE,
                                           error_code=None if state is CaptureState.COMPLETE else "capture_gap")
        record = finish(request_stop(record, now=now, reason=StopReason.USER), now=now, state=state,
                        error_code=None if state is CaptureState.COMPLETE else "capture_gap")
        self.captures[record.capture_id] = record
        return record

    async def events(self, *kinds: ActivityKind):  # noqa: ANN201
        return await self.artifacts.activity(ActivityQuery(kinds=kinds, limit=500))

    async def segments(self, audio_id: str):  # noqa: ANN201
        relations = await self.artifacts.relations(audio_id, RelationDirection.DEPENDENTS)
        found = [await self.artifacts.get(r.artifact_id) for r in relations
                 if r.relation is ArtifactRelationKind.TRANSCRIBED_FROM]
        return sorted((a for a in found if a.kind is ArtifactKind.TRANSCRIPT_SEGMENT),
                      key=lambda a: a.metadata["seq"])


async def make_env(root: Path) -> Env:
    state = SQLiteStateRepository(root / "state" / "jarvis.sqlite3")
    await state.initialize()
    artifacts = ArtifactService(SQLiteArtifactRepository(state), SQLiteActivityLedger(state), FileArtifactPayloads(root))
    boards, contexts = SQLiteBoardRepository(state), SQLiteContextRepository(state)
    session = await boards.current_session()
    if session is None:
        board = default_board(now=utc_now())
        await boards.save_board(board)
        session = open_session(board, now=utc_now())
        await boards.save_session(session)
        transition = create_context(session, (), now=utc_now())
        await contexts.commit_contexts(transition.changed)
        context_id = transition.active.context_id
    else:
        context_id = (await contexts.list_contexts(session.jarvis_session_id))[-1].context_id
    return Env(root, state, artifacts, session.jarvis_session_id, context_id)


async def run_to_end(transcriber: RecordingTranscriber, record) -> dict:  # noqa: ANN001
    await transcriber.on_capture_started(record)

    def done() -> bool:
        status = transcriber.status(record.capture_id)
        return status is not None and status["state"] in ("complete", "partial")

    await until(done)
    return transcriber.status(record.capture_id)


# ------------------------------------------------------------------ nominal, ordre et temps


async def test_segments_are_immutable_ordered_timecoded_evidence_and_the_projection_reads_whole(tmp_path):
    env = await make_env(tmp_path)
    stt = FakeSTT()
    transcriber = env.transcriber(stt)
    record = await env.recording(TWO_PHRASES)
    try:
        status = await run_to_end(transcriber, record)
        assert status["segments"] == 2 and status["state"] == "complete"
        first, second = await env.segments(record.artifact_id)
        for segment, (low, high) in ((first, (700, 1100)), (second, (3200, 3600))):
            assert segment.state is ArtifactState.COMPLETE and segment.source == SOURCE
            assert low <= segment.metadata["start_ms"] <= high, segment.metadata
            assert segment.metadata["end_ms"] - segment.metadata["start_ms"] == segment.duration_ms
            assert segment.started_at == record.activated_at + (segment.started_at - record.activated_at)
            assert (segment.started_at - record.activated_at).total_seconds() * 1000 == pytest.approx(
                segment.metadata["start_ms"], abs=1)
            assert (segment.jarvis_session_id, segment.context_id) == (env.session_id, env.context_id)
            assert segment.metadata["speaker"] is None  # extensible (diarisation : enrichissement plus tard)
        assert first.metadata["end_ms"] <= second.metadata["start_ms"]
        assert (first.text, second.text) == ("phrase 1", "phrase 2")
        assert first.artifact_id == segment_id_of(record.artifact_id, 1)
        projection = await env.artifacts.get(projection_id_of(record.artifact_id))
        assert projection.state is ArtifactState.COMPLETE and projection.text == "phrase 1\nphrase 2"
        assert (tmp_path / "artifacts" / projection.artifact_id / "transcript.txt").read_text("utf-8") == \
            "phrase 1\nphrase 2"
        origins = {(r.relation, r.origin_artifact_id)
                   for r in await env.artifacts.relations(first.artifact_id, RelationDirection.ORIGINS)}
        assert origins == {(ArtifactRelationKind.TRANSCRIBED_FROM, record.artifact_id),
                           (ArtifactRelationKind.SEGMENT_OF, projection.artifact_id)}
        created = await env.events(ActivityKind.TRANSCRIPT_SEGMENT_CREATED)
        assert [e.data["seq"] for e in created] == [1, 2]
        assert all("text" not in e.data and "phrase" not in str(e.data) for e in created), "jamais de texte"
        assert len(await env.events(ActivityKind.TRANSCRIPT_PROJECTION_UPDATED)) >= 3
    finally:
        await transcriber.close()
        await env.state.close()


async def test_forced_segmentation_of_an_unbroken_speaker_stays_contiguous(tmp_path):
    env = await make_env(tmp_path)
    transcriber = env.transcriber(FakeSTT(), max_utterance_ms=3000)
    record = await env.recording(silence(500) + speech(7000) + silence(1000))
    try:
        await run_to_end(transcriber, record)
        segments = await env.segments(record.artifact_id)
        assert len(segments) >= 2 and segments[0].metadata["forced_cut"] is True
        for before, after in zip(segments, segments[1:]):
            assert before.metadata["end_frame"] == after.metadata["start_frame"], "aucun trou entre deux coupes"
        assert [s.metadata["seq"] for s in segments] == list(range(1, len(segments) + 1))
    finally:
        await transcriber.close()
        await env.state.close()


async def test_a_partial_recording_gives_a_partial_transcript(tmp_path):
    env = await make_env(tmp_path)
    transcriber = env.transcriber(FakeSTT())
    record = await env.recording(TWO_PHRASES, state=CaptureState.PARTIAL)
    try:
        status = await run_to_end(transcriber, record)
        assert status["state"] == "partial"
        projection = await env.artifacts.get(projection_id_of(record.artifact_id))
        assert (projection.state, projection.error_code) == (ArtifactState.PARTIAL, "capture_gap")
    finally:
        await transcriber.close()
        await env.state.close()


async def test_an_empty_provider_answer_is_no_speech_not_a_failure(tmp_path):
    env = await make_env(tmp_path)
    transcriber = env.transcriber(FakeSTT("empty", "empty"))
    record = await env.recording(TWO_PHRASES)
    try:
        status = await run_to_end(transcriber, record)
        assert (status["state"], status["segments"]) == ("complete", 0)
        projection = await env.artifacts.get(projection_id_of(record.artifact_id))
        assert projection.state is ArtifactState.COMPLETE and projection.text == ""
    finally:
        await transcriber.close()
        await env.state.close()


# ------------------------------------------------------------------ délais, pannes, relances


async def test_a_timed_out_attempt_is_retried_and_counted(tmp_path):
    env = await make_env(tmp_path)
    stt = FakeSTT("hang")
    transcriber = env.transcriber(stt, attempt_timeout_s=0.1)
    record = await env.recording(silence(500) + speech(1500) + silence(1000))
    try:
        await run_to_end(transcriber, record)
        (segment,) = await env.segments(record.artifact_id)
        assert segment.metadata["attempts"] == 2 and len(stt.calls) == 2
    finally:
        await transcriber.close()
        await env.state.close()


async def test_a_provider_outage_waits_then_retries_on_its_own_without_duplicates(tmp_path):
    env = await make_env(tmp_path)
    outage = ProviderError("openai", "transcription", "OpenAI HTTP 503", retryable=True)
    stt = FakeSTT(outage, outage)
    transcriber = env.transcriber(stt, attempts=2, retry_wait_s=(0.3,))
    record = await env.recording(silence(500) + speech(1500) + silence(1000))
    try:
        await transcriber.on_capture_started(record)
        await until(lambda: (transcriber.status(record.capture_id) or {}).get("state") == "waiting_retry")
        for _ in range(100):  # l'état en mémoire précède son commit de quelques ms
            projection = await env.artifacts.get(projection_id_of(record.artifact_id))
            if projection.metadata["transcription_state"] != "running":
                break
            await asyncio.sleep(0.005)
        assert projection.is_pending
        assert (projection.metadata["transcription_state"], projection.metadata["error_code"]) == (
            "waiting_retry", "transcription_unavailable")
        assert "OpenAI HTTP 503" in projection.metadata["last_error"], "la cause réelle est dite"
        await until(lambda: transcriber.status(record.capture_id)["state"] == "complete")
        (segment,) = await env.segments(record.artifact_id)
        assert len(stt.calls) == 3 and segment.metadata["seq"] == 1
    finally:
        await transcriber.close()
        await env.state.close()


async def test_a_refusal_waits_for_an_explicit_retry_and_two_retries_do_not_duplicate(tmp_path):
    env = await make_env(tmp_path)
    stt = FakeSTT(ProviderError("openai", "transcription", "OpenAI HTTP 401", retryable=False))
    transcriber = env.transcriber(stt)
    record = await env.recording(TWO_PHRASES)
    try:
        await transcriber.on_capture_started(record)
        await until(lambda: (transcriber.status(record.capture_id) or {}).get("state") == "unavailable")
        await asyncio.sleep(0.2)
        assert len(stt.calls) == 1, "pas de relance automatique d'un refus"
        await asyncio.gather(transcriber.retry(record.capture_id), transcriber.retry(record.capture_id))
        await until(lambda: transcriber.status(record.capture_id)["state"] == "complete")
        segments = await env.segments(record.artifact_id)
        assert [s.metadata["seq"] for s in segments] == [1, 2] and len(stt.calls) == 3
    finally:
        await transcriber.close()
        await env.state.close()


async def test_without_a_provider_transcription_is_unavailable_and_retryable_later(tmp_path):
    env = await make_env(tmp_path)
    provider: list = []
    transcriber = RecordingTranscriber(env.artifacts, env.reader, lambda: provider[0] if provider else None,
                                       poll_s=0.02)
    record = await env.recording(TWO_PHRASES)
    try:
        await transcriber.on_capture_started(record)
        await until(lambda: (transcriber.status(record.capture_id) or {}).get("state") == "unavailable")
        status = transcriber.status(record.capture_id)
        assert status["error_code"] == CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE.value
        projection = await env.artifacts.get(projection_id_of(record.artifact_id))
        assert projection.metadata["transcription_state"] == "unavailable"
        provider.append(FakeSTT())  # clé ajoutée dans les réglages
        await transcriber.retry(record.capture_id)
        await until(lambda: transcriber.status(record.capture_id)["state"] == "complete")
    finally:
        await transcriber.close()
        await env.state.close()


# ------------------------------------------------------------------ reprise après la mort de Core


class BlockSecond(FakeSTT):
    """1er appel rendu, 2e bloqué pour toujours : Core meurt pendant cet appel."""

    async def transcribe(self, audio) -> TranscriptionResult:  # noqa: ANN001
        if self.calls:
            self.calls.append(audio.duration_ms)
            await asyncio.Event().wait()
        return await super().transcribe(audio)


async def test_core_restart_resumes_from_the_cursor_and_never_redoes_a_segment(tmp_path):
    env = await make_env(tmp_path)
    dying = BlockSecond()
    first = env.transcriber(dying)
    record = await env.recording(TWO_PHRASES)
    await first.on_capture_started(record)
    await until(lambda: len(dying.calls) == 2)
    assert first.status(record.capture_id)["segments"] == 1
    await first.close()  # Core meurt pendant le 2e appel
    await env.state.close()

    env = await make_env(tmp_path)
    env.captures[record.capture_id] = record
    resumed_stt = FakeSTT()
    second = env.transcriber(resumed_stt)
    try:
        assert await second.recover() == (record.capture_id,)
        projection = await env.artifacts.get(projection_id_of(record.artifact_id))
        assert second.owns(projection) and projection.is_pending
        report = await env.artifacts.recover_pending(owned=second.owns)
        assert projection.artifact_id in report.owned and report.failed == ()
        await until(lambda: (second.status(record.capture_id) or {}).get("state") == "complete")
        assert len(resumed_stt.calls) == 1, "le 1er segment n'est jamais retranscrit"
        segments = await env.segments(record.artifact_id)
        assert [s.metadata["seq"] for s in segments] == [1, 2]
        assert segments[0].metadata["end_frame"] <= segments[1].metadata["start_frame"]
        assert (await env.artifacts.get(projection.artifact_id)).text == "phrase 1\nphrase 1"
    finally:
        await second.close()
        await env.state.close()


async def test_a_segment_written_just_before_death_is_adopted_not_duplicated(tmp_path):
    env = await make_env(tmp_path)
    stt_first = FakeSTT()
    first = env.transcriber(stt_first)
    original_save = first._save

    async def die_after_second_segment(job, *, event):  # noqa: ANN001, ANN202
        if job.next_seq == 3:  # segment 2 écrit, projection pas encore notée : mort ici
            await asyncio.Event().wait()
        await original_save(job, event=event)

    first._save = die_after_second_segment  # type: ignore[method-assign]
    record = await env.recording(TWO_PHRASES)
    await first.on_capture_started(record)
    await until(lambda: len(stt_first.calls) == 2)
    await asyncio.sleep(0.1)
    await first.close()
    projection = await env.artifacts.get(projection_id_of(record.artifact_id))
    assert projection.metadata["next_seq"] == 2, "la projection ignore encore le segment 2"
    await env.state.close()

    env = await make_env(tmp_path)
    env.captures[record.capture_id] = record
    stt = FakeSTT()
    second = env.transcriber(stt)
    try:
        await second.recover()
        await until(lambda: (second.status(record.capture_id) or {}).get("state") == "complete")
        assert stt.calls == [], "segment déjà enregistré : adopté, jamais refait"
        assert [s.metadata["seq"] for s in await env.segments(record.artifact_id)] == [1, 2]
        assert (await env.artifacts.get(projection.artifact_id)).text == "phrase 1\nphrase 2"
    finally:
        await second.close()
        await env.state.close()


# ------------------------------------------------------------------ bout en bout dans Core


class FakeInput:
    def __init__(self) -> None:
        self.callback = None
        self.finished = None

    def open(self, *, device, sample_rates, block_ms, callback, finished):  # noqa: ANN001, ANN201
        self.callback, self.finished = callback, finished

        class Stream:
            def start(self) -> None: ...

            def stop(self) -> None: ...

            def close(self) -> None: ...

        return OpenedInput(stream=Stream(), sample_rate=RATE, device_name="Fake Mic")

    def close(self, opened) -> None:  # noqa: ANN001
        pass


async def test_slow_transcription_never_loses_audio_and_catches_up_after_stop(tmp_path):
    mics: list[FakeInput] = []

    def factory() -> FakeInput:
        mics.append(FakeInput())
        return mics[-1]

    gate = asyncio.Event()
    stt = FakeSTT(gate=gate)
    core = JarvisCoreApplication(data_root=tmp_path,
                                 capture_sources=AudioRecordingSources(configured_device=lambda: None,
                                                                       backend_factory=factory),
                                 recording_transcription=lambda: stt)
    core.transcripts._poll_s = 0.02
    await core.start()
    try:
        record = await core.captures.start(CaptureChannel.AUDIO)
        await until(lambda: core.transcripts.status(record.capture_id) is not None)
        for start in range(0, len(TWO_PHRASES), 3200):
            mics[-1].callback(TWO_PHRASES[start:start + 3200], False)
        await until(lambda: len(stt.calls) == 1)  # 1er segment parti, fournisseur bloqué
        await until(lambda: core.captures.status().captures[0].bytes_written == 44 + len(TWO_PHRASES))
        final = await core.captures.stop(record.capture_id)
        assert final.state is CaptureState.COMPLETE and final.bytes_written == 44 + len(TWO_PHRASES)
        assert core.transcripts.status(record.capture_id)["state"] == "running"  # en retard, pas en panne
        gate.set()
        await until(lambda: core.transcripts.status(record.capture_id)["state"] == "complete")
        projection = await core.artifacts.get(projection_id_of(final.artifact_id))
        assert projection.text == "phrase 1\nphrase 2"
        # D17 : la parole enregistrée n'est jamais un tour adressé.
        db = sqlite3.connect(tmp_path / "state" / "jarvis.sqlite3")
        try:
            assert db.execute("SELECT COUNT(*) FROM conversation_events").fetchone()[0] == 0
        finally:
            db.close()
    finally:
        await core.stop()


async def test_recording_without_any_provider_is_complete_and_its_transcript_unavailable(tmp_path):
    mics: list[FakeInput] = []

    def factory() -> FakeInput:
        mics.append(FakeInput())
        return mics[-1]

    core = JarvisCoreApplication(data_root=tmp_path, capture_sources=AudioRecordingSources(
        configured_device=lambda: None, backend_factory=factory))
    await core.start()
    try:
        record = await core.captures.start(CaptureChannel.AUDIO)
        mics[-1].callback(speech(500), False)
        await until(lambda: (core.transcripts.status(record.capture_id) or {}).get("state") == "unavailable")
        final = await core.captures.stop(record.capture_id)
        assert final.state is CaptureState.COMPLETE, "l'enregistrement ne dépend jamais de la transcription"
        status = await core.transcripts.retry(record.capture_id)
        assert status["error_code"] == "transcription_unavailable"
    finally:
        await core.stop()


# ------------------------------------------------------------------ rework QA : base refusée, rattrapage, bornes


async def test_a_refused_projection_write_is_noted_and_retry_never_duplicates_a_segment(tmp_path):
    env = await make_env(tmp_path)
    stt = FakeSTT()
    transcriber = env.transcriber(stt)
    original = env.artifacts.update_pending
    refused: list[str] = []

    async def refuse_once(artifact_id, **kwargs):  # noqa: ANN001, ANN003, ANN202
        if not refused and (kwargs.get("metadata") or {}).get("next_seq") == 2:
            refused.append(artifact_id)  # segment 1 écrit, sa projection refusée
            raise RuntimeError("database is locked")
        return await original(artifact_id, **kwargs)

    env.artifacts.update_pending = refuse_once  # type: ignore[method-assign]
    record = await env.recording(TWO_PHRASES)
    projection_id = projection_id_of(record.artifact_id)
    try:
        await transcriber.on_capture_started(record)
        await until(lambda: refused and transcriber._jobs[record.capture_id].task is None)
        projection = await env.artifacts.get(projection_id)
        assert projection.is_pending
        assert (projection.metadata["transcription_state"], projection.metadata["error_code"]) == (
            "unavailable", "transcription_unavailable"), "l'arrêt est noté dans la base, pas qu'en mémoire"
        assert "database is locked" in projection.metadata["last_error"]
        assert projection.metadata["next_seq"] == 1, "la base ignore encore le segment 1"
        assert transcriber.status(record.capture_id)["segments"] == 0, "la mémoire n'a pas dépassé la base"
        assert len(await env.segments(record.artifact_id)) == 1

        await transcriber.retry(record.capture_id)
        await until(lambda: transcriber.status(record.capture_id)["state"] == "complete")
        segments = await env.segments(record.artifact_id)
        assert [s.metadata["seq"] for s in segments] == [1, 2]
        assert len({s.artifact_id for s in segments}) == 2
        ranges = sorted((s.metadata["start_frame"], s.metadata["end_frame"]) for s in segments)
        assert ranges[0][1] <= ranges[1][0], f"plages qui se chevauchent : {ranges}"
        assert len(stt.calls) == 2, "le segment 1 est adopté, jamais retranscrit"
        assert (await env.artifacts.get(projection_id)).text == "phrase 1\nphrase 2"
    finally:
        await transcriber.close()
        await env.state.close()


async def test_a_success_resets_the_wait_so_a_second_outage_waits_the_first_delay(tmp_path):
    env = await make_env(tmp_path)
    outage = ProviderError("openai", "transcription", "OpenAI HTTP 503", retryable=True)
    stt = FakeSTT(outage, "ok", outage, "ok")
    transcriber = env.transcriber(stt, attempts=1, retry_wait_s=(0.1, 30.0))
    record = await env.recording(TWO_PHRASES)
    try:
        await transcriber.on_capture_started(record)
        await until(lambda: transcriber.status(record.capture_id)["state"] == "complete", timeout=3.0)
        assert len(stt.calls) == 4
    finally:
        await transcriber.close()
        await env.state.close()


async def _refuse_transcript_creation(env: Env, transcriber: RecordingTranscriber, record) -> None:  # noqa: ANN001
    original = env.artifacts.create

    async def refuse(**kwargs):  # noqa: ANN003, ANN202
        if kwargs.get("kind") is ArtifactKind.TRANSCRIPT:
            raise RuntimeError("database is locked")
        return await original(**kwargs)

    env.artifacts.create = refuse  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):  # dans Core : `core.capture.listener_failed`
        await transcriber.on_capture_started(record)
    env.artifacts.create = original  # type: ignore[method-assign]
    assert transcriber.status(record.capture_id) is None


async def test_a_transcript_refused_at_start_is_created_by_retry(tmp_path):
    env = await make_env(tmp_path)
    transcriber = env.transcriber(FakeSTT())
    record = await env.recording(TWO_PHRASES)
    try:
        await _refuse_transcript_creation(env, transcriber, record)
        status = await transcriber.retry(record.capture_id)
        assert status["transcript_artifact_id"] == projection_id_of(record.artifact_id)
        await until(lambda: transcriber.status(record.capture_id)["state"] == "complete")
        assert (await env.artifacts.get(projection_id_of(record.artifact_id))).text == "phrase 1\nphrase 2"
    finally:
        await transcriber.close()
        await env.state.close()


async def test_a_transcript_refused_at_start_is_caught_up_when_the_recording_stops(tmp_path):
    env = await make_env(tmp_path)
    transcriber = env.transcriber(FakeSTT())
    record = await env.recording(TWO_PHRASES)
    try:
        await _refuse_transcript_creation(env, transcriber, record)
        await transcriber.on_capture_stopped(record)
        await until(lambda: (transcriber.status(record.capture_id) or {}).get("state") == "complete")
        await transcriber.on_capture_stopped(record)  # rejoué : rien de plus
        assert [s.metadata["seq"] for s in await env.segments(record.artifact_id)] == [1, 2]
    finally:
        await transcriber.close()
        await env.state.close()


async def test_core_catches_up_the_transcript_of_a_recording_when_it_stops(tmp_path):
    mics: list[FakeInput] = []

    def factory() -> FakeInput:
        mics.append(FakeInput())
        return mics[-1]

    stt = FakeSTT()
    core = JarvisCoreApplication(data_root=tmp_path,
                                 capture_sources=AudioRecordingSources(configured_device=lambda: None,
                                                                       backend_factory=factory),
                                 recording_transcription=lambda: stt)
    core.transcripts._poll_s = 0.02
    await core.start()
    original = core.artifacts.create
    refused: list[str] = []

    async def refuse(**kwargs):  # noqa: ANN003, ANN202
        if kwargs.get("kind") is ArtifactKind.TRANSCRIPT and not refused:
            refused.append("transcript")
            raise RuntimeError("database is locked")
        return await original(**kwargs)

    core.artifacts.create = refuse  # type: ignore[method-assign]
    try:
        record = await core.captures.start(CaptureChannel.AUDIO)
        await until(lambda: refused)
        for start in range(0, len(TWO_PHRASES), 3200):
            mics[-1].callback(TWO_PHRASES[start:start + 3200], False)
        await until(lambda: core.captures.status().captures[0].bytes_written == 44 + len(TWO_PHRASES))
        assert core.transcripts.status(record.capture_id) is None
        await core.captures.stop(record.capture_id)
        await until(lambda: (core.transcripts.status(record.capture_id) or {}).get("state") == "complete")
        projection = await core.artifacts.get(projection_id_of(record.artifact_id))
        assert projection.text == "phrase 1\nphrase 2"
    finally:
        await core.stop()


async def test_at_most_two_provider_calls_are_in_flight_across_recordings(tmp_path):
    env = await make_env(tmp_path)
    gate = asyncio.Event()
    stt = FakeSTT(gate=gate)
    transcriber = env.transcriber(stt)
    records = [await env.recording(TWO_PHRASES) for _ in range(3)]
    try:
        for record in records:
            await transcriber.on_capture_started(record)
        await until(lambda: len(stt.calls) == 2)
        await asyncio.sleep(0.3)
        assert len(stt.calls) == 2, "deux appels en vol au plus, tous enregistrements confondus"
        gate.set()
        await until(lambda: all(transcriber.status(r.capture_id)["state"] == "complete" for r in records))
        assert len(stt.calls) == 6
    finally:
        await transcriber.close()
        await env.state.close()


def test_the_projection_keeps_a_bounded_readable_tail_and_counts_every_char():
    from jarvis.core.recording_transcriber import _Job
    from jarvis.domain.artifacts import MAX_ARTIFACT_TEXT_CHARS

    assert MAX_ARTIFACT_TEXT_CHARS == 16_000
    transcriber = RecordingTranscriber(None, None, lambda: None)  # type: ignore[arg-type]

    def job() -> _Job:
        return _Job(capture_id="cap", audio_id="aud", projection=None)  # type: ignore[arg-type]

    exact = job()
    transcriber._append_tail(exact, "b" * 16_000)
    assert (len(exact.tail), exact.truncated) == (16_000, False), "pile la borne : rien de coupé"

    lines = job()
    for digit in "123":
        transcriber._append_tail(lines, digit * 6000)
    assert lines.tail == "2" * 6000 + "\n" + "3" * 6000, "coupé à une fin de ligne, jamais au milieu"
    assert lines.truncated and lines.chars == 18_000

    one = job()
    transcriber._append_tail(one, "c" * 16_001)
    assert one.tail == "c" * 16_000 and one.truncated, "une seule ligne trop longue : sa fin"


# ------------------------------------------------------------------ frontières (D12, D17)


def _imports(relative: str) -> set[str]:
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_the_transcriber_never_touches_conversation_or_action_authority():
    leaked = {name for name in _imports("jarvis/core/recording_transcriber.py")
              if any(part in name for part in ("conversation", "speech_authority", "admission", "explicit_address",
                                               "brain", "action"))}
    assert leaked == set()


def test_the_presentation_lane_stays_memory_only_and_untouched_by_recording():
    from jarvis.audio import capture_hub

    assert capture_hub.BACKPRESSURE_POLICY == "drop_oldest"
    for relative in ("jarvis/audio/capture_hub.py", "jarvis/runtime/ambient_lane.py",
                     "jarvis/audio/ambient_segmenter.py", "jarvis/runtime/presentation_audio.py"):
        imported = _imports(relative)
        assert not {name for name in imported if name.endswith(("sounddevice_recording", "recording_transcriber",
                                                                 "artifact_service", "artifact_payloads",
                                                                 "wav_pcm", "capture_service"))}, relative
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "open_spool" not in text and "write_payload" not in text, relative

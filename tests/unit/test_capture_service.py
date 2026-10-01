"""Propriétaire des captures dans Core : cycle de vie, courses, pannes, reprise après mort de Core.

Handoff session-context-recording, Slice 05. Contrat : `docs/capture.md`.
Sources et stockage factices (`jarvis/adapters/fake_capture.py`), bases et
dossiers temporaires (`tmp_path`) seulement ; aucun appareil réel.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import errno
import os
from pathlib import Path
import sqlite3
import threading
import time

import pytest

from jarvis.adapters.artifact_payloads import FileArtifactPayloads
from jarvis.adapters.fake_capture import (
    DEFAULT_FRAME, FailingPayloads, FakeCaptureSource, FakeCaptureSources, FakeOneShotSource,
)
from jarvis.adapters.sqlite_artifacts import SQLiteArtifactRepository
from jarvis.adapters.sqlite_captures import SQLiteCaptureRepository
from jarvis.adapters.sqlite_session_activity import SQLiteActivityLedger
from jarvis.adapters.sqlite_session_context import SQLiteContextRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.artifact_service import ArtifactService
from jarvis.core.capture_service import (
    CaptureAssociation, CaptureOptions, CaptureService, failure_code, storage_code,
)
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.artifacts import ArtifactError, ArtifactErrorCode, ArtifactKind, ArtifactState
from jarvis.domain.capture import (
    CaptureChannel, CaptureError, CaptureErrorCode, CaptureMode, CaptureState, StopReason, attach_artifact,
    new_capture, request_stop,
)
from jarvis.domain.session_activity import ActivityKind, ActivityQuery
from jarvis.domain.session_context import create_context
from jarvis.domain.v2 import utc_now
from jarvis.domain.workspace_board import default_board, open_session
from jarvis.ports.artifacts import PAYLOAD_FAILED, ArtifactPayloadError
from jarvis.ports.capture import (
    CaptureSourceError, CaptureStoreError, CaptureStoreUnavailable, RepairOutcome, RepairTarget,
)

AUDIO, SCREEN = CaptureChannel.AUDIO, CaptureChannel.SCREEN
FRAME = len(DEFAULT_FRAME)


class Journal:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:  # noqa: ANN001
        self.lines.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[dict]:
        return [data for k, _, data in self.lines if k == kind]


class RecordingRepair:
    """Réparation factice : note ce qu'elle voit, réécrit 4 octets en tête du `.partial` (en-tête WAV)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.targets: list[RepairTarget] = []
        self.fail = fail

    def repair(self, target: RepairTarget) -> RepairOutcome:
        self.targets.append(target)
        if self.fail:
            raise OSError(errno.EIO, "fake repair failure")
        if target.partial_bytes:
            with open(target.partial_path, "r+b") as handle:
                handle.write(b"RIFF")
            return RepairOutcome(repaired=True, duration_ms=1234, detail="header_rewritten")
        return RepairOutcome(repaired=False, detail="nothing_to_repair")


@dataclass
class Env:
    root: Path
    state: SQLiteStateRepository
    artifacts: ArtifactService
    repo: SQLiteCaptureRepository
    service: CaptureService
    sources: FakeCaptureSources
    journal: Journal
    association: list[CaptureAssociation] = field(default_factory=list)

    @property
    def sid(self) -> str:
        return self.association[0].jarvis_session_id

    async def aclose(self) -> None:
        await self.service.close()  # aucune capture laissée ouverte par un test
        await self.state.close()

    async def events(self, *kinds: ActivityKind):
        return await self.artifacts.activity(ActivityQuery(kinds=kinds, limit=500))


def fake_sources(**source_kwargs) -> FakeCaptureSources:  # noqa: ANN003
    return FakeCaptureSources(
        continuous={AUDIO: lambda: FakeCaptureSource(**source_kwargs), SCREEN: lambda: FakeCaptureSource(**source_kwargs)},
        one_shot={SCREEN: FakeOneShotSource},
    )


async def make_env(root: Path, *, sources: FakeCaptureSources | None = None, payloads=None, repairs=None,  # noqa: ANN001
                   start_timeout_s: float = 2.0, stop_timeout_s: float = 2.0, seed: bool = True,
                   flush_interval_s: float = 3600.0, fsync_interval_s: float = 3600.0,
                   repair_timeout_s: float = 45.0) -> Env:
    """Cadence de durabilité coupée par défaut (`checkpoint` à la main) : aucun test ne dépend de l'horloge."""

    state = SQLiteStateRepository(root / "state" / "jarvis.sqlite3")
    await state.initialize()
    journal = Journal()
    store = payloads(FileArtifactPayloads(root)) if payloads else FileArtifactPayloads(root)
    artifacts = ArtifactService(SQLiteArtifactRepository(state), SQLiteActivityLedger(state), store,
                                diagnostics=journal)
    holder: list[CaptureAssociation] = []
    if seed:
        boards, contexts = SQLiteBoardRepository(state), SQLiteContextRepository(state)
        board = default_board(now=utc_now())
        await boards.save_board(board)
        session = open_session(board, now=utc_now())
        await boards.save_session(session)
        transition = create_context(session, (), now=utc_now())
        await contexts.commit_contexts(transition.changed)
        holder.append(CaptureAssociation(session.jarvis_session_id, transition.active.context_id))
    else:
        holder.extend(await _existing_association(state))

    async def association() -> CaptureAssociation:
        return holder[0]

    repo = SQLiteCaptureRepository(state)
    sources = sources or fake_sources()
    service = CaptureService(repo, artifacts, sources, association=association, repairs=repairs,
                             diagnostics=journal, start_timeout_s=start_timeout_s, stop_timeout_s=stop_timeout_s,
                             flush_interval_s=flush_interval_s, fsync_interval_s=fsync_interval_s,
                             repair_timeout_s=repair_timeout_s)
    return Env(root, state, artifacts, repo, service, sources, journal, holder)


async def _existing_association(state: SQLiteStateRepository) -> list[CaptureAssociation]:
    session = await SQLiteBoardRepository(state).current_session()
    contexts = await SQLiteContextRepository(state).list_contexts(session.jarvis_session_id)
    return [CaptureAssociation(session.jarvis_session_id, contexts[-1].context_id)]


@pytest.fixture
async def env(tmp_path):
    made = await make_env(tmp_path)
    try:
        yield made
    finally:
        await made.aclose()


async def drain(service: CaptureService) -> None:
    """Laisse passer les rappels du sink (`call_soon_threadsafe`) et les arrêts qu'ils lancent."""

    for _ in range(3):
        await asyncio.sleep(0)
        while service._tasks:
            await asyncio.gather(*list(service._tasks), return_exceptions=True)


async def checkpoint(service: CaptureService, *, durable: bool = False) -> None:
    """Un tour de la cadence du propriétaire, à la main."""

    for run in list(service._runs.values()):
        if run.sink is not None:
            await asyncio.to_thread(run.sink.checkpoint, durable=durable)


def source_of(env: Env, index: int = -1) -> FakeCaptureSource:
    return env.sources.created[index]  # type: ignore[return-value]


# ------------------------------------------------------------------ cycle nominal


async def test_start_observe_stop_finalizes_a_complete_artifact_with_activity(env):
    record = await env.service.start(AUDIO)
    assert record.state is CaptureState.ACTIVE and record.capture_id.startswith("jcap_")
    assert (record.jarvis_session_id, record.context_id) == (env.association[0].jarvis_session_id,
                                                             env.association[0].context_id)
    artifact = await env.artifacts.get(record.artifact_id)
    assert artifact.state is ArtifactState.PENDING and artifact.kind is ArtifactKind.AUDIO_RECORDING
    assert artifact.metadata["capture_id"] == record.capture_id
    source = source_of(env)
    source.push(4)
    (live,) = env.service.status().captures
    assert live.bytes_written == 0  # encore dans le tampon du processus : pas annoncé (ne survivrait pas)
    await checkpoint(env.service)
    (live,) = env.service.status().captures
    assert (live.capture_id, live.bytes_written, live.state) == (record.capture_id, 5 * FRAME, CaptureState.ACTIVE)

    done = await env.service.stop(record.capture_id)
    assert (done.state, done.error_code, done.stop_reason) == (CaptureState.COMPLETE, None, StopReason.USER)
    assert done.bytes_written == 5 * FRAME and done.ended_at is not None
    artifact = await env.artifacts.get(record.artifact_id)
    assert (artifact.state, artifact.size_bytes, artifact.duration_ms) == (ArtifactState.COMPLETE, 5 * FRAME, 50)
    assert (env.root / "artifacts" / artifact.artifact_id / "source.bin").read_bytes() == DEFAULT_FRAME * 5
    assert env.service.status().captures == ()
    assert await env.repo.get_capture(record.capture_id) == done
    kinds = [e.kind for e in await env.events() if record.capture_id in e.capture_ids]
    assert kinds == [ActivityKind.ARTIFACT_CREATED, ActivityKind.CAPTURE_STARTED, ActivityKind.CAPTURE_STOPPED]
    (stopped,) = await env.events(ActivityKind.CAPTURE_STOPPED)
    assert stopped.data["state"] == "complete" and stopped.artifact_ids == (record.artifact_id,)
    assert env.journal.of("core.capture.started")[0]["capture_id"] == record.capture_id
    assert source.stop_calls == 1


async def test_stop_is_idempotent_and_unknown_ids_are_named(env):
    record = await env.service.start(AUDIO)
    first = await env.service.stop(record.capture_id)
    again = await env.service.stop(record.capture_id)
    assert again == first
    assert len(await env.events(ActivityKind.CAPTURE_STOPPED)) == 1
    with pytest.raises(CaptureError) as caught:
        await env.service.stop("jcap_unknown")
    assert caught.value.code is CaptureErrorCode.CAPTURE_NOT_FOUND and caught.value.status == 404
    with pytest.raises(CaptureError) as caught:
        await env.service.stop("jcap_UPPER")
    assert caught.value.code is CaptureErrorCode.INVALID_CAPTURE


# ------------------------------------------------------------------ concurrence et conflits


async def test_one_capture_per_channel_device_but_channels_and_devices_run_together(env):
    audio = await env.service.start(AUDIO)
    with pytest.raises(CaptureError) as caught:
        await env.service.start(AUDIO)
    assert (caught.value.code, caught.value.capture_id) == (CaptureErrorCode.ALREADY_ACTIVE, audio.capture_id)
    screen = await env.service.start(SCREEN)
    other_mic = await env.service.start(AUDIO, CaptureOptions(device="usb-mic"))
    assert {r.capture_id for r in env.service.status().captures} == {audio.capture_id, screen.capture_id,
                                                                      other_mic.capture_id}
    assert len(env.service.status().active_on(AUDIO)) == 2
    for record in (audio, screen, other_mic):
        assert (await env.service.stop(record.capture_id)).state is CaptureState.COMPLETE
    assert (await env.service.start(AUDIO)).state is CaptureState.ACTIVE  # canal libéré


async def test_two_concurrent_starts_on_one_channel_admit_exactly_one(env):
    results = await asyncio.gather(env.service.start(AUDIO), env.service.start(AUDIO), return_exceptions=True)
    started = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, CaptureError)]
    assert len(started) == 1 and len(refused) == 1
    assert refused[0].code is CaptureErrorCode.ALREADY_ACTIVE and refused[0].capture_id == started[0].capture_id
    assert len(env.sources.created) == 2  # la source refusée n'a jamais été démarrée
    assert sum(s.start_calls for s in env.sources.created) == 1


async def test_an_orphan_row_holding_the_device_is_reconciled_inline_then_the_start_proceeds(env):
    stale = new_capture(channel=AUDIO, mode=CaptureMode.CONTINUOUS, source="fake", now=utc_now(),
                        jarvis_session_id=env.sid)
    await env.repo.insert_capture(stale)  # ligne d'une autre vie, pas en mémoire
    with pytest.raises(CaptureError) as caught:
        await env.repo.insert_capture(new_capture(channel=AUDIO, mode=CaptureMode.CONTINUOUS, source="fake",
                                                  now=utc_now(), jarvis_session_id=env.sid))
    assert (caught.value.code, caught.value.capture_id) == (CaptureErrorCode.ALREADY_ACTIVE, stale.capture_id)
    started = await env.service.start(AUDIO)  # le magasin nomme l'orphelin : réconcilié, puis un essai
    assert started.state is CaptureState.ACTIVE
    closed = await env.repo.get_capture(stale.capture_id)
    assert (closed.state, closed.error_code, closed.stop_reason) == (
        CaptureState.FAILED, "capture_interrupted", StopReason.RECOVERED)
    assert env.journal.of("core.capture.orphan_recovered")[0]["capture_id"] == stale.capture_id


async def test_an_orphan_that_cannot_be_reconciled_keeps_the_already_active_refusal(env):
    stale = new_capture(channel=AUDIO, mode=CaptureMode.CONTINUOUS, source="fake", now=utc_now(),
                        jarvis_session_id=env.sid)
    await env.repo.insert_capture(stale)

    async def unreadable(capture_id):  # noqa: ANN001
        raise CaptureStoreError("captures", capture_id, "key columns disagree with data")

    env.repo.get_capture = unreadable
    with pytest.raises(CaptureError) as caught:
        await env.service.start(AUDIO)
    assert (caught.value.code, caught.value.capture_id) == (CaptureErrorCode.ALREADY_ACTIVE, stale.capture_id)
    assert env.journal.of("core.capture.orphan_unrecovered")[0]["code"] == "storage_unavailable"


async def test_stop_during_starting_waits_for_the_source_then_stops_once(tmp_path):
    gate = asyncio.Event()
    env = await make_env(tmp_path, sources=fake_sources(start_gate=gate))
    try:
        start = asyncio.create_task(env.service.start(AUDIO))
        for _ in range(200):  # la ligne `starting` est écrite dans un fil SQLite
            if env.service.status().captures:
                break
            await asyncio.sleep(0.005)
        (starting,) = env.service.status().captures
        assert starting.state is CaptureState.STARTING
        stop = asyncio.create_task(env.service.stop(starting.capture_id))
        for _ in range(200):
            if env.service.status().captures[0].state is CaptureState.STOPPING:
                break
            await asyncio.sleep(0.005)
        assert (await env.repo.get_capture(starting.capture_id)).state is CaptureState.STOPPING
        assert env.service.status().captures[0].state is CaptureState.STOPPING
        gate.set()
        started, stopped = await asyncio.gather(start, stop)
        assert started.state is CaptureState.STOPPING  # jamais `active` : l'arrêt était déjà demandé
        assert stopped.state is CaptureState.COMPLETE and stopped.activated_at is None
        source = source_of(env)
        assert (source.start_calls, source.stop_calls) == (1, 1)
        assert await env.events(ActivityKind.CAPTURE_STARTED) == ()
        assert len(await env.events(ActivityKind.CAPTURE_STOPPED)) == 1
    finally:
        await env.aclose()


async def test_concurrent_stops_share_one_stop(tmp_path):
    gate = asyncio.Event()
    env = await make_env(tmp_path, sources=fake_sources(stop_gate=gate))
    try:
        record = await env.service.start(AUDIO)
        stops = [asyncio.create_task(env.service.stop(record.capture_id)) for _ in range(3)]
        for _ in range(200):
            if source_of(env).stop_calls:
                break
            await asyncio.sleep(0.005)
        assert (await env.service.get(record.capture_id)).state is CaptureState.STOPPING
        gate.set()
        results = await asyncio.gather(*stops)
        assert len({r.state for r in results}) == 1 and results[0].state is CaptureState.COMPLETE
        assert source_of(env).stop_calls == 1
        assert len(await env.events(ActivityKind.CAPTURE_STOPPED)) == 1
    finally:
        await env.aclose()


# ------------------------------------------------------------------ perte de source et trous


async def test_source_loss_stops_the_capture_as_partial_with_a_gap(env):
    record = await env.service.start(AUDIO)
    source = source_of(env)
    source.push(2)
    source.lose()
    await drain(env.service)
    final = await env.service.get(record.capture_id)
    assert (final.state, final.error_code, final.stop_reason) == (CaptureState.PARTIAL, "source_lost",
                                                                  StopReason.SOURCE_LOST)
    artifact = await env.artifacts.get(record.artifact_id)
    assert (artifact.state, artifact.error_code, artifact.size_bytes) == (ArtifactState.PARTIAL, "source_lost",
                                                                          3 * FRAME)
    (gap,) = await env.events(ActivityKind.CAPTURE_GAP)
    assert gap.data["reason"] == "source_lost" and gap.capture_ids == (record.capture_id,)
    seqs = {e.kind: e.seq for e in await env.events(ActivityKind.CAPTURE_GAP, ActivityKind.CAPTURE_STOPPED)}
    assert seqs[ActivityKind.CAPTURE_GAP] < seqs[ActivityKind.CAPTURE_STOPPED]
    assert await env.service.stop(record.capture_id) == final  # arrêt après la perte : rien à refaire


async def test_scripted_loss_without_any_byte_fails(tmp_path):
    env = await make_env(tmp_path, sources=fake_sources(initial_frames=0, lose_after=0))
    try:
        record = await env.service.start(AUDIO)
        source_of(env).push(1)  # la perte scriptée tombe avant la première trame
        await drain(env.service)
        final = await env.service.get(record.capture_id)
        assert (final.state, final.error_code) == (CaptureState.FAILED, "source_lost")
        assert (await env.artifacts.get(record.artifact_id)).state is ArtifactState.FAILED
    finally:
        await env.aclose()


async def test_a_dated_gap_makes_the_evidence_partial_never_complete(env):
    record = await env.service.start(AUDIO)
    source = source_of(env)
    source.drop(lost_ms=120)
    await drain(env.service)
    assert env.service.status().captures[0].gaps == 1
    (gap,) = await env.events(ActivityKind.CAPTURE_GAP)
    assert gap.data == {"reason": "queue_overflow", "lost_ms": 120, "channel": "audio"}
    final = await env.service.stop(record.capture_id)
    assert (final.state, final.error_code, final.gaps) == (CaptureState.PARTIAL, "capture_gap", 1)
    assert (await env.artifacts.get(record.artifact_id)).state is ArtifactState.PARTIAL


# ------------------------------------------------------------------ refus de la source


@pytest.mark.parametrize("code", [CaptureErrorCode.PERMISSION_DENIED, CaptureErrorCode.SOURCE_UNAVAILABLE])
async def test_a_refused_source_fails_the_capture_and_frees_the_channel(tmp_path, code):
    env = await make_env(tmp_path, sources=fake_sources(refuse=code))
    try:
        with pytest.raises(CaptureError) as caught:
            await env.service.start(AUDIO)
        assert caught.value.code is code and caught.value.capture_id
        record = await env.repo.get_capture(caught.value.capture_id)
        assert (record.state, record.error_code, record.stop_reason) == (CaptureState.FAILED, code.value,
                                                                         StopReason.START_FAILED)
        artifact = await env.artifacts.get(record.artifact_id)
        assert (artifact.state, artifact.error_code) == (ArtifactState.FAILED, code.value)
        assert env.service.status().captures == ()
        assert await env.events(ActivityKind.CAPTURE_STARTED) == ()
        env.sources._continuous[AUDIO] = FakeCaptureSource  # l'autorisation est revenue
        assert (await env.service.start(AUDIO)).state is CaptureState.ACTIVE
    finally:
        await env.aclose()


async def test_a_source_that_never_starts_times_out(tmp_path):
    env = await make_env(tmp_path, sources=fake_sources(start_gate=asyncio.Event()), start_timeout_s=0.05)
    try:
        with pytest.raises(CaptureError) as caught:
            await env.service.start(AUDIO)
        assert caught.value.code is CaptureErrorCode.SOURCE_TIMEOUT and caught.value.status == 504
        assert (await env.repo.get_capture(caught.value.capture_id)).state is CaptureState.FAILED
    finally:
        await env.aclose()


async def test_a_source_that_never_stops_is_bounded_and_the_evidence_kept_partial(tmp_path):
    env = await make_env(tmp_path, sources=fake_sources(stop_gate=asyncio.Event()), stop_timeout_s=0.05)
    try:
        record = await env.service.start(AUDIO)
        final = await env.service.stop(record.capture_id)
        assert (final.state, final.error_code) == (CaptureState.PARTIAL, "source_timeout")
        assert (await env.artifacts.get(record.artifact_id)).state is ArtifactState.PARTIAL
    finally:
        await env.aclose()


async def test_unsupported_sources_platforms_and_channels_are_refused_before_any_row(tmp_path):
    env = await make_env(tmp_path, sources=FakeCaptureSources(platform_supported=False))
    try:
        for start, code in ((lambda: env.service.start(AUDIO), CaptureErrorCode.UNSUPPORTED_PLATFORM),
                            (lambda: env.service.start("camera"), CaptureErrorCode.UNSUPPORTED_SOURCE)):
            with pytest.raises(CaptureError) as caught:
                await start()
            assert caught.value.code is code
        env.sources.platform_supported = True
        with pytest.raises(CaptureError) as caught:
            await env.service.start(AUDIO, CaptureOptions(source="microphone"))
        assert caught.value.code is CaptureErrorCode.UNSUPPORTED_SOURCE
        assert await env.repo.recent_captures(limit=10) == ()
        assert env.journal.of("core.capture.refused")[0]["code"] == "unsupported_platform"
    finally:
        await env.aclose()


async def test_no_association_no_capture(env):
    async def broken() -> CaptureAssociation:
        raise RuntimeError("no session")

    env.service._association = broken
    with pytest.raises(CaptureError) as caught:
        await env.service.start(AUDIO)
    assert caught.value.code is CaptureErrorCode.ASSOCIATION_UNAVAILABLE


# ------------------------------------------------------------------ stockage


@pytest.mark.parametrize(("write_errno", "code"), [(errno.ENOSPC, "storage_full"), (errno.EIO, "write_failed")])
async def test_a_write_failure_stops_the_capture_and_keeps_what_was_written(tmp_path, write_errno, code):
    env = await make_env(tmp_path, payloads=lambda inner: FailingPayloads(inner, fail_write_after=2 * FRAME,
                                                                           write_errno=write_errno))
    try:
        record = await env.service.start(AUDIO)
        source = source_of(env)
        assert source.push(5) == 1
        assert source.write_error.value == code
        await drain(env.service)
        final = await env.service.get(record.capture_id)
        assert (final.state, final.error_code, final.stop_reason) == (CaptureState.PARTIAL, code,
                                                                      StopReason.STORAGE_FAILURE)
        artifact = await env.artifacts.get(record.artifact_id)
        assert (artifact.state, artifact.size_bytes, artifact.error_code) == (ArtifactState.PARTIAL, 2 * FRAME, code)
    finally:
        await env.aclose()


@pytest.mark.parametrize(("open_errno", "code"), [(errno.EACCES, "storage_unavailable"), (errno.ENOSPC, "storage_full")])
async def test_storage_refused_at_start_fails_before_the_device_opens(tmp_path, open_errno, code):
    env = await make_env(tmp_path, payloads=lambda inner: FailingPayloads(inner, fail_open=open_errno))
    try:
        with pytest.raises(CaptureError) as caught:
            await env.service.start(AUDIO)
        assert caught.value.code.value == code
        assert source_of(env).start_calls == 0
        record = await env.repo.get_capture(caught.value.capture_id)
        assert record.state is CaptureState.FAILED
        assert (await env.artifacts.get(record.artifact_id)).error_code == code
    finally:
        await env.aclose()


async def test_a_refused_finalization_fails_and_leaves_the_partial_as_evidence(tmp_path):
    env = await make_env(tmp_path, payloads=lambda inner: FailingPayloads(inner, fail_finalize=errno.EIO))
    try:
        record = await env.service.start(AUDIO)
        final = await env.service.stop(record.capture_id)
        assert (final.state, final.error_code) == (CaptureState.FAILED, "finalize_failed")
        artifact = await env.artifacts.get(record.artifact_id)
        assert (artifact.state, artifact.error_code) == (ArtifactState.FAILED, "finalize_failed")
        assert (tmp_path / "artifacts" / artifact.artifact_id / "source.bin.partial").stat().st_size == FRAME
        assert env.journal.of("core.capture.finalize_failed")[0]["code"] == "finalize_failed"
    finally:
        await env.aclose()


# ------------------------------------------------------------------ capture ponctuelle


async def test_a_screenshot_is_one_shot_and_never_conflicts_with_screen_recording(env):
    recording = await env.service.start(SCREEN)
    shot = await env.service.screenshot()
    assert (shot.mode, shot.state, shot.stop_reason) == (CaptureMode.ONE_SHOT, CaptureState.COMPLETE,
                                                         StopReason.ONE_SHOT)
    artifact = await env.artifacts.get(shot.artifact_id)
    assert (artifact.kind, artifact.state, artifact.width, artifact.mime_type) == (
        ArtifactKind.SCREENSHOT, ArtifactState.COMPLETE, 1, "image/png")
    assert (await env.service.stop(shot.capture_id)) == shot  # rien à arrêter
    assert [r.capture_id for r in env.service.status().captures] == [recording.capture_id]
    assert await env.events(ActivityKind.CAPTURE_STARTED) != ()
    assert all(shot.capture_id not in e.capture_ids
               for e in await env.events(ActivityKind.CAPTURE_STARTED, ActivityKind.CAPTURE_STOPPED))


async def test_a_refused_screenshot_fails_its_capture_and_artifact(tmp_path):
    sources = FakeCaptureSources(one_shot={SCREEN: lambda: FakeOneShotSource(refuse=CaptureErrorCode.PERMISSION_DENIED)})
    env = await make_env(tmp_path, sources=sources)
    try:
        with pytest.raises(CaptureError) as caught:
            await env.service.screenshot()
        assert caught.value.code is CaptureErrorCode.PERMISSION_DENIED
        record = await env.repo.get_capture(caught.value.capture_id)
        assert (record.state, record.error_code) == (CaptureState.FAILED, "permission_denied")
        assert (await env.artifacts.get(record.artifact_id)).state is ArtifactState.FAILED
        with pytest.raises(CaptureError) as caught:
            await env.service.screenshot(channel=AUDIO)
        assert caught.value.code is CaptureErrorCode.UNSUPPORTED_SOURCE
    finally:
        await env.aclose()


# ------------------------------------------------------------------ Session et Context


async def test_a_capture_keeps_its_start_context_and_notes_a_switch(env):
    record = await env.service.start(AUDIO)
    await env.service.association_changed("context_created")  # même Context : rien
    assert await env.events(ActivityKind.CAPTURE_ASSOCIATION_CHANGED) == ()
    boards, contexts = SQLiteBoardRepository(env.state), SQLiteContextRepository(env.state)
    session = await boards.current_session()
    transition = create_context(session, tuple(await contexts.list_contexts(session.jarvis_session_id)),
                                now=utc_now())
    await contexts.commit_contexts(transition.changed)
    started = env.association[0]
    env.association[0] = CaptureAssociation(session.jarvis_session_id, transition.active.context_id)
    await env.service.association_changed("context_created")
    (note,) = await env.events(ActivityKind.CAPTURE_ASSOCIATION_CHANGED)
    assert note.context_id == transition.active.context_id and note.capture_ids == (record.capture_id,)
    assert note.data["started_context_id"] == started.context_id and note.data["reason"] == "context_created"
    final = await env.service.stop(record.capture_id)
    assert final.context_id == started.context_id  # association de démarrage gardée
    assert (await env.artifacts.get(record.artifact_id)).context_id == started.context_id


# ------------------------------------------------------------------ arrêt ordonné de Core


async def test_close_stops_every_capture_and_refuses_new_ones(env):
    audio = await env.service.start(AUDIO)
    screen = await env.service.start(SCREEN)
    await env.service.close()
    for record in (audio, screen):
        final = await env.repo.get_capture(record.capture_id)
        assert (final.state, final.stop_reason) == (CaptureState.COMPLETE, StopReason.CORE_SHUTDOWN)
    with pytest.raises(CaptureError) as caught:
        await env.service.start(AUDIO)
    assert caught.value.code is CaptureErrorCode.SERVICE_STOPPING


# ------------------------------------------------------------------ mort de Core et reprise


def _drop_process_buffer(spool) -> None:  # noqa: ANN001 - FileArtifactSpool (or the failing wrapper)
    """Ce que la mort du processus fait au spool : le système ferme le fichier, le tampon Python est perdu.

    Le descripteur est d'abord redirigé vers `NUL` (`dup2`) : la fermeture Python
    « vide » alors son tampon dans le néant, jamais dans le `.partial`.
    """

    spool = getattr(spool, "_inner", spool)
    if spool._closed or spool._external:
        spool._closed = True
        return
    fd = spool._handle.fileno()
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null, fd)
    finally:
        os.close(null)
    spool._handle.close()
    spool._closed = True


def _die(service: CaptureService) -> None:
    """Mort brutale : seuls les octets déjà remis au système restent ; rien n'est finalisé ni écrit en base."""

    for run in service._runs.values():
        if run.durability is not None:
            run.durability.cancel()
        if run.sink is not None:
            with run.sink._lock:
                run.sink._closed = True  # une source attardée ne peut plus rien poster au propriétaire
                _drop_process_buffer(run.sink._spool)
    service._runs.clear()
    service._holders.clear()


async def test_core_death_mid_capture_is_recovered_as_partial_after_repair_never_restarted(tmp_path):
    first = await make_env(tmp_path)
    record = await first.service.start(AUDIO)
    source_of(first).push(9)
    await checkpoint(first.service)  # un tour de cadence : 10 trames remises au système
    source_of(first).push(3)  # encore dans le tampon du processus : perdues avec lui
    _die(first.service)
    await first.aclose()

    repair = RecordingRepair()
    sources = fake_sources()
    second = await make_env(tmp_path, sources=sources, repairs={AUDIO: repair}, seed=False)
    try:
        report = await second.service.recover()
        assert report.partial == (record.capture_id,) and report.failed == () and report.repair_failed == ()
        (target,) = repair.targets
        assert (target.partial_bytes, target.final_bytes) == (10 * FRAME, None)  # réparée avant la promotion
        recovered = await second.repo.get_capture(record.capture_id)
        assert (recovered.state, recovered.error_code, recovered.stop_reason) == (
            CaptureState.PARTIAL, "recoverable_partial", StopReason.RECOVERED)
        assert recovered.data["recovered_from"] == "active" and recovered.data["repair"] == "header_rewritten"
        artifact = await second.artifacts.get(record.artifact_id)
        assert (artifact.state, artifact.size_bytes, artifact.duration_ms) == (ArtifactState.PARTIAL, 10 * FRAME,
                                                                               1234)
        payload = (tmp_path / "artifacts" / artifact.artifact_id / "source.bin").read_bytes()
        assert payload[:4] == b"RIFF" and payload[4:] == (DEFAULT_FRAME * 10)[4:]
        (gap,) = await second.events(ActivityKind.CAPTURE_GAP)
        assert gap.data["reason"] == "core_restart" and gap.capture_ids == (record.capture_id,)
        (stopped,) = await second.events(ActivityKind.CAPTURE_STOPPED)
        assert stopped.data["reason"] == "recovered" and gap.seq < stopped.seq
        assert sources.created == []  # jamais relancée
        assert second.service.status().recovery == report
        assert (await second.artifacts.recover_pending()).partial == ()  # rien laissé à la reprise générique
        assert await second.service.recover() == type(report)()  # idempotent
        assert (await second.service.start(AUDIO)).state is CaptureState.ACTIVE  # appareil libéré
    finally:
        await second.aclose()


async def test_recovery_covers_every_crash_point(tmp_path):
    first = await make_env(tmp_path, sources=fake_sources(initial_frames=0))
    sid, ctx = first.association[0].jarvis_session_id, first.association[0].context_id
    # 1. morte avant même l'Artifact : rien à reprendre
    bare = new_capture(channel=AUDIO, mode=CaptureMode.CONTINUOUS, source="fake", now=utc_now(),
                       jarvis_session_id=sid, context_id=ctx)
    await first.repo.insert_capture(bare)
    # 2. Artifact réservé, spool vide
    empty = await first.service.start(SCREEN, CaptureOptions(device="d2"))
    first.service._runs[empty.capture_id].sink._spool.close()
    # 3. morte entre l'Artifact `complete` et la ligne (arrêt presque fini)
    almost = await first.service.start(SCREEN, CaptureOptions(device="d3"))
    run = first.service._runs[almost.capture_id]
    await first.service._save(run, lambda r: request_stop(r, now=utc_now(), reason=StopReason.USER))
    run.sink.finalize()
    await first.artifacts.finalize(almost.artifact_id)
    first.service._runs.clear()
    first.service._holders.clear()
    await first.aclose()

    second = await make_env(tmp_path, seed=False)
    try:
        report = await second.service.recover()
        assert set(report.failed) == {bare.capture_id, empty.capture_id}
        assert report.complete == (almost.capture_id,) and report.partial == ()
        assert (await second.repo.get_capture(bare.capture_id)).error_code == "capture_interrupted"
        failed_empty = await second.repo.get_capture(empty.capture_id)
        assert failed_empty.error_code == "capture_interrupted"
        assert (await second.artifacts.get(empty.artifact_id)).error_code == "artifact_payload_missing"
        done = await second.repo.get_capture(almost.capture_id)
        assert (done.state, done.error_code) == (CaptureState.COMPLETE, None)
        kinds = [e.kind for e in await second.events(ActivityKind.CAPTURE_GAP, ActivityKind.CAPTURE_STOPPED)
                 if almost.capture_id in e.capture_ids]
        assert kinds == [ActivityKind.CAPTURE_STOPPED]  # aucune perte : pas de trou
        assert await second.repo.open_captures(limit=10) == ()
    finally:
        await second.aclose()


async def test_a_failing_repair_is_logged_and_the_evidence_still_recovered(tmp_path):
    first = await make_env(tmp_path)
    record = await first.service.start(AUDIO)
    await checkpoint(first.service)
    _die(first.service)
    await first.aclose()
    second = await make_env(tmp_path, repairs={AUDIO: RecordingRepair(fail=True)}, seed=False)
    try:
        report = await second.service.recover()
        assert report.partial == (record.capture_id,) and report.repair_failed == (record.capture_id,)
        assert (await second.repo.get_capture(record.capture_id)).data["repair_failed"] is True
        assert second.journal.of("core.capture.repair_failed")[0]["exception_type"] == "OSError"
    finally:
        await second.aclose()


async def test_attach_artifact_is_allowed_while_a_stop_waits_for_the_start():
    record = request_stop(new_capture(channel=AUDIO, mode=CaptureMode.CONTINUOUS, source="fake", now=utc_now()),
                          now=utc_now(), reason=StopReason.USER)
    assert attach_artifact(record, "jart_x", now=utc_now()).artifact_id == "jart_x"


# ------------------------------------------------------------------ câblage dans Core


async def test_core_start_reconciles_captures_before_the_generic_artifact_recovery(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    order: list[str] = []
    capture_recover, artifact_recover = core.captures.recover, core.artifacts.recover_pending
    transcript_recover = core.transcripts.recover

    async def captures_first():
        order.append("captures")
        return await capture_recover()

    async def transcripts_between(recovered):  # noqa: ANN001
        order.append("transcripts")  # Slice 06 : projections reprises par leur propriétaire
        return await transcript_recover(recovered)

    async def artifacts_after(**kwargs):  # noqa: ANN003
        order.append("artifacts")
        assert kwargs["owned"] == core.transcripts.owns
        return await artifact_recover(**kwargs)

    core.captures.recover = captures_first  # type: ignore[method-assign]
    core.transcripts.recover = transcripts_between  # type: ignore[method-assign]
    core.artifacts.recover_pending = artifacts_after  # type: ignore[method-assign]
    await core.start()
    try:
        assert order == ["captures", "transcripts", "artifacts"]
    finally:
        await core.stop()


async def test_core_owns_capture_lifetime_across_its_own_death(tmp_path):
    repair = RecordingRepair()
    core = JarvisCoreApplication(data_root=tmp_path, capture_sources=fake_sources(),
                                 capture_repairs={AUDIO: repair})
    await core.start()
    try:
        with pytest.raises(CaptureError) as caught:
            await JarvisCoreApplication(data_root=tmp_path / "other").captures.start(AUDIO)
        assert caught.value.code is CaptureErrorCode.UNSUPPORTED_SOURCE  # aucune source réelle installée
        record = await core.captures.start(AUDIO)
        context = (await core.sessions.current_context()).context
        assert record.context_id == context.context_id
        await core.sessions.create_context(title="B")  # rappel câblé : la capture traverse le changement
        (note,) = await core.artifacts.activity(ActivityQuery(kinds=(ActivityKind.CAPTURE_ASSOCIATION_CHANGED,)))
        assert note.data["started_context_id"] == context.context_id and note.context_id != context.context_id
        await checkpoint(core.captures)
        _die(core.captures)  # Core meurt avec tout l'arbre : rien n'est finalisé
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path, diagnostics=(journal := Journal()),
                                 capture_sources=fake_sources(), capture_repairs={AUDIO: repair})
    await core.start()
    try:
        recovered = await core.captures.get(record.capture_id)
        assert (recovered.state, recovered.error_code) == (CaptureState.PARTIAL, "recoverable_partial")
        assert len(repair.targets) == 1
        assert journal.of("core.capture.recovery")[0]["partial"] == 1
        assert journal.of("core.artifact.recovery")[0]["partial"] == 0  # déjà repris par le propriétaire
        assert core.captures.status().captures == ()  # jamais relancée
    finally:
        await core.stop()


async def test_core_graceful_stop_finalizes_running_captures(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path, capture_sources=fake_sources())
    await core.start()
    record = await core.captures.start(AUDIO)
    await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        final = await core.captures.get(record.capture_id)
        assert (final.state, final.stop_reason) == (CaptureState.COMPLETE, StopReason.CORE_SHUTDOWN)
        assert core.captures.status().recovery.partial == ()
    finally:
        await core.stop()


# ------------------------------------------------------------------ durabilité : perte bornée (QA S5 MAJOR-1)


async def test_the_owner_hands_the_spool_to_the_system_every_tick_and_fsyncs_on_a_slower_cadence(tmp_path):
    env = await make_env(tmp_path, flush_interval_s=0.05, fsync_interval_s=0.2)
    try:
        record = await env.service.start(AUDIO)
        run = env.service._runs[record.capture_id]
        spool = run.sink._spool
        syncs: list[int] = []
        real_sync = spool.sync

        def counted_sync() -> None:
            syncs.append(spool.size)
            real_sync()

        spool.sync = counted_sync
        source_of(env).push(4)
        partial = env.root / "artifacts" / record.artifact_id / "source.bin.partial"
        for _ in range(100):
            if env.service.status().captures[0].bytes_written == 5 * FRAME and syncs:
                break
            await asyncio.sleep(0.02)
        assert env.service.status().captures[0].bytes_written == 5 * FRAME
        assert partial.stat().st_size == 5 * FRAME  # sur disque (cache du système), sans finalisation
        assert syncs  # `fsync` à son propre rythme, plus lent
        await env.service.stop(record.capture_id)
        assert run.durability is None  # cadence arrêtée avec la source
    finally:
        await env.aclose()


async def test_a_disk_refusal_at_a_checkpoint_stops_the_capture_with_its_storage_code(env):
    record = await env.service.start(AUDIO)
    spool = env.service._runs[record.capture_id].sink._spool

    def full() -> None:
        error = ArtifactPayloadError(PAYLOAD_FAILED, Path("fake"), "flush: disk full")
        error.__cause__ = OSError(None, "disk full", None, 112)
        raise error

    spool.flush = full
    with pytest.raises(CaptureSourceError):
        await checkpoint(env.service)
    await drain(env.service)
    final = await env.service.get(record.capture_id)
    assert (final.state, final.error_code, final.stop_reason) == (
        CaptureState.PARTIAL, "storage_full", StopReason.STORAGE_FAILURE)


def test_disk_full_is_recognised_in_every_form():
    assert storage_code(OSError(None, "full", None, 39), CaptureErrorCode.WRITE_FAILED) is CaptureErrorCode.STORAGE_FULL
    assert storage_code(OSError(None, "full", None, 112), CaptureErrorCode.WRITE_FAILED) \
        is CaptureErrorCode.STORAGE_FULL
    assert storage_code(OSError(errno.ENOSPC, "full"), CaptureErrorCode.WRITE_FAILED) is CaptureErrorCode.STORAGE_FULL
    sqlite_full = sqlite3.OperationalError("database or disk is full")
    sqlite_full.sqlite_errorcode = 13
    wrapped = CaptureStoreUnavailable("update_capture", "OperationalError: database or disk is full")
    wrapped.__cause__ = sqlite_full
    assert storage_code(wrapped, CaptureErrorCode.STORAGE_UNAVAILABLE) is CaptureErrorCode.STORAGE_FULL
    assert failure_code(CaptureStoreUnavailable("x", "OperationalError: database is locked")) \
        is CaptureErrorCode.STORAGE_UNAVAILABLE
    assert storage_code(OSError(None, "denied", None, 5), CaptureErrorCode.WRITE_FAILED) \
        is CaptureErrorCode.WRITE_FAILED


_CHILD = r"""
import asyncio, json, os, sys, time
from pathlib import Path
sys.path.insert(0, os.environ["JARVIS_TEST_UNIT_DIR"])
from test_capture_service import make_env, source_of
from jarvis.domain.capture import CaptureChannel

async def main(root, report):
    env = await make_env(Path(root), flush_interval_s=0.2, fsync_interval_s=1.0)
    record = await env.service.start(CaptureChannel.AUDIO)
    source = source_of(env)
    out = open(report, "a", buffering=1)  # une ligne par tour, remise au système à chaque ligne
    while True:
        source.push(20)  # 3 200 octets toutes les 10 ms
        live = env.service.status().captures[0]
        out.write(json.dumps({"artifact_id": record.artifact_id, "reported": live.bytes_written,
                              "pushed": source.frames * 160}) + "\n")
        await asyncio.sleep(0.01)

asyncio.run(main(sys.argv[1], sys.argv[2]))
"""


def test_a_real_hard_kill_keeps_every_byte_the_status_reported(tmp_path):
    """Vrai processus enfant, vrai spool, vraie base ; `TerminateProcess` au milieu de l'écriture."""

    import json
    import subprocess
    import sys
    import time

    def last_line() -> dict | None:
        try:
            lines = report.read_text().split("\n")[:-1]  # la dernière ligne peut être coupée
        except OSError:
            return None
        return json.loads(lines[-1]) if lines else None

    unit = Path(__file__).resolve().parent
    report = tmp_path / "report.json"
    child_env = {**os.environ, "JARVIS_TEST_UNIT_DIR": str(unit), "PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONPATH": str(unit.parents[1])}
    child = subprocess.Popen([sys.executable, "-c", _CHILD, str(tmp_path / "root"), str(report)], env=child_env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 8.0
        seen = None
        while time.monotonic() < deadline:
            seen = last_line()
            if seen and seen["reported"] >= 64 * 1024:
                break
            if child.poll() is not None:
                pytest.fail(f"child died: {child.stderr.read().decode(errors='replace')[-800:]}")
            time.sleep(0.05)
        assert seen and seen["reported"] >= 64 * 1024, seen
        child.kill()  # TerminateProcess : aucun `finally`, aucun vidage de tampon
        child.wait(5)
        final = last_line()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(5)
        child.stderr.close()
    partial = tmp_path / "root" / "artifacts" / final["artifact_id"] / "source.bin.partial"
    on_disk = partial.stat().st_size
    assert on_disk >= final["reported"] > 0  # tout ce que le statut a annoncé a survécu
    # Perte bornée : au plus un tour de cadence (0,2 s ≈ 64 Ko ici) + le tampon du spool (64 Kio).
    assert final["pushed"] - on_disk <= 64 * 1024 + 20 * 160 * 25


# ------------------------------------------------------------------ base refusée pendant un arrêt (QA S5 MAJOR-2)


def _disk_full_on(env: Env, when) -> dict:  # noqa: ANN001
    """`update_capture` refusé (SQLite plein) tant que `when(previous, updated)` et `flags["on"]`."""

    flags = {"on": True, "refused": 0}
    real = env.repo.update_capture

    async def update(previous, updated, *, activity=()):  # noqa: ANN001
        if flags["on"] and when(previous, updated):
            flags["refused"] += 1
            cause = sqlite3.OperationalError("database or disk is full")
            raise CaptureStoreUnavailable("update_capture", f"OperationalError: {cause}") from cause
        return await real(previous, updated, activity=activity)

    env.repo.update_capture = update
    return flags


async def test_disk_full_while_stopping_keeps_the_capture_visible_and_a_later_stop_finishes_it(env):
    record = await env.service.start(AUDIO)
    source = source_of(env)
    flags = _disk_full_on(env, lambda previous, updated: updated.is_terminal)
    with pytest.raises(CaptureError) as caught:
        await env.service.stop(record.capture_id)
    assert (caught.value.code, caught.value.capture_id) == (CaptureErrorCode.STORAGE_FULL, record.capture_id)
    assert source.stop_calls == 1 and not source.running  # l'appareil est relâché malgré la base
    status = env.service.status()
    assert [r.capture_id for r in status.captures] == [record.capture_id]
    assert status.captures[0].state is CaptureState.STOPPING
    assert [(s.capture_id, s.error_code) for s in status.stuck] == [(record.capture_id, CaptureErrorCode.STORAGE_FULL)]
    assert status.to_payload()["stuck"][0]["error_code"] == "storage_full"
    assert (await env.service.get(record.capture_id)).state is CaptureState.STOPPING
    assert env.journal.of("core.capture.stop_stuck")[0]["code"] == "storage_full"
    with pytest.raises(CaptureError) as again:  # encore refusé : même code, toujours visible
        await env.service.stop(record.capture_id)
    assert again.value.code is CaptureErrorCode.STORAGE_FULL and env.service.status().stuck
    flags["on"] = False
    done = await env.service.stop(record.capture_id)  # la base revient : l'arrêt reprend où il en était
    assert (done.state, done.error_code, done.stop_reason) == (CaptureState.COMPLETE, None, StopReason.USER)
    assert done.bytes_written == FRAME and source.stop_calls == 1
    assert (await env.artifacts.get(record.artifact_id)).state is ArtifactState.COMPLETE
    assert env.service.status().captures == () and env.service.status().stuck == ()
    assert len(await env.events(ActivityKind.CAPTURE_STOPPED)) == 1


async def test_a_start_on_the_device_of_a_stuck_capture_replays_its_stop_first(env):
    record = await env.service.start(AUDIO)
    flags = _disk_full_on(env, lambda previous, updated: True)  # même `stopping` refusé
    with pytest.raises(CaptureError):
        await env.service.stop(record.capture_id)
    assert source_of(env, 0).stop_calls == 1
    with pytest.raises(CaptureError) as caught:  # base toujours pleine : le code du stockage, et qui bloque
        await env.service.start(AUDIO)
    assert (caught.value.code, caught.value.capture_id) == (CaptureErrorCode.STORAGE_FULL, record.capture_id)
    flags["on"] = False
    fresh = await env.service.start(AUDIO)
    assert fresh.state is CaptureState.ACTIVE and fresh.capture_id != record.capture_id
    old = await env.repo.get_capture(record.capture_id)
    assert (old.state, old.stop_reason) == (CaptureState.COMPLETE, StopReason.USER)
    assert [r.capture_id for r in env.service.status().captures] == [fresh.capture_id]


async def test_close_retries_a_stuck_stop_and_leaves_the_rest_to_recovery(tmp_path):
    env = await make_env(tmp_path)
    record = await env.service.start(AUDIO)
    source_of(env).push(2)
    flags = _disk_full_on(env, lambda previous, updated: updated.is_terminal)
    with pytest.raises(CaptureError):
        await env.service.stop(record.capture_id)
    await env.service.close()  # toujours refusé : journalisé, la ligne reste `stopping`
    assert env.journal.of("core.capture.close_failed")
    flags["on"] = False
    await env.state.close()
    second = await make_env(tmp_path, seed=False)
    try:
        report = await second.service.recover()
        assert report.complete == (record.capture_id,)  # payload et Artifact déjà finis avant la panne
        assert (await second.repo.get_capture(record.capture_id)).state is CaptureState.COMPLETE
    finally:
        await second.aclose()


# ------------------------------------------------------------------ reprise : une ligne ne bloque pas les autres


async def test_one_unreadable_open_row_never_blocks_the_recovery_of_the_others(tmp_path):
    first = await make_env(tmp_path)
    bad = await first.service.start(AUDIO)
    good = await first.service.start(SCREEN)
    await checkpoint(first.service)
    _die(first.service)
    await first.aclose()
    conn = sqlite3.connect(tmp_path / "state" / "jarvis.sqlite3")
    try:
        conn.execute("UPDATE captures SET data='{\"broken\": 1}' WHERE capture_id=?", (bad.capture_id,))
        conn.commit()
    finally:
        conn.close()
    second = await make_env(tmp_path, seed=False)
    try:
        report = await second.service.recover()
        assert report.unreadable == (bad.capture_id,) and report.partial == (good.capture_id,)
        assert (await second.repo.get_capture(good.capture_id)).state is CaptureState.PARTIAL
        assert second.journal.of("core.capture.recover_one_failed")[0]["capture_id"] == bad.capture_id
        assert second.journal.of("core.capture.recovery")[0]["unreadable"] == 1
        assert (await second.service.start(SCREEN)).state is CaptureState.ACTIVE  # appareil sain libéré
    finally:
        await second.aclose()


async def test_an_active_row_whose_artifact_was_already_complete_is_recovered_partial(tmp_path):
    first = await make_env(tmp_path)
    record = await first.service.start(AUDIO)
    run = first.service._runs[record.capture_id]
    run.durability.cancel()
    run.sink.finalize()
    await first.artifacts.finalize(record.artifact_id)  # mort juste après : ligne encore `active`
    first.service._runs.clear()
    first.service._holders.clear()
    await first.aclose()
    second = await make_env(tmp_path, seed=False)
    try:
        report = await second.service.recover()
        assert report.partial == (record.capture_id,)
        recovered = await second.repo.get_capture(record.capture_id)
        assert (recovered.state, recovered.error_code) == (CaptureState.PARTIAL, "recoverable_partial")
        assert (await second.artifacts.get(record.artifact_id)).state is ArtifactState.COMPLETE  # inchangé
        (gap,) = await second.events(ActivityKind.CAPTURE_GAP)
        assert gap.data["last_seen_source"] == "payload_write"
    finally:
        await second.aclose()


async def test_the_gap_dates_the_last_durable_write_not_the_activation(tmp_path):
    first = await make_env(tmp_path)
    record = await first.service.start(AUDIO)
    await checkpoint(first.service)
    _die(first.service)
    await first.aclose()
    partial = tmp_path / "artifacts" / record.artifact_id / "source.bin.partial"
    later = record.updated_at.timestamp() + 3600
    os.utime(partial, (later, later))  # dernière écriture une heure après l'activation
    second = await make_env(tmp_path, seed=False)
    try:
        await second.service.recover()
        (gap,) = await second.events(ActivityKind.CAPTURE_GAP)
        assert gap.data["last_seen_source"] == "payload_write"
        assert abs(datetime.fromisoformat(gap.data["last_seen_at"]).timestamp() - later) < 1
    finally:
        await second.aclose()


async def test_a_hung_repair_never_blocks_core_start(tmp_path):
    first = await make_env(tmp_path)
    record = await first.service.start(AUDIO)
    await checkpoint(first.service)
    _die(first.service)
    await first.aclose()
    release = threading.Event()

    class HungRepair:
        def repair(self, target: RepairTarget) -> RepairOutcome:
            release.wait(10)
            return RepairOutcome(repaired=False)

    second = await make_env(tmp_path, repairs={AUDIO: HungRepair()}, seed=False, repair_timeout_s=0.2)
    try:
        report = await asyncio.wait_for(second.service.recover(), 5)
        assert report.partial == (record.capture_id,) and report.repair_failed == (record.capture_id,)
        assert second.journal.of("core.capture.repair_timeout")[0]["capture_id"] == record.capture_id
        assert (await second.repo.get_capture(record.capture_id)).data["repair_failed"] is True
    finally:
        release.set()
        await second.aclose()


# ------------------------------------------------------------------ capture d'écran : toute issue est finie


async def test_a_screenshot_source_crash_fails_row_and_artifact_with_a_stable_code(tmp_path):
    class Crashing(FakeOneShotSource):
        async def capture(self):  # noqa: ANN201
            raise RuntimeError("driver crashed")

    env = await make_env(tmp_path, sources=FakeCaptureSources(one_shot={SCREEN: Crashing}))
    try:
        with pytest.raises(CaptureError) as caught:
            await env.service.screenshot()
        assert caught.value.code is CaptureErrorCode.SOURCE_UNAVAILABLE and "RuntimeError" in str(caught.value)
        record = await env.repo.get_capture(caught.value.capture_id)
        assert (record.state, record.error_code) == (CaptureState.FAILED, "source_unavailable")
        assert (await env.artifacts.get(record.artifact_id)).state is ArtifactState.FAILED
        assert await env.repo.open_capture_ids(limit=10) == ()
    finally:
        await env.aclose()


async def test_a_refused_screenshot_artifact_fails_the_row_without_leaving_it_open(env):
    async def refused(**kwargs):  # noqa: ANN003
        raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT, "registry refused")

    env.artifacts.create = refused
    with pytest.raises(CaptureError) as caught:
        await env.service.screenshot()
    assert caught.value.code is CaptureErrorCode.STORAGE_UNAVAILABLE
    record = await env.repo.get_capture(caught.value.capture_id)
    assert (record.state, record.error_code, record.artifact_id) == (CaptureState.FAILED, "storage_unavailable", None)
    assert await env.repo.open_capture_ids(limit=10) == ()


# ------------------------------------------------------------------ disque lent, arrêt bloqué, encodeur externe (QA S5 2)


def _slow_or_failing(made: list, **kwargs):  # noqa: ANN003, ANN202
    """Fabrique `payloads` de `make_env` qui garde le `FailingPayloads` créé (pour l'observer)."""

    def wrap(inner):  # noqa: ANN001, ANN202
        made.append(FailingPayloads(inner, **kwargs))
        return made[-1]

    return wrap


async def test_a_slow_disk_never_blocks_core_loop_while_a_capture_stops(tmp_path):
    made: list[FailingPayloads] = []
    env = await make_env(tmp_path, payloads=_slow_or_failing(made, sync_delay_s=0.6),
                         flush_interval_s=0.01, fsync_interval_s=0.0)
    try:
        record = await env.service.start(AUDIO)
        source_of(env).push(5)
        assert await asyncio.to_thread(made[0].syncing.wait, 5)  # un `fsync` lent est en vol (verrou du sink tenu)
        gaps: list[float] = []
        done = asyncio.Event()

        async def ticker() -> None:
            last = time.monotonic()
            while not done.is_set():
                await asyncio.sleep(0.01)
                now = time.monotonic()
                gaps.append(now - last)
                last = now

        tick = asyncio.create_task(ticker())
        started = time.monotonic()
        final = await env.service.stop(record.capture_id)
        elapsed = time.monotonic() - started
        done.set()
        await tick
        assert (final.state, final.bytes_written) == (CaptureState.COMPLETE, 6 * FRAME)
        assert elapsed >= 0.5  # l'arrêt a bien attendu le disque lent...
        assert max(gaps) < 0.1, max(gaps)  # ... sans jamais retenir la boucle de Core
    finally:
        await env.aclose()


async def test_a_stuck_stop_puts_the_last_bytes_on_disk_at_once(env):
    record = await env.service.start(AUDIO)
    source_of(env).push(3)
    run = env.service._runs[record.capture_id]
    path = run.sink._spool.path
    assert path.stat().st_size == 0  # encore dans le tampon du processus
    flags = _disk_full_on(env, lambda previous, updated: True)
    with pytest.raises(CaptureError):
        await env.service.stop(record.capture_id)
    assert run.payload is None  # payload pas finalisé : il le sera au rejeu...
    assert path.stat().st_size == 4 * FRAME  # ... mais une mort de Core d'ici là ne perd rien
    assert env.service.status().captures[0].bytes_written == 4 * FRAME
    flags["on"] = False


async def test_close_puts_a_left_open_capture_bytes_on_disk(tmp_path):
    env = await make_env(tmp_path)
    record = await env.service.start(AUDIO)
    source_of(env).push(3)
    path = env.service._runs[record.capture_id].sink._spool.path
    _disk_full_on(env, lambda previous, updated: True)
    await env.service.close()  # base refusée : la ligne reste ouverte, réconciliée au prochain démarrage
    assert env.journal.of("core.capture.close_failed")
    assert path.stat().st_size == 4 * FRAME
    await env.state.close()


class HandOverSource(FakeCaptureSource):
    """Écrivain externe (comme ffmpeg) : prend le `.partial` (`hand_over`) et y écrit lui-même."""

    def __init__(self) -> None:
        super().__init__(initial_frames=0)

    async def start(self, sink) -> None:  # noqa: ANN001
        await super().start(sink)
        with open(sink.hand_over(), "ab") as handle:
            handle.write(DEFAULT_FRAME)


@pytest.mark.parametrize("fail_sync", [None, errno.EACCES])
async def test_the_owner_fsyncs_an_external_encoder_file_and_a_refusal_is_logged_once_never_fatal(tmp_path,
                                                                                                fail_sync):
    made: list[FailingPayloads] = []
    env = await make_env(tmp_path, sources=FakeCaptureSources(continuous={SCREEN: HandOverSource}),
                         payloads=_slow_or_failing(made, fail_sync=fail_sync),
                         flush_interval_s=0.01, fsync_interval_s=0.0)
    try:
        record = await env.service.start(SCREEN)
        deadline = time.monotonic() + 5
        while made[0].sync_calls < 3 and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert made[0].sync_calls >= 3  # le fichier de l'encodeur est rouvert et `fsync` à chaque cadence
        assert env.service.status().captures[0].state is CaptureState.ACTIVE  # un refus n'arrête rien
        refusals = env.journal.of("core.capture.encoder_sync_refused")
        assert len(refusals) == (0 if fail_sync is None else 1)  # une fois par capture, pas à chaque tour
        final = await env.service.stop(record.capture_id)
        assert (final.state, final.error_code, final.bytes_written) == (CaptureState.COMPLETE, None, FRAME)
    finally:
        await env.aclose()

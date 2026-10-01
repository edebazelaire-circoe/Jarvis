"""Propriétaire des captures dans Core : cycle de vie, courses, pannes, reprise après mort de Core.

Handoff session-context-recording, Slice 05. Contrat : `docs/capture.md`.
Sources et stockage factices (`jarvis/adapters/fake_capture.py`), bases et
dossiers temporaires (`tmp_path`) seulement ; aucun appareil réel.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import errno
from pathlib import Path

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
from jarvis.core.capture_service import CaptureAssociation, CaptureOptions, CaptureService
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.artifacts import ArtifactKind, ArtifactState
from jarvis.domain.capture import (
    CaptureChannel, CaptureError, CaptureErrorCode, CaptureMode, CaptureState, StopReason, attach_artifact,
    new_capture, request_stop,
)
from jarvis.domain.session_activity import ActivityKind, ActivityQuery
from jarvis.domain.session_context import create_context
from jarvis.domain.v2 import utc_now
from jarvis.domain.workspace_board import default_board, open_session
from jarvis.ports.capture import RepairOutcome, RepairTarget

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
                   start_timeout_s: float = 2.0, stop_timeout_s: float = 2.0, seed: bool = True) -> Env:
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
                             diagnostics=journal, start_timeout_s=start_timeout_s, stop_timeout_s=stop_timeout_s)
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


async def test_the_store_itself_refuses_a_second_open_capture_on_a_device(env):
    stale = new_capture(channel=AUDIO, mode=CaptureMode.CONTINUOUS, source="fake", now=utc_now(),
                        jarvis_session_id=env.sid)
    await env.repo.insert_capture(stale)  # ligne d'une autre vie, pas en mémoire
    with pytest.raises(CaptureError) as caught:
        await env.service.start(AUDIO)
    assert (caught.value.code, caught.value.capture_id) == (CaptureErrorCode.ALREADY_ACTIVE, stale.capture_id)


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


def _die(service: CaptureService) -> None:
    """Mort brutale : le système ferme les fichiers ouverts, rien n'est finalisé ni écrit en base."""

    for run in service._runs.values():
        if run.sink is not None:
            run.sink._spool.close()
    service._runs.clear()
    service._holders.clear()


async def test_core_death_mid_capture_is_recovered_as_partial_after_repair_never_restarted(tmp_path):
    first = await make_env(tmp_path)
    record = await first.service.start(AUDIO)
    source_of(first).push(9)
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

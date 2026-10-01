"""Payloads d'Artifacts sur disque, service Core, reprise après arrêt brutal, activité des Sessions.

Handoff session-context-recording, Slice 04. Contrat : `docs/artifacts.md`
(*Payloads*, *Recovery*, *Deletion*, *Activity ledger*). Dossiers et bases
temporaires (`tmp_path`) seulement.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from jarvis.adapters.artifact_payloads import FileArtifactPayloads
from jarvis.adapters.sqlite_artifacts import SQLiteArtifactRepository
from jarvis.adapters.sqlite_session_activity import SQLiteActivityLedger
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.artifact_service import PAYLOAD_MISSING, RECOVERED, ArtifactService
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.artifacts import (
    ArtifactError, ArtifactErrorCode, ArtifactKind, ArtifactQuery, ArtifactRelationKind, ArtifactState,
)
from jarvis.domain.session_activity import ActivityKind, ActivityQuery
from jarvis.ports.artifacts import (
    PAYLOAD_CONFLICT, PAYLOAD_UNSAFE, ArtifactPayloadError, RelationDirection,
)

AID = "jart_0123456789abcdef"


def _junction(link: Path, target: Path) -> None:
    if sys.platform != "win32":
        os.symlink(target, link, target_is_directory=True)
        return
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


class Journal:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:  # noqa: ANN001
        self.lines.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[dict]:
        return [data for k, _, data in self.lines if k == kind]


# ------------------------------------------------------------------ disque


def test_spool_writes_a_partial_then_finalizes_atomically(tmp_path):
    payloads = FileArtifactPayloads(tmp_path)
    folder = tmp_path.resolve() / "artifacts" / AID
    with payloads.open_spool(AID, "source.wav") as spool:
        spool.write(b"RIFF....")
        spool.write(b"data")
        spool.write_at(4, b"\x0c\x00\x00\x00")
        spool.sync()
        # pendant l'écriture : seul le `.partial` existe, jamais un nom final incomplet
        assert sorted(p.name for p in folder.iterdir()) == ["source.wav.partial"]
        assert payloads.inspect(AID, "source.wav").final_bytes is None
        assert spool.finalize() == 12
    assert sorted(p.name for p in folder.iterdir()) == ["source.wav"]
    assert (folder / "source.wav").read_bytes() == b"RIFF\x0c\x00\x00\x00data"
    assert payloads.path_of(f"artifacts/{AID}/source.wav") == folder / "source.wav"
    with pytest.raises(ArtifactPayloadError) as caught:  # jamais d'écrasement
        payloads.write_payload(AID, "source.wav", b"x")
    assert caught.value.code == PAYLOAD_CONFLICT


def test_a_crashed_writer_leaves_its_partial_which_is_never_overwritten(tmp_path):
    payloads = FileArtifactPayloads(tmp_path)
    spool = payloads.open_spool(AID, "video.mp4")
    spool.write(b"\x00" * 100)
    spool.close()  # « arrêt brutal » : pas de finalize
    assert payloads.inspect(AID, "video.mp4").partial_bytes == 100
    with pytest.raises(ArtifactPayloadError) as caught:
        payloads.open_spool(AID, "video.mp4")
    assert caught.value.code == PAYLOAD_CONFLICT
    assert payloads.promote_partial(AID, "video.mp4") == 100
    info = payloads.inspect(AID, "video.mp4")
    assert (info.final_bytes, info.partial_bytes) == (100, None)
    with pytest.raises(ArtifactPayloadError):
        spool.write(b"x")  # fermé


def test_the_process_buffer_is_bounded_and_flushed_size_counts_only_what_left_the_process(tmp_path):
    from jarvis.adapters.artifact_payloads import SPOOL_BUFFER_BYTES

    payloads = FileArtifactPayloads(tmp_path)
    spool = payloads.open_spool(AID, "a.wav")
    partial = spool.path
    spool.write(b"\x01" * 1000)
    assert (spool.size, spool.flushed_size, partial.stat().st_size) == (1000, 0, 0)  # encore dans le processus
    spool.flush()
    assert (spool.flushed_size, partial.stat().st_size) == (1000, 1000)  # remis au système, sans `fsync`
    for _ in range(3):
        spool.write(b"\x02" * (SPOOL_BUFFER_BYTES // 2))
    assert spool.size - partial.stat().st_size <= SPOOL_BUFFER_BYTES  # jamais plus d'un tampon en mémoire
    spool.sync()
    assert spool.flushed_size == spool.size == partial.stat().st_size
    spool.write(b"\x03" * 10)
    spool.close()
    assert spool.flushed_size == spool.size  # la fermeture vide le tampon
    external = payloads.open_spool("jart_fedcba9876543210", "v.mp4")
    path = external.hand_over()
    path.write_bytes(b"\x00" * 7)  # l'encodeur externe écrit
    external.flush()  # rien à faire, jamais refusé
    assert external.flushed_size == external.size == 7


@pytest.mark.parametrize("refusals,succeeds", [(1, True), (3, True), (99, False)])
def test_a_brief_windows_refusal_to_open_the_renamed_payload_is_retried(tmp_path, monkeypatch, refusals, succeeds):
    """Cause des flakes S9 : `PermissionError` (errno 13) en ouvrant `source.wav` tout juste renommé."""

    from jarvis.adapters import artifact_payloads, file_replace

    monkeypatch.setattr(file_replace, "REPLACE_BACKOFF_S", 0.0)
    monkeypatch.setattr(file_replace, "REPLACE_BACKOFF_MAX_S", 0.0)
    payloads = FileArtifactPayloads(tmp_path)
    payloads.write_payload(AID, "source.wav", b"RIFF-and-data")
    left = [refusals]
    real_open = open

    def flaky_open(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if left[0]:
            left[0] -= 1
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(artifact_payloads, "open", flaky_open, raising=False)
    if succeeds:
        assert payloads.read_range(AID, "source.wav", 4, 4) == b"-and"
        return
    with pytest.raises(ArtifactPayloadError) as refused:
        payloads.read_range(AID, "source.wav", 0, 4)
    assert refused.value.code == "artifact_payload_failed" and isinstance(refused.value.__cause__, PermissionError)
    assert left[0] == 99 - file_replace.REPLACE_ATTEMPTS, "borné : autant d'essais qu'un renommage"


def test_write_at_cannot_grow_the_file(tmp_path):
    spool = FileArtifactPayloads(tmp_path).open_spool(AID, "a.wav")
    spool.write(b"abcd")
    with pytest.raises(ArtifactPayloadError):
        spool.write_at(2, b"xyz")
    spool.close()


@pytest.mark.parametrize("level", ["artifacts", "artifact"])
def test_a_junction_is_refused_and_nothing_is_written_outside(tmp_path, level):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    if level == "artifacts":
        _junction(root / "artifacts", outside)
    else:
        (root / "artifacts").mkdir()
        _junction(root / "artifacts" / AID, outside)
    payloads = FileArtifactPayloads(root)
    for attempt in (lambda: payloads.open_spool(AID, "x.wav"), lambda: payloads.write_payload(AID, "x.png", b"1"),
                    lambda: payloads.inspect(AID, "x.wav"), lambda: payloads.remove_folder(AID)):
        with pytest.raises(ArtifactPayloadError) as caught:
            attempt()
        assert caught.value.code == PAYLOAD_UNSAFE
    assert list(outside.iterdir()) == []


def test_a_payload_that_is_a_link_or_folder_is_refused(tmp_path):
    payloads = FileArtifactPayloads(tmp_path)
    folder = payloads.ensure_folder(AID)
    (folder / "x.wav").mkdir()
    with pytest.raises(ArtifactPayloadError) as caught:
        payloads.inspect(AID, "x.wav")
    assert caught.value.code == PAYLOAD_UNSAFE
    with pytest.raises(ArtifactPayloadError) as caught:
        payloads.remove_folder(AID)  # entrée inattendue : rien n'est effacé à l'aveugle
    assert caught.value.code == PAYLOAD_UNSAFE and (folder / "x.wav").is_dir()


def test_invalid_ids_and_names_never_reach_the_disk(tmp_path):
    payloads = FileArtifactPayloads(tmp_path)
    for bad_id, name in (("jart_../x", "a"), ("JART_A", "a"), (AID, "../a"), (AID, "a.partial")):
        with pytest.raises(ArtifactError):
            payloads.open_spool(bad_id, name)
    assert not (tmp_path / "artifacts").exists()


# ------------------------------------------------------------------ service


@pytest.fixture
async def service(tmp_path):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    journal = Journal()
    svc = ArtifactService(SQLiteArtifactRepository(state), SQLiteActivityLedger(state), FileArtifactPayloads(tmp_path),
                          diagnostics=journal)
    svc.journal = journal  # type: ignore[attr-defined]
    try:
        yield svc
    finally:
        await state.close()


async def test_create_spool_finalize_query_with_activity_and_measured_size(service, tmp_path):
    artifact = await service.create(kind=ArtifactKind.AUDIO_RECORDING, source="capture.audio",
                                    payload_name="source.wav", mime_type="audio/wav", capture_id="jcap_1")
    with pytest.raises(ArtifactError) as caught:  # pas de `complete` sans payload final
        await service.finalize(artifact.artifact_id)
    assert caught.value.code is ArtifactErrorCode.INVALID_ARTIFACT
    with service.open_spool(artifact) as spool:
        spool.write(b"\x01" * 2048)
        spool.finalize()
    done = await service.finalize(artifact.artifact_id, duration_ms=1000)
    assert (done.state, done.size_bytes) == (ArtifactState.COMPLETE, 2048)
    transcript = await service.create(kind=ArtifactKind.TRANSCRIPT_SEGMENT, source="stt",
                                      origins=((ArtifactRelationKind.TRANSCRIBED_FROM, artifact.artifact_id),))
    await service.finalize(transcript.artifact_id, text="bonjour à tous")
    await service.enrich(artifact.artifact_id, {"speakers": 2})
    events = await service.activity(ActivityQuery())
    assert [e.kind for e in events] == [ActivityKind.ARTIFACT_CREATED, ActivityKind.ARTIFACT_FINALIZED,
                                        ActivityKind.ARTIFACT_CREATED, ActivityKind.ARTIFACT_FINALIZED,
                                        ActivityKind.ARTIFACT_ENRICHMENT_UPDATED]
    assert events[0].capture_ids == ("jcap_1",)
    assert events[2].artifact_ids == (transcript.artifact_id, artifact.artifact_id)
    dependents = await service.relations(artifact.artifact_id, RelationDirection.DEPENDENTS)
    assert [r.artifact_id for r in dependents] == [transcript.artifact_id]
    page = await service.query(ArtifactQuery(kinds=(ArtifactKind.AUDIO_RECORDING,)))
    assert [a.artifact_id for a in page.items] == [artifact.artifact_id]
    # aucun texte ni octet dans le ledger ni dans le journal : identifiants, états, codes
    dumped = json.dumps([e.to_payload() for e in events]) + json.dumps(service.journal.lines, default=str)
    assert "bonjour" not in dumped and "\\u0001" not in dumped


async def test_store_payload_for_a_short_capture(service):
    shot = await service.create(kind=ArtifactKind.SCREENSHOT, source="capture.screen", payload_name="screen.png")
    done = await service.store_payload(shot.artifact_id, b"\x89PNG....", width=1920, height=1080)
    assert (done.state, done.size_bytes, done.width) == (ArtifactState.COMPLETE, 8, 1920)
    assert Path(service.payload_path(done)).read_bytes() == b"\x89PNG...."
    with pytest.raises(ArtifactError) as caught:
        await service.store_payload(shot.artifact_id, b"again")
    assert caught.value.code is ArtifactErrorCode.ARTIFACT_NOT_PENDING


async def test_delete_removes_rows_then_folders_never_automatically(service, tmp_path):
    audio = await service.create(kind=ArtifactKind.AUDIO_RECORDING, source="a", payload_name="a.wav")
    await service.store_payload(audio.artifact_id, b"abc")
    derived = await service.create(kind=ArtifactKind.DERIVED, source="d", payload_name="d.txt",
                                   origins=((ArtifactRelationKind.DERIVED_FROM, audio.artifact_id),))
    await service.store_payload(derived.artifact_id, b"x")
    with pytest.raises(ArtifactError) as caught:
        await service.delete(audio.artifact_id)
    assert caught.value.code is ArtifactErrorCode.ARTIFACT_HAS_DEPENDENTS
    assert (tmp_path / "artifacts" / audio.artifact_id / "a.wav").exists()
    result = await service.delete(audio.artifact_id, cascade=True)
    assert set(result.artifact_ids) == {audio.artifact_id, derived.artifact_id} and result.orphan_folders == ()
    assert list((tmp_path / "artifacts").iterdir()) == []
    deleted = await service.activity(ActivityQuery(kinds=(ActivityKind.ARTIFACT_DELETED,)))
    assert len(deleted) == 2


async def test_a_folder_that_resists_is_reported_not_rolled_back(service, tmp_path):
    shot = await service.create(kind=ArtifactKind.SCREENSHOT, source="s", payload_name="s.png")
    await service.store_payload(shot.artifact_id, b"1")
    (tmp_path / "artifacts" / shot.artifact_id / "unexpected").mkdir()
    result = await service.delete(shot.artifact_id)
    assert result.orphan_folders == (shot.artifact_id,)
    assert await service._repo.get_artifact(shot.artifact_id) is None
    assert service.journal.of("core.artifact.folder_not_removed")[0]["code"] == PAYLOAD_UNSAFE


# ------------------------------------------------------------------ reprise


async def test_recovery_turns_crash_leftovers_into_partial_or_failed(service, tmp_path):
    with_bytes = await service.create(kind=ArtifactKind.AUDIO_RECORDING, source="a", payload_name="a.wav")
    spool = service.open_spool(with_bytes)
    spool.write(b"\x00" * 500)
    spool.close()  # arrêt brutal : `.partial` de 500 octets
    renamed = await service.create(kind=ArtifactKind.SCREEN_RECORDING, source="s", payload_name="s.mp4")
    spool = service.open_spool(renamed)
    spool.write(b"\x00" * 10)
    spool.finalize()  # renommé, mais la base n'a pas été mise à jour
    empty = await service.create(kind=ArtifactKind.AUDIO_RECORDING, source="a", payload_name="e.wav")
    service.open_spool(empty).close()  # `.partial` vide
    nothing = await service.create(kind=ArtifactKind.TRANSCRIPT, source="t")
    done = await service.create(kind=ArtifactKind.SCREENSHOT, source="x", payload_name="x.png")
    await service.store_payload(done.artifact_id, b"ok")

    report = await service.recover_pending()
    assert set(report.partial) == {with_bytes.artifact_id, renamed.artifact_id}
    assert set(report.failed) == {empty.artifact_id, nothing.artifact_id} and report.skipped == ()
    a = await service.get(with_bytes.artifact_id)
    assert (a.state, a.size_bytes, a.error_code) == (ArtifactState.PARTIAL, 500, RECOVERED)
    assert (tmp_path / "artifacts" / with_bytes.artifact_id / "a.wav").stat().st_size == 500
    assert (await service.get(renamed.artifact_id)).size_bytes == 10
    assert (await service.get(empty.artifact_id)).error_code == PAYLOAD_MISSING
    assert (await service.get(nothing.artifact_id)).error_code == "artifact_interrupted"
    assert (await service.get(done.artifact_id)).state is ArtifactState.COMPLETE
    finalized = [e for e in await service.activity(ActivityQuery(kinds=(ActivityKind.ARTIFACT_FINALIZED,)))
                 if e.data["recovered"]]
    assert len(finalized) == 4
    assert await service.recover_pending() == type(report)()  # idempotent


async def test_recovery_skips_an_unsafe_payload_and_keeps_core_starting(service, tmp_path):
    artifact = await service.create(kind=ArtifactKind.AUDIO_RECORDING, source="a", payload_name="a.wav")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    _junction(tmp_path / "artifacts" / artifact.artifact_id, outside)
    report = await service.recover_pending()
    assert report.skipped == (artifact.artifact_id,)
    assert (await service.get(artifact.artifact_id)).is_pending
    assert service.journal.of("core.artifact.recovery_skipped")[0]["code"] == PAYLOAD_UNSAFE


async def test_core_start_recovers_pending_artifacts_of_the_previous_life(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        artifact = await core.artifacts.create(kind=ArtifactKind.AUDIO_RECORDING, source="a", payload_name="a.wav")
        spool = core.artifacts.open_spool(artifact)
        spool.write(b"\x00" * 64)
        spool.close()
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path, diagnostics=(journal := Journal()))
    await core.start()
    try:
        recovered = await core.artifacts.get(artifact.artifact_id)
        assert (recovered.state, recovered.size_bytes) == (ArtifactState.PARTIAL, 64)
        assert journal.of("core.artifact.recovery")[0]["partial"] == 1
    finally:
        await core.stop()


# ------------------------------------------------------------------ activité automatique des Sessions


async def test_session_and_context_transitions_write_the_ledger_automatically(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        first = (await core.sessions.current()).session.jarvis_session_id
        first_ctx = (await core.sessions.current_context()).context.context_id
        second_ctx = (await core.sessions.create_context(title="B")).context.context_id
        await core.sessions.activate_context(first_ctx)
        await core.sessions.activate_context(first_ctx)  # déjà actif : rien
        _closed, view = await core.sessions.start_new_session()
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        await core.sessions.start()  # appel répété : pas de seconde reprise
        events = await core.artifacts.activity(ActivityQuery())
        new_sid = view.session.jarvis_session_id
        new_ctx = (await core.sessions.current_context()).context.context_id
        assert [(e.kind.value, e.jarvis_session_id, e.context_id) for e in events] == [
            ("session.opened", first, first_ctx), ("context.created", first, first_ctx),
            ("context.dormant", first, first_ctx), ("context.created", first, second_ctx),
            ("context.dormant", first, second_ctx), ("context.activated", first, first_ctx),
            ("context.dormant", first, first_ctx), ("session.closed", first, None),
            ("session.opened", new_sid, new_ctx), ("context.created", new_sid, new_ctx),
            ("session.resumed", new_sid, new_ctx),
        ]
        assert all(e.data["origin"] for e in events)
        tail = await core.artifacts.activity(ActivityQuery(after_seq=events[-3].seq, jarvis_session_id=new_sid))
        assert [e.kind for e in tail] == [ActivityKind.CONTEXT_CREATED, ActivityKind.SESSION_RESUMED]
    finally:
        await core.stop()


# ------------------------------------------------------------------ reprise QA Slice 04


def test_the_spool_buffer_is_exactly_64_kib(tmp_path):
    """Borne documentée (`docs/capture.md` › *Loss bounds*) : 65 536 octets, ni plus ni moins."""

    from jarvis.adapters.artifact_payloads import SPOOL_BUFFER_BYTES

    assert SPOOL_BUFFER_BYTES == 65536
    spool = FileArtifactPayloads(tmp_path).open_spool(AID, "a.wav")
    for _ in range(64):
        spool.write(bytes(1024))
    assert spool.path.stat().st_size == 0  # 64 Kio pile : tout reste dans le tampon du processus
    spool.write(bytes(1))
    assert spool.path.stat().st_size >= 65536  # un octet de plus : le tampon est remis au système
    spool.close()


def test_finalize_refuses_a_final_file_that_appeared_after_the_spool_opened(tmp_path):
    """A13 : `os.replace` écraserait un fichier final arrivé entre `open_spool` et `finalize`."""

    store = FileArtifactPayloads(tmp_path)
    spool = store.open_spool(AID, "a.wav")
    spool.write(b"mine")
    final = tmp_path / "artifacts" / AID / "a.wav"
    final.write_bytes(b"theirs")
    with pytest.raises(ArtifactPayloadError) as caught:
        spool.finalize()
    assert caught.value.code == PAYLOAD_CONFLICT
    assert final.read_bytes() == b"theirs"
    assert (tmp_path / "artifacts" / AID / "a.wav.partial").read_bytes() == b"mine"  # preuve gardée


@pytest.mark.skipif(sys.platform != "win32", reason="limite MAX_PATH de Windows")
def test_a_payload_path_above_max_path_is_refused_before_any_folder_is_created(tmp_path):
    from jarvis.adapters.safe_folders import WINDOWS_MAX_DIR_PATH, WINDOWS_MAX_FILE_PATH
    folder_tail = len("/artifacts/") + len(AID)
    root = tmp_path / ("r" * (WINDOWS_MAX_DIR_PATH - 8 - len(str(tmp_path)) - folder_tail - 1))  # dossier : 240
    root.mkdir()
    folder = root.resolve() / "artifacts" / AID
    assert len(str(folder)) <= WINDOWS_MAX_DIR_PATH  # le dossier seul passe
    name = "n" * 20 + ".wav"
    assert len(str(folder / f"{name}.partial")) > WINDOWS_MAX_FILE_PATH
    store = FileArtifactPayloads(root)
    with pytest.raises(ArtifactPayloadError) as caught:
        store.open_spool(AID, name)
    assert caught.value.code == "artifact_payload_failed" and "Windows limit" in str(caught.value)
    assert not (root / "artifacts").exists()
    with pytest.raises(ArtifactPayloadError):
        store.write_payload(AID, name, b"x")
    store.open_spool(AID, "a.wav").close()  # un nom court passe


async def test_finalize_complete_needs_the_final_file_even_after_progress_was_recorded(service):
    """A27 : une taille notée en cours d'acquisition n'est pas une preuve de payload final."""

    from jarvis.domain.artifacts import update_pending
    artifact = await service.create(kind=ArtifactKind.AUDIO_RECORDING, source="a", payload_name="a.wav")
    progressed = update_pending(artifact, now=artifact.updated_at, size_bytes=10)
    await service._repo.update_artifact(artifact, progressed)
    spool = service.open_spool(progressed)
    spool.write(b"0123456789")
    spool.close()  # `.partial` seulement
    with pytest.raises(ArtifactError) as caught:
        await service.finalize(artifact.artifact_id)
    assert caught.value.code is ArtifactErrorCode.INVALID_ARTIFACT
    assert (await service.get(artifact.artifact_id)).is_pending


async def test_recovery_pages_past_a_full_batch_of_unsafe_payloads(service, tmp_path):
    """Un lot entier (128) de payloads refusés en tête ne bloque plus la reprise des suivants."""

    from jarvis.core.artifact_service import RECOVERY_BATCH
    unsafe = []
    for _ in range(RECOVERY_BATCH + 1):
        artifact = await service.create(kind=ArtifactKind.AUDIO_RECORDING, source="a", payload_name="a.wav")
        (tmp_path / "artifacts" / artifact.artifact_id / "a.wav").mkdir(parents=True)  # dossier au lieu d'un fichier
        unsafe.append(artifact.artifact_id)
    good = await service.create(kind=ArtifactKind.AUDIO_RECORDING, source="a", payload_name="b.wav")
    spool = service.open_spool(good)
    spool.write(b"\x00" * 8)
    spool.close()
    report = await service.recover_pending()
    assert report.partial == (good.artifact_id,)
    assert report.skipped == tuple(unsafe)
    assert (await service.get(good.artifact_id)).state is ArtifactState.PARTIAL

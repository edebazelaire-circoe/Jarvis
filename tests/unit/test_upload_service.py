"""`UploadService` (chat Slice 07, `docs/chat.md` › *Attachments*) sur un vrai Core (SQLite sous `tmp_path`).

Les corps sont des lecteurs factices qui **génèrent** leurs octets morceau par
morceau (`StreamedBody`) : aucun test n'alloue le fichier entier en mémoire.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from jarvis.adapters.artifact_payloads import FileArtifactPayloads
from jarvis.core.artifact_service import ArtifactService
from jarvis.core.upload_service import UploadRefused, UploadService, upload_view
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery, ArtifactState
from jarvis.domain.uploads import UploadBounds, upload_artifact_id

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
UID = "0b6c1f0e-1111-4222-8333-444455556666"


class Diagnostics:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):  # noqa: ANN001
        self.events.append((kind, message, dict(data or {})))


class StreamedBody:
    """`read(n)` d'un corps de `total` octets générés (motif déterministe), coupé après `fail_after` si dit."""

    def __init__(self, total: int, *, seed: int = 7, fail_after: int | None = None,
                 gate: asyncio.Event | None = None, gate_after: int = 0) -> None:
        self.total, self.seed, self.fail_after, self.gate, self.gate_after = total, seed, fail_after, gate, gate_after
        self.sent = 0
        self.digest = hashlib.sha256()

    async def read(self, n: int) -> bytes:
        if self.gate is not None and self.sent >= self.gate_after:
            await self.gate.wait()
        if self.fail_after is not None and self.sent >= self.fail_after:
            raise ConnectionResetError("client went away")
        size = min(n, self.total - self.sent)
        if size <= 0:
            return b""
        start = self.sent
        chunk = bytes((self.seed + start + i) % 251 for i in range(size))
        self.sent += size
        self.digest.update(chunk)
        return chunk


class BytesBody:
    def __init__(self, data: bytes, piece: int = 7000) -> None:
        self.data, self.piece, self.offset = data, piece, 0

    async def read(self, n: int) -> bytes:
        chunk = self.data[self.offset:self.offset + min(n, self.piece)]
        self.offset += len(chunk)
        return chunk


@pytest.fixture
async def core(tmp_path):
    diagnostics = Diagnostics()
    app = JarvisCoreApplication(data_root=tmp_path / "data", diagnostics=diagnostics)
    await app.start()
    app.test_diagnostics = diagnostics
    try:
        yield app
    finally:
        await app.stop()


def bounded(core, max_bytes: int) -> None:
    core.uploads._bounds = lambda: UploadBounds(max_bytes=max_bytes, max_attachments=10)


async def put(core, body, *, uid: str = UID, name: str | None = "photo.png", content_length: int | None = None,
              agent: str | None = "claude", declared: str | None = "image/png"):
    return await core.uploads.put(client_upload_id=uid, purpose="chat", agent=agent, declared_mime=declared,
                                  name_header=name, content_length=content_length, read=body.read)


def folder(core, artifact_id: str) -> Path:
    return core.artifacts._payloads.root() / artifact_id


async def uploads_of(core) -> list:
    page = await core.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.UPLOAD,), limit=50))
    return list(page.items)


async def test_a_png_is_stored_complete_with_its_sniffed_type_and_metadata(core):
    outcome = await put(core, BytesBody(PNG), name="Ph%C3%B6to%20finale.PNG", content_length=len(PNG))
    artifact = outcome.artifact
    session = (await core.sessions.current()).session
    assert outcome.replayed is False and artifact.state is ArtifactState.COMPLETE
    assert artifact.artifact_id == upload_artifact_id(UID) and artifact.kind is ArtifactKind.UPLOAD
    assert (artifact.mime_type, artifact.size_bytes, artifact.payload_name) == ("image/png", len(PNG), "upload.png")
    assert artifact.jarvis_session_id == session.jarvis_session_id and artifact.context_id
    assert artifact.source == "chat"
    assert dict(artifact.metadata) == {"original_name": "Phöto finale.PNG", "declared_mime": "image/png",
                                       "provenance": "chat_attachment", "client_upload_id": UID,
                                       "brain_readable": True, "sha256": hashlib.sha256(PNG).hexdigest()}
    files = sorted(p.name for p in folder(core, artifact.artifact_id).iterdir())
    assert files == ["upload.png"] and (folder(core, artifact.artifact_id) / "upload.png").read_bytes() == PNG
    view = upload_view(artifact)
    assert "path" not in view and "payload_ref" not in view and str(core.artifacts._payloads.root()) not in str(view)


async def test_declared_type_and_lying_extension_lose_to_the_sniffed_bytes(core):
    zip_bytes = b"PK\x03\x04" + b"\x01" * 100
    artifact = (await put(core, BytesBody(zip_bytes), name="rapport.pdf", declared="application/pdf")).artifact
    assert (artifact.mime_type, artifact.payload_name) == ("application/octet-stream", "upload.bin")
    assert artifact.metadata["brain_readable"] is False and artifact.metadata["declared_mime"] == "application/pdf"


async def test_codex_reads_nothing(core):
    artifact = (await put(core, BytesBody(PNG), agent="codex")).artifact
    assert artifact.metadata["brain_readable"] is False


async def test_bound_exceeded_in_flow_fails_without_final_file_nor_partial(core):
    bounded(core, 200_000)
    body = StreamedBody(10_000_000)  # announced by nobody (chunked): the bound is held chunk by chunk
    with pytest.raises(UploadRefused) as refused:
        await put(core, body)
    assert (refused.value.status, refused.value.code) == (413, "upload_too_large")
    assert body.sent <= 200_000 + 64 * 1024, "reading stopped right after the bound"
    [artifact] = await uploads_of(core)
    assert artifact.state is ArtifactState.FAILED and artifact.error_code == "upload_too_large"
    assert not folder(core, artifact.artifact_id).exists()


async def test_content_length_above_the_bound_is_refused_before_reading(core):
    bounded(core, 1000)
    body = StreamedBody(5000)
    with pytest.raises(UploadRefused) as refused:
        await put(core, body, content_length=5000)
    assert (refused.value.status, refused.value.code, body.sent) == (413, "upload_too_large", 0)
    assert await uploads_of(core) == []


async def test_a_short_body_is_incomplete_and_failed(core):
    with pytest.raises(UploadRefused) as refused:
        await put(core, StreamedBody(500), content_length=1000)
    assert (refused.value.status, refused.value.code) == (400, "upload_incomplete")
    [artifact] = await uploads_of(core)
    assert (artifact.state, artifact.error_code) == (ArtifactState.FAILED, "upload_incomplete")
    assert not folder(core, artifact.artifact_id).exists()


async def test_a_body_cut_mid_stream_is_incomplete_and_leaves_no_partial(core):
    with pytest.raises(UploadRefused) as refused:
        await put(core, StreamedBody(1_000_000, fail_after=300_000))
    assert refused.value.code == "upload_incomplete" and refused.value.artifact.state is ArtifactState.FAILED
    assert not folder(core, refused.value.artifact.artifact_id).exists()


async def test_a_body_cut_before_the_first_bytes_writes_nothing(core):
    with pytest.raises(UploadRefused) as refused:
        await put(core, StreamedBody(1000, fail_after=0))
    assert refused.value.code == "upload_incomplete" and await uploads_of(core) == []


async def test_an_empty_file_is_refused_and_writes_nothing(core):
    with pytest.raises(UploadRefused) as refused:
        await put(core, BytesBody(b""))
    assert (refused.value.status, refused.value.code) == (400, "upload_empty")
    assert await uploads_of(core) == []


async def test_identical_replay_returns_the_same_artifact_never_a_double(core):
    first = await put(core, StreamedBody(300_000))
    again = await put(core, StreamedBody(300_000), content_length=300_000)
    assert again.replayed is True and again.artifact == first.artifact
    assert len(await uploads_of(core)) == 1


@pytest.mark.parametrize("body,length", [(lambda: StreamedBody(300_000, seed=9), None),  # same size, other bytes
                                         (lambda: StreamedBody(300_001), None),          # one byte more
                                         (lambda: StreamedBody(299_999), None),
                                         (lambda: StreamedBody(10), 10)])                # announced size differs
async def test_replay_with_other_bytes_is_a_conflict(core, body, length):
    first = await put(core, StreamedBody(300_000))
    with pytest.raises(UploadRefused) as refused:
        await put(core, body(), content_length=length)
    assert (refused.value.status, refused.value.code) == (409, "upload_conflict")
    assert await core.artifacts.get(first.artifact.artifact_id) == first.artifact


async def test_a_replay_after_a_failed_attempt_is_a_conflict(core):
    with pytest.raises(UploadRefused):
        await put(core, StreamedBody(1000), content_length=2000)
    with pytest.raises(UploadRefused) as refused:
        await put(core, StreamedBody(1000))
    assert (refused.value.status, refused.value.code) == (409, "upload_conflict")


async def test_a_concurrent_upload_of_the_same_id_is_in_progress(core):
    gate = asyncio.Event()
    first = asyncio.create_task(put(core, StreamedBody(200_000, gate=gate, gate_after=100_000)))
    await asyncio.sleep(0.2)
    with pytest.raises(UploadRefused) as refused:
        await put(core, StreamedBody(200_000))
    assert (refused.value.status, refused.value.code) == (409, "upload_in_progress")
    # Même refus depuis un autre processus : la ligne `pending` suffit, sans le verrou en mémoire.
    core.uploads._active.clear()
    with pytest.raises(UploadRefused) as refused:
        await put(core, StreamedBody(200_000))
    assert refused.value.code == "upload_in_progress"
    gate.set()
    assert (await first).artifact.state is ArtifactState.COMPLETE


async def test_a_partial_left_there_is_never_overwritten(core):
    artifact_id = upload_artifact_id(UID)
    target = folder(core, artifact_id)
    target.mkdir(parents=True)
    (target / "upload.png.partial").write_bytes(b"evidence")
    with pytest.raises(UploadRefused) as refused:
        await put(core, BytesBody(PNG))
    assert (refused.value.status, refused.value.code) == (503, "upload_storage_failed")
    assert (target / "upload.png.partial").read_bytes() == b"evidence"
    assert (await core.artifacts.get(artifact_id)).state is ArtifactState.FAILED


async def test_a_path_beyond_max_path_is_a_coded_storage_failure(core, tmp_path):
    deep = tmp_path / ("d" * 120) / ("e" * 120)
    artifacts = ArtifactService(core.artifacts._repo, core.artifacts._ledger, FileArtifactPayloads(deep))
    service = UploadService(artifacts, association=core._upload_association, bounds=core.uploads._bounds,
                            artifacts_root=deep / "artifacts")
    with pytest.raises(UploadRefused) as refused:
        await service.put(client_upload_id=UID, purpose="chat", agent="claude", declared_mime=None,
                          name_header="a.png", content_length=None, read=BytesBody(PNG).read)
    assert (refused.value.status, refused.value.code) == (503, "upload_storage_failed")
    assert (await artifacts.get(upload_artifact_id(UID))).state is ArtifactState.FAILED


@pytest.mark.parametrize("kwargs,code", [
    ({"purpose": "board"}, "invalid_request"), ({"purpose": "other"}, "invalid_request"),
    ({"client_upload_id": "x"}, "invalid_request"), ({"agent": "gpt"}, "invalid_request"),
    ({"name_header": "%FF.txt"}, "upload_name_invalid"), ({"name_header": "a" * 300}, "upload_name_invalid"),
])
async def test_refusals_before_reading(core, kwargs, code):
    args = {"client_upload_id": UID, "purpose": "chat", "agent": "claude", "declared_mime": None,
            "name_header": "a.png", "content_length": None, "read": BytesBody(PNG).read, **kwargs}
    with pytest.raises(UploadRefused) as refused:
        await core.uploads.put(**args)
    assert (refused.value.status, refused.value.code) == (400, code)
    assert await uploads_of(core) == []


async def test_a_pending_upload_from_a_dead_core_is_failed_without_payload(core):
    session = (await core.sessions.current()).session
    artifact = await core.artifacts.create(kind=ArtifactKind.UPLOAD, source="chat",
                                           jarvis_session_id=session.jarvis_session_id, payload_name="upload.png",
                                           artifact_id=upload_artifact_id(UID),
                                           metadata={"provenance": "chat_attachment"})
    spool = core.artifacts.open_spool(artifact)
    spool.write(b"half a file")
    spool.close()
    report = await core.artifacts.recover_pending(owned=core.uploads.owns)
    assert artifact.artifact_id not in report.partial and artifact.artifact_id not in report.failed
    assert await core.uploads.recover() == 1
    recovered = await core.artifacts.get(artifact.artifact_id)
    assert (recovered.state, recovered.error_code) == (ArtifactState.FAILED, "upload_interrupted")
    assert not folder(core, artifact.artifact_id).exists()


async def test_the_journal_never_carries_the_original_name(core):
    await put(core, BytesBody(PNG), name="secret%20dossier%20m%C3%A9dical.png")
    with pytest.raises(UploadRefused):
        await put(core, StreamedBody(10), uid="another-upload-id-1", name="secret%20dossier%20m%C3%A9dical.zip",
                  content_length=20)
    text = repr(core.test_diagnostics.events)
    assert "secret" not in text and "médical" not in text
    kinds = {kind for kind, _, _ in core.test_diagnostics.events}
    assert {"core.upload.stored", "core.upload.refused"} <= kinds

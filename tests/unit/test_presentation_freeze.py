"""Références vivantes (résolution Core) et gel en paquet autonome (Remotion Slice 09).

Vrai registre SQLite, vrai magasin de mémoire de Board, vrai Studio de fichiers, vrai `PrefabService` avec une vraie source
Remotion, vrai spool d'`ArtifactService` (`tmp_path`). Contrat : `docs/presentation-live-refs.md`.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

import pytest

from jarvis.adapters.artifact_payloads import FileArtifactPayloads
from jarvis.adapters.board_memory_store import FileBoardMemoryStore
from jarvis.adapters.file_prefab_library import FilePrefabLibrary
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.adapters.sqlite_artifacts import SQLiteArtifactRepository
from jarvis.adapters.sqlite_board_artifact_links import SQLiteBoardArtifactLinks
from jarvis.adapters.sqlite_session_activity import SQLiteActivityLedger
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.artifact_service import ArtifactService
from jarvis.core.prefab_service import PrefabService
from jarvis.core.presentation_artifacts import PresentationArtifacts
from jarvis.core.presentation_live_refs import LiveRefResolver
from jarvis.core.presentation_snapshot_packager import PACKAGE_FAILED, PresentationPackager
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery, ArtifactState
from jarvis.domain.board_memory import BoardMemoryPath
from jarvis.domain.presentation_live_refs import (
    LIVE_REFS_FORMAT, LIVE_REFS_PATH, MAX_BINARY_BYTES, MAX_TEXT_BYTES, LiveRef, LiveRefError, LiveRefErrorCode as E,
    LiveRefState as S, parse_live_ref,
)
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.workspace_board import default_board, open_session
from jarvis.ports.board_memory import WriteMode
from tests.fakes.prefabs import install_version
from tests.fakes.remotion_scene import PNG_1X1, scene_candidate, scene_files

T0 = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)
SID = "jsess_0123456789abcdef"
SCENE_PREFAB = "presentation-studio.p000000000001.s000000000001"
SCENE_ID = "pss_000000000001"
NOTE = "board:default/memory/notes/a.md"


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.rows.append((kind, level))


def declaration(*refs: tuple[str, str]) -> str:
    return json.dumps({"format": LIVE_REFS_FORMAT, "refs": [{"name": n, "ref": r} for n, r in refs]})


class World:
    pass


@pytest.fixture
async def world(tmp_path):
    w = World()
    w.tmp_path = tmp_path
    w.state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await w.state.initialize()
    boards = SQLiteBoardRepository(w.state)
    first = default_board(now=T0)
    await boards.save_board(first)
    await boards.save_session(open_session(first, now=T0, jarvis_session_id=SID))
    for name in ("data", "studio", "package", "prefabs", "boards_root"):
        (tmp_path / name).mkdir()
    w.sink = Sink()
    w.boards = boards
    w.artifacts = ArtifactService(SQLiteArtifactRepository(w.state), SQLiteActivityLedger(w.state),
                                  FileArtifactPayloads(tmp_path / "data"), diagnostics=w.sink)
    w.links = SQLiteBoardArtifactLinks(w.state)
    w.memory = FileBoardMemoryStore(tmp_path / "boards_root")
    w.studio = PresentationStudioService(FilePresentationStudioStore(tmp_path / "studio"))
    install_version(tmp_path / "package", "jarvis.counter", title="Base counter")
    w.prefabs = PrefabService(FilePrefabLibrary(tmp_path / "package", tmp_path / "prefabs"), diagnostics=w.sink,
                              clock=lambda: T0)
    w.snapshots = PresentationArtifacts(w.studio, w.artifacts, w.links, diagnostics=w.sink)
    w.resolver = LiveRefResolver(boards=boards, memory=w.memory, artifacts=w.artifacts, links=w.links, diagnostics=w.sink)
    w.packager = PresentationPackager(
        studio=w.studio, artifacts=w.artifacts, snapshots=w.snapshots, prefabs=w.prefabs, resolver=w.resolver,
        runtime=lambda: {"remotion_version": "4.0.534", "compiler_sha256": "c" * 64}, clock=lambda: T0, diagnostics=w.sink)
    w.write_note("notes/a.md", "# Live note\n")
    w.photo = await w.add_artifact(ArtifactKind.SCREENSHOT, "image/png", PNG_1X1)
    w.pid, w.vid = await w.new_presentation([("note", NOTE), ("photo", f"board:default/artifact/{w.photo}")])
    try:
        yield w
    finally:
        await w.state.close()


def _write_note(self, path: str, text: str, mode: WriteMode = WriteMode.REPLACE) -> None:
    self.memory.write("default", BoardMemoryPath.parse(path), text, mode=mode)


async def _add_artifact(self, kind: ArtifactKind, mime: str | None, data: bytes, name: str = "item.bin") -> str:
    artifact = await self.artifacts.create(kind=kind, source="test", jarvis_session_id=SID, payload_name=name, mime_type=mime)
    await self.artifacts.store_payload(artifact.artifact_id, data)
    return artifact.artifact_id


async def _new_presentation(self, refs, *, prefab_id: str = SCENE_PREFAB) -> tuple[str, str]:
    files = scene_files()
    files[LIVE_REFS_PATH] = declaration(*refs)
    published = await self.prefabs.save(scene_candidate(prefab_id, files=files), actor="user")
    created = await self.studio.create({"title": "Atelier"})
    pid, vid = created.presentation.presentation_id, created.presentation.active_variant_id
    variant = created.variants[0].to_document()
    await self.studio.save_variant(pid, vid, {
        "expected_revision": variant["revision"], "title": variant["title"],
        "scenes": [{"scene_id": SCENE_ID, "prefab": {"id": prefab_id, "version": published.version}}],
        "art_direction_id": None, "score_id": None})
    return pid, vid


async def _revisions(self, pid: str | None = None) -> tuple[int, int]:
    view = await self.studio.get(pid or self.pid)
    return view.presentation.revision, view.variants[0].revision


async def _freeze(self) -> dict:
    p, v = await self.revisions()
    return await self.packager.freeze(self.pid, self.vid, expected_presentation_revision=p, expected_variant_revision=v)


async def _snapshot_count(self) -> int:
    page = await self.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_SNAPSHOT,), limit=50))
    return len(page.items)


for _fn in (_write_note, _add_artifact, _new_presentation, _revisions, _freeze, _snapshot_count):
    setattr(World, _fn.__name__.lstrip("_"), _fn)


def ref(value: str, name: str = "x") -> LiveRef:
    return parse_live_ref(name, value)


# ------------------------------------------------------------------ resolver (edit time)


async def test_a_note_and_an_image_resolve_with_their_hashes(world):
    note = await world.resolver.resolve(ref(NOTE))
    photo = await world.resolver.resolve(ref(f"board:default/artifact/{world.photo}"))
    assert (note.state, note.mime, note.data) == (S.OK, "text/markdown", b"# Live note\n")
    assert note.sha256 == hashlib.sha256(b"# Live note\n").hexdigest()
    assert (photo.state, photo.mime, photo.data) == (S.OK, "image/png", PNG_1X1)
    assert ("core.live_refs.unresolved", "warning") not in world.sink.rows


async def test_a_live_change_is_visible_as_changed_not_hidden(world):
    seen = (await world.resolver.resolve(ref(NOTE))).sha256
    world.write_note("notes/a.md", "# Edited\n")
    moved = await world.resolver.resolve(ref(NOTE), expected_sha256=seen)
    assert moved.state is S.CHANGED and moved.data == b"# Edited\n" and moved.usable
    same = await world.resolver.resolve(ref(NOTE), expected_sha256=moved.sha256)
    assert same.state is S.OK


async def test_missing_items_are_typed_states_not_exceptions(world):
    gone = await world.resolver.resolve(ref("board:default/memory/notes/nope.md"))
    assert gone.state is S.MISSING and gone.data is None and not gone.usable
    assert (await world.resolver.resolve(ref("board:board_nowhere/memory/notes/a.md"))).state is S.BOARD_MISSING
    assert (await world.resolver.resolve(ref("board:default/artifact/jart_" + "0" * 32))).state is S.MISSING
    world.memory.delete("default", BoardMemoryPath.parse("notes/a.md"))
    assert (await world.resolver.resolve(ref(NOTE))).state is S.MISSING
    assert ("core.live_refs.unresolved", "warning") in world.sink.rows


async def test_an_artifact_must_be_linked_to_that_very_board(world):
    first = await world.boards.get_board("default")
    other = first.__class__(board_id="board_other", title="Autre", created_at=T0, updated_at=T0)
    await world.boards.save_board(other)
    item = await world.resolver.resolve(ref(f"board:board_other/artifact/{world.photo}"))
    assert item.state is S.NOT_ON_BOARD and item.data is None


async def test_unsafe_or_oversized_content_is_refused(world):
    svg = await world.add_artifact(ArtifactKind.SCREENSHOT, "image/svg+xml", b"<svg onload='x()'/>")
    fake_png = await world.add_artifact(ArtifactKind.SCREENSHOT, "image/png", b"<svg onload='x()'/>")
    audio = await world.add_artifact(ArtifactKind.AUDIO_RECORDING, "audio/wav", b"RIFF....WAVE")
    huge = await world.add_artifact(ArtifactKind.SCREENSHOT, "image/png", PNG_1X1 + b"\0" * MAX_BINARY_BYTES)
    binary_text = await world.add_artifact(ArtifactKind.DESCRIPTION, "text/plain", b"\xff\xfe\x00bad")
    for artifact_id, state in ((svg, S.NOT_ALLOWED), (fake_png, S.NOT_ALLOWED), (audio, S.NOT_ALLOWED), (huge, S.TOO_LARGE),
                               (binary_text, S.NOT_TEXT)):
        item = await world.resolver.resolve(ref(f"board:default/artifact/{artifact_id}"))
        assert (item.state, item.data) == (state, None), artifact_id
    # a text item above the bound, in Board memory (written in two appends: one write is capped)
    world.write_note("notes/big.md", "x" * (MAX_TEXT_BYTES // 2 + 1), WriteMode.REPLACE)
    world.write_note("notes/big.md", "x" * (MAX_TEXT_BYTES // 2 + 1), WriteMode.APPEND)
    assert (await world.resolver.resolve(ref("board:default/memory/notes/big.md"))).state is S.TOO_LARGE
    world.write_note("notes/a.exe", "MZ")
    assert (await world.resolver.resolve(ref("board:default/memory/notes/a.exe"))).state is S.NOT_ALLOWED


async def test_a_presentation_artifact_is_never_a_usable_item(world):
    await world.freeze()
    video = await world.add_artifact(ArtifactKind.PRESENTATION_VIDEO, "video/mp4", b"\0\0\0\x18ftypmp42")
    item = await world.resolver.resolve(ref(f"board:default/artifact/{video}"))
    assert item.state is S.NOT_ALLOWED and "presentation_video" in item.message


async def test_the_total_of_a_set_is_bounded(world):
    big = await world.add_artifact(ArtifactKind.SCREENSHOT, "image/png", PNG_1X1 + b"\0" * (MAX_BINARY_BYTES - 200))
    refs = [ref(f"board:default/artifact/{big}", f"p{i}") for i in range(5)]
    out = await world.resolver.resolve_all(refs)
    assert [item.state for item in out.values()] == [S.OK] * 4 + [S.TOO_LARGE]


async def test_a_store_failure_is_reported_never_swallowed(world):
    class Broken:
        async def get_board(self, board_id):
            raise OSError("C:\\secret\\disk path")

    resolver = LiveRefResolver(boards=Broken(), memory=world.memory, artifacts=world.artifacts, links=world.links,
                               diagnostics=world.sink)
    item = await resolver.resolve(ref(NOTE))
    assert item.state is S.UNREADABLE and "secret" not in item.message and "C:" not in item.message
    assert ("core.live_refs.unreadable", "warning") in world.sink.rows


# ------------------------------------------------------------------ scene data for the sandbox


async def test_scene_data_is_resolved_core_side_and_only_data_crosses(world):
    data = await world.packager.scene_live_data(world.pid, world.vid, SCENE_ID)
    assert [row["state"] for row in data["refs"]] == ["ok", "ok"]
    assert data["payload"]["note"]["text"] == "# Live note\n"
    assert data["payload"]["photo"]["file"] == "live/photo.png"
    text = json.dumps(data["payload"])
    for leaked in ("board:", "default", "notes/a.md", str(world.tmp_path), world.photo, "jart_"):
        assert leaked not in text, leaked
    world.memory.delete("default", BoardMemoryPath.parse("notes/a.md"))
    again = await world.packager.scene_live_data(world.pid, world.vid, SCENE_ID)
    assert again["payload"]["note"] == {"state": "missing", "message": "memory_not_found"}  # visible during edit, no raise


async def test_a_scene_can_not_ask_for_a_name_it_did_not_declare_or_another_presentation(world):
    other_pid, other_vid = await world.new_presentation([("secret", "board:default/memory/notes/a.md")],
                                                        prefab_id="presentation-studio.p000000000001.s000000000002")
    mine = await world.packager.scene_live_data(world.pid, world.vid, SCENE_ID)
    assert set(mine["payload"]) == {"note", "photo"}  # nothing from the other presentation's declaration
    assert "secret" not in json.dumps(mine)
    with pytest.raises(LiveRefError) as caught:
        await world.packager.scene_live_data(world.pid, world.vid, "pss_000000000099")
    assert caught.value.code is E.UNKNOWN
    with pytest.raises(LiveRefError) as caught:
        await world.packager.scene_live_data(world.pid, other_vid, SCENE_ID)  # a variant of ANOTHER presentation
    assert caught.value.code is E.UNKNOWN


async def test_a_cross_presentation_reference_in_a_source_refuses_the_freeze_and_the_edit_read(world):
    snapshot = await world.freeze()
    pid, vid = await world.new_presentation([("stolen", f"board:default/artifact/{snapshot['artifact_id']}")],
                                            prefab_id="presentation-studio.p000000000001.s000000000003")
    p, v = await world.revisions(pid)
    before = await world.snapshot_count()
    with pytest.raises(LiveRefError) as caught:
        await world.packager.freeze(pid, vid, expected_presentation_revision=p, expected_variant_revision=v)
    assert caught.value.code is E.CROSS_PRESENTATION
    with pytest.raises(LiveRefError):
        await world.packager.scene_live_data(pid, vid, SCENE_ID)
    assert await world.snapshot_count() == before


# ------------------------------------------------------------------ freeze


async def test_a_freeze_builds_a_verified_self_contained_package(world):
    done = await world.freeze()
    artifact = await world.artifacts.get(done["artifact_id"])
    assert artifact.state is ArtifactState.COMPLETE and done["created"] and not done["replayed"]
    package = await world.packager.read_snapshot(done["artifact_id"])
    # the recorded hash is the real sha256 of snapshot.zip on disk
    on_disk = world.artifacts.read_payload(artifact, 0, 1 << 26)
    assert hashlib.sha256(on_disk).hexdigest() == artifact.metadata["content_sha256"] == done["content_sha256"]
    manifest = package.manifest
    assert manifest["provenance"]["source_presentation_id"] == world.pid
    assert manifest["provenance"]["source_engine"] == "remotion"
    assert manifest["runtime"] == {"remotion_version": "4.0.534", "compiler_sha256": "c" * 64}
    (row,) = manifest["prefabs"]
    assert row["kind"] == "remotion" and row["engine"]["name"] == "remotion" and len(row["source_digest"]) == 64
    root = f"prefabs/{SCENE_PREFAB}/1"
    assert {f"{root}/src/Scene.tsx", f"{root}/src/lib/Title.tsx", f"{root}/public/dot.png", f"{root}/source.json",
            f"{root}/{LIVE_REFS_PATH}"} <= set(package.files)
    assert package.live(SCENE_PREFAB, 1, "note") == b"# Live note\n"
    assert package.live(SCENE_PREFAB, 1, "photo") == PNG_1X1
    assert {"presentation/presentation.json", "presentation/variant.json"} <= set(package.files)
    # no secret / machine path anywhere in the package
    blob = b"".join(package.files.values()) + json.dumps(dict(manifest)).encode()
    assert str(world.tmp_path).encode() not in blob and str(world.tmp_path).replace("\\", "/").encode() not in blob
    assert ("core.snapshot_packager.frozen", "info") in world.sink.rows


async def test_the_frozen_package_never_changes_when_the_board_changes_later(world):
    done = await world.freeze()
    artifact = await world.artifacts.get(done["artifact_id"])
    before = world.artifacts.read_payload(artifact, 0, 1 << 26)
    world.write_note("notes/a.md", "# CHANGED AFTER THE FREEZE\n")
    world.memory.delete("default", BoardMemoryPath.parse("notes/a.md"))
    await world.artifacts.delete(world.photo, cascade=True)
    live = await world.resolver.resolve(ref(NOTE))
    assert live.state is S.MISSING  # the Board really moved on
    package = await world.packager.read_snapshot(done["artifact_id"])  # replays with no Board item left
    assert package.live(SCENE_PREFAB, 1, "note") == b"# Live note\n"
    assert package.live(SCENE_PREFAB, 1, "photo") == PNG_1X1
    after = world.artifacts.read_payload(await world.artifacts.get(done["artifact_id"]), 0, 1 << 26)
    assert after == before


async def test_a_replayed_freeze_returns_the_same_snapshot_without_touching_the_board(world):
    first = await world.freeze()
    world.memory.delete("default", BoardMemoryPath.parse("notes/a.md"))  # a replay must not need the Board
    second = await world.freeze()
    assert second["replayed"] and not second["created"] and second["artifact_id"] == first["artifact_id"]
    assert second["content_sha256"] == first["content_sha256"] and await world.snapshot_count() == 1


async def test_a_stale_revision_is_refused_and_writes_nothing(world):
    p, v = await world.revisions()
    variant = (await world.studio.get(world.pid)).variants[0].to_document()
    await world.studio.save_variant(world.pid, world.vid, {
        "expected_revision": variant["revision"], "title": "Changed", "scenes": variant["scenes"],
        "art_direction_id": None, "score_id": None})
    with pytest.raises(PresentationStudioError) as caught:
        await world.packager.freeze(world.pid, world.vid, expected_presentation_revision=p, expected_variant_revision=v)
    assert caught.value.code is C.STALE_REVISION and await world.snapshot_count() == 0


@pytest.mark.parametrize("damage", ["memory_deleted", "artifact_deleted", "artifact_oversized", "memory_oversized",
                                    "board_deleted"])
async def test_an_unresolvable_live_reference_fails_the_freeze_and_leaves_no_package(world, damage):
    if damage == "memory_deleted":
        world.memory.delete("default", BoardMemoryPath.parse("notes/a.md"))
    elif damage == "artifact_deleted":
        await world.artifacts.delete(world.photo, cascade=True)
    elif damage == "artifact_oversized":
        world.photo = await world.add_artifact(ArtifactKind.SCREENSHOT, "image/png", PNG_1X1 + b"\0" * MAX_BINARY_BYTES)
        world.pid, world.vid = await world.new_presentation(
            [("photo", f"board:default/artifact/{world.photo}")], prefab_id="presentation-studio.p000000000001.s000000000004")
    elif damage == "memory_oversized":
        world.write_note("notes/a.md", "x" * (MAX_TEXT_BYTES // 2 + 1))
        world.write_note("notes/a.md", "x" * (MAX_TEXT_BYTES // 2 + 1), WriteMode.APPEND)
    else:
        world.pid, world.vid = await world.new_presentation(
            [("gone", "board:board_nowhere/memory/notes/a.md")], prefab_id="presentation-studio.p000000000001.s000000000005")
    with pytest.raises(LiveRefError) as caught:
        await world.freeze()
    assert caught.value.code is E.UNRESOLVED and caught.value.details
    assert all(row["state"] != "ok" for row in caught.value.details)
    assert str(world.tmp_path) not in json.dumps(caught.value.details) + str(caught.value)
    assert await world.snapshot_count() == 0  # nothing created, so nothing partial, nothing marked complete
    assert ("core.snapshot_packager.refused", "warning") in world.sink.rows


async def test_a_package_write_failure_fails_the_snapshot_and_never_completes_it(world, monkeypatch):
    def boom(spool, data):
        raise OSError("disk full")

    monkeypatch.setattr(PresentationPackager, "_spool_write", staticmethod(boom))
    with pytest.raises(OSError):
        await world.freeze()
    page = await world.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_SNAPSHOT,), limit=10))
    (only,) = page.items
    assert only.state is ArtifactState.FAILED and only.error_code == PACKAGE_FAILED
    monkeypatch.undo()
    retry = await world.freeze()  # the next attempt opens _a2: a failed one is evidence, never reused
    assert retry["artifact_id"].endswith("_a2") and retry["created"]


async def test_a_pending_snapshot_with_its_file_resumes_with_that_exact_file(world):
    p, v = await world.revisions()
    begun = await world.snapshots.begin_snapshot(world.pid, world.vid, expected_presentation_revision=p,
                                                 expected_variant_revision=v)
    # an earlier attempt wrote the file then died before finalize; the Board has moved since
    from jarvis.domain.presentation_snapshot_package import build_package
    data = build_package({"provenance": {}, "frozen_at": "x", "scenes": [], "prefabs": [], "live_refs": [], "runtime": None},
                         {"presentation/presentation.json": b"{}"})
    spool = world.artifacts.open_spool(begun["artifact"])
    spool.write(data)
    spool.finalize()
    world.memory.delete("default", BoardMemoryPath.parse("notes/a.md"))
    done = await world.freeze()
    assert done["content_sha256"] == hashlib.sha256(data).hexdigest() and not done["created"]
    assert (await world.artifacts.get(begun["artifact_id"])).state is ArtifactState.COMPLETE


async def test_a_tampered_package_is_refused_on_reopen(world):
    done = await world.freeze()
    artifact = await world.artifacts.get(done["artifact_id"])
    path = world.artifacts.payload_path(artifact)
    with open(path, "r+b") as handle:
        handle.seek(200)
        byte = handle.read(1)
        handle.seek(200)
        handle.write(bytes([byte[0] ^ 0xFF]))
    with pytest.raises(LiveRefError) as caught:
        await world.packager.read_snapshot(done["artifact_id"])
    assert caught.value.code is E.PACKAGE_INVALID


async def test_a_pending_or_failed_snapshot_is_not_readable_as_a_package(world):
    p, v = await world.revisions()
    begun = await world.snapshots.begin_snapshot(world.pid, world.vid, expected_presentation_revision=p,
                                                 expected_variant_revision=v)
    from jarvis.domain.artifacts import ArtifactError
    with pytest.raises(ArtifactError):
        await world.packager.read_snapshot(begun["artifact_id"])


async def test_html_scenes_are_frozen_too_without_live_references(world):
    class Html:
        async def manifest(self, prefab_id, version):
            return type("M", (), {"source": None})()

        async def bundle(self, prefab_id, version):
            return {"id": prefab_id, "version": version, "fingerprint": "f" * 64, "manifest": {"id": prefab_id},
                    "files": {"template.html": "<p>x</p>"}, "runtime": {"shim": "do not copy"}}

    packager = PresentationPackager(studio=world.studio, artifacts=world.artifacts, snapshots=world.snapshots, prefabs=Html(),
                                    resolver=world.resolver, clock=lambda: T0)
    p, v = await world.revisions()
    done = await packager.freeze(world.pid, world.vid, expected_presentation_revision=p, expected_variant_revision=v)
    package = await packager.read_snapshot(done["artifact_id"])
    assert package.manifest["prefabs"][0]["kind"] == "html" and package.manifest["live_refs"] == []
    assert b"do not copy" not in b"".join(package.files.values())

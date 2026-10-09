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
OK = {"default"}


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


async def _new_presentation(self, refs, *, prefab_id: str = SCENE_PREFAB, extra=None) -> tuple[str, str]:
    files = {**scene_files(), **(extra or {})}
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


async def _freeze(self, allowed=None) -> dict:
    p, v = await self.revisions()
    return await self.packager.freeze(self.pid, self.vid, expected_presentation_revision=p, expected_variant_revision=v,
                                      authorised_boards=OK if allowed is None else allowed)


async def _snapshot_count(self) -> int:
    page = await self.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_SNAPSHOT,), limit=50))
    return len(page.items)


for _fn in (_write_note, _add_artifact, _new_presentation, _revisions, _freeze, _snapshot_count):
    setattr(World, _fn.__name__.lstrip("_"), _fn)


def ref(value: str, name: str = "x") -> LiveRef:
    return parse_live_ref(name, value)


# ------------------------------------------------------------------ resolver (edit time)


async def test_a_note_and_an_image_resolve_with_their_hashes(world):
    note = await world.resolver.resolve(ref(NOTE), authorised_boards=OK)
    photo = await world.resolver.resolve(ref(f"board:default/artifact/{world.photo}"), authorised_boards=OK)
    assert (note.state, note.mime, note.data) == (S.OK, "text/markdown", b"# Live note\n")
    assert note.sha256 == hashlib.sha256(b"# Live note\n").hexdigest()
    assert (photo.state, photo.mime, photo.data) == (S.OK, "image/png", PNG_1X1)
    assert ("core.live_refs.unresolved", "warning") not in world.sink.rows


async def test_a_live_change_is_visible_as_changed_not_hidden(world):
    seen = (await world.resolver.resolve(ref(NOTE), authorised_boards=OK)).sha256
    world.write_note("notes/a.md", "# Edited\n")
    moved = await world.resolver.resolve(ref(NOTE), authorised_boards=OK, expected_sha256=seen)
    assert moved.state is S.CHANGED and moved.data == b"# Edited\n" and moved.usable
    same = await world.resolver.resolve(ref(NOTE), authorised_boards=OK, expected_sha256=moved.sha256)
    assert same.state is S.OK


async def test_missing_items_are_typed_states_not_exceptions(world):
    gone = await world.resolver.resolve(ref("board:default/memory/notes/nope.md"), authorised_boards=OK)
    assert gone.state is S.MISSING and gone.data is None and not gone.usable
    assert (await world.resolver.resolve(ref("board:board_nowhere/memory/notes/a.md"), authorised_boards=OK | {"board_nowhere"})).state is S.BOARD_MISSING
    assert (await world.resolver.resolve(ref("board:default/artifact/jart_" + "0" * 32), authorised_boards=OK)).state is S.MISSING
    world.memory.delete("default", BoardMemoryPath.parse("notes/a.md"))
    assert (await world.resolver.resolve(ref(NOTE), authorised_boards=OK)).state is S.MISSING
    assert ("core.live_refs.unresolved", "warning") in world.sink.rows


async def test_an_artifact_must_be_linked_to_that_very_board(world):
    first = await world.boards.get_board("default")
    other = first.__class__(board_id="board_other", title="Autre", created_at=T0, updated_at=T0)
    await world.boards.save_board(other)
    item = await world.resolver.resolve(ref(f"board:board_other/artifact/{world.photo}"), authorised_boards={"board_other"})
    assert item.state is S.NOT_ON_BOARD and item.data is None


async def test_unsafe_or_oversized_content_is_refused(world):
    svg = await world.add_artifact(ArtifactKind.SCREENSHOT, "image/svg+xml", b"<svg onload='x()'/>")
    fake_png = await world.add_artifact(ArtifactKind.SCREENSHOT, "image/png", b"<svg onload='x()'/>")
    audio = await world.add_artifact(ArtifactKind.AUDIO_RECORDING, "audio/wav", b"RIFF....WAVE")
    huge = await world.add_artifact(ArtifactKind.SCREENSHOT, "image/png", PNG_1X1 + b"\0" * MAX_BINARY_BYTES)
    binary_text = await world.add_artifact(ArtifactKind.DESCRIPTION, "text/plain", b"\xff\xfe\x00bad")
    for artifact_id, state in ((svg, S.NOT_ALLOWED), (fake_png, S.NOT_ALLOWED), (audio, S.NOT_ALLOWED), (huge, S.TOO_LARGE),
                               (binary_text, S.NOT_TEXT)):
        item = await world.resolver.resolve(ref(f"board:default/artifact/{artifact_id}"), authorised_boards=OK)
        assert (item.state, item.data) == (state, None), artifact_id
    # a text item above the bound, in Board memory (written in two appends: one write is capped)
    world.write_note("notes/big.md", "x" * (MAX_TEXT_BYTES // 2 + 1), WriteMode.REPLACE)
    world.write_note("notes/big.md", "x" * (MAX_TEXT_BYTES // 2 + 1), WriteMode.APPEND)
    assert (await world.resolver.resolve(ref("board:default/memory/notes/big.md"), authorised_boards=OK)).state is S.TOO_LARGE
    world.write_note("notes/a.exe", "MZ")
    assert (await world.resolver.resolve(ref("board:default/memory/notes/a.exe"), authorised_boards=OK)).state is S.NOT_ALLOWED


async def test_a_presentation_artifact_is_never_a_usable_item(world):
    await world.freeze()
    video = await world.add_artifact(ArtifactKind.PRESENTATION_VIDEO, "video/mp4", b"\0\0\0\x18ftypmp42")
    item = await world.resolver.resolve(ref(f"board:default/artifact/{video}"), authorised_boards=OK)
    assert item.state is S.NOT_ALLOWED and "presentation_video" in item.message


async def test_the_total_of_a_set_is_bounded(world):
    big = await world.add_artifact(ArtifactKind.SCREENSHOT, "image/png", PNG_1X1 + b"\0" * (MAX_BINARY_BYTES - 200))
    refs = [ref(f"board:default/artifact/{big}", f"p{i}") for i in range(5)]
    out = await world.resolver.resolve_all(refs, authorised_boards=OK)
    assert [item.state for item in out.values()] == [S.OK] * 4 + [S.TOO_LARGE]


async def test_a_store_failure_is_reported_never_swallowed(world):
    class Broken:
        async def get_board(self, board_id):
            raise OSError("C:\\secret\\disk path")

    resolver = LiveRefResolver(boards=Broken(), memory=world.memory, artifacts=world.artifacts, links=world.links,
                               diagnostics=world.sink)
    item = await resolver.resolve(ref(NOTE), authorised_boards=OK)
    assert item.state is S.UNREADABLE and "secret" not in item.message and "C:" not in item.message
    assert ("core.live_refs.unreadable", "warning") in world.sink.rows


# ------------------------------------------------------------------ scene data for the sandbox


async def test_scene_data_is_resolved_core_side_and_only_data_crosses(world):
    data = await world.packager.scene_live_data(world.pid, world.vid, SCENE_ID, authorised_boards=OK)
    assert [row["state"] for row in data["refs"]] == ["ok", "ok"]
    assert data["payload"]["note"]["text"] == "# Live note\n"
    assert data["payload"]["photo"]["file"] == "live/photo.png"
    text = json.dumps(data["payload"])
    for leaked in ("board:", "default", "notes/a.md", str(world.tmp_path), world.photo, "jart_"):
        assert leaked not in text, leaked
    world.memory.delete("default", BoardMemoryPath.parse("notes/a.md"))
    again = await world.packager.scene_live_data(world.pid, world.vid, SCENE_ID, authorised_boards=OK)
    assert again["payload"]["note"] == {"state": "missing", "message": "memory_not_found"}  # visible during edit, no raise


async def test_a_scene_can_not_ask_for_a_name_it_did_not_declare_or_another_presentation(world):
    other_pid, other_vid = await world.new_presentation([("secret", "board:default/memory/notes/a.md")],
                                                        prefab_id="presentation-studio.p000000000001.s000000000002")
    mine = await world.packager.scene_live_data(world.pid, world.vid, SCENE_ID, authorised_boards=OK)
    assert set(mine["payload"]) == {"note", "photo"}  # nothing from the other presentation's declaration
    assert "secret" not in json.dumps(mine)
    with pytest.raises(LiveRefError) as caught:
        await world.packager.scene_live_data(world.pid, world.vid, "pss_000000000099", authorised_boards=OK)
    assert caught.value.code is E.UNKNOWN
    with pytest.raises(LiveRefError) as caught:
        await world.packager.scene_live_data(world.pid, other_vid, SCENE_ID, authorised_boards=OK)  # a variant of ANOTHER presentation
    assert caught.value.code is E.UNKNOWN


async def test_a_cross_presentation_reference_in_a_source_refuses_the_freeze_and_the_edit_read(world):
    snapshot = await world.freeze()
    pid, vid = await world.new_presentation([("stolen", f"board:default/artifact/{snapshot['artifact_id']}")],
                                            prefab_id="presentation-studio.p000000000001.s000000000003")
    p, v = await world.revisions(pid)
    before = await world.snapshot_count()
    with pytest.raises(LiveRefError) as caught:
        await world.packager.freeze(pid, vid, expected_presentation_revision=p, expected_variant_revision=v, authorised_boards=OK)
    assert caught.value.code is E.CROSS_PRESENTATION
    shown = await world.packager.scene_live_data(pid, vid, SCENE_ID, authorised_boards=OK)  # editing: typed, never a raise
    assert shown["refs"] == [] and shown["payload"] == {}
    assert [e["code"] for e in shown["declaration_errors"]] == ["live_ref_cross_presentation"]
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
    live = await world.resolver.resolve(ref(NOTE), authorised_boards=OK)
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
        await world.packager.freeze(world.pid, world.vid, expected_presentation_revision=p, expected_variant_revision=v, authorised_boards=OK)
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
        await world.freeze(OK | {"board_nowhere"})
    assert caught.value.code is E.UNRESOLVED and caught.value.details
    assert all(row["state"] != "ok" for row in caught.value.details)
    assert str(world.tmp_path) not in json.dumps(caught.value.details) + str(caught.value)
    assert await world.snapshot_count() == 0  # nothing created, so nothing partial, nothing marked complete
    assert ("core.snapshot_packager.refused", "warning") in world.sink.rows


async def test_a_package_write_failure_fails_the_snapshot_and_never_completes_it(world, monkeypatch):
    def boom(spool, data):
        raise OSError("disk full")

    monkeypatch.setattr(PresentationPackager, "_spool_write", staticmethod(boom))
    with pytest.raises(LiveRefError) as caught:
        await world.freeze()
    assert caught.value.code is E.PACKAGE_FAILED and "disk full" not in str(caught.value)
    page = await world.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_SNAPSHOT,), limit=10))
    (only,) = page.items
    assert only.state is ArtifactState.FAILED and only.error_code == PACKAGE_FAILED
    monkeypatch.undo()
    retry = await world.freeze()  # the next attempt opens _a2: a failed one is evidence, never reused
    assert retry["artifact_id"].endswith("_a2") and retry["created"]


async def pending_with_file(world, *, provenance=None, garbage: bytes | None = None):
    from jarvis.domain.presentation_artifacts import SourceProvenance
    from jarvis.domain.presentation_snapshot_package import build_package
    p, v = await world.revisions()
    begun = await world.snapshots.begin_snapshot(world.pid, world.vid, expected_presentation_revision=p,
                                                 expected_variant_revision=v)
    meta = SourceProvenance.of_snapshot(begun["artifact"]).to_metadata() if provenance is None else provenance
    data = garbage if garbage is not None else build_package(
        {"provenance": meta, "frozen_at": "x", "scenes": [], "prefabs": [], "live_refs": [], "runtime": None},
        {"presentation/presentation.json": b"{}"})
    spool = world.artifacts.open_spool(begun["artifact"])
    spool.write(data)
    spool.finalize()
    return begun, data


async def test_a_pending_snapshot_with_its_file_resumes_with_that_exact_file(world):
    begun, data = await pending_with_file(world)
    world.memory.delete("default", BoardMemoryPath.parse("notes/a.md"))  # the Board has moved since: not needed
    done = await world.freeze()
    assert done["content_sha256"] == hashlib.sha256(data).hexdigest() and not done["created"]
    assert (await world.artifacts.get(begun["artifact_id"])).state is ArtifactState.COMPLETE


@pytest.mark.parametrize("kind", ["corrupt", "other_revision"])
async def test_a_bad_pending_file_is_rejected_on_resume_and_fails_the_snapshot(world, kind):
    from jarvis.domain.presentation_artifacts import SourceProvenance
    if kind == "corrupt":
        begun, _ = await pending_with_file(world, garbage=b"PK-not-a-zip")
    else:  # a well-formed package that describes another revision
        p, v = await world.revisions()
        meta = SourceProvenance(world.pid, world.vid, p, v + 7, "remotion").to_metadata()
        begun, _ = await pending_with_file(world, provenance=meta)
    with pytest.raises(LiveRefError) as caught:
        await world.freeze()
    assert caught.value.code is E.PACKAGE_INVALID
    assert (await world.artifacts.get(begun["artifact_id"])).state is ArtifactState.FAILED
    assert ("core.snapshot_packager.resume_rejected", "error") in world.sink.rows
    retry = await world.freeze()  # the next attempt starts clean
    assert retry["artifact_id"].endswith("_a2")


async def test_a_leftover_partial_file_is_a_typed_failure_and_is_never_deleted(world):
    p, v = await world.revisions()
    begun = await world.snapshots.begin_snapshot(world.pid, world.vid, expected_presentation_revision=p,
                                                 expected_variant_revision=v)
    leftover = world.artifacts.open_spool(begun["artifact"])  # a crashed earlier life left a .partial
    leftover.write(b"half")
    leftover.flush()
    with pytest.raises(LiveRefError) as caught:
        await world.freeze()
    assert caught.value.code is E.PACKAGE_FAILED and str(world.tmp_path) not in str(caught.value)
    failed = await world.artifacts.get(begun["artifact_id"])
    assert failed.error_code == PACKAGE_FAILED
    assert world.artifacts.payload_info(failed).partial_bytes == 4  # kept as evidence
    leftover.close()
    assert (await world.freeze())["artifact_id"].endswith("_a2")


async def test_four_concurrent_freezes_of_the_same_revisions_agree(world):
    import asyncio
    p, v = await world.revisions()
    results = await asyncio.gather(*[
        world.packager.freeze(world.pid, world.vid, expected_presentation_revision=p, expected_variant_revision=v,
                              authorised_boards=OK) for _ in range(4)])
    assert len({r["artifact_id"] for r in results}) == 1 and len({r["content_sha256"] for r in results}) == 1
    assert sum(not r["replayed"] for r in results) == 1 and await world.snapshot_count() == 1
    assert (await world.artifacts.get(results[0]["artifact_id"])).state is ArtifactState.COMPLETE
    assert not world.packager._locks  # nothing leaks


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
    done = await packager.freeze(world.pid, world.vid, expected_presentation_revision=p, expected_variant_revision=v, authorised_boards=OK)
    package = await packager.read_snapshot(done["artifact_id"])
    assert package.manifest["prefabs"][0]["kind"] == "html" and package.manifest["live_refs"] == []
    assert b"do not copy" not in b"".join(package.files.values())


# ------------------------------------------------------------------ authorisation (default deny)


async def other_board_world(world):
    """A second Board with a private note and a private image, both declared by a scene of this presentation."""
    first = await world.boards.get_board("default")
    await world.boards.save_board(first.__class__(board_id="board_private", title="Prive", created_at=T0, updated_at=T0))
    world.memory.write("board_private", BoardMemoryPath.parse("secrets/plan.md"), "TOP SECRET PLAN", mode=WriteMode.REPLACE)
    artifact = await world.artifacts.create(kind=ArtifactKind.SCREENSHOT, source="test", jarvis_session_id=SID,
                                            payload_name="p.png", mime_type="image/png")
    await world.artifacts.store_payload(artifact.artifact_id, PNG_1X1)
    await world.links.link("board_private", artifact.artifact_id, now=T0)
    world.secret_prefab = "presentation-studio.p000000000001.s000000000006"
    world.pid, world.vid = await world.new_presentation(
        [("plan", "board:board_private/memory/secrets/plan.md"),
         ("pic", f"board:board_private/artifact/{artifact.artifact_id}")], prefab_id=world.secret_prefab)


async def test_a_scene_cannot_read_a_board_nobody_authorised_the_probe(world):
    await other_board_world(world)
    shown = await world.packager.scene_live_data(world.pid, world.vid, SCENE_ID, authorised_boards=OK)
    assert [row["state"] for row in shown["refs"]] == ["not_authorised", "not_authorised"]
    assert shown["payload"]["plan"] == {"state": "not_authorised",
                                        "message": "this Board is not authorised for this presentation"}
    assert "TOP SECRET" not in json.dumps(shown) and "board_private" not in json.dumps(shown["payload"])
    with pytest.raises(LiveRefError) as caught:
        await world.freeze()
    assert caught.value.code is E.NOT_AUTHORISED
    assert {row["state"] for row in caught.value.details} == {"not_authorised"}
    assert "TOP SECRET" not in str(caught.value) + json.dumps(caught.value.details)
    assert await world.snapshot_count() == 0


async def test_an_empty_allow_list_resolves_nothing_and_a_missing_board_looks_the_same(world):
    shown = await world.packager.scene_live_data(world.pid, world.vid, SCENE_ID, authorised_boards=set())
    assert {row["state"] for row in shown["refs"]} == {"not_authorised"}
    with pytest.raises(LiveRefError) as caught:
        await world.freeze(set())
    assert caught.value.code is E.NOT_AUTHORISED and await world.snapshot_count() == 0
    # same state for an existing forbidden Board and for one that does not exist: no existence oracle
    await other_board_world(world)
    forbidden = await world.resolver.resolve(ref("board:board_private/memory/secrets/plan.md"), authorised_boards=OK)
    absent = await world.resolver.resolve(ref("board:board_ghost/memory/secrets/plan.md"), authorised_boards=OK)
    assert (forbidden.state, forbidden.message) == (absent.state, absent.message) == (
        S.NOT_AUTHORISED, "this Board is not authorised for this presentation")
    for bad in ("default", None, 12):
        with pytest.raises(LiveRefError):
            await world.packager.scene_live_data(world.pid, world.vid, SCENE_ID, authorised_boards=bad)


async def test_an_authorised_board_works_and_the_freeze_lists_the_boards_used(world):
    await other_board_world(world)
    done = await world.freeze({"board_private"})
    assert done["authorised_boards"] == ["board_private"]
    package = await world.packager.read_snapshot(done["artifact_id"])
    assert package.live(world.secret_prefab, 1, "plan") == b"TOP SECRET PLAN"
    again = await world.freeze({"board_private"})
    assert again["replayed"] and again["authorised_boards"] == ["board_private"]
    assert (await world.freeze())["replayed"]  # a replay reads nothing from any Board, so it needs no grant
    data = await world.packager.scene_live_data(world.pid, world.vid, SCENE_ID, authorised_boards={"board_private"})
    assert data["payload"]["plan"]["text"] == "TOP SECRET PLAN" and data["authorised_boards"] == ["board_private"]


async def test_the_default_deny_is_part_of_the_signature(world):
    import inspect
    for fn in (world.packager.freeze, world.packager.scene_live_data, world.resolver.resolve, world.resolver.resolve_all):
        parameter = inspect.signature(fn).parameters["authorised_boards"]
        assert parameter.default is inspect.Parameter.empty and parameter.kind is inspect.Parameter.KEYWORD_ONLY


# ------------------------------------------------------------------ editing view, package bounds, reopen


async def test_a_malformed_declaration_is_a_typed_row_during_editing_and_a_refusal_at_freeze(world):
    files = scene_files()
    files[LIVE_REFS_PATH] = "{ not json"
    prefab = "presentation-studio.p000000000001.s000000000008"
    await world.prefabs.save(scene_candidate(prefab, files=files), actor="user")
    view = await world.studio.get(world.pid)
    doc = view.variants[0].to_document()
    await world.studio.save_variant(world.pid, world.vid, {
        "expected_revision": doc["revision"], "title": doc["title"],
        "scenes": [{"scene_id": SCENE_ID, "prefab": {"id": prefab, "version": 1}}],
        "art_direction_id": None, "score_id": None})
    shown = await world.packager.scene_live_data(world.pid, world.vid, SCENE_ID, authorised_boards=OK)
    assert shown["refs"] == [] and shown["declaration_errors"][0]["code"] == "live_ref_invalid"
    with pytest.raises(LiveRefError):
        await world.freeze()
    assert await world.snapshot_count() == 0


async def test_the_editing_view_also_lists_the_refs_of_shelved_pins(world, monkeypatch):
    from jarvis.domain.presentation_studio_scene import StudioScene
    other = await world.prefabs.save(scene_candidate(
        "presentation-studio.p000000000001.s000000000009",
        files={**scene_files(), LIVE_REFS_PATH: declaration(("shelf", NOTE))}), actor="user")
    held = frozenset({(SCENE_PREFAB, 1), (other.prefab_id, 1)})  # what a scene with a shelved local variant holds
    monkeypatch.setattr(StudioScene, "held_pins", lambda self: held)
    shown = await world.packager.scene_live_data(world.pid, world.vid, SCENE_ID, authorised_boards=OK)
    assert {(r["prefab_id"], r["name"], r["active"]) for r in shown["refs"]} == {
        (SCENE_PREFAB, "note", True), (SCENE_PREFAB, "photo", True), (other.prefab_id, "shelf", False)}
    assert "shelf" not in shown["payload"]  # only the current pin feeds the sandbox


async def test_a_legal_eight_deep_source_freezes(world):
    deep = "src/a/b/c/d/e/f/Deep.tsx"  # 8 segments: the Slice 05 maximum
    prefab = "presentation-studio.p000000000001.s000000000010"
    world.pid, world.vid = await world.new_presentation([("note", NOTE)], prefab_id=prefab,
                                                        extra={deep: "export const Deep = () => null;\n"})
    done = await world.freeze()
    package = await world.packager.read_snapshot(done["artifact_id"])
    assert f"prefabs/{prefab}/1/{deep}" in package.files
    assert package.live(prefab, 1, "note") == b"# Live note\n"


def test_the_built_zip_is_bounded_not_only_its_members(monkeypatch):
    from jarvis.domain import presentation_snapshot_package as pkg
    members = {f"f{i}.txt": b"x" * 100 for i in range(10)}
    core = {"provenance": {}, "frozen_at": "x", "scenes": [], "prefabs": [], "live_refs": [], "runtime": None}
    built = len(pkg.build_package(core, members))
    assert built > sum(len(b) for b in members.values())  # headers and manifest are real bytes
    monkeypatch.setattr(pkg, "MAX_PACKAGE_BYTES", built)
    pkg.read_package(pkg.build_package(core, members))  # exactly at the limit: producible and readable
    monkeypatch.setattr(pkg, "MAX_PACKAGE_BYTES", built - 1)  # the members alone fit, the zip does not
    with pytest.raises(LiveRefError) as caught:
        pkg.build_package(core, members)
    assert caught.value.code is E.PACKAGE_TOO_LARGE
    monkeypatch.setattr(pkg, "MAX_PACKAGE_BYTES", 64 * 1024 * 1024)
    huge = {**core, "provenance": {"k": "v" * (pkg.MAX_MANIFEST_BYTES + 1)}}
    with pytest.raises(LiveRefError) as caught:
        pkg.build_package(huge, {})
    assert caught.value.code is E.PACKAGE_TOO_LARGE


async def test_reopening_checks_the_provenance_and_logs_tampering(world):
    from jarvis.domain.presentation_snapshot_package import build_package, read_package
    done = await world.freeze()
    artifact = await world.artifacts.get(done["artifact_id"])
    forged = build_package({"provenance": {"source_kind": "presentation"}, "frozen_at": "x", "scenes": [], "prefabs": [],
                            "live_refs": [], "runtime": None}, {"presentation/presentation.json": b"{}"})
    # a well-formed package with a wrong provenance is refused even when its own hash is the recorded one
    with pytest.raises(LiveRefError):
        PresentationPackager._check_provenance(artifact, read_package(forged))
    # and a replaced file is caught by the recorded hash, logged as an error
    with open(world.artifacts.payload_path(artifact), "wb") as handle:
        handle.write(forged)
    with pytest.raises(LiveRefError):
        await world.packager.read_snapshot(done["artifact_id"])
    assert ("core.snapshot_packager.tampered", "error") in world.sink.rows


async def test_the_package_describes_only_the_frozen_variant(world):
    view = await world.studio.get(world.pid)
    done = await world.freeze()
    package = await world.packager.read_snapshot(done["artifact_id"])
    doc = json.loads(package.files["presentation/presentation.json"])
    assert [e["variant_id"] for e in doc["variants"]] == [world.vid] and doc["archived"] == []
    assert doc["active_variant_id"] == world.vid and doc["presentation_id"] == view.presentation.presentation_id

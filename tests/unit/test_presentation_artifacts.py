"""Source de Presentation (parent éditable) contre Artifacts terminaux (Remotion Slice 07).

Vrai magasin de fichiers du Studio + vrai registre SQLite (`tmp_path`). Contrat : `docs/presentation-artifacts.md`.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
from pathlib import Path

import pytest

from jarvis.adapters.artifact_payloads import FileArtifactPayloads
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.adapters.sqlite_artifacts import SQLiteArtifactRepository
from jarvis.adapters.sqlite_board_artifact_links import SQLiteBoardArtifactLinks
from jarvis.adapters.sqlite_session_activity import SQLiteActivityLedger
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.artifact_service import ArtifactService
from jarvis.core.presentation_artifacts import PresentationArtifacts
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain import presentation_artifacts as pa
from jarvis.domain.artifacts import (
    ArtifactError, ArtifactErrorCode as AE, ArtifactKind, ArtifactQuery, ArtifactRelationKind, ArtifactState,
    check_artifact_id,
)
from jarvis.domain.board_artifact_links import BoardArtifactLinkOrigin
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_engine import Engine
from jarvis.domain.workspace_board import create_board, default_board, open_session
from jarvis.ports.artifacts import RelationDirection

T0 = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)
SID = "jsess_0123456789abcdef"
SCENES = [{"scene_id": "pss_000000000001", "prefab": {"id": "jarvis.window", "version": 1}}]


class World:
    def __init__(self, tmp_path, state, studio, artifacts, links, boards, sink) -> None:
        self.tmp_path, self.state, self.studio, self.artifacts = tmp_path, state, studio, artifacts
        self.links, self.boards, self.sink = links, boards, sink
        self.service = PresentationArtifacts(studio, artifacts, links, diagnostics=sink)
        self.pid = self.vid = ""

    async def source(self) -> tuple[int, int]:
        view = await self.studio.get(self.pid)
        return view.presentation.revision, view.variants[0].revision

    async def edit_variant(self) -> None:
        variant = (await self.studio.get(self.pid)).variants[0]
        doc = variant.to_document()
        await self.studio.save_variant(self.pid, self.vid, {
            "expected_revision": doc["revision"], "title": doc["title"] + "!", "scenes": doc["scenes"],
            "art_direction_id": doc["art_direction_id"], "score_id": doc["score_id"]})

    async def begin(self) -> dict:
        p, v = await self.source()
        return await self.service.begin_snapshot(self.pid, self.vid, expected_presentation_revision=p,
                                                 expected_variant_revision=v)

    async def package(self, artifact_id: str, data: bytes = b"PK-frozen-package") -> str:
        spool = self.artifacts.open_spool(await self.artifacts.get(artifact_id))
        spool.write(data)
        spool.finalize()
        return hashlib.sha256(data).hexdigest()

    async def frozen(self) -> str:
        began = await self.begin()
        digest = await self.package(began["artifact_id"])
        await self.service.finalize_snapshot(began["artifact_id"], content_sha256=digest)
        return began["artifact_id"]

    async def board_ids(self, artifact_id: str) -> set[str]:
        return {link.board_id for link in await self.links.boards_of_artifact(artifact_id, limit=50)}


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.rows.append((kind, level))


@pytest.fixture
async def world(tmp_path):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    boards = SQLiteBoardRepository(state)
    first = default_board(now=T0)
    await boards.save_board(first)
    await boards.save_session(open_session(first, now=T0, jarvis_session_id=SID))
    sink = Sink()
    for name in ("data", "studio", "elsewhere"):
        (tmp_path / name).mkdir()
    artifacts = ArtifactService(SQLiteArtifactRepository(state), SQLiteActivityLedger(state),
                                FileArtifactPayloads(tmp_path / "data"), diagnostics=sink)
    studio = PresentationStudioService(FilePresentationStudioStore(tmp_path / "studio"))
    w = World(tmp_path, state, studio, artifacts, SQLiteBoardArtifactLinks(state), boards, sink)
    w.first_board = first
    created = await studio.create({"title": "Atelier"})
    w.pid, w.vid = created.presentation.presentation_id, created.presentation.active_variant_id
    await w.edit_variant()  # revision 2: the fixture is not at the creation defaults
    try:
        yield w
    finally:
        await state.close()


async def refused(awaitable, code):
    with pytest.raises((ArtifactError, PresentationStudioError)) as caught:
        await awaitable
    assert caught.value.code == code, caught.value
    return caught.value


# ------------------------------------------------------------------ identity of the editable parent


def test_a_source_ref_is_stable_parseable_and_never_an_artifact_id():
    pid, vid = "pst_" + "a" * 32, "psv_" + "b" * 32
    for ref in (pa.SourceRef(pid), pa.SourceRef(pid, vid)):
        assert pa.SourceRef.parse(str(ref)) == ref
        assert not str(ref).startswith("jart_")
        assert "revision" not in str(ref)  # it survives every edit: it never names a revision
    assert str(pa.SourceRef(pid, vid)) == f"presentation:{pid}/{vid}"
    for bad in ("jart_" + "a" * 8, "presentation:nope", f"presentation:{pid}/psv_x", f"slide:{pid}", None, 12):
        with pytest.raises(PresentationStudioError):
            pa.SourceRef.parse(bad)


def test_a_presentation_id_can_never_be_a_board_link_target():
    with pytest.raises(ArtifactError) as caught:
        check_artifact_id("pst_" + "a" * 32)  # the first line of WorkspaceService.artifact_link
    assert caught.value.code is AE.INVALID_ARTIFACT


def test_no_presentation_module_writes_board_state():
    root = Path(__file__).resolve().parents[2] / "jarvis"
    for path in (root / "core" / "presentation_artifacts.py", root / "domain" / "presentation_artifacts.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not {m for m in imported if "board_service" in m or "workspace_service" in m}, path
        assert "artifact_refs" not in {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert "artifact_refs" not in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


# ------------------------------------------------------------------ freezing


async def test_begin_snapshot_opens_a_pending_snapshot_of_exactly_this_revision(world):
    p, v = await world.source()
    began = await world.begin()
    snap = began["artifact"]
    assert began["created"] and snap.kind is ArtifactKind.PRESENTATION_SNAPSHOT and snap.state is ArtifactState.PENDING
    assert snap.artifact_id == pa.snapshot_artifact_id(world.pid, world.vid, p, v)
    provenance = pa.SourceProvenance.of_snapshot(snap)
    assert (provenance.presentation_id, provenance.variant_id, provenance.presentation_revision,
            provenance.variant_revision, provenance.engine) == (world.pid, world.vid, p, v, Engine.REMOTION)
    # the editable source stays a Presentation: no Artifact row carries its id, no link row names it
    page = await world.artifacts.query(ArtifactQuery())
    assert [a.artifact_id for a in page.items] == [snap.artifact_id]
    assert await world.board_ids(snap.artifact_id) == {world.first_board.board_id}  # automatic active-Board link
    assert ("core.presentation_artifacts.snapshot_begun", "info") in world.sink.rows


async def test_the_same_revision_is_replayed_never_duplicated(world):
    first, again = await world.begin(), await world.begin()
    assert not again["created"] and again["artifact_id"] == first["artifact_id"]
    assert len((await world.artifacts.query(ArtifactQuery())).items) == 1


async def test_a_stale_source_revision_is_refused_and_writes_nothing(world):
    p, v = await world.source()
    for args in ((p - 1, v), (p, v - 1), (p + 1, v + 1)):
        await refused(world.service.begin_snapshot(world.pid, world.vid, expected_presentation_revision=args[0],
                                                   expected_variant_revision=args[1]), C.STALE_REVISION)
    assert (await world.artifacts.query(ArtifactQuery())).items == ()


async def test_unknown_presentation_variant_and_ids_are_refused(world):
    p, v = await world.source()
    await refused(world.service.begin_snapshot("pst_" + "0" * 32, world.vid, expected_presentation_revision=p,
                                               expected_variant_revision=v), C.UNKNOWN_PRESENTATION)
    await refused(world.service.begin_snapshot(world.pid, "psv_" + "0" * 32, expected_presentation_revision=p,
                                               expected_variant_revision=v), C.UNKNOWN_VARIANT)
    await refused(world.service.begin_snapshot("jart_x", world.vid, expected_presentation_revision=p,
                                               expected_variant_revision=v), C.UNKNOWN_PRESENTATION)


async def test_finalize_freezes_the_snapshot_with_its_hash(world):
    sid = await world.frozen()
    done = await world.artifacts.get(sid)
    assert done.state is ArtifactState.COMPLETE and done.size_bytes == len(b"PK-frozen-package")
    assert done.metadata["content_sha256"] == hashlib.sha256(b"PK-frozen-package").hexdigest()
    assert done.payload_ref == f"artifacts/{sid}/snapshot.zip" and not done.payload_ref.startswith(("/", "presentations"))


async def test_a_bad_content_hash_is_refused(world):
    began = await world.begin()
    await world.package(began["artifact_id"])
    for bad in ("", "ABC", "g" * 64, "a" * 63, None):
        await refused(world.service.finalize_snapshot(began["artifact_id"], content_sha256=bad), AE.INVALID_ARTIFACT)
    assert (await world.artifacts.get(began["artifact_id"])).state is ArtifactState.PENDING


async def test_a_source_edited_before_finalize_fails_the_snapshot_never_completes_it(world):
    began = await world.begin()
    digest = await world.package(began["artifact_id"])
    await world.edit_variant()
    await refused(world.service.finalize_snapshot(began["artifact_id"], content_sha256=digest), C.STALE_REVISION)
    failed = await world.artifacts.get(began["artifact_id"])
    assert failed.state is ArtifactState.FAILED and failed.error_code == pa.SOURCE_STALE
    assert ("core.presentation_artifacts.snapshot_refused", "warning") in world.sink.rows
    # the new revision freezes under its own id; the failed one stays failed evidence
    again = await world.begin()
    assert again["created"] and again["artifact_id"] != began["artifact_id"]
    assert (await world.artifacts.get(began["artifact_id"])).state is ArtifactState.FAILED


async def test_a_failed_attempt_of_a_revision_opens_the_next_attempt(world):
    first = await world.begin()
    await world.artifacts.fail(first["artifact_id"], error_code="disk_full")
    second = await world.begin()
    assert second["created"] and second["artifact_id"] == first["artifact_id"][:-1] + "2"
    assert (await world.artifacts.get(first["artifact_id"])).state is ArtifactState.FAILED


async def test_attempts_are_bounded(world):
    for _ in range(pa.MAX_SNAPSHOT_ATTEMPTS):
        began = await world.begin()
        await world.artifacts.fail(began["artifact_id"], error_code="disk_full")
    await refused(world.begin(), AE.ARTIFACT_CONFLICT)


async def test_a_complete_snapshot_is_immutable_and_independent_of_later_edits(world):
    sid = await world.frozen()
    before = await world.artifacts.get(sid)
    await world.edit_variant()
    await world.edit_variant()
    after = await world.artifacts.get(sid)
    assert after == before
    await refused(world.artifacts.update_pending(sid, metadata={"source_variant_revision": 99}), AE.ARTIFACT_NOT_PENDING)
    await refused(world.artifacts.fail(sid, error_code="x"), AE.ARTIFACT_NOT_PENDING)
    await refused(world.service.finalize_snapshot(sid, content_sha256="a" * 64), AE.ARTIFACT_NOT_PENDING)
    enriched = await world.artifacts.enrich(sid, {"label": "client review"})  # enrichment stays open, the rest does not move
    assert enriched.metadata == before.metadata and enriched.payload_ref == before.payload_ref


async def test_a_provenance_contradicting_its_id_is_not_trusted(world):
    sid = await world.frozen()
    other = await world.artifacts.create(
        kind=ArtifactKind.PRESENTATION_SNAPSHOT, source=pa.ARTIFACT_SOURCE,
        metadata={**(await world.artifacts.get(sid)).metadata, "source_variant_revision": 9})
    with pytest.raises(ArtifactError) as caught:
        pa.SourceProvenance.of_snapshot(other)
    assert caught.value.code is AE.INVALID_ARTIFACT
    bare = await world.artifacts.create(kind=ArtifactKind.PRESENTATION_SNAPSHOT, source=pa.ARTIFACT_SOURCE)
    with pytest.raises(ArtifactError):
        pa.SourceProvenance.of_snapshot(bare)


# ------------------------------------------------------------------ derivatives


async def test_a_render_links_back_to_its_snapshot_with_the_snapshot_provenance(world):
    sid = await world.frozen()
    for fmt, kind in (("mp4", ArtifactKind.PRESENTATION_VIDEO), (pa.RenderFormat.STILL, ArtifactKind.PRESENTATION_STILL),
                      ("pdf", ArtifactKind.PRESENTATION_PDF)):
        render = await world.service.begin_render(sid, fmt)
        assert render.kind is kind and render.state is ArtifactState.PENDING
        origins = await world.artifacts.relations(render.artifact_id, RelationDirection.ORIGINS)
        assert [(r.relation, r.origin_artifact_id) for r in origins] == [(ArtifactRelationKind.RENDERED_FROM, sid)]
        assert await world.board_ids(render.artifact_id) == {world.first_board.board_id}
        assert "source_presentation_id" not in render.metadata  # one copy of the provenance: the snapshot's
    dependents = await world.artifacts.relations(sid, RelationDirection.DEPENDENTS)
    assert len(dependents) == 3


async def test_a_render_of_an_older_snapshot_stays_valid_after_the_source_moved(world):
    sid = await world.frozen()
    await world.edit_variant()
    render = await world.service.begin_render(sid, "mp4")  # it renders THIS snapshot, not the live source
    assert render.state is ArtifactState.PENDING


async def test_an_orphaned_or_invalid_origin_is_refused(world):
    await refused(world.service.begin_render("jart_ps_" + "0" * 32, "mp4"), AE.ARTIFACT_NOT_FOUND)
    pending = await world.begin()
    await refused(world.service.begin_render(pending["artifact_id"], "mp4"), AE.INVALID_RELATION)  # not complete yet
    shot = await world.artifacts.create(kind=ArtifactKind.SCREENSHOT, source="test", payload_name="s.png")
    await refused(world.service.begin_render(shot.artifact_id, "mp4"), AE.INVALID_RELATION)  # not a snapshot
    assert [a.kind for a in (await world.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_VIDEO,)))).items] == []


async def test_the_registry_itself_refuses_a_derivative_with_an_unknown_origin(world):
    await refused(world.artifacts.create(kind=ArtifactKind.PRESENTATION_VIDEO, source=pa.ARTIFACT_SOURCE,
                                         origins=((ArtifactRelationKind.RENDERED_FROM, "jart_" + "9" * 32),)),
                  AE.ARTIFACT_NOT_FOUND)


async def test_a_bad_render_format_is_refused_before_anything_is_read(world):
    sid = await world.frozen()
    for bad in ("gif", "", None, "MP4"):
        await refused(world.service.begin_render(sid, bad), C.INVALID_PRESENTATION)


async def test_a_snapshot_of_an_engine_that_cannot_export_yields_no_render(world):
    legacy = pa.SourceProvenance(world.pid, world.vid, 1, 1, Engine.SLIDECAR)
    snap = await world.artifacts.create(
        kind=ArtifactKind.PRESENTATION_SNAPSHOT, source=pa.ARTIFACT_SOURCE, payload_name="snapshot.zip",
        artifact_id=pa.snapshot_artifact_id(world.pid, world.vid, 1, 1), metadata=legacy.to_metadata())
    spool = world.artifacts.open_spool(snap)
    spool.write(b"x")
    spool.finalize()
    await world.artifacts.finalize(snap.artifact_id)
    await refused(world.service.begin_render(snap.artifact_id, "mp4"), C.ENGINE_UNSUPPORTED)


async def test_a_snapshot_cannot_be_deleted_from_under_its_renders(world):
    sid = await world.frozen()
    render = await world.service.begin_render(sid, "mp4")
    await world.artifacts.fail(render.artifact_id, error_code="render_failed")
    await refused(world.artifacts.delete(sid), AE.ARTIFACT_HAS_DEPENDENTS)  # no orphan by accident
    result = await world.artifacts.delete(sid, cascade=True)  # explicit and transitive: the registry's own rule
    assert set(result.artifact_ids) == {sid, render.artifact_id}


# ------------------------------------------------------------------ which Boards show this (one owner: the link service)


async def test_a_source_that_was_never_frozen_is_on_no_board(world):
    described = await world.service.describe_source(world.pid)
    assert described["snapshots"] == [] and described["board_ids"] == []
    assert described["source"]["exists"] is True and described["source_ref"] == f"presentation:{world.pid}"
    assert (await world.service.sources_of_board(world.first_board.board_id))["sources"] == []


async def test_the_board_lists_the_source_through_its_linked_artifacts_only(world):
    sid = await world.frozen()
    render = await world.service.begin_render(sid, "mp4")
    listing = await world.service.sources_of_board(world.first_board.board_id)
    (source,) = listing["sources"]
    assert source["presentation_id"] == world.pid and source["source"]["title"] == "Atelier"
    (entry,) = source["snapshots"]
    assert entry["artifact_id"] == sid and entry["linked_here"] is True and entry["stale"] is False
    assert [r["artifact_id"] for r in entry["renders"]] == [render.artifact_id]
    assert entry["board_ids"] == [world.first_board.board_id]
    # the single owner: the link table. Nothing else was written for the Board.
    assert await world.links.count_links(world.first_board.board_id) == 2


async def test_an_explicit_cross_board_link_is_what_makes_another_board_show_the_source(world):
    sid = await world.frozen()
    other = create_board("Revue client", now=T0)
    await world.boards.save_board(other)
    assert (await world.service.sources_of_board(other.board_id))["sources"] == []
    await world.links.link(other.board_id, sid, now=T0, origin=BoardArtifactLinkOrigin.EXPLICIT)
    assert (await world.service.sources_of_board(other.board_id))["sources"][0]["presentation_id"] == world.pid
    assert await world.service.boards_of_source(world.pid) == sorted({other.board_id, world.first_board.board_id})
    await world.links.unlink(other.board_id, sid)
    assert await world.service.boards_of_source(world.pid) == [world.first_board.board_id]


async def test_a_render_linked_alone_shows_its_snapshot_unlinked_here(world):
    sid = await world.frozen()
    render = await world.service.begin_render(sid, "pdf")
    other = create_board("Archive", now=T0)
    await world.boards.save_board(other)
    await world.links.link(other.board_id, render.artifact_id, now=T0)
    (source,) = (await world.service.sources_of_board(other.board_id))["sources"]
    assert source["snapshots"][0]["artifact_id"] == sid and source["snapshots"][0]["linked_here"] is False


async def test_stale_is_a_display_fact_and_a_snapshot_never_expires(world):
    sid = await world.frozen()
    await world.edit_variant()
    (entry,) = (await world.service.describe_source(world.pid))["snapshots"]
    assert entry["artifact_id"] == sid and entry["stale"] is True and entry["state"] == "complete"


async def test_the_lineage_survives_the_loss_of_the_editable_source(world, tmp_path):
    sid = await world.frozen()
    gone = PresentationArtifacts(PresentationStudioService(FilePresentationStudioStore(tmp_path / "elsewhere")),
                                 world.artifacts, world.links)
    described = await gone.describe_source(world.pid)
    assert described["source"] == {"exists": False}
    assert [e["artifact_id"] for e in described["snapshots"]] == [sid] and described["snapshots"][0]["stale"] is None
    await world.edit_variant()
    pending = await world.begin()
    await refused(gone.finalize_snapshot(pending["artifact_id"], content_sha256="a" * 64), C.UNKNOWN_PRESENTATION)
    assert (await world.artifacts.get(pending["artifact_id"])).error_code == pa.SOURCE_MISSING


async def test_the_scan_says_when_it_is_cut_short(world, monkeypatch):
    from jarvis.core import presentation_artifacts as module
    await world.frozen()
    monkeypatch.setattr(module, "SCAN_PAGE", 1)
    monkeypatch.setattr(module, "MAX_SCAN_PAGES", 1)
    await world.edit_variant()
    await world.frozen()
    assert (await world.service.describe_source(world.pid))["truncated"] is True


# ------------------------------------------------------------------ QA polish: hash, error mapping, unreadable rows, honest truncation


async def test_a_false_content_hash_is_refused_and_the_snapshot_stays_pending(world):
    began = await world.begin()
    real = await world.package(began["artifact_id"])
    wrong = "0" * 64
    assert wrong != real
    error = await refused(world.service.finalize_snapshot(began["artifact_id"], content_sha256=wrong), AE.INVALID_ARTIFACT)
    assert "does not match" in str(error)
    assert (await world.artifacts.get(began["artifact_id"])).state is ArtifactState.PENDING
    assert ("core.presentation_artifacts.hash_mismatch", "warning") in world.sink.rows
    done = await world.service.finalize_snapshot(began["artifact_id"], content_sha256=real)  # the right hash still works
    assert done.state is ArtifactState.COMPLETE and done.metadata["content_sha256"] == real


async def test_finalize_without_the_final_package_on_disk_is_refused_and_stays_pending(world):
    began = await world.begin()
    await refused(world.service.finalize_snapshot(began["artifact_id"], content_sha256="a" * 64), AE.INVALID_ARTIFACT)
    assert (await world.artifacts.get(began["artifact_id"])).state is ArtifactState.PENDING


class BrokenStudio:
    def __init__(self, error: PresentationStudioError) -> None:
        self.error = error

    async def get(self, presentation_id):
        raise self.error


@pytest.mark.parametrize("code", [C.STORAGE_IO, C.CORRUPT_DOCUMENT, C.UNSUPPORTED_SCHEMA_VERSION])
async def test_an_unrelated_studio_failure_leaves_the_snapshot_pending(world, code):
    began = await world.begin()
    digest = await world.package(began["artifact_id"])
    broken = PresentationArtifacts(BrokenStudio(PresentationStudioError(code, "disk said no")), world.artifacts, world.links)
    await refused(broken.finalize_snapshot(began["artifact_id"], content_sha256=digest), code)
    assert (await world.artifacts.get(began["artifact_id"])).state is ArtifactState.PENDING


@pytest.mark.parametrize("code,expected", [(C.UNKNOWN_PRESENTATION, pa.SOURCE_MISSING), (C.UNKNOWN_VARIANT, pa.SOURCE_MISSING),
                                           (C.STALE_REVISION, pa.SOURCE_STALE)])
async def test_only_missing_and_stale_fail_the_snapshot_with_their_own_code(world, code, expected):
    began = await world.begin()
    digest = await world.package(began["artifact_id"])
    broken = PresentationArtifacts(BrokenStudio(PresentationStudioError(code, "x")), world.artifacts, world.links)
    await refused(broken.finalize_snapshot(began["artifact_id"], content_sha256=digest), code)
    failed = await world.artifacts.get(began["artifact_id"])
    assert failed.state is ArtifactState.FAILED and failed.error_code == expected


async def _bad_rows(world) -> list[str]:
    good = await world.frozen()
    meta = (await world.artifacts.get(good)).metadata
    contradicting = await world.artifacts.create(kind=ArtifactKind.PRESENTATION_SNAPSHOT, source=pa.ARTIFACT_SOURCE,
                                                 metadata={**meta, "source_variant_revision": 9})
    bare = await world.artifacts.create(kind=ArtifactKind.PRESENTATION_SNAPSHOT, source=pa.ARTIFACT_SOURCE)
    return [good, contradicting.artifact_id, bare.artifact_id]


async def test_describe_source_skips_and_flags_unreadable_rows_instead_of_failing(world):
    good, contradicting, bare = await _bad_rows(world)
    described = await world.service.describe_source(world.pid)
    assert [e["artifact_id"] for e in described["snapshots"]] == [good]
    flagged = {row["artifact_id"]: row["code"] for row in described["unreadable"]}
    assert flagged == {contradicting: "invalid_artifact", bare: "invalid_artifact"}


async def test_sources_of_board_skips_and_flags_unreadable_rows_instead_of_failing(world):
    good, contradicting, bare = await _bad_rows(world)
    listing = await world.service.sources_of_board(world.first_board.board_id)
    (source,) = listing["sources"]
    assert [e["artifact_id"] for e in source["snapshots"]] == [good]
    assert {row["artifact_id"] for row in listing["unreadable"]} == {contradicting, bare}


async def test_a_render_without_a_readable_snapshot_is_flagged_not_fatal(world):
    sid = await world.frozen()
    render = await world.service.begin_render(sid, "mp4")
    orphan = await world.artifacts.create(kind=ArtifactKind.PRESENTATION_VIDEO, source=pa.ARTIFACT_SOURCE)  # no origin
    listing = await world.service.sources_of_board(world.first_board.board_id)
    assert [r["artifact_id"] for r in listing["unreadable"]] == [orphan.artifact_id]
    assert listing["sources"][0]["snapshots"][0]["renders"][0]["artifact_id"] == render.artifact_id


async def test_truncated_is_false_when_nothing_was_cut(world):
    await world.frozen()
    assert (await world.service.describe_source(world.pid))["truncated"] is False
    assert (await world.service.sources_of_board(world.first_board.board_id))["truncated"] is False


async def test_truncated_is_honest_when_the_board_page_is_full(world, monkeypatch):
    from jarvis.core import presentation_artifacts as module
    await world.frozen()
    await world.edit_variant()
    await world.frozen()
    monkeypatch.setattr(module, "SCAN_PAGE", 1)
    listing = await world.service.sources_of_board(world.first_board.board_id)
    assert listing["truncated"] is True and len(listing["sources"][0]["snapshots"]) == 1


async def test_truncated_is_honest_when_the_relations_read_is_full(world, monkeypatch):
    from jarvis.core import presentation_artifacts as module
    sid = await world.frozen()
    await world.service.begin_render(sid, "mp4")
    monkeypatch.setattr(module, "RELATIONS_READ", 1)  # the read returned as many rows as its cap: more may exist
    assert (await world.service.describe_source(world.pid))["truncated"] is True
    monkeypatch.setattr(module, "RELATIONS_READ", 2)
    assert (await world.service.describe_source(world.pid))["truncated"] is False


async def test_truncated_is_honest_when_the_board_links_read_is_full(world, monkeypatch):
    from jarvis.core import presentation_artifacts as module
    sid = await world.frozen()
    other = create_board("Revue", now=T0)
    await world.boards.save_board(other)
    await world.links.link(other.board_id, sid, now=T0)
    monkeypatch.setattr(module, "BOARD_LINKS_READ", 1)
    described = await world.service.describe_source(world.pid)
    assert described["truncated"] is True and len(described["snapshots"][0]["board_ids"]) == 1
    monkeypatch.setattr(module, "BOARD_LINKS_READ", 2)
    assert (await world.service.describe_source(world.pid))["truncated"] is False

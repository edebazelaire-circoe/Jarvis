"""Découverte d'une présentation depuis un Board (Remotion Slice 08).

Vraie chaîne (`tests/fakes/capture_stack.py` : Core sur SQLite et racine de données réelles, `LocalProtocolServer`,
Control Center), vrais propriétaires : `PresentationStudioService` écrit la source, `PresentationArtifacts` fige et rend,
`board_artifact_links` dit quels Boards montrent quoi. Contrat : `docs/presentation-artifacts.md`, `docs/boards.md`.
"""

from __future__ import annotations

import hashlib
import shutil

from jarvis.domain.artifacts import ArtifactKind
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_capture_api_protocol import assert_clean, core

SOURCES = "/v1/workspace/boards/{}/presentation-sources"
SOURCE = "/v1/workspace/presentation-sources/{}"


async def freeze(stack: CaptureStack, pid: str, vid: str) -> str:
    c = stack.core
    view = await c.presentation_studio.get(pid)
    variant = next(v for v in view.variants if v.variant_id == vid)
    began = await c.presentation_artifacts.begin_snapshot(
        pid, vid, expected_presentation_revision=view.presentation.revision, expected_variant_revision=variant.revision)
    spool = c.artifacts.open_spool(await c.artifacts.get(began["artifact_id"]))
    data = b"PK-" + began["artifact_id"].encode()
    spool.write(data)
    spool.finalize()
    await c.presentation_artifacts.finalize_snapshot(began["artifact_id"], content_sha256=hashlib.sha256(data).hexdigest())
    return began["artifact_id"]


async def new_source(stack: CaptureStack, title: str = "Atelier") -> tuple[str, str]:
    created = await stack.core.presentation_studio.create({"title": title})
    return created.presentation.presentation_id, created.presentation.active_variant_id


async def board_on(stack: CaptureStack, title: str) -> str:
    board = (await stack.core.boards.create({"title": title})).board_id
    await stack.core.boards.switch(board)
    return board


async def test_the_core_composition_root_wires_the_bridge_once(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        c = stack.core
        assert c.presentation_artifacts is not None and c.workspace._presentations is c.presentation_artifacts


async def test_a_board_without_presentation_says_so_and_unknown_boards_are_refused(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        board = (await stack.core.boards.create({"title": "Vide"})).board_id
        status, body, raw, _ = await core(stack, "GET", SOURCES.format(board))
        assert status == 200 and body["sources"] == [] and body["unreadable"] == [] and body["truncated"] is False
        status, missing, _, _ = await core(stack, "GET", SOURCES.format("board_nope"))
        assert (status, missing["error"]["code"]) == (404, "board_not_found")
        assert_clean(stack, raw)


async def test_a_never_frozen_source_is_on_no_board(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        board = await board_on(stack, "B")
        pid, _ = await new_source(stack)
        _, body, _, _ = await core(stack, "GET", SOURCE.format(pid))
        assert body["board_ids"] == [] and body["snapshots"] == [] and body["source"]["exists"] is True
        _, listing, _, _ = await core(stack, "GET", SOURCES.format(board))
        assert listing["sources"] == []


async def test_a_frozen_source_and_its_render_group_under_the_active_board_and_survive_a_restart(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        c = stack.core
        board = await board_on(stack, "Atelier")
        pid, vid = await new_source(stack)
        snap = await freeze(stack, pid, vid)  # a freeze never asks for a Board: the active one is linked
        render = (await c.presentation_artifacts.begin_render(snap, "mp4")).artifact_id
        _, body, raw, _ = await core(stack, "GET", SOURCES.format(board))
        (group,) = body["sources"]
        assert group["source_ref"] == f"presentation:{pid}" and group["source"]["exists"] is True
        assert group["source"]["engine"] == "remotion" and group["source"]["title"] == "Atelier"
        (entry,) = group["snapshots"]
        assert (entry["artifact_id"], entry["state"], entry["variant_id"], entry["engine"]) == (
            snap, "complete", vid, "remotion")
        assert entry["stale"] is False and entry["linked_here"] is True and entry["created_at"]
        (shown,) = entry["renders"]
        assert (shown["artifact_id"], shown["format"], shown["state"]) == (render, "mp4", "pending")
        assert board in shown["board_ids"]
        assert_clean(stack, raw)
        _, source, _, _ = await core(stack, "GET", SOURCE.format(pid))  # reverse navigation: same answer, other end
        assert source["board_ids"] == [board] and source["snapshots"][0]["renders"][0]["artifact_id"] == render
    async with CaptureStack(tmp_path) as again:  # nothing is cached: a new Core on the same data root reads the same
        _, restarted, _, _ = await core(again, "GET", SOURCES.format(board))
        assert restarted["sources"][0]["snapshots"][0]["artifact_id"] == snap
        assert restarted["sources"][0]["snapshots"][0]["renders"][0]["artifact_id"] == render


async def test_stale_and_deleted_sources_are_visible_and_never_rewrite_the_frozen_copy(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        c = stack.core
        board = await board_on(stack, "B")
        pid, vid = await new_source(stack)
        snap = await freeze(stack, pid, vid)
        frozen = (await c.artifacts.get(snap)).to_payload()
        variant = (await c.presentation_studio.get(pid)).variants[0].to_document()
        await c.presentation_studio.save_variant(pid, vid, {
            "expected_revision": variant["revision"], "title": variant["title"] + "!", "scenes": variant["scenes"],
            "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"]})
        _, body, _, _ = await core(stack, "GET", SOURCES.format(board))
        entry = body["sources"][0]["snapshots"][0]
        assert entry["stale"] is True and entry["state"] == "complete"
        shutil.rmtree(stack.data_root / "presentations" / pid)  # the user lost the source folder
        _, gone, _, _ = await core(stack, "GET", SOURCES.format(board))
        group = gone["sources"][0]
        assert group["source"] == {"exists": False}
        assert group["snapshots"][0]["stale"] is None and group["snapshots"][0]["artifact_id"] == snap
        assert (await c.artifacts.get(snap)).to_payload() == frozen  # lineage intact, byte for byte


async def test_an_explicit_cross_board_link_shows_the_group_on_the_other_board_and_unlink_is_local(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        c = stack.core
        other = (await c.boards.create({"title": "Autre"})).board_id
        home = await board_on(stack, "Maison")
        pid, vid = await new_source(stack)
        snap = await freeze(stack, pid, vid)
        render = (await c.presentation_artifacts.begin_render(snap, "pdf")).artifact_id
        # only the render is shared with the other Board: the snapshot appears under it, flagged `linked_here: false`
        status, _, _, _ = await core(stack, "POST", f"/v1/workspace/boards/{other}/artifacts/{render}", json={})
        assert status == 201
        _, body, _, _ = await core(stack, "GET", SOURCES.format(other))
        (entry,) = body["sources"][0]["snapshots"]
        assert entry["artifact_id"] == snap and entry["linked_here"] is False
        assert set(entry["board_ids"]) == {home, other}
        _, source, _, _ = await core(stack, "GET", SOURCE.format(pid))
        assert set(source["board_ids"]) == {home, other}
        status, _, _, _ = await core(stack, "DELETE", f"/v1/workspace/boards/{other}/artifacts/{render}")
        assert status == 200
        _, after, _, _ = await core(stack, "GET", SOURCES.format(other))
        assert after["sources"] == []
        _, still, _, _ = await core(stack, "GET", SOURCES.format(home))
        assert still["sources"][0]["snapshots"][0]["renders"][0]["artifact_id"] == render


async def test_a_presentation_id_is_never_a_board_link_and_unknown_sources_say_so(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        board = (await stack.core.boards.create({"title": "B"})).board_id
        pid, _ = await new_source(stack)
        status, body, _, _ = await core(stack, "POST", f"/v1/workspace/boards/{board}/artifacts/{pid}", json={})
        assert status == 400 and body["error"]["code"] == "invalid_artifact"  # no phantom link
        _, bare, _, _ = await core(stack, "GET", f"/v1/workspace/boards/{board}")
        assert bare["artifacts"]["linked"] == 0 and bare["legacy_artifact_refs"]["items"] == []
        status, body, _, _ = await core(stack, "GET", SOURCE.format("pst_" + "0" * 32))
        assert status == 200 and body["source"] == {"exists": False} and body["snapshots"] == []
        status, body, _, _ = await core(stack, "GET", SOURCE.format("nope"))
        assert status == 404 and body["error"]["code"] == "presentation_studio_unknown_presentation"


async def test_a_frozen_presentation_never_enters_the_legacy_refs_of_its_board(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        board = await board_on(stack, "Own")
        pid, vid = await new_source(stack)
        snap = await freeze(stack, pid, vid)
        _, inspected, _, _ = await core(stack, "GET", f"/v1/workspace/boards/{board}")
        assert inspected["artifacts"]["linked"] == 1 and inspected["legacy_artifact_refs"]["items"] == []
        _, relations, _, _ = await core(stack, "GET", f"/v1/workspace/artifacts/{snap}/relations")
        assert [(x["board_id"], x["origin"]) for x in relations["boards"]["items"]] == [(board, "active_board")]


async def test_a_row_without_provenance_is_flagged_and_does_not_hide_the_others(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        c = stack.core
        board = await board_on(stack, "B")
        pid, vid = await new_source(stack)
        snap = await freeze(stack, pid, vid)
        bad = await c.artifacts.create(kind=ArtifactKind.PRESENTATION_SNAPSHOT, source="presentation_studio",
                                       payload_name="snapshot.zip", metadata={})
        _, body, _, _ = await core(stack, "GET", SOURCES.format(board))
        assert [x["artifact_id"] for x in body["unreadable"]] == [bad.artifact_id]
        assert body["sources"][0]["snapshots"][0]["artifact_id"] == snap


async def test_an_unreadable_source_document_flags_the_source_and_keeps_the_board_readable(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        board = await board_on(stack, "B")
        pid, vid = await new_source(stack)
        snap = await freeze(stack, pid, vid)
        (stack.data_root / "presentations" / pid / "presentation.json").write_text("{not json", encoding="utf-8")
        status, body, raw, _ = await core(stack, "GET", SOURCES.format(board))
        assert status == 200, body
        group = body["sources"][0]
        assert group["source"]["exists"] is None and group["source"]["unreadable"]
        assert group["snapshots"][0]["artifact_id"] == snap and group["snapshots"][0]["stale"] is None
        assert_clean(stack, raw)


async def test_the_workspace_relay_serves_both_reads_and_the_kind_filter_knows_the_new_kinds(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        board = await board_on(stack, "R")
        pid, vid = await new_source(stack)
        snap = await freeze(stack, pid, vid)
        status, body, _ = await stack.call("GET", f"/api/workspace/boards/{board}/presentation-sources")
        assert status == 200 and body["sources"][0]["snapshots"][0]["artifact_id"] == snap
        status, body, _ = await stack.call("GET", f"/api/workspace/presentation-sources/{pid}")
        assert status == 200 and body["board_ids"] == [board]
        status, body, _ = await stack.call("GET", "/api/workspace/artifacts",
                                           params={"board_id": board, "kind": "presentation_snapshot"})
        assert status == 200 and [a["artifact_id"] for a in body["artifacts"]] == [snap]
        status, _, _ = await stack.call("GET", f"/api/workspace/boards/{board}/presentation-sources",
                                        params={"x": "1"})
        assert status == 400


async def test_an_unwired_bridge_is_said_503_never_an_empty_board(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        board = (await stack.core.boards.create({"title": "B"})).board_id
        bound, stack.core.workspace._presentations = stack.core.workspace._presentations, None
        try:
            status, body, _, _ = await core(stack, "GET", SOURCES.format(board))
            assert (status, body["error"]["code"]) == (503, "presentations_unavailable")
            status, body, _, _ = await core(stack, "GET", SOURCE.format("pst_" + "0" * 32))
            assert (status, body["error"]["code"]) == (503, "presentations_unavailable")
        finally:
            stack.core.workspace._presentations = bound

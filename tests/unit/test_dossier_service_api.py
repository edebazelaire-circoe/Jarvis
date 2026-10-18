"""Dossier d'un Board : projection et opérations sémantiques (wheel-dossier-refactor, Slice 05).

Contrat : `docs/dossier.md`. Vraie chaîne (`tests/fakes/capture_stack.py`) et même monde que l'inspection
(`test_workspace_inspection_api.build`) : Board A (mémoire : `summary.md`, `notes/plan.md`, `image.bin`),
Board B, Board archivé. Couvre la « Dossier semantics matrix » (`tasks/.../docs/04-testing-and-quality.md`)
au niveau service **et** API (Core et relais du Control Center).
"""

from __future__ import annotations

import pytest

from jarvis.domain.board_memory import BoardMemoryError, BoardMemoryErrorCode, BoardMemoryPath
from jarvis.domain.dossier import ranger_path
from jarvis.domain.scene import (
    Representation, SceneActor, SceneCommand, SceneCommandOutcome, SceneObjectFields, SceneObjectKind, SceneOp,
    ScenePayload, ScenePayloadItem, Visibility,
)
from jarvis.domain.scene_batch import SelectionChanges
from jarvis.domain.scene_selection import SceneSelection
from jarvis.domain.v2 import utc_now
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_capture_api_protocol import assert_clean, core
from tests.unit.test_workspace_inspection_api import World, build, snapshot
from tests.unit.test_workspace_memory_mutations import Diagnostics

V1 = "/v1/workspace"


async def get(stack: CaptureStack, route: str, **params):
    status, body, raw, _ = await core(stack, "GET", V1 + route, params=params or None)
    assert_clean(stack, raw)
    return status, body


async def post(stack: CaptureStack, path: str, body: dict):
    status, payload, raw, _ = await core(stack, "POST", V1 + path, json=body)
    assert_clean(stack, raw)
    return status, payload


async def put(stack: CaptureStack, object_id: str, *, kind=SceneObjectKind.ARTIFACT, payload: ScenePayload,
              category: str = "research") -> None:
    update = await stack.core.scene.apply(SceneCommand(
        op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id=object_id,
        fields=SceneObjectFields(kind=kind, category=category, payload=payload)))
    assert update.outcome is SceneCommandOutcome.APPLIED, update


async def active(stack: CaptureStack, object_id: str):
    item = (await stack.core.scene.snapshot()).get_object(object_id)
    return item if item is not None and item.active else None


async def on_board_a(stack: CaptureStack) -> World:
    w = await build(stack)
    await stack.core.boards.switch(w.board_a)
    return w


def memory_file(stack: CaptureStack, board_id: str, path: str):
    return stack.data_root / "boards" / board_id / "memory" / path


RESEARCH = ScenePayload(title="Pistes de financement", summary="Trois guichets **possibles**.\nBpifrance d'abord.",
                        items=(ScenePayloadItem(label="Bpifrance", url="https://www.bpifrance.fr"),))


# ------------------------------------------------------------------ 1. liste composée


async def test_list_composes_memory_and_linked_artifacts_once_without_side_effect(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)  # A holds both Artifacts made while it was active (automatic links)
        before = await snapshot(stack)
        status, body = await get(stack, f"/boards/{w.board_a}/dossier")
        assert status == 200, body
        assert await snapshot(stack) == before, "a Dossier read writes nothing"
        ids = [entry["entry_id"] for entry in body["entries"]]
        assert ids[0] == "memory:summary.md", "the Board summary comes first"
        assert sorted(ids) == sorted({"memory:summary.md", "memory:notes/plan.md", "memory:image.bin",
                                      f"artifact:{w.art_derived}", f"artifact:{w.art_audio}"}),             "each source once, no duplicate"
        by_id = {entry["entry_id"]: entry for entry in body["entries"]}
        assert by_id["memory:summary.md"]["kind"] == "memory_summary"
        assert by_id["memory:summary.md"]["title"] == "Résumé du Board"
        assert (by_id["memory:notes/plan.md"]["kind"], by_id["memory:notes/plan.md"]["open"]) == ("note", "text")
        assert by_id["memory:notes/plan.md"]["folder"] == "notes"
        assert by_id["memory:image.bin"]["open"] == "none", "a binary memory file is listed, never pretended open"
        linked = by_id[f"artifact:{w.art_derived}"]
        assert (linked["kind"], linked["open"], linked["preview"]) == ("report", "text", "résumé")
        assert linked["provenance"] == "ajouté automatiquement (Board actif à sa création)" and linked["added_at"]
        assert linked["title"].startswith("Synthèse du "), "a human label, never the raw id"
        assert all("advanced" not in entry for entry in body["entries"]), "default view is human (D14)"
        assert body["board"] == {"board_id": w.board_a, "title": "Projet A", "board_kind": "meeting",
                                 "status": "active", "writable": True}
        assert body["sources"]["artifacts"]["linked"] == 2 and body["sources"]["memory"]["files"] == 3

        _, advanced = await get(stack, f"/boards/{w.board_a}/dossier", advanced="true")
        extra = {e["entry_id"]: e["advanced"] for e in advanced["entries"]}
        assert extra["memory:notes/plan.md"] == {"locator": f"boards/{w.board_a}/memory/notes/plan.md"}
        assert extra[f"artifact:{w.art_derived}"]["link_origin"] == "active_board"

        _, page = await get(stack, f"/boards/{w.board_a}/dossier", limit="1")
        assert len(page["entries"]) == 1 and page["truncated"] is True and page["total"] == 5

        await stack.core.workspace.artifact_link(w.board_a, w.art_closed)
        _, linked_now = await get(stack, f"/boards/{w.board_a}/dossier")
        added = next(e for e in linked_now["entries"] if e["entry_id"] == f"artifact:{w.art_closed}")
        assert added["provenance"] == "ajouté au Dossier"


async def test_list_since_keeps_what_changed_and_the_relay_is_identical(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        mark = utc_now()
        await stack.core.workspace.memory_write(w.board_a, path="notes/nouveau.md", content="neuf\n")
        _, body = await get(stack, f"/boards/{w.board_a}/dossier", since=mark.isoformat())
        assert [e["entry_id"] for e in body["entries"]] == ["memory:notes/nouveau.md"]
        assert body["since"] == mark.isoformat()
        status, relayed, _ = await stack.call("GET", f"/api/workspace/boards/{w.board_a}/dossier",
                                              params={"since": mark.isoformat()})
        assert status == 200 and relayed == body


async def test_archived_board_dossier_stays_readable_and_refuses_writes(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        status, body = await get(stack, f"/boards/{w.board_archived}/dossier")
        assert status == 200 and [e["entry_id"] for e in body["entries"]] == ["memory:vieux.md"]
        assert body["board"]["writable"] is False
        status, entry = await get(stack, f"/boards/{w.board_archived}/dossier/entry", id="memory:vieux.md")
        assert status == 200 and entry["entry"]["title"] == "vieux"
        await put(stack, "brain-artifact-x", payload=RESEARCH)
        status, refused = await post(stack, f"/boards/{w.board_archived}/dossier/ranger",
                                     {"object_ids": ["brain-artifact-x"]})
        assert (status, refused["error"]["code"]) == (409, "board_archived"), refused
        status, refused = await post(stack, f"/boards/{w.board_archived}/dossier/present",
                                     {"entry_id": "memory:vieux.md"})
        assert (status, refused["error"]["code"]) == (409, "board_archived")
        assert await active(stack, "brain-artifact-x") is not None


async def test_entry_resolution_and_its_refusals(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        base = f"/boards/{w.board_a}/dossier/entry"
        status, body = await get(stack, base, id="memory:notes/plan.md")
        assert status == 200 and body["entry"]["entry_id"] == "memory:notes/plan.md"
        for raw, expected in (("memory:absent.md", (404, "dossier_entry_not_found")),
                              ("memory:notes", (404, "dossier_entry_not_found")),
                              (f"artifact:{w.art_closed}", (404, "dossier_entry_not_found")),  # linked to B, not A
                              ("memory:../x", (400, "dossier_entry_invalid")),
                              ("fichier:x", (400, "dossier_entry_invalid"))):
            status, refused = await get(stack, base, id=raw)
            assert (status, refused["error"]["code"]) == expected, (raw, refused)
        status, body = await get(stack, f"/boards/{w.board_b}/dossier/entry", id=f"artifact:{w.art_audio}")
        assert status == 200 and body["entry"]["kind"] == "transcript"


# ------------------------------------------------------------------ 2-3. source durable et Ranger


async def test_ranger_materializes_ephemeral_content_once_then_removes_the_representation(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        await put(stack, "brain-artifact-r1", payload=RESEARCH)
        item = await active(stack, "brain-artifact-r1")
        status, backing = await get(stack, f"/boards/{w.board_a}/dossier/backing", object_id="brain-artifact-r1")
        expected_path = ranger_path(item).value
        assert backing["objects"] == [{"object_id": "brain-artifact-r1", "backing": "content",
                                       "entry_id": f"memory:{expected_path}", "rangeable": True}]
        assert backing["board_active"] is True and "board_code" not in backing
        assert await active(stack, "brain-artifact-r1") is not None, "backing is a read"

        status, body = await post(stack, f"/boards/{w.board_a}/dossier/ranger", {"object_ids": ["brain-artifact-r1"]})
        assert status == 200, body
        [result] = body["results"]
        assert result["status"] == "stored" and result["action"] == "materialized" and result["durable"] is True
        assert result["archived"] is True and result["entry_id"] == f"memory:{expected_path}"
        assert body["stored"] == 1 and body["refused"] == 0 and body["revision"] > 0
        assert await active(stack, "brain-artifact-r1") is None, "representation removed after durability"
        text = memory_file(stack, w.board_a, expected_path).read_text(encoding="utf-8")
        assert text.startswith("# Pistes de financement\n\nTrois guichets **possibles**.\nBpifrance d'abord.")
        assert "- Bpifrance (https://www.bpifrance.fr)" in text and "Rangé depuis le Board le" in text
        assert "object_id=brain-artifact-r1" in text and "origin=user" in text
        _, listed = await get(stack, f"/boards/{w.board_a}/dossier")
        assert f"memory:{expected_path}" in [e["entry_id"] for e in listed["entries"]], "Ranger -> Dossier entry"


async def test_ranger_never_overwrites_a_file_that_holds_another_body(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        await put(stack, "brain-artifact-r2", payload=RESEARCH)
        item = await active(stack, "brain-artifact-r2")
        path = ranger_path(item).value
        await stack.core.workspace.memory_write(w.board_a, path=path, content="déjà rangé, puis corrigé\n")
        status, body = await post(stack, f"/boards/{w.board_a}/dossier/ranger", {"object_ids": ["brain-artifact-r2"]})
        [result] = body["results"]
        variant = ranger_path(item, content_variant=True).value
        assert status == 200 and (result["action"], result["path"], result["archived"]) == ("materialized", variant, True)
        assert result["entry_id"] == f"memory:{variant}", "the answer names the file that holds the shown content"
        assert memory_file(stack, w.board_a, path).read_text(encoding="utf-8") == "déjà rangé, puis corrigé\n"
        assert "Bpifrance d'abord." in memory_file(stack, w.board_a, variant).read_text(encoding="utf-8")


async def _ranger_refused_by_the_scene(stack, monkeypatch, board_id: str, object_id: str) -> dict:
    """Ranger dont le retrait est refusé par le vrai réducteur (acteur `runtime`) : durable, encore affiché."""

    scene = stack.core.scene
    real = scene.apply_if

    async def refusing(plan):
        command = plan(await scene.snapshot())
        return await real(lambda _s: SceneCommand(op=command.op, actor=SceneActor.RUNTIME, selection=command.selection))

    monkeypatch.setattr(scene, "apply_if", refusing)
    _, body = await post(stack, f"/boards/{board_id}/dossier/ranger", {"object_ids": [object_id]})
    monkeypatch.setattr(scene, "apply_if", real)
    return body["results"][0]


async def test_a_second_ranger_of_the_same_content_confirms_the_first_file(tmp_path, monkeypatch):
    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        await put(stack, "brain-artifact-same", payload=RESEARCH)
        first = await _ranger_refused_by_the_scene(stack, monkeypatch, w.board_a, "brain-artifact-same")
        assert (first["action"], first["code"]) == ("materialized", "dossier_archive_failed")
        before = memory_file(stack, w.board_a, first["path"]).read_bytes()
        _, body = await post(stack, f"/boards/{w.board_a}/dossier/ranger", {"object_ids": ["brain-artifact-same"]})
        [second] = body["results"]
        assert (second["action"], second["path"], second["archived"]) == ("confirmed", first["path"], True)
        assert memory_file(stack, w.board_a, first["path"]).read_bytes() == before
        assert len(list(memory_file(stack, w.board_a, "notes").glob("pistes-de-financement-*.md"))) == 1


async def test_same_title_changed_content_second_ranger_keeps_both_versions(tmp_path, monkeypatch):
    """QA S05 B1 : même titre, contenu modifié après un retrait refusé ; le second Ranger garde la version affichée."""

    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        await put(stack, "brain-artifact-b1", payload=RESEARCH)
        first = await _ranger_refused_by_the_scene(stack, monkeypatch, w.board_a, "brain-artifact-b1")
        old_text = memory_file(stack, w.board_a, first["path"]).read_text(encoding="utf-8")
        edited = ScenePayload(title=RESEARCH.title, summary="Version corrigée : Bpifrance puis la Région.")
        await put(stack, "brain-artifact-b1", payload=edited)
        _, body = await post(stack, f"/boards/{w.board_a}/dossier/ranger", {"object_ids": ["brain-artifact-b1"]})
        [second] = body["results"]
        assert second["action"] == "materialized" and second["path"] != first["path"] and second["archived"] is True
        assert "Version corrigée" in memory_file(stack, w.board_a, second["path"]).read_text(encoding="utf-8")
        assert memory_file(stack, w.board_a, first["path"]).read_text(encoding="utf-8") == old_text, "old file intact"
        assert await active(stack, "brain-artifact-b1") is None


async def test_ranger_confirms_or_links_durable_sources(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        plan = str(memory_file(stack, w.board_a, "notes/plan.md"))
        await put(stack, "brain-window-file", kind=SceneObjectKind.WINDOW, category="dossier",
                  payload=ScenePayload(title="plan", source_path=plan))
        await put(stack, "brain-window-art", kind=SceneObjectKind.WINDOW, category="dossier",
                  payload=ScenePayload(title="note", registry_artifact_id=w.art_closed))
        status, body = await post(stack, f"/boards/{w.board_a}/dossier/ranger",
                                  {"object_ids": ["brain-window-file", "brain-window-art"], "origin": "brain"})
        assert status == 200, body
        first, second = body["results"]
        assert (first["backing"], first["action"], first["entry_id"]) == ("memory", "confirmed", "memory:notes/plan.md")
        assert (second["backing"], second["action"], second["entry_id"]) == ("artifact", "linked",
                                                                              f"artifact:{w.art_closed}")
        assert first["archived"] and second["archived"]
        _, listed = await get(stack, f"/boards/{w.board_a}/dossier")
        assert f"artifact:{w.art_closed}" in [e["entry_id"] for e in listed["entries"]], "now linked to A"


async def test_ranger_refusals_leave_every_representation_visible(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        sink = Diagnostics()
        stack.core.dossier._diagnostics = sink
        outside = str(tmp_path / "ailleurs.md")
        other_board = str(memory_file(stack, w.board_archived, "vieux.md"))
        await put(stack, "brain-group-g", kind=SceneObjectKind.GROUP, category="groupe",
                  payload=ScenePayload(title="Groupe"))
        await put(stack, "brain-window-empty", kind=SceneObjectKind.WINDOW, category="note", payload=ScenePayload())
        await put(stack, "brain-window-out", kind=SceneObjectKind.WINDOW, category="note",
                  payload=ScenePayload(title="dehors", source_path=outside))
        await put(stack, "brain-window-other", kind=SceneObjectKind.WINDOW, category="note",
                  payload=ScenePayload(title="autre Board", source_path=other_board))
        await put(stack, "brain-window-gone", kind=SceneObjectKind.WINDOW, category="note",
                  payload=ScenePayload(title="disparu", source_path=str(memory_file(stack, w.board_a, "x.md"))))
        ids = ["brain-group-g", "brain-window-empty", "brain-window-out", "brain-window-other", "brain-window-gone",
               "brain-nope"]
        status, body = await post(stack, f"/boards/{w.board_a}/dossier/ranger", {"object_ids": ids})
        assert status == 200 and body["stored"] == 0 and body["refused"] == 6 and body["revision"] is None
        assert [r["code"] for r in body["results"]] == [
            "dossier_not_eligible", "dossier_nothing_to_keep", "dossier_source_outside_board",
            "dossier_source_outside_board", "dossier_source_missing", "dossier_object_not_found"]
        assert all(r["message"] and not r["archived"] and not r["durable"] for r in body["results"])
        assert all("vous" in r["message"] or "Board" in r["message"] for r in body["results"])
        for object_id in ids[:-1]:
            assert await active(stack, object_id) is not None, object_id
        assert not (memory_file(stack, w.board_a, "notes")).joinpath("ailleurs.md").exists(), "never copied"
        refusals = [e for e in sink.events if e["kind"] == "core.dossier.ranger_refused"]
        assert len(refusals) == 6 and all(e["level"] == "warning" for e in refusals)


async def test_ranger_keeps_the_representation_when_durability_fails(tmp_path, monkeypatch):
    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        await put(stack, "brain-artifact-f", payload=RESEARCH)

        async def refuse(*_args, **_kwargs):
            raise BoardMemoryError(BoardMemoryErrorCode.MEMORY_CONFLICT, "notes: a file where a folder is expected")

        monkeypatch.setattr(stack.core.workspace, "memory_write", refuse)
        status, body = await post(stack, f"/boards/{w.board_a}/dossier/ranger", {"object_ids": ["brain-artifact-f"]})
        assert status == 200
        [result] = body["results"]
        assert (result["status"], result["code"], result["durable"], result["archived"]) == (
            "refused", "memory_conflict", False, False)
        assert "reste sur le Board" in result["message"]
        assert await active(stack, "brain-artifact-f") is not None


async def test_ranger_says_when_the_scene_refuses_the_removal_after_durability(tmp_path, monkeypatch):
    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        await put(stack, "brain-artifact-a", payload=RESEARCH)
        scene = stack.core.scene
        real = scene.apply_if

        async def refusing(plan):
            snapshot = await scene.snapshot()
            command = plan(snapshot)
            assert command is not None and command.op is SceneOp.ARCHIVE_SELECTION
            # Un acteur `runtime` n'a pas `archive_selection` : le vrai réducteur refuse.
            return await real(lambda _s: SceneCommand(op=command.op, actor=SceneActor.RUNTIME,
                                                      selection=command.selection))

        monkeypatch.setattr(scene, "apply_if", refusing)
        status, body = await post(stack, f"/boards/{w.board_a}/dossier/ranger", {"object_ids": ["brain-artifact-a"]})
        [result] = body["results"]
        assert (result["status"], result["durable"], result["archived"], result["code"]) == (
            "stored", True, False, "dossier_archive_failed"), result
        assert "reste affiché" in result["message"]
        assert await active(stack, "brain-artifact-a") is not None
        assert memory_file(stack, w.board_a, result["path"]).is_file(), "durable copy kept"


async def test_ranger_never_removes_content_changed_while_it_was_stored(tmp_path, monkeypatch):
    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        await put(stack, "brain-artifact-c", payload=RESEARCH)
        workspace = stack.core.workspace
        real = workspace.memory_write

        async def write_then_edit(*args, **kwargs):
            written = await real(*args, **kwargs)
            await put(stack, "brain-artifact-c", payload=ScenePayload(title=RESEARCH.title, summary="éditée entre-temps"))
            return written

        monkeypatch.setattr(workspace, "memory_write", write_then_edit)
        _, body = await post(stack, f"/boards/{w.board_a}/dossier/ranger", {"object_ids": ["brain-artifact-c"]})
        [result] = body["results"]
        assert (result["durable"], result["archived"], result["code"]) == (True, False, "dossier_changed_meanwhile")
        assert (await active(stack, "brain-artifact-c")).payload.summary == "éditée entre-temps"
        monkeypatch.setattr(workspace, "memory_write", real)
        # « Rangez-le de nouveau » : même titre, autre corps -> un second fichier, l'ancien reste, puis le retrait.
        _, again = await post(stack, f"/boards/{w.board_a}/dossier/ranger", {"object_ids": ["brain-artifact-c"]})
        [second] = again["results"]
        assert (second["action"], second["archived"]) == ("materialized", True) and second["path"] != result["path"]
        assert "éditée entre-temps" in memory_file(stack, w.board_a, second["path"]).read_text(encoding="utf-8")
        assert "Bpifrance d'abord." in memory_file(stack, w.board_a, result["path"]).read_text(encoding="utf-8")


async def test_ranger_and_present_need_the_active_board(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)  # Board B active
        await put(stack, "brain-artifact-n", payload=RESEARCH)
        status, refused = await post(stack, f"/boards/{w.board_a}/dossier/ranger", {"object_ids": ["brain-artifact-n"]})
        assert (status, refused["error"]["code"]) == (409, "dossier_board_not_active")
        status, refused = await post(stack, f"/boards/{w.board_a}/dossier/present", {"entry_id": "memory:summary.md"})
        assert (status, refused["error"]["code"]) == (409, "dossier_board_not_active")
        status, refused = await post(stack, f"/boards/{w.board_b}/dossier/ranger", {"object_ids": []})
        assert (status, refused["error"]["code"]) == (400, "invalid_request")
        assert await active(stack, "brain-artifact-n") is not None


async def test_masquer_never_creates_a_dossier_entry_and_show_hidden_is_visibility_only(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        await put(stack, "brain-artifact-h", payload=RESEARCH)
        _, before = await get(stack, f"/boards/{w.board_a}/dossier")
        files_before = sorted(p.name for p in memory_file(stack, w.board_a, "").rglob("*"))
        for visibility in (Visibility.HIDDEN, Visibility.VISIBLE):
            update = await stack.core.scene.apply(SceneCommand(
                op=SceneOp.PATCH_SELECTION, actor=SceneActor.USER, selection=SceneSelection(ids=("brain-artifact-h",)),
                changes=SelectionChanges(visibility=visibility)))
            assert update.outcome is SceneCommandOutcome.APPLIED
            _, after = await get(stack, f"/boards/{w.board_a}/dossier")
            assert after["entries"] == before["entries"]
            assert sorted(p.name for p in memory_file(stack, w.board_a, "").rglob("*")) == files_before
        assert (await active(stack, "brain-artifact-h")).payload == RESEARCH


# ------------------------------------------------------------------ 4. Afficher sur le Board


async def test_present_points_at_the_same_source_and_reuses_its_representation(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        status, shown = await post(stack, f"/boards/{w.board_a}/dossier/present", {"entry_id": "memory:notes/plan.md"})
        assert status == 201 and shown["created"] is True and shown["representation"] == "window", shown
        item = await active(stack, shown["object_id"])
        assert item.kind is SceneObjectKind.WINDOW and item.category == "dossier"
        assert item.payload.source_path == str(memory_file(stack, w.board_a, "notes/plan.md"))
        assert item.payload.summary == "" or "étape" in item.payload.summary, "the watcher reads, nothing copied"
        size_before = memory_file(stack, w.board_a, "notes/plan.md").stat().st_size

        status, again = await post(stack, f"/boards/{w.board_a}/dossier/present",
                                   {"entry_id": "memory:notes/plan.md", "origin": "brain"})
        assert status == 200 and again["reused"] is True and again["object_id"] == shown["object_id"]
        assert again["revision"] is None, "already shown as asked: nothing written"
        await stack.core.scene.apply(SceneCommand(
            op=SceneOp.PATCH_SELECTION, actor=SceneActor.USER, selection=SceneSelection(ids=(shown["object_id"],)),
            changes=SelectionChanges(visibility=Visibility.HIDDEN)))
        status, revealed = await post(stack, f"/boards/{w.board_a}/dossier/present",
                                      {"entry_id": "memory:notes/plan.md", "representation": "capsule"})
        assert status == 200 and revealed["reused"] is True
        item = await active(stack, shown["object_id"])
        assert (item.visibility, item.representation) == (Visibility.VISIBLE, Representation.CAPSULE)
        assert memory_file(stack, w.board_a, "notes/plan.md").stat().st_size == size_before

        status, art = await post(stack, f"/boards/{w.board_a}/dossier/present",
                                 {"entry_id": f"artifact:{w.art_derived}"})
        assert status == 201
        item = await active(stack, art["object_id"])
        assert item.payload.registry_artifact_id == w.art_derived and item.payload.summary == ""
        status, refused = await post(stack, f"/boards/{w.board_a}/dossier/present", {"entry_id": "memory:absent.md"})
        assert (status, refused["error"]["code"]) == (404, "dossier_entry_not_found")
        status, refused = await post(stack, f"/boards/{w.board_a}/dossier/present",
                                     {"entry_id": "memory:notes/plan.md", "representation": "plein"})
        assert (status, refused["error"]["code"]) == (400, "invalid_request")

        # Ranger d'une représentation présentée : la source est la même, rien n'est recopié.
        _, ranged = await post(stack, f"/boards/{w.board_a}/dossier/ranger", {"object_ids": [art["object_id"]]})
        assert ranged["results"][0]["action"] == "confirmed" and ranged["results"][0]["archived"] is True


async def test_relay_ranger_and_present_match_core(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        await put(stack, "brain-artifact-relay", payload=RESEARCH)
        status, body, text = await stack.call("POST", f"/api/workspace/boards/{w.board_a}/dossier/ranger",
                                              json={"object_ids": ["brain-artifact-relay"]})
        assert status == 200 and body["results"][0]["status"] == "stored", body
        assert str(tmp_path) not in text
        status, body, _ = await stack.call("POST", f"/api/workspace/boards/{w.board_a}/dossier/present",
                                           json={"entry_id": body["results"][0]["entry_id"]})
        assert status == 201 and body["created"] is True
        status, body, _ = await stack.call("GET", f"/api/workspace/boards/{w.board_a}/dossier/backing",
                                           params=[("object_id", body["object_id"]), ("object_id", "x")])
        assert status == 200 and [o["backing"] for o in body["objects"]] == ["memory", "refused"]
        status, refused, _ = await stack.call("POST", f"/api/workspace/boards/{w.board_a}/dossier/ranger",
                                              json={"object_ids": ["x"]}, headers={"Origin": "https://evil.example"})
        assert status == 403, refused
        status, refused, _ = await stack.call("POST", "/api/dossier/navigation/commands",
                                              json={"board_id": w.board_a, "entry_id": "memory:summary.md"},
                                              headers={"Origin": "https://evil.example"})
        assert status == 403, "the navigation channel is guarded like the workspace"


async def test_a_human_edit_is_what_the_agent_reads_next(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        _, read = await get(stack, f"/boards/{w.board_a}/memory/read", path="notes/plan.md")
        status, _, _ = await stack.call("POST", f"/api/workspace/boards/{w.board_a}/memory/write", json={
            "path": "notes/plan.md", "content": "étape 1 corrigée\n", "mode": "replace",
            "expected_sha256": read["sha256"]})
        assert status == 200
        _, again = await get(stack, f"/boards/{w.board_a}/memory/read", path="notes/plan.md")
        assert again["text"] == "étape 1 corrigée\n"
        _, entry = await get(stack, f"/boards/{w.board_a}/dossier/entry", id="memory:notes/plan.md")
        assert entry["entry"]["size"] == len("étape 1 corrigée\n".encode())


@pytest.mark.parametrize("raw", ["memory:", "artifact:jart_", "memory:a//b"])
async def test_malformed_entry_ids_are_refused_by_present(tmp_path, raw):
    async with CaptureStack(tmp_path) as stack:
        w = await on_board_a(stack)
        status, refused = await post(stack, f"/boards/{w.board_a}/dossier/present", {"entry_id": raw})
        assert (status, refused["error"]["code"]) == (400, "dossier_entry_invalid")


def test_ranger_path_is_deterministic_and_safe():
    from jarvis.domain.scene import SceneConstraints, SceneObject, PlacedBy

    item = SceneObject(object_id="brain-artifact-1", kind=SceneObjectKind.ARTIFACT, category="research",
                       constraints=SceneConstraints(placed_by=PlacedBy.BRAIN), origin=SceneActor.BRAIN,
                       payload=ScenePayload(title="Éléments d'été : CON/aux?"))
    path = ranger_path(item)
    assert path == ranger_path(item) and path.value.startswith("notes/elements-d-ete-con-aux-")
    assert isinstance(path, BoardMemoryPath)


def test_the_registry_artifact_reference_is_an_optional_payload_key():
    from jarvis.runtime.display_mcp import _merged_payload

    bound = ScenePayload(title="audio", registry_artifact_id="jart_" + "a" * 32)
    wire = bound.to_payload()
    assert wire["registry_artifact_id"] == "jart_" + "a" * 32 and ScenePayload.from_payload(wire) == bound
    assert "registry_artifact_id" not in ScenePayload(title="x").to_payload(), "emitted only when set"
    with pytest.raises(ValueError, match="registry_artifact_id"):
        ScenePayload(registry_artifact_id="artifact-1")
    from jarvis.domain.artifacts import ARTIFACT_ID_PREFIX
    from jarvis.domain.scene import REGISTRY_ARTIFACT_ID_PREFIX

    assert REGISTRY_ARTIFACT_ID_PREFIX == ARTIFACT_ID_PREFIX, "one id shape for registry Artifacts"
    renamed = _merged_payload(bound, title="audio du lundi", summary=None, items=None)
    assert renamed.registry_artifact_id == bound.registry_artifact_id, "a brain edit keeps the Dossier link"


async def test_backing_says_when_the_board_is_not_the_displayed_one(tmp_path):
    """Slice 06 (polish S05 8) : l'aperçu ne promet pas « rangeable » quand Ranger refuserait 409."""

    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)  # B actif
        await put(stack, "brain-artifact-inactive", payload=RESEARCH)
        status, backing = await get(stack, f"/boards/{w.board_a}/dossier/backing", object_id="brain-artifact-inactive")
        assert status == 200 and backing["objects"][0]["rangeable"] is True, "per-object backing is unchanged"
        assert backing["board_active"] is False and backing["board_code"] == "dossier_board_not_active"
        assert "Board actif" in backing["board_message"]
        status, refused = await post(stack, f"/boards/{w.board_a}/dossier/ranger",
                                     {"object_ids": ["brain-artifact-inactive"]})
        assert status == 409 and refused["error"]["code"] == "dossier_board_not_active"
        status, archived = await get(stack, f"/boards/{w.board_archived}/dossier/backing",
                                     object_id="brain-artifact-inactive")
        assert status == 200 and archived["board_code"] == "board_archived"

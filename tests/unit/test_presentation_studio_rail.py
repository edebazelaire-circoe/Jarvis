"""Rail des presentations : masquer / archiver (rail.json), etat de travail (bleu, vert, orange), demandes d'ecran, outils MCP.

Vrai Core derriere le vrai protocole (`Core`), vrai magasin de fichiers. Contrat : `docs/presentation-studio.md` > *Rail des presentations*.
"""

from __future__ import annotations

import json

import pytest

from jarvis.core.presentation_studio_rail import (
    DONE, PROBLEM, RAIL_SCHEMA, WORKING, PresentationWorkTracker, RailFlags, parse_rail,
)
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.runtime.presentation_studio_mcp_support import PresentationToolError
from tests.unit.presentation_studio_mcp_world import S1, open_world
from tests.unit.test_presentation_studio_routes import Core

PID = "pst_" + "0" * 32


class Tick:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


# ------------------------------------------------------------------ l'etat de travail (memoire)

def test_a_presentation_nobody_touched_is_done():
    tracker = PresentationWorkTracker(clock=Tick())
    assert tracker.snapshot(PID)["state"] == DONE


def test_begin_is_blue_until_the_window_runs_out_then_green():
    clock = Tick()
    tracker = PresentationWorkTracker(clock=clock, ttl_s=90, settle_s=20)
    tracker.report(PID, "begin", label="presentation_edit")
    assert tracker.snapshot(PID)["state"] == WORKING and tracker.snapshot(PID)["label"] == "presentation_edit"
    clock.t += 89
    assert tracker.snapshot(PID)["state"] == WORKING
    clock.t += 2
    assert tracker.snapshot(PID)["state"] == DONE


def test_success_keeps_the_blue_a_little_then_settles():
    clock = Tick()
    tracker = PresentationWorkTracker(clock=clock, ttl_s=90, settle_s=20)
    tracker.report(PID, "begin")
    tracker.report(PID, "success")
    clock.t += 19
    assert tracker.snapshot(PID)["state"] == WORKING
    clock.t += 2
    assert tracker.snapshot(PID)["state"] == DONE


def test_failure_is_orange_and_sticks_until_acknowledged_or_new_work():
    clock = Tick()
    tracker = PresentationWorkTracker(clock=clock)
    tracker.report(PID, "begin")
    tracker.report(PID, "failure", code="presentation_studio_storage_io", message="disque plein")
    clock.t += 10_000
    snap = tracker.snapshot(PID)
    assert snap["state"] == PROBLEM and snap["code"] == "presentation_studio_storage_io" and snap["message"] == "disque plein"
    tracker.report(PID, "ack")
    assert tracker.snapshot(PID)["state"] == DONE
    tracker.fail(PID, "x")
    tracker.report(PID, "begin")
    assert tracker.snapshot(PID)["state"] == WORKING and "code" not in tracker.snapshot(PID)


def test_an_edit_commit_extends_work_in_progress_but_never_starts_it():
    clock = Tick()
    tracker = PresentationWorkTracker(clock=clock, ttl_s=30, settle_s=20)
    tracker.touch(PID)  # the user's own edit: not agent work
    assert tracker.snapshot(PID)["state"] == DONE
    tracker.report(PID, "begin")
    clock.t += 25
    tracker.touch(PID)
    clock.t += 15
    assert tracker.snapshot(PID)["state"] == WORKING


def test_the_revision_moves_only_when_something_visible_changes():
    clock = Tick()
    tracker = PresentationWorkTracker(clock=clock, ttl_s=30, settle_s=20)
    before = tracker.revision
    tracker.report(PID, "begin")
    assert tracker.revision > before
    clock.t += 31
    tracker.snapshot(PID)
    settled = tracker.revision
    tracker.snapshot(PID)
    assert tracker.revision == settled


def test_an_unknown_event_is_refused():
    with pytest.raises(PresentationStudioError):
        PresentationWorkTracker(clock=Tick()).report(PID, "explode")


# ------------------------------------------------------------------ rail.json

def test_rail_document_roundtrip_and_refusals():
    assert parse_rail("") == RailFlags()
    flags = RailFlags(True, False, "2026-10-10T10:00:00Z", None)
    assert parse_rail(json.dumps(flags.to_document())) == flags
    with pytest.raises(PresentationStudioError) as newer:
        parse_rail(json.dumps({"schema": RAIL_SCHEMA, "schema_version": 99, "hidden": False, "archived": False}))
    assert newer.value.code is C.UNSUPPORTED_SCHEMA_VERSION
    for bad in ("{", "[]", json.dumps({"schema": "other", "schema_version": 1}),
                json.dumps({"schema": RAIL_SCHEMA, "schema_version": 1, "hidden": "yes", "archived": False})):
        with pytest.raises(PresentationStudioError) as caught:
            parse_rail(bad)
        assert caught.value.code is C.CORRUPT_DOCUMENT


# ------------------------------------------------------------------ de bout en bout (Core reel)

async def create(core: Core, title: str) -> str:
    status, made = await core.call("POST", "", json={"title": title})
    assert status == 201, made
    return made["presentation"]["presentation_id"]


async def test_hide_show_archive_restore_persist_beside_the_manifest(tmp_path):
    async with Core(tmp_path) as core:
        a, b = await create(core, "Alpha"), await create(core, "Beta")
        listing = await core.client.presentation_studio_rail()
        assert {r["presentation_id"] for r in listing["presentations"]} == {a, b}
        assert all(r["hidden"] is False and r["archived"] is False and r["work"]["state"] == "done" for r in listing["presentations"])

        hidden = await core.client.presentation_studio_rail_act(a, {"action": "hide", "actor": "user"})
        assert hidden["changed"] is True and hidden["hidden"] is True
        assert (await core.client.presentation_studio_rail_act(a, {"action": "hide", "actor": "user"}))["changed"] is False
        rows = {r["presentation_id"]: r for r in (await core.client.presentation_studio_rail())["presentations"]}
        assert rows[a]["hidden"] is True and rows[b]["hidden"] is False
        # the manifest is untouched: no schema bump, only a file beside it
        status, view = await core.call("GET", f"/{a}")
        assert status == 200 and view["presentation"]["schema_version"] == 3 and view["presentation"]["revision"] == 1
        rail_file = next(tmp_path.rglob(f"{a}/rail.json"))
        assert json.loads(rail_file.read_text(encoding="utf-8"))["hidden"] is True

        shown = await core.client.presentation_studio_rail_act(a, {"action": "show", "actor": "user"})
        assert shown["hidden"] is False
        archived = await core.client.presentation_studio_rail_act(a, {"action": "archive", "actor": "user"})
        assert archived["archived"] is True and archived["restorable"] is True
        rows = (await core.client.presentation_studio_rail())["presentations"]
        assert rows[-1]["presentation_id"] == a and rows[-1]["archived"] is True  # archived sorts last
        status, still = await core.call("GET", f"/{a}")
        assert status == 200, "archiving never deletes the document"
        restored = await core.client.presentation_studio_rail_act(a, {"action": "restore", "actor": "user"})
        assert restored["archived"] is False


async def test_rail_state_survives_a_core_restart(tmp_path):
    async with Core(tmp_path) as core:
        pid = await create(core, "Survivante")
        await core.client.presentation_studio_rail_act(pid, {"action": "hide", "actor": "user"})
    async with Core(tmp_path) as core:
        rows = (await core.client.presentation_studio_rail())["presentations"]
        assert [(r["presentation_id"], r["hidden"]) for r in rows] == [(pid, True)]


async def test_the_brain_cannot_archive_without_the_users_yes(tmp_path):
    async with Core(tmp_path) as core:
        pid = await create(core, "Gardee")
        with pytest.raises(Exception) as caught:
            await core.client.presentation_studio_rail_act(pid, {"action": "archive", "actor": "brain"})
        assert "presentation_studio_confirmation_required" in str(getattr(caught.value, "code", "")) + str(caught.value)
        done = await core.client.presentation_studio_rail_act(pid, {"action": "archive", "actor": "brain", "confirmed": True})
        assert done["archived"] is True


async def test_unknown_presentation_and_bad_bodies_are_coded(tmp_path):
    async with Core(tmp_path) as core:
        with pytest.raises(Exception) as unknown:
            await core.client.presentation_studio_rail_act(PID, {"action": "hide", "actor": "user"})
        assert getattr(unknown.value, "status", None) == 404
        pid = await create(core, "Corps")
        for body in ({"action": "explode"}, {"action": "hide", "stray": 1}, {"action": "hide", "actor": "root"},
                     {"action": "rename"}, {"action": "archive", "confirmed": "yes"}):
            with pytest.raises(Exception) as bad:
                await core.client.presentation_studio_rail_act(pid, body)
            assert getattr(bad.value, "status", None) == 400, body


async def test_rename_goes_through_the_revisioned_save(tmp_path):
    async with Core(tmp_path) as core:
        pid = await create(core, "Ancien")
        out = await core.client.presentation_studio_rail_act(pid, {"action": "rename", "actor": "user", "title": "  Nouveau   nom "})
        assert out["changed"] is True and out["title"] == "Nouveau nom" and out["revision"] == 2
        assert (await core.client.presentation_studio_rail_act(pid, {"action": "rename", "actor": "user", "title": "Nouveau nom"}))["changed"] is False
        with pytest.raises(Exception) as bad:
            await core.client.presentation_studio_rail_act(pid, {"action": "rename", "actor": "user", "title": "x" * 200})
        assert getattr(bad.value, "status", None) == 400


async def test_work_state_over_the_wire_and_acknowledge(tmp_path):
    async with Core(tmp_path) as core:
        pid = await create(core, "Travail")
        await core.client.presentation_studio_work(pid, {"event": "begin", "label": "presentation_edit"})
        row = (await core.client.presentation_studio_rail())["presentations"][0]
        assert row["work"]["state"] == "working" and row["work"]["label"] == "presentation_edit"
        await core.client.presentation_studio_work(pid, {"event": "failure", "code": "presentation_studio_storage_io", "message": "boom"})
        row = (await core.client.presentation_studio_rail())["presentations"][0]
        assert row["work"]["state"] == "problem" and row["work"]["message"] == "boom"
        await core.client.presentation_studio_rail_act(pid, {"action": "acknowledge", "actor": "user"})
        assert (await core.client.presentation_studio_rail())["presentations"][0]["work"]["state"] == "done"


async def test_ui_requests_are_numbered_and_the_page_report_is_dated(tmp_path):
    async with Core(tmp_path) as core:
        pid = await create(core, "Ecran")
        first = await core.client.presentation_studio_rail_display({"action": "show_rail", "presentation_id": pid})
        assert first["request"]["seq"] == 1 and first["request"]["presentation_id"] == pid and first["reported"] is None
        second = await core.client.presentation_studio_rail_display({"action": "hide_rail"})
        assert second["request"]["seq"] == 2 and second["request"]["action"] == "hide_rail"
        # Slice 09: the floating window host is retired; its screen requests are refused (typed 400), Variants has its own channel
        for retired in ({"action": "open_window", "presentation_id": pid}, {"action": "close_window"}):
            with pytest.raises(Exception) as bad:
                await core.client.presentation_studio_rail_display(retired)
            assert getattr(bad.value, "status", None) == 400
        rail = core.stack.core.presentation_studio_rail
        reported = rail.report_ui({"rail_visible": True, "variants_open": True, "presentation_id": pid, "applied_seq": 2})
        assert reported["reported"]["variants_open"] is True and reported["reported"]["presentation_id"] == pid
        with pytest.raises(PresentationStudioError):                     # the retired field is refused, never read as Variants
            rail.report_ui({"rail_visible": True, "window_open": True, "presentation_id": pid})
        listing = await core.client.presentation_studio_rail()
        assert listing["ui"]["seq"] == 2


# ------------------------------------------------------------------ outils MCP

async def test_mcp_library_inspect_rail_and_the_archived_gate(tmp_path):
    core, world = await open_world(tmp_path)
    try:
        tools = world.tools
        rows = {r["presentation_id"]: r for r in (await tools.inspect("rail"))["presentations"]["items"]} \
            if isinstance((await tools.inspect("rail"))["presentations"], dict) else {}
        assert world.pid in rows or rows == {}
        hid = await tools.library("hide", presentation_id=world.pid)
        assert hid["hidden"] is True and hid["speech"] == "silent"
        overview = await tools.inspect("overview")
        listed = overview["presentations"]["items"]
        assert [r.get("hidden") for r in listed if r["presentation_id"] == world.pid] == [True]
        await tools.library("show", presentation_id=world.pid)

        with pytest.raises(PresentationToolError) as unconfirmed:
            await tools.library("archive", presentation_id=world.pid)
        assert unconfirmed.value.code == "presentation_studio_confirmation_required"
        archived = await tools.library("archive", presentation_id=world.pid, confirmed=True)
        assert archived["archived"] is True and archived["speech"] == "say"
        for call in (lambda: tools.play("start", presentation_id=world.pid, role="rehearsal"),
                     lambda: tools.view("window_open", presentation_id=world.pid),
                     lambda: tools.view("explorer_open", presentation_id=world.pid)):
            with pytest.raises(PresentationToolError) as gate:
                await call()
            assert gate.value.code == "presentation_archived"
        await tools.library("restore", presentation_id=world.pid)
        world.cc.answers[("POST", "/api/presentation-studio/explorer/commands")] = (200, {"state": "opened", "mode": "windowed"})
        out = await tools.view("window_open", presentation_id=world.pid)
        assert out["status"] == "opened" and out["mode"] == "windowed", "Variants, windowed, with the page's receipt (Slice 09)"
        screen = await tools.view("rail_hide")
        assert screen["seq"] == 1
        renamed = await tools.library("rename", presentation_id=world.pid, title="Titre rendu")
        assert renamed["changed"] is True and renamed["title"] == "Titre rendu"
        with pytest.raises(PresentationToolError):
            await tools.library("rename", presentation_id=world.pid)
    finally:
        await core.__aexit__(None, None, None)


async def test_mcp_edit_lights_the_blue_dot_and_a_real_failure_the_orange_one(tmp_path):
    core, world = await open_world(tmp_path)
    try:
        tools = world.tools
        await tools.edit([{"op": "scene.rename", "scene_id": S1, "title": "Renommee"}], presentation_id=world.pid, variant_id=world.vid)
        row = next(r for r in (await core.client.presentation_studio_rail())["presentations"] if r["presentation_id"] == world.pid)
        assert row["work"]["state"] == "working" and row["work"]["label"] == "presentation_edit"
        # a refusal the agent corrects (unknown scene) does not raise the alarm
        with pytest.raises(PresentationToolError):
            await tools.edit([{"op": "scene.rename", "scene_id": "pss_ffffffffffff", "title": "x"}], presentation_id=world.pid, variant_id=world.vid)
        row = next(r for r in (await core.client.presentation_studio_rail())["presentations"] if r["presentation_id"] == world.pid)
        assert row["work"]["state"] == "working"
        await tools._work(world.pid, "failure", label="presentation_edit", code="presentation_studio_storage_io", message="boom")
        row = next(r for r in (await core.client.presentation_studio_rail())["presentations"] if r["presentation_id"] == world.pid)
        assert row["work"]["state"] == "problem"
        await tools.library("acknowledge", presentation_id=world.pid)
        row = next(r for r in (await core.client.presentation_studio_rail())["presentations"] if r["presentation_id"] == world.pid)
        assert row["work"]["state"] == "done"
    finally:
        await core.__aexit__(None, None, None)


# ------------------------------------------------------------------ rail actif (S07, D10) : apercu, type, « a revoir »

async def _still(core: Core, pid: str, *, width: int = 1280, height: int = 720, finish: bool = True, payload: bytes = b"PNG-still") -> str:
    """Un vrai `presentation_still` : snapshot fige de la revision vivante, puis rendu `rendered_from` ce snapshot (registre reel)."""

    import hashlib

    from jarvis.domain import presentation_artifacts as pa
    from jarvis.domain.artifacts import ArtifactState

    app = core.stack.core
    view = await app.presentation_studio.get(pid)
    variant = view.variants[0]
    began = await app.presentation_artifacts.begin_snapshot(pid, variant.variant_id, expected_presentation_revision=view.presentation.revision,
                                                            expected_variant_revision=variant.revision)
    sid = began["artifact_id"]
    if began["state"] == "pending":
        spool = app.artifacts.open_spool(await app.artifacts.get(sid))
        spool.write(b"PK-frozen")
        spool.finalize()
        await app.presentation_artifacts.finalize_snapshot(sid, content_sha256=hashlib.sha256(b"PK-frozen").hexdigest())
    render = await app.presentation_artifacts.begin_render(sid, pa.RenderFormat.STILL)
    if finish:
        spool = app.artifacts.open_spool(render)
        spool.write(payload)
        spool.finalize()
        await app.artifacts.finalize(render.artifact_id, state=ArtifactState.COMPLETE, width=width, height=height)
    return render.artifact_id


async def test_row_preview_is_latest_complete_still_without_path(tmp_path):
    async with Core(tmp_path) as core:
        shown, bare = await create(core, "Avec apercu"), await create(core, "Sans apercu")
        await _still(core, shown, width=640, height=360)
        newest = await _still(core, shown)
        await _still(core, shown, finish=False)  # a pending render is never a preview
        rows = {r["presentation_id"]: r for r in (await core.client.presentation_studio_rail())["presentations"]}
        assert rows[shown]["preview"] == {"artifact_id": newest, "kind": "presentation_still", "width": 1280, "height": 720}
        assert rows[bare]["preview"] is None, "no render: the page draws a typed placeholder, never a fake slide"
        assert rows[shown]["type"] == {"engine": "remotion"} and rows[bare]["type"] == {"engine": "remotion"}
        wire = json.dumps(rows)
        assert str(tmp_path) not in wire and str(tmp_path).replace("\\", "/") not in wire and "payload_ref" not in wire, "never a filesystem path"


async def test_preview_cache_bounded():
    from types import SimpleNamespace

    from jarvis.core import presentation_studio_rail as rail_module
    from jarvis.core.presentation_studio_rail import PREVIEW_LINEAGE_MAX, PREVIEW_RESOLVES, PresentationRail
    from jarvis.domain.artifacts import ArtifactKind

    def page(start: int) -> list:
        return [SimpleNamespace(artifact_id=f"jart_{n:032x}", kind=ArtifactKind.PRESENTATION_STILL, width=10, height=10)
                for n in range(start, start + rail_module.PREVIEW_SCAN)]

    stills = page(0)
    queries: list[object] = []

    class Registry:
        async def query(self, query):
            queries.append(query)
            return SimpleNamespace(items=list(stills), next_cursor=None)

    rail = PresentationRail(SimpleNamespace(trace=lambda *a, **k: None))  # type: ignore[arg-type]
    rail.bind_artifacts(Registry())
    resolved: list[str] = []

    async def owner_of(still):
        resolved.append(still.artifact_id)
        return "pst_" + still.artifact_id[-32:]

    rail._owner_of = owner_of  # type: ignore[method-assign]
    first = await rail.previews()
    assert len(resolved) == PREVIEW_RESOLVES and len(first) == PREVIEW_RESOLVES, "a read resolves at most PREVIEW_RESOLVES new lineages"
    reads = 1
    while len(resolved) < len(stills):
        await rail.previews()
        reads += 1
    assert reads == -(-len(stills) // PREVIEW_RESOLVES)
    before = len(resolved)
    again = await rail.previews()
    assert len(resolved) == before and len(again) == len(stills), "same newest stills: nothing is resolved again"
    assert queries[-1].limit == rail_module.PREVIEW_SCAN and [k.value for k in queries[-1].kinds] == ["presentation_still"]
    assert [s.value for s in queries[-1].states] == ["complete"]
    start = 10_000
    while len(resolved) < PREVIEW_LINEAGE_MAX + 2 * rail_module.PREVIEW_SCAN:
        stills[:] = page(start)
        start += rail_module.PREVIEW_SCAN
        while True:
            count = len(resolved)
            await rail.previews()
            if len(resolved) == count:
                break
    assert len(rail._lineage) <= PREVIEW_LINEAGE_MAX, "the lineage cache is bounded"


async def test_brain_success_marks_unreviewed_user_review_clears(tmp_path):
    def row(listing: dict, pid: str) -> dict:
        return next(r for r in listing["presentations"] if r["presentation_id"] == pid)

    async with Core(tmp_path) as core:
        pid = await create(core, "Revue")

        def rail_file() -> dict:
            return json.loads(next(tmp_path.rglob(f"{pid}/rail.json")).read_text(encoding="utf-8"))

        assert row(await core.client.presentation_studio_rail(), pid)["unreviewed"] is None
        await core.client.presentation_studio_work(pid, {"event": "begin", "label": "presentation_edit"})
        assert row(await core.client.presentation_studio_rail(), pid)["unreviewed"] is None, "work in progress is not yet to review"
        await core.client.presentation_studio_work(pid, {"event": "success", "label": "presentation_edit"})
        marked = row(await core.client.presentation_studio_rail(), pid)["unreviewed"]
        assert marked["label"] == "presentation_edit" and marked["since"]
        assert rail_file()["unreviewed"] == marked and rail_file()["schema_version"] == 1, "additive key, schema stays v1"
        await core.client.presentation_studio_work(pid, {"event": "success", "label": "presentation_variant"})
        assert rail_file()["unreviewed"] == marked, "already to review: the first unreviewed work keeps its date"
        # a hide keeps the mark (flags are replaced, never rebuilt from scratch)
        await core.client.presentation_studio_rail_act(pid, {"action": "hide", "actor": "user"})
        assert rail_file()["unreviewed"] == marked and rail_file()["hidden"] is True
        with pytest.raises(Exception) as brain:
            await core.client.presentation_studio_rail_act(pid, {"action": "review", "actor": "brain"})
        assert getattr(brain.value, "status", None) == 400, "only the user marks a presentation as seen"
        seen = await core.client.presentation_studio_rail_act(pid, {"action": "review", "actor": "user"})
        assert seen["changed"] is True and seen["unreviewed"] is None
        assert "unreviewed" not in rail_file() and rail_file()["hidden"] is True
        assert (await core.client.presentation_studio_rail_act(pid, {"action": "review", "actor": "user"}))["changed"] is False
        assert row(await core.client.presentation_studio_rail(), pid)["unreviewed"] is None
        await core.client.presentation_studio_work(pid, {"event": "success", "label": "presentation_edit"})
    async with Core(tmp_path) as core:  # persisted: a restart keeps the yellow, unlike the work state
        listed = row(await core.client.presentation_studio_rail(), pid)
        assert listed["unreviewed"]["label"] == "presentation_edit" and listed["work"]["state"] == "done"


def test_old_rail_json_reads_without_unreviewed():
    old = {"schema": RAIL_SCHEMA, "schema_version": 1, "hidden": True, "archived": False, "hidden_at": "2026-10-10T10:00:00Z", "archived_at": None}
    flags = parse_rail(json.dumps(old))
    assert flags.unreviewed is None and flags.hidden is True
    assert flags.to_document() == old, "nothing to review: the document is exactly the v1 an older Core writes"
    marked = parse_rail(json.dumps({**old, "unreviewed": {"since": "2026-10-11T09:00:00Z", "label": "presentation_edit"}}))
    assert marked.unreviewed == {"since": "2026-10-11T09:00:00Z", "label": "presentation_edit"}
    assert parse_rail(json.dumps(marked.to_document())) == marked
    for bad in ("yes", {"label": "x"}, {"since": 3}, {"since": ""}, None, []):
        assert parse_rail(json.dumps({**old, "unreviewed": bad})).unreviewed is None, bad


async def test_problem_never_reported_as_unreviewed(tmp_path):
    async with Core(tmp_path) as core:
        pid = await create(core, "Probleme")
        await core.client.presentation_studio_work(pid, {"event": "success", "label": "presentation_edit"})
        await core.client.presentation_studio_work(pid, {"event": "failure", "code": "presentation_studio_storage_io", "message": "disque plein"})
        row = (await core.client.presentation_studio_rail())["presentations"][0]
        assert row["work"]["state"] == "problem" and row["unreviewed"] is None, "a problem keeps its own treatment"
        await core.client.presentation_studio_rail_act(pid, {"action": "acknowledge", "actor": "user"})
        row = (await core.client.presentation_studio_rail())["presentations"][0]
        assert row["work"]["state"] == "done" and row["unreviewed"]["label"] == "presentation_edit", "acknowledged: the unseen work is still to review"

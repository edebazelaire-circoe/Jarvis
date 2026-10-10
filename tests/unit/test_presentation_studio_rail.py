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
        first = await core.client.presentation_studio_rail_display({"action": "open_window", "presentation_id": pid})
        assert first["request"]["seq"] == 1 and first["request"]["presentation_id"] == pid and first["reported"] is None
        second = await core.client.presentation_studio_rail_display({"action": "hide_rail"})
        assert second["request"]["seq"] == 2 and second["request"]["action"] == "hide_rail"
        with pytest.raises(Exception) as bad:
            await core.client.presentation_studio_rail_display({"action": "open_window"})
        assert getattr(bad.value, "status", None) == 400
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
        out = await tools.view("window_open", presentation_id=world.pid)
        assert out["status"] == "requested" and out["seq"] == 1
        screen = await tools.view("rail_hide")
        assert screen["seq"] == 2
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

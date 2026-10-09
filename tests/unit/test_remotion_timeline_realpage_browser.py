"""La partition conduit une scène Remotion, dans le VRAI Control Center, un VRAI Chrome, un Core isolé (Slice 12).

Opt-in comme la Slice 10 : exige une installation Remotion existante (`JARVIS_REMOTION_RUNTIME_DIR` = son dossier `runtime/`), Node et
Chrome ; sans eux ces épreuves sont ignorées (elles n'installent jamais rien). Même chaîne réelle que
`test_remotion_player_realpage_browser.py` (`RemotionStack`) ; ne démarre ni n'arrête jamais le Jarvis vivant.

Prouvé (mesuré, image lue DANS le bac à sable) : le segment d'entrée joue jusqu'à l'image avant la première ancre puis tient ; révéler
une ancre (`next`) fait aller le lecteur à son image et jouer jusqu'à l'image avant l'ancre suivante, où il s'arrête de lui-même ;
une cue (le rapport typé du suiveur, comme la voix) fait de même ; pause tient l'image, reprise continue sans revenir en arrière ;
`previous` ramène à l'ancre précédente ; une scène sans ancre se joue seule (Slice 10) et la vue de Core n'a alors aucune
`timeline` ; un faux rapport de position venu de la scène est refusé par le chien de garde et ne change rien.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil

import pytest

from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.domain.remotion_source import Composition
from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.fakes.remotion_scene import scene_candidate
from tests.unit.test_remotion_player_realpage_browser import (
    PROPS, READY, SAMPLE, SANDBOX, SCENE_TSX, SHELL, STAGE, http_step, noise, record_evidence, run, scene,
)

RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

A, B = "presentation-studio.p000000000001.s000000000001", "presentation-studio.p000000000001.s000000000002"
S1, S2 = "pss_000000000001", "pss_000000000002"
CUE = "psc_000000000001"
FRAME = "Number(document.querySelector('#frame').textContent)"
PLAYBACK = "/v1/presentation-studio/playback"
#: 30 images/s, 150 images (5 s). Ancres à 1 s, 2,5 s et 4 s = images 30, 75, 120 : segments [0,29] [30,74] [75,119] [120,149].
ANCHORS = [{"anchor_id": "intro", "label": "Intro", "at_ms": 1000}, {"anchor_id": "middle", "label": "Milieu", "at_ms": 2500},
           {"anchor_id": "end", "label": "Fin", "at_ms": 4000}]


def item(n: int, scene_id: str, note: str, nxt: int | None, **extra) -> dict:
    return {"item_id": f"psi_{n:012d}", "scene_id": scene_id, "presenter": "user", "kind": "speech", "note": note,
            **({"next_item_id": f"psi_{nxt:012d}"} if nxt else {}), **extra}


def reveal(anchor: str) -> list[dict]:
    return [{"kind": "reveal", "scene_id": S1, "anchor_id": anchor}]


async def publish(stack: RemotionStack, prefab_id: str, title: str) -> None:
    await stack.core.prefabs.save(scene_candidate(
        prefab_id, engine=shipped_engine_pin(), title=title, composition=Composition("Scene", 1280, 720, 30, 150),
        files={"src/Scene.tsx": SCENE_TSX}, props=PROPS, sample=SAMPLE), actor="user")


async def make_presentation(stack: RemotionStack) -> str:
    base = "/v1/presentation-studio/presentations"
    _, created = await stack.call("POST", base, json={"title": "Chronologie"})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    vid = variant["variant_id"]
    scenes = [{**scene(S1, A, "Un"), "anchors": ANCHORS}, scene(S2, B, "Deux")]
    status, saved = await stack.call("PUT", f"{base}/{pid}/variants/{vid}", json={
        "expected_revision": variant["revision"], "title": variant["title"], "scenes": scenes,
        "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"]})
    assert status == 200, saved
    items = [item(1, S1, "Ouverture", 2), item(2, S1, "Intro", 3, visual=reveal("intro")),
             item(3, S1, "Milieu", 4, cue_id=CUE, visual=reveal("middle")), item(4, S1, "Fin", 5, visual=reveal("end")),
             item(5, S2, "Autre", None)]
    status, made = await stack.call("POST", f"{base}/{pid}/variants/{vid}/score", json={
        "expected_variant_revision": saved["revision"], "start_item_id": items[0]["item_id"], "items": items,
        "cues": [{"cue_id": CUE, "label": "Milieu", "armable": True, "predicate": {"phrases": ["passons au milieu"]}}],
        "sequences": [], "recovery_points": []})
    assert status == 201, made
    status, art = await stack.call("POST", f"{base}/{pid}/variants/{vid}/art-direction/fallback",
                                   json={"expected_variant_revision": saved["revision"] + 1})
    assert status == 201, art
    return pid


def compact(reads: dict) -> dict:
    """Evidence keeps what was measured: frames read in the sandbox, and per command only the status and the timeline Core described."""

    return {name: ({"status": value["status"], "timeline": ((value.get("body") or {}).get("state") or {}).get("timeline")}
                   if isinstance(value, dict) and "status" in value and "body" in value else value) for name, value in reads.items()}


def reached(frame: int) -> dict:
    return {"until": f"{FRAME}>={frame}", "ms": 15000, **SANDBOX}


async def fire_the_cue(stack: RemotionStack) -> dict:
    """What the voice follower does: pull the armed set, report the typed cue. No text, no tool, Core decides."""

    status, armed = await stack.call("GET", f"{PLAYBACK}/armed")
    assert status == 200 and [c["cue_id"] for c in armed["cues"]] == [CUE], armed
    status, fired = await stack.call("POST", "/v1/presentation-studio/cues/satisfied",
                                     json={"run_id": armed["run_id"], "generation": armed["generation"], "cue_id": CUE})
    assert status == 200 and fired["status"] == "fired", fired
    return fired


async def test_the_score_drives_a_remotion_scene_through_its_anchors_a_cue_pause_resume_and_back(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        await publish(stack, A, "Un")
        await publish(stack, B, "Deux")
        pid = await make_presentation(stack)
        status, started = await stack.start(pid)
        assert status == 200 and started["state"]["phase"] == "playing", started
        first = started["state"]["timeline"]
        assert (first["composition_id"], first["fps"], first["duration_frames"], first["anchor_id"]) == ("Scene", 30, 150, None)
        assert (first["from_frame"], first["until_frame"], first["playing"]) == (0, 29, True), "the lead-in plays up to the beat"
        shot1, shot2 = str(tmp_path / "intro_hold.png"), str(tmp_path / "end_hold.png")

        # --- page 1: the entry segment, then an anchor revealed by the presenter, then a forged position report
        one = await run(stack.page_url, [
            {"wait": 500}, READY,
            reached(29), {"wait": 900}, {"value": "entry_a", "expr": FRAME, **SANDBOX}, {"wait": 900}, {"value": "entry_b", "expr": FRAME, **SANDBOX},
            http_step(stack, "next", "POST", f"{PLAYBACK}/next", {"actor": "user"}),
            {"until": f"{FRAME}>=30 && {FRAME}<74", "ms": 15000, **SANDBOX}, {"value": "intro_playing", "expr": FRAME, **SANDBOX},
            reached(74), {"wait": 900}, {"value": "intro_a", "expr": FRAME, **SANDBOX}, {"wait": 900}, {"value": "intro_b", "expr": FRAME, **SANDBOX},
            {"shot": shot1},
            # a hostile scene (or a bug) reports a position far beyond the composition: refused, counted, nothing moves
            {"value": "refused_before", "expr": f"({SHELL}.supervisor.refused.bad_clock||0)"},
            {"eval": "parent.postMessage({rs:1,type:'clock',frame:99999999,playing:true},'*')", **SANDBOX},
            {"eval": "parent.postMessage({rs:1,type:'clock',frame:-3,playing:false},'*')", **SANDBOX},
            {"wait": 700},
            {"value": "refused_after", "expr": f"({SHELL}.supervisor.refused.bad_clock||0)"},
            {"value": "frame_after_spoof", "expr": FRAME, **SANDBOX},
            {"value": "shell_frame", "expr": f"{SHELL}.frame"},
            {"value": "frames", "expr": "document.querySelectorAll('iframe[data-remotion-stage]').length"},
        ])
        reads1 = one["reads"]
        assert "failed" not in reads1, reads1
        assert reads1["entry_a"] == reads1["entry_b"] == 29, "the lead-in stops by itself on the frame before the first anchor"
        assert 30 <= reads1["intro_playing"] < 74, reads1
        assert reads1["intro_a"] == reads1["intro_b"] == 74, "the 'intro' segment ends on the frame before 'middle'"
        assert reads1["refused_after"] >= reads1["refused_before"] + 2, "forged position reports are refused by the watchdog"
        assert reads1["frame_after_spoof"] == 74 and reads1["shell_frame"] <= 149 and reads1["frames"] == 1
        assert not noise(one), noise(one)

        # --- the cue (the voice follower's typed report) opens the next segment; the page joins the run mid-way, paused
        fired = await fire_the_cue(stack)
        status, paused = await stack.call("POST", f"{PLAYBACK}/pause", json={"actor": "user"})
        assert status == 200, paused
        _, state = await stack.call("GET", PLAYBACK)
        middle = state["state"]["timeline"]
        assert middle["anchor_id"] == "middle" and (middle["from_frame"], middle["until_frame"]) == (75, 119)
        two = await run(stack.page_url, [
            {"wait": 500}, READY, {"wait": 2500},
            {"value": "paused_at", "expr": FRAME, **SANDBOX}, {"wait": 1200}, {"value": "paused_still", "expr": FRAME, **SANDBOX},
            http_step(stack, "resume", "POST", f"{PLAYBACK}/resume", {"actor": "user"}),
            {"until": f"{FRAME}>75", "ms": 15000, **SANDBOX},
            reached(119), {"wait": 900}, {"value": "middle_a", "expr": FRAME, **SANDBOX}, {"wait": 900}, {"value": "middle_b", "expr": FRAME, **SANDBOX},
            http_step(stack, "next_end", "POST", f"{PLAYBACK}/next", {"actor": "user"}),
            {"until": f"{FRAME}>=120", "ms": 15000, **SANDBOX},
            reached(149), {"wait": 900}, {"value": "end_a", "expr": FRAME, **SANDBOX}, {"wait": 900}, {"value": "end_b", "expr": FRAME, **SANDBOX},
            {"shot": shot2},
            # back: hiding is going back, the playhead returns to the furthest anchor still revealed
            http_step(stack, "previous", "POST", f"{PLAYBACK}/previous", {"actor": "user"}),
            {"until": f"{FRAME}>=75 && {FRAME}<119", "ms": 15000, **SANDBOX}, {"value": "back_playing", "expr": FRAME, **SANDBOX},
            # pause in the middle of a segment holds the image, resume carries on without going back
            {"until": f"{FRAME}>=90", "ms": 15000, **SANDBOX},
            http_step(stack, "pause_mid", "POST", f"{PLAYBACK}/pause", {"actor": "user"}),
            {"wait": 900}, {"value": "mid_a", "expr": FRAME, **SANDBOX}, {"wait": 1100}, {"value": "mid_b", "expr": FRAME, **SANDBOX},
            http_step(stack, "resume_mid", "POST", f"{PLAYBACK}/resume", {"actor": "user"}),
            {"wait": 600},
            {"value": "after_resume", "expr": FRAME, **SANDBOX},
            reached(119), {"wait": 700}, {"value": "back_end", "expr": FRAME, **SANDBOX},
        ])
        reads2 = two["reads"]
        assert "failed" not in reads2, reads2
        assert reads2["paused_at"] == reads2["paused_still"] and 75 <= reads2["paused_at"] <= 80, "a page that joins a paused run holds the segment start"
        assert reads2["middle_a"] == reads2["middle_b"] == 119
        assert reads2["end_a"] == reads2["end_b"] == 149, "the last segment plays to the end and holds"
        assert 75 <= reads2["back_playing"] < 119
        assert reads2["mid_a"] == reads2["mid_b"] and 90 <= reads2["mid_a"] < 119, "pause holds the image"
        assert reads2["after_resume"] >= reads2["mid_b"], "resume continues, it never goes back to the anchor"
        assert reads2["back_end"] == 119
        assert not noise(two), noise(two)

        # --- a scene with no anchor is left to itself (Slice 10) and Core's view carries no timeline for it
        for _ in range(2):
            status, moved = await stack.call("POST", f"{PLAYBACK}/next", json={"actor": "user"})
            assert status == 200, moved
        _, state = await stack.call("GET", PLAYBACK)
        assert state["state"]["scene"]["scene_id"] == S2 and "timeline" not in state["state"]
        three = await run(stack.page_url, [
            {"wait": 500}, READY, {"wait": 800},
            {"value": "free_a", "expr": FRAME, **SANDBOX}, {"wait": 900}, {"value": "free_b", "expr": FRAME, **SANDBOX},
        ])
        assert three["reads"]["free_a"] != three["reads"]["free_b"], "a scene without anchors plays on its own"

        kinds = set(stack.kinds())
        assert "core.presentation_studio.timeline_resolved" in kinds, "the normal path is journalled too"
        assert fired["status"] == "fired" and paused["state"]["timeline"]["playing"] is False
        record_evidence("timeline_bridge", {
            "composition": {"fps": 30, "frames": 150, "anchors_ms": ANCHORS},
            "page1": {"reads": compact(reads1), "console": [line for line in one["console"] if "timeline" in line][-20:], "errors": one["errors"]},
            "page2": {"reads": compact(reads2), "console": [line for line in two["console"] if "timeline" in line][-30:], "errors": two["errors"]},
            "page3": {"reads": three["reads"]},
            "timeline_after_cue": middle, "journal": sorted(kinds)}, shot1, shot2)

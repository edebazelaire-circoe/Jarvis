"""Porte de release « lecture de présentation » (handoff jarvis-remotion-native-studio-playback-fix, Slice 03).

VRAI Core, VRAI Control Center, VRAI Chrome sans tête, VRAI Player Remotion, sur des ports libres et une racine jetable
(`RemotionStack`) ; jamais le Jarvis vivant. Opt-in comme les autres épreuves Remotion réelles : `JARVIS_REMOTION_RUNTIME_DIR` = le
dossier `runtime/` d'une installation Remotion existante (jamais une installation de plus), Node et Chrome ; sinon tout est ignoré.

Chaque épreuve encode le comportement JUSTE (handoff `docs/02-architecture.md` > *State semantics*) sur une présentation de 9 scènes
aux durées et cadences mêlées (`presentation_playback_gate_world.DECK`). Celles qui échouent sur la base de la tâche sont marquées
`xfail(strict=True)` avec le défaut et la Slice qui le corrige : la suite reste verte, et l'épreuve devient un échec (XPASS strict) le
jour où la correction arrive, pour qu'on retire la marque. Une mesure cassée (pilote, délai) n'est jamais « attendue » : les marques
n'acceptent que `AssertionError`. Constats, chiffres et captures : `tasks/jarvis-remotion-native-studio-playback-fix/slices/
03-reproduce-timeline-and-transition-failures/evidence/` (`summary.json`, `runtime/*.json`, `runtime/*.png`).

    JARVIS_REMOTION_RUNTIME_DIR=<runtime> [JARVIS_PLAYBACK_GATE_EVIDENCE_DIR=<dossier>] \\
      python -m pytest tests/unit/test_presentation_playback_release_gate_browser.py -q -p no:cacheprovider
"""

from __future__ import annotations

import asyncio
import shutil
import time

import pytest

from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.unit.presentation_playback_gate_world import (
    DECK, PAGE_PROBE, PLAYBACK, READ_PROBE, SCENE_IDS, TARGET_MS, VISIBLE, VISIBLE_RECT, CorePoller, blank_spans, bursts_classified,
    first_play, frame_rows, frames_of, make_deck, next_boundary, player_clocks, record, run_long, transition_shots, wraps,
)
from tests.unit.test_remotion_player_realpage_browser import http_step

RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

STATE = f"(()=>{{const f={VISIBLE};try{{return f?f.contentWindow.__remotionStage.state():null}}catch(e){{return null}}}})()"
READY = {"until": f"(()=>{{const s={STATE};return !!s&&s.phase==='ready'}})()", "ms": 90000}
#: The run is over: the last scene (S9, 240 frames) holds its last frame and the band says scene 9/9.
FINAL = (f"(()=>{{const s={STATE};const w=document.querySelector('#jvStudioBand .jvsp-where');"
         f"return !!s&&s.duration===240&&s.frame===239&&!s.playing&&!!w&&w.textContent.includes('Scène 9/9')}})()")
#: What a viewer reads at one instant: the stage bar (`rs-time`), the band clock, the Player frame.
CLOCKS = (f"(()=>{{const f={VISIBLE};const s={STATE};const b=document.querySelector('#jvStudioBand .jvsp-clock');"
          "const t=f&&f.contentDocument.querySelector('.rs-time');const w=document.querySelector('#jvStudioBand .jvsp-where');"
          "return {rs_time:t?t.textContent:null,band:b?b.textContent:null,band_where:w?w.textContent:null,frame:s&&s.frame,playing:s&&s.playing,"
          "duration:s&&s.duration}})()")


def harness(ok: object, why: object) -> None:
    """A broken measure is a real failure, never an expected one: the xfail marks only accept `AssertionError` (`raises=`)."""

    if not ok:
        pytest.fail(f"harness: {why}")


def scrub(frame: int) -> str:
    """The user drags the stage page's inner bar (`rs-bar` scrub) to `frame` : the real `input` listener runs."""

    return (f"(()=>{{const f={VISIBLE};const r=f.contentDocument.querySelector('.rs-scrub');r.value='{frame}';"
            "r.dispatchEvent(new Event('input',{bubbles:true}));return true})()")


def at_frame(frame: int) -> dict:
    return {"until": f"(()=>{{const s={STATE};return !!s&&s.phase==='ready'&&s.frame>={frame}}})()", "ms": 60000}


async def start_manual(stack: RemotionStack, pid: str, scene_index: int | None = None) -> dict:
    status, started = await stack.call("POST", f"{PLAYBACK}/start", json={"actor": "user", "presentation_id": pid, "role": "user_presenter"})
    assert status == 200 and started["state"]["scope"] == "manual", started
    if scene_index:
        status, moved = await stack.call("POST", f"{PLAYBACK}/goto", json={"actor": "user", "scene_id": SCENE_IDS[scene_index]})
        assert status == 200, moved
        return moved
    return started


def scene_of_uid(probe: dict) -> dict[int, str]:
    return {row[2]: row[4] for row in probe["ev"] if row[1] == "mount"}


def core_enter_ms(core_rows: list[dict], epoch: int) -> dict[int, int]:
    """Page time (ms) at which Core's position first entered each scene number."""

    out: dict[int, int] = {}
    for row in core_rows:
        if row.get("scene") and row["scene"] not in out:
            out[row["scene"]] = row["at"] - epoch
    return out


# ---------------------------------------------------------------------------------------------------------------- (c) play all

@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S03 repro: defect A — in a chained play a one-segment scene's staged frame is discarded by the "
                                       "next scene's preload (prefab_host.preload -> dropNext), the run stalls ~LOAD_ALLOWANCE then skips it "
                                       "— fixed by Slice 05/06")
async def test_play_all_shows_every_scene_in_order_from_frame_zero_without_stall_blank_or_cut(tmp_path):
    """(c) « tout jouer » (`scope: all`) on the run stage: each of the 9 scenes becomes visible within 1.5 s of Core entering it, plays from
    its frame 0 to its last frame (the 30 s scene is not cut at its 8 s score target), no instant without a ready frame, no replay."""

    shots = tmp_path / "shots"
    shots.mkdir()
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        status, started = await stack.call("POST", f"{PLAYBACK}/start", json={
            "actor": "user", "presentation_id": pid, "role": "user_presenter", "scope": "all"})
        assert status == 200 and started["state"]["scope"] == "all", started
        plan: list[dict] = [{"eval": PAGE_PROBE}, READY]
        for boundary in range(1, 9):
            plan += [{"until": f"({next_boundary()})||({FINAL})", "ms": 70000},
                     {"burst": str(shots), "ms": 1800, "clipExpr": VISIBLE_RECT, "prefix": f"b{boundary}", "as": f"burst{boundary}"}]
            if boundary == 2:   # 4 s after the S2 -> S3 boundary: S3 playing, or S2 held while the band says scene 3/9 (the stall)
                plan += [{"wait": 2500}, {"shot": str(tmp_path / "stall.png")}, {"value": "at_stall_shot", "expr": CLOCKS}]
        plan += [{"until": FINAL, "ms": 70000}, {"wait": 3000}, {"value": "probe", "expr": READ_PROBE},
                 http_step(stack, "where", "GET", PLAYBACK)]
        async with CorePoller(stack) as poll:
            began = time.time()
            result = await run_long(stack.page_url, plan)
            took = time.time() - began
        reads = result["reads"]
        probe = reads.get("probe")
        harness(probe, reads.get("failed"))
        evidence = analyse_play_all(probe, reads, poll.rows)
        evidence["wall_s"] = round(took, 1)
        evidence["failed_step"] = reads.get("failed")
        evidence["at_stall_shot"] = reads.get("at_stall_shot")
        boundary_shots = [p for burst in evidence["bursts"].values() for p in transition_shots(burst, shots, 2)]
        record("play_all", {"evidence": evidence, "page_epoch": probe["epoch"], "core": poll.rows, "probe_ev": probe["ev"], "band": probe["band"]},
               boundary_shots + [tmp_path / "stall.png"])
        shown = [s["scene"] for s in evidence["per_scene"]]
        assert shown == [f"S{n}" for n in range(1, 10)], f"scenes shown: {shown}; never shown: {evidence['never_shown']}"
        for scene in evidence["per_scene"]:
            n = int(scene["scene"][1:]) - 1
            assert scene["first_play"] and scene["first_play"][1] == 0, scene
            assert scene["max_frame"] == frames_of(n) - 1, scene      # the 30 s scene is not cut at its 8 s target
            assert scene["wraps"] == [] and scene["entry_latency_ms"] is not None and scene["entry_latency_ms"] <= 1500, scene
        assert evidence["blank_spans_ms"] == [], evidence["blank_spans_ms"]
        assert all(c.startswith("S") for burst in evidence["bursts"].values() for _t, c, _f in burst), "a white / empty capture at a boundary"
        harness("failed" not in reads, reads.get("failed"))


def analyse_play_all(probe: dict, reads: dict, core_rows: list[dict]) -> dict:
    rows = frame_rows(probe)
    clocks = player_clocks(probe)
    scene_of = scene_of_uid(probe)
    enter = core_enter_ms(core_rows, probe["epoch"])
    per_scene = []
    for ms, uid in [(row[0], row[2]) for row in probe["ev"] if row[1] == "live"]:
        scene = scene_of.get(uid)
        number = int(scene[1:]) if scene else None
        per_scene.append({"uid": uid, "scene": scene, "live_ms": ms, "core_enter_ms": enter.get(number),
                          "entry_latency_ms": None if number not in enter else ms - enter[number],
                          "duration": next((s[5] for s in rows.get(uid, []) if s[5]), None), "first_play": first_play(probe, uid),
                          "max_frame": max((c[1] for c in clocks.get(uid, [])), default=None), "wraps": wraps(clocks.get(uid, []))})
    shown = {s["scene"] for s in per_scene}
    stalls = []
    for number, ms in sorted(enter.items()):
        if f"S{number}" not in shown:
            following = enter.get(number + 1)
            stalls.append({"scene": f"S{number}", "core_enter_ms": ms, "core_left_ms": following,
                           "held_previous_ms": None if following is None else following - ms})
    bursts = {key: bursts_classified(value) for key, value in reads.items() if key.startswith("burst") and isinstance(value, list)}
    return {"mounted_frames": [(row[0], row[2], row[4], row[5]) for row in probe["ev"] if row[1] == "mount"],
            "per_scene": per_scene, "never_shown": stalls, "blank_spans_ms": blank_spans(probe, place="board"), "bursts": bursts,
            "core_scopes": sorted({r.get("scope") for r in core_rows if r.get("scope")}),
            "expected_s": sum(s for s, _f, _a, _b in DECK),
            "where_end": {k: ((reads.get("where") or {}).get("body") or {}).get("state", {}).get(k) for k in ("phase", "scope", "position")}}


# ---------------------------------------------------------------------------------------------------------------- (d)+(e) one scene, two clocks

async def scene_clocks_run(tmp_path) -> dict:
    """S3 (30 s at 30 fps, score target 8 s) played with `play {scope: scene}`: what the viewer reads at 2.6 s, then a scrub of the inner bar to
    20 s, then the end. Measured once per module and shared by the tests below."""

    cached = globals().get("_SCENE_CLOCKS")
    if cached:
        return cached
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        await start_manual(stack, pid, 2)
        status, played = await stack.call("POST", f"{PLAYBACK}/play", json={"actor": "user", "scope": "scene"})
        assert status == 200 and played["state"]["scope"] == "scene", played
        plan = [{"eval": PAGE_PROBE}, READY, at_frame(78), {"value": "at_2_6", "expr": CLOCKS}, http_step(stack, "core_2_6", "GET", PLAYBACK),
                {"shot": str(tmp_path / "clocks-2_6s.png")},
                {"eval": scrub(600)}, {"wait": 1500}, {"value": "after_scrub", "expr": CLOCKS}, http_step(stack, "core_after_scrub", "GET", PLAYBACK),
                {"shot": str(tmp_path / "clocks-after-scrub.png")},
                {"until": f"(()=>{{const s={STATE};return !!s&&s.frame===899&&!s.playing}})()", "ms": 40000},
                {"value": "held", "expr": CLOCKS}, {"wait": 2000}, {"value": "probe", "expr": READ_PROBE}]
        async with CorePoller(stack) as poll:
            result = await run_long(stack.page_url, plan, timeout=300)
            # Core keeps its own clock after the Player halted: wait for its deadline (cap 30 s + grace 3 s from the segment start)
            for _ in range(80):
                if poll.rows and poll.rows[-1].get("scope") == "manual":
                    break
                await asyncio.sleep(0.5)
        reads = result["reads"]
        probe = reads.get("probe") or {}
        epoch = probe.get("epoch", 0)
        scope_change = next((r["at"] - epoch for r in poll.rows if r.get("scope") == "manual"), None)
        clocks = player_clocks(probe) if probe else {}
        uid = max(clocks, key=lambda u: len(clocks[u])) if clocks else None
        own = clocks.get(uid, []) if uid else []
        scrubbed = next((ms for ms, frame, _p in own if frame >= 600), None)
        after = [c for c in own if scrubbed is not None and c[0] >= scrubbed]
        reached = next((ms for ms, frame, _p in after if frame >= 890), None)
        halted = next((ms for ms, frame, playing in own if frame == 899 and not playing), None)
        evidence = {"at_2_6": reads.get("at_2_6"), "core_2_6": core_view(reads.get("core_2_6")),
                    "after_scrub": reads.get("after_scrub"), "core_after_scrub": core_view(reads.get("core_after_scrub")),
                    "held": reads.get("held"), "scrub_seen_ms": scrubbed, "player_reached_end_ms": reached, "player_halted_ms": halted,
                    "wraps_after_scrub": wraps(after), "orders": [row for row in probe.get("ev", []) if row[1] == "order"],
                    "core_scope_back_to_manual_ms": scope_change,
                    "core_lag_after_player_end_ms": None if reached is None or scope_change is None else scope_change - reached,
                    "first_play": first_play(probe, uid) if uid else None, "failed": reads.get("failed")}
        record("scene_clocks_S3", {"evidence": evidence, "page_epoch": epoch, "core": poll.rows, "probe_ev": probe.get("ev"), "band": probe.get("band")},
               [tmp_path / "clocks-2_6s.png", tmp_path / "clocks-after-scrub.png"])
        globals()["_SCENE_CLOCKS"] = evidence
        return evidence


def core_view(answer: dict | None) -> dict | None:
    state = ((answer or {}).get("body") or {}).get("state") or {}
    tl = state.get("timeline") or {}
    return {"scope": state.get("scope"), "phase": state.get("phase"), "scene": (state.get("scene") or {}).get("number"),
            "play_ms": tl.get("play_ms"), "from": tl.get("from_frame"), "until": tl.get("until_frame"), "seq": tl.get("seq"),
            "item_ms": (state.get("elapsed") or {}).get("item_ms"), "item_target_ms": (state.get("elapsed") or {}).get("item_target_ms")}


async def test_a_30s_composition_with_an_8s_score_target_plays_to_its_last_frame(tmp_path):
    """(c)/(E) The score's `target_duration_ms` (8 s) never cuts a 30 s Remotion composition: the Player reaches frame 899."""

    evidence = await scene_clocks_run(tmp_path)
    harness(evidence["failed"] is None, evidence["failed"])
    assert evidence["held"]["frame"] == 899 and evidence["held"]["playing"] is False, evidence["held"]
    assert evidence["first_play"] and evidence["first_play"][1] == 0, evidence["first_play"]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S03 repro: defect D/F — the band shows the score item clock (elapsed / target_duration_ms) while the "
                                       "stage bar shows the composition clock: two times for one picture — fixed by Slice 04/06")
async def test_one_clock_every_time_readout_shows_the_composition_time(tmp_path):
    """(d) At 2.6 s into S3 the viewer reads ONE time: the band and the stage bar agree on the composition clock (x / 30 s), never 00:02 / 00:08."""

    evidence = await scene_clocks_run(tmp_path)
    at = evidence["at_2_6"]
    assert at["rs_time"].endswith("/ 30.0 s"), at
    assert at["band"] is None or "00:08" not in at["band"], f"two clocks for one picture: stage {at['rs_time']!r}, band {at['band']!r}"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S03 repro: defect D — an inner-bar scrub only seeks the sandboxed Player; Core's segment clock and the "
                                       "band never hear of it — fixed by Slice 04/06")
async def test_a_scrub_of_the_player_bar_moves_the_shared_clock(tmp_path):
    """(d) Scrubbing the Player bar to 20 s moves the one composition clock: Core's position (timeline play time) follows the scrub."""

    evidence = await scene_clocks_run(tmp_path)
    after, core = evidence["after_scrub"], evidence["core_after_scrub"]
    assert after["frame"] >= 600, after                                 # the Player did take the seek
    assert core["play_ms"] is not None and core["play_ms"] >= 19000, f"Player at {after['frame']} / band {after['band']!r} / Core {core}"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S03 repro: defect C/D — a scrub clears the Player's stop frame (sandbox seek "
                                       "sets until=null) so it runs past the end and loops from 0 (loop:true); Core ends the scene on its own clock "
                                       "~20 s later and the follower then jumps the Player forward — fixed by Slice 04/05/06")
async def test_after_a_forward_scrub_the_scene_ends_once_and_core_ends_with_it(tmp_path):
    """(d) After a scrub to 20 s, the Player plays to the last frame and HOLDS it (no wrap to 0), and Core ends the scene-scope play within
    1.5 s of that end (one clock, not Core's own deadline)."""

    evidence = await scene_clocks_run(tmp_path)
    assert evidence["wraps_after_scrub"] == [], f"the Player looped after the scrub: {evidence['wraps_after_scrub']}"
    lag = evidence["core_lag_after_player_end_ms"]
    assert lag is not None and 0 <= lag <= 1500, f"Player at its end at {evidence['player_reached_end_ms']} ms, Core ended at {evidence['core_scope_back_to_manual_ms']} ms"


# ---------------------------------------------------------------------------------------------------------------- (e) manual, anchors or not

@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S03 repro: defect A/C — a manual run gives an anchorless scene no timeline; the Player is free with "
                                       "loop:true after the 450 ms hold and replays forever — fixed by Slice 06")
async def test_a_manual_scene_without_anchor_plays_once_and_holds_its_last_frame(tmp_path):
    """(e) Manual scope, S1 (3 s, no anchor): it plays once from frame 0 and holds frame 89; it never wraps to 0 by itself."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        await start_manual(stack, pid)
        result = await run_long(stack.page_url, [{"eval": PAGE_PROBE}, READY, {"wait": 8000}, {"value": "probe", "expr": READ_PROBE},
                                                  http_step(stack, "core", "GET", PLAYBACK)], timeout=240)
        probe = result["reads"]["probe"]
        clocks = player_clocks(probe)
        uid = max(clocks, key=lambda u: len(clocks[u]))
        evidence = {"wraps": wraps(clocks[uid]), "first_play": first_play(probe, uid), "core": core_view(result["reads"].get("core")),
                    "orders": [row for row in probe["ev"] if row[1] == "order"], "clocks": clocks[uid][:60]}
        record("manual_anchorless_S1", evidence)
        assert evidence["wraps"] == [], f"the Player looped {len(evidence['wraps'])} times in 8 s: {evidence['wraps'][:3]}"


async def test_a_manual_scrub_of_a_held_segment_is_kept(tmp_path):
    """(e)/(d) Manual scope, S2 entry segment [0,59] held on 59: a scrub back to 20 (then forward to 200) stays where the user put it."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        await start_manual(stack, pid, 1)
        held = f"(()=>{{const s={STATE};return !!s&&s.frame===59&&!s.playing}})()"
        result = await run_long(stack.page_url, [
            {"eval": PAGE_PROBE}, READY, {"until": held, "ms": 30000}, {"value": "before", "expr": CLOCKS},
            {"eval": scrub(20)}, {"wait": 1500}, {"value": "after_1500", "expr": CLOCKS},
            {"eval": scrub(200)}, {"wait": 4000}, {"value": "after_forward", "expr": CLOCKS},
            {"value": "probe", "expr": READ_PROBE}, http_step(stack, "core", "GET", PLAYBACK)], timeout=240)
        reads = result["reads"]
        harness("failed" not in reads, reads.get("failed"))
        evidence = {k: reads.get(k) for k in ("before", "after_1500", "after_forward")}
        evidence["core"] = core_view(reads.get("core"))
        evidence["orders"] = [row for row in reads["probe"]["ev"] if row[1] == "order"][-12:]
        record("manual_scrub_held_S2", evidence)
        assert reads["before"]["frame"] == 59, reads["before"]
        assert reads["after_1500"]["frame"] == 20 and reads["after_forward"]["frame"] == 200, evidence


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S03 repro: defect C/D — a scrub during a manual segment clears the Player's "
                                       "stop frame (remotion_sandbox_child.js applyControl seek: until=null): the Player runs on into the "
                                       "next anchors' animation (frame 149 five seconds later) — fixed by Slice 06")
async def test_a_manual_scrub_back_while_playing_is_honoured_and_the_segment_still_stops(tmp_path):
    """(e)/(d) Manual scope, S2 entry segment [0,59] while it plays: the user scrubs back to frame 5. The host gives no order of its own after the
    scrub (no re-seek to Core's clock), and the Player still stops at the segment's stop frame 59 (it does not run into the next anchors)."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        await start_manual(stack, pid, 1)
        playing = f"(()=>{{const s={STATE};return !!s&&s.playing&&s.frame>=30}})()"
        result = await run_long(stack.page_url, [
            {"eval": PAGE_PROBE}, READY, {"until": playing, "ms": 30000}, {"value": "before", "expr": CLOCKS},
            {"value": "scrub_at", "expr": "Math.round(performance.now()-__pg.t0)"}, {"eval": scrub(5)},
            {"wait": 300}, {"value": "after_300", "expr": CLOCKS}, {"wait": 1200}, {"value": "after_1500", "expr": CLOCKS},
            {"wait": 3500}, {"value": "after_5000", "expr": CLOCKS},
            {"value": "probe", "expr": READ_PROBE}, http_step(stack, "core", "GET", PLAYBACK)], timeout=240)
        reads = result["reads"]
        harness("failed" not in reads, reads.get("failed"))
        probe = reads["probe"]
        clocks = player_clocks(probe)
        uid = max(clocks, key=lambda u: len(clocks[u]))
        after = [c for c in clocks[uid] if c[0] >= reads["scrub_at"]]
        evidence = {k: reads.get(k) for k in ("before", "scrub_at", "after_300", "after_1500", "after_5000")}
        evidence["core"] = core_view(reads.get("core"))
        evidence["orders_after_scrub"] = [row for row in probe["ev"] if row[1] == "order" and row[0] >= reads["scrub_at"]]
        evidence["max_frame_after_scrub"] = max((c[1] for c in after), default=None)
        evidence["wraps_after_scrub"] = wraps(after)
        evidence["clocks_after_scrub"] = after[:40]
        record("manual_scrub_playing_S2", evidence)
        assert evidence["orders_after_scrub"] == [], f"the host re-seeked the Player after the user's scrub: {evidence['orders_after_scrub']}"
        assert evidence["max_frame_after_scrub"] is not None and evidence["max_frame_after_scrub"] <= 59, evidence["max_frame_after_scrub"]


# ---------------------------------------------------------------------------------------------------------------- (a) Variants preview

EXPLORER_READY = {"until": "(()=>{const f=[...document.querySelectorAll('#jvStudioExplorer iframe[data-remotion-stage]')].find(x=>!x.classList.contains('sc-prefab-staged'));"
                           "try{return !!f&&f.contentWindow.__remotionStage.state().phase==='ready'}catch(e){return false}})()", "ms": 90000}


def strip(scene_index: int) -> dict:
    return {"click": f"#jvStudioExplorer .jvx-scene[data-scene=\"{SCENE_IDS[scene_index]}\"]"}


async def explorer_run(tmp_path) -> dict:
    cached = globals().get("_EXPLORER")
    if cached:
        return cached
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        plan = [{"until": "!!window.JarvisStudioExplorer", "ms": 20000}, {"eval": PAGE_PROBE},
                {"eval": f"JarvisStudioExplorer.open({{presentation_id:'{pid}',fullscreen:false}})"},
                EXPLORER_READY, {"wait": 6000},                                   # S1 (3 s): does it loop?
                {"shot": str(tmp_path / "explorer-S1.png")},
                {"eval": f"window.__clip={VISIBLE_RECT}"}, {"value": "click_1_3", "expr": "Math.round(performance.now()-__pg.t0)"},
                strip(2), {"burst": str(tmp_path), "ms": 1500, "clipExpr": "window.__clip", "prefix": "x13", "as": "burst_1_3"},
                EXPLORER_READY, {"wait": 3000}, {"value": "click_3_4", "expr": "Math.round(performance.now()-__pg.t0)"},
                strip(3), {"burst": str(tmp_path), "ms": 1500, "clipExpr": "window.__clip", "prefix": "x34", "as": "burst_3_4"},
                EXPLORER_READY, {"wait": 2000}, {"value": "probe", "expr": READ_PROBE}]
        result = await run_long(stack.page_url, plan, timeout=300)
        reads = result["reads"]
        probe = reads.get("probe") or {}
        rows, clocks, scene_of = frame_rows(probe), player_clocks(probe), scene_of_uid(probe)
        frames = []
        for uid, scene in scene_of.items():
            frames.append({"uid": uid, "scene": scene, "first_play": first_play(probe, uid), "wraps": wraps(clocks.get(uid, [])),
                           "mount_ms": next(r[0] for r in probe["ev"] if r[1] == "mount" and r[2] == uid),
                           "ready_ms": next((r[0] for r in probe["ev"] if r[1] == "status" and r[2] == uid and r[3] == "ready"), None),
                           "gone_ms": next((r[0] for r in probe["ev"] if r[1] == "gone" and r[2] == uid), None)})
        evidence = {"frames": frames, "blank_spans_ms": blank_spans(probe, place="explorer"),
                    "bursts": {k: bursts_classified(v) for k, v in reads.items() if k.startswith("burst") and isinstance(v, list)},
                    "clicks_ms": {"S1->S3": reads.get("click_1_3"), "S3->S4": reads.get("click_3_4")},
                    "orders": [row for row in probe.get("ev", []) if row[1] == "order"], "failed": reads.get("failed")}
        for key, click, target in (("burst_1_3", reads.get("click_1_3"), "S3"), ("burst_3_4", reads.get("click_3_4"), "S4")):
            burst = evidence["bursts"].get(key) or []
            first_scene = next((t for t, c, _f in burst if c == target), None)
            evidence.setdefault("click_to_first_scene_pixels_ms", {})[key] = None if first_scene is None or click is None else first_scene - click
        del rows
        record("explorer_preview", evidence,
               [tmp_path / "explorer-S1.png"] + [p for burst in evidence["bursts"].values() for p in transition_shots(burst, tmp_path, 4)])
        globals()["_EXPLORER"] = evidence
        return evidence


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S03 repro: defect B — the Variants preview host has no swapPrefix: a slide change unmounts the frame "
                                       "and mounts a fresh one (loading gap) — fixed by Slice 06/11")
async def test_variants_slide_change_never_shows_an_empty_preview(tmp_path):
    """(a) Changing slide in Variants keeps a ready picture on screen: no interval without a ready preview frame."""

    evidence = await explorer_run(tmp_path)
    harness(evidence["failed"] is None, evidence["failed"])
    assert evidence["blank_spans_ms"] == [], f"empty preview spans (start ms, duration ms): {evidence['blank_spans_ms']}"
    # what the screen shows (captures right after the click), not only what the DOM says: never an empty / dark preview
    seen = [c for burst in evidence["bursts"].values() for _t, c, _f in burst]
    assert seen and all(c.startswith("S") for c in seen), f"click -> first scene pixels (ms): {evidence['click_to_first_scene_pixels_ms']}"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S03 repro: defect A/C — the Variants preview Player is loop:true and nobody orders it: a 3 s slide "
                                       "replays forever — fixed by Slice 06")
async def test_variants_preview_plays_a_slide_once_and_holds(tmp_path):
    """(a) A previewed 3 s slide plays from frame 0 to its end and holds; it never wraps by itself."""

    evidence = await explorer_run(tmp_path)
    first = next(f for f in evidence["frames"] if f["scene"] == "S1")
    assert first["first_play"] and first["first_play"][1] == 0, first
    assert first["wraps"] == [], f"S1 preview looped {len(first['wraps'])} times: {first['wraps'][:3]}"


# ---------------------------------------------------------------------------------------------------------------- (b) Variants play buttons

def by_text(label: str) -> str:
    return (f"(()=>{{const b=[...document.querySelectorAll('#jvStudioExplorer .jvx-play button')].find(x=>x.textContent.trim()==={label!r});"
            "if(!b)return null;const r=b.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S03 repro: defect A — « Tout jouer » starts a MANUAL run (no scope) and closes Variants for the "
                                       "floating stage; nothing advances after scene 1 — fixed by Slice 06/10")
async def test_variants_play_all_plays_the_whole_presentation_inside_variants(tmp_path):
    """(b) « Tout jouer » starts a chained play (`scope: all`), keeps Variants open, and the run reaches scene 2 by itself."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        plan = [{"until": "!!window.JarvisStudioExplorer", "ms": 20000}, {"eval": PAGE_PROBE},
                {"eval": f"JarvisStudioExplorer.open({{presentation_id:'{pid}',fullscreen:false}})"}, EXPLORER_READY, {"wait": 500},
                {"clickExpr": by_text("Tout jouer")}, {"wait": 1500}, {"value": "explorer_open", "expr": "JarvisStudioExplorer.isOpen()"},
                http_step(stack, "core_start", "GET", PLAYBACK), {"wait": 9000},
                {"value": "explorer_open_later", "expr": "JarvisStudioExplorer.isOpen()"}, {"shot": str(tmp_path / "play-all-after-9s.png")},
                http_step(stack, "core_later", "GET", PLAYBACK), {"value": "probe", "expr": READ_PROBE}]
        result = await run_long(stack.page_url, plan, timeout=240)
        reads = result["reads"]
        probe = reads.get("probe") or {}
        evidence = {"explorer_open_after_click": reads.get("explorer_open"), "explorer_open_9s": reads.get("explorer_open_later"),
                    "core_start": core_view(reads.get("core_start")), "core_9s": core_view(reads.get("core_later")),
                    "frames": [(r[0], r[2], r[3], r[4]) for r in probe.get("ev", []) if r[1] == "mount"], "failed": reads.get("failed")}
        record("variants_play_all", evidence, [tmp_path / "play-all-after-9s.png"])
        assert evidence["core_start"]["scope"] == "all", evidence
        assert evidence["explorer_open_9s"] is True, evidence
        assert (evidence["core_9s"]["scene"] or 0) >= 2, evidence


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S03 repro: defect A — « Jouer cette slide » starts a MANUAL run (no scope) and closes Variants — "
                                       "fixed by Slice 06/10")
async def test_variants_play_this_slide_plays_the_slide_in_scene_scope(tmp_path):
    """(b) On S3, « Jouer cette slide » plays S3 (`scope: scene`, position on S3) and keeps Variants open."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        plan = [{"until": "!!window.JarvisStudioExplorer", "ms": 20000}, {"eval": PAGE_PROBE},
                {"eval": f"JarvisStudioExplorer.open({{presentation_id:'{pid}',fullscreen:false}})"}, EXPLORER_READY, strip(2), EXPLORER_READY,
                {"wait": 500}, {"clickExpr": by_text("Jouer cette slide")}, {"wait": 2500},
                {"value": "explorer_open", "expr": "JarvisStudioExplorer.isOpen()"}, http_step(stack, "core", "GET", PLAYBACK)]
        result = await run_long(stack.page_url, plan, timeout=240)
        reads = result["reads"]
        evidence = {"explorer_open": reads.get("explorer_open"), "core": core_view(reads.get("core")), "failed": reads.get("failed")}
        record("variants_play_slide", evidence)
        assert evidence["core"]["scope"] == "scene" and evidence["core"]["scene"] == 3, evidence
        assert evidence["explorer_open"] is True, evidence


assert TARGET_MS == 8000 and frames_of(2) == 900   # the fixture the reasons above speak of

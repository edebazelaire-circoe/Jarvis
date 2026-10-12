"""Continuous Variants playback through a Core restart and a lost Core (handoff jarvis-remotion-native-studio-playback-fix, Slice 16).

VRAI Core, VRAI Control Center, VRAI Chrome sans tête, VRAI Player Remotion de Variantes, sur des ports libres et une racine jetable
(`RemotionStack`) ; jamais le Jarvis vivant. Same 9-scene gate deck as Slices 03, 05 and 14 (`presentation_playback_gate_world.DECK`).

Once S2 is on screen, Core goes away (`RemotionStack.stop_core`: protocol server, sandbox listener, Core) while the Control Center and the
page stay, then comes back on the same ports and data root (`start_core`, a new Core life). Two outages:

- `restart`: 3 s, a Core restart in the middle of a scene;
- `lost`: 20 s, longer than S2: Core is unreachable across the S2 > S3 hand-over. S3 cannot be served: the veil says so with « Réessayer »;
  once Core is back the user presses « Réessayer » and playback goes on from S3 frame 0 (no automatic retry exists: measured, not assumed).

What the contract asks (`docs/presentation-studio.md`, *Presentation experience contract* § 4 and *Failure, waiting and recovery*):
continuous playback is the Variants Player's own and needs no Core run, so a scene already loaded keeps playing; a scene that cannot be
loaded is SAID (failed / waiting, never a silent stall) and playback can go on once Core is back; no scene is cut, wrapped or entered
mid-animation. Measured: the scenes shown in order, each one's first and last frame, the hand-over gaps, what the page said during the
outage, and the wall time against the 74 s of content.

Evidence: `JARVIS_PLAYBACK_GATE_EVIDENCE_DIR` (`resilience_<outage>.json`, small PNGs, home path masked).
"""

from __future__ import annotations

import asyncio
import shutil
import time

from aiohttp import web
import pytest

from tests.fakes.remotion_player_stack import RemotionStack, free_port, runtime_dir_from_env
from tests.unit.presentation_playback_gate_world import (
    PAGE_PROBE, PLAYBACK, PREFABS, READ_PROBE, VISIBLE_RECT, frames_of, harness, make_deck, next_boundary, record, run_long,
)
from tests.unit.test_presentation_continuous_playback_browser import EXPLORER_READY, LIRE, PHASE, boundaries, per_scene
from tests.unit.test_remotion_player_realpage_browser import http_step

RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

ENDED = f"({PHASE}==='ended')"
#: Every 200 ms: the Variants playback view, the notice and the stage veil, as the user would read them.
SAMPLER = ("(()=>{if(window.__rs)return;const R=window.__rs={t0:performance.now(),rows:[]};setInterval(()=>{let v=null;"
           "try{v=JarvisStudioExplorer.playback.view()}catch(e){}const n=document.querySelector('#jvStudioExplorer .jvx-notice-text');"
           "const veil=document.querySelector('#jvStudioExplorer .jvx-stage-veil');"
           "R.rows.push([Math.round(performance.now()-R.t0),v&&v.phase,v&&v.scene_index,v&&v.frame,v&&v.error&&v.error.code,"
           "n?n.textContent.trim().slice(0,160):'',veil&&!veil.hidden&&veil.offsetParent?veil.textContent.trim().slice(0,160):''])},200)})()")
RETRY = ("(()=>{const b=[...document.querySelectorAll('#jvStudioExplorer .jvx-stage-veil button')].find(x=>!x.hidden&&x.textContent.trim()==='Réessayer');"
         "if(!b)return null;const r=b.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()")
S2_ON_SCREEN = f"(()=>{{let v=null;try{{v=JarvisStudioExplorer.playback.view()}}catch(e){{}}return !!v&&v.scene_index===1&&v.phase==='playing'}})()"


def said(rows: list[list], start_ms: int, end_ms: int) -> list[dict]:
    """The distinct things the page showed between two instants (phase, scene, error, notice, veil), in order."""

    out, last = [], None
    for at, phase, scene, frame, code, notice, veil in rows:
        if not start_ms <= at <= end_ms:
            continue
        key = (phase, scene, code, notice, veil)
        if key != last:
            out.append({"ms": at, "phase": phase, "scene": None if scene is None else scene + 1, "frame": frame, "error": code,
                        "notice": notice, "veil": veil})
            last = key
    return out


@pytest.mark.parametrize(("outage", "down_s", "retry"), [("restart", 3, False), ("lost", 20, True)])
async def test_continuous_variants_playback_through_a_core_outage(tmp_path, outage, down_s, retry):
    shots = tmp_path / "shots"
    shots.mkdir()
    gone = asyncio.Event()
    marks: dict[str, float] = {}

    async def signal(_request: web.Request) -> web.Response:
        gone.set()
        return web.json_response({"ok": True})

    signal_app = web.Application()
    signal_app.router.add_get("/outage", signal)
    runner = web.AppRunner(signal_app)
    await runner.setup()
    signal_port = free_port()
    await web.TCPSite(runner, "127.0.0.1", signal_port).start()
    try:
        async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
            pid, _vid = await make_deck(stack)
            for prefab in PREFABS:   # warm compiles (the outputs are on disk: the new Core life finds them)
                status, _h, _t = await stack.get(f"/api/remotion/player/{prefab}/1")
                assert status == 200, prefab

            async def take_core_away() -> None:
                await gone.wait()
                marks["down"] = time.time()
                await stack.stop_core()
                await asyncio.sleep(down_s)
                await stack.start_core()
                marks["up"] = time.time()

            plan: list[dict] = [
                {"until": "!!window.JarvisStudioExplorer", "ms": 20000}, {"eval": PAGE_PROBE}, {"eval": SAMPLER},
                {"eval": f"JarvisStudioExplorer.open({{presentation_id:'{pid}',fullscreen:false}})"}, EXPLORER_READY, {"wait": 1500},
                {"eval": f"window.__clip={VISIBLE_RECT}"}, {"clickExpr": LIRE}, {"until": f"({PHASE}==='playing')", "ms": 30000, "required": True},
                {"until": S2_ON_SCREEN, "ms": 30000, "required": True, "as": "s2_on_screen"},
                {"value": "down_at", "expr": "Math.round(performance.now()-__rs.t0)"},
                {"http": {"method": "GET", "url": f"http://127.0.0.1:{signal_port}/outage"}, "as": "signal"},
                {"wait": min(down_s * 1000 // 2, 6000)}, {"shot": str(shots / f"{outage}-during.png")},
                {"value": "view_during", "expr": "JarvisStudioExplorer.playback.view()"},
            ]
            if retry:   # the user's gesture once Core is back: the veil's « Réessayer » (contract § 4.11), never an automatic skip
                plan += [{"until": f"({PHASE}==='failed')", "ms": 60000, "as": "failed_seen"},
                         {"value": "failed_at", "expr": "Math.round(performance.now()-__rs.t0)"},
                         {"shot": str(shots / f"{outage}-failed.png")}, {"value": "view_failed", "expr": "JarvisStudioExplorer.playback.view()"},
                         {"wait": down_s * 1000}, {"clickExpr": RETRY, "as": "retry"},
                         {"value": "retry_at", "expr": "Math.round(performance.now()-__rs.t0)"}]
            plan += [{"until": f"({next_boundary()})||{ENDED}", "ms": 70000, "as": f"boundary_{n}"} for n in range(2, 9)]
            plan += [{"until": ENDED, "ms": 90000, "as": "ended"}, {"value": "ended_at", "expr": "Math.round(performance.now()-__rs.t0)"},
                     {"wait": 3000}, {"shot": str(shots / f"{outage}-end.png")},
                     {"value": "view_end", "expr": "JarvisStudioExplorer.playback.view()"}, {"value": "open", "expr": "JarvisStudioExplorer.isOpen()"},
                     {"value": "probe", "expr": READ_PROBE}, {"value": "rs", "expr": "window.__rs"},
                     http_step(stack, "core_after", "GET", PLAYBACK)]
            outage_task = asyncio.get_running_loop().create_task(take_core_away())
            began = time.time()
            try:
                result = await run_long(stack.page_url, plan, timeout=900)
            finally:
                if not outage_task.done():
                    gone.set()
                await outage_task
            took = time.time() - began
            reads = result["reads"]
            probe, rs = reads.get("probe"), reads.get("rs")
            harness(probe and rs, reads.get("failed"))
            down_ms = reads.get("down_at") or 0
            up_ms = down_ms + round((marks["up"] - marks["down"]) * 1000)
            scenes = per_scene(probe, "explorer")
            evidence = {
                "outage": outage, "core_down_s": round(marks["up"] - marks["down"], 1), "wall_s": round(took, 1), "content_s": 74,
                "page_ms": {"core_down": down_ms, "core_up": up_ms, "ended": reads.get("ended_at")},
                "failed": reads.get("failed"), "ended": reads.get("ended"), "explorer_open_at_end": reads.get("open"),
                "view_during": reads.get("view_during"), "view_end": reads.get("view_end"),
                "failed_seen_ms": reads.get("failed_at"), "view_failed": reads.get("view_failed"), "retry_clicked_ms": reads.get("retry_at"),
                "said_during_outage": said(rs["rows"], down_ms, up_ms + 2000),
                "said_whole_run": said(rs["rows"], 0, 10 ** 9),
                "scenes": [{k: s[k] for k in ("scene", "first_play", "max_frame", "played_ms", "wraps", "duration")} for s in scenes],
                "boundaries": boundaries(probe, "explorer"),
                "core_after": (reads.get("core_after") or {}).get("status"),
                "console_errors": [line for line in result.get("console", []) if "error" in str(line).lower()][:20],
            }
            evidence["failed_attempts"] = [x["scene"] for x in evidence["scenes"] if x["first_play"] is None and x["max_frame"] is None]
            record(f"resilience_{outage}", evidence, [p for p in (shots / f"{outage}-during.png", shots / f"{outage}-failed.png",
                                                                  shots / f"{outage}-end.png") if p.exists()])
            harness("failed" not in reads, reads.get("failed"))
            assert evidence["core_after"] == 200, "the new Core life answers"
            # A frame Core could not serve never played (no clock): it is the failed attempt the veil named, kept apart, never a scene shown.
            attempts = [s for s in evidence["scenes"] if s["first_play"] is None and s["max_frame"] is None]
            evidence["scenes"] = [s for s in evidence["scenes"] if s not in attempts]
            evidence["failed_attempts"] = [s["scene"] for s in attempts]
            assert len(attempts) == (1 if retry else 0), f"failed attempts: {evidence['failed_attempts']}"
            shown = [s["scene"] for s in evidence["scenes"]]
            assert shown[-9:] == [f"S{n}" for n in range(1, 10)] and len(shown) == 9, f"scenes shown in order, once each: {shown}"
            for scene in evidence["scenes"][1:]:
                n = int(scene["scene"][1:]) - 1
                assert scene["first_play"] and scene["first_play"][1] == 0, scene
                assert scene["max_frame"] == frames_of(n) - 1 and scene["wraps"] == [], scene
            for b in evidence["boundaries"]:
                if b["in_first_frame"] is None and b["to"] in evidence["failed_attempts"]:
                    continue   # the hand-over to the failed attempt: the outgoing Player held its last frame under the veil
                assert b["out_last_frame"] == b["out_expected_last"] and b["in_first_frame"] == 0, b
            assert evidence["ended"] is True and evidence["view_end"]["phase"] == "ended", evidence["view_end"]
            assert evidence["explorer_open_at_end"] is True
            if retry:   # the scene Core could not serve was SAID (veil, real reason, « Réessayer »), not skipped, and replayed from frame 0
                failed = evidence["view_failed"] or {}
                assert reads.get("failed_seen") is True and failed.get("retryable") is True and (failed.get("error") or {}).get("code"), failed
                assert any(row["veil"] and "lecture impossible" in row["veil"] for row in evidence["said_whole_run"]), "the veil names the scene"
    finally:
        await runner.cleanup()

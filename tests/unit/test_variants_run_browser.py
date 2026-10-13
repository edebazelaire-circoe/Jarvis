"""A presentation run in Variants, on the REAL Control Center page, in a REAL headless Chrome, against an isolated REAL Core
(jarvis-remotion-native-studio-playback-fix, Slice 09: the legacy floating viewer is retired).

Before Slice 09 a run showed in a Board window (`studio-stage-<run_id>`) under a floating band (`#jvStudioBand`); this file replaces
the two proofs of that viewer (`test_presentation_studio_player_browser.py`, `test_presentation_studio_player_realpage_browser.py`).
Nothing is simulated except the display: a real `JarvisCoreApplication` behind the real `LocalProtocolServer` (own data root, own
ports), a real presentation with a real score, the real `ControlCenter` page relaying to it, real CDP keys and clicks.

Proved, measured:

- a run Core starts (as voice and MCP do) opens Variants windowed on it, by itself, once: no Board window, no band; the presenter
  strip (`.jvx-presenter`) says who presents and where the run is, the slider is read-only;
- the § 4.15 « Presenter run » keys on the Variants stage drive the run exactly once each (→ ← next / previous, Début / Fin first /
  last item, Espace pause / resume); keys typed in another field of the page are untouched;
- `F` puts the Variants stage in real fullscreen, the keys still act once each there, leaving it keeps the run;
- Échap closes Variants and pauses a playing run, which never reopens Variants by itself;
- the presenter strip never overlaps the interaction-mode HUD and stays on screen (1280x720 and 1920x1080); during a run the HUD
  stays live and drawn above Variants, beside it in the rail's column (Slice 09 rework), and becomes modal-inert again when the run
  ends.

Not provable headless (Human check HV-RFX-09-01, `docs/OPERATIONS.md`): the physical Esc key, sound, a second screen.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.interaction_mode_view import CoreInteractionModeTransport, CoreInteractionModeView
from jarvis.runtime.presentation_studio_relay import PLAYBACK_ROUTE
from jarvis.runtime.scene_view import CoreSceneTransport, CoreSceneView
from tests.unit.test_fullscreen_browser import _chrome
from tests.unit.test_presentation_studio_playback_routes import presentation_with_score, start_body
from tests.unit.test_presentation_studio_routes import Core

HARNESS = Path(__file__).parent / "_fullscreen_browser.mjs"
EXPLORER = "window.JarvisStudioExplorer"
STRIP = "document.querySelector('#jvStudioExplorer .jvx-presenter')"
STAGE_SEL = "#jvStudioExplorer .jvx-stage"
POS = "(window.JarvisStudioPlayer.view().position||{}).index"
PHASE = "window.JarvisStudioPlayer.view().phase"
FOCUS_STAGE = {"eval": f"document.querySelector('{STAGE_SEL}').focus()"}


def _drive(url: str, plan: list, *, viewport: str = "1280x720") -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    done = subprocess.run([node, str(HARNESS), url, _chrome(), json.dumps(plan)], capture_output=True, text=True,
                          encoding="utf-8", timeout=240, check=False,
                          env={**os.environ, "CDP_REAL_PAGE": "1", "CDP_VIEWPORT": viewport})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


async def drive(url: str, plan: list, **kwargs) -> dict:
    # The blocking subprocess runs in a thread so the event loop keeps serving Core and the Control Center.
    return await asyncio.to_thread(_drive, url, plan, **kwargs)


def _until(expr: str, ms: int = 8000) -> dict:
    return {"until": expr, "ms": ms}


def _no_noise(result: dict) -> None:
    errors = [line for line in result["console"] if line.startswith(("error", "warning")) and "poll_failed" not in line]
    assert not result["errors"] and not errors, (result["errors"], errors)


#: Variants is open on the run, its scene is mounted under the run surface id, the presenter strip is on screen.
READY = _until(f"{EXPLORER}.state().open && !!{EXPLORER}.run.view() && !!{STRIP} && !{STRIP}.hidden"
               f" && String({EXPLORER}.run.objectId()||'').startsWith('variants-run-') && {EXPLORER}.run.stats().mounted>0"
               " && !!document.querySelector('#jvStudioExplorer .jvx-slot iframe.sc-prefab-frame')", 30000)

GEOMETRY = {"value": "geometry", "expr": """(()=>{
  const rect=el=>{if(!el)return null;const r=el.getBoundingClientRect();return {l:Math.round(r.left),t:Math.round(r.top),r:Math.round(r.right),b:Math.round(r.bottom)}};
  const band=document.querySelector('#jvStudioExplorer .jvx-presenter'),hud=document.getElementById('interactionModeHud');
  const btn=hud&&hud.querySelector('button'),rail=document.getElementById('presentationRail');
  const a=rect(band),h=rect(btn||hud),r=rail&&!rail.hidden?rect(rail):null;
  const meets=(x,y)=>!!x&&!!y&&x.l<y.r&&y.l<x.r&&x.t<y.b&&y.t<x.b;
  const mid=btn?document.elementFromPoint((h.l+h.r)/2,(h.t+h.b)/2):null;
  let inert=false;for(let n=btn;n;n=n.parentElement)if(n.inert)inert=true;
  return {band:a,hud:h,rail:r,overlap:meets(a,h),railOverlap:meets(r,h),hudReachable:!!mid&&btn.contains(mid),hudInert:inert,
    runClass:document.documentElement.classList.contains('jvx-run'),vw:innerWidth,vh:innerHeight};
})()"""}


async def wire(core: Core, tmp_path: Path) -> str:
    """What `jarvis/app.py` wires: the scene relay (the page renders what Core's scene holds) and the mode relay (the HUD)."""

    stack = core.stack
    port = int(stack.core_url.rsplit(":", 1)[1])
    token_file = tmp_path / "core.token"
    stack.center.scene_view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=port, token_file=token_file))
    stack.center.interaction_mode_view = CoreInteractionModeView(
        CoreInteractionModeTransport(host="127.0.0.1", port=port, token_file=token_file))
    return f"http://127.0.0.1:{stack.cc_port}/"


@pytest.fixture
async def run(tmp_path):
    """An isolated Core with a presentation and a running `user_presenter` run started by Core; yields `(core, url)`."""

    async with Core(tmp_path) as core:
        url = await wire(core, tmp_path)
        pid, _ = await presentation_with_score(core)
        status, started, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/start", json=start_body(pid))
        assert status == 200 and started["state"]["phase"] == "playing", started
        yield core, url
        await core.stack.center.scene_view.aclose()


async def test_a_run_core_starts_opens_variants_windowed_with_the_presenter_strip_and_no_floating_viewer(run, tmp_path):
    core, url = run
    shot = tmp_path / "variants-run-1280x720.png"
    result = await drive(url, [
        {"wait": 600}, READY, {"wait": 400},
        {"value": "seen", "expr": f"""JSON.stringify({{mode:{EXPLORER}.state().mode,fs:!!document.fullscreenElement,
          board:!!document.querySelector('[data-object-id^="studio-stage-"]'),band:!!document.getElementById('jvStudioBand'),
          role:{STRIP}.querySelector('.jvx-presenter-role').textContent,where:{STRIP}.querySelector('.jvx-presenter-where').textContent,
          scrub:document.querySelector('#jvStudioExplorer [role=slider]').getAttribute('aria-disabled'),
          tree:document.querySelector('#jvStudioExplorer .jvx-treepane').inert,
          stops:[...document.querySelectorAll('#jvStudioExplorer button')].filter(b=>!b.hidden&&b.offsetParent&&b.textContent.trim()==='Arrêter').length}})"""},
        {"shot": str(shot)},
    ])
    reads = result["reads"]
    assert "failed" not in reads, reads
    seen = json.loads(reads["seen"])
    assert seen["mode"] == "windowed" and seen["fs"] is False, "a run Core starts opens Variants windowed (never fullscreen by itself)"
    assert seen["board"] is False and seen["band"] is False, "the floating viewer is retired: no Board stage window, no band"
    assert seen["role"] == "Vous présentez" and seen["where"].startswith("Scène 1/"), seen
    assert seen["scrub"] == "true" and seen["tree"] is True and seen["stops"] == 1, "one « Arrêter » (the transport's)"
    assert shot.stat().st_size > 1000
    _no_noise(result)


async def test_the_presenter_run_keys_on_the_variants_stage_act_once_each_and_other_fields_are_untouched(run):
    core, url = run
    result = await drive(url, [
        {"wait": 600}, READY, FOCUS_STAGE,
        {"value": "start", "expr": f"[{POS},{PHASE}]"},
        {"key": "ArrowRight"}, _until(f"{POS}===2"), {"value": "after_right", "expr": POS},
        {"key": "ArrowLeft"}, {"wait": 900}, {"value": "after_restart", "expr": POS},
        {"key": "ArrowLeft"}, {"key": "ArrowLeft"}, _until(f"{POS}===1"), {"value": "after_left", "expr": POS},
        {"key": "End"}, _until(f"{POS}===3"), {"value": "after_end", "expr": POS},
        {"key": "Home"}, _until(f"{POS}===1"), {"value": "after_home", "expr": POS},
        {"key": " "}, _until(f"{PHASE}==='paused'"), {"value": "space_phase", "expr": PHASE},
        {"key": " "}, _until(f"{PHASE}==='playing'"), {"value": "space_again", "expr": PHASE},
        {"wait": 300}, {"value": "settled", "expr": f"[{POS},{PHASE}]"},
        # a real text field of the page: the run keys typed there are text, never commands
        {"eval": "(()=>{const f=document.createElement('input');f.id='probeField';f.type='text';f.style.cssText="
                 "'position:fixed;right:20px;top:20px;z-index:2147483647';document.body.appendChild(f);f.focus()})()"},
        {"key": "a"}, {"key": "ArrowRight"}, {"key": " "}, {"key": "End"}, {"wait": 500},
        {"value": "field", "expr": "document.getElementById('probeField').value"},
        {"value": "outside", "expr": f"[{POS},{PHASE}]"},
    ])
    reads = result["reads"]
    assert "failed" not in reads, reads
    assert reads["start"] == [1, "playing"]
    assert (reads["after_right"], reads["after_restart"], reads["after_left"], reads["after_end"], reads["after_home"]) == (2, 2, 1, 3, 1), reads
    assert (reads["space_phase"], reads["space_again"]) == ("paused", "playing")
    assert reads["settled"] == [1, "playing"], "each key acted once (no double command)"
    assert reads["field"] == "a ", reads["field"]
    assert reads["outside"] == [1, "playing"], "no key typed in another field reached the run"
    state = await core.client.presentation_studio_playback_state()
    assert state["state"]["phase"] == "playing" and state["state"]["position"]["index"] == 1
    _no_noise(result)


async def test_f_puts_the_variants_stage_in_fullscreen_where_the_keys_act_once_and_leaving_keeps_the_run(run):
    core, url = run
    result = await drive(url, [
        {"wait": 600}, READY, FOCUS_STAGE,
        {"key": "f"}, _until("!!document.fullscreenElement", 6000), {"wait": 400},
        {"value": "fs", "expr": "!!document.fullscreenElement&&!!document.fullscreenElement.closest('#jvStudioExplorer')"},
        {"value": "strip_in_fs", "expr": f"!!document.fullscreenElement&&document.fullscreenElement.contains({STRIP})&&!{STRIP}.hidden"},
        {"eval": f"document.querySelector('{STAGE_SEL}').focus()"},
        {"key": "ArrowRight"}, _until(f"{POS}===2"), {"wait": 300}, {"value": "after_one", "expr": POS},
        {"key": "End"}, _until(f"{POS}===3"), {"wait": 300}, {"value": "after_end", "expr": POS},
        {"eval": "document.exitFullscreen()"}, _until("!document.fullscreenElement", 6000), {"wait": 300},
        {"value": "back", "expr": f"[{EXPLORER}.state().open,{PHASE},!{STRIP}.hidden]"},
    ])
    reads = result["reads"]
    assert "failed" not in reads, reads
    assert reads["fs"] is True, "F enters real fullscreen on the Variants stage"
    assert reads["strip_in_fs"] is False, "the presenter strip is outside the theater (windowed only)"
    assert (reads["after_one"], reads["after_end"]) == (2, 3), reads
    assert reads["back"] == [True, "playing", True], "leaving fullscreen keeps Variants, the run and the strip"
    state = await core.client.presentation_studio_playback_state()
    assert state["state"]["position"]["index"] == 3
    _no_noise(result)


async def test_escape_closes_variants_and_pauses_the_run_which_never_reopens_it_by_itself(run):
    core, url = run
    result = await drive(url, [
        {"wait": 600}, READY, FOCUS_STAGE,
        {"key": "Escape"}, _until(f"!{EXPLORER}.state().open", 6000),
        _until(f"{PHASE}==='paused'", 10000),
        {"wait": 6000},
        {"value": "after", "expr": f"[{EXPLORER}.state().open,{PHASE}]"},
    ])
    reads = result["reads"]
    assert "failed" not in reads, reads
    assert reads["after"] == [False, "paused"], "closed by the user: the run pauses, Variants stays closed"
    state = await core.client.presentation_studio_playback_state()
    assert state["state"]["phase"] == "paused"
    _no_noise(result)


@pytest.mark.parametrize("viewport", ["1280x720", "1920x1080"])
async def test_the_presenter_strip_never_overlaps_the_mode_hud_and_stays_on_screen(run, viewport, tmp_path):
    core, url = run
    shot = tmp_path / f"strip-{viewport}.png"
    result = await drive(url, [{"wait": 600}, READY, {"wait": 500}, GEOMETRY, {"shot": str(shot)}], viewport=viewport)
    geometry = result["reads"]["geometry"]
    assert geometry["hud"] is not None, "the interaction-mode HUD is part of the real page"
    assert geometry["overlap"] is False, geometry
    # Slice 09 rework (agent 0's decision): during a run the interaction-mode HUD stays live and drawn above Variants, in the rail's
    # column (whose list stops above it): « Refusé par la voix » and the way out of PRESENTATION stay visible and clickable.
    assert geometry["runClass"] is True and geometry["hudInert"] is False, geometry
    assert geometry["hudReachable"] is True, geometry
    assert geometry["railOverlap"] is False, geometry
    h = geometry["hud"]
    assert h["l"] >= 0 and h["b"] <= geometry["vh"], geometry
    band = geometry["band"]
    assert band["l"] >= 0 and band["r"] <= geometry["vw"] and band["t"] >= 0 and band["b"] <= geometry["vh"], geometry
    assert shot.stat().st_size > 1000
    _no_noise(result)

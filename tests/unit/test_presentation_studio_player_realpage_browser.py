"""The playback band and keyboard on the REAL Control Center page, driven by a REAL Chrome against an isolated Core (Slice 12 rework).

Why this file exists (QA-1 B1): the first browser proof (`test_presentation_studio_player_browser.py`) uses a synthetic page,
which has no copy of `control_center_scene_page.js`'s own keyboard navigation. That handler calls `preventDefault()` on Arrow /
Home / End / Escape of a focused window node, and the player used to ignore a prevented key: in the real page the arrows did
nothing. Here nothing is simulated except the headless display:

- a real `JarvisCoreApplication` behind the real `LocalProtocolServer` (own data root, own ports), a real presentation with a
  real score, the real base prefab `jarvis.window`;
- the real `ControlCenter` page, served over HTTP and relaying to that Core, with the real scene page, fullscreen module and
  player module;
- real CDP input events (clicks give the Fullscreen API its user activation; keys are `Input.dispatchKeyEvent`).

Proved, measured: windowed arrows / Home / End / Space / PageDown / P and Escape (pause) drive the run once each; the scene
page does not also act on a consumed key; keys typed in another input of the Control Center and keys on another window are
untouched; fullscreen acts once per key; the band never covers the interaction-mode HUD at 1280x720 and 1920x1080.

Not provable headless (Human check, `docs/OPERATIONS.md`): the physical Esc key, a second screen, a projector.
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
STAGE = "document.querySelector('[data-object-id^=\"studio-stage-\"]')"
POS = "(window.JarvisStudioPlayer.view().position||{}).index"
PHASE = "window.JarvisStudioPlayer.view().phase"
KEYS = "window.JarvisStudioPlayer.stats().keys"


def _drive(url: str, plan: list, *, viewport: str = "1280x720") -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    done = subprocess.run([node, str(HARNESS), url, _chrome(), json.dumps(plan)], capture_output=True, text=True,
                          encoding="utf-8", timeout=240, check=False,
                          env={**os.environ, "CDP_REAL_PAGE": "1", "CDP_VIEWPORT": viewport})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _until(expr: str, ms: int = 8000) -> dict:
    return {"until": expr, "ms": ms}


#: The band is on screen and the stage window of the run is rendered by the real scene page.
READY = _until(f"!!document.getElementById('jvStudioBand') && !document.getElementById('jvStudioBand').hidden && !!{STAGE}", 15000)

#: Click the stage window's title bar: the host element (tabindex -1) takes the focus, as a user clicking it would.
FOCUS_STAGE = {"click": '[data-object-id^="studio-stage-"] .sc-wtitle'}


def _geometry(reads: dict) -> dict:
    return reads["geometry"]


GEOMETRY = {"value": "geometry", "expr": """(()=>{
  const rect=el=>{if(!el)return null;const r=el.getBoundingClientRect();return {l:Math.round(r.left),t:Math.round(r.top),r:Math.round(r.right),b:Math.round(r.bottom)}};
  const band=document.getElementById('jvStudioBand'),hud=document.getElementById('interactionModeHud');
  const a=rect(band),h=rect(hud);
  const overlap=a&&h&&a.l<h.r&&h.l<a.r&&a.t<h.b&&h.t<a.b;
  const mid=hud?document.elementFromPoint((h.l+h.r)/2,(h.t+h.b)/2):null;
  return {band:a,hud:h,overlap:!!overlap,hudReachable:!!mid&&(hud.contains(mid)||mid===hud),vw:innerWidth,vh:innerHeight};
})()"""}


@pytest.fixture
async def run(tmp_path):
    """An isolated Core with a presentation and a running `user_presenter` run; yields `(core, url)`."""

    async with Core(tmp_path) as core:
        stack = core.stack
        port = int(stack.core_url.rsplit(":", 1)[1])
        token_file = tmp_path / "core.token"
        # What `jarvis/app.py` wires: the scene relay (the page renders what Core's scene holds) and the mode relay (the HUD).
        stack.center.scene_view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=port, token_file=token_file))
        stack.center.interaction_mode_view = CoreInteractionModeView(
            CoreInteractionModeTransport(host="127.0.0.1", port=port, token_file=token_file))
        pid, _ = await presentation_with_score(core)
        status, started, _ = await stack.call("POST", f"{PLAYBACK_ROUTE}/start", json=start_body(pid))
        assert status == 200 and started["state"]["phase"] == "playing", started
        yield core, f"http://127.0.0.1:{stack.cc_port}/"
        await stack.center.scene_view.aclose()


async def drive(url: str, plan: list, **kwargs) -> dict:
    # The blocking subprocess runs in a thread so the event loop keeps serving Core and the Control Center.
    return await asyncio.to_thread(_drive, url, plan, **kwargs)


def _no_noise(result: dict) -> None:
    errors = [line for line in result["console"] if line.startswith(("error", "warning")) and "poll_failed" not in line]
    assert not result["errors"] and not errors, (result["errors"], errors)


async def test_windowed_keys_work_on_the_real_page_and_other_inputs_are_untouched(run):
    core, url = run
    result = await drive(url, [
        {"wait": 600}, READY, FOCUS_STAGE,
        {"value": "focus", "expr": f"document.activeElement===({STAGE})||({STAGE}).contains(document.activeElement)"},
        {"value": "start", "expr": f"[{POS},{PHASE}]"},
        {"key": "ArrowRight"}, _until(f"{POS}===2"), {"value": "after_right", "expr": POS},
        {"key": "ArrowLeft"}, _until(f"{POS}===1"), {"value": "after_left", "expr": POS},
        {"key": "End"}, _until(f"{POS}===3"), {"value": "after_end", "expr": POS},
        {"key": "Home"}, _until(f"{POS}===1"), {"value": "after_home", "expr": POS},
        {"key": "ArrowDown"}, _until(f"{POS}===2"), {"key": "ArrowUp"}, _until(f"{POS}===1"),
        {"key": " "}, _until(f"{POS}===2"), {"key": "PageDown"}, _until(f"{POS}===3"),
        {"value": "keys_so_far", "expr": KEYS},
        {"key": "Escape"}, _until(f"{PHASE}==='paused'"), {"value": "escape_phase", "expr": PHASE},
        {"value": "still_focused", "expr": f"({STAGE}).contains(document.activeElement)||document.activeElement===({STAGE})"},
        {"key": "p"}, _until(f"{PHASE}==='playing'"), {"value": "p_phase", "expr": PHASE},
        {"value": "keys", "expr": KEYS},
    ])
    reads = result["reads"]
    assert "failed" not in reads, reads
    assert reads["focus"] is True and reads["start"] == [1, "playing"]
    assert (reads["after_right"], reads["after_left"], reads["after_end"], reads["after_home"]) == (2, 1, 3, 1), reads
    assert reads["keys_so_far"] == 8, "one command per key: the scene page's handler did not also act, nothing was counted twice"
    assert reads["escape_phase"] == "paused" and reads["p_phase"] == "playing" and reads["keys"] == 10
    assert reads["still_focused"] is True, "the scene page's Escape (blur) did not also run"
    state = await core.client.presentation_studio_playback_state()
    assert state["state"]["phase"] == "playing" and state["state"]["position"]["index"] == 3
    _no_noise(result)


async def test_keys_typed_elsewhere_in_the_control_center_and_on_other_windows_are_untouched(run):
    core, url = run
    result = await drive(url, [
        {"wait": 600}, READY,
        # a real text field of the Control Center page, focused by script (a real click on it is page-layout dependent)
        {"eval": "(()=>{const f=document.createElement('input');f.id='probeField';f.type='text';f.style.cssText="
                 "'position:fixed;right:20px;top:20px;z-index:9000';document.body.appendChild(f);f.focus()})()"},
        {"key": "a"}, {"key": "ArrowRight"}, {"key": " "}, {"key": "Home"}, {"key": "p"}, {"key": "Escape"}, {"wait": 300},
        {"value": "field", "expr": "document.getElementById('probeField').value"},
        {"value": "outside", "expr": f"[{KEYS},{POS},{PHASE}]"},
        # another window of the scene: focus it, press the keys; the player must not act, the page keeps its own navigation
        {"eval": "(()=>{const o=document.createElement('div');o.id='otherWin';o.dataset.objectId='some-other-window';"
                 "o.tabIndex=-1;o.style.cssText='position:fixed;left:30px;top:30px;width:60px;height:40px;z-index:9000';"
                 "document.body.appendChild(o);window.__otherKeys=[];o.addEventListener('keydown',e=>window.__otherKeys.push(e.key));"
                 "o.focus()})()"},
        {"key": "ArrowRight"}, {"key": "End"}, {"key": "Escape"}, {"wait": 300},
        {"value": "other", "expr": f"({{keys:{KEYS},pos:{POS},phase:{PHASE},seen:window.__otherKeys}})"},
    ])
    reads = result["reads"]
    assert "failed" not in reads, reads
    assert reads["field"] == "pa ", reads["field"]        # 'a', Space, then Home moved the caret and 'p' went in front: all typed text
    assert reads["outside"] == [0, 1, "playing"], "no key typed in another input reached the player"
    assert reads["other"]["keys"] == 0 and reads["other"]["pos"] == 1 and reads["other"]["phase"] == "playing"
    assert reads["other"]["seen"] == ["ArrowRight", "End", "Escape"], "the other window's own handler still sees its keys"
    _no_noise(result)


async def test_fullscreen_keys_act_once_each_and_leaving_fullscreen_restores_the_band(run):
    core, url = run
    result = await drive(url, [
        {"wait": 600}, READY,
        {"click": "#jvStudioBand .jvsp-full"},
        _until("!!document.fullscreenElement", 6000),
        {"value": "fs", "expr": "!!document.fullscreenElement && document.fullscreenElement.dataset.objectId.startsWith('studio-stage-')"},
        {"value": "before", "expr": f"[{POS},{KEYS}]"},
        {"key": "ArrowRight"}, _until(f"{POS}===2"), {"wait": 300}, {"value": "after_one", "expr": f"[{POS},{KEYS}]"},
        {"key": "ArrowLeft"}, _until(f"{POS}===1"), {"key": "End"}, _until(f"{POS}===3"), {"wait": 300},
        {"value": "after_more", "expr": f"[{POS},{KEYS}]"},
        {"eval": "document.exitFullscreen()"}, _until("!document.fullscreenElement", 6000),
        {"value": "back", "expr": "[document.getElementById('jvStudioBand').hidden,"
                                  f"{PHASE}]"},
    ])
    reads = result["reads"]
    assert "failed" not in reads, reads
    assert reads["fs"] is True and reads["before"] == [1, 0]
    assert reads["after_one"][0] == 2, reads
    assert reads["after_more"][0] == 3, reads
    assert reads["back"] == [False, "playing"], "leaving fullscreen brings the band back; the run is unchanged"
    _no_noise(result)
    state = await core.client.presentation_studio_playback_state()
    assert state["state"]["position"]["index"] == 3


@pytest.mark.parametrize("viewport", ["1280x720", "1920x1080"])
async def test_the_band_never_covers_the_mode_hud(run, viewport, tmp_path):
    core, url = run
    shot = tmp_path / f"band-{viewport}.png"
    result = await drive(url, [{"wait": 600}, READY, {"wait": 500}, GEOMETRY, {"shot": str(shot)}], viewport=viewport)
    geometry = _geometry(result["reads"])
    assert geometry["hud"] is not None, "the interaction-mode HUD is part of the real page"
    assert geometry["overlap"] is False, geometry
    assert geometry["hudReachable"] is True, "the HUD is the topmost element at its own centre (reachable by a click)"
    band = geometry["band"]
    assert band["l"] >= 0 and band["r"] <= geometry["vw"] and band["t"] >= 0 and band["b"] <= geometry["vh"], geometry
    assert shot.stat().st_size > 1000
    _no_noise(result)

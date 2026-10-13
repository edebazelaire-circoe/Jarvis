"""Variants entrypoints of the whole video on the REAL Control Center page, in a REAL headless Chrome, against an isolated REAL Core
(handoff jarvis-remotion-master-project-studio-export, Slice 08; `docs/remotion-master-project.md` § 13).

Part 1 (always): real Core (own data root, own ports), the real prefab library, the real master planner and its live route, the real Remotion
Studio service with Core's `FakeStudioRunner` (no Node process), the real Control Center relay, real CDP input. Proved: on a master-ready
deck « Remotion Studio » opens ONE confirmation naming the whole video (keyboard: the focus stays in the dialog, `Échap` closes it and gives
the focus back, nothing launched), confirming makes Core record the master target (`state.json` schema 2 view: `target.kind`), the line says
the whole video; an incompatible deck keeps the scene door, says the § 3 sentence and refuses « Exporter la vidéo »; at 800x600, 1280x720 and
1920x1080 the changed controls are named, inside the window, without horizontal overflow or overlap; in the stage fullscreen they are hidden.
Slice 09 polish: with the Control Center's link to Core cut (a real `core_unreachable` from the relay) the line never says Remotion Studio is
open, and a whole-video export failed by a throwing scene says the scene, offers no « Réessayer » and wraps its small-print code at every size.

Part 2 (opt-in `JARVIS_REMOTION_RUNTIME_DIR`, Node, Chrome; one real process at a time): `RemotionStack` with the real `remotion studio`
(private copy of the runtime's `node_modules`) and the real render host. The page's « Remotion Studio » opens the REAL Studio on the master
(Remotion Studio's own page lists `JarvisPresentation`); then the page's « Exporter la vidéo » renders a verified whole-video MP4 for a small
3-scene deck (Artefact `render_scope: master`, 3 scenes).

With `JARVIS_VARIANTS_MASTER_EVIDENCE_DIR`: small screenshots (half scale) and `variants-master-summary.json`; the home path and the user
name are redacted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.domain.remotion_master_project import MasterReason
from jarvis.domain.remotion_master_sentences import REASON_SENTENCES
from tests.fakes.remotion_studio import FakeStudioRunner
from tests.unit.presentation_playback_gate_world import redact, run_long
from tests.unit.test_local_capability_host import FakeRunner
from tests.unit.test_presentation_studio_composition_clock_routes import FAST, SLOW, presentation, publish_scenes, remotion_scene
from tests.unit.test_presentation_studio_edit_routes import S1, S2
from tests.unit.test_presentation_studio_routes import AUTH, Core
from tests.unit.test_variants_controls_browser import INVENTORY
from tests.unit.test_variants_remotion_studio_browser import PREFAB_A, PREFAB_B, _deck, _free_port, _studio_page
from tests.unit.test_variants_run_browser import wire

X = "#jvStudioExplorer"
EXPLORER = "window.JarvisStudioExplorer"
DOOR = f"{X} [data-act=\"remotion_studio\"]"
SCENE_DOOR = f"{X} [data-act=\"remotion_studio_scene\"]"
EXPORT = f"{X} [data-act=\"video_export\"]"
CONFIRM = f"{X} [data-act=\"remotion_studio_confirm\"]"
DIALOG = f"document.querySelector('{X} [data-kind=\"remotion_studio\"]')"
MASTER_LINE = f"((document.querySelector('{X} .jvx-rms-master-text')||{{}}).textContent||'')"
RMS_TEXT = f"((document.querySelector('{X} .jvx-rms-text')||{{}}).textContent||'')"
VX_TEXT = f"((document.querySelector('{X} .jvx-vx-text')||{{}}).textContent||'')"
RMS_STATE = f"{EXPLORER}.remotionStudio.state()"
MASTER_READY = f"({RMS_STATE}.master||{{}}).state==='ready'"
SHOWN = "(s=>{const b=document.querySelector(s);return !!b&&!b.hidden&&b.offsetParent!==null})"
FULL = "({x:0,y:0,width:innerWidth,height:innerHeight})"
#: Boxes of the changed controls (door, export, « Présenter », the scene door, the lines) for the overlap check.
BOXES = (f"(()=>{{const r=s=>{{const e=document.querySelector(s);if(!e||e.hidden||e.offsetParent===null)return null;const b=e.getBoundingClientRect();"
         f"return [Math.round(b.left),Math.round(b.top),Math.round(b.right),Math.round(b.bottom)]}};"
         f"return {{door:r('{DOOR}'),export:r('{EXPORT}'),present:r('{X} [data-act=\"present\"]'),scene:r('{SCENE_DOOR}'),"
         f"line:r('{X} .jvx-rms'),vw:innerWidth,overflowX:document.documentElement.scrollWidth>innerWidth}}}})()")


def evidence() -> Path | None:
    raw = os.environ.get("JARVIS_VARIANTS_MASTER_EVIDENCE_DIR")
    if not raw:
        return None
    folder = Path(raw)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def shot(folder: Path, name: str) -> dict:
    """A half-scale screenshot of the whole page (small evidence), written `<name>-000.png` in `folder`."""

    return {"burst": str(folder), "ms": 1, "scale": 0.5, "clipExpr": FULL, "prefix": name, "as": f"shot_{name}"}


def keep_shots(raw: Path, folder: Path | None) -> list[str]:
    if folder is None:
        return []
    kept = []
    for path in sorted(raw.glob("*-000.png")):
        target = folder / path.name.replace("-000.png", ".png")
        shutil.copy2(path, target)
        kept.append(target.name)
    return kept


def open_plan(pid: str) -> list[dict]:
    return [{"until": f"!!{EXPLORER}", "ms": 20000, "required": True, "as": "explorer"},
            {"eval": f"{EXPLORER}.open({{presentation_id:'{pid}',fullscreen:false}})"},
            {"until": f"{EXPLORER}.state().open && {EXPLORER}.state().preview.status==='ready'", "ms": 30000, "required": True, "as": "preview"}]


#: The scene door against the primary door: computed weight, decoration and WCAG contrast of each text on the opaque colour behind it.
STYLES = ("(()=>{const rgb=c=>(c.match(/[\\d.]+/g)||[]).map(Number);"
          "const lum=([r,g,b])=>{const f=v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)};return .2126*f(r)+.7152*f(g)+.0722*f(b)};"
          "const bg=e=>{for(let n=e;n;n=n.parentElement){const c=rgb(getComputedStyle(n).backgroundColor);if(c.length>=3&&(c.length<4||c[3]>.5))return c}"
          "return [4,8,12]};"
          "const ratio=(a,b)=>{const x=lum(a),y=lum(b);return Math.round((Math.max(x,y)+.05)/(Math.min(x,y)+.05)*100)/100};"
          f"const one=s=>{{const e=document.querySelector(s),cs=getComputedStyle(e);return {{weight:cs.fontWeight,decoration:cs.textDecorationLine,"
          f"color:cs.color,border:cs.borderTopColor,contrast:ratio(rgb(cs.color),bg(e))}}}};"
          f"return {{scene:one('{SCENE_DOOR}'),door:one('{DOOR}')}}}})()")
#: The open dialog's geometry: the action row and the focused button inside the window, the body scrolling when it must.
DIALOG_BOX = (f"(()=>{{const d={DIALOG},b=d.querySelector('.jvx-confirm-body'),a=d.querySelector('.jvx-dialog-actions'),"
              "f=document.activeElement,r=e=>{const x=e.getBoundingClientRect();return [Math.round(x.left),Math.round(x.top),Math.round(x.right),Math.round(x.bottom)]};"
              "return {vh:innerHeight,vw:innerWidth,box:r(d),actions:r(a),focus:r(f),focusText:f.textContent,focusInActions:a.contains(f),"
              "scrolls:b.scrollHeight>b.clientHeight+1,bodyScroll:[b.scrollHeight,b.clientHeight],boxScroll:[d.scrollHeight,d.clientHeight]}})()")


def _head() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()


def overlaps(a: list[int] | None, b: list[int] | None) -> bool:
    return bool(a and b) and a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


@pytest.fixture
async def stack(tmp_path):
    """An isolated Core with Remotion Studio (fake process), its capability ready; a 2-scene master-ready deck and an incompatible one."""

    port = _free_port()
    runner, capability = FakeStudioRunner(port=port), FakeRunner()
    page = await _studio_page(port)
    async with Core(tmp_path, local_capability_runner=capability, remotion_studio_runner=runner,
                    local_capability_store=FileLocalCapabilityStore((tmp_path / "data").resolve())) as core:
        assert (await core.client.local_capability_action("remotion", "install"))["capability"]["status"] == "ready"
        url = await wire(core, tmp_path)
        ready = await _deck(core)
        await publish_scenes(core)
        # the same two prefab ids as `_deck` (FAST is PREFAB_A, SLOW is PREFAB_B): `publish_scenes` adds their version 2, SLOW at 24 fps
        broken, _ = await presentation(core, [remotion_scene(S1, FAST, 2), remotion_scene(S2, SLOW, 2)])
        yield core, url, ready, broken, runner
        await core.stack.center.scene_view.aclose()
    await page.cleanup()


async def test_the_whole_video_door_confirms_by_keyboard_and_records_the_master_target(stack, tmp_path):
    core, url, pid, _broken, runner = stack
    raw = tmp_path / "shots"
    raw.mkdir()
    result = await run_long(url, open_plan(pid) + [
        {"until": MASTER_READY, "ms": 15000, "required": True, "as": "master_read"}, {"wait": 300},
        {"value": "line", "expr": MASTER_LINE}, {"value": "door", "expr": f"document.querySelector('{DOOR}').getAttribute('aria-label')"},
        {"value": "sceneShown", "expr": f"{SHOWN}('{SCENE_DOOR}')"}, {"value": "exportShown", "expr": f"{SHOWN}('{EXPORT}')"},
        {"value": "styles", "expr": STYLES}, {"value": "live", "expr": f"document.querySelector('{X} .jvx-rms-master-text').getAttribute('aria-live')"},
        shot(raw, "variants-master-ready-1280x720"),
        {"click": DOOR}, {"until": f"!!{DIALOG}", "ms": 8000, "required": True, "as": "dialog"}, {"wait": 200},
        {"value": "dialog", "expr": f"{DIALOG}.innerText"}, {"value": "target", "expr": f"{DIALOG}.getAttribute('data-target')"},
        {"value": "focus0", "expr": "document.activeElement&&document.activeElement.textContent"},
        shot(raw, "variants-master-confirm-1280x720"),
        {"key": "Tab"}, {"key": "Tab"}, {"key": "Tab"},
        {"value": "trapped", "expr": f"{DIALOG}.contains(document.activeElement)"},
        {"key": "Escape"}, {"wait": 300},
        {"value": "closed", "expr": f"!{DIALOG}"}, {"value": "focusBack", "expr": f"document.activeElement===document.querySelector('{DOOR}')"},
        {"click": DOOR}, {"until": f"!!{DIALOG}", "ms": 8000}, {"click": CONFIRM},
        {"until": f"{RMS_STATE}.studio && {RMS_STATE}.studio.status==='ready' && !{RMS_STATE}.busy", "ms": 20000, "as": "opened"},
        {"wait": 400}, {"value": "status", "expr": RMS_TEXT},
        {"value": "button", "expr": f"[document.querySelector('{DOOR}').dataset.state,document.querySelector('{DOOR}').getAttribute('aria-label')]"},
        {"value": "target_view", "expr": f"JSON.stringify({RMS_STATE}.studio.target)"},
        shot(raw, "variants-master-open-1280x720")])
    reads = result["reads"]
    assert not reads.get("failed"), reads.get("failed")
    assert reads["line"] == "Vidéo entière : « Horloge », variante 1, 2 scènes (6 s)." and reads["door"] == "Remotion Studio, vidéo entière"
    assert reads["sceneShown"] is True and reads["exportShown"] is True
    st = reads["styles"]
    assert st["scene"]["weight"] == "400" and st["scene"]["decoration"] == "none", "the secondary door is quiet at rest"
    assert 4.5 <= st["scene"]["contrast"] <= st["door"]["contrast"], ("never brighter than the primary's text", st)
    assert st["scene"]["border"] == "rgba(0, 0, 0, 0)" and st["door"]["border"] != "rgba(0, 0, 0, 0)", "the primary keeps its button chrome"
    assert reads["live"] == "polite"
    assert reads["target"] == "master" and "2 scènes vont tourner hors du bac à sable, dans Remotion Studio" in reads["dialog"]
    assert "un agent" not in reads["dialog"] and "Attention" in reads["dialog"], "one scene was written by the brain: the reinforced warning"
    assert reads["focus0"] == "Annuler" and reads["trapped"] is True, "the focus starts on « Annuler » (danger) and stays in the dialog"
    assert reads["closed"] is True and reads["focusBack"] is True
    assert reads["opened"] is True and "ouvert sur la vidéo entière (2 scènes)" in reads["status"]
    assert reads["button"] == ["here", "Remotion Studio, ouvert sur la vidéo entière"]
    target = json.loads(reads["target_view"])
    assert target["kind"] == "variant_master" and target["presentation_id"] == pid and target["scene_count"] == 2
    assert len(runner.launches) == 1, "Core really started the (fake) process once, after the confirmation"
    async with core.http.get(core.stack.core_url + "/v1/local-capabilities/remotion/studio", headers=AUTH) as response:
        view = (await response.json())["studio"]
    assert view["pin"] is None and view["target"]["kind"] == "variant_master"
    shots = keep_shots(raw, evidence())
    if evidence():
        (evidence() / "variants-master-door-summary.json").write_text(redact(json.dumps(
            {"tested_head": _head(), "line": reads["line"], "dialog": reads["dialog"], "status": reads["status"], "target": target,
             "scene_door_style": st, "screenshots": shots},
            indent=1, ensure_ascii=False)), encoding="utf-8")


async def test_an_incompatible_deck_keeps_the_scene_door_says_the_sentence_and_refuses_the_export(stack):
    core, url, _pid, broken, runner = stack
    result = await run_long(url, open_plan(broken) + [
        {"until": f"({RMS_STATE}.master||{{}}).state==='incompatible'", "ms": 15000, "required": True, "as": "master_read"}, {"wait": 300},
        {"value": "line", "expr": MASTER_LINE}, {"value": "sceneShown", "expr": f"{SHOWN}('{SCENE_DOOR}')"},
        {"value": "target", "expr": f"document.querySelector('{DOOR}').dataset.target"},
        {"value": "export", "expr": f"[document.querySelector('{EXPORT}').getAttribute('aria-disabled'),document.querySelector('{EXPORT}').title]"},
        {"click": EXPORT}, {"wait": 300}, {"value": "exportLine", "expr": VX_TEXT},
        {"click": DOOR}, {"until": f"!!{DIALOG}", "ms": 8000}, {"value": "dialog", "expr": f"{DIALOG}.innerText"},
        {"value": "dialogTarget", "expr": f"{DIALOG}.getAttribute('data-target')"}])
    reads = result["reads"]
    sentence = REASON_SENTENCES[MasterReason.FPS_MISMATCH]
    assert reads["line"] == sentence + " « Remotion Studio » ouvre donc la scène à l’écran."
    assert reads["sceneShown"] is False and reads["target"] == "scene"
    assert reads["export"][0] == "true" and sentence in reads["export"][1] and sentence in reads["exportLine"]
    assert reads["dialogTarget"] is None and "Scène 1 sur 2" in reads["dialog"], "the scene door, as before"
    assert not runner.launches


@pytest.mark.parametrize("viewport", ["800x600", "1280x720"])
async def test_a_twelve_scene_confirmation_keeps_its_action_row_in_view_and_scrolls_its_body(stack, viewport, tmp_path):
    """QA Slice 08 polish: 12 scenes at 800x600 pushed the actions out of the dialog and half hid the focused « Annuler »."""

    core, url, _pid, _broken, _runner = stack
    # eleven scenes written by the user and one by the brain: the reinforced warning (the longest dialog), the focus on « Annuler »
    scenes = [remotion_scene(f"pss_{n + 1:012d}", PREFAB_B if n == 11 else PREFAB_A) for n in range(12)]
    pid, _vid = await presentation(core, scenes)
    raw = tmp_path / "shots"
    raw.mkdir()
    result = await run_long(url, open_plan(pid) + [
        {"until": MASTER_READY, "ms": 20000, "required": True, "as": "master_read"}, {"wait": 300},
        {"click": DOOR}, {"until": f"!!{DIALOG}", "ms": 8000, "required": True, "as": "dialog"}, {"wait": 300},
        {"value": "geo", "expr": DIALOG_BOX}, {"value": "text", "expr": f"{DIALOG}.innerText"},
        shot(raw, f"variants-master-confirm12-{viewport}"),
        {"key": "Tab"}, {"wait": 100}, {"value": "geo2", "expr": DIALOG_BOX},
        {"key": "Escape"}, {"wait": 300}, {"value": "closed", "expr": f"!{DIALOG}"}], viewport=viewport)
    reads = result["reads"]
    assert not reads.get("failed"), reads.get("failed")
    assert "12 scènes vont tourner hors du bac à sable" in reads["text"]
    for geo in (reads["geo"], reads["geo2"]):
        vh, box, actions, focus = geo["vh"], geo["box"], geo["actions"], geo["focus"]
        assert 0 <= box[1] and box[3] <= vh, ("the dialog fits the window", geo)
        assert box[1] <= actions[1] and actions[3] <= box[3] and actions[3] <= vh, ("the action row is inside the dialog and the window", geo)
        assert geo["focusInActions"] and box[1] <= focus[1] and focus[3] <= box[3] and focus[3] <= vh, ("the focused button is fully visible", geo)
        assert geo["boxScroll"][0] <= geo["boxScroll"][1] + 1, ("the dialog itself never scrolls: its body does", geo)
    assert reads["geo"]["focusText"] == "Annuler"
    if viewport == "800x600":
        assert reads["geo"]["scrolls"] is True, "at 800x600 the twelve versions scroll inside the body"
    assert reads["closed"] is True
    keep_shots(raw, evidence())


@pytest.mark.parametrize("viewport", ["800x600", "1280x720", "1920x1080"])
async def test_the_changed_controls_fit_every_viewport_and_hide_in_the_stage_fullscreen(stack, viewport, tmp_path):
    core, url, pid, _broken, _runner = stack
    raw = tmp_path / "shots"
    raw.mkdir()
    result = await run_long(url, open_plan(pid) + [
        {"until": MASTER_READY, "ms": 15000, "required": True, "as": "master_read"}, {"wait": 400},
        {"value": "inv", "expr": INVENTORY}, {"value": "boxes", "expr": BOXES}, shot(raw, f"variants-master-{viewport}"),
        {"click": f"{X} .jvx-top-actions .jvx-btn"},
        {"until": f"document.fullscreenElement===document.querySelector('{X} .jvx-theater')", "ms": 5000, "as": "fullscreen"}, {"wait": 400},
        {"value": "inFullscreen", "expr": f"[{SHOWN}('{DOOR}'),{SHOWN}('{EXPORT}'),{SHOWN}('{X} .jvx-rms'),{SHOWN}('{X} .jvx-vx')]"},
        shot(raw, f"variants-master-fullscreen-{viewport}")], viewport=viewport)
    reads = result["reads"]
    assert not reads.get("failed"), reads.get("failed")
    inv, boxes = reads["inv"], reads["boxes"]
    named = {c["act"]: c for c in inv["controls"] if c["act"] in ("remotion_studio", "video_export", "present", "remotion_studio_scene")}
    assert set(named) == {"remotion_studio", "video_export", "present", "remotion_studio_scene"}, named
    assert named["remotion_studio"]["name"] == "Remotion Studio, vidéo entière" and named["video_export"]["name"] == "Exporter la vidéo"
    assert named["remotion_studio_scene"]["name"] == "Cette scène seule dans Remotion Studio"
    for act, control in named.items():
        assert 0 <= control["box"][0] and control["box"][2] <= inv["vw"], (act, control["box"], inv["vw"])
    assert inv["overflowX"] is False and boxes["overflowX"] is False
    keys = ("door", "export", "present", "scene")
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            assert not overlaps(boxes[a], boxes[b]), (viewport, a, b, boxes)
    assert reads["fullscreen"] is True and reads["inFullscreen"] == [False, False, False, False], "nothing of this Slice over the slide"
    keep_shots(raw, evidence())


class _ScriptedRelay:
    """The Control Center's transport to Core, scripted (Slice 09 polish): `down` -> the relay answers a real `core_unreachable` (503);
    `failed_job` -> a whole-video export request answers a job that a throwing scene failed (Core's own shape and wording)."""

    def __init__(self, real, *, down: bool = False, failed_job: dict | None = None) -> None:
        self.real, self.down, self.failed_job = real, down, failed_job

    async def forward(self, method, core_path, *, body=None, timeout_s):
        if self.down:
            raise ConnectionRefusedError("Core stopped")
        if self.failed_job and method == "POST" and core_path.endswith("/jobs"):
            return 202, {"job": self.failed_job}
        return await self.real.forward(method, core_path, body=body, timeout_s=timeout_s)


#: The export line's small print against its panel and the window (R3: it was cut at the panel's right edge at 1280x720).
CODE_BOX = (f"(()=>{{const c=document.querySelector('{X} .jvx-vx-code'),p=document.querySelector('{X} .jvx-vx');"
            "const r=e=>{const x=e.getBoundingClientRect();return [Math.round(x.left),Math.round(x.top),Math.round(x.right),Math.round(x.bottom)]};"
            "const lh=parseFloat(getComputedStyle(c).lineHeight)||14;"
            "return {code:r(c),panel:r(p),lines:Math.round(c.getBoundingClientRect().height/lh),cut:c.scrollWidth>c.clientWidth+1,"
            "shown:!c.hidden&&c.offsetParent!==null,vw:innerWidth,overflowX:document.documentElement.scrollWidth>innerWidth}})()")


@pytest.mark.parametrize("viewport", ["800x600", "1280x720", "1920x1080"])
async def test_a_core_outage_never_says_studio_open_and_a_throwing_scene_export_wraps_its_code(stack, viewport, tmp_path):
    """Slice 09 polish (R1, R3) on the real page: Remotion Studio really open on the whole video, then the relay loses Core."""

    core, url, pid, _broken, runner = stack
    opened = await run_long(url, open_plan(pid) + [
        {"until": MASTER_READY, "ms": 15000, "required": True, "as": "master_read"}, {"wait": 300},
        {"click": DOOR}, {"until": f"!!{DIALOG}", "ms": 8000, "required": True, "as": "dialog"}, {"click": CONFIRM},
        {"until": f"{RMS_STATE}.studio && {RMS_STATE}.studio.status==='ready' && !{RMS_STATE}.busy", "ms": 20000, "required": True, "as": "opened"},
        {"wait": 300}, {"value": "status", "expr": RMS_TEXT}], viewport=viewport)
    assert not opened["reads"].get("failed"), opened["reads"].get("failed")
    assert "ouvert sur la vidéo entière" in opened["reads"]["status"]
    center = core.stack.center
    detail = ("scene 2 (pss_0000000000c2) failed while rendering: Error: jarvis_master_scene_failed:pss_0000000000c2:2: "
              "ReferenceError_boom_in_the_second_scene_at_frame_5_without_any_space_to_break_this_very_long_line_on")
    failed = {"job_id": "rj_0123456789ab", "artifact_id": "jart_" + "e" * 32, "state": "failed", "phase": "failed", "format": "mp4",
              "frames_done": 40, "frames_total": 180, "percent": 22, "elapsed_s": 3, "timeout_s": 435, "can_cancel": False,
              "error_code": "presentation_render_master_scene_failed", "error_detail": detail, "scope": "master", "scene_count": 2}
    studio_relay, render_relay = center.remotion_studio_routes, center.presentation_render_routes
    studio_relay._transport = lambda: _ScriptedRelay(center.sessions, down=True)
    render_relay._transport = lambda: _ScriptedRelay(center.sessions, failed_job=failed)
    raw = tmp_path / "shots"
    raw.mkdir()
    try:
        result = await run_long(url, open_plan(pid) + [
            {"until": MASTER_READY, "ms": 15000, "required": True, "as": "master_read"},
            {"until": f"{RMS_TEXT}.includes('plus confirmé')", "ms": 15000, "required": True, "as": "unconfirmed"}, {"wait": 300},
            {"value": "status", "expr": RMS_TEXT}, {"value": "readError", "expr": f"({RMS_STATE}.readError||{{}}).code"},
            {"value": "door", "expr": f"(b=>[b.dataset.state,b.getAttribute('aria-disabled'),b.getAttribute('aria-label')])(document.querySelector('{DOOR}'))"},
            {"value": "link", "expr": f"{SHOWN}('{X} .jvx-rms-link')"},
            {"click": DOOR}, {"wait": 600}, {"value": "dialogAfterClick", "expr": f"!!{DIALOG}"},
            {"click": EXPORT}, {"until": f"{SHOWN}('{X} .jvx-vx-code')", "ms": 10000, "required": True, "as": "exportFailed"}, {"wait": 300},
            {"value": "exportText", "expr": VX_TEXT}, {"value": "retry", "expr": f"{SHOWN}('{X} [data-act=\"video_export_retry\"]')"},
            {"value": "codeBox", "expr": CODE_BOX}, {"value": "boxes", "expr": BOXES},
            shot(raw, f"variants-outage-scene-failed-{viewport}")], viewport=viewport)
    finally:
        studio_relay._transport = render_relay._transport = lambda: center.sessions
    reads = result["reads"]
    assert not reads.get("failed"), reads.get("failed")
    assert reads["status"] == "Core injoignable : l’état de Remotion Studio n’est plus confirmé." and "ouvert" not in reads["status"]
    assert reads["readError"] == "core_unreachable", "the relay's real answer, not a page-side stub"
    assert reads["door"] == ["idle", "true", "Remotion Studio, vidéo entière"] and reads["link"] is False
    assert reads["dialogAfterClick"] is False and len(runner.launches) == 1, "a click while Core is unreachable opens nothing"
    assert reads["exportText"] == ("Export de la vidéo entière échoué : la scène 2 a échoué pendant le rendu, aucun fichier n’a été gardé. "
                                   "Corrigez la scène 2, puis exportez de nouveau.")
    assert reads["retry"] is False, "a scene that throws throws again: no « Réessayer »"
    box = reads["codeBox"]
    assert box["shown"] and not box["cut"], ("the long code wraps instead of running out", box)
    if viewport != "1920x1080":
        assert box["lines"] >= 2, ("at this width the code needs more than one line: it wraps", box)
    assert box["panel"][0] <= box["code"][0] and box["code"][2] <= box["panel"][2] + 1 and box["code"][2] <= box["vw"], box
    assert box["overflowX"] is False and reads["boxes"]["overflowX"] is False
    keep_shots(raw, evidence())


# ---------------------------------------------------------------------------------------------------------------- Part 2: real Studio, real render

RUNTIME = os.environ.get("JARVIS_REMOTION_RUNTIME_DIR", "")


@pytest.mark.skipif(not RUNTIME or shutil.which("node") is None or not (Path(RUNTIME or ".") / "node_modules" / "@remotion").is_dir(),
                    reason="needs JARVIS_REMOTION_RUNTIME_DIR (an installed Remotion runtime), node and Chrome")
async def test_real_remotion_studio_opens_the_whole_video_and_the_export_renders_one_verified_mp4(tmp_path):
    from jarvis.adapters.remotion_render_runner import RemotionRenderRunner
    from jarvis.adapters.remotion_studio_runner import RemotionStudioRunner
    from jarvis.adapters.remotion_compiler import shipped_engine_pin
    from jarvis.domain.remotion_source import Composition
    from tests.fakes.remotion_player_stack import RemotionStack
    from tests.fakes.remotion_scene import scene_candidate
    from tests.unit.presentation_playback_gate_world import BASE, PROPS, SCENE_TSX, harness
    from tests.unit.test_remotion_studio_roundtrip_real_browser import private_runtime_copy

    folder = evidence()
    raw = tmp_path / "shots"
    raw.mkdir()
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    report: dict = {"slice": "08-variants-master-entrypoints", "tested_head": head, "durations_ms": {},
                    "runtime": "RemotionStack (real Core, real remotion studio and render host) on free loopback ports, throw-away data root, "
                               "private copy of the gate runtime's node_modules, headless Chrome over CDP; the live Jarvis was never contacted"}
    started = time.monotonic()
    private_runtime_copy(tmp_path)
    report["durations_ms"]["private_runtime_copy"] = round((time.monotonic() - started) * 1000)

    def options(stack) -> dict:
        runtime = lambda: stack.data_root / "local_capabilities" / "remotion" / "runtime"  # noqa: E731 - the runners take a root factory
        return {"remotion_studio_runner": RemotionStudioRunner(runtime), "remotion_render_runner": RemotionRenderRunner(runtime)}

    prefabs = [f"presentation-studio.p0000000000c8.s{n:012d}" for n in range(1, 4)]
    async with RemotionStack(tmp_path, runtime_dir=Path(RUNTIME), core_options=options) as stack:
        for n, prefab_id in enumerate(prefabs):
            await stack.core.prefabs.save(scene_candidate(
                prefab_id, engine=shipped_engine_pin(), title=f"V{n + 1}", composition=Composition("Scene", 640, 360, 30, 20 + 10 * n),
                files={"src/Scene.tsx": SCENE_TSX}, props=PROPS, sample={"props": {"title": f"V{n + 1}", "bg": "#203060"}, "data": {}}),
                actor="user")
        _, created = await stack.call("POST", BASE, json={"title": "Vidéo S08"})
        pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
        scenes = [{"scene_id": f"pss_c{n:011d}", "prefab": {"id": prefabs[n], "version": 1}, "title": f"SCENE-{n + 1}",
                   "props": {"title": f"SCENE-{n + 1}", "bg": ["#a02020", "#20a020", "#2030c0"][n]}, "data": {}} for n in range(3)]
        status, saved = await stack.call("PUT", f"{BASE}/{pid}/variants/{variant['variant_id']}", json={
            "expected_revision": variant["revision"], "title": variant["title"], "scenes": scenes,
            "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"]})
        harness(status == 200, f"variant save refused: {saved}")
        url = stack.page_url
        # 1. the page's « Remotion Studio »: the real remotion studio on the whole video
        started = time.monotonic()
        result = await run_long(url, open_plan(pid) + [
            {"until": MASTER_READY, "ms": 30000, "required": True, "as": "master_read"},
            {"click": DOOR}, {"until": f"!!{DIALOG}", "ms": 15000, "required": True, "as": "dialog"},
            {"value": "dialog", "expr": f"{DIALOG}.innerText"}, {"click": CONFIRM},
            {"until": f"{RMS_STATE}.studio && {RMS_STATE}.studio.status==='ready' && !{RMS_STATE}.busy", "ms": 200000, "as": "studio_ready"},
            {"value": "status", "expr": RMS_TEXT}, {"value": "studio", "expr": f"JSON.stringify({RMS_STATE}.studio)"},
            shot(raw, "real-studio-open-in-variants")], timeout=400)
        report["durations_ms"]["studio_open_from_page"] = round((time.monotonic() - started) * 1000)
        reads = result["reads"]
        harness(not reads.get("failed") and reads.get("studio_ready"), f"Remotion Studio did not open the master: {reads}")
        studio = json.loads(reads["studio"])
        assert studio["target"]["kind"] == "variant_master" and studio["target"]["scene_count"] == 3
        assert "3 scènes vont tourner hors du bac à sable" in reads["dialog"]
        # a cold start outlives the click's permission to open a tab: the line then offers the link (« prêt … après un clic »)
        assert ("ouvert sur la vidéo entière (3 scènes)" in reads["status"] or "Remotion Studio est prêt sur la vidéo entière" in reads["status"]), reads["status"]
        page = await run_long(studio["url"] + "JarvisPresentation", [
            {"until": "document.body.innerText.includes('JarvisPresentation')", "ms": 150000, "as": "composition_listed"}, {"wait": 1500},
            shot(raw, "real-studio-master-page")], timeout=300)
        assert page["reads"].get("composition_listed") is True, "Remotion Studio's own page shows the master composition"
        report["studio"] = {"target": studio["target"], "status_line": reads["status"]}
        status, _closed = await stack.call("POST", "/v1/local-capabilities/remotion/studio/close", json={})
        harness(status == 200, "Remotion Studio did not close")
        # 2. the page's « Exporter la vidéo »: one whole-video MP4
        started = time.monotonic()
        result = await run_long(url, open_plan(pid) + [
            {"until": MASTER_READY, "ms": 30000, "required": True, "as": "master_read"},
            {"click": EXPORT}, {"until": f"{VX_TEXT}.includes('Rendu des images')||{VX_TEXT}.includes('exportée')", "ms": 120000, "as": "running"},
            {"value": "running_text", "expr": VX_TEXT}, shot(raw, "real-export-running"),
            {"until": f"{VX_TEXT}.startsWith('Vidéo entière exportée')||{VX_TEXT}.includes('échoué')", "ms": 400000, "as": "done"},
            {"value": "done_text", "expr": VX_TEXT}, {"value": "link", "expr": f"document.querySelector('{X} .jvx-vx-link').getAttribute('href')"},
            {"value": "job", "expr": f"JSON.stringify({EXPLORER}.videoExport.state().job)"}, shot(raw, "real-export-done")], timeout=600)
        report["durations_ms"]["export_from_page"] = round((time.monotonic() - started) * 1000)
        reads = result["reads"]
        harness(reads.get("done") and reads["done_text"].startswith("Vidéo entière exportée"), f"export did not finish: {reads}")
        job = json.loads(reads["job"])
        artifact = await stack.core.artifacts.get(job["artifact_id"])
        meta = dict(artifact.metadata)
        assert meta["render_scope"] == "master" and meta["render_scene_count"] == 3 and artifact.kind.value == "presentation_video"
        assert meta["render_composition"] == "JarvisPresentation" and (artifact.width, artifact.height) == (640, 360)
        assert reads["link"] == f"/api/artifacts/{job['artifact_id']}/payload"
        report["export"] = {"running": reads["running_text"], "done": reads["done_text"], "frames": job.get("frames_total"),
                            "size_bytes": job.get("size_bytes"), "render_scope": meta["render_scope"], "scenes": meta["render_scene_count"],
                            "verified_by": meta.get("render_verified_by")}
    report["screenshots"] = keep_shots(raw, folder)
    if folder:
        (folder / "variants-master-summary.json").write_text(redact(json.dumps(report, indent=1, ensure_ascii=False, default=str)), encoding="utf-8")

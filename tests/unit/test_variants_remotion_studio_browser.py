"""« Remotion Studio » in Variants on the REAL Control Center page, in a REAL headless Chrome, against an isolated REAL Core
(jarvis-remotion-native-studio-playback-fix, Slice 11: first-class Remotion Studio and Variants choices).

Real: Core behind the real protocol server (own data root, own ports), the real prefab library with published Remotion scene versions,
a presentation whose scenes pin them, the real Remotion Studio service and routes of Core, the real Control Center relay, real CDP clicks
(the confirmation click is a real user activation, which the tab opening needs). Simulated: the `remotion studio` PROCESS only — Core's
`FakeStudioRunner` (no Node, no webpack) — and the page it serves, a tiny local page standing for Remotion Studio's tab. The live
Jarvis and the user's own Remotion Studio are never contacted.

Proved (contract `docs/presentation-studio.md` › *Remotion Studio from Variants (Level 3, Slice 11)*, § 6 #22, PX-1, PX-2):

- the « Remotion Studio » button sits on the scene row beside « Présenter », named, inside the window, without overflow at 800x600,
  1280x720 and 1920x1080;
- a click opens ONE confirmation in Variants (risk, exact version, provenance); confirming sends Core's `open` with the scene's exact pin,
  a NEW TAB opens on Remotion Studio's address, and Variants keeps its variant, its scene and its tree; coming back re-reads Remotion
  Studio and says « ouvert sur cette scène »;
- a Core without Remotion Studio, and a start that fails, are said in Variants with the reason and the code; « Réessayer » recovers;
- the rail's « Remotion Studio… » opens Variants and this same confirmation.

With `JARVIS_VARIANTS_REMOTION_EVIDENCE_DIR` (and the tag `JARVIS_VARIANTS_REMOTION_SHOT_TAG`, the SHA), `test_evidence_…` writes the
screenshots of the Slice (home path never written).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket

from aiohttp import web
import pytest

from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.domain.remotion_studio import StudioError, StudioErrorCode
from tests.fakes.remotion_scene import scene_candidate
from tests.fakes.remotion_studio import FakeStudioRunner
from tests.unit.test_local_capability_host import FakeRunner
from tests.unit.test_presentation_studio_composition_clock_routes import presentation, remotion_scene
from tests.unit.test_presentation_studio_edit_routes import S1, S2
from tests.unit.test_presentation_studio_routes import AUTH, Core
from tests.unit.test_variants_controls_browser import INVENTORY, _ok, _open_variants
from tests.unit.test_variants_run_browser import drive, wire

X = "#jvStudioExplorer"
EXPLORER = "window.JarvisStudioExplorer"
DOOR = f"{X} [data-act=\"remotion_studio\"]"
CONFIRM = f"{X} [data-act=\"remotion_studio_confirm\"]"
DIALOG = f"document.querySelector('{X} [data-kind=\"remotion_studio\"]')"
RMS_TEXT = f"(document.querySelector('{X} .jvx-rms-text')||{{}}).textContent||''"
RMS_STATE = f"{EXPLORER}.remotionStudio.state()"
PREFAB_A = "presentation-studio.p000000000001.s000000000001"
PREFAB_B = "presentation-studio.p000000000001.s000000000002"
STUDIO_PAGE = "<!doctype html><title>Remotion Studio (test double)</title><p>Remotion Studio</p>"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _studio_page(port: int) -> web.AppRunner:
    """The page the fake Remotion Studio process « serves »: what the new tab shows."""

    async def index(_request: web.Request) -> web.Response:
        return web.Response(text=STUDIO_PAGE, content_type="text/html")

    app = web.Application()
    app.router.add_get("/", index)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    return runner


async def _deck(core) -> str:
    prefabs = core.stack.core.prefabs
    await prefabs.save(scene_candidate(PREFAB_A), actor="user")
    await prefabs.save(scene_candidate(PREFAB_B), actor="brain")
    pid, _vid = await presentation(core, [remotion_scene(S1, PREFAB_A), remotion_scene(S2, PREFAB_B)])
    return pid


@pytest.fixture
async def studio_deck(tmp_path):
    """An isolated Core with Remotion Studio (fake process), its capability ready, a 2-scene Remotion presentation; yields
    `(core, url, pid, runner, studio_url)`."""

    port = _free_port()
    runner, capability = FakeStudioRunner(port=port), FakeRunner()
    page = await _studio_page(port)
    async with Core(tmp_path, local_capability_runner=capability, remotion_studio_runner=runner,
                    local_capability_store=FileLocalCapabilityStore((tmp_path / "data").resolve())) as core:
        assert (await core.client.local_capability_action("remotion", "install"))["capability"]["status"] == "ready"
        url = await wire(core, tmp_path)
        pid = await _deck(core)
        yield core, url, pid, runner, f"http://127.0.0.1:{port}/"
        await core.stack.center.scene_view.aclose()
    await page.cleanup()


async def _close_studio(core) -> None:
    async with core.http.post(core.stack.core_url + "/v1/local-capabilities/remotion/studio/close", json={}, headers=AUTH) as response:
        assert response.status == 200, await response.text()


def _confirm_plan(scene_index: int) -> list[dict]:
    return [{"click": f"{X} .jvx-strip [role=\"option\"]:nth-child({scene_index})"}, {"wait": 300},
            {"click": DOOR}, {"until": f"!!{DIALOG}", "ms": 8000},
            {"value": "dialog", "expr": f"{DIALOG}.innerText"},
            {"value": "beforeState", "expr": f"JSON.stringify({EXPLORER}.state())"},
            {"click": CONFIRM},
            {"until": f"{RMS_STATE}.studio && {RMS_STATE}.studio.status==='ready' && !{RMS_STATE}.busy", "ms": 15000}]


async def test_confirmed_open_starts_remotion_studio_on_the_exact_pin_in_a_new_tab_and_variants_keeps_everything(studio_deck, tmp_path):
    core, url, pid, runner, studio_url = studio_deck
    result = await drive(url, _open_variants(pid) + _confirm_plan(2) + [
        {"wait": 800}, {"targets": "tabs"},
        {"value": "afterState", "expr": f"JSON.stringify({EXPLORER}.state())"},
        {"value": "status", "expr": RMS_TEXT},
        {"value": "button", "expr": f"[document.querySelector('{DOOR}').dataset.state,document.querySelector('{DOOR}').getAttribute('aria-label')]"},
        {"eval": "window.dispatchEvent(new Event('focus'))"}, {"wait": 600},
        {"value": "back", "expr": RMS_TEXT},
        {"value": "frames", "expr": f"[...document.querySelectorAll('{X} iframe')].filter(f=>String(f.src).includes('{studio_url}')).length"}])
    reads = _ok(result)
    assert "Scène 2 sur 2" in reads["dialog"] and "Sans bac à sable" in reads["dialog"], reads["dialog"]
    assert "un agent de Jarvis" in reads["dialog"], "the provenance of THAT version (written by the brain) is read and shown"
    assert studio_url in reads["tabs"], ("a new tab on Remotion Studio's address", reads["tabs"])
    assert runner.launches and "launch" in runner.calls, "Core really started the (fake) process"
    b, a = json.loads(reads["beforeState"]), json.loads(reads["afterState"])
    assert (a["open"], a["selected"], a["active"], a["preview"]["scene"]) == (True, b["selected"], b["active"], b["preview"]["scene"])
    assert a["preview"]["scene"] == S2, "Variants is still on the scene that was opened"
    assert "ouvert sur cette scène" in reads["status"] and reads["button"] == ["here", "Remotion Studio, ouvert sur cette scène"]
    assert "ouvert sur cette scène" in reads["back"], "coming back re-reads Remotion Studio"
    assert reads["frames"] == 0, "Remotion Studio is never drawn inside Variants"
    state = runner.state or {}
    assert (state.get("pin") or {}).get("prefab_id") == PREFAB_B and int((state.get("pin") or {}).get("version")) == 1, state


async def test_a_core_without_remotion_studio_is_said_in_variants_and_nothing_opens(tmp_path):
    async with Core(tmp_path) as core:
        url = await wire(core, tmp_path)
        pid = await _deck(core)
        result = await drive(url, _open_variants(pid) + [{"wait": 600}, {"click": DOOR}, {"wait": 400},
                                                         {"value": "status", "expr": RMS_TEXT}, {"value": "dialog", "expr": f"!!{DIALOG}"},
                                                         {"value": "disabled", "expr": f"document.querySelector('{DOOR}').getAttribute('aria-disabled')"},
                                                         {"targets": "tabs"}])
        await core.stack.center.scene_view.aclose()
    reads = _ok(result)
    assert "pas de Remotion Studio" in reads["status"] and reads["dialog"] is False and reads["disabled"] == "true"
    assert len(reads["tabs"]) == 1, "no tab opened"


async def test_a_failed_start_is_said_with_its_code_and_retry_recovers(studio_deck):
    core, url, pid, runner, studio_url = studio_deck
    runner.launch_errors = [StudioError(StudioErrorCode.START_TIMEOUT, "no answer within 120 s")]
    result = await drive(url, _open_variants(pid) + [
        {"click": DOOR}, {"until": f"!!{DIALOG}", "ms": 8000}, {"click": CONFIRM},
        {"until": f"{RMS_STATE}.studio && {RMS_STATE}.studio.status==='failed' && !{RMS_STATE}.busy", "ms": 15000},
        {"value": "failedText", "expr": RMS_TEXT},
        {"value": "retry", "expr": f"!document.querySelector('{X} [data-act=\"remotion_studio_retry\"]').hidden"},
        {"click": f"{X} [data-act=\"remotion_studio_retry\"]"}, {"until": f"!!{DIALOG}", "ms": 8000}, {"click": CONFIRM},
        {"until": f"{RMS_STATE}.studio && {RMS_STATE}.studio.status==='ready' && !{RMS_STATE}.busy", "ms": 15000},
        {"value": "ok", "expr": RMS_TEXT}])
    reads = _ok(result)
    assert "remotion_studio_start_timeout" in reads["failedText"] and "n’a pas répondu dans le délai" in reads["failedText"] and reads["retry"]
    assert "ouvert sur cette scène" in reads["ok"]


async def test_the_rail_entry_opens_variants_then_the_same_confirmation(studio_deck):
    core, url, pid, runner, studio_url = studio_deck
    result = await drive(url, [{"until": "!!window.JarvisPresentationRail && !!window.JarvisStudioExplorer", "ms": 15000},
                               {"eval": f"window.JarvisPresentationRail.refresh()"}, {"wait": 600},
                               {"eval": f"void window.JarvisPresentationRail.run('studio','{pid}')"},
                               {"until": f"{EXPLORER}.state().open && !!{DIALOG}", "ms": 20000},
                               {"value": "dialog", "expr": f"{DIALOG}.innerText"},
                               {"value": "state", "expr": f"JSON.stringify({EXPLORER}.state())"}])
    reads = _ok(result)
    assert "Scène 1 sur 2" in reads["dialog"] and '"open":true' in reads["state"]
    assert not runner.launches, "nothing launched before the confirmation"


@pytest.mark.parametrize("viewport", ["800x600", "1280x720", "1920x1080"])
async def test_the_door_is_named_inside_the_window_without_overflow(studio_deck, viewport):
    core, url, pid, runner, studio_url = studio_deck
    result = await drive(url, _open_variants(pid) + [{"wait": 600}, {"value": "inv", "expr": INVENTORY}], viewport=viewport)
    inv = _ok(result)["inv"]
    door = [c for c in inv["controls"] if c["act"] == "remotion_studio"]
    assert len(door) == 1 and door[0]["name"] == "Remotion Studio", door
    assert 0 <= door[0]["box"][0] and door[0]["box"][2] <= inv["vw"] and inv["overflowX"] is False
    present = [c for c in inv["controls"] if c["act"] == "present"]
    assert len(present) == 1 and abs(present[0]["box"][1] - door[0]["box"][1]) <= 4, "on the scene row, beside « Présenter »"


# ---------------------------------------------------------------------------------------------------------------- evidence

def _evidence_dir() -> Path | None:
    raw = os.environ.get("JARVIS_VARIANTS_REMOTION_EVIDENCE_DIR")
    return Path(raw) if raw else None


@pytest.mark.skipif(_evidence_dir() is None, reason="JARVIS_VARIANTS_REMOTION_EVIDENCE_DIR not set")
async def test_evidence_variants_with_the_remotion_studio_door(studio_deck):
    core, url, pid, runner, studio_url = studio_deck
    out, tag = _evidence_dir(), os.environ.get("JARVIS_VARIANTS_REMOTION_SHOT_TAG", "local")
    out.mkdir(parents=True, exist_ok=True)
    plan = _open_variants(pid) + [{"wait": 800}, {"shot": str(out / f"after-{tag}-variants-1280x720.png")},
                                  {"click": DOOR}, {"until": f"!!{DIALOG}", "ms": 8000}, {"wait": 300},
                                  {"shot": str(out / f"after-{tag}-confirm-1280x720.png")},
                                  {"click": CONFIRM},
                                  {"until": f"{RMS_STATE}.studio && {RMS_STATE}.studio.status==='ready' && !{RMS_STATE}.busy", "ms": 15000},
                                  {"wait": 600}, {"shot": str(out / f"after-{tag}-open-here-1280x720.png")}]
    _ok(await drive(url, plan))
    _ok(await drive(url, _open_variants(pid) + [{"wait": 800}, {"shot": str(out / f"after-{tag}-variants-800x600.png")}], viewport="800x600"))
    runner.launch_errors = [StudioError(StudioErrorCode.START_TIMEOUT, "no answer within 120 s")]
    await _close_studio(core)
    _ok(await drive(url, _open_variants(pid) + [{"click": DOOR}, {"until": f"!!{DIALOG}", "ms": 8000}, {"click": CONFIRM},
                                                {"until": f"{RMS_STATE}.studio && {RMS_STATE}.studio.status==='failed'", "ms": 15000},
                                                {"wait": 400}, {"shot": str(out / f"after-{tag}-failed-1280x720.png")}]))

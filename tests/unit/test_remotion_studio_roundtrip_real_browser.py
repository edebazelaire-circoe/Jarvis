"""REAL round trip: Remotion Studio (the real `remotion studio` process) -> workspace edit -> HMR -> « Publier dans la variante… » in
Variants -> a fresh Core on the same data root shows the new version (handoff jarvis-remotion-native-studio-playback-fix, Slice 12).

Opt-in: `JARVIS_REMOTION_RUNTIME_DIR` (an installed Remotion runtime, e.g. the read-only gate copy: its `node_modules` is COPIED, only read, into a
PRIVATE data root: Remotion Studio's guard needs esbuild under that root), Node and Chrome. Everything runs on free loopback ports and a throw-away data root; the live Jarvis and
the user's own Remotion Studio are never contacted. ~600 MB while Remotion Studio builds.

1. Core life 1 (`RemotionStack`, real compiler, real `RemotionStudioRunner`): a 9-scene Remotion deck; Remotion Studio opened on scene 1's
   exact pin (Core route, the acknowledgment the Variants door sends after its confirmation; the door itself is proved in Slice 11).
2. Real headless Chrome on Remotion Studio's own page (`/Scene`): the composition renders; the test then edits `src/Scene.tsx` IN THE
   WORKSPACE (as an editor would) and waits until Remotion Studio's page shows the edit, without any reload: HMR, no render.
3. Real Chrome on the real Control Center page: Variants says « 1 fichier modifié … pas encore publié »; « Publier dans la variante… », the
   confirmation, « Publier »; Variants says « Publié dans la variante : nouvelle version de la scène (v1) ; la version d'avant reste disponible. » and plays it.
4. Core stopped (Remotion Studio closed with it). Core life 2 on the same data root: Variants shows the published version.

With `JARVIS_STUDIO_ROUNDTRIP_EVIDENCE_DIR`: `roundtrip.json` (SHA, durations, reads), the sample source, and the frame captures; the home
path and the user name are redacted at write time.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

from aiohttp import web
import pytest

from jarvis.adapters.remotion_studio_runner import RemotionStudioRunner
from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.unit.presentation_playback_gate_world import (
    PREFABS, SCENE_IDS, SCENE_TSX, VISIBLE_RECT, VSTATE, harness, make_deck, open_variants, png_rgb_mean, redact, run_long,
)

RUNTIME = runtime_dir_from_env()
pytestmark = [pytest.mark.asyncio,
              pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                 reason="needs JARVIS_REMOTION_RUNTIME_DIR (an installed Remotion runtime), node and Chrome")]

X = "#jvStudioExplorer"
RMS_TEXT = f"((document.querySelector('{X} .jvx-rms-text')||{{}}).textContent||'')"   # parenthesised: `.includes` applies to the text
PUBLISH = f"{X} [data-act=\"remotion_studio_publish\"]"
PUBLISH_GO = f"{X} [data-act=\"remotion_studio_publish_confirm\"]"
PUBLISH_DIALOG = f"document.querySelector('{X} [data-kind=\"remotion_studio_publish\"]')"
MARKER = "STUDIO-EDIT-OK"
EDITED_BG = "#00e0ff"
EDITED_TSX = SCENE_TSX.replace("background: props.bg", f'background: "{EDITED_BG}"').replace(
    '<p id="label"', f'<p id="edit" style={{{{color: "#000000", fontSize: 40, margin: 24}}}}>{MARKER}</p>\n      <p id="label"')


def evidence() -> Path | None:
    raw = os.environ.get("JARVIS_STUDIO_ROUNDTRIP_EVIDENCE_DIR")
    if not raw:
        return None
    folder = Path(raw)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def frame(folder: Path, name: str) -> dict:
    """One capture of the visible Remotion stage of Variants (the sandboxed Player frame), half size."""

    return {"burst": str(folder), "ms": 1, "clipExpr": VISIBLE_RECT, "scale": 0.5, "prefix": name, "as": f"shot_{name}"}


def distance(rgb, hex_color: str) -> float:
    ref = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return sum((a - b) ** 2 for a, b in zip(rgb, ref)) ** 0.5


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def editor(workspace: Path, port: int, log: dict) -> web.AppRunner:
    """A stand-in for the user's editor, called by the browser plan at the right moment: it saves the TSX into the workspace."""

    async def save(_request: web.Request) -> web.Response:
        target = workspace / "src" / "Scene.tsx"
        target.write_bytes(EDITED_TSX.encode("utf-8"))
        log["saved_at_ms"] = time.time() * 1000
        return web.json_response({"saved": True})

    app = web.Application()
    app.router.add_get("/save", save)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    return runner


def private_runtime_copy(tmp_path: Path) -> None:
    """A REAL copy of the runtime's `node_modules` inside the private data root (≈ 200 MB, ≈ 10 s with robocopy). Remotion Studio's guard
    lets only the esbuild binary under `<data root>/.../runtime/node_modules` run; Node resolves a junction to its target, so the shared
    junction of `RemotionStack` (enough for the Player's compiler) would be refused there. The source runtime is only read."""

    target = tmp_path / "data" / "local_capabilities" / "remotion" / "runtime" / "node_modules"
    if target.exists():
        return
    target.mkdir(parents=True)
    if os.name == "nt":
        done = subprocess.run(["robocopy", str(RUNTIME / "node_modules"), str(target), "/E", "/MT:8", "/NFL", "/NDL", "/NJH", "/NJS", "/NP",
                               "/R:1", "/W:1"], capture_output=True, text=True, check=False)
        harness(done.returncode < 8, f"robocopy failed ({done.returncode}): {done.stdout[-500:]}")
    else:
        shutil.copytree(RUNTIME / "node_modules", target, symlinks=True, dirs_exist_ok=True)


def studio_runner(stack) -> dict:
    return {"remotion_studio_runner": RemotionStudioRunner(lambda: stack.data_root / "local_capabilities" / "remotion" / "runtime")}


async def test_edit_in_remotion_studio_hot_reloads_publishes_into_the_variant_and_survives_a_core_restart(tmp_path):
    folder = evidence() or tmp_path
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    report: dict = {"slice": "12-native-authoring-workspace-roundtrip", "tested_head": head, "edited_source": "sample-Scene.tsx",
                    "runtime": "RemotionStack (real Core, real compiler, real remotion studio) on free loopback ports, throw-away data root, "
                               "headless Chrome over CDP; the live Jarvis was never contacted", "durations_ms": {}}
    (folder / "sample-Scene.tsx").write_text(EDITED_TSX, encoding="utf-8")
    log: dict = {}
    copy_started = time.monotonic()
    private_runtime_copy(tmp_path)
    report["durations_ms"]["private_runtime_copy"] = round((time.monotonic() - copy_started) * 1000)
    # ------------------------------------------------------------------ life 1
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME, core_options=studio_runner) as stack:
        pid, vid = await make_deck(stack)
        workspace = stack.data_root / "local_capabilities" / "remotion" / "runtime" / "studio" / "work"
        started = time.monotonic()
        status, opened = await stack.call("POST", "/v1/local-capabilities/remotion/studio/open",
                                          json={"prefab_id": PREFABS[0], "version": 1, "acknowledge_unsandboxed_scene": True})
        report["durations_ms"]["studio_open_cold"] = round((time.monotonic() - started) * 1000)
        harness(status == 200 and opened["studio"]["status"] == "ready", f"Remotion Studio did not open: {status} {opened}")
        studio_url = opened["studio"]["url"]
        report["studio_open"] = {k: opened["studio"].get(k) for k in ("status", "pin", "work_copy", "port_mode")}
        port = free_port()
        edit_server = await editor(workspace, port, log)
        try:
            # 2. Remotion Studio's own page: render, the editor saves, HMR shows it without a reload (no MP4 render on edit)
            studio_plan = [
                {"until": "document.body.innerText.includes('S1')", "ms": 120000, "as": "studio_rendered"},
                {"value": "studio_text", "expr": "document.body.innerText.slice(0,600)"},
                {"until": "document.body.innerText.includes('S1')", "ms": 1000, "required": True, "as": "studio_rendered_required"},
                {"wait": 1500}, {"shot": str(folder / "studio-before-edit.png")},
                {"eval": "window.__noReload=true"},
                {"http": {"method": "GET", "url": f"http://127.0.0.1:{port}/save"}, "as": "saved"},
                {"until": f"document.body.innerText.includes('{MARKER}')", "ms": 60000, "required": True, "as": "hmr_seen"},
                {"value": "hmr_seen_at_ms", "expr": "Date.now()"}, {"value": "same_document", "expr": "window.__noReload===true"},
                {"wait": 1000}, {"shot": str(folder / "studio-after-edit.png")}]
            studio = await run_long(studio_url + "Scene", studio_plan, timeout=300)
            reads = studio["reads"]
            harness("failed" not in reads, reads.get("failed"))
            report["studio"] = {"rendered": reads.get("studio_rendered"), "text_before_edit": reads.get("studio_text"), "hmr_seen": reads.get("hmr_seen"),
                                "same_document_no_reload": reads.get("same_document"), "console_errors": [l for l in studio["console"] if l.startswith("error")][:10]}
            report["durations_ms"]["hmr_edit_to_screen"] = round(reads["hmr_seen_at_ms"] - log["saved_at_ms"])
            assert reads["hmr_seen"] and reads["same_document"] is True, "Remotion Studio's HMR showed the edit in the same page"
            status, view = await stack.call("GET", "/v1/local-capabilities/remotion/studio")
            assert view["studio"]["work_copy"]["modified_files"] == ["src/Scene.tsx"] and view["studio"]["work_copy"]["unpublished"] == 1
            report["work_copy_before_publish"] = view["studio"]["work_copy"]
            # 3. Variants on the real Control Center page: said, published, played
            variants_plan = open_variants(pid) + [
                {"until": f"{RMS_TEXT}.includes('pas encore publi')", "ms": 30000, "required": True, "as": "said_unpublished"},
                {"value": "line_before", "expr": RMS_TEXT}, {"wait": 1500}, frame(folder, "variants-before-publish"),
                {"shot": str(folder / "variants-unpublished-1280x720.png")},
                {"click": PUBLISH}, {"until": f"!!{PUBLISH_DIALOG}", "ms": 8000, "required": True, "as": "confirm_shown"},
                {"value": "confirm_text", "expr": f"{PUBLISH_DIALOG}.innerText"}, {"shot": str(folder / "variants-publish-confirm-1280x720.png")},
                {"value": "publish_clicked_at_ms", "expr": "Date.now()"}, {"click": PUBLISH_GO},
                {"until": f"{RMS_TEXT}.includes('dans la variante : nouvelle version')", "ms": 150000, "required": True, "as": "published"},
                {"value": "published_at_ms", "expr": "Date.now()"}, {"value": "line_after", "expr": RMS_TEXT},
                {"until": f"(()=>{{const s={VSTATE};return !!s&&s.phase==='ready'}})()", "ms": 90000, "required": True, "as": "player_ready_again"},
                {"wait": 2500}, frame(folder, "variants-after-publish"), {"shot": str(folder / "variants-published-1280x720.png")},
                {"value": "preview_pin", "expr": f"(JarvisStudioExplorer.state().preview||{{}})"}]
            variants = await run_long(stack.page_url, variants_plan, timeout=420)
            v = variants["reads"]
            harness("failed" not in v, v.get("failed"))
            report["variants"] = {k: v.get(k) for k in ("line_before", "confirm_text", "line_after", "preview_pin")}
            report["durations_ms"]["publish_click_to_said"] = round(v["published_at_ms"] - v["publish_clicked_at_ms"])
            assert "Publié dans la variante : nouvelle version de la scène (v1) ; la version d’avant reste disponible." in v["line_after"]
            status, variant = await stack.call("GET", f"/v1/presentation-studio/presentations/{pid}/variants/{vid}")
            pin = next(scene["prefab"] for scene in variant["scenes"] if scene["scene_id"] == SCENE_IDS[0])
            assert pin["id"].startswith("presentation-studio.") and pin["id"] != PREFABS[0] and pin["version"] == 1, pin
            report["scene_pin_after_publish"] = pin
            before = png_rgb_mean(Path(v["shot_variants-before-publish"][0][1]))
            after = png_rgb_mean(Path(v["shot_variants-after-publish"][0][1]))
            report["stage_mean_rgb"] = {"before": before, "after": after}
            assert distance(after, EDITED_BG) < distance(before, EDITED_BG), (before, after)
        finally:
            await edit_server.cleanup()
    # ------------------------------------------------------------------ life 2: a fresh Core on the same data root
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME, core_options=studio_runner) as stack:
        status, variant = await stack.call("GET", f"/v1/presentation-studio/presentations/{pid}/variants/{vid}")
        pin_again = next(scene["prefab"] for scene in variant["scenes"] if scene["scene_id"] == SCENE_IDS[0])
        assert pin_again == pin, "the published version is the scene's pin after a Core restart"
        status, view = await stack.call("GET", "/v1/local-capabilities/remotion/studio")
        report["studio_after_restart"] = {k: view["studio"].get(k) for k in ("status", "stop_reason", "pin", "work_copy")}
        assert view["studio"]["status"] in ("stopped", "failed") and view["studio"]["work_copy"]["unpublished"] == 0
        assert view["studio"]["pin"] == {"prefab_id": pin["id"], "version": pin["version"]}, "the workspace base followed the publication"
        restart_plan = open_variants(pid) + [{"wait": 2500}, frame(folder, "variants-after-restart"),
                                             {"shot": str(folder / "variants-after-restart-1280x720.png")},
                                             {"value": "preview_pin", "expr": f"(JarvisStudioExplorer.state().preview||{{}})"}]
        again = await run_long(stack.page_url, restart_plan, timeout=300)
        r = again["reads"]
        harness("failed" not in r, r.get("failed"))
        restarted = png_rgb_mean(Path(r["shot_variants-after-restart"][0][1]))
        report["stage_mean_rgb"]["after_restart"] = restarted
        assert distance(restarted, EDITED_BG) < 80, restarted
    report["evidence_files"] = sorted(p.name for p in folder.iterdir() if p.suffix in (".png", ".tsx"))
    (folder / "roundtrip.json").write_text(redact(json.dumps(report, indent=1, ensure_ascii=False, default=str)), encoding="utf-8")
    await asyncio.sleep(0)

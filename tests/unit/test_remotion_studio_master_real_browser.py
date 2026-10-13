"""REAL proof: a whole Presentation Variant opened in the managed native Remotion Studio (handoff jarvis-remotion-master-project-studio-export,
Slice 05; `docs/remotion-master-project.md` § 9, § 11).

Opt-in: `JARVIS_REMOTION_RUNTIME_DIR` (an installed Remotion runtime, e.g. the read-only gate copy; its `node_modules` is COPIED, only read,
into a PRIVATE data root, as `test_remotion_studio_roundtrip_real_browser.py` does), Node and Chrome. Free loopback ports, a throw-away data
root; the live Jarvis and the user's own Remotion Studio are never contacted. One real `remotion studio` process at a time.

1. Real Core (`RemotionStack`, real `RemotionStudioRunner`): a 3-scene Remotion deck (1280x720 @ 30, 30 + 45 + 60 frames). `GET
   .../master-project` gives the key; the master body opens the real `remotion studio` on the generated master root.
2. Headless Chrome over CDP on Remotion Studio's own page `/JarvisPresentation`: the composition is listed and shown with the master
   duration (135 frames, 4.5 s); stepping through the timeline shows each scene in turn (its title), i.e. the scene sources are mounted.
3. Another variant (a second deck, two scenes) has another key: a stale body is refused 409, the new key hot-syncs the same process.
4. An unpublished edit of a mounted scene source blocks a rebuild (409 `remotion_studio_unpublished_edits`, class `scene`) until
   `discard_unpublished: true`.
5. Back to a scene target (schema 1): Remotion Studio's page shows that scene alone.

With `JARVIS_STUDIO_MASTER_EVIDENCE_DIR`: `studio-master-summary.json` and the screenshots; the home path and the user name are redacted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.domain.remotion_source import Composition
from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.fakes.remotion_scene import scene_candidate
from tests.unit.presentation_playback_gate_world import BASE, PROPS, SCENE_TSX, harness, redact, run_long
from tests.unit.test_remotion_studio_roundtrip_real_browser import private_runtime_copy, studio_runner

RUNTIME = runtime_dir_from_env()
pytestmark = [pytest.mark.asyncio,
              pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                 reason="needs JARVIS_REMOTION_RUNTIME_DIR (an installed Remotion runtime), node and Chrome")]

STUDIO = "/v1/local-capabilities/remotion/studio"
PREFABS = [f"presentation-studio.p0000000000b1.s{n:012d}" for n in range(1, 4)]
FRAMES = (30, 45, 60)
COLORS = ("#b01010", "#10a010", "#1030c0")
TEXT = "document.body.innerText"


def evidence() -> Path | None:
    raw = os.environ.get("JARVIS_STUDIO_MASTER_EVIDENCE_DIR")
    if not raw:
        return None
    folder = Path(raw)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


async def publish_scenes(stack: RemotionStack) -> None:
    for n, prefab_id in enumerate(PREFABS):
        await stack.core.prefabs.save(scene_candidate(
            prefab_id, engine=shipped_engine_pin(), title=f"M{n + 1}", composition=Composition("Scene", 1280, 720, 30, FRAMES[n]),
            files={"src/Scene.tsx": SCENE_TSX}, props=PROPS, sample={"props": {"title": f"M{n + 1}", "bg": COLORS[n]}, "data": {}}),
            actor="user")


async def deck(stack: RemotionStack, title: str, order: list[int]) -> tuple[str, str]:
    _, created = await stack.call("POST", BASE, json={"title": title})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    scenes = [{"scene_id": f"pss_{'a' if title.startswith('M') else 'b'}{n:011d}", "prefab": {"id": PREFABS[n], "version": 1}, "title": f"SCENE-{n + 1}",
               "props": {"title": f"SCENE-{n + 1}", "bg": COLORS[n]}, "data": {}} for n in order]
    status, saved = await stack.call("PUT", f"{BASE}/{pid}/variants/{variant['variant_id']}", json={
        "expected_revision": variant["revision"], "title": variant["title"], "scenes": scenes,
        "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"]})
    harness(status == 200, f"variant save refused: {saved}")
    return pid, variant["variant_id"]


def master(pid: str, vid: str, key: str, **extra) -> dict:
    return {"kind": "variant_master", "presentation_id": pid, "variant_id": vid, "project_key": key,
            "acknowledge_unsandboxed_project": True, **extra}


def step_until(text: str, ms: int, name: str) -> list[dict]:
    """Press → (one frame) until the Studio's page shows `text` (the next scene's title)."""

    return [{"until": f"{TEXT}.includes('{text}')", "ms": ms, "as": name}]


async def test_a_whole_variant_opens_in_real_remotion_studio_and_switches_target_safely(tmp_path):
    folder = evidence() or tmp_path
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    report: dict = {"slice": "05-remotion-studio-master-project", "tested_head": head, "durations_ms": {},
                    "runtime": "RemotionStack (real Core, real remotion studio via RemotionStudioRunner) on free loopback ports, throw-away data "
                               "root with a private copy of the gate runtime's node_modules, headless Chrome over CDP; the live Jarvis and "
                               "the user's own Remotion Studio were never contacted"}
    started = time.monotonic()
    private_runtime_copy(tmp_path)
    report["durations_ms"]["private_runtime_copy"] = round((time.monotonic() - started) * 1000)
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME, core_options=studio_runner) as stack:
        await publish_scenes(stack)
        pid, vid = await deck(stack, "Master A", [0, 1, 2])
        pid_b, vid_b = await deck(stack, "Bravo", [2, 0])
        status, read = await stack.call("GET", f"{BASE}/{pid}/variants/{vid}/master-project")
        harness(status == 200 and read["master"]["status"] == "ready", f"master not ready: {status} {read}")
        plan = read["master"]
        key = plan["project_key"]
        assert plan["composition"] == {"id": "JarvisPresentation", "width": 1280, "height": 720, "fps": 30, "duration_in_frames": 135}
        report["plan"] = {k: plan[k] for k in ("status", "project_key", "composition", "totals")} | {
            "scenes": [{k: s[k] for k in ("scene_id", "prefab_id", "from_frame", "duration_in_frames", "mount")} for s in plan["scenes"]]}

        # 1. open the master in the real remotion studio
        started = time.monotonic()
        status, opened = await stack.call("POST", STUDIO + "/open", json=master(pid, vid, key))
        report["durations_ms"]["studio_open_master_cold"] = round((time.monotonic() - started) * 1000)
        harness(status == 200 and opened["studio"]["status"] == "ready", f"Remotion Studio did not open the master: {status} {opened}")
        view = opened["studio"]
        report["studio_open"] = {k: view.get(k) for k in ("status", "pin", "target", "composition", "work_copy")}
        assert view["pin"] is None and view["target"]["kind"] == "variant_master" and view["target"]["scene_count"] == 3
        assert view["target"]["stale"] is False and view["composition"]["id"] == "JarvisPresentation"
        state = json.loads((stack.data_root / "local_capabilities" / "remotion" / "runtime" / "studio" / "state.json").read_text("utf-8"))
        assert state["schema"] == 2 and state["target"]["project_key"] == key and "pin" not in state
        work = stack.data_root / "local_capabilities" / "remotion" / "runtime" / "studio" / "work"
        mounted = sorted(p.relative_to(work).as_posix() for p in (work / "src").rglob("*") if p.is_file())
        report["workspace_src"] = mounted
        assert {f"src/scenes/{s['scene_id']}/Scene.tsx" for s in plan["scenes"]} <= set(mounted)
        assert not os.access(work / "src" / "master" / "Presentation.tsx", os.W_OK), "generated files are read-only"
        url = view["url"]

        # 2. Remotion Studio's own page: the master composition, its duration, each scene in turn
        page = [{"until": f"{TEXT}.includes('JarvisPresentation')", "ms": 150000, "required": True, "as": "composition_listed"},
                {"until": f"{TEXT}.includes('SCENE-1')", "ms": 60000, "required": True, "as": "scene1_rendered"},
                {"wait": 1500}, {"value": "text_at_open", "expr": f"{TEXT}.slice(0,1500)"},
                {"shot": str(folder / "studio-master-open.png")}]
        for n in (2, 3):
            page += [{"eval": "window.focus()"}] + [{"key": "ArrowRight", "shift": True} for _ in range(2)]
            page += step_until(f"SCENE-{n}", 15000, f"scene{n}_rendered")
            page += [{"value": f"text_scene{n}", "expr": f"{TEXT}.slice(0,1500)"}, {"shot": str(folder / f"studio-master-scene{n}.png")}]
        studio = await run_long(url + "JarvisPresentation", page, timeout=400)
        reads = studio["reads"]
        harness("failed" not in reads, reads.get("failed"))
        report["studio_page"] = {k: reads.get(k) for k in ("composition_listed", "scene1_rendered", "scene2_rendered", "scene3_rendered",
                                                             "text_at_open")}
        report["studio_page"]["console_errors"] = [line for line in studio["console"] if line.startswith("error")][:10]
        assert reads["composition_listed"] and reads["scene1_rendered"]
        text = reads["text_at_open"]
        assert "JarvisPresentation" in text and ("135" in text or "0:04.15" in text or "00:04.15" in text or "4.5" in text), text
        assert reads.get("scene2_rendered") and reads.get("scene3_rendered"), "each mounted scene source shows in the master timeline"

        # 3. another variant: another key; a stale body is refused, the new key hot-syncs the SAME process
        _, other = await stack.call("GET", f"{BASE}/{pid_b}/variants/{vid_b}/master-project")
        key_b = other["master"]["project_key"]
        assert other["master"]["status"] == "ready" and key_b != key
        status, stale = await stack.call("POST", STUDIO + "/sync", json=master(pid_b, vid_b, key))
        assert status == 409 and stale["error"]["code"] == "remotion_studio_master_stale" and stale["error"]["project_key"] == key_b
        started = time.monotonic()
        status, switched = await stack.call("POST", STUDIO + "/sync", json=master(pid_b, vid_b, key_b))
        report["durations_ms"]["studio_switch_variant_hot"] = round((time.monotonic() - started) * 1000)
        assert status == 200 and switched["studio"]["target"]["project_key"] == key_b and switched["studio"]["target"]["scene_count"] == 2
        assert switched["studio"]["port"] == view["port"], "one process: the switch is a hot sync"
        report["switch_variant"] = {"stale_refusal": stale["error"], "target": switched["studio"]["target"]}

        # 4. an unpublished edit of a mounted scene source blocks a rebuild until it is set aside
        scene_b = other["master"]["scenes"][0]["scene_id"]
        edited = work / "src" / "scenes" / scene_b / "Scene.tsx"
        edited.write_text(SCENE_TSX.replace("props.title", '"EDITED-" + props.title'), encoding="utf-8")
        _, status_view = await stack.call("GET", STUDIO)
        classified = status_view["studio"]["work_copy"]["classified"]
        assert classified == [{"path": f"src/scenes/{scene_b}/Scene.tsx", "class": "scene", "scene_id": scene_b}], classified
        status, blocked = await stack.call("POST", STUDIO + "/sync", json=master(pid_b, vid_b, key_b))
        assert status == 409 and blocked["error"]["code"] == "remotion_studio_unpublished_edits"
        assert blocked["error"]["classified"][0]["class"] == "scene" and "EDITED-" in edited.read_text("utf-8"), "never overwritten"
        status, discarded = await stack.call("POST", STUDIO + "/sync", json=master(pid_b, vid_b, key_b, discard_unpublished=True))
        assert status == 200 and discarded["studio"]["work_copy"]["unpublished"] == 0 and discarded["studio"]["work_copy"]["edits_saved"] == 1
        report["unpublished"] = {"classified": classified, "refusal": blocked["error"]["code"],
                                 "after_discard": discarded["studio"]["work_copy"]}

        # 5. back to a scene target in the same process: schema 1, the scene alone on Remotion Studio's page
        status, scene = await stack.call("POST", STUDIO + "/open", json={"prefab_id": PREFABS[0], "version": 1,
                                                                           "acknowledge_unsandboxed_scene": True})
        assert status == 200 and scene["studio"]["target"] == {"kind": "scene", "prefab_id": PREFABS[0], "version": 1}
        assert scene["studio"]["pin"] == {"prefab_id": PREFABS[0], "version": 1} and scene["studio"]["port"] == view["port"]
        state = json.loads((stack.data_root / "local_capabilities" / "remotion" / "runtime" / "studio" / "state.json").read_text("utf-8"))
        assert state["schema"] == 1 and "target" not in state and not (work / "src" / "master").exists()
        back = await run_long(url + "Scene", [{"until": f"{TEXT}.includes('M1')", "ms": 90000, "required": True, "as": "scene_rendered"},
                                              {"wait": 1000}, {"value": "text_scene", "expr": f"{TEXT}.slice(0,800)"},
                                              {"shot": str(folder / "studio-scene-after-master.png")}], timeout=200)
        harness("failed" not in back["reads"], back["reads"].get("failed"))
        assert "JarvisPresentation" not in back["reads"]["text_scene"], "the master composition is gone with the master target"
        report["back_to_scene"] = {"target": scene["studio"]["target"], "state_schema": state["schema"],
                                   "text": back["reads"]["text_scene"][:300]}
        status, closed = await stack.call("POST", STUDIO + "/close", json={})
        assert status == 200 and closed["studio"]["status"] == "stopped"
    report["evidence_files"] = sorted(p.name for p in folder.iterdir() if p.suffix == ".png")
    (folder / "studio-master-summary.json").write_text(redact(json.dumps(report, indent=1, ensure_ascii=False, default=str)), encoding="utf-8")

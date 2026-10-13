"""Master Remotion workspace, REAL (handoff jarvis-remotion-master-project-studio-export, Slice 04; `docs/remotion-master-project.md` §6-8).

A 3-scene master (scene 1 plays `<Audio>` from `staticFile`, scene 2 an `<OffthreadVideo>`, scene 3 imports between its own modules) is planned
(`plan_master`), laid out (`plan_master_files`) and handed to the REAL guarded render runner (`RemotionRenderRunner.prepare` + `run`:
pinned @remotion/bundler + renderer, `render-guard.cjs`, deny proxy, Chrome sandbox): the bundle compiles, `selectComposition("JarvisPresentation")`
matches the plan spec and duration (the host's declared-config check), frames around each boundary show each scene at its local frame 0, the
MP4 holds the whole duration and an audio stream. A throwing scene is contained by `SceneBoundary` outside rendering: the read-only Studio
of the same bundle shows the fallback card naming the scene.

Opt-in: `JARVIS_REMOTION_RUNTIME_DIR` = a Remotion `runtime/` folder (read only: it is copied, `node_modules` joined, into `tmp_path`). Skips
without it, without Node or without Chrome. Never the live JARVIS.
"""

from __future__ import annotations

import functools
import http.server
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import threading
import time
import wave

import pytest

from jarvis.adapters.remotion_render_runner import RemotionRenderRunner
from jarvis.domain.prefab import PrefabRef
from jarvis.domain.presentation_studio import StudioScene
from jarvis.domain.presentation_studio_engine import Engine
from jarvis.adapters.remotion_media_tools import compositor_tool
from jarvis.domain.remotion_master_files import plan_master_files
from jarvis.domain.remotion_master_project import MasterInputs, PinSource, plan_master
from jarvis.domain.remotion_source import Composition, decode_candidate_files, parse_source, parse_source_block
from jarvis.domain.remotion_studio import plan_workspace
from tests.fakes.remotion_player_stack import provision_runtime
from tests.fakes.remotion_scene import ENGINE, scene_candidate

RUNTIME = os.environ.get("JARVIS_REMOTION_RUNTIME_DIR", "")
pytestmark = pytest.mark.skipif(not RUNTIME or shutil.which("node") is None or not (Path(RUNTIME or ".") / "node_modules" / "@remotion").is_dir(),
                                reason="JARVIS_REMOTION_RUNTIME_DIR (a Remotion runtime) and Node.js are required")

W, H, FPS = 320, 180, 30
D1, D2, D3 = 30, 45, 30
IDS = ("pss_0000000000a1", "pss_0000000000b2", "pss_0000000000c3")
PREFABS = tuple(f"presentation-studio.p000000000004.s00000000000{n}" for n in range(1, 4))
PROBE = '''const seen = new Set<number>();
export const probe = (label: string, frame: number, duration: number) => {
  if (!seen.has(frame)) {
    seen.add(frame);
    console.log(`PROBE|${label}|${frame}|${duration}`);
  }
};
'''


def scene_tsx(label: str, color: str, body: str, imports: str = "") -> str:
    return f'''import React from "react";
import {{AbsoluteFill, Audio, OffthreadVideo, staticFile, useCurrentFrame, useVideoConfig}} from "remotion";
import {{probe}} from "./probe";
{imports}
export default function Scene(props: {{title: string}}) {{
  const frame = useCurrentFrame();
  const {{durationInFrames}} = useVideoConfig();
  probe("{label}:" + props.title, frame, durationInFrames);
  return (
    <AbsoluteFill style={{{{background: "{color}"}}}}>
      {body}
    </AbsoluteFill>
  );
}}
'''


def tone_wav(seconds: float = 1.0, rate: int = 22050) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(int(seconds * rate))))
    return buffer.getvalue()


def make_source(files, duration: int):
    candidate = scene_candidate(files=files, composition=Composition("Scene", W, H, FPS, duration), engine=ENGINE,
                                props={"type": "object", "properties": {"title": {"type": "string", "default": "d", "max_length": 40}}},
                                sample={"props": {"title": "d"}, "data": {}})
    return parse_source(parse_source_block(candidate["manifest"]["source"]), decode_candidate_files(candidate["sources"], candidate["assets"]))


def runtime_root(tmp_path: Path) -> Path:
    provision_runtime(tmp_path / "rt", Path(RUNTIME))
    return tmp_path / "rt" / "local_capabilities" / "remotion" / "runtime"


def run_job(runner: RemotionRenderRunner, job_id: str, files, spec):
    browser = runner.find_browser()
    if browser is None:
        pytest.skip("no Chrome/Edge found for the real render")
    runner.prepare(job_id, files)
    started = time.monotonic()
    outcome = runner.run(job_id, spec, browser=browser, cancel=threading.Event(), timeout_s=600, on_start=lambda ref: None,
                         on_progress=lambda progress: None)
    elapsed = time.monotonic() - started
    result = json.loads((runner.job_dir(job_id) / "result.json").read_text(encoding="utf-8"))
    return outcome, result, elapsed


def spec_of(plan, fmt: str, **extra):
    c = plan.composition
    return {"format": fmt, "entry": "studio-root.tsx", "composition_id": c.composition_id,
            "composition": {"width": c.width, "height": c.height, "fps": c.fps, "durationInFrames": c.duration_in_frames},
            "props": {}, "crf": 23, "scale": 1, "concurrency": 1, "jpeg_quality": 80, **extra}


def clip_mp4(runner: RemotionRenderRunner) -> bytes:
    """A real 15-frame H.264 clip, made by the same guarded runner from a scene-lane workspace (the pinned ffmpeg has no generator input)."""

    files = {"src/Scene.tsx": 'import React from "react";\nimport {AbsoluteFill, useCurrentFrame} from "remotion";\n'
                              'export default function Scene() {\n  const f = useCurrentFrame();\n'
                              '  return <AbsoluteFill style={{background: `rgb(${f * 16}, 80, 200)`}} />;\n}\n'}
    source = make_source(files, 15)
    outcome, result, _ = run_job(runner, "rj_00000000c11f", plan_workspace(source, {}),
                                 {"format": "mp4", "entry": "studio-root.tsx", "composition_id": "Scene",
                                  "composition": {"width": W, "height": H, "fps": FPS, "durationInFrames": 15}, "props": {},
                                  "frames_total": 15, "frame_range": [0, 14], "crf": 28, "scale": 0.5, "concurrency": 1})
    assert outcome.ok, (outcome.code, outcome.detail, result.get("message", "")[:400])
    return (runner.job_dir("rj_00000000c11f") / "out.mp4").read_bytes()


def deck(clip: bytes, *, throwing: bool = False):
    s1 = {"src/Scene.tsx": scene_tsx("s1", "#cc2222", '<Audio src={staticFile("s1-tone.wav")} />'), "src/probe.ts": PROBE,
          "public/s1-tone.wav": tone_wav()}
    s2 = {"src/Scene.tsx": scene_tsx("s2", "#22cc22", '<OffthreadVideo src={staticFile("s2-clip.mp4")} style={{width: 160}} />'),
          "src/probe.ts": PROBE, "public/s2-clip.mp4": clip}
    s3 = {"src/Scene.tsx": scene_tsx("s3", "#2222cc", "<Panel />", 'import {Panel} from "./parts/Panel";'), "src/probe.ts": PROBE,
          "src/parts/Panel.tsx": 'import React from "react";\nimport {accent} from "../palette";\n'
                                 'export const Panel = () => <div style={{width: 80, height: 40, background: accent}} />;\n',
          "src/palette.ts": 'export const accent = "#ffcc00";\n'}
    if throwing:
        s1 = {**s1, "src/Scene.tsx": s1["src/Scene.tsx"].replace("const frame = useCurrentFrame();",
                                                                 'const frame = useCurrentFrame();\n  if (frame >= 0) throw new Error("boom in s1");')}
    sources = (make_source(s1, D1), make_source(s2, D2), make_source(s3, D3))
    scenes = tuple(StudioScene(IDS[i], PrefabRef(PREFABS[i], 1), props={"title": f"T{i + 1}"}) for i in range(3))
    pins = {(PREFABS[i], 1): PinSource.remotion(sources[i], props_defaults={"title": "d"}) for i in range(3)}
    plan = plan_master(MasterInputs("pst_" + "4" * 32, "psv_" + "4" * 32, 1, Engine.REMOTION, scenes, pins))
    assert plan.ready, (plan.reason, plan.detail)
    return plan


def probes(result) -> set[tuple[str, int, int]]:
    found = set()
    for line in result.get("browser_logs", []):
        if line.startswith("PROBE|"):
            _, label, frame, duration = line.split("|")
            found.add((label, int(frame), int(duration)))
    return found


def test_the_master_workspace_compiles_and_plays_each_scene_from_its_local_frame_0(tmp_path):
    runner = RemotionRenderRunner(lambda: runtime_root(tmp_path))
    assert runner.runtime_ready() is None, runner.runtime_ready()
    plan = deck(clip_mp4(runner))
    files = plan_master_files(plan)
    assert plan.composition.duration_in_frames == D1 + D2 + D3 == 105
    # frames around every boundary: 0 | 29 30 | 74 75 | 104
    frames = [0, D1 - 1, D1, D1 + D2 - 1, D1 + D2, D1 + D2 + D3 - 1]
    outcome, result, elapsed = run_job(runner, "rj_00000000a051", files, spec_of(plan, "pdf", frames=frames, frames_total=len(frames),
                                                                                 frame_range=[0, 104]))
    assert outcome.ok, (outcome.code, outcome.detail, result.get("message", "")[:600])
    seen = probes(result)
    expected = {("s1:T1", 0, D1), ("s1:T1", D1 - 1, D1), ("s2:T2", 0, D2), ("s2:T2", D2 - 1, D2), ("s3:T3", 0, D3), ("s3:T3", D3 - 1, D3)}
    assert seen == expected, (sorted(seen), result.get("browser_logs"))  # each frame shows exactly one scene, at its local frame
    assert len(outcome.outputs) == len(frames) and all(Path(p).stat().st_size > 0 for p in outcome.outputs)
    print(f"\nmaster stills: {len(frames)} frames in {elapsed:.1f} s; probes {sorted(seen)}")

    outcome, result, elapsed = run_job(runner, "rj_00000000a052", files, spec_of(plan, "mp4", frames_total=105, frame_range=[0, 104],
                                                                                 scale=0.5))
    assert outcome.ok, (outcome.code, outcome.detail, result.get("message", "")[:600])
    ffprobe = compositor_tool(runner_root := Path(runner._runtime_dir()), "ffprobe")  # noqa: SLF001 - the pinned binary of this runtime
    assert ffprobe is not None, runner_root
    probe = json.loads(subprocess.run([str(ffprobe), "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(outcome.outputs[0])],
                                      capture_output=True, text=True, timeout=60, check=True).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    audio = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    assert int(video["nb_read_frames"]) == 105 and (int(video["width"]), int(video["height"])) == (W // 2, H // 2)
    assert video["r_frame_rate"] == "30/1" and audio, probe["streams"]
    print(f"master mp4: 105 frames {video['width']}x{video['height']} + {audio[0]['codec_name']} audio in {elapsed:.1f} s")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs) -> None:  # argued: a test server's access log is noise
        pass


def _serve(folder: Path):
    handler = functools.partial(_Quiet, directory=str(folder))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_throwing_scene_is_contained_by_its_boundary_outside_rendering(tmp_path):
    runner = RemotionRenderRunner(lambda: runtime_root(tmp_path))
    plan = deck(clip_mp4(runner), throwing=True)
    files = plan_master_files(plan)
    # Rendering: the boundary cancels the render, naming the scene (the typed job failure itself is Slice 06).
    outcome, result, _ = run_job(runner, "rj_00000000a053", files, spec_of(plan, "pdf", frames=[0], frames_total=1, frame_range=[0, 0]))
    assert not outcome.ok and f"jarvis_master_scene_failed:{IDS[0]}:1: boom in s1" in result.get("message", ""), result.get("message", "")[:600]
    # Outside rendering: the read-only Studio of the same bundle draws the fallback card and the page keeps running.
    browser = runner.find_browser()
    server = _serve(runner.job_dir("rj_00000000a053") / "bundle")
    try:
        # the read-only Studio routes by query string (`@remotion/studio` url-state: `?/<composition id>`)
        url = f"http://127.0.0.1:{server.server_address[1]}/?/{plan.composition.composition_id}"
        dom = subprocess.run([browser.path, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
                              f"--user-data-dir={tmp_path / 'chrome'}", "--proxy-server=http://127.0.0.1:9", "--virtual-time-budget=20000",
                              "--dump-dom", url], capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace").stdout
    finally:
        server.shutdown()
    (tmp_path / "studio-dom.html").write_text(dom, encoding="utf-8")
    assert f"Scène 1 ({IDS[0]}) : erreur — boom in s1" in dom, dom[-1500:]
    assert "&lt;Series.Sequence&gt;" in dom and "JarvisPresentation" in dom, "the Studio keeps the master timeline after the failure"

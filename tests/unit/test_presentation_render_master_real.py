"""Whole-video render, REAL (handoff jarvis-remotion-master-project-studio-export, Slice 06; `docs/remotion-master-project.md` §10).

A real world (registry, Studio, prefab store, packager) freezes a 3-scene variant (320x180 @ 30; 30 + 45 + 30 frames; scene 1 plays an
`<Audio>` from `staticFile`, scene 2 an `<OffthreadVideo>`, scene 3 imports between its own modules); `PresentationRenderService.submit`
with `scope: "master"` renders it through the REAL guarded runner (pinned bundler + renderer, `render-guard.cjs`, deny proxy, Chrome
sandbox). The stored `presentation_video` is probed with the pinned ffprobe (105 frames, H.264 + audio) and decoded at every boundary with
the pinned ffmpeg: each scene paints its background from its LOCAL frame, so a boundary that enters the next scene at its local frame 0
shows that scene's base colour. A second variant with a scene that throws fails as `presentation_render_master_scene_failed` naming it.

Opt-in: `JARVIS_REMOTION_RUNTIME_DIR` (read only: copied, `node_modules` joined, into `tmp_path`). Never the live JARVIS. One render at a time.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

from jarvis.adapters.remotion_media_tools import compositor_tool
from jarvis.adapters.remotion_render_runner import RemotionRenderRunner
from jarvis.core.presentation_render_service import PresentationRenderService
from jarvis.domain.artifacts import ArtifactState
from jarvis.domain.remotion_source import Composition
from tests.fakes.presentation_world import PresentationWorld
from tests.fakes.remotion_scene import ENGINE, scene_candidate
from tests.unit.test_remotion_master_files_real import clip_mp4, runtime_root, tone_wav

RUNTIME = os.environ.get("JARVIS_REMOTION_RUNTIME_DIR", "")
pytestmark = pytest.mark.skipif(not RUNTIME or shutil.which("node") is None or not (Path(RUNTIME or ".") / "node_modules" / "@remotion").is_dir(),
                                reason="JARVIS_REMOTION_RUNTIME_DIR (a Remotion runtime) and Node.js are required")

W, H, FPS = 320, 180, 30
DURATIONS = (30, 45, 30)
IDS = ("pss_0000000006a1", "pss_0000000006b2", "pss_0000000006c3")
PREFABS = tuple(f"presentation-studio.p000000000006.s00000000000{n}" for n in range(1, 4))
PROPS = {"type": "object", "properties": {"title": {"type": "string", "default": "d", "max_length": 40}}}
#: channel painted by each scene: value = 40 + 4 x local frame
CHANNEL = (0, 1, 2)


def scene_tsx(channel: int, body: str, imports: str = "", throw: bool = False) -> str:
    rgb = ["0", "0", "0"]
    rgb[channel] = "${40 + frame * 4}"
    boom = '\n  if (frame >= 3) throw new Error("boom in the video scene");' if throw else ""
    return f'''import React from "react";
import {{AbsoluteFill, Audio, OffthreadVideo, staticFile, useCurrentFrame}} from "remotion";
{imports}
export default function Scene(props: {{title: string}}) {{
  const frame = useCurrentFrame();{boom}
  return (
    <AbsoluteFill style={{{{background: `rgb({", ".join(rgb)})`}}}}>
      {body}
    </AbsoluteFill>
  );
}}
'''


async def publish(world, n: int, files) -> int:
    candidate = scene_candidate(PREFABS[n], files=files, composition=Composition("Scene", W, H, FPS, DURATIONS[n]), engine=ENGINE,
                                props=PROPS, sample={"props": {"title": "d"}, "data": {}})
    return (await world.prefabs.save(candidate, actor="user")).version


async def frozen_deck(world, clip: bytes, *, throw: bool = False) -> str:
    sources = (
        {"src/Scene.tsx": scene_tsx(0, '<Audio src={staticFile("s1-tone.wav")} />'), "public/s1-tone.wav": tone_wav()},
        {"src/Scene.tsx": scene_tsx(1, '<OffthreadVideo src={staticFile("s2-clip.mp4")} style={{width: 120}} />', throw=throw),
         "public/s2-clip.mp4": clip},
        {"src/Scene.tsx": scene_tsx(2, "<Panel />", 'import {Panel} from "./parts/Panel";'),
         "src/parts/Panel.tsx": 'import React from "react";\nimport {accent} from "../palette";\n'
                                'export const Panel = () => <div style={{width: 60, height: 30, background: accent}} />;\n',
         "src/palette.ts": 'export const accent = "#ffcc00";\n'},
    )
    created = await world.studio.create({"title": "Vidéo entière"})
    pid, vid = created.presentation.presentation_id, created.presentation.active_variant_id
    scenes = [{"scene_id": IDS[n], "prefab": {"id": PREFABS[n], "version": await publish(world, n, sources[n])}, "props": {"title": f"T{n}"}}
              for n in range(3)]
    variant = created.variants[0].to_document()
    await world.studio.save_variant(pid, vid, {"expected_revision": variant["revision"], "title": variant["title"], "scenes": scenes,
                                               "art_direction_id": None, "score_id": None})
    return (await world.freeze(pid, vid))["artifact_id"]


async def finished(service, job_id, timeout=600.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        view = service.get(job_id)
        if view["state"] in ("complete", "failed", "cancelled"):
            return view
        await asyncio.sleep(0.5)
    raise AssertionError(service.get(job_id))


def pixel(ffmpeg: Path, video: Path, frame: int, size: tuple[int, int]) -> tuple[int, int, int]:
    """The colour near the bottom-right corner of master frame `frame` (background only: no video, no panel there). Output seeking keeps
    the first frame whose timestamp is at or after `-ss`: a quarter frame before frame n's timestamp selects frame n."""

    raw = subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-i", str(video), "-ss", f"{max(0.0, (frame - 0.25) / FPS):.4f}",
                          "-frames:v", "1", "-c:v", "rawvideo", "-pix_fmt", "rgb24", "-f", "image2pipe", "-"],
                         capture_output=True, timeout=60, check=True).stdout
    w, h = size
    x, y = w - 6, h - 6
    offset = 3 * (y * w + x)
    return raw[offset], raw[offset + 1], raw[offset + 2]


async def test_a_frozen_three_scene_variant_renders_as_one_verified_video(tmp_path):
    root = runtime_root(tmp_path)
    runner = RemotionRenderRunner(lambda: root)
    assert runner.runtime_ready() is None
    world = await PresentationWorld().open(tmp_path / "world", runtime={"remotion_version": "4.0.534"})
    service = PresentationRenderService(artifacts=world.artifacts, snapshots=world.snapshots, packager=world.packager, runner=runner,
                                        installed_engine=runner.installed_engine, diagnostics=world.sink)
    try:
        clip = clip_mp4(runner)
        snapshot = await frozen_deck(world, clip)
        readiness = await service.master_readiness(snapshot)
        assert readiness["status"] == "ready" and readiness["composition"]["duration_in_frames"] == 105, readiness
        started = time.monotonic()
        queued = await service.submit(snapshot, "mp4", {"scope": "master", "scale": 0.5})
        done = await finished(service, queued["job_id"])
        elapsed = time.monotonic() - started
        assert done["state"] == "complete", (done["error_code"], done["error_detail"], done["log_tail"])
        artifact = await world.artifacts.get(done["artifact_id"])
        assert artifact.state is ArtifactState.COMPLETE and (artifact.width, artifact.height) == (W // 2, H // 2)
        meta = dict(artifact.metadata)
        assert meta["render_scope"] == "master" and meta["render_project_key"] == readiness["project_key"] and meta["render_scene_count"] == 3
        assert meta["render_verified_by"] == "ffprobe" and meta["render_sandbox"] is True
        video = Path(world.artifacts.payload_path(artifact))
        ffprobe, ffmpeg = compositor_tool(root, "ffprobe"), compositor_tool(root, "ffmpeg")
        probe = json.loads(subprocess.run([str(ffprobe), "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(video)],
                                          capture_output=True, text=True, timeout=60, check=True).stdout)
        v = next(s for s in probe["streams"] if s["codec_type"] == "video")
        audio = [s for s in probe["streams"] if s["codec_type"] == "audio"]
        assert int(v["nb_read_frames"]) == 105 and v["codec_name"] == "h264" and audio, probe["streams"]
        # boundaries: scene k at master frame from_k shows its LOCAL frame 0 (channel 40), its last frame 40 + 4 x (d - 1)
        checks = []
        start = 0
        for n, duration in enumerate(DURATIONS):
            for local in (0, duration - 1):
                rgb = pixel(ffmpeg, video, start + local, (W // 2, H // 2))
                expected = 40 + 4 * local
                checks.append((start + local, n + 1, local, rgb))
                assert abs(rgb[CHANNEL[n]] - expected) <= 14, (start + local, n, local, rgb)
                assert all(rgb[c] <= 24 for c in range(3) if c != CHANNEL[n]), (start + local, n, rgb)
            start += duration
        print(f"\nmaster export: 105 frames {v['width']}x{v['height']} h264 + {audio[0]['codec_name']} in {elapsed:.1f} s; boundaries {checks}")
    finally:
        await service.stop()
        await world.close()


async def test_a_scene_that_throws_fails_the_whole_video_naming_it(tmp_path):
    root = runtime_root(tmp_path)
    runner = RemotionRenderRunner(lambda: root)
    world = await PresentationWorld().open(tmp_path / "world", runtime={"remotion_version": "4.0.534"})
    service = PresentationRenderService(artifacts=world.artifacts, snapshots=world.snapshots, packager=world.packager, runner=runner,
                                        installed_engine=runner.installed_engine, diagnostics=world.sink)
    try:
        snapshot = await frozen_deck(world, clip_mp4(runner), throw=True)
        done = await finished(service, (await service.submit(snapshot, "mp4", {"scope": "master", "scale": 0.5}))["job_id"])
        assert done["state"] == "failed" and done["error_code"] == "presentation_render_master_scene_failed", (done["error_code"], done["error_detail"])
        assert done["error_detail"] == f"scene 2 ({IDS[1]}) failed while rendering: boom in the video scene", done["error_detail"]
        assert (await world.artifacts.get(done["artifact_id"])).state is ArtifactState.FAILED
        print(f"\nthrowing scene: {done['error_code']}: {done['error_detail']}")
    finally:
        await service.stop()
        await world.close()

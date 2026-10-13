"""Release journeys of the whole video, REAL (handoff jarvis-remotion-master-project-studio-export, Slice 09; `docs/remotion-master-project.md`).

Opt-in: `JARVIS_REMOTION_RUNTIME_DIR` (an installed Remotion runtime, read only: its `node_modules` is COPIED into a private data root), Node
and Chrome. `RemotionStack`: real Core, real Control Center, real `remotion studio` and real guarded render host, on free loopback ports with
a throw-away data root. The page is the real Control Center page in headless Chrome over CDP. The live Jarvis and the user's own Remotion
Studio are never contacted. One real Studio or render at a time.

1. `test_a_compatible_deck_opens_in_studio_exports_one_verified_video_and_survives_injected_failures`: a 4-scene deck (1920x1080 @ 30,
   30 + 45 + 30 + 45 frames; scene 1 plays an `<Audio>`, scene 2 an `<OffthreadVideo>`, scene 3 imports its own modules, each scene paints
   its own colour ramp from its LOCAL frame). From Variants: « Remotion Studio » opens the real Studio on `JarvisPresentation` (every scene
   seen by stepping), « Exporter la vidéo » renders one MP4 (ffprobe: 150 frames, 1920x1080, 30/1, h264 + aac; every boundary decoded).
   Injections, each visible and none mutating the canonical presentation and prefab files (hashed before and after): unpublished master
   Studio edits before a switch; Core outage while the master Studio is open; a repin between the plan and the export (the frozen snapshot
   wins, the stale body is refused); render browser unusable during the export and absent at the request; a scene that throws.
2. `test_an_incompatible_legacy_deck_is_refused_and_keeps_the_scene_path`: the gate's 9-scene mixed-fps deck: master readiness
   `master_fps_mismatch` with the § 3 sentence on the page, « Exporter la vidéo » refused, a whole-video export refused 409 with nothing
   frozen; « Lire » plays; the scene door opens the real Studio on the scene; a scene export renders.

With `JARVIS_MASTER_RELEASE_EVIDENCE_DIR`: `release-summary.json` / `legacy-summary.json` and a few half-scale PNGs, home path and user name
redacted.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import wave
import zlib

import pytest

from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.adapters.remotion_media_tools import compositor_tool
from jarvis.adapters.remotion_render_runner import RemotionRenderRunner
from jarvis.adapters.remotion_studio_runner import RemotionStudioRunner
from jarvis.domain.remotion_master_sentences import REASON_SENTENCES
from jarvis.domain.remotion_source import Composition
from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.fakes.remotion_scene import scene_candidate
from tests.unit.presentation_playback_gate_world import BASE, VSTATE, gesture, harness, make_deck, redact, run_long
from tests.unit.test_remotion_master_files_real import clip_mp4, tone_wav
from tests.unit.test_remotion_studio_roundtrip_real_browser import private_runtime_copy
from tests.unit.test_variants_master_entrypoints_browser import (CONFIRM, DIALOG, DOOR, EXPLORER, EXPORT, MASTER_LINE, MASTER_READY, RMS_STATE,
                                                                  RMS_TEXT, SCENE_DOOR, VX_TEXT, X, keep_shots, open_plan, shot)

RUNTIME = runtime_dir_from_env()
pytestmark = [pytest.mark.asyncio,
              pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                 reason="needs JARVIS_REMOTION_RUNTIME_DIR (an installed Remotion runtime), node and Chrome")]

STUDIO = "/v1/local-capabilities/remotion/studio"
RENDER = "/v1/local-capabilities/remotion/render/jobs"
W, H, FPS = 1920, 1080, 30
DURATIONS = (30, 45, 30, 45)
#: channels each scene ramps from its LOCAL frame (value 40 + 4 x local): R, G, B, then R+B
CHANNELS = ((0,), (1,), (2,), (0, 2))
PREFABS = [f"presentation-studio.p0000000000d9.s{n:012d}" for n in range(1, 5)]
SCENE_IDS = [f"pss_d{n:011d}" for n in range(1, 5)]
BOOM_PREFABS = [f"presentation-studio.p0000000000da.s{n:012d}" for n in range(1, 3)]
BOOM_IDS = [f"pss_e{n:011d}" for n in range(1, 3)]
PROPS = {"type": "object", "properties": {"title": {"type": "string", "default": "d", "max_length": 40}}}
TEXT = "document.body.innerText"
#: The Remotion Studio line as SHOWN (its text node keeps its last words while hidden, so `textContent` alone is not what the user sees).
RMS_SHOWN = f"((e=>e&&!e.hidden&&e.offsetParent!==null?e.textContent:'')(document.querySelector('{X} .jvx-rms-text')))"
VX_CODE = f"((document.querySelector('{X} .jvx-vx-code')||{{}}).textContent||'')"


def scene_tsx(channels: tuple[int, ...], body: str = "", imports: str = "", throw: bool = False) -> str:
    rgb = ["0", "0", "0"]
    for channel in channels:
        rgb[channel] = "${40 + frame * 4}"
    boom = '\n  if (frame >= 3) throw new Error("boom in the second scene");' if throw else ""
    return f'''import React from "react";
import {{AbsoluteFill, Audio, OffthreadVideo, staticFile, useCurrentFrame}} from "remotion";
{imports}
export default function Scene(props: {{title: string}}) {{
  const frame = useCurrentFrame();{boom}
  return (
    <AbsoluteFill style={{{{background: `rgb({", ".join(rgb)})`}}}}>
      <p style={{{{color: "#ffffff", fontSize: 72, margin: 64}}}}>{{props.title}}</p>
      {body}
    </AbsoluteFill>
  );
}}
'''


def sources(clip: bytes) -> list[dict]:
    return [
        {"src/Scene.tsx": scene_tsx(CHANNELS[0], '<Audio src={staticFile("rel-s1-tone.wav")} />'), "public/rel-s1-tone.wav": tone_wav()},
        {"src/Scene.tsx": scene_tsx(CHANNELS[1], '<OffthreadVideo src={staticFile("rel-s2-clip.mp4")} style={{width: 480}} />'),
         "public/rel-s2-clip.mp4": clip},
        {"src/Scene.tsx": scene_tsx(CHANNELS[2], "<Panel />", 'import {Panel} from "./parts/Panel";'),
         "src/parts/Panel.tsx": 'import React from "react";\nimport {accent} from "../palette";\n'
                                'export const Panel = () => <div style={{width: 320, height: 120, background: accent}} />;\n',
         "src/palette.ts": 'export const accent = "#ffcc00";\n'},
        {"src/Scene.tsx": scene_tsx(CHANNELS[3])},
    ]


async def publish(stack: RemotionStack, prefab_id: str, files: dict, duration: int) -> int:
    candidate = scene_candidate(prefab_id, engine=shipped_engine_pin(), files=files, composition=Composition("Scene", W, H, FPS, duration),
                                props=PROPS, sample={"props": {"title": "d"}, "data": {}})
    return (await stack.core.prefabs.save(candidate, actor="user")).version


async def deck(stack: RemotionStack, title: str, scenes: list[dict]) -> tuple[str, str, int]:
    _, created = await stack.call("POST", BASE, json={"title": title})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    status, saved = await stack.call("PUT", f"{BASE}/{pid}/variants/{variant['variant_id']}", json={
        "expected_revision": variant["revision"], "title": variant["title"], "scenes": scenes,
        "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"]})
    harness(status == 200, f"variant save refused: {saved}")
    return pid, variant["variant_id"], saved["revision"]


def canonical(root: Path) -> dict[str, str]:
    """SHA-256 of every presentation-store and prefab-store file of the data root (the canonical data an injection must not touch)."""

    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or rel.startswith("local_capabilities/"):
            continue
        parts = rel.split("/")
        if "presentations" in parts or "prefabs" in parts:
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def master_body(pid: str, vid: str, key: str, **extra) -> dict:
    return {"kind": "variant_master", "presentation_id": pid, "variant_id": vid, "project_key": key, "acknowledge_unsandboxed_project": True,
            **extra}


async def studio_post(stack: RemotionStack, action: str, body: dict, report: dict) -> tuple[int, dict]:
    """POST a Studio action; a `remotion_studio_busy` 409 (the status read holds the service lock a moment) is retried and counted."""

    for _ in range(40):
        status, answer = await stack.call("POST", f"{STUDIO}/{action}", json=body)
        if not (status == 409 and (answer.get("error") or {}).get("code") == "remotion_studio_busy"):
            return status, answer
        report["studio_busy_retries"] = report.get("studio_busy_retries", 0) + 1
        await asyncio.sleep(0.5)
    return status, answer


async def revisions(stack: RemotionStack, pid: str, vid: str) -> tuple[int, int]:
    _, view = await stack.call("GET", f"{BASE}/{pid}")
    _, variant = await stack.call("GET", f"{BASE}/{pid}/variants/{vid}")
    return view["presentation"]["revision"], variant["revision"]


async def job_done(stack: RemotionStack, job_id: str, timeout: float = 600.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        _, read = await stack.call("GET", f"{RENDER}/{job_id}")
        if read["job"]["state"] in ("complete", "failed", "cancelled"):
            return read["job"]
        await asyncio.sleep(1.0)
    raise AssertionError(f"render job {job_id} did not finish")


def export_plan(pid: str, raw: Path, name: str) -> list[dict]:
    """The page's « Exporter la vidéo » to its end (done or failed), the line, its small print and the job."""

    return open_plan(pid) + [
        {"until": MASTER_READY, "ms": 30000, "required": True, "as": "master_read"},
        {"click": EXPORT},
        {"until": f"{VX_TEXT}.startsWith('Vidéo entière exportée')||{VX_TEXT}.includes('échoué')||{VX_CODE}.length>0", "ms": 500000, "as": "done"},
        {"wait": 500}, {"value": "done_text", "expr": VX_TEXT}, {"value": "code", "expr": VX_CODE},
        {"value": "job", "expr": f"JSON.stringify({EXPLORER}.videoExport.state().job)"}, shot(raw, name)]


def probe(root: Path, video: Path) -> dict:
    ffprobe = compositor_tool(root, "ffprobe")
    return json.loads(subprocess.run([str(ffprobe), "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(video)],
                                     capture_output=True, text=True, timeout=120, check=True).stdout)


def pixel(ffmpeg: Path, video: Path, frame: int) -> tuple[int, int, int]:
    """Colour near the bottom-right corner of master frame `frame` (background only). A quarter frame before frame n selects frame n."""

    raw = subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, (frame - 0.25) / FPS):.4f}", "-i", str(video),
                          "-frames:v", "1", "-vf", f"crop=8:8:{W - 12}:{H - 12}", "-c:v", "rawvideo", "-pix_fmt", "rgb24", "-f", "image2pipe", "-"],
                         capture_output=True, timeout=60, check=True).stdout
    px = [raw[i:i + 3] for i in range(0, len(raw), 3)]
    return tuple(round(sum(p[c] for p in px) / len(px)) for c in range(3))  # type: ignore[return-value]


def mean_volume(ffmpeg: Path, video: Path, start: float, length: float) -> float | None:
    """RMS level in dBFS of the audio between `start` and `start + length` s (decoded to a mono 16-bit WAV and measured here: the pinned
    compositor ffmpeg has no `volumedetect` and no raw PCM muxer). None when nothing decodes; -inf for digital silence."""

    target = Path(tempfile.mkdtemp(prefix="jq-level-")) / "level.wav"
    subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start}", "-t", f"{length}", "-i", str(video), "-vn",
                    "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le", "-f", "wav", str(target)], capture_output=True, timeout=60, check=False)
    if not target.is_file():
        return None
    with wave.open(str(target), "rb") as level:
        pcm = level.readframes(level.getnframes())
    target.unlink()
    count = len(pcm) // 2
    if count == 0:
        return None
    samples = struct.unpack(f"<{count}h", pcm[:count * 2])
    rms = math.sqrt(sum(v * v for v in samples) / count)
    return float("-inf") if rms == 0 else round(20 * math.log10(rms / 32768), 1)


def contact_sheet(ffmpeg: Path, video: Path, frames: list[int], target: Path, size: tuple[int, int] = (240, 135)) -> None:
    """The boundary frames side by side, 4 per row (one small PNG). The pinned compositor ffmpeg has few filters and encoders: each frame
    is decoded scaled to raw RGB and the sheet is encoded here."""

    w, h = size
    tiles = []
    for frame in frames:
        tiles.append(subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, (frame - 0.25) / FPS):.4f}",
                                     "-i", str(video), "-frames:v", "1", "-vf", f"scale={w}:{h}", "-c:v", "rawvideo", "-pix_fmt", "rgb24",
                                     "-f", "image2pipe", "-"], capture_output=True, timeout=60, check=True).stdout)
    cols, gap = 4, 4
    rows = (len(tiles) + cols - 1) // cols
    width, height = cols * w + (cols - 1) * gap, rows * h + (rows - 1) * gap
    lines = []
    for y in range(height):
        row, ty = bytearray(b"\x00"), y // (h + gap)
        for x_tile in range(cols):
            index, local = ty * cols + x_tile, y - ty * (h + gap)
            if index < len(tiles) and local < h:
                row += tiles[index][local * w * 3:(local + 1) * w * 3]
            else:
                row += b"\xff" * (w * 3)
            if x_tile < cols - 1:
                row += b"\xff" * (gap * 3)
        lines.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    target.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                       + chunk(b"IDAT", zlib.compress(b"".join(lines), 9)) + chunk(b"IEND", b""))


def _head() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()


def evidence() -> Path | None:
    raw = os.environ.get("JARVIS_MASTER_RELEASE_EVIDENCE_DIR")
    if not raw:
        return None
    folder = Path(raw)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


#: A drive-letter path in any JSON spelling (raw, escaped, nested) or a forward-slash one.
DRIVE_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:(?:\\+|/)[^\"\s]{0,80}")


def path_leaks(payloads: dict, *roots: Path) -> dict[str, list[str]]:
    """Machine paths found in route answers (`{name: [hit, ...]}` for the names that hold one): a drive-letter path, or a root of this run
    (data root, temp folder, home) in any spelling. Hits are recorded redacted by `write_summary`."""

    forms = set()
    for root in (*roots, Path.home()):
        raw = str(root)
        forms |= {raw, raw.replace("\\", "/"), raw.replace("\\", "\\\\"), raw.lower()}
    leaks = {}
    for name, payload in payloads.items():
        text = json.dumps(payload, ensure_ascii=False)
        hits = sorted({m.group(0)[:80] for m in DRIVE_PATH.finditer(text)} | {f for f in forms if f and f in text})
        if hits:
            leaks[name] = hits
    return leaks


def write_summary(folder: Path | None, name: str, report: dict) -> None:
    if folder is not None:
        (folder / name).write_text(redact(json.dumps(report, indent=1, ensure_ascii=False, default=str)), encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------- 1. compatible deck

@asynccontextmanager
async def _compatible(tmp_path, journey: str):
    """The compatible stack of journeys A1 and A2: yields `(stack, world, report, raw, render_env)`."""

    folder = evidence()
    raw = tmp_path / "shots"
    raw.mkdir()
    report: dict = {"slice": "09-release-and-human-acceptance", "tested_head": _head(), "durations_ms": {}, "journey": journey, "injections": {},
                    "runtime": "RemotionStack (real Core, real Control Center, real remotion studio, real guarded render host) on free loopback "
                               "ports, throw-away data root, private copy of the gate runtime's node_modules, headless Chrome over CDP; the live "
                               "Jarvis and the user's own Remotion Studio were never contacted"}
    started = time.monotonic()
    private_runtime_copy(tmp_path)
    report["durations_ms"]["private_runtime_copy"] = round((time.monotonic() - started) * 1000)
    render_env = dict(os.environ)  # the render runner's environment, changed in place by the browser injection

    def options(stack) -> dict:
        runtime = lambda: stack.data_root / "local_capabilities" / "remotion" / "runtime"  # noqa: E731 - the runners take a root factory
        return {"remotion_studio_runner": RemotionStudioRunner(runtime), "remotion_render_runner": RemotionRenderRunner(runtime, environ=render_env)}

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME, core_options=options) as stack:
        runtime_root = stack.data_root / "local_capabilities" / "remotion" / "runtime"
        ffmpeg = compositor_tool(runtime_root, "ffmpeg")
        clip = clip_mp4(RemotionRenderRunner(lambda: runtime_root))
        files = sources(clip)
        scenes = []
        for n in range(4):
            version = await publish(stack, PREFABS[n], files[n], DURATIONS[n])
            scenes.append({"scene_id": SCENE_IDS[n], "prefab": {"id": PREFABS[n], "version": version}, "title": f"SCENE-{n + 1}",
                           "props": {"title": f"SCENE-{n + 1}"}, "data": {}})
        pid, vid, revision = await deck(stack, "Release S09", scenes)
        boom = []
        for n in range(2):
            version = await publish(stack, BOOM_PREFABS[n], {"src/Scene.tsx": scene_tsx(CHANNELS[n], throw=n == 1)}, 30)
            boom.append({"scene_id": BOOM_IDS[n], "prefab": {"id": BOOM_PREFABS[n], "version": version}, "title": f"BOOM-{n + 1}",
                         "props": {"title": f"BOOM-{n + 1}"}, "data": {}})
        pid_boom, vid_boom, _ = await deck(stack, "Boom S09", boom)
        status, read = await stack.call("GET", f"{BASE}/{pid}/variants/{vid}/master-project")
        harness(status == 200 and read["master"]["status"] == "ready", f"master not ready: {status} {read}")
        plan = read["master"]
        key = plan["project_key"]
        assert plan["composition"] == {"id": "JarvisPresentation", "width": W, "height": H, "fps": FPS, "duration_in_frames": sum(DURATIONS)}
        report["plan"] = {k: plan[k] for k in ("status", "project_key", "composition", "totals")} | {
            "scenes": [{k: s[k] for k in ("scene_id", "from_frame", "duration_in_frames", "mount")} for s in plan["scenes"]],
            "public_assets": [{k: a[k] for k in ("path", "bytes", "scene_ids")} for a in plan["public_assets"]]}
        h0 = canonical(stack.data_root)
        report["canonical_files"] = {"count": len(h0), "roots": sorted({k.split("/")[0] for k in h0})}
        harness(h0, "no canonical file found to hash")

        report["outcome"] = "failed"
        try:
            yield stack, dict(pid=pid, vid=vid, key=key, scenes=scenes, files=files, pid_boom=pid_boom, vid_boom=vid_boom, h0=h0,
                              runtime_root=runtime_root, ffmpeg=ffmpeg), report, raw, render_env
            report["outcome"] = "passed"
        finally:
            report["screenshots"] = keep_shots(raw, folder)
            write_summary(folder, f"release-{journey}-summary.json", report)


async def test_a1_the_whole_video_opens_in_real_studio_from_variants_and_survives_unpublished_edits_and_a_core_outage(tmp_path):
    async with _compatible(tmp_path, "studio") as (stack, w, report, raw, render_env):
        pid, vid, key, scenes, files = (w[k] for k in ("pid", "vid", "key", "scenes", "files"))
        pid_boom, vid_boom, h0, runtime_root, ffmpeg = (w[k] for k in ("pid_boom", "vid_boom", "h0", "runtime_root", "ffmpeg"))
        # A1. Variants « Remotion Studio » -> the real remotion studio on the whole video
        started = time.monotonic()
        result = await run_long(stack.page_url, open_plan(pid) + [
            {"until": MASTER_READY, "ms": 30000, "required": True, "as": "master_read"}, {"value": "master_line", "expr": MASTER_LINE},
            {"click": DOOR}, {"until": f"!!{DIALOG}", "ms": 15000, "required": True, "as": "dialog"},
            {"value": "dialog", "expr": f"{DIALOG}.innerText"}, {"click": CONFIRM},
            {"until": f"{RMS_STATE}.studio && {RMS_STATE}.studio.status==='ready' && !{RMS_STATE}.busy", "ms": 240000, "as": "studio_ready"},
            {"value": "status", "expr": RMS_TEXT}, {"value": "studio", "expr": f"JSON.stringify({RMS_STATE}.studio)"}], timeout=420)
        report["durations_ms"]["studio_open_from_page"] = round((time.monotonic() - started) * 1000)
        reads = result["reads"]
        harness(not reads.get("failed") and reads.get("studio_ready"), f"Remotion Studio did not open the master: {reads}")
        studio = json.loads(reads["studio"])
        assert studio["target"]["kind"] == "variant_master" and studio["target"]["scene_count"] == 4, studio
        assert "4 scènes vont tourner hors du bac à sable" in reads["dialog"], reads["dialog"]
        assert "4 scènes" in reads["master_line"], reads["master_line"]
        work = runtime_root / "studio" / "work"
        mounted = sorted(p.relative_to(work).as_posix() for p in (work / "src").rglob("*") if p.is_file())
        assert {f"src/scenes/{s}/Scene.tsx" for s in SCENE_IDS} <= set(mounted), mounted
        page = [{"until": f"{TEXT}.includes('JarvisPresentation')", "ms": 150000, "required": True, "as": "composition_listed"},
                {"until": f"{TEXT}.includes('SCENE-1')", "ms": 60000, "required": True, "as": "scene1"}, {"wait": 1000},
                {"value": "text_at_open", "expr": f"{TEXT}.slice(0,1500)"}, shot(raw, "studio-master")]
        for n, presses in ((2, 1), (3, 2), (4, 1)):   # one Shift+→ = one second (30 frames): frame 30, 90, 120
            page += [{"eval": "window.focus()"}] + [{"key": "ArrowRight", "shift": True} for _ in range(presses)]
            page += [{"until": f"{TEXT}.includes('SCENE-{n}')", "ms": 20000, "as": f"scene{n}"}]
        studio_page = await run_long(studio["url"] + "JarvisPresentation", page, timeout=400)
        sreads = studio_page["reads"]
        harness("failed" not in sreads, sreads.get("failed"))
        assert all(sreads.get(f"scene{n}") for n in (1, 2, 3, 4)), {k: sreads.get(k) for k in ("scene1", "scene2", "scene3", "scene4")}
        assert "00:05.00" in sreads["text_at_open"] or "150" in sreads["text_at_open"], sreads["text_at_open"]
        report["studio"] = {"target": studio["target"], "status_line": reads["status"], "master_line": reads["master_line"],
                            "scenes_seen_by_stepping": [n for n in (1, 2, 3, 4) if sreads.get(f"scene{n}")],
                            "mounted": [p for p in mounted if p.endswith("Scene.tsx") or p.startswith("src/master/")],
                            "console_errors": [line for line in studio_page["console"] if line.startswith("error")][:5]}
        assert changed(h0, canonical(stack.data_root)) == [], "opening the master Studio writes no canonical file"

        # C4. unpublished master Studio files before a switch: refused without discard, set aside with it, never overwritten
        edited = work / "src" / "scenes" / SCENE_IDS[1] / "Scene.tsx"
        edited.write_text(edited.read_text("utf-8").replace("props.title", '"EDITED " + props.title'), encoding="utf-8")
        (work / "remotion.config.ts").write_text("// a shared top-level edit\n", encoding="utf-8")
        _, boom_plan = await stack.call("GET", f"{BASE}/{pid_boom}/variants/{vid_boom}/master-project")
        boom_key = boom_plan["master"]["project_key"]
        status, refused = await studio_post(stack, "sync", master_body(pid_boom, vid_boom, boom_key), report)
        assert status == 409 and refused["error"]["code"] == "remotion_studio_unpublished_edits", refused
        classes = sorted((c["path"], c["class"]) for c in refused["error"]["classified"])
        assert classes == [("remotion.config.ts", "shared"), (f"src/scenes/{SCENE_IDS[1]}/Scene.tsx", "scene")], classes
        assert "EDITED " in edited.read_text("utf-8") and (work / "remotion.config.ts").exists(), "a refusal overwrites nothing"
        _, still = await stack.call("GET", STUDIO)
        assert still["studio"]["target"]["project_key"] == key, "the refused switch left the master open"
        status, set_aside = await studio_post(stack, "sync", master_body(pid_boom, vid_boom, boom_key, discard_unpublished=True), report)
        assert status == 200 and set_aside["studio"]["target"]["project_key"] == boom_key, set_aside
        edits_root = runtime_root.parent / "studio-edits"
        saved_edits = sorted(p.relative_to(edits_root).as_posix() for p in edits_root.rglob("*") if p.is_file())
        assert any(p.endswith(f"{SCENE_IDS[1]}/Scene.tsx") for p in saved_edits) and any(p.endswith("remotion.config.ts") for p in saved_edits), saved_edits
        assert changed(h0, canonical(stack.data_root)) == [], "unpublished master edits never reach the canonical data"
        status, back = await studio_post(stack, "open", master_body(pid, vid, key), report)
        assert status == 200 and back["studio"]["target"]["project_key"] == key, back
        report["injections"]["unpublished_master_edits"] = {
            "refusal": {"status": 409, "code": refused["error"]["code"], "classified": classes},
            "with_discard": {"target_key": boom_key, "work_copy": set_aside["studio"]["work_copy"], "set_aside": saved_edits},
            "canonical_changed": []}

        # C1. Core outage while the master Studio is open: the page says it, Core comes back, nothing canonical moves
        state_file = runtime_root / "studio" / "state.json"
        page_task = asyncio.create_task(run_long(stack.page_url, open_plan(pid) + [
            {"until": f"{RMS_STATE}.studio && {RMS_STATE}.studio.status==='ready' && ({RMS_STATE}.studio.target||{{}}).kind==='variant_master'",
             "ms": 60000, "required": True, "as": "studio_seen"},
            {"value": "line_before", "expr": RMS_SHOWN},
            {"until": f"!!{RMS_STATE}.readError", "ms": 150000, "as": "outage_seen"}, {"wait": 500},
            {"value": "line_outage", "expr": RMS_SHOWN}, {"value": "read_error", "expr": f"JSON.stringify({RMS_STATE}.readError)"},
            {"value": "unreachable_notices", "expr": "(document.body.innerText.match(/[^\\n]*injoignable[^\\n]*/g)||[]).slice(0,4)"},
            shot(raw, "core-outage"),
            {"until": f"!{RMS_STATE}.readError && !!{RMS_STATE}.studio", "ms": 150000, "as": "recovered"}, {"wait": 500},
            {"value": "line_after", "expr": RMS_SHOWN}, {"value": "studio_after", "expr": f"JSON.stringify({RMS_STATE}.studio)"},
            {"until": f"!{RMS_SHOWN}.includes('est ouvert')", "ms": 30000, "as": "settled"}, {"wait": 500},
            {"value": "line_settled", "expr": RMS_SHOWN}, {"value": "studio_settled", "expr": f"JSON.stringify({RMS_STATE}.studio)"}], timeout=420))
        await asyncio.sleep(60)
        studio_port = back["studio"]["port"]
        await stack.stop_core()
        await asyncio.sleep(3)
        listening = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False).stdout
        studio_alive_after_core_stop = any(f":{studio_port} " in line and "LISTENING" in line for line in listening.splitlines())
        state_during = json.loads(state_file.read_text("utf-8")) if state_file.exists() else None
        await asyncio.sleep(25)
        await stack.start_core()
        outage = await page_task
        oreads = outage["reads"]
        _, after_status = await stack.call("GET", STUDIO)
        report["injections"]["core_outage_with_master_studio_open"] = {
            "page": {k: oreads.get(k) for k in ("studio_seen", "line_before", "outage_seen", "line_outage", "read_error", "unreachable_notices",
                                                "recovered", "line_after", "settled", "line_settled")},
            "studio_process_listening_after_core_stop": studio_alive_after_core_stop,
            "state_json_during_outage": None if state_during is None else {"schema": state_during.get("schema"),
                                                                             "target_kind": (state_during.get("target") or {}).get("kind")},
            "studio_after_core_restart": {k: after_status["studio"].get(k) for k in ("status", "target")},
            "canonical_changed": changed(h0, canonical(stack.data_root))}
        harness(oreads.get("studio_seen"), f"the page never saw the master Studio: {oreads}")
        assert oreads.get("outage_seen"), f"the Core outage was not said on the page: {oreads}"
        assert changed(h0, canonical(stack.data_root)) == []
        _, plan_view = await stack.call("GET", f"{BASE}/{pid}/variants/{vid}/master-project")
        report["path_probe"] = path_leaks({"master_project": plan_view, "studio_status": after_status, "studio_open": back,
                                           "unpublished_refusal": refused, "unpublished_set_aside": set_aside}, stack.data_root, tmp_path)
        assert report["path_probe"] == {}, "Studio and master-project answers carry no machine path"
        await studio_post(stack, "close", {}, report)



async def test_a2_the_whole_video_exports_one_verified_mp4_from_variants_and_render_failures_are_typed(tmp_path):
    async with _compatible(tmp_path, "export") as (stack, w, report, raw, render_env):
        pid, vid, key, scenes, files = (w[k] for k in ("pid", "vid", "key", "scenes", "files"))
        pid_boom, vid_boom, h0, runtime_root, ffmpeg = (w[k] for k in ("pid_boom", "vid_boom", "h0", "runtime_root", "ffmpeg"))
        # A2. Variants « Exporter la vidéo » -> one whole-video MP4, verified
        started = time.monotonic()
        result = await run_long(stack.page_url, export_plan(pid, raw, "export-done"), timeout=600)
        report["durations_ms"]["export_from_page"] = round((time.monotonic() - started) * 1000)
        reads = result["reads"]
        harness(reads.get("done") and reads["done_text"].startswith("Vidéo entière exportée"), f"export did not finish: {reads}")
        job = json.loads(reads["job"])
        artifact = await stack.core.artifacts.get(job["artifact_id"])
        meta = dict(artifact.metadata)
        assert meta["render_scope"] == "master" and meta["render_scene_count"] == 4 and meta["render_project_key"] == key, meta
        assert meta["render_composition"] == "JarvisPresentation" and artifact.kind.value == "presentation_video"
        video = Path(stack.core.artifacts.payload_path(artifact))
        facts = probe(runtime_root, video)
        v = next(s for s in facts["streams"] if s["codec_type"] == "video")
        a = [s for s in facts["streams"] if s["codec_type"] == "audio"]
        assert (int(v["width"]), int(v["height"]), v["r_frame_rate"], v["codec_name"]) == (W, H, "30/1", "h264"), v
        assert int(v["nb_read_frames"]) == sum(DURATIONS) and a and a[0]["codec_name"] == "aac", facts["streams"]
        assert abs(float(facts["format"]["duration"]) - sum(DURATIONS) / FPS) < 0.1, facts["format"]
        boundaries, start = [], 0
        for n, duration in enumerate(DURATIONS):
            for local in (0, duration - 1):
                rgb = pixel(ffmpeg, video, start + local)
                expected = 40 + 4 * local
                ok = all(abs(rgb[c] - expected) <= 16 for c in CHANNELS[n]) and all(rgb[c] <= 24 for c in range(3) if c not in CHANNELS[n])
                boundaries.append({"master_frame": start + local, "scene": n + 1, "local_frame": local, "rgb": rgb, "expected_channel": expected,
                                   "ok": ok})
            start += duration
        assert all(b["ok"] for b in boundaries), boundaries
        sheet = raw / "boundaries-000.png"
        contact_sheet(ffmpeg, video, [b["master_frame"] for b in boundaries], sheet)
        loud, quiet = mean_volume(ffmpeg, video, 0.0, 0.9), mean_volume(ffmpeg, video, 2.0, 3.0)
        assert loud is not None and loud > -45 and (quiet is None or quiet < loud - 20), (loud, quiet)
        report["export"] = {"line": reads["done_text"], "artifact_kind": artifact.kind.value, "size_bytes": video.stat().st_size,
                            "metadata": {k: meta.get(k) for k in ("render_scope", "render_project_key", "render_scene_count", "render_composition",
                                                                 "render_width", "render_height", "render_fps", "render_verified_by", "render_sandbox")},
                            "ffprobe": {"video": {k: v.get(k) for k in ("codec_name", "width", "height", "r_frame_rate", "nb_read_frames")},
                                        "audio": {k: a[0].get(k) for k in ("codec_name", "sample_rate", "channels")},
                                        "duration_s": facts["format"]["duration"]},
                            "boundaries": boundaries, "mean_volume_db": {"0.0-0.9 s (scene 1, <Audio>)": loud, "2.0-5.0 s": quiet},
                            "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest()}
        assert changed(h0, canonical(stack.data_root)) == [], "an export freezes a snapshot; it never rewrites the presentation or a prefab"

        # C3. a repin between the plan and the export: the frozen snapshot wins; a stale body is refused
        p_rev, v_rev = await revisions(stack, pid, vid)
        status, queued = await stack.call("POST", RENDER, json={
            "presentation_id": pid, "variant_id": vid, "expected_presentation_revision": p_rev, "expected_variant_revision": v_rev,
            "format": "mp4", "settings": {"scope": "master", "frame_start": 60, "frame_end": 89, "scale": 0.25}})
        assert status == 202, queued
        v3 = await publish(stack, PREFABS[2], {**files[2], "src/palette.ts": 'export const accent = "#00ffcc";\n'}, DURATIONS[2])
        repinned = [dict(s) for s in scenes]
        repinned[2] = {**repinned[2], "prefab": {"id": PREFABS[2], "version": v3}}
        _, variant_doc = await stack.call("GET", f"{BASE}/{pid}/variants/{vid}")
        status, saved = await stack.call("PUT", f"{BASE}/{pid}/variants/{vid}", json={
            "expected_revision": variant_doc["revision"], "title": variant_doc["title"], "scenes": repinned,
            "art_direction_id": variant_doc["art_direction_id"], "score_id": variant_doc["score_id"]})
        assert status == 200, saved
        _, live = await stack.call("GET", f"{BASE}/{pid}/variants/{vid}/master-project")
        new_key = live["master"]["project_key"]
        assert new_key != key
        frozen = await job_done(stack, queued["job"]["job_id"])
        assert frozen["state"] == "complete", frozen
        frozen_meta = dict((await stack.core.artifacts.get(frozen["artifact_id"])).metadata)
        assert frozen_meta["render_project_key"] == key, "the job renders the snapshot frozen before the repin"
        h1 = canonical(stack.data_root)
        status, stale_export = await stack.call("POST", RENDER, json={
            "presentation_id": pid, "variant_id": vid, "expected_presentation_revision": p_rev, "expected_variant_revision": v_rev,
            "format": "mp4", "settings": {"scope": "master"}})
        assert status == 409 and stale_export["error"]["code"] == "presentation_studio_stale_revision", stale_export
        status, stale_studio = await studio_post(stack, "open", master_body(pid, vid, key), report)
        assert status == 409 and stale_studio["error"]["code"] == "remotion_studio_master_stale", stale_studio
        assert stale_studio["error"]["project_key"] == new_key
        _, jobs = await stack.call("GET", RENDER)
        assert changed(h1, canonical(stack.data_root)) == []
        report["injections"]["repin_between_plan_and_export"] = {
            "key_before": key, "key_after_repin": new_key, "job_frozen_before_repin": {"state": frozen["state"],
                                                                                   "render_project_key": frozen_meta["render_project_key"]},
            "stale_export": {"status": 409, "code": stale_export["error"]["code"]},
            "stale_studio_open": {"status": 409, "code": stale_studio["error"]["code"], "current_project_key": stale_studio["error"]["project_key"]},
            "jobs_total_after_refusals": len(jobs["jobs"]),
            "canonical_changed_by_the_refusals": [],
            "note": "the repin itself is a deliberate user save (variant revision + 1, scene 3 -> v%d); a re-read package whose key differs from "
                    "the plan's is refused presentation_render_snapshot_invalid (unit: test_presentation_render_master.py)" % v3}

        # C2. render browser unusable during the export (job fails, said on the page) and absent at the request (refused, typed)
        render_env["JARVIS_REMOTION_RENDER_BROWSER"] = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "where.exe")
        result = await run_long(stack.page_url, export_plan(pid, raw, "browser-failed"), timeout=600)
        breads = result["reads"]
        bjob = json.loads(breads["job"]) if breads.get("job") not in (None, "null") else {}
        assert "échoué" in breads.get("done_text", "") or breads.get("code"), breads
        render_env["JARVIS_REMOTION_RENDER_BROWSER"] = str(tmp_path / "no-such-browser.exe")
        p_rev, v_rev = await revisions(stack, pid, vid)
        status, absent = await stack.call("POST", RENDER, json={
            "presentation_id": pid, "variant_id": vid, "expected_presentation_revision": p_rev, "expected_variant_revision": v_rev,
            "format": "mp4", "settings": {"scope": "master"}})
        render_env.pop("JARVIS_REMOTION_RENDER_BROWSER")
        assert status >= 400 and absent["error"]["code"] == "presentation_render_browser_unavailable", (status, absent)
        assert changed(h1, canonical(stack.data_root)) == []
        report["injections"]["render_browser_unavailable"] = {
            "during_export": {"line": breads.get("done_text"), "code": breads.get("code"), "job_state": bjob.get("state"),
                              "error_code": bjob.get("error_code")},
            "at_request": {"status": status, "code": absent["error"]["code"], "message": absent["error"].get("message")},
            "canonical_changed": []}

        # C5. a scene that throws during the whole-video export: typed failure naming the scene, said on the page
        result = await run_long(stack.page_url, export_plan(pid_boom, raw, "throwing-scene"), timeout=600)
        treads = result["reads"]
        tjob = json.loads(treads["job"]) if treads.get("job") not in (None, "null") else {}
        assert "échoué" in treads.get("done_text", ""), treads
        assert "presentation_render_master_scene_failed" in treads.get("code", "") and BOOM_IDS[1] in treads.get("code", ""), treads
        assert changed(h1, canonical(stack.data_root)) == []
        report["injections"]["throwing_scene"] = {"line": treads.get("done_text"), "code": treads.get("code"),
                                                  "job_state": tjob.get("state"), "error_code": tjob.get("error_code"), "canonical_changed": []}
        _, all_jobs = await stack.call("GET", RENDER)
        _, readiness = await stack.call("GET", f"/v1/local-capabilities/remotion/render/master?snapshot_id={frozen['snapshot_id']}")
        report["path_probe"] = path_leaks({"render_jobs": all_jobs, "render_master_readiness": readiness, "stale_export": stale_export,
                                           "stale_studio_open": stale_studio, "browser_absent": absent}, stack.data_root, tmp_path)
        report["path_probe_jobs"] = [{k: j.get(k) for k in ("state", "scope", "error_code", "log_tail")} for j in all_jobs["jobs"]]
        assert readiness.get("master", readiness).get("status") == "ready", readiness
        assert report["path_probe"] == {}, "render answers carry no machine path"


# ---------------------------------------------------------------------------------------------------------------- 2. legacy deck

async def test_an_incompatible_legacy_deck_is_refused_and_keeps_the_scene_path(tmp_path):
    folder = evidence()
    raw = tmp_path / "shots"
    raw.mkdir()
    report: dict = {"slice": "09-release-and-human-acceptance", "tested_head": _head(), "durations_ms": {},
                    "runtime": "RemotionStack (real Core, real Control Center, real remotion studio, real guarded render host), throw-away data "
                               "root, headless Chrome over CDP; the live Jarvis was never contacted"}
    private_runtime_copy(tmp_path)

    def options(stack) -> dict:
        runtime = lambda: stack.data_root / "local_capabilities" / "remotion" / "runtime"  # noqa: E731
        return {"remotion_studio_runner": RemotionStudioRunner(runtime), "remotion_render_runner": RemotionRenderRunner(runtime)}

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME, core_options=options) as stack:
        pid, vid = await make_deck(stack, title="Ancienne neuf scenes")
        status, read = await stack.call("GET", f"{BASE}/{pid}/variants/{vid}/master-project")
        assert status == 200 and read["master"]["status"] == "incompatible" and read["master"]["reason"] == "master_fps_mismatch", read
        sentence = REASON_SENTENCES["master_fps_mismatch"]
        h0 = canonical(stack.data_root)
        p_rev, v_rev = await revisions(stack, pid, vid)
        status, refused = await stack.call("POST", RENDER, json={
            "presentation_id": pid, "variant_id": vid, "expected_presentation_revision": p_rev, "expected_variant_revision": v_rev,
            "format": "mp4", "settings": {"scope": "master"}})
        assert status == 409 and refused["error"]["code"] == "presentation_render_master_incompatible", refused
        _, jobs = await stack.call("GET", RENDER)
        assert jobs["jobs"] == [], "nothing was queued"
        snapshots = [a for a in await stack.core.artifacts.list() if a.kind.value in ("presentation_snapshot", "presentation_video")] \
            if hasattr(stack.core.artifacts, "list") else []
        report["master"] = {"reason": read["master"]["reason"], "detail": read["master"]["detail"], "scene_ids": read["master"]["scene_ids"],
                            "export_refusal": {"status": 409, "code": refused["error"]["code"], "reason": refused["error"].get("reason")},
                            "jobs_after_refusal": len(jobs["jobs"])}
        # Variants: the § 3 sentence, the export refused, « Lire » plays, the scene door opens the real Studio on the scene
        started = time.monotonic()
        result = await run_long(stack.page_url, open_plan(pid) + [
            {"until": f"({RMS_STATE}.master||{{}}).state==='incompatible'", "ms": 30000, "required": True, "as": "master_read"},
            {"value": "line", "expr": RMS_TEXT}, {"value": "master_line", "expr": MASTER_LINE},
            {"value": "export_disabled", "expr": f"document.querySelector('{EXPORT}').getAttribute('aria-disabled')"},
            {"value": "export_title", "expr": f"document.querySelector('{EXPORT}').getAttribute('title')"},
            {"value": "door_target", "expr": f"document.querySelector('{DOOR}').getAttribute('data-target')"},
            {"value": "scene_door_shown", "expr": f"!!document.querySelector('{SCENE_DOOR}')&&document.querySelector('{SCENE_DOOR}').offsetParent!==null"},
            {"until": f"(()=>{{const s={VSTATE};return !!s&&s.phase==='ready'&&s.duration>0}})()", "ms": 90000, "required": True,
             "as": "player_ready"},
            {"value": "frame_t0", "expr": f"JSON.stringify({VSTATE})"}, {"value": "play_control", "expr": gesture("play", legacy=False)},
            {"wait": 4500}, {"value": "frame_t1", "expr": f"JSON.stringify({VSTATE})"}, shot(raw, "legacy-variants"),
            {"click": DOOR}, {"until": f"!!{DIALOG}", "ms": 15000, "required": True, "as": "dialog"},
            {"value": "dialog", "expr": f"{DIALOG}.innerText.slice(0,400)"}, {"value": "dialog_target", "expr": f"{DIALOG}.getAttribute('data-target')"},
            {"click": CONFIRM},
            {"until": f"{RMS_STATE}.studio && {RMS_STATE}.studio.status==='ready' && !{RMS_STATE}.busy", "ms": 240000, "as": "studio_ready"},
            {"value": "studio", "expr": f"JSON.stringify({RMS_STATE}.studio)"}, {"value": "status", "expr": RMS_TEXT}], timeout=420)
        report["durations_ms"]["variants_and_scene_studio"] = round((time.monotonic() - started) * 1000)
        reads = result["reads"]
        harness(not reads.get("failed"), reads.get("failed"))
        assert sentence in reads["line"] or sentence in reads["master_line"], (reads["line"], reads["master_line"])
        assert reads["export_disabled"] == "true" and sentence in (reads["export_title"] or ""), reads
        played = json.loads(reads["frame_t0"] or "null"), json.loads(reads["frame_t1"] or "null")
        studio = json.loads(reads["studio"] or "null") or {}
        assert (studio.get("target") or {}).get("kind") == "scene", studio
        report["variants"] = {k: reads.get(k) for k in ("line", "master_line", "export_disabled", "export_title", "door_target", "scene_door_shown",
                                                        "dialog", "dialog_target", "status")}
        report["variants"]["play"] = {"control": reads.get("play_control"), "before": played[0], "after_4_5_s": played[1]}
        report["variants"]["studio_target"] = studio.get("target")
        # scene 1 lasts 3 s: 4.5 s after « Lire » the Player has crossed into scene 2 (or, on a slow machine, advanced at least 1 s)
        assert played[0] and played[1] and (played[1]["scene"] == "S2" or played[1]["frame"] - played[0]["frame"] >= 30), played
        await studio_post(stack, "close", {}, report)
        # a scene export still renders (scene scope, today's body)
        p_rev, v_rev = await revisions(stack, pid, vid)
        _, variant_doc = await stack.call("GET", f"{BASE}/{pid}/variants/{vid}")
        first = variant_doc["scenes"][0]["scene_id"]
        status, queued = await stack.call("POST", RENDER, json={
            "presentation_id": pid, "variant_id": vid, "expected_presentation_revision": p_rev, "expected_variant_revision": v_rev,
            "format": "mp4", "settings": {"scene_id": first, "scale": 0.25}})
        assert status == 202, queued
        done = await job_done(stack, queued["job"]["job_id"])
        assert done["state"] == "complete", done
        meta = dict((await stack.core.artifacts.get(done["artifact_id"])).metadata)
        assert meta["render_scope"] == "scene" and meta["render_scene_id"] == first, meta
        report["scene_export"] = {"state": done["state"], "frames": done.get("frames_total"), "render_scope": meta["render_scope"],
                                  "render_scene_id": meta["render_scene_id"]}
        report["canonical_changed"] = changed(h0, canonical(stack.data_root))
        assert report["canonical_changed"] == []
    report["screenshots"] = keep_shots(raw, folder)
    write_summary(folder, "legacy-summary.json", report)

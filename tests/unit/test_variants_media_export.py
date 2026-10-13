"""Le son d'une scène Remotion jusqu'à l'export (handoff jarvis-remotion-native-studio-playback-fix, Slice 08).

1. Toujours : l'asset audio de la source gelée (`public/tone.wav`) est dans le plan d'export, octet pour octet, et le rendu MP4 est demandé
   avec le son (`muted: false` dans `render-host.cjs`).
2. Opt-in (`JARVIS_REMOTION_RUNTIME_DIR`, Node, Chrome) : un VRAI rendu MP4 de cette scène, vérifié par le runner, porte un flux audio
   (ffprobe indépendant du runner, celui du compositeur épinglé). Runtime PRIVÉ sous `tmp_path` (jonction `node_modules` vers l'installation
   donnée, qui reste en lecture seule) ; jamais le Jarvis vivant.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import time

import pytest

from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.domain.presentation_render_plan import choose_scene, plan_files
from jarvis.domain.remotion_source import Composition
from tests.fakes.presentation_world import PresentationWorld
from tests.fakes.remotion_player_stack import provision_runtime, runtime_dir_from_env
from tests.unit.presentation_playback_gate_world import record
from tests.unit.variants_media_world import AUDIO_TSX, PROPS, tone_wav

ROOT = Path(__file__).resolve().parents[2]
COMPOSITION = Composition("Scene", 1280, 720, 30, 60)
SAMPLE = {"props": {"title": "Son", "bg": "#b01010"}, "data": {}}


async def audio_package(world: PresentationWorld, *, engine=None):
    kwargs = {"engine": engine} if engine is not None else {}
    pid, vid = await world.new_presentation({"src/Scene.tsx": AUDIO_TSX, "public/tone.wav": tone_wav(2.0)}, composition=COMPOSITION,
                                            props_schema=PROPS, sample=SAMPLE, props={"title": "Son", "bg": "#b01010"}, **kwargs)
    frozen = await world.freeze(pid, vid)
    return frozen["artifact_id"], await world.packager.read_snapshot(frozen["artifact_id"])


async def test_the_audio_asset_is_in_the_export_plan_and_the_mp4_is_rendered_with_sound(tmp_path):
    world = await PresentationWorld().open(tmp_path, runtime={"remotion_version": "4.0.534"})
    try:
        _, package = await audio_package(world)
        files, _props = plan_files(package, choose_scene(package, None))
    finally:
        await world.close()
    assert files["public/tone.wav"] == tone_wav(2.0), "the frozen asset goes to the render, byte for byte"
    assert 'staticFile("tone.wav")' in files["src/Scene.tsx"].decode("utf-8")
    host = (ROOT / "jarvis" / "capabilities" / "remotion" / "render-host.cjs").read_text(encoding="utf-8")
    assert "codec: 'h264'" in host and "muted: false" in host, "an MP4 export keeps the composition's audio"


def ffprobe_of(runtime: Path) -> Path | None:
    for entry in sorted((runtime / "node_modules" / "@remotion").iterdir()):
        if entry.name.startswith("compositor-"):
            for name in ("ffprobe.exe", "ffprobe"):
                if (entry / name).is_file():
                    return entry / name
    return None


RUNTIME = runtime_dir_from_env()


@pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None, reason="needs JARVIS_REMOTION_RUNTIME_DIR, node and Chrome")
async def test_a_real_mp4_export_of_an_audio_scene_carries_an_audio_stream(tmp_path):
    from jarvis.adapters.remotion_render_runner import RemotionRenderRunner
    from jarvis.core.presentation_render_service import PresentationRenderService

    provision_runtime(tmp_path / "data", RUNTIME)
    runtime = tmp_path / "data" / "local_capabilities" / "remotion" / "runtime"
    world = await PresentationWorld().open(tmp_path / "world", runtime={"remotion_version": "4.0.534"})
    runner = RemotionRenderRunner(lambda: runtime)
    service = PresentationRenderService(artifacts=world.artifacts, snapshots=world.snapshots, packager=world.packager, runner=runner,
                                        installed_engine=runner.installed_engine, diagnostics=world.sink)
    try:
        snapshot_id, _ = await audio_package(world, engine=shipped_engine_pin())
        view = await service.submit(snapshot_id, "mp4", {"frame_start": 0, "frame_end": 59, "concurrency": 1})
        end = time.monotonic() + 300
        while time.monotonic() < end:
            view = service.get(view["job_id"])
            if view["state"] in ("complete", "failed", "cancelled"):
                break
            await asyncio.sleep(0.25)
        assert view["state"] == "complete", [view.get("error_code"), view.get("error_detail"), view.get("log_tail")]
        artifact = await world.artifacts.get(view["artifact_id"])
        payload = Path(world.artifacts.payload_path(artifact))
        ffprobe = ffprobe_of(RUNTIME)
        assert ffprobe is not None, "the pinned compositor's ffprobe"
        probe = json.loads(subprocess.run([str(ffprobe), "-v", "error", "-show_streams", "-of", "json", str(payload)], capture_output=True,
                                          text=True, timeout=60, check=False).stdout)
    finally:
        await service.stop()
        await world.close()
    streams = [{k: s.get(k) for k in ("codec_type", "codec_name", "sample_rate", "channels", "duration")} for s in probe["streams"]]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    record("export", {"streams": streams, "verified_by": view.get("verified_by"), "size_bytes": view.get("size_bytes")})
    assert [s["codec_type"] for s in streams].count("video") == 1 and view.get("verified_by") == "ffprobe"
    assert len(audio) == 1 and abs(float(audio[0]["duration"]) - 2.0) < 0.2, streams

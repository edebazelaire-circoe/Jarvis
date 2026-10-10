"""Harnais de RENDU RÉEL d'une présentation gelée (Slice 16 de jarvis-remotion-presentation-integration ; `docs/remotion-render.md` §9).

Prouve sur ce poste, avec le vrai moteur Remotion épinglé (runtime privé, `JARVIS_REMOTION_RUNTIME_DIR` ou `--runtime-dir`) et le vrai Chrome
installé, que : une scène Remotion gelée (vrai registre, vrai paquet, vrai `PresentationPackager`) se rend en MP4, en image fixe et en PDF
de pages-images ; que les fichiers sont ce qu'ils disent (ffprobe INDÉPENDANT du runner, en-têtes, dimensions, nombre d'images, empreinte égale
à celle du payload de l'Artifact) ; que le dérivé est relié à son snapshot avec ses réglages ; et que les échecs sont dits (annulation en cours de
rendu, processus tué, Core mort puis reprise, instantané inconnu ou périmé, disque, délai, scène hostile sans sortie réseau).

    python scripts/remotion_render_harness.py --work-dir C:/Users/<moi>/AppData/Local/Temp/jrs16 --runtime-dir <runtime> \\
        --evidence tasks/jarvis-remotion-presentation-integration/slices/16-render-export-and-derived-artifacts/evidence/real-render.json

Racine de données PRIVÉE, jamais le JARVIS vivant : aucune route de Core n'est appelée ici (le service de rendu est composé comme `v2_app` le
compose, avec le vrai runner). La capacité locale est déclarée `ready` (le runtime privé est une jonction vers l'installation de la Slice 06,
aucune installation de plus).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import http.server
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.adapters.process_tree import kill_tree, pid_exists  # noqa: E402
from jarvis.adapters.remotion_compiler import shipped_engine_pin  # noqa: E402
from jarvis.adapters.remotion_render_runner import RemotionRenderRunner  # noqa: E402
from jarvis.core.presentation_render_service import PresentationRenderService  # noqa: E402
from jarvis.domain import presentation_render as D  # noqa: E402
from jarvis.domain.artifacts import ArtifactKind, ArtifactState  # noqa: E402
from jarvis.domain.remotion_source import Composition  # noqa: E402
from jarvis.ports.artifacts import RelationDirection  # noqa: E402
from tests.fakes.presentation_world import SCENE_ID, PresentationWorld  # noqa: E402
from tests.fakes.remotion_hostile import BY_ID  # noqa: E402

COMPOSITION = Composition("Scene", 1280, 720, 30, 90)
SCENE_TSX = '''import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
export default function Scene(props: {title: string; accent: string}) {
  const frame = useCurrentFrame();
  const {durationInFrames, width} = useVideoConfig();
  const left = interpolate(frame, [0, durationInFrames - 1], [0, width - 240]);
  return (
    <AbsoluteFill style={{background: "#101820"}}>
      <div style={{position: "absolute", left, top: 300, width: 240, height: 120, background: props.accent}} />
      <h1 style={{color: "#ffffff", fontSize: 72, fontFamily: "sans-serif", margin: 60}}>{props.title} · {frame}</h1>
    </AbsoluteFill>
  );
}
'''
PROPS = {"type": "object", "properties": {"title": {"type": "string", "default": "Jarvis", "max_length": 80},
                                           "accent": {"type": "color", "default": "#3366ff"}}}
SAMPLE = {"props": {"title": "Jarvis", "accent": "#3366ff"}, "data": {}}


def sh(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False).stdout


def ffprobe_of(runtime: Path) -> Path:
    for entry in sorted((runtime / "node_modules" / "@remotion").iterdir()):
        if entry.name.startswith("compositor-"):
            for name in ("ffprobe.exe", "ffprobe"):
                if (entry / name).is_file():
                    return entry / name
    raise SystemExit("ffprobe of the pinned compositor not found")


def jobs_alive(runtime: Path, needle: str) -> list[str]:
    """Processus dont la ligne de commande contient `needle` (le dossier d'un travail) : Windows par PowerShell, ailleurs `ps`."""

    if os.name == "nt":
        out = sh(["powershell", "-NoProfile", "-Command",
                  f"Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like '*{needle}*' -and $_.Name -notlike 'powershell*' }} | ForEach-Object {{ $_.Name + ':' + $_.ProcessId }}"])
    else:
        out = sh(["pgrep", "-af", needle])
    return [line.strip() for line in out.splitlines() if line.strip()]


class Harness:
    def __init__(self, work: Path, runtime: Path) -> None:
        self.work, self.runtime = work, runtime
        self.checks: list[dict] = []
        self.timings: dict[str, float] = {}
        self.facts: dict[str, object] = {}

    def check(self, name: str, ok: bool, **detail) -> bool:
        self.checks.append({"check": name, "ok": bool(ok), **detail})
        print(("PASS " if ok else "FAIL ") + name + (" " + json.dumps(detail, default=str)[:300] if detail else ""), flush=True)
        return ok

    async def wait_done(self, service: PresentationRenderService, job_id: str, *, timeout=240.0, on_view=None) -> dict:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            view = service.get(job_id)
            if on_view:
                on_view(view)
            if view["state"] in ("complete", "failed", "cancelled"):
                return view
            await asyncio.sleep(0.25)
        raise SystemExit(f"job {job_id} did not finish within {timeout} s")

    async def build(self, name: str, *, free_bytes=None) -> tuple[PresentationWorld, RemotionRenderRunner, PresentationRenderService]:
        root = self.work / name
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        world = await PresentationWorld().open(root, runtime={"remotion_version": "4.0.534"})
        runner = RemotionRenderRunner(lambda: self.runtime, free_bytes=free_bytes)
        service = PresentationRenderService(artifacts=world.artifacts, snapshots=world.snapshots, packager=world.packager, runner=runner,
                                            installed_engine=runner.installed_engine, diagnostics=world.sink)
        return world, runner, service

    # ------------------------------------------------------------------ scénarios

    async def happy(self) -> None:
        world, runner, service = await self.build("happy")
        pin = shipped_engine_pin()
        pid, vid = await world.new_presentation({"src/Scene.tsx": SCENE_TSX}, composition=COMPOSITION, engine=pin, props_schema=PROPS,
                                                sample=SAMPLE, props={"title": "Export réel"})
        frozen = await world.freeze(pid, vid)
        snapshot_id = frozen["artifact_id"]
        availability = service.availability()
        self.facts["availability"] = availability
        self.check("availability ready with a real browser", availability["ready"] is True, browser=availability["browser"])
        ffprobe = ffprobe_of(self.runtime)
        results = {}
        for label, fmt, settings in (("mp4", "mp4", {"frame_start": 0, "frame_end": 59, "concurrency": 2}),
                                     ("still", "still", {"frame": 45}),
                                     ("pdf", "pdf", {"frames": [0, 45, 89]})):
            started = time.monotonic()
            view = await service.submit(snapshot_id, fmt, settings)
            samples: list[dict] = []
            done = await self.wait_done(service, view["job_id"], on_view=lambda v: samples.append({k: v[k] for k in ("state", "phase", "frames_done", "elapsed_s", "percent")}))
            took = time.monotonic() - started
            self.timings[label + "_s"] = round(took, 1)
            artifact = await world.artifacts.get(done["artifact_id"])
            results[label] = (done, artifact)
            if not self.check(f"{label}: job complete", done["state"] == "complete", elapsed_s=round(took, 1), size=done["size_bytes"],
                              verified_by=done["verified_by"], progress_samples=len(samples), phases=sorted({s["phase"] for s in samples}),
                              error=[done["error_code"], done["error_detail"]], log=done["log_tail"]):
                await world.close()
                return
            payload = world.artifacts.payload_path(artifact)
            data = Path(payload).read_bytes()
            self.check(f"{label}: artifact complete, kind and payload", artifact.state is ArtifactState.COMPLETE and artifact.size_bytes == len(data),
                       kind=artifact.kind.value, size=len(data), width=artifact.width, height=artifact.height, duration_ms=artifact.duration_ms)
            self.check(f"{label}: payload sha256 equals the recorded one", hashlib.sha256(data).hexdigest() == artifact.metadata["render_output_sha256"])
            origins = await world.artifacts.relations(artifact.artifact_id, RelationDirection.ORIGINS)
            self.check(f"{label}: rendered_from the snapshot", [(r.relation.value, r.origin_artifact_id) for r in origins] == [("rendered_from", snapshot_id)])
            self.facts[label + "_metadata"] = dict(artifact.metadata)
            if label == "mp4":
                probe = json.loads(sh([str(ffprobe), "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", payload]))
                stream = probe["streams"][0]
                self.facts["mp4_ffprobe"] = {k: stream.get(k) for k in ("codec_name", "width", "height", "r_frame_rate", "nb_read_frames", "duration", "pix_fmt")}
                self.check("mp4: independent ffprobe (h264, 1280x720, 30 fps, 60 frames, 2 s)",
                           (stream["codec_name"], stream["width"], stream["height"], stream["r_frame_rate"], stream["nb_read_frames"]) ==
                           ("h264", 1280, 720, "30/1", "60") and abs(float(stream["duration"]) - 2.0) < 0.05, **self.facts["mp4_ffprobe"])
                self.check("mp4: ftyp header", data[4:8] == b"ftyp")
            if label == "still":
                self.check("still: PNG 1280x720", data[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(data[16:20], "big") == 1280 and int.from_bytes(data[20:24], "big") == 720)
                (self.work / "evidence_still.png").write_bytes(data)
            if label == "pdf":
                self.check("pdf: header, 3 pages, flat", data.startswith(b"%PDF-") and data.count(b"/Type /Page ") == 3 and artifact.metadata["render_flat"] is True,
                           pages=artifact.metadata.get("render_pages"))
                (self.work / "evidence.pdf").write_bytes(data)
        # le même instantané, les mêmes réglages : mêmes images (le hash du MP4 peut varier d'un encodeur à l'autre, pas celui d'une image fixe)
        again = await service.submit(snapshot_id, "still", {"frame": 45})
        redo = await self.wait_done(service, again["job_id"])
        first = await world.artifacts.get(results["still"][0]["artifact_id"])
        second = await world.artifacts.get(redo["artifact_id"])
        self.check("still: same snapshot + same settings give the same settings hash and the same bytes",
                   first.metadata["render_settings_sha256"] == second.metadata["render_settings_sha256"]
                   and first.metadata["render_output_sha256"] == second.metadata["render_output_sha256"],
                   sha=first.metadata["render_output_sha256"][:16])
        other = await service.submit(snapshot_id, "still", {"frame": 0})
        zero = await world.artifacts.get((await self.wait_done(service, other["job_id"]))["artifact_id"])
        self.check("still: another frame gives other pixels", zero.metadata["render_output_sha256"] != first.metadata["render_output_sha256"])
        egress = results["mp4"][0]
        self.facts["egress_denied_mp4"] = egress["egress_denied"]
        alive = jobs_alive(self.runtime, "render\\jobs")
        left = [str(p.relative_to(self.runtime)) for p in (self.runtime / "render" / "jobs").glob("*/*")
                if p.name not in ("job.json", "render.log", "result.json", "egress.json")]
        self.check("job folders cleaned, no render process left", not alive and not left, alive=alive[:5], left=left[:5])
        await world.close()


async def amain(args: argparse.Namespace) -> int:
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    runtime = Path(args.runtime_dir)
    harness = Harness(work, runtime)
    usage = shutil.disk_usage(work)
    free_before = usage.free
    started = time.monotonic()
    scenarios = {"happy": harness.happy}
    for name, fn in scenarios.items():
        if args.only and name not in args.only:
            continue
        await fn()
    free_after = shutil.disk_usage(work).free
    ok = all(c["ok"] for c in harness.checks)
    head = sh(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).strip()
    dirty = bool(sh(["git", "-C", str(ROOT), "status", "--porcelain"]).strip())
    report = {"verdict": "PASSED" if ok else "FAILED", "head": head, "tree_dirty": dirty, "platform": platform.platform(),
              "node": sh(["node", "--version"]).strip(), "chrome": (harness.facts.get("availability") or {}).get("browser"),
              "remotion": "4.0.534", "elapsed_s": round(time.monotonic() - started, 1), "timings": harness.timings,
              "disk": {"free_before_mb": free_before >> 20, "free_after_mb": free_after >> 20}, "facts": harness.facts, "checks": harness.checks}
    Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
    Path(args.evidence).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(report["verdict"], f"{sum(c['ok'] for c in harness.checks)}/{len(harness.checks)}")
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--runtime-dir", default=os.environ.get("JARVIS_REMOTION_RUNTIME_DIR", ""))
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--only", nargs="*")
    ns = parser.parse_args()
    if not ns.runtime_dir:
        raise SystemExit("--runtime-dir (or JARVIS_REMOTION_RUNTIME_DIR) is required")
    raise SystemExit(asyncio.run(amain(ns)))

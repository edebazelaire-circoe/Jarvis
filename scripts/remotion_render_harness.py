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
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.adapters import remotion_render_runner as runner_module  # noqa: E402
from jarvis.adapters.process_tree import kill_tree, make_process_ref, pid_exists, ref_alive  # noqa: E402
from jarvis.adapters.remotion_compiler import shipped_engine_pin  # noqa: E402
from jarvis.adapters.remotion_render_runner import RemotionRenderRunner  # noqa: E402
from jarvis.core.presentation_render_service import PresentationRenderService  # noqa: E402
from jarvis.domain import presentation_render as D  # noqa: E402
from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery, ArtifactState  # noqa: E402
from jarvis.domain.presentation_render import RenderError  # noqa: E402
from jarvis.domain.presentation_studio import PresentationStudioError  # noqa: E402
from jarvis.domain import remotion_source as rsrc  # noqa: E402
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
        original_close = world.close

        async def close_in_order() -> None:  # as Core stops: the render service first, then the registry
            await service.stop()
            await original_close()

        world.close = close_in_order
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
            self.check(f"{label}: rendered with Chrome's process sandbox ON (recorded on the derivative and in the job view)",
                       artifact.metadata["render_sandbox"] is True and done["sandbox"] is True)
            origins = await world.artifacts.relations(artifact.artifact_id, RelationDirection.ORIGINS)
            self.check(f"{label}: rendered_from the snapshot", [(r.relation.value, r.origin_artifact_id) for r in origins] == [("rendered_from", snapshot_id)])
            self.facts[label + "_metadata"] = dict(artifact.metadata)
            if label == "mp4":
                shutil.copyfile(payload, self.work / "evidence.mp4")
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
        again = await service.submit(snapshot_id, "still", {"frame": 45}, deduplicate=False)  # forced: the point is to compare two real renders
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

    # ------------------------------------------------------------------ rework: sandbox, burst, two Cores

    async def sandbox(self) -> None:
        root = self.work / "sandbox"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        runner = RemotionRenderRunner(lambda: self.runtime)
        browser = runner.find_browser()
        job_id = "rj_5a4d00b0c5ab"
        runner.prepare(job_id, {"x.txt": b"x"})
        job = self.runtime / "render" / "jobs" / job_id
        shutil.copyfile(ROOT / "scripts" / "remotion_sandbox_probe.cjs", job / "remotion_sandbox_probe.cjs")
        summary = {}
        for label, opt_out in (("sandbox_on", False), ("opt_out", True)):
            env = {**{k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA")},
                   "JARVIS_RENDER_DIR": str(job), "JARVIS_RENDER_RUNTIME": str(self.runtime), "JARVIS_RENDER_BROWSER": browser.path}
            if opt_out:
                env["JARVIS_REMOTION_RENDER_NO_SANDBOX"] = "1"
            out = job / f"{label}.json"
            done = subprocess.run(["node", "--require", str(job / "render-guard.cjs"), str(job / "remotion_sandbox_probe.cjs"), str(self.runtime), browser.path, str(out)],
                                  capture_output=True, text=True, timeout=120, env=env, check=False)
            report = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {"error": done.stderr[-300:]}
            lines = [line.split("\t") for line in str(report.get("sandbox_page", "")).splitlines() if "\t" in line]
            rows = [{"type": cols[1], "sandbox": cols[3], "lockdown": cols[4] if len(cols) > 4 else "", "integrity": cols[5] if len(cols) > 5 else ""}
                    for cols in lines[1:] if len(cols) > 3]
            summary[label] = {"rows": rows, "guard_sandbox_flag": report.get("sandbox_flag_in_guard"), "error": report.get("error")}
        self.facts["sandbox_probe"] = {**summary, "chrome": browser.version}
        (self.work / "sandbox-probe.json").write_text(json.dumps(self.facts["sandbox_probe"], indent=2), encoding="utf-8")
        on = [r for r in summary["sandbox_on"]["rows"] if r["type"] == "Renderer"]
        off = [r for r in summary["opt_out"]["rows"] if r["type"] == "Renderer"]
        self.check("sandbox ON: chrome://sandbox reports every Renderer process sandboxed (Lockdown / Untrusted)",
                   bool(on) and all(r["lockdown"] == "Lockdown" and "Untrusted" in r["integrity"] for r in on), renderers=on[:3], guard=summary["sandbox_on"]["guard_sandbox_flag"])
        self.check("explicit opt-out: the same probe reports the Renderer processes NOT sandboxed (so the probe sees the difference)",
                   bool(off) and all(r["sandbox"] == "Not Sandboxed" for r in off) and summary["opt_out"]["guard_sandbox_flag"] is False, renderers=off[:3])
        shutil.rmtree(job, ignore_errors=True)
        # a browser that cannot start with the sandbox says so, typed, and is NEVER retried unsandboxed
        node_exe = shutil.which("node")
        for label, env_extra, expected in (("sandbox on", {}, "presentation_render_sandbox_unavailable"),
                                           ("opt-out", {"JARVIS_REMOTION_RENDER_NO_SANDBOX": "1"}, "presentation_render_browser_unavailable")):
            world, _, _ = await self.build(f"sandbox-fail-{label.replace(' ', '-')}")
            failing = RemotionRenderRunner(lambda: self.runtime, environ={**os.environ, "JARVIS_REMOTION_RENDER_BROWSER": node_exe, **env_extra})
            service = PresentationRenderService(artifacts=world.artifacts, snapshots=world.snapshots, packager=world.packager, runner=failing,
                                                installed_engine=failing.installed_engine, diagnostics=world.sink)
            pid, vid = await world.new_presentation({"src/Scene.tsx": SCENE_TSX}, composition=COMPOSITION, engine=shipped_engine_pin(), props_schema=PROPS, sample=SAMPLE)
            snapshot = (await world.freeze(pid, vid))["artifact_id"]
            view = await service.submit(snapshot, "still", {"frame": 1})
            done = await self.wait_done(service, view["job_id"], timeout=90)
            artifact = await world.artifacts.get(done["artifact_id"])
            detail = done["error_detail"] or ""
            self.check(f"a browser that cannot start ({label}) is a typed visible failure and is not retried without the sandbox",
                       done["state"] == "failed" and done["error_code"] == expected and artifact.state is ArtifactState.FAILED
                       and ((expected.endswith("sandbox_unavailable") and "JARVIS_REMOTION_RENDER_NO_SANDBOX=1" in detail and "never retries" in detail)
                            or expected.endswith("browser_unavailable")) and not self.no_final_file_for(world, artifact),
                       code=done["error_code"], detail=detail[:200])
            await world.close()

    def no_final_file_for(self, world, artifact) -> bool:
        return not self.no_final_file(world, artifact)

    async def burst(self) -> None:
        world, runner, service, pid, vid, snap = await self.plain_world("burst")
        results = await asyncio.gather(*(service.submit(snap, "still", {"frame": index}) for index in range(40)), return_exceptions=True)
        accepted = [r for r in results if isinstance(r, dict)]
        refused = [r for r in results if isinstance(r, RenderError)]
        derivs = (await world.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_STILL,), limit=100))).items
        self.check("burst: 40 concurrent requests -> 8 accepted, 32 queue_full, no derivative for a refused one",
                   len(accepted) == 8 and len(refused) == 32 and {r.code.value for r in refused} == {"presentation_render_queue_full"}
                   and len(derivs) == 8 and {d.artifact_id for d in derivs} == {r["artifact_id"] for r in accepted},
                   accepted=len(accepted), refused=len(refused), derivatives=len(derivs))
        again = await service.submit(snap, "still", {"frame": 0})
        self.check("burst: an identical request returns the existing job (deduplicated), creating nothing", again["deduplicated"] is True and again["job_id"] in {r["job_id"] for r in accepted})
        for job in accepted:
            try:
                await service.cancel(job["job_id"])
            except RenderError:
                pass
        for job in accepted:
            await self.wait_done(service, job["job_id"], timeout=90)
        self.check("burst: every accepted job ends terminal after the cancels, nothing left", not jobs_alive(self.runtime, "render\\jobs"), alive=jobs_alive(self.runtime, "render\\jobs")[:3])
        await world.close()

    async def two_cores(self) -> None:
        world, runner, service, pid, vid, snap = await self.plain_world("twocores")
        await world.close()
        known = {record.get("job_id") for record in RemotionRenderRunner(lambda: self.runtime).records()}
        child = subprocess.Popen([sys.executable, str(Path(__file__)), "--child", str(self.work / "twocores"), "--runtime-dir", str(self.runtime),
                                  "--snapshot", snap, "--work-dir", str(self.work), "--evidence", "unused"], cwd=str(ROOT))
        end, ref = time.monotonic() + 150, ""
        while time.monotonic() < end and not ref:
            await asyncio.sleep(0.5)
            for record in RemotionRenderRunner(lambda: self.runtime).records():
                if record.get("process_ref") and record.get("state") == "running" and record.get("job_id") not in known:
                    ref = record["process_ref"]
        if not self.check("two Cores: the first Core is rendering", bool(ref)):
            child.kill()
            return
        world2 = await PresentationWorld().open(self.work / "twocores", runtime={"remotion_version": "4.0.534"})
        runner2 = RemotionRenderRunner(lambda: self.runtime)
        second = PresentationRenderService(artifacts=world2.artifacts, snapshots=world2.snapshots, packager=world2.packager, runner=runner2,
                                           installed_engine=runner2.installed_engine, diagnostics=world2.sink)
        report = await second.reconcile()
        page = await world2.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_VIDEO,), limit=10))
        try:
            await second.submit(snap, "still", {"frame": 3})
            refused = None
        except RenderError as exc:
            refused = exc.code.value
        self.check("two Cores: the second Core kills and recovers NOTHING of the first one's render, and refuses to render itself",
                   report.get("locked") is True and ref_alive(ref) and [a.state for a in page.items] == [ArtifactState.PENDING] and refused == "presentation_render_locked"
                   and second.availability()["ready"] is False, report=report, refused=refused)
        kill_core(child, self.work / "twocores" / "child.pid")
        third = PresentationRenderService(artifacts=world2.artifacts, snapshots=world2.snapshots, packager=world2.packager, runner=runner2,
                                          installed_engine=runner2.installed_engine, diagnostics=world2.sink)
        report = await third.reconcile()
        artifact = await world2.artifacts.get(page.items[0].artifact_id)
        self.check("two Cores: once the first Core is dead its lock is taken over and the orphan is recovered",
                   report.get("locked") is None and report["killed"] >= 1 and artifact.state is ArtifactState.FAILED and not ref_alive(ref), report=report)
        await third.stop()
        await world2.close()

    # ------------------------------------------------------------------ échecs

    async def long_job(self, service, snapshot_id, **settings):
        """Un MP4 volontairement lent (2560x1440, un seul onglet) pour avoir le temps d'agir en cours de rendu."""

        view = await service.submit(snapshot_id, "mp4", {"scale": 2.0, "concurrency": 1, **settings})
        end = time.monotonic() + 150
        while time.monotonic() < end:
            now = service.get(view["job_id"])
            if now["phase"] == "rendering" and now["frames_done"] >= 2:
                return view["job_id"]
            if now["state"] in ("failed", "cancelled", "complete"):
                raise SystemExit(f"the long job ended early: {now['state']} {now['error_code']} {now['error_detail']}")
            await asyncio.sleep(0.2)
        raise SystemExit("the long job never reached the rendering phase")

    async def plain_world(self, name: str, **kw):
        world, runner, service = await self.build(name, **kw)
        pid, vid = await world.new_presentation({"src/Scene.tsx": SCENE_TSX}, composition=COMPOSITION, engine=shipped_engine_pin(),
                                                props_schema=PROPS, sample=SAMPLE)
        return world, runner, service, pid, vid, (await world.freeze(pid, vid))["artifact_id"]

    @staticmethod
    def no_final_file(world, artifact) -> bool:
        info = world.artifacts.payload_info(artifact)
        return info is None or info.final_bytes is None

    async def cancel_and_kill(self) -> None:
        world, runner, service, pid, vid, snap = await self.plain_world("cancel")
        job_id = await self.long_job(service, snap)
        ref = service._jobs[job_id].process_ref
        node_pid = int(ref.split(":")[0])
        started = time.monotonic()
        view = await service.cancel(job_id)
        self.check("cancel: the view says cancel is requested while the process still runs", view["cancel_requested"] is True and view["state"] == "running")
        done = await self.wait_done(service, job_id, timeout=60)
        took = time.monotonic() - started
        artifact = await world.artifacts.get(done["artifact_id"])
        self.timings["cancel_to_stopped_s"] = round(took, 1)
        self.check("cancel: job cancelled, derivative failed with a stable code, no final file", done["state"] == "cancelled" and artifact.state is ArtifactState.FAILED
                   and artifact.error_code == "presentation_render_cancelled" and self.no_final_file(world, artifact), seconds=round(took, 1),
                   state=done["state"], artifact_state=artifact.state.value, code=artifact.error_code, final=not self.no_final_file(world, artifact))
        self.check("cancel: the whole process tree is gone (identity-checked ref, no process carries the job id)",
                   not ref_alive(ref) and not pid_exists(node_pid) and not jobs_alive(self.runtime, job_id), alive=jobs_alive(self.runtime, job_id))
        # a pid reused by another program is never killed: the ref carries the creation time
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            wrong = f"{sleeper.pid}:1"
            self.check("stop(): a reference with the wrong creation time does not kill the program that owns the pid",
                       runner.stop(wrong) is True and sleeper.poll() is None)
            self.check("stop(): the right reference does", runner.stop(make_process_ref(sleeper.pid)) is True and sleeper.wait(timeout=10) is not None)
        finally:
            sleeper.kill()
        # killed from outside, whole tree
        job_id = await self.long_job(service, snap)
        ref = service._jobs[job_id].process_ref
        kill_tree(int(ref.split(":")[0]))
        done = await self.wait_done(service, job_id, timeout=60)
        artifact = await world.artifacts.get(done["artifact_id"])
        self.check("kill: a render killed from outside fails visibly (code, detail), no final file, nothing left", done["state"] == "failed"
                   and artifact.state is ArtifactState.FAILED and artifact.error_code in ("presentation_render_failed", "presentation_render_crashed")
                   and self.no_final_file(world, artifact) and not jobs_alive(self.runtime, job_id), code=done["error_code"], detail=done["error_detail"])
        # killed from outside, NODE ONLY: Chrome is orphaned and must be swept
        job_id = await self.long_job(service, snap)
        ref = service._jobs[job_id].process_ref
        node_pid = int(ref.split(":")[0])
        subprocess.run(["taskkill", "/PID", str(node_pid), "/F"], capture_output=True, check=False)
        done = await self.wait_done(service, job_id, timeout=60)
        artifact = await world.artifacts.get(done["artifact_id"])
        self.check("kill (node only): orphaned Chrome is swept, derivative failed, no final file", done["state"] == "failed"
                   and artifact.state is ArtifactState.FAILED and self.no_final_file(world, artifact) and not jobs_alive(self.runtime, job_id),
                   alive=jobs_alive(self.runtime, job_id), log=done["log_tail"])
        again = await service.submit(snap, "still", {"frame": 0})
        ok = await self.wait_done(service, again["job_id"])
        self.check("after cancel and kills the queue still works", ok["state"] == "complete")
        await world.close()

    async def core_death(self) -> None:
        world, runner, service, pid, vid, snap = await self.plain_world("restart")
        await world.close()
        child = subprocess.Popen([sys.executable, str(Path(__file__)), "--child", str(self.work / "restart"), "--runtime-dir", str(self.runtime),
                                  "--snapshot", snap, "--work-dir", str(self.work), "--evidence", "unused"], cwd=str(ROOT))
        end, ref, job_id = time.monotonic() + 150, "", ""
        while time.monotonic() < end and not ref:
            await asyncio.sleep(0.5)
            for record in RemotionRenderRunner(lambda: self.runtime).records():
                if record.get("process_ref") and record.get("state") in ("queued", "running"):
                    ref, job_id = record["process_ref"], record["job_id"]
        if not self.check("restart: a render is running in a separate Core-like process", bool(ref), job=job_id):
            child.kill()
            return
        job_dir = self.runtime / "render" / "jobs" / job_id
        end = time.monotonic() + 120
        while time.monotonic() < end:  # kill the Core while frames are being produced, not while bundling
            try:
                if json.loads((job_dir / "progress.json").read_text(encoding="utf-8")).get("frames_done", 0) >= 2:
                    break
            except (OSError, ValueError):
                pass
            await asyncio.sleep(0.3)
        kill_core(child, self.work / ("restart" if True else "") / "child.pid")  # no /T: the render survives its Core
        progress = (job_dir / "progress.json").read_text(encoding="utf-8") if (job_dir / "progress.json").is_file() else "(none)"
        self.check("restart: the 'Core' is dead and its render process is still alive (an orphan)", ref_alive(ref), ref=ref, progress=progress[:200],
                   result_written=(job_dir / "result.json").is_file())
        world2 = await PresentationWorld().open(self.work / "restart", runtime={"remotion_version": "4.0.534"})
        runner2 = RemotionRenderRunner(lambda: self.runtime)
        service2 = PresentationRenderService(artifacts=world2.artifacts, snapshots=world2.snapshots, packager=world2.packager, runner=runner2,
                                             installed_engine=runner2.installed_engine, diagnostics=world2.sink)
        page = await world2.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_VIDEO,), limit=10))
        pending = [a for a in page.items if a.state is ArtifactState.PENDING]
        self.check("restart: before recovery the derivative is still pending", len(pending) == 1)
        # the generic recovery leaves render derivatives to the render service (owned), as v2_app wires it
        generic = await world2.artifacts.recover_pending(owned=PresentationRenderService.owns)
        self.check("restart: generic recovery leaves the render derivative to its owner", generic.owned == (pending[0].artifact_id,) and not generic.partial)
        report = await service2.reconcile()
        artifact = await world2.artifacts.get(pending[0].artifact_id)
        self.facts["reconcile_report"] = report
        self.check("restart: reconcile kills the orphan, fails the derivative as interrupted, no final file, nothing left",
                   report["killed"] >= 1 and artifact.state is ArtifactState.FAILED and artifact.error_code == "presentation_render_interrupted"
                   and self.no_final_file(world2, artifact) and not ref_alive(ref) and not jobs_alive(self.runtime, job_id), report=report,
                   code=artifact.error_code)
        again = await service2.submit(snap, "still", {"frame": 0})
        self.check("restart: a new render works after the recovery", (await self.wait_done(service2, again["job_id"]))["state"] == "complete")
        await service2.stop()  # releases the render lock like a Core that stops
        await world2.close()

    async def refusals(self) -> None:
        world, runner, service, pid, vid, snap = await self.plain_world("refusals")
        kinds = (ArtifactKind.PRESENTATION_VIDEO, ArtifactKind.PRESENTATION_STILL, ArtifactKind.PRESENTATION_PDF)

        async def renders() -> int:
            return len((await world.artifacts.query(ArtifactQuery(kinds=kinds, limit=50))).items)

        async def refused(label: str, call, code: str) -> None:
            try:
                await call()
            except Exception as exc:  # noqa: BLE001 - the check compares the stable code
                got = getattr(getattr(exc, "code", None), "value", type(exc).__name__)
                self.check(f"refusal: {label}", got == code and await renders() == 0, code=got, expected=code)
                return
            self.check(f"refusal: {label}", False, code="(accepted)")

        await refused("unknown snapshot id", lambda: service.submit("jart_ps_" + "0" * 32 + "_" + "0" * 32 + "_p1_v1_a1", "mp4"),
                      "presentation_render_snapshot_invalid")
        shot = await world.artifacts.create(kind=ArtifactKind.SCREENSHOT, source="test", payload_name="s.png", mime_type="image/png")
        await world.artifacts.store_payload(shot.artifact_id, b"\x89PNG\r\n\x1a\n" + b"0" * 40)
        await refused("an Artifact that is not a snapshot", lambda: service.submit(shot.artifact_id, "mp4"), "presentation_render_snapshot_invalid")
        await refused("a bad format", lambda: service.submit(snap, "gif"), "presentation_studio_invalid")
        await refused("an unknown setting", lambda: service.submit(snap, "mp4", {"codec": "vp9"}), "presentation_render_invalid")
        await refused("a frame outside the scene", lambda: service.submit(snap, "still", {"frame": 90}), "presentation_render_invalid")
        await refused("a reversed range", lambda: service.submit(snap, "mp4", {"frame_start": 5, "frame_end": 2}), "presentation_render_invalid")
        await refused("a setting that does not apply to the format", lambda: service.submit(snap, "still", {"frames": [1]}), "presentation_render_invalid")
        # tampered package: a byte of snapshot.zip changed on disk
        art = await world.artifacts.get(snap)
        path = Path(world.artifacts.payload_path(art))
        original = path.read_bytes()
        data = bytearray(original)
        data[len(data) // 2] ^= 0xFF
        path.write_bytes(bytes(data))
        await refused("a tampered snapshot.zip (hash differs)", lambda: service.submit(snap, "still"), "presentation_render_snapshot_invalid")
        path.write_bytes(original)

        class Other:
            remotion_version, lock_sha256 = "4.0.999", "0" * 64

        drift = PresentationRenderService(artifacts=world.artifacts, snapshots=world.snapshots, packager=world.packager, runner=runner,
                                          installed_engine=lambda: Other(), diagnostics=world.sink)
        await refused("an installed engine that differs from the frozen one", lambda: drift.submit(snap, "still"), "presentation_render_engine_mismatch")
        notready = PresentationRenderService(artifacts=world.artifacts, snapshots=world.snapshots, packager=world.packager, runner=runner,
                                             installed_engine=runner.installed_engine, capability_status=lambda: "not_installed", diagnostics=world.sink)
        await refused("the Remotion capability is not installed", lambda: notready.submit(snap, "still"), "presentation_render_runtime_unavailable")
        try:
            service.get("rj_000000000000")
            self.check("refusal: unknown job id is a typed 404", False)
        except RenderError as exc:
            self.check("refusal: unknown job id is a typed 404", exc.code.value == "presentation_render_unknown_job" and exc.status == 404)
        # stale source: edit after freezing
        p, v = 1, 1
        view = await world.studio.get(pid)
        variant = view.variants[0].to_document()
        await world.studio.save_variant(pid, vid, {"expected_revision": variant["revision"], "title": "Titre modifié", "scenes": variant["scenes"],
                                                    "art_direction_id": None, "score_id": None})
        try:
            await service.export(presentation_id=pid, variant_id=vid, expected_presentation_revision=view.presentation.revision,
                                 expected_variant_revision=variant["revision"], authorised_boards=["default"], render_format="still")
            self.check("stale: exporting an outdated revision is refused", False)
        except PresentationStudioError as exc:
            self.check("stale: exporting an outdated revision is refused (nothing frozen, nothing rendered)",
                       exc.code.value == "presentation_studio_stale_revision" and await renders() == 0, code=exc.code.value)
        done = await self.wait_done(service, (await service.submit(snap, "still", {"frame": 3}))["job_id"])
        described = await world.snapshots.describe_source(pid)
        entry = next(e for e in described["snapshots"] if e["artifact_id"] == snap)
        self.check("stale: the old snapshot still renders, and the Board data says stale: true with its render listed",
                   done["state"] == "complete" and entry["stale"] is True and [r["state"] for r in entry["renders"]] == ["complete"],
                   stale=entry["stale"], renders=entry["renders"])
        await world.close()

    async def bounds(self) -> None:
        world, runner, service, pid, vid, snap = await self.plain_world("bounds", free_bytes=lambda path: 100 << 20)
        done = await self.wait_done(service, (await service.submit(snap, "still", {"frame": 0}))["job_id"])
        artifact = await world.artifacts.get(done["artifact_id"])
        self.check("disk: less than the minimum free space fails before anything is written", done["state"] == "failed"
                   and done["error_code"] == "presentation_render_disk_low" and artifact.state is ArtifactState.FAILED
                   and not (self.runtime / "render" / "jobs" / done["job_id"] / "work").exists(), detail=done["error_detail"])
        await world.close()
        calls = {"n": 0}

        def shrinking(path):
            calls["n"] += 1
            return 10 << 30 if calls["n"] <= 1 else 10 << 20

        world, runner, service, pid, vid, snap = await self.plain_world("bounds2", free_bytes=shrinking)
        job_id = (await service.submit(snap, "mp4", {"scale": 2.0, "concurrency": 1}))["job_id"]
        done = await self.wait_done(service, job_id, timeout=120)
        artifact = await world.artifacts.get(done["artifact_id"])
        self.check("disk full while rendering: the process tree is killed, derivative failed, no final file", done["state"] == "failed"
                   and done["error_code"] == "presentation_render_disk_full" and self.no_final_file(world, artifact)
                   and not jobs_alive(self.runtime, job_id), detail=done["error_detail"])
        await world.close()
        real = D.MAX_JOB_DIR_BYTES
        D.MAX_JOB_DIR_BYTES = 3 << 20
        try:
            world, runner, service, pid, vid, snap = await self.plain_world("bounds3")
            job_id = (await service.submit(snap, "mp4", {"scale": 2.0, "concurrency": 1}))["job_id"]
            done = await self.wait_done(service, job_id, timeout=120)
            self.check("size bound: a render folder that grows past its limit is killed", done["state"] == "failed"
                       and done["error_code"] == "presentation_render_job_too_large" and not jobs_alive(self.runtime, job_id), detail=done["error_detail"])
            await world.close()
        finally:
            D.MAX_JOB_DIR_BYTES = real
        real_base = D.TIMEOUT_BASE_S
        D.TIMEOUT_BASE_S, D.TIMEOUT_PER_FRAME_S = 6.0, 0.0
        try:
            world, runner, service, pid, vid, snap = await self.plain_world("bounds4")
            job_id = (await service.submit(snap, "mp4", {"scale": 2.0, "concurrency": 1}))["job_id"]
            done = await self.wait_done(service, job_id, timeout=120)
            self.check("time bound: a render past its deadline is killed with a stated limit", done["state"] == "failed"
                       and done["error_code"] == "presentation_render_timeout" and not jobs_alive(self.runtime, job_id)
                       and done["timeout_s"] == 6, detail=done["error_detail"])
            await world.close()
        finally:
            D.TIMEOUT_BASE_S, D.TIMEOUT_PER_FRAME_S = real_base, 1.0

    async def hostile(self) -> None:
        http_hits: list[str] = []
        tcp_hits: list[str] = []
        udp_hits: list[int] = []

        class Sink(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                http_hits.append(self.path)
                self.send_response(200)
                self.end_headers()

            do_POST = do_GET

            def log_message(self, *args):
                pass

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Sink)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        tcp = socket.socket()
        tcp.bind(("127.0.0.1", 0))
        tcp.listen(16)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(("127.0.0.1", 0))
        stop = threading.Event()

        def accept_tcp():
            tcp.settimeout(0.3)
            while not stop.is_set():
                try:
                    conn, _ = tcp.accept()
                    tcp_hits.append("connect")
                    conn.close()
                except OSError:
                    pass

        def read_udp():
            udp.settimeout(0.3)
            while not stop.is_set():
                try:
                    udp.recvfrom(2048)
                    udp_hits.append(1)
                except OSError:
                    pass

        threading.Thread(target=accept_tcp, daemon=True).start()
        threading.Thread(target=read_udp, daemon=True).start()
        replacements = {"__ATTACKER__": f"http://127.0.0.1:{httpd.server_address[1]}", "__UDP__": f"127.0.0.1:{udp.getsockname()[1]}",
                        "__TAG__": "rj", "__PRECONNECT__": f"http://127.0.0.1:{tcp.getsockname()[1]}"}

        async def run_sample(sample_id: str, label: str, control: bool = False) -> dict:
            sample = BY_ID[sample_id]
            files: dict = {}
            for path, value in sample.source("evasive", "x").items():
                if isinstance(value, str):
                    for key, repl in replacements.items():
                        value = value.replace(key, repl)
                files[path] = value
            world, runner, service = await self.build(f"hostile-{label}")
            guards = rsrc.SOURCE_GUARDS
            rsrc.SOURCE_GUARDS = ()  # as in the Slice 06 harness: the STATIC layer is off so that the RUNTIME layer is what is measured
            pid, vid = await world.new_presentation(files, composition=COMPOSITION, engine=shipped_engine_pin(),
                                                    props_schema={"type": "object", "properties": {"title": {"type": "string", "default": "x", "max_length": 40}}},
                                                    sample={"props": {"title": "x"}, "data": {}})
            snap = (await world.freeze(pid, vid))["artifact_id"]
            if control:
                alt = self.work / "neutered-guard"
                alt.mkdir(exist_ok=True)
                shutil.copy(runner_module.SHIPPED_DIR / runner_module.HOST_FILE, alt / runner_module.HOST_FILE)
                text = (runner_module.SHIPPED_DIR / runner_module.GUARD_FILE).read_text(encoding="utf-8")
                marker = "function rewriteBrowserArgs(args) {"
                assert marker in text
                (alt / runner_module.GUARD_FILE).write_text(text.replace(marker, marker + "\n  return args;"), encoding="utf-8")
                runner_module.SHIPPED_DIR = alt
            try:
                view = await service.submit(snap, "still", {"frame": 10})
                done = await self.wait_done(service, view["job_id"])
            finally:
                rsrc.SOURCE_GUARDS = guards
                if control:
                    runner_module.SHIPPED_DIR = ROOT / "jarvis" / "capabilities" / "remotion"
            artifact = await world.artifacts.get(done["artifact_id"])
            refusal = None
            if sample_id == "net_exfil" and not control:
                # the snapshot was frozen before a stricter static guard existed: the frozen source is revalidated at render time and NOT rendered
                rsrc.SOURCE_GUARDS = (*guards, lambda source: ["added after the freeze: the word ATTACKER is now forbidden"]
                                      if any("ATTACKER" in text for text in source.module_texts().values()) else [])
                try:
                    again = await service.submit(snap, "still", {"frame": 10})
                    refusal = await self.wait_done(service, again["job_id"])
                finally:
                    rsrc.SOURCE_GUARDS = guards
            await world.close()
            return {"done": done, "artifact": artifact, "refusal": refusal}

        before = (len(http_hits), len(tcp_hits), len(udp_hits))
        out = {}
        for sample_id in ("net_exfil", "link_hints", "webrtc_exfil"):
            out[sample_id] = await run_sample(sample_id, sample_id)
        after = (len(http_hits), len(tcp_hits), len(udp_hits))
        denied = {k: v["done"]["egress_denied"] for k, v in out.items()}
        self.facts["hostile_guarded"] = {"http_hits": http_hits[:10], "tcp_connections": after[1] - before[1], "udp_packets": after[2] - before[2],
                                         "denied_by_sample": denied, "states": {k: v["done"]["state"] for k, v in out.items()}}
        self.check("hostile scenes (fetch, XHR, WebSocket, beacon, Image, CSS url, preconnect, WebRTC) render normally",
                   all(v["done"]["state"] == "complete" for v in out.values()), states=self.facts["hostile_guarded"]["states"],
                   errors=[(v["done"]["error_code"], v["done"]["error_detail"]) for v in out.values()])
        self.check("guarded: the local HTTP service received 0 requests, the TCP sink 0 connections, the UDP sink 0 packets", after == before,
                   http=http_hits[:5], tcp=after[1] - before[1], udp=after[2] - before[2])
        self.check("guarded: the denied requests are COUNTED and recorded on the derivative (render_egress_denied > 0)",
                   all(int(v["artifact"].metadata["render_egress_denied"]) > 0 for v in out.values()), denied=denied)
        refusal = out["net_exfil"]["refusal"]
        self.check("a frozen source that no longer passes today's static guards is revalidated and refused at render time (no browser launched)",
                   refusal["state"] == "failed" and refusal["error_code"] == "presentation_render_source_refused" and refusal["phase"] == "failed",
                   state=refusal["state"], phase=refusal["phase"], code=refusal["error_code"], detail=(refusal["error_detail"] or "")[:160])
        # negative control: the same scenes with the browser arguments left as Remotion sets them reach the sinks
        before = (len(http_hits), len(tcp_hits), len(udp_hits))
        for sample_id in ("net_exfil", "link_hints", "webrtc_exfil"):
            await run_sample(sample_id, sample_id + "-control", control=True)
        after = (len(http_hits), len(tcp_hits), len(udp_hits))
        self.facts["hostile_control"] = {"http_hits": after[0] - before[0], "tcp_connections": after[1] - before[1], "udp_packets": after[2] - before[2]}
        self.check("negative control (browser arguments not rewritten): the sinks DO receive traffic, so the harness would see a leak",
                   after[0] > before[0] and after[1] > before[1] and after[2] > before[2], **self.facts["hostile_control"])
        stop.set()
        httpd.shutdown()


def kill_core(shim: subprocess.Popen, pid_file: Path) -> None:
    """Tue le processus « Core » (l'interpréteur lui-même, pas son arbre : le rendu lui survit). Le `python.exe` d'un venv Windows est un lanceur
    qui démarre le vrai interpréteur : tuer le lanceur seul laisserait le Core vivant (et son verrou)."""

    try:
        real = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        real = shim.pid
    subprocess.run(["taskkill", "/PID", str(real), "/F"], capture_output=True, check=False)
    try:
        shim.wait(timeout=30)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/PID", str(shim.pid), "/F"], capture_output=True, check=False)


async def child_main(args: argparse.Namespace) -> int:
    """Processus « Core » du scénario de reprise : demande un rendu lent puis attend d'être tué."""

    runtime = Path(args.runtime_dir)
    (Path(args.child) / "child.pid").write_text(str(os.getpid()), encoding="utf-8")
    world = await PresentationWorld().open(Path(args.child), runtime={"remotion_version": "4.0.534"})
    runner = RemotionRenderRunner(lambda: runtime)
    service = PresentationRenderService(artifacts=world.artifacts, snapshots=world.snapshots, packager=world.packager, runner=runner,
                                        installed_engine=runner.installed_engine, diagnostics=world.sink)
    await service.reconcile()  # takes the render lock exactly as a Core does at start
    await service.submit(args.snapshot, "mp4", {"scale": 2.0, "concurrency": 1})
    await asyncio.sleep(600)
    return 0


async def amain(args: argparse.Namespace) -> int:
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    runtime = Path(args.runtime_dir)
    harness = Harness(work, runtime)
    shutil.rmtree(runtime / "render", ignore_errors=True)  # runtime privé : aucune trace d'une exécution précédente
    usage = shutil.disk_usage(work)
    free_before = usage.free
    started = time.monotonic()
    scenarios = {"happy": harness.happy, "cancel_and_kill": harness.cancel_and_kill, "core_death": harness.core_death,
                 "refusals": harness.refusals, "bounds": harness.bounds, "hostile": harness.hostile, "sandbox": harness.sandbox, "burst": harness.burst,
                 "two_cores": harness.two_cores}
    for name, fn in scenarios.items():
        if args.only and name not in args.only:
            continue
        await fn()
    free_after = shutil.disk_usage(work).free
    ok = all(c["ok"] for c in harness.checks)
    head = sh(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).strip()
    dirty = bool(sh(["git", "-C", str(ROOT), "status", "--porcelain", "--", ".", ":!tasks"]).strip())  # the evidence files themselves are not product code
    report = {"verdict": "PASSED" if ok else "FAILED", "head": head, "tree_dirty": dirty, "platform": platform.platform(),
              "node": sh(["node", "--version"]).strip(), "chrome": (harness.facts.get("availability") or {}).get("browser"),
              "remotion": "4.0.534", "elapsed_s": round(time.monotonic() - started, 1), "timings": harness.timings,
              "disk": {"free_before_mb": free_before >> 20, "free_after_mb": free_after >> 20}, "facts": harness.facts, "checks": harness.checks}
    out = Path(args.evidence)
    out.parent.mkdir(parents=True, exist_ok=True)
    run = {"scenarios": list(args.only or scenarios), "head": head, "tree_dirty": dirty, "elapsed_s": report["elapsed_s"],
           "disk_free_before_mb": free_before >> 20, "disk_free_after_mb": free_after >> 20}
    report["runs"] = [run]
    if args.append and out.is_file():  # the scenarios are run in chunks (a long run is fragile on a loaded machine): one report, every run listed
        before = json.loads(out.read_text(encoding="utf-8"))
        report["runs"] = [*before.get("runs", []), run]
        report["checks"] = [*before["checks"], *harness.checks]
        report["timings"] = {**before.get("timings", {}), **harness.timings}
        report["facts"] = {**before.get("facts", {}), **harness.facts}
        report["elapsed_s"] = round(before.get("elapsed_s", 0) + report["elapsed_s"], 1)
        report["disk"] = {"free_before_mb": before["disk"]["free_before_mb"], "free_after_mb": free_after >> 20}
        report["chrome"] = report["chrome"] or before.get("chrome")
        ok = all(c["ok"] for c in report["checks"])
        report["verdict"] = "PASSED" if ok else "FAILED"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(report["verdict"], f"{sum(c['ok'] for c in report['checks'])}/{len(report['checks'])}")
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--runtime-dir", default=os.environ.get("JARVIS_REMOTION_RUNTIME_DIR", ""))
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--append", action="store_true", help="add this run to an existing evidence file")
    parser.add_argument("--child")
    parser.add_argument("--snapshot")
    ns = parser.parse_args()
    if ns.child:
        raise SystemExit(asyncio.run(child_main(ns)))
    if not ns.runtime_dir:
        raise SystemExit("--runtime-dir (or JARVIS_REMOTION_RUNTIME_DIR) is required")
    raise SystemExit(asyncio.run(amain(ns)))

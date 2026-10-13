"""Run the REAL guarded Jarvis render host (render-guard.cjs + render-host.cjs, copied from the worktree) on the control project."""
import json, os, shutil, subprocess, sys, time
from pathlib import Path
S = Path(sys.argv[1]); comp, w, h, fps, frames = sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
repo = Path("C:/Projects/jarvis/bmp/jarvis/capabilities/remotion")
runtime = S / "runtime"; job = runtime / "render" / "jobs" / ("real-" + comp.lower())
src_work = runtime / "render" / "jobs" / "master" / "work"
if job.exists(): shutil.rmtree(job)
for d in ("tmp", "pages"): (job / d).mkdir(parents=True)
shutil.copytree(src_work, job / "work")
for n in ("render-guard.cjs", "render-host.cjs"): shutil.copyfile(repo / n, job / n)
browser = "C:/Program Files/Google/Chrome/Application/chrome.exe"
spec = {"format": "mp4", "entry": "studio-root.tsx", "composition_id": comp,
        "composition": {"width": w, "height": h, "fps": fps, "durationInFrames": frames}, "props": {}, "frames_total": frames,
        "frame_range": [0, frames - 1], "frames": [], "crf": 23, "scale": 1.0, "concurrency": 1, "jpeg_quality": 90,
        "runtime": str(runtime), "work": str(job / "work"), "bundle_dir": str(job / "bundle"), "progress": str(job / "progress.json"),
        "result": str(job / "result.json"), "pages_dir": str(job / "pages"), "out": str(job / "out.mp4"), "browser": browser}
(job / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
env = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "WINDIR", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "COMSPEC", "PATHEXT")}
env.update(NO_COLOR="1", FORCE_COLOR="0", CI="1", TEMP=str(job / "tmp"), TMP=str(job / "tmp"), JARVIS_RENDER_DIR=str(job),
           JARVIS_RENDER_RUNTIME=str(runtime), JARVIS_RENDER_BROWSER=browser)
t = time.monotonic()
p = subprocess.run(["node", "--max-old-space-size=2048", "--require", str(job / "render-guard.cjs"), str(job / "render-host.cjs"), str(job / "spec.json")],
                   cwd=job / "work", env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
wall = time.monotonic() - t
res = json.loads((job / "result.json").read_text(encoding="utf-8")) if (job / "result.json").exists() else {}
eg = json.loads((job / "egress.json").read_text(encoding="utf-8")) if (job / "egress.json").exists() else {}
print(json.dumps({"composition": comp, "exit": p.returncode, "wall_s": round(wall, 2), "ok": res.get("ok"), "code": res.get("code"),
                  "elapsed_ms": res.get("elapsed_ms"), "message": (res.get("message") or "")[:300],
                  "egress": {k: eg.get(k) for k in ("blocked_connect", "blocked_spawn", "proxy_denied", "browser_launches", "sandbox", "guard_error")},
                  "stderr_tail": p.stderr[-300:]}, indent=1))

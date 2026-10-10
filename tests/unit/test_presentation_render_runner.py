"""Runner du rendu (Remotion Slice 16) : disque réel (`tmp_path`), vrais processus enfants (Python tient lieu de Node), faux ffprobe.

Le vrai Node + le vrai Chrome sont éprouvés par `scripts/remotion_render_harness.py` et `test_presentation_render_real.py` (opt-in).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from jarvis.adapters import process_tree
from jarvis.adapters import remotion_render_runner as R
from jarvis.domain import presentation_render as D
from jarvis.domain import presentation_render_output as O
from jarvis.domain.presentation_render import RenderError, RenderErrorCode as C
from jarvis.ports.remotion_render import BrowserInfo, VerifiedOutput

JOB = "rj_0123456789ab"
BROWSER = BrowserInfo("C:/Chrome/chrome.exe", "chrome 154.0.0.0")

CHILD = r"""
import json, os, sys, time
spec = json.load(open(sys.argv[1]))
mode = os.environ.get("CHILD_MODE", "ok")
def write(name, value): open(spec[name], "w").write(json.dumps(value))
egress = os.path.join(os.path.dirname(spec["progress"]), "egress.json")
if mode == "sleep":
    time.sleep(60)
write("progress", {"phase": "rendering", "frames_done": 3, "frames_total": spec["frames_total"]})
if mode == "grow":
    open(os.path.join(os.path.dirname(spec["progress"]), "bundle.bin"), "wb").write(b"0" * (4 << 20)); time.sleep(60)
if mode == "ok":
    open(spec["out"], "wb").write(b"\x00\x00\x00\x20ftypisom" + b"0" * 32)
    open(egress, "w").write(json.dumps({"proxy_denied": 7, "blocked_connect": 1, "browser_launches": 1, "proxy_port": 40000, "sandbox": True, "guard_error": ""}))
    write("result", {"ok": True, "outputs": [spec["out"]]}); sys.exit(0)
if mode == "composition":
    write("result", {"ok": False, "code": "composition_mismatch", "message": "composition width is 800, the frozen manifest declares 1280"}); sys.exit(1)
if mode == "enospc":
    write("result", {"ok": False, "code": "render_failed", "message": "Error: ENOSPC: no space left on device, write C:\\Users\\me\\x"}); sys.exit(1)
if mode == "crash":
    write("result", {"ok": False, "code": "render_crashed", "message": "uncaughtException: read ECONNRESET"}); sys.exit(1)
if mode == "silent":
    print("a line on stdout"); sys.exit(3)
if mode == "sandbox":
    write("result", {"ok": False, "code": "sandbox_launch_failed", "message": "Failed to launch the browser process"}); sys.exit(1)
if mode == "browser":
    write("result", {"ok": False, "code": "browser_launch_failed", "message": "could not launch the browser"}); sys.exit(1)
if mode == "args":
    open(egress, "w").write(json.dumps({"guard_error": "render_guard_unexpected_args", "unexpected_flags": ["--some-flag"]}))
    write("result", {"ok": False, "code": "render_guard_unexpected_args", "message": "x"}); sys.exit(1)
if mode == "noguard":
    open(spec["out"], "wb").write(b"\x00\x00\x00\x20ftypisom" + b"0" * 32)
    open(egress, "w").write(json.dumps({"browser_launches": 0, "proxy_port": 0}))
    write("result", {"ok": True, "outputs": [spec["out"]]}); sys.exit(0)
"""


class Rig:
    pass


def make(tmp_path, *, mode="ok", free=lambda path: 10 << 30, env=None) -> Rig:
    rig = Rig()
    rig.runtime = tmp_path / "runtime"
    (rig.runtime / "node_modules" / "@remotion" / "bundler").mkdir(parents=True)
    (rig.runtime / "node_modules" / "@remotion" / "renderer").mkdir(parents=True)
    for package in ("bundler", "renderer"):
        (rig.runtime / "node_modules" / "@remotion" / package / "package.json").write_text("{}")
    rig.spawned = []

    def spawn(argv, *, cwd, env, log_path):
        rig.spawned.append({"argv": list(argv), "cwd": cwd, "env": dict(env)})
        child_env = {**os.environ, "CHILD_MODE": mode}
        with open(log_path, "ab") as log:
            return subprocess.Popen([sys.executable, "-c", CHILD, argv[-1]], cwd=str(cwd), env=child_env, stdout=log, stderr=subprocess.STDOUT)

    rig.runner = R.RemotionRenderRunner(lambda: rig.runtime, which=lambda name: "node" if name == "node" else None, spawn=spawn,
                                        environ=env if env is not None else {"PATH": "x", "SYSTEMROOT": "C:\\Windows", "HTTPS_PROXY": "http://corp:3128",
                                                                            "OPENAI_API_KEY": "sk-secret", "JARVIS_TOKEN": "t" * 40, "TEMP": "C:\\Temp"},
                                        free_bytes=free)
    return rig


def spec(**changes):
    base = {"format": "mp4", "frames_total": 30, "frame_range": [0, 29]}
    base.update(changes)
    return base


def run(rig, job_id=JOB, *, cancel=None, timeout_s=30.0, **spec_changes):
    rig.runner.prepare(job_id, {"src/Scene.tsx": b"x", "studio-root.tsx": b"y"})
    started, progress = [], []
    outcome = rig.runner.run(job_id, spec(**spec_changes), browser=BROWSER, cancel=cancel or threading.Event(), timeout_s=timeout_s,
                             on_start=started.append, on_progress=progress.append)
    return outcome, started, progress


# ------------------------------------------------------------------ prepare


def test_prepare_writes_exactly_the_frozen_files_and_the_shipped_guard_and_host(tmp_path):
    rig = make(tmp_path)
    rig.runner.prepare(JOB, {"src/Scene.tsx": b"scene", "public/dot.png": b"\x89PNG", "studio-root.tsx": b"root"})
    job = rig.runtime / "render" / "jobs" / JOB
    assert (job / "work" / "src" / "Scene.tsx").read_bytes() == b"scene" and (job / "work" / "public" / "dot.png").read_bytes() == b"\x89PNG"
    assert sorted(p.name for p in job.iterdir()) == ["pages", "render-guard.cjs", "render-host.cjs", "tmp", "work"]
    assert (job / R.GUARD_FILE).read_bytes() == (R.SHIPPED_DIR / R.GUARD_FILE).read_bytes()
    rig.runner.prepare(JOB, {"src/Other.tsx": b"o"})  # a second prepare starts from a clean folder
    assert [p.name for p in (job / "work").rglob("*") if p.is_file()] == ["Other.tsx"]


@pytest.mark.parametrize("path", ["../escape.tsx", "/abs.tsx", "src//x.tsx", "src/./x.tsx", "C:/x.tsx", "src\\x.tsx", "src/x.tsx\x00"])
def test_prepare_refuses_a_path_that_could_leave_the_work_folder_before_writing_anything(tmp_path, path):
    rig = make(tmp_path)
    with pytest.raises(RenderError) as refused:
        rig.runner.prepare(JOB, {"src/Scene.tsx": b"ok", path: b"bad"})
    assert refused.value.code is C.SOURCE_REFUSED
    assert not (tmp_path / "escape.tsx").exists()


def test_prepare_refuses_a_disk_that_is_too_full_and_writes_nothing(tmp_path):
    rig = make(tmp_path, free=lambda path: 100 << 20)
    with pytest.raises(RenderError) as refused:
        rig.runner.prepare(JOB, {"src/Scene.tsx": b"x"})
    assert refused.value.code is C.DISK_LOW and refused.value.status == 507 and "100 MiB free" in refused.value.detail
    assert not (rig.runtime / "render" / "jobs" / JOB / "work").exists()


def test_a_job_id_must_have_the_exact_shape(tmp_path):
    rig = make(tmp_path)
    for bad in ("", "rj_", "../x", "rj_0123456789abc", "RJ_0123456789ab", "rj_0123456789ag"):
        with pytest.raises(RenderError):
            rig.runner.job_dir(bad)


def test_the_runtime_must_have_node_the_bundler_and_the_renderer(tmp_path):
    rig = make(tmp_path)
    assert rig.runner.runtime_ready() is None
    (rig.runtime / "node_modules" / "@remotion" / "renderer" / "package.json").unlink()
    assert rig.runner.runtime_ready().startswith("renderer_missing")
    no_node = R.RemotionRenderRunner(lambda: rig.runtime, which=lambda name: None)
    assert no_node.runtime_ready().startswith("node_missing")


# ------------------------------------------------------------------ the browser


def test_the_browser_is_the_explicit_setting_then_the_usual_installs_and_never_a_download(tmp_path):
    exe = tmp_path / "Chrome" / "Application" / "chrome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    (exe.parent / "153.0.1.2").mkdir()
    (exe.parent / "154.0.8037.99").mkdir()
    (exe.parent / "not-a-version").mkdir()
    found = R.RemotionRenderRunner(lambda: tmp_path, environ={"JARVIS_REMOTION_RENDER_BROWSER": str(exe)}).find_browser()
    assert found == BrowserInfo(str(exe), "chrome 154.0.8037.99")
    # an explicit setting that does not exist is NOT replaced by another browser
    assert R.RemotionRenderRunner(lambda: tmp_path, environ={"JARVIS_REMOTION_RENDER_BROWSER": str(tmp_path / "nope.exe")}).find_browser() is None
    assert R.RemotionRenderRunner(lambda: tmp_path, environ={}, which=lambda name: None).find_browser() is None or sys.platform == "win32"
    edge = tmp_path / "Edge" / "msedge.exe"
    edge.parent.mkdir()
    edge.write_text("")
    assert R.RemotionRenderRunner(lambda: tmp_path, environ={"JARVIS_REMOTION_RENDER_BROWSER": str(edge)}).find_browser().version == "unknown"


def test_the_browser_version_is_never_obtained_by_launching_it(tmp_path):
    source = Path(R.__file__).read_text(encoding="utf-8")
    body = source.split("def _version_of")[1].split("def _ffprobe")[0].split('"""')[2]  # the code, not the docstring that explains why
    assert "subprocess" not in body and "Popen" not in body and "spawn" not in body and "scandir" in body


# ------------------------------------------------------------------ run


def test_the_process_gets_an_allow_listed_environment_without_proxy_or_secret_and_a_job_private_temp(tmp_path):
    rig = make(tmp_path)
    outcome, started, progress = run(rig)
    assert outcome.ok is True
    env = rig.spawned[0]["env"]
    assert "OPENAI_API_KEY" not in env and "JARVIS_TOKEN" not in env and not {"HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"} & {k.upper() for k in env}
    job = rig.runtime / "render" / "jobs" / JOB
    assert env["TEMP"] == env["TMP"] == str(job / "tmp") and env["JARVIS_RENDER_DIR"] == str(job)
    assert env["JARVIS_RENDER_RUNTIME"] == str(rig.runtime) and env["JARVIS_RENDER_BROWSER"] == BROWSER.path
    assert sorted(k for k in env if k.startswith("JARVIS_")) == ["JARVIS_RENDER_BROWSER", "JARVIS_RENDER_DIR", "JARVIS_RENDER_RUNTIME"]
    assert "JARVIS_REMOTION_RENDER_NO_SANDBOX" not in env, "the sandbox stays on unless the user asked otherwise"
    argv = rig.spawned[0]["argv"]
    assert argv[0] == "node" and "--max-old-space-size=2048" in argv and argv[argv.index("--require") + 1] == str(job / R.GUARD_FILE)
    assert rig.spawned[0]["cwd"] == job / "work"


def test_a_successful_run_reports_start_progress_outputs_and_the_egress_the_guard_counted(tmp_path):
    rig = make(tmp_path)
    outcome, started, progress = run(rig)
    assert outcome.ok and len(started) == 1 and process_tree.parse_process_ref(started[0]) is not None
    assert progress and progress[-1]["frames_done"] == 3
    assert [p.name for p in outcome.outputs] == ["out.mp4"] and outcome.egress["proxy_denied"] == 7 and outcome.egress["blocked_connect"] == 1
    assert outcome.egress["sandbox"] is True and outcome.egress["browser_launches"] == 1
    full = json.loads((rig.runtime / "render" / "jobs" / JOB / "spec.json").read_text())
    assert full["browser"] == BROWSER.path and full["runtime"] == str(rig.runtime) and full["frames_total"] == 30 and full["out"].endswith("out.mp4")
    assert not process_tree.ref_alive(started[0])


@pytest.mark.parametrize("mode,code,needle", [("composition", C.COMPOSITION_MISMATCH, "declares 1280"), ("enospc", C.DISK_FULL, "<path>"),
                                              ("crash", C.CRASHED, "ECONNRESET"), ("silent", C.FAILED, "a line on stdout"),
                                              ("sandbox", C.SANDBOX_UNAVAILABLE, "JARVIS_REMOTION_RENDER_NO_SANDBOX=1"),
                                              ("browser", C.BROWSER_UNAVAILABLE, "launch"), ("args", C.GUARD_UNEXPECTED_ARGS, "--some-flag"),
                                              ("noguard", C.GUARD_NOT_APPLIED, "rewritten browser launch")])
def test_a_failed_process_is_a_typed_outcome_without_a_machine_path(tmp_path, mode, code, needle):
    rig = make(tmp_path, mode=mode)
    outcome, _, _ = run(rig)
    assert outcome.ok is False and outcome.code == code.value and needle in outcome.detail
    assert "C:\\Users" not in outcome.detail
    assert rig.runner.sweep(JOB) == 0  # nothing left over for the sweep to find


def test_a_run_past_its_deadline_is_killed_and_says_which_limit(tmp_path):
    rig = make(tmp_path, mode="sleep")
    started_at = time.monotonic()
    outcome, started, _ = run(rig, timeout_s=1.5)
    assert outcome.code == C.TIMEOUT.value and "1 s limit" in outcome.detail and time.monotonic() - started_at < 20
    assert not process_tree.ref_alive(started[0])


def test_cancel_kills_the_process_tree_within_a_second_or_two(tmp_path):
    rig = make(tmp_path, mode="sleep")
    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    started_at = time.monotonic()
    outcome, started, _ = run(rig, cancel=cancel)
    assert outcome.code == C.CANCELLED.value and time.monotonic() - started_at < 15 and not process_tree.ref_alive(started[0])


def test_a_job_folder_that_outgrows_its_bound_is_killed(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "MAX_JOB_DIR_BYTES", 1 << 20)
    rig = make(tmp_path, mode="grow")
    outcome, started, _ = run(rig)
    assert outcome.code == C.JOB_TOO_LARGE.value and "1 MiB" in outcome.detail and not process_tree.ref_alive(started[0])


def test_a_disk_that_fills_during_the_render_kills_it(tmp_path):
    calls = {"n": 0}

    def shrinking(path):
        calls["n"] += 1
        return 10 << 30 if calls["n"] == 1 else 1 << 20

    rig = make(tmp_path, mode="sleep", free=shrinking)
    outcome, started, _ = run(rig)
    assert outcome.code == C.DISK_FULL.value and "nearly full" in outcome.detail and not process_tree.ref_alive(started[0])


def test_a_process_that_cannot_be_launched_is_a_runtime_error_not_an_exception(tmp_path):
    rig = make(tmp_path)

    def broken(argv, *, cwd, env, log_path):
        raise FileNotFoundError("node")

    rig.runner._spawn = broken
    outcome, started, _ = run(rig)
    assert outcome.code == C.RUNTIME_UNAVAILABLE.value and started == [] and "FileNotFoundError" in outcome.detail


# ------------------------------------------------------------------ verification of the output


def write_job_file(rig, name: str, data: bytes) -> Path:
    job = rig.runtime / "render" / "jobs" / JOB
    job.mkdir(parents=True, exist_ok=True)
    (job / "pages").mkdir(exist_ok=True)
    path = job / name
    path.write_bytes(data)
    return path


def test_a_still_is_checked_for_signature_and_exact_size(tmp_path):
    from tests.unit.test_presentation_render_domain import png
    rig = make(tmp_path)
    write_job_file(rig, "out.png", png(1280, 720))
    ok = rig.runner.verify(JOB, "still", width=1280, height=720, frames=None, pages=None)
    assert ok.verified_by == "png" and ok.size_bytes > 0 and len(ok.sha256) == 64 and (ok.width, ok.height) == (1280, 720)
    for kwargs, needle in (({"width": 640, "height": 360}, "expected 640x360"),):
        with pytest.raises(RenderError) as refused:
            rig.runner.verify(JOB, "still", frames=None, pages=None, **kwargs)
        assert refused.value.code is C.OUTPUT_INVALID and needle in refused.value.detail
    write_job_file(rig, "out.png", b"GIF89a" + b"0" * 40)
    with pytest.raises(RenderError) as lie:
        rig.runner.verify(JOB, "still", width=1280, height=720, frames=None, pages=None)
    assert "PNG" in lie.value.detail


def test_missing_empty_and_oversized_outputs_are_refused(tmp_path, monkeypatch):
    rig = make(tmp_path)
    write_job_file(rig, "keep", b"")
    with pytest.raises(RenderError) as missing:
        rig.runner.verify(JOB, "mp4", width=1, height=1, frames=1, pages=None)
    assert "without producing" in missing.value.detail
    write_job_file(rig, "out.mp4", b"")
    with pytest.raises(RenderError) as empty:
        rig.runner.verify(JOB, "mp4", width=1, height=1, frames=1, pages=None)
    assert "empty" in empty.value.detail
    monkeypatch.setattr(D, "MAX_OUTPUT_BYTES", 10)
    write_job_file(rig, "out.mp4", b"\x00\x00\x00\x20ftypisom" + b"0" * 32)
    with pytest.raises(RenderError) as huge:
        rig.runner.verify(JOB, "mp4", width=1, height=1, frames=1, pages=None)
    assert huge.value.code is C.OUTPUT_TOO_LARGE


def fake_probe(monkeypatch, rig, stdout: str, returncode: int = 0):
    ffprobe = rig.runtime / "node_modules" / "@remotion" / "compositor-test" / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    ffprobe.parent.mkdir(parents=True, exist_ok=True)
    ffprobe.write_text("")
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, returncode, stdout, "boom at C:\\Users\\me\\x" if returncode else "")

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    return seen


def probe_json(**stream):
    base = {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720, "nb_frames": "30", "r_frame_rate": "30/1", "duration": "1.000000"}
    return json.dumps({"streams": [{**base, **stream}], "format": {"duration": "1.0"}})


def test_an_mp4_is_verified_by_the_pinned_ffprobe_dimensions_codec_and_frame_count(tmp_path, monkeypatch):
    rig = make(tmp_path)
    write_job_file(rig, "out.mp4", b"\x00\x00\x00\x20ftypisom" + b"0" * 32)
    seen = fake_probe(monkeypatch, rig, probe_json())
    ok = rig.runner.verify(JOB, "mp4", width=1280, height=720, frames=30, pages=None)
    assert (ok.verified_by, ok.frames, ok.duration_ms, ok.width) == ("ffprobe", 30, 1000, 1280) and "-show_entries" in seen[0] and "-of" in seen[0]
    for stdout, needle in ((probe_json(nb_frames="29"), "29 frames"), (probe_json(width=1920), "1920x720"), (probe_json(codec_name="vp9"), "vp9"),
                           ("not json", "not readable")):
        fake_probe(monkeypatch, rig, stdout)
        with pytest.raises(RenderError) as refused:
            rig.runner.verify(JOB, "mp4", width=1280, height=720, frames=30, pages=None)
        assert refused.value.code is C.OUTPUT_INVALID and needle in refused.value.detail, stdout
    fake_probe(monkeypatch, rig, "", returncode=1)
    with pytest.raises(RenderError) as failed:
        rig.runner.verify(JOB, "mp4", width=1280, height=720, frames=30, pages=None)
    assert "C:\\Users" not in failed.value.detail and "<path>" in failed.value.detail


def test_without_a_pinned_ffprobe_the_header_check_alone_is_said_so(tmp_path):
    rig = make(tmp_path)
    write_job_file(rig, "out.mp4", b"\x00\x00\x00\x20ftypisom" + b"0" * 32)
    assert rig.runner.verify(JOB, "mp4", width=1280, height=720, frames=30, pages=None).verified_by == "header"
    write_job_file(rig, "out.mp4", b"\x00\x00\x00\x20moovisom" + b"0" * 32)
    with pytest.raises(RenderError) as lie:
        rig.runner.verify(JOB, "mp4", width=1280, height=720, frames=30, pages=None)
    assert "ftyp" in lie.value.detail


def test_a_pdf_is_assembled_from_the_page_images_and_checked(tmp_path):
    from tests.unit.test_presentation_render_domain import jpeg
    rig = make(tmp_path)
    write_job_file(rig, "keep", b"")
    pages = rig.runtime / "render" / "jobs" / JOB / "pages"
    for index in (1, 2, 3):
        (pages / f"page-{index:02d}.jpg").write_bytes(jpeg(1280, 720))
    ok = rig.runner.verify(JOB, "pdf", width=1280, height=720, frames=None, pages=3)
    assert ok.verified_by == "pdf" and ok.pages == 3 and O.pdf_page_count(ok.path.read_bytes()) == 3
    with pytest.raises(RenderError) as count:
        rig.runner.verify(JOB, "pdf", width=1280, height=720, frames=None, pages=4)
    assert "expected 4 page images, found 3" in count.value.detail
    (pages / "page-03.jpg").write_bytes(jpeg(640, 360))
    with pytest.raises(RenderError) as size:
        rig.runner.verify(JOB, "pdf", width=1280, height=720, frames=None, pages=3)
    assert "not 1280x720" in size.value.detail


def test_the_verified_file_is_copied_by_blocks(tmp_path):
    rig = make(tmp_path)
    path = write_job_file(rig, "out.mp4", b"x" * (R.COPY_CHUNK + 5))
    chunks = []
    rig.runner.copy_output(JOB, VerifiedOutput(path, path.stat().st_size, "0" * 64, 1, 1, None, None, None, "header"), chunks.append)
    assert [len(c) for c in chunks] == [R.COPY_CHUNK, 5]


# ------------------------------------------------------------------ traces, recovery, clean-up


def test_cleanup_keeps_only_the_small_traces(tmp_path):
    rig = make(tmp_path)
    run(rig)
    rig.runner.write_record(JOB, {"job_id": JOB, "state": "complete"})
    rig.runner.cleanup(JOB)
    kept = sorted(p.name for p in (rig.runtime / "render" / "jobs" / JOB).iterdir())
    assert kept == ["egress.json", "job.json", "render.log", "result.json"] or set(kept) <= {"egress.json", "job.json", "render.log", "result.json"}
    assert "work" not in kept and "bundle" not in kept and "tmp" not in kept


def test_records_are_read_back_and_a_damaged_one_is_flagged_not_trusted(tmp_path):
    rig = make(tmp_path)
    rig.runner.write_record(JOB, {"job_id": JOB, "state": "running", "process_ref": "1:2"})
    other = rig.runtime / "render" / "jobs" / "rj_ffffffffffff"
    other.mkdir()
    (other / "job.json").write_text("{broken")
    wrong = rig.runtime / "render" / "jobs" / "rj_eeeeeeeeeeee"
    wrong.mkdir()
    (wrong / "job.json").write_text(json.dumps({"job_id": "rj_other0000000"}))
    (rig.runtime / "render" / "jobs" / "not-a-job").mkdir()
    records = {r["job_id"]: r for r in rig.runner.records()}
    assert records[JOB]["process_ref"] == "1:2" and records["rj_ffffffffffff"] == {"job_id": "rj_ffffffffffff", "unreadable": True}
    assert records["rj_eeeeeeeeeeee"].get("unreadable") is True and "not-a-job" not in records
    assert not list((rig.runtime / "render" / "jobs" / JOB).glob("*.tmp"))


def test_prune_keeps_the_newest_job_folders(tmp_path):
    rig = make(tmp_path)
    ids = [f"rj_{n:012x}" for n in range(1, 6)]
    for index, job_id in enumerate(ids):
        rig.runner.write_record(job_id, {"job_id": job_id})
        folder = rig.runtime / "render" / "jobs" / job_id
        os.utime(folder, (1000 + index, 1000 + index))
    assert rig.runner.prune(2) == 3
    assert sorted(p.name for p in (rig.runtime / "render" / "jobs").iterdir()) == ids[3:]


def test_stop_never_kills_a_program_that_only_reuses_the_pid(tmp_path):
    rig = make(tmp_path)
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert rig.runner.stop(f"{sleeper.pid}:1") is True and sleeper.poll() is None and rig.runner.alive(f"{sleeper.pid}:1") is False
        ref = process_tree.make_process_ref(sleeper.pid)
        assert rig.runner.alive(ref) is True and rig.runner.stop(ref) is True
        assert sleeper.wait(timeout=10) is not None
        assert rig.runner.stop("garbage") is True and rig.runner.stop("") is True
    finally:
        sleeper.kill()


@pytest.mark.skipif(sys.platform != "win32" and not any(os.access(os.path.join(p, "pgrep"), os.X_OK) for p in os.environ.get("PATH", "").split(os.pathsep)),
                    reason="no process listing tool")
def test_the_sweep_kills_what_carries_this_job_id_and_nothing_else(tmp_path):
    rig = make(tmp_path)
    mine = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", JOB])  # a leftover of this job (its id on the command line)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "rj_aaaaaaaaaaaa"])
    try:
        time.sleep(1.0)
        assert rig.runner.sweep(JOB) >= 1
        assert mine.wait(timeout=10) is not None and other.poll() is None
    finally:
        mine.kill()
        other.kill()


def test_the_explicit_sandbox_opt_out_is_forwarded_only_when_the_user_set_it(tmp_path):
    rig = make(tmp_path, env={"PATH": "x", "JARVIS_REMOTION_RENDER_NO_SANDBOX": "1"})
    run(rig)
    assert rig.spawned[0]["env"]["JARVIS_REMOTION_RENDER_NO_SANDBOX"] == "1"
    other = make(tmp_path / "b", env={"PATH": "x", "JARVIS_REMOTION_RENDER_NO_SANDBOX": "true"})  # only the exact value 1 counts
    run(other)
    assert "JARVIS_REMOTION_RENDER_NO_SANDBOX" not in other.spawned[0]["env"]


# ------------------------------------------------------------------ one live Core per data root


def runner_for(runtime, ref):
    return R.RemotionRenderRunner(lambda: runtime, which=lambda name: "node", self_ref=lambda: ref)


def test_the_lock_belongs_to_one_live_core_and_a_dead_ones_is_taken_over(tmp_path):
    runtime = tmp_path / "runtime"
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        live_ref = process_tree.make_process_ref(live.pid)
        first, second = runner_for(runtime, live_ref), runner_for(runtime, process_tree.make_process_ref(os.getpid()))
        assert first.acquire_lock() is None and (runtime / "render" / "core.lock").is_file()
        assert second.acquire_lock() == live_ref, "a second Core sees the live holder and takes nothing"
        second.release_lock()
        assert (runtime / "render" / "core.lock").is_file(), "a Core never releases a lock it does not hold"
        assert first.acquire_lock() is None, "taking it again from the same Core is fine (a restart in the same life)"
        first.release_lock()
        assert not (runtime / "render" / "core.lock").exists() and second.acquire_lock() is None
        second.release_lock()
    finally:
        live.kill()


def test_a_lock_left_by_a_dead_core_is_replaced(tmp_path):
    runtime = tmp_path / "runtime"
    (runtime / "render").mkdir(parents=True)
    (runtime / "render" / "core.lock").write_text(json.dumps({"ref": "999999:1", "at": 0}))
    assert runner_for(runtime, process_tree.make_process_ref(os.getpid())).acquire_lock() is None
    (runtime / "render" / "core.lock").write_text("{garbage")
    assert runner_for(runtime, process_tree.make_process_ref(os.getpid())).acquire_lock() is None

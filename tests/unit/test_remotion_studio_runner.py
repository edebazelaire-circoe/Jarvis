"""Runner du Studio Remotion : dossier de travail, lancement, identité, arrêt (Slice 11). Faux spawn, vrai disque et vrai HTTP de boucle locale.

Le processus Node réel et le garde réseau sont dans `test_remotion_studio_guard.py` (Node seul) et `test_remotion_studio_real.py`
(environnement Remotion installé, `JARVIS_REMOTION_RUNTIME_DIR`).
"""

from __future__ import annotations

import http.server
import json
import os
from pathlib import Path
import threading

import pytest

from jarvis.adapters import remotion_studio_runner as R
from jarvis.adapters.remotion_studio_runner import RemotionStudioRunner
from jarvis.domain import remotion_studio as D
from jarvis.domain.remotion_studio import StudioError, StudioErrorCode as C
from tests.unit.test_remotion_studio import PIN, source_for

CLI = Path("node_modules") / "@remotion" / "cli" / "remotion-cli.js"


@pytest.fixture
def runtime(tmp_path):
    runtime = tmp_path / "local_capabilities" / "remotion" / "runtime"
    (runtime / CLI.parent).mkdir(parents=True)
    (runtime / CLI).write_text("// fake cli", encoding="utf-8")
    return runtime


def make(runtime, **options):
    options.setdefault("which", lambda name: "/fake/node")
    options.setdefault("environ", {"PATH": "/bin", "JARVIS_CORE_TOKEN": "sekret", "OPENAI_API_KEY": "sk-1", "HOME": "/home/u"})
    return RemotionStudioRunner(lambda: runtime, **options)


def files(suffix=""):
    return D.plan_workspace(source_for(PIN), {"title": "A"}) | ({"src/extra.ts": suffix.encode()} if suffix else {})


class FakeServer:
    """Un vrai serveur HTTP de boucle locale qui joue le Studio : /__jarvis_studio__/health et /."""

    def __init__(self, launch_id="", root_ok=True):
        self.launch_id, self.root_ok = launch_id, root_ok
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == R.HEALTH_PATH:
                    body = json.dumps({"ok": True, "pid": 1, "launch": outer.launch_id}).encode()
                else:
                    body = b"<html><title>Remotion Studio</title></html>" if outer.root_ok else b"nope"
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


# ------------------------------------------------------------------ dossier de travail

def test_sync_work_writes_exactly_the_files_read_only_and_records_them(runtime):
    runner = make(runtime)
    report = runner.sync_work(files())
    work = runtime / "studio" / "work"
    assert report.written == len(files()) and report.removed == 0 and report.edits_saved == ()
    assert (work / "src" / "Scene.tsx").read_bytes() == files()["src/Scene.tsx"]
    assert {p.relative_to(work).as_posix() for p in work.rglob("*") if p.is_file()} == set(files())
    assert not os.access(work / "src" / "Scene.tsx", os.W_OK), "the work copy is read-only: a Studio save cannot write it"
    assert runner.modified_work() == ()
    assert not (runtime / "studio" / ".tmp").exists()


def test_sync_work_touches_only_what_changed_so_hot_reload_sees_one_file(runtime):
    runner = make(runtime)
    runner.sync_work(files())
    target = runtime / "studio" / "work" / "src" / "lib" / "Title.tsx"
    before = target.stat().st_mtime_ns
    changed = dict(files())
    changed["src/lib/Title.tsx"] = changed["src/lib/Title.tsx"] + b"// edit\n"
    report = runner.sync_work(changed)
    assert (report.written, report.unchanged) == (1, len(changed) - 1)
    assert target.read_bytes().endswith(b"// edit\n") and target.stat().st_mtime_ns != before


def test_sync_work_removes_files_the_new_version_no_longer_has(runtime):
    runner = make(runtime)
    runner.sync_work(files("// x"))
    work = runtime / "studio" / "work"
    assert (work / "src" / "extra.ts").exists()
    report = runner.sync_work(files())
    assert report.removed == 1 and not (work / "src" / "extra.ts").exists()


def test_a_file_edited_outside_jarvis_is_saved_aside_then_replaced(runtime):
    runner = make(runtime)
    runner.sync_work(files())
    scene = runtime / "studio" / "work" / "src" / "Scene.tsx"
    os.chmod(scene, 0o666)
    scene.write_text("// hand edit in the Studio\n", encoding="utf-8")
    assert runner.modified_work() == ("src/Scene.tsx",)
    report = runner.sync_work(files())
    assert report.edits_saved == ("src/Scene.tsx",)
    saved = list((runtime / "studio" / "edits").glob("*/src/Scene.tsx"))
    assert len(saved) == 1 and saved[0].read_text(encoding="utf-8") == "// hand edit in the Studio\n"
    assert scene.read_bytes() == files()["src/Scene.tsx"] and runner.modified_work() == ()


def test_saved_edits_are_bounded_and_never_silently_dropped_before_the_bound(runtime):
    runner = make(runtime)
    runner.sync_work(files())
    scene = runtime / "studio" / "work" / "src" / "Scene.tsx"
    for index in range(D.MAX_SAVED_EDITS + 2):
        os.chmod(scene, 0o666)
        scene.write_text(f"// {index}\n", encoding="utf-8")
        assert runner.save_modified() == ("src/Scene.tsx",)
        runner.sync_work(files())
    assert len(list((runtime / "studio" / "edits").iterdir())) == D.MAX_SAVED_EDITS


def test_a_stray_file_added_to_the_work_folder_is_reported_and_removed(runtime):
    runner = make(runtime)
    runner.sync_work(files())
    stray = runtime / "studio" / "work" / "src" / "evil.ts"
    stray.write_text("export {}", encoding="utf-8")
    assert runner.modified_work() == ("src/evil.ts",)
    report = runner.sync_work(files())
    assert report.removed == 1 and not stray.exists() and report.edits_saved == ("src/evil.ts",)


def test_the_tool_cache_inside_the_work_folder_is_neither_counted_nor_removed(runtime):
    runner = make(runtime)
    runner.sync_work(files())
    cache = runtime / "studio" / "work" / "node_modules" / ".cache" / "webpack"
    cache.mkdir(parents=True)
    for index in range(R.MAX_WORK_FILES + 20):  # bien plus de fichiers que la borne de la source
        (cache / f"{index}.pack").write_bytes(b"x")
    assert runner.modified_work() == ()
    report = runner.sync_work(files())
    assert report.removed == 0 and len(list(cache.iterdir())) == R.MAX_WORK_FILES + 20


def test_a_top_level_file_added_by_hand_is_seen_and_removed_because_the_studio_would_read_it(runtime):
    runner = make(runtime)
    runner.sync_work(files())
    config = runtime / "studio" / "work" / "remotion.config.ts"
    config.write_text("export {}", encoding="utf-8")
    assert runner.modified_work() == ("remotion.config.ts",)
    assert runner.sync_work(files()).edits_saved == ("remotion.config.ts",) and not config.exists()


def test_a_source_folder_replaced_by_a_link_is_refused_or_removed_never_followed(runtime, tmp_path):
    from tests.fakes.links import make_dir_link
    runner = make(runtime)
    runner.sync_work(files())
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    work = runtime / "studio" / "work"
    R._remove_tree(work / "public")
    make_dir_link(work / "public", outside)
    assert runner.modified_work() != ()
    runner.sync_work(files())
    assert outside.exists() and not (work / "public").is_symlink()


def test_a_directory_link_planted_in_the_work_folder_is_removed_never_followed(runtime, tmp_path):
    from tests.fakes.links import make_dir_link
    runner = make(runtime)
    runner.sync_work(files())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    work = runtime / "studio" / "work"
    R._remove_tree(work / "src" / "lib")
    make_dir_link(work / "src" / "lib", outside)
    runner.sync_work(files())
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "secret" and not (outside / "Title.tsx").exists()
    assert not (work / "src" / "lib").is_symlink() and (work / "src" / "lib" / "Title.tsx").is_file()
    assert runner.modified_work() == ()


# ------------------------------------------------------------------ lancement

def test_launch_runs_node_with_the_guard_loopback_flags_and_a_clean_environment(runtime):
    server = FakeServer()
    seen = {}

    def spawn(argv, *, cwd, env, log_path):
        seen.update(argv=list(argv), cwd=Path(cwd), env=dict(env))
        server.launch_id = env["JARVIS_STUDIO_LAUNCH"]  # le « Studio » factice répond avec l'identifiant de CE lancement
        return os.getpid()

    runner = make(runtime, spawn=spawn, port_chooser=lambda: server.port)
    runner.sync_work(files())
    try:
        result = runner.launch(port=None)
    finally:
        server.close()
    assert result.port == server.port
    argv = seen["argv"]
    assert argv[0] == "/fake/node" and "--require" in argv and argv[argv.index("--require") + 1].endswith(D.GUARD_FILE)
    assert argv[argv.index("studio") + 1] == D.WORK_ROOT_FILE
    assert {"--no-open", "--ipv4", "--disable-ask-ai", "--disable-git-source"} <= set(argv) and any(a.startswith("--port=") for a in argv)
    assert seen["cwd"] == runtime / "studio" / "work"
    env = seen["env"]
    assert "JARVIS_CORE_TOKEN" not in env and "OPENAI_API_KEY" not in env and "sekret" not in json.dumps(env)
    assert sorted(k for k in env if k.startswith("JARVIS_")) == ["JARVIS_STUDIO_DIR", "JARVIS_STUDIO_IDLE_S", "JARVIS_STUDIO_LAUNCH", "JARVIS_STUDIO_PARENT"]
    assert env["JARVIS_STUDIO_PARENT"] == str(os.getpid())
    assert result.launch_id == env["JARVIS_STUDIO_LAUNCH"] and result.process_ref.startswith(f"{os.getpid()}:")
    guard = runtime / "studio" / D.GUARD_FILE
    assert guard.read_bytes() == R.SHIPPED_GUARD.read_bytes(), "the guard is copied from the shipped file"


def test_a_tampered_guard_copy_is_replaced_at_each_launch(runtime):
    runner = make(runtime)
    (runtime / "studio").mkdir(parents=True)
    guard = runtime / "studio" / D.GUARD_FILE
    guard.write_text("// tampered", encoding="utf-8")
    runner._copy_guard()
    assert guard.read_bytes() == R.SHIPPED_GUARD.read_bytes()


def test_launch_refuses_without_a_materialised_work_folder_or_the_cli(runtime):
    runner = make(runtime)
    with pytest.raises(StudioError) as caught:
        runner.launch(port=None)
    assert caught.value.code is C.START_FAILED and "work_missing" in caught.value.detail
    runner.sync_work(files())
    (runtime / CLI).unlink()
    with pytest.raises(StudioError) as caught:
        runner.launch(port=None)
    assert caught.value.code is C.RUNTIME_UNAVAILABLE and runner.runtime_ready().startswith("cli_missing")


def test_a_busy_configured_port_is_refused_before_spawning(runtime):
    holder = FakeServer()
    spawned = []
    runner = make(runtime, spawn=lambda *a, **k: spawned.append(1) or 1)
    runner.sync_work(files())
    try:
        with pytest.raises(StudioError) as caught:
            runner.launch(port=holder.port)
    finally:
        holder.close()
    assert caught.value.code is C.PORT_UNAVAILABLE and spawned == []


def test_another_program_on_the_port_does_not_pass_the_identity_check(runtime):
    foreign = FakeServer(launch_id="someone-else")
    runner = make(runtime)
    try:
        with pytest.raises(StudioError) as caught:
            runner.probe(foreign.port, "mine")
    finally:
        foreign.close()
    assert caught.value.code is C.HEALTH_FAILED and "another program" in caught.value.detail


def test_a_process_that_exits_during_start_reports_its_log(runtime):
    def spawn(argv, *, cwd, env, log_path):
        Path(log_path).write_text("\x1b[31mError: Cannot find module 'x'\x1b[0m\n", encoding="utf-8")
        return 2_000_000_000  # n'existe pas

    runner = make(runtime, spawn=spawn, port_chooser=lambda: 39999, sleep=lambda s: None)
    runner.sync_work(files())
    with pytest.raises(StudioError) as caught:
        runner.launch(port=None)
    assert caught.value.code is C.START_FAILED and "Cannot find module" in caught.value.detail and "\x1b" not in caught.value.detail


def test_a_studio_that_never_answers_times_out_and_is_killed(runtime, monkeypatch):
    killed = []
    monkeypatch.setattr(R.process_tree, "kill_tree", lambda pid: killed.append(pid) or True)
    ticks = iter(range(0, 10_000))
    runner = make(runtime, spawn=lambda *a, **k: os.getpid(), port_chooser=lambda: 1, clock=lambda: next(ticks) * 20, sleep=lambda s: None,
                  start_timeout_s=50)
    runner.sync_work(files())
    with pytest.raises(StudioError) as caught:
        runner.launch(port=None)
    assert caught.value.code is C.START_TIMEOUT and killed == [os.getpid()]


# ------------------------------------------------------------------ arrêt et identité

def test_stop_never_kills_a_process_whose_identity_changed(runtime, monkeypatch):
    killed = []
    monkeypatch.setattr(R.process_tree, "kill_tree", lambda pid: killed.append(pid) or True)
    runner = make(runtime)
    runner.stop(f"{os.getpid()}:1")  # pid vivant, heure de création différente : un autre programme a réutilisé ce pid
    runner.stop("not a ref")
    assert killed == []
    runner.stop(R.process_tree.make_process_ref(os.getpid()))
    assert killed == [os.getpid()]


def test_a_failed_kill_is_a_typed_error_not_a_silent_success(runtime, monkeypatch):
    monkeypatch.setattr(R.process_tree, "kill_tree", lambda pid: False)
    with pytest.raises(StudioError) as caught:
        make(runtime).stop(R.process_tree.make_process_ref(os.getpid()))
    assert caught.value.code is C.STOP_FAILED


def test_activity_of_another_launch_is_ignored(runtime):
    runner = make(runtime)
    (runtime / "studio").mkdir(parents=True)
    (runtime / "studio" / "activity.json").write_text(json.dumps({"launch": "old", "ws_open": 3}), encoding="utf-8")
    assert runner.activity("new") == {} and runner.activity("old")["ws_open"] == 3


def test_state_round_trip_and_an_unreadable_file_is_typed(runtime):
    runner = make(runtime)
    assert runner.read_state() is None
    runner.write_state({"schema": 1, "x": 1})
    assert runner.read_state() == {"schema": 1, "x": 1}
    (runtime / "studio" / "state.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(StudioError) as caught:
        runner.read_state()
    assert caught.value.code is C.STORE_FAILED


def test_the_operator_port_is_validated(runtime):
    assert make(runtime, environ={"JARVIS_REMOTION_STUDIO_PORT": "45678"}).configured_port() == 45678
    assert make(runtime, environ={}).configured_port() is None
    for bad in ("80", "abc", "99999", "-1"):
        with pytest.raises(StudioError):
            make(runtime, environ={"JARVIS_REMOTION_STUDIO_PORT": bad}).configured_port()

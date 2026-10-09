"""Compilateur de scènes Remotion : processus géré, délai, cache, échecs typés (Slice 05).

Faux processus Node (aucun npm, aucun Node) : le contrat Python (requête, cache, clés, erreurs, élagage, concurrence).
La compilation réelle est dans `tests/unit/test_remotion_compiler_real.py` (Node + esbuild installés) et dans
`scripts/remotion_compile_harness.py`. Contrat : `docs/remotion-source.md` §5.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time

import pytest

from jarvis.adapters.process_tree import ProcessResult
from jarvis.adapters.remotion_compiler import RemotionCompiler, read_installed_engine, shipped_engine_pin
from jarvis.domain import remotion_compile as rc
from jarvis.domain.prefab import parse_candidate
from tests.fakes.remotion_scene import PNG_1X1, scene_candidate, scene_files

INSTALLED = {"installed": {"remotion": "4.0.534", "react": "19.3.0"}, "lock_sha256": "a" * 64}


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, level, dict(data or {})))

    def kinds(self):
        return [kind for kind, _, _ in self.events]


def ok_build(request, out):
    name = "scene.js" if request["target"] == "scene" else "host.js"
    (out / name).write_text(f"/* {request['target']} */var JarvisScene={{}};", encoding="utf-8")
    (out / "result.json").write_text(json.dumps({"ok": True, "files": [], "warnings": 1}), encoding="utf-8")
    return ProcessResult(0, "{}", False, 0.1)


class FakeRunner:
    def __init__(self, build=ok_build):
        self.build = build
        self.calls: list[dict] = []
        self.timeouts: list[float] = []
        self.args: list[list[str]] = []

    def run_script(self, runtime_dir, args, *, timeout_s):
        request = json.loads(Path(args[1]).read_text(encoding="utf-8"))
        self.calls.append(request)
        self.timeouts.append(timeout_s)
        self.args.append(list(args))
        return self.build(request, Path(request["out_dir"]))


@pytest.fixture
def env(tmp_path):
    runtime = tmp_path / "local_capabilities" / "remotion" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "install-record.json").write_text(json.dumps(INSTALLED), encoding="utf-8")
    return runtime


def make(env, runner=None, *, ready=None, **options):
    runner = runner or FakeRunner()
    recorder = Recorder()
    compiler = RemotionCompiler(runner=runner, runtime_dir=env, cache_dir=env.parent / "compiled",
                                readiness=lambda: ready, diagnostics=recorder, **options)
    return compiler, runner, recorder


def source_of(prefab_id="presentation-studio.p000000000001.s000000000001", **options):
    return parse_candidate(scene_candidate(prefab_id, **options)).remotion_source()


def failing(code, message="boom", diagnostics=()):
    def build(request, out):
        (out / "result.json").write_text(json.dumps({"ok": False, "code": code, "message": message,
                                                     "diagnostics": list(diagnostics)}), encoding="utf-8")
        return ProcessResult(3, "{}", False, 0.1)
    return build


# ------------------------------------------------------------------ chemin normal


def test_a_scene_compiles_through_one_managed_process_and_lands_in_the_cache(env):
    compiler, runner, recorder = make(env)
    source = source_of()
    artifact = compiler.compile_scene(source)
    assert artifact.target is rc.CompileTarget.SCENE and not artifact.reused
    assert [f.path for f in artifact.files] == ["public/dot.png", "scene.js"]
    cache = env.parent / "compiled" / artifact.cache_key
    assert (cache / "scene.js").is_file() and (cache / "public" / "dot.png").read_bytes() == PNG_1X1
    assert json.loads((cache / "compile.json").read_text("utf-8"))["source_digest"] == source.digest
    assert not [p for p in (env.parent / "compiled").iterdir() if p.name.startswith(".tmp-")]
    request = runner.calls[0]
    assert request["contract"] == 1 and request["target"] == "scene" and request["entry"] == "src/Scene.tsx"
    assert set(request["modules"]) == {"src/Scene.tsx", "src/lib/Title.tsx", "src/theme.json"}
    assert request["allowed_imports"] == list(rc.SCENE_ALLOWED_IMPORTS) and request["digest"] == source.digest
    assert runner.args[0][0] == "--compile" and runner.timeouts == [rc.SCENE_TIMEOUT_S]
    assert "remotion.compile.done" in recorder.kinds()
    assert artifact.warnings == 1 and artifact.duration_ms >= 0


def test_the_same_content_is_compiled_once_even_after_a_restart(env):
    compiler, runner, recorder = make(env)
    first = compiler.compile_scene(source_of())
    second = compiler.compile_scene(source_of())
    assert len(runner.calls) == 1 and second.reused and second.cache_key == first.cache_key
    restarted, runner2, recorder2 = make(env)  # new process: new compiler object, same disk
    third = restarted.compile_scene(source_of())
    assert runner2.calls == [] and third.reused and third.files == first.files
    assert "remotion.compile.reused" in recorder2.kinds()


def test_the_key_is_the_content_not_the_prefab_identity(env):
    compiler, runner, _ = make(env)
    one = compiler.compile_scene(source_of("presentation-studio.p000000000001.s000000000001"))
    two = compiler.compile_scene(source_of("presentation-studio.p000000000009.s000000000009"))
    assert one.cache_key == two.cache_key and len(runner.calls) == 1
    three = compiler.compile_scene(source_of(files=scene_files("// changed\n")))
    assert three.cache_key != one.cache_key and len(runner.calls) == 2


def test_the_key_follows_the_installed_tree_the_import_list_and_minification(env):
    compiler, runner, _ = make(env)
    base = compiler.compile_scene(source_of()).cache_key
    assert compiler.compile_scene(source_of(), minify=False).cache_key != base
    narrower = RemotionCompiler(runner=runner, runtime_dir=env, cache_dir=env.parent / "compiled", readiness=lambda: None,
                                allowed_imports=("react", "remotion"))
    assert narrower.compile_scene(source_of()).cache_key != base
    (env / "install-record.json").write_text(json.dumps({**INSTALLED, "lock_sha256": "b" * 64}), encoding="utf-8")
    assert compiler.compile_scene(source_of()).cache_key != base  # a repaired/updated tree never reuses old bundles


def test_a_damaged_cache_entry_is_rebuilt_not_trusted(env):
    compiler, runner, _ = make(env)
    artifact = compiler.compile_scene(source_of())
    (env.parent / "compiled" / artifact.cache_key / "scene.js").write_text("tampered", encoding="utf-8")
    again = compiler.compile_scene(source_of())
    assert not again.reused and len(runner.calls) == 2
    assert (env.parent / "compiled" / artifact.cache_key / "scene.js").read_text("utf-8").startswith("/* scene */")


def test_the_host_bundle_is_keyed_by_the_installed_tree_only(env):
    compiler, runner, _ = make(env)
    host = compiler.compile_host()
    assert host.target is rc.CompileTarget.HOST and host.cache_key.startswith("host-") and host.source_digest is None
    assert [f.path for f in host.files] == ["host.js"] and runner.timeouts == [rc.HOST_TIMEOUT_S]
    assert compiler.compile_host().reused and len(runner.calls) == 1
    assert compiler.compile_scene(source_of()).cache_key != host.cache_key


def test_engine_drift_is_reported_never_corrected(env):
    compiler, _, _ = make(env)
    artifact = compiler.compile_scene(source_of())  # the fixtures pin lock "aaaa..." == the installed one: no drift
    assert artifact.engine_pinned["lock_sha256"] == "a" * 64 and not artifact.engine_drift
    other = RemotionCompiler(runner=FakeRunner(), runtime_dir=env, cache_dir=env.parent / "compiled2", readiness=lambda: None)
    (env / "install-record.json").write_text(json.dumps({"installed": {"remotion": "4.0.600", "react": "19.3.0"},
                                                          "lock_sha256": "c" * 64}), encoding="utf-8")
    drifted = other.compile_scene(source_of())
    assert drifted.engine_drift and drifted.to_public()["engine_drift"] is True
    assert drifted.engine_installed.remotion_version == "4.0.600" and drifted.engine_pinned["version"] == "4.0.534"


def test_the_public_form_has_no_absolute_path_and_no_port(env, tmp_path):
    compiler, _, _ = make(env)
    text = json.dumps(compiler.compile_scene(source_of()).to_public())
    assert str(tmp_path) not in text and str(tmp_path).replace("\\", "/") not in text
    assert "127.0.0.1" not in text and "localhost" not in text and ":\\" not in text
    body = json.loads(text)
    assert body["entry_file"] == "scene.js" and body["contract"] == 1 and body["target"] == "scene"


def test_concurrent_requests_for_one_key_run_one_process(env):
    gate = threading.Event()

    def slow(request, out):
        gate.wait(5)
        return ok_build(request, out)

    compiler, runner, _ = make(env, FakeRunner(slow))
    results = []
    threads = [threading.Thread(target=lambda: results.append(compiler.compile_scene(source_of()))) for _ in range(3)]
    for thread in threads:
        thread.start()
    time.sleep(0.3)
    gate.set()
    for thread in threads:
        thread.join(10)
    assert len(results) == 3 and len(runner.calls) == 1 and sum(1 for r in results if r.reused) == 2


# ------------------------------------------------------------------ échecs typés


def refused(compiler, source=None, **options):
    with pytest.raises(rc.RemotionCompileError) as caught:
        compiler.compile_scene(source or source_of(), **options)
    return caught.value


def test_a_syntax_error_carries_file_line_and_column_and_leaves_no_cache(env):
    diagnostics = [{"file": "src/Scene.tsx", "line": 12, "column": 7, "text": 'Expected ")" but found "}"'}]
    compiler, _, recorder = make(env, FakeRunner(failing("compile_source_error", "src/Scene.tsx:12:7 Expected", diagnostics)))
    error = refused(compiler)
    assert error.code is rc.CompileErrorCode.SOURCE_ERROR and error.status == 422
    assert error.diagnostics[0].to_dict() == {"file": "src/Scene.tsx", "line": 12, "column": 7, "text": 'Expected ")" but found "}"'}
    assert not [p for p in (env.parent / "compiled").iterdir()]
    kind, level, data = [e for e in recorder.events if e[0] == "remotion.compile.failed"][0]
    assert level == "warning" and data["code"] == "compile_source_error"  # the user's mistake is not a system error


@pytest.mark.parametrize("code,expected", [
    ("compile_import_refused", rc.CompileErrorCode.IMPORT_REFUSED),
    ("compile_entry_invalid", rc.CompileErrorCode.ENTRY_INVALID),
    ("compile_compiler_failed", rc.CompileErrorCode.COMPILER_FAILED),
    ("something_new", rc.CompileErrorCode.COMPILER_FAILED),
])
def test_compiler_codes_map_to_typed_errors(env, code, expected):
    compiler, _, _ = make(env, FakeRunner(failing(code)))
    assert refused(compiler).code is expected


def test_a_timeout_is_typed_and_the_cache_is_clean(env):
    compiler, _, recorder = make(env, FakeRunner(lambda request, out: ProcessResult(None, "", True, 60.0)), scene_timeout_s=60)
    error = refused(compiler)
    assert error.code is rc.CompileErrorCode.TIMEOUT and error.status == 504 and "60 s" in error.message
    assert not [p for p in (env.parent / "compiled").iterdir()]
    assert [e for e in recorder.events if e[0] == "remotion.compile.failed"][0][1] == "warning"


def test_a_crashed_compiler_without_a_result_is_a_system_failure_without_paths(env):
    tail = f"Error: boom at {env}/runtime-host.mjs:9\nSecond line"
    compiler, _, recorder = make(env, FakeRunner(lambda request, out: ProcessResult(1, tail, False, 0.2)))
    error = refused(compiler)
    assert error.code is rc.CompileErrorCode.COMPILER_FAILED and "exit 1" in error.message
    assert str(env) not in error.message and "<capability>" in error.message
    assert [e for e in recorder.events if e[0] == "remotion.compile.failed"][0][1] == "error"


def test_node_missing_is_a_runtime_unavailable_error(env):
    compiler, _, _ = make(env, FakeRunner(lambda request, out: ProcessResult(None, "node_missing", False, 0.0, started=False)))
    assert refused(compiler).code is rc.CompileErrorCode.RUNTIME_UNAVAILABLE


def test_a_capability_that_is_not_ready_is_refused_before_any_process(env):
    compiler, runner, _ = make(env, ready="the Remotion capability is repair_needed (local_capability_health_failed); repair it")
    error = refused(compiler)
    assert error.code is rc.CompileErrorCode.RUNTIME_UNAVAILABLE and "repair" in error.message and error.status == 409
    assert runner.calls == []
    with pytest.raises(rc.RemotionCompileError):
        compiler.compile_host()


def test_a_missing_install_record_is_a_runtime_unavailable_error(env):
    (env / "install-record.json").unlink()
    compiler, runner, _ = make(env)
    assert read_installed_engine(env) is None
    assert refused(compiler).code is rc.CompileErrorCode.RUNTIME_UNAVAILABLE and runner.calls == []


def test_an_oversize_bundle_is_refused_and_not_cached(env):
    def huge(request, out):
        (out / "scene.js").write_bytes(b"x" * (rc.MAX_SCENE_BUNDLE_BYTES + 1))
        (out / "result.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
        return ProcessResult(0, "", False, 0.1)

    compiler, _, _ = make(env, FakeRunner(huge))
    assert refused(compiler).code is rc.CompileErrorCode.OUTPUT_TOO_LARGE
    assert not list((env.parent / "compiled").iterdir())


def test_a_report_that_says_ok_with_a_failing_exit_code_is_not_trusted(env):
    def liar(request, out):
        (out / "scene.js").write_text("x", encoding="utf-8")
        (out / "result.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
        return ProcessResult(3, "", False, 0.1)

    compiler, _, _ = make(env, FakeRunner(liar))
    assert refused(compiler).code is rc.CompileErrorCode.COMPILER_FAILED


def test_a_compile_cache_folder_that_is_a_file_is_a_typed_cache_error(env):
    (env.parent / "compiled").write_text("not a folder", encoding="utf-8")
    compiler, runner, recorder = make(env)
    assert refused(compiler).code is rc.CompileErrorCode.CACHE_IO and runner.calls == []
    assert [e for e in recorder.events if e[0] == "remotion.compile.failed"][0][1] == "error"


def test_every_error_code_has_an_http_status_and_a_serialisable_form():
    assert set(rc.COMPILE_HTTP_STATUS) == set(rc.CompileErrorCode)
    error = rc.RemotionCompileError("compile_timeout", "x" * 400)
    assert len(error.message) == 300 and json.dumps(error.to_dict())


# ------------------------------------------------------------------ servir les sorties, élagage


def test_only_declared_output_files_resolve_to_a_path(env):
    compiler, _, _ = make(env)
    artifact = compiler.compile_scene(source_of())
    key = artifact.cache_key
    assert compiler.resolve_output_file(key, "scene.js").read_text("utf-8").startswith("/* scene */")
    assert compiler.resolve_output_file(key, "public/dot.png").read_bytes() == PNG_1X1
    for key_bad, relative in [(key, "../compiled/other"), (key, "compile.json"), (key, "public/../scene.js"),
                              (key, "/scene.js"), (key, "public\\dot.png"), ("../x", "scene.js"), ("scene-" + "0" * 32, "scene.js"),
                              (key, "public/missing.png")]:
        with pytest.raises(rc.RemotionCompileError) as caught:
            compiler.resolve_output_file(key_bad, relative)
        assert caught.value.code is rc.CompileErrorCode.CACHE_IO
    (env.parent / "compiled" / key / "scene.js").write_text("shorter", encoding="utf-8")
    with pytest.raises(rc.RemotionCompileError):
        compiler.resolve_output_file(key, "scene.js")  # size no longer matches compile.json


def test_pruning_keeps_the_most_recent_entries_and_never_the_protected_one(env):
    compiler, _, recorder = make(env)
    keys = []
    for index in range(4):
        keys.append(compiler.compile_scene(source_of(files=scene_files(f"// {index}\n"))).cache_key)
        folder = env.parent / "compiled" / keys[-1]
        os.utime(folder, (1000 + index, 1000 + index))
    removed = compiler.prune(keep=2, protect=keys[0])
    left = {p.name for p in (env.parent / "compiled").iterdir()}
    assert {keys[0], keys[2], keys[3]} == left and removed == [keys[1]]  # the 2 newest + the protected one
    assert "remotion.compile.pruned" in recorder.kinds()
    old = env.parent / "compiled" / ".tmp-deadbeefdeadbeef"
    old.mkdir()
    os.utime(old, (1000, 1000))
    assert ".tmp-deadbeefdeadbeef" in compiler.prune()


def test_the_shipped_engine_pin_is_the_shipped_lock():
    pin = shipped_engine_pin()
    lock = Path(__file__).resolve().parents[2] / "jarvis" / "capabilities" / "remotion" / "package-lock.json"
    import hashlib
    assert pin.lock_sha256 == hashlib.sha256(lock.read_bytes()).hexdigest()
    assert (pin.version, pin.react_version) == ("4.0.534", "19.3.0")

"""Résumés du banc d'essai Bare Hands, côté serveur (tâche adaptative, Slice 08).

La route `/api/barehands/benchmarks` est ouverte : ce fichier épingle ce
qu'elle accepte d'écrire (un résultat du contrat, métriques et échantillons
scalaires, reconstruit clé par clé), ce qu'elle refuse avec un code — y compris
une valeur d'un type inattendu, jamais un 500 sans code —, le plafond de
rangement, la déduplication, l'écriture atomique, la copie d'un fichier
illisible avant de l'écraser, l'effacement, les lignes de journal, le refus
d'origine nommé — et la **parité** de la liste blanche Python avec le contrat
JS (`createBenchmarkResult`), tables et verdicts.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime import barehands_benchmark as bench
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "jarvis" / "runtime" / "control_center_barehands_contracts.js"
#: Le contrat étendu du § 12 (Slice 10) : tous les noms du contrat, plus la
#: calibration adaptative et le banc — ce que lisent les modules de page.
ADAPTIVE = ROOT / "jarvis" / "runtime" / "control_center_barehands_adaptive.js"

PERFECT = {"acquisition_ms": 900.0, "missed_click_count": 0, "wrong_target_count": 0, "reacquisition_count": 0,
           "press_latency_ms": 30.5, "false_click_count": 0, "false_press_rate": 0.0,
           "false_secondary_press_rate": 0.0, "unintended_target_rate": 0.0, "unintended_pointer_rate": 0.0,
           "pointer_jitter_px": 1.2, "target_ambiguity": 0.3, "drag_success_rate": 1.0,
           "premature_drop_count": 0, "placement_error_px": 8.0, "release_latency_ms": -12.0,
           "pointer_lag_ms": 20.0, "transition_ms": 900.0, "timeout_count": 0}
SUITE = (("target_acquisition", 6), ("nearby_targets", 6), ("moving_target", 4), ("drag_drop", 5),
         ("chained", 4), ("no_click_tracking", 4))


def result(**overrides) -> dict:
    payload = {
        "schemaVersion": 1, "kind": "benchmark_result", "ref": "bm-1", "seed": 42, "planClass": "bh-bench-1",
        "runAt": 1_700_000_000_000, "profileSource": "saved", "trialRef": None,
        "profileFingerprint": "0123abcd4567ef89", "viewport": {"width": 1280, "height": 720, "scale": 4},
        "exercises": [{"ref": f"ex-{i + 1}", "kind": kind, "trials": trials,
                       "metrics": {m: PERFECT[m] for m in bench.EXERCISE_METRICS[kind]},
                       "samples": {m: [PERFECT[m]] for m in bench.EXERCISE_METRICS[kind]}}
                      for i, (kind, trials) in enumerate(SUITE)],
    }
    payload.update(overrides)
    return payload


def with_exercise(which: str = "target_acquisition", **changes) -> dict:
    payload = result()
    for exercise in payload["exercises"]:
        if exercise["kind"] == which:
            for key, value in changes.items():
                if key in ("metrics", "samples") and isinstance(value, dict):
                    exercise[key].update(value)
                else:
                    exercise[key] = value
    return payload


def with_metric(name: str, value, kind: str = "target_acquisition") -> dict:
    return with_exercise(kind, metrics={name: value})


# ------------------------------------------------------------------ la liste blanche


def test_the_server_rebuilds_a_result_key_by_key():
    raw = result()
    normalized = bench.normalize(raw)
    assert normalized == bench.normalize(normalized), "relire un résumé rangé doit rendre le même résumé"
    assert normalized["exercises"][0]["metrics"]["missed_click_count"] == 0
    assert isinstance(normalized["exercises"][0]["metrics"]["missed_click_count"], int)
    assert normalized["viewport"] == {"width": 1280.0, "height": 720.0, "scale": 4.0}
    assert normalized["exercises"][0]["samples"]["acquisition_ms"] == [900.0]
    raw.pop("planClass")
    assert bench.normalize(raw)["planClass"] == "bh-bench-1"
    assert bench.normalize(result())["exercises"][3]["metrics"]["release_latency_ms"] == -12.0
    no_samples = result()
    for exercise in no_samples["exercises"]:
        exercise.pop("samples")
    assert "samples" not in bench.normalize(no_samples)["exercises"][0]


def _drop(payload: dict, key: str) -> dict:
    payload = copy.deepcopy(payload)
    payload.pop(key)
    return payload


def _metrics_without(name: str) -> dict:
    payload = result()
    payload["exercises"][0]["metrics"].pop(name)
    return payload


def _too_many_exercises() -> dict:
    payload = result()
    base = payload["exercises"][0]
    payload["exercises"] = [{**copy.deepcopy(base), "ref": f"ex-{i}"} for i in range(1, 26)]
    return payload


REFUSALS = [
    (result(frames=[[0.1, 0.2]]), "barehands_session_key_unknown"),
    (result(scores={"global": 90}), "barehands_session_key_unknown"),
    (with_metric("landmarks", [1, 2]), "barehands_session_key_unknown"),
    (_metrics_without("acquisition_ms"), "barehands_benchmark_metric_missing"),
    (with_metric("missed_click_count", 7), "barehands_benchmark_invalid"),
    (with_metric("timeout_count", 7), "barehands_benchmark_invalid"),
    (with_metric("missed_click_count", 1.5), "barehands_benchmark_invalid"),
    (with_metric("acquisition_ms", -1), "barehands_benchmark_invalid"),
    (with_metric("press_latency_ms", -2500), "barehands_benchmark_invalid"),
    (with_metric("acquisition_ms", True), "barehands_benchmark_invalid"),
    (with_metric("acquisition_ms", "900"), "barehands_benchmark_invalid"),
    (with_metric("acquisition_ms", 10**400), "barehands_benchmark_invalid"),
    (with_metric("drag_success_rate", 1.5, "drag_drop"), "barehands_benchmark_invalid"),
    (with_exercise(samples={"acquisition_ms": [1.0] * 65}), "barehands_benchmark_invalid"),
    (with_exercise(samples={"acquisition_ms": [-5]}), "barehands_benchmark_invalid"),
    (with_exercise(samples={"acquisition_ms": "900"}), "barehands_benchmark_invalid"),
    (with_exercise(samples={"target_ambiguity": [0.2]}), "barehands_session_key_unknown"),
    (with_exercise("nearby_targets", samples={"target_ambiguity": [1.5]}), "barehands_benchmark_invalid"),
    (with_exercise(samples=[1, 2]), "barehands_benchmark_invalid"),
    (with_exercise(metrics=[1, 2]), "barehands_benchmark_invalid"),
    (with_exercise(kind=["target_acquisition"]), "barehands_benchmark_exercise_unknown"),
    (with_exercise(kind={"a": 1}), "barehands_benchmark_exercise_unknown"),
    (result(viewport={"width": 1280, "height": 720}), "barehands_benchmark_invalid"),
    (result(viewport={"width": 1280, "height": 720, "scale": 4, "dpi": 2}), "barehands_session_key_unknown"),
    (result(viewport=[1280, 720]), "barehands_benchmark_invalid"),
    (result(viewport={"width": 1280, "height": 720, "scale": 0}), "barehands_benchmark_invalid"),
    (result(viewport={"width": 1280, "height": 720, "scale": 5000}), "barehands_benchmark_invalid"),
    (with_exercise(samples={"missed_click_count": [0.5]}), "barehands_benchmark_invalid"),
    (with_exercise(samples={"acquisition_ms": [900.0] * 7}), "barehands_benchmark_invalid"),
    (with_exercise(samples={"acquisition_ms": [800.0]}), "barehands_benchmark_samples_mismatch"),
    (with_exercise(samples={"missed_click_count": [1, 0]}), "barehands_benchmark_samples_mismatch"),
    (with_exercise(samples={"acquisition_ms": []}), "barehands_benchmark_samples_mismatch"),
    (result(seed=-1), "barehands_benchmark_seed_invalid"),
    (result(seed=True), "barehands_benchmark_seed_invalid"),
    (result(seed=4294967296), "barehands_benchmark_seed_invalid"),
    (result(seed=10**400), "barehands_benchmark_seed_invalid"),
    (result(runAt=-1), "barehands_benchmark_invalid"),
    (result(runAt=2**53), "barehands_benchmark_invalid"),
    (result(profileSource="trial"), "barehands_benchmark_profile_invalid"),
    (result(profileSource=["saved"]), "barehands_benchmark_invalid"),
    (result(trialRef="tr-3"), "barehands_benchmark_profile_invalid"),
    (result(profileFingerprint="XYZ"), "barehands_benchmark_profile_invalid"),
    (result(planClass="bh-bench-9"), "barehands_benchmark_invalid"),
    (result(planClass=["bh-bench-1"]), "barehands_benchmark_invalid"),
    (result(schemaVersion=2), "barehands_schema_version_unsupported"),
    (result(ref="ex-1"), "barehands_session_ref_invalid"),
    (result(exercises=[]), "barehands_benchmark_invalid"),
    (_too_many_exercises(), "barehands_benchmark_invalid"),
    (_drop(result(), "runAt"), "barehands_benchmark_invalid"),
    ("pas un objet", "barehands_benchmark_invalid"),
]


@pytest.mark.parametrize("payload, code", REFUSALS)
def test_a_result_the_server_cannot_read_is_refused_with_a_code(payload, code):
    with pytest.raises(bench.BarehandsBenchmarkError) as caught:
        bench.normalize(payload)
    assert caught.value.code == code


def test_an_unknown_exercise_and_a_duplicate_ref_are_refused():
    unknown = result()
    unknown["exercises"][0]["kind"] = "arcade"
    duplicate = result()
    duplicate["exercises"][1]["ref"] = "ex-1"
    for payload, code in ((unknown, "barehands_benchmark_exercise_unknown"),
                          (duplicate, "barehands_session_ref_duplicate")):
        with pytest.raises(bench.BarehandsBenchmarkError) as caught:
            bench.normalize(payload)
        assert caught.value.code == code


# ------------------------------------------------------------------ le rangement


def test_storing_keeps_the_twenty_most_recent_and_never_duplicates(tmp_path):
    for index in range(25):
        stored = bench.store(tmp_path, result(runAt=1000 + index, seed=index))
    assert stored["stored"] == 20 and stored["dropped"] == 1
    loaded = bench.load(tmp_path)
    assert [entry["result"]["runAt"] for entry in loaded["results"]] == list(range(1005, 1025))
    again = bench.store(tmp_path, result(runAt=1024, seed=24))
    assert again["duplicate"] is True and again["stored"] == 20
    assert len(bench.load(tmp_path)["results"]) == 20
    # Sur le disque : des résultats du contrat, rien d'autre, et aucun fichier
    # temporaire laissé derrière (écriture atomique).
    document = json.loads(bench.store_path(tmp_path).read_text(encoding="utf-8"))
    assert set(document) == {"schema", "schemaVersion", "results"}
    for entry in document["results"]:
        assert set(entry) == {"id", "result"}
        assert set(entry["result"]) == set(bench.RESULT_KEYS)
    assert sorted(p.name for p in tmp_path.iterdir()) == [bench.STORE_FILENAME]
    assert bench.clear(tmp_path) == {"cleared": 20, "backups": 0}
    assert bench.load(tmp_path)["results"] == []
    assert not bench.store_path(tmp_path).exists()


def test_the_same_run_posted_twice_is_stored_once(tmp_path):
    first = bench.store(tmp_path, result())
    second = bench.store(tmp_path, result())
    assert first["id"] == second["id"] and second["duplicate"] is True
    assert second["stored"] == 1 and len(bench.load(tmp_path)["results"]) == 1


def test_loading_orders_by_run_time_whatever_the_file_order(tmp_path):
    entries = [{"id": "x", "result": result(runAt=at, seed=at)} for at in (30, 10, 20)]
    bench.store_path(tmp_path).write_text(json.dumps({"schema": bench.STORE_SCHEMA, "schemaVersion": 1,
                                                      "results": entries}), encoding="utf-8")
    assert [e["result"]["runAt"] for e in bench.load(tmp_path)["results"]] == [10, 20, 30]


def test_an_unreadable_store_is_backed_up_before_it_is_overwritten(tmp_path):
    bench.store(tmp_path, result())
    path = bench.store_path(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["results"].append({"id": "x", "result": {**result(runAt=5), "frames": [[1, 2, 3]]}})
    path.write_text(json.dumps(document), encoding="utf-8")
    loaded = bench.load(tmp_path)
    assert loaded["skipped"] == 1 and len(loaded["results"]) == 1
    path.write_text("{pas du json", encoding="utf-8")
    assert bench.load(tmp_path) == {"results": [], "skipped": 1, "max": bench.SUMMARY_MAX}
    stored = bench.store(tmp_path, result(runAt=7))
    assert stored["backup"] == "barehands-benchmarks.unreadable-1.json" and stored["skipped"] == 1
    assert (tmp_path / stored["backup"]).read_text(encoding="utf-8") == "{pas du json"
    # Au plus trois copies : la plus ancienne est remplacée.
    for n in range(5):
        path.write_text(f"cassé {n}", encoding="utf-8")
        bench.store(tmp_path, result(runAt=8 + n))
    backups = sorted(p.name for p in tmp_path.glob("barehands-benchmarks.unreadable-*.json"))
    assert len(backups) == 3


class Request:
    def __init__(self, payload=None, *, path="/api/barehands/benchmarks", method="POST", headers=None):
        self._payload = payload
        self.path = path
        self.method = method
        self.headers = headers or {}

    async def json(self):
        if self._payload is _BROKEN:
            raise ValueError("pas du json")
        return self._payload


_BROKEN = object()


def _control(tmp_path):
    from jarvis.runtime.control_center import ControlCenter

    runtime = tmp_path / "runtime"
    return runtime, ControlCenter(runtime_root=runtime, project_root=tmp_path,
                                  barehands_vendor_root=tmp_path / "vendor")


def test_the_routes_store_list_and_clear_and_say_so_in_the_journal(tmp_path):
    from aiohttp import web

    runtime, control = _control(tmp_path)
    body = json.loads(asyncio.run(control.save_barehands_benchmark(Request(result()))).text)
    assert body["stored"] == 1 and body["duplicate"] is False
    listed = json.loads(asyncio.run(control.get_barehands_benchmarks(Request(method="GET"))).text)
    assert listed["results"][0]["id"] == body["id"] and listed["max"] == 20
    for bad in (result(frames=[]), result(seed=10**400), with_exercise(kind=["x"]), _BROKEN):
        with pytest.raises(web.HTTPBadRequest) as caught:
            asyncio.run(control.save_barehands_benchmark(Request(bad)))
        assert caught.value.headers["X-Jarvis-Error-Code"].startswith("barehands_")
    cleared = json.loads(asyncio.run(control.clear_barehands_benchmarks(Request(method="DELETE"))).text)
    assert cleared == {"cleared": 1, "backups": 0}
    trace = read_jsonl_tail(RuntimeJournal(runtime).trace_path, limit=50)
    kinds = [line.get("kind") for line in trace]
    assert kinds.count("barehands.benchmark_recorded") == 1
    assert kinds.count("barehands.benchmark_cleared") == 1
    errors = read_jsonl_tail(RuntimeJournal(runtime).error_path, limit=20)
    assert sum(1 for line in errors if line.get("kind") == "barehands.benchmark_rejected") == 4


def test_unreadable_entries_are_said_on_read_and_on_write(tmp_path):
    runtime, control = _control(tmp_path)
    runtime.mkdir(parents=True, exist_ok=True)
    bench.store_path(runtime).write_text("{cassé", encoding="utf-8")
    listed = json.loads(asyncio.run(control.get_barehands_benchmarks(Request(method="GET"))).text)
    assert listed["skipped"] == 1
    stored = json.loads(asyncio.run(control.save_barehands_benchmark(Request(result()))).text)
    assert stored["backup"] is not None
    trace = read_jsonl_tail(RuntimeJournal(runtime).trace_path, limit=50)
    unreadable = [line for line in trace if line.get("kind") == "barehands.benchmark_unreadable"]
    assert len(unreadable) == 2 and all(line["data"]["code"] == "barehands_benchmark_unreadable" for line in unreadable)


def test_a_disk_failure_is_a_coded_error_in_error_logs_not_a_bare_500(tmp_path, monkeypatch):
    runtime, control = _control(tmp_path)

    def broken(*_args, **_kwargs):
        # Pas une erreur de disque : toute panne imprévue doit rester codée.
        raise RuntimeError("panne imprévue")

    monkeypatch.setattr(bench, "_write", broken)
    response = asyncio.run(control.save_barehands_benchmark(Request(result())))
    assert response.status == 500
    assert response.headers["X-Jarvis-Error-Code"] == "barehands_benchmark_store_failed"
    assert "RuntimeError" in response.text
    errors = read_jsonl_tail(RuntimeJournal(runtime).error_path, limit=20)
    assert any(line.get("kind") == "barehands.benchmark_store_failed" for line in errors)


def test_a_foreign_origin_is_refused_with_a_named_code(tmp_path):
    from jarvis.runtime import control_center as cc

    _runtime, control = _control(tmp_path)
    assert cc.BAREHANDS_BENCHMARKS_ROUTE in cc.READ_GUARDED_ROUTES

    async def handler(_request):
        raise AssertionError("la requête étrangère ne doit pas atteindre la route")

    for method in ("GET", "POST", "DELETE"):
        response = asyncio.run(control._origin_guard(
            Request(method=method, headers={"Origin": "http://evil.example", "Host": "127.0.0.1:1"}), handler))
        assert response.status == 403
        assert response.headers["X-Jarvis-Error-Code"] == "barehands_forbidden_origin"


def test_the_routes_are_declared():
    from jarvis.runtime import control_center as cc

    source = Path(cc.__file__).read_text(encoding="utf-8")
    for method in ("get", "post", "delete"):
        assert f"web.{method}(BAREHANDS_BENCHMARKS_ROUTE" in source
    assert cc.BAREHANDS_BENCHMARKS_ROUTE == "/api/barehands/benchmarks"


# ------------------------------------------------------------------ parité avec le contrat JS


def _node(source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    done = subprocess.run(
        [node, "-"], input=f"const C=require({json.dumps(str(ADAPTIVE))});" + source,
        capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_python_tables_mirror_the_contract():
    tables = _node("""
      const metrics=[...new Set(Object.values(C.BENCHMARK_EXERCISE_METRICS).flat())];
      process.stdout.write(JSON.stringify({exercises:C.BENCHMARK_EXERCISE_METRICS,
        bounds:Object.fromEntries(metrics.map(m=>{const s=C.CALIBRATION_METRIC[m];return [m,[s.min,s.max,s.integer,s.perTrial]]})),
        classes:C.BENCHMARK_PLAN_CLASSES,sources:C.BENCHMARK_PROFILE_SOURCES,
        max:[C.BENCHMARK_EXERCISES_MAX,C.BENCHMARK_TRIALS_MAX,C.BENCHMARK_SAMPLES_MAX],version:C.SESSION_SCHEMA_VERSION,
        retention:C.DATA_RETENTION.benchmark_result}));
    """)
    assert {k: list(v) for k, v in bench.EXERCISE_METRICS.items()} == tables["exercises"]
    assert {k: [v[0], v[1], v[2], v[3]] for k, v in bench.METRIC_BOUNDS.items()} == tables["bounds"]
    assert list(bench.PLAN_CLASSES) == tables["classes"]
    assert list(bench.PROFILE_SOURCES) == tables["sources"]
    assert [bench.EXERCISES_MAX, bench.TRIALS_MAX, bench.SAMPLES_MAX] == tables["max"]
    assert bench.SCHEMA_VERSION == tables["version"]
    assert tables["retention"] == "persistent"


def test_python_and_the_contract_give_the_same_verdict_on_every_sample():
    samples = [result(), result(planClass=None, trialRef=None, viewport=None)] + [
        payload for payload, _ in REFUSALS
        if isinstance(payload, dict) and not any(isinstance(v, int) and abs(v) > 2**53 for v in _flat(payload))]
    verdicts = _node(f"""
      const samples={json.dumps(samples)};
      process.stdout.write(JSON.stringify(samples.map(s=>{{const r=C.checkSchema(C.createBenchmarkResult,s);return r.ok?null:r.code}})));
    """)
    for payload, js in zip(samples, verdicts):
        try:
            bench.normalize(payload)
            py = None
        except bench.BarehandsBenchmarkError as exc:
            py = exc.code
        assert py == js, (py, js, json.dumps(payload)[:600])


def _flat(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _flat(v)
    elif isinstance(value, list):
        for v in value:
            yield from _flat(v)
    else:
        yield value


def test_clearing_also_removes_the_unreadable_copies(tmp_path):
    bench.store(tmp_path, result())
    bench.store_path(tmp_path).write_text("cassé", encoding="utf-8")
    bench.store(tmp_path, result(runAt=9))
    assert len(bench.backups(tmp_path)) == 1
    assert bench.clear(tmp_path) == {"cleared": 1, "backups": 1}
    assert list(tmp_path.iterdir()) == []


def test_many_latency_samples_are_allowed_but_never_more_than_64():
    many = with_exercise(samples={"release_latency_ms": [-12.0] * 64})
    assert len(bench.normalize(many)["exercises"][0]["samples"]["release_latency_ms"]) == 64
    with pytest.raises(bench.BarehandsBenchmarkError):
        bench.normalize(with_exercise(samples={"release_latency_ms": [-12.0] * 65}))


def test_python_and_the_contract_compute_the_same_statistic_to_the_bit():
    import random

    rng = random.Random(8)
    cases = []
    for name in bench.METRIC_STAT:
        low, high, integer, _per_trial = bench.METRIC_BOUNDS[name]
        for _ in range(40):
            n = rng.randint(1, 9)
            top = high if high is not None else 2000
            values = [rng.randint(0, 3) if integer else round(rng.uniform(max(low, 0), top), 3) for _ in range(n)]
            cases.append([name, values])
    js = _node(f"""
      const cases={json.dumps(cases)};
      process.stdout.write(JSON.stringify({{stats:cases.map(([n,v])=>C.benchmarkStat(n,v)),
        stat:C.BENCHMARK_METRIC_STAT,perTrial:C.BENCHMARK_SAMPLES_PER_TRIAL,digits:C.BENCHMARK_METRIC_DIGITS,
        units:Object.fromEntries(Object.keys(C.BENCHMARK_METRIC_STAT).map(m=>[m,C.CALIBRATION_METRIC[m].unit]))}}));
    """)
    assert [bench.benchmark_stat(name, values) for name, values in cases] == js["stats"]
    assert bench.METRIC_STAT == js["stat"]
    assert bench.SAMPLES_PER_TRIAL == js["perTrial"]
    assert bench.UNIT_DIGITS == js["digits"]
    assert bench.METRIC_UNITS == js["units"]

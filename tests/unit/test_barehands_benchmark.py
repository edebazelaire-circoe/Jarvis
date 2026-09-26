"""Résumés du banc d'essai Bare Hands, côté serveur (tâche adaptative, Slice 08).

La route `/api/barehands/benchmarks` est ouverte : ce fichier épingle ce
qu'elle accepte d'écrire (un résultat du contrat, reconstruit clé par clé),
ce qu'elle refuse avec un code, le plafond de rangement, l'effacement, les
lignes de journal — et la **parité** de la liste blanche Python avec le
contrat JS (`createBenchmarkResult`), tables et verdicts.
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

PERFECT = {"acquisition_ms": 900.0, "missed_click_count": 0, "wrong_target_count": 0, "reacquisition_count": 0,
           "press_latency_ms": 30.5, "false_click_count": 0, "false_press_rate": 0.0,
           "false_secondary_press_rate": 0.0, "unintended_target_rate": 0.0, "unintended_pointer_rate": 0.0,
           "pointer_jitter_px": 1.2, "target_ambiguity": 0.3, "drag_success_rate": 1.0,
           "premature_drop_count": 0, "placement_error_px": 8.0, "release_latency_ms": -12.0,
           "pointer_lag_ms": 20.0, "transition_ms": 900.0}
SUITE = (("target_acquisition", 6), ("nearby_targets", 6), ("moving_target", 4), ("drag_drop", 3),
         ("chained", 3), ("no_click_tracking", 4))


def result(**overrides) -> dict:
    payload = {
        "schemaVersion": 1, "kind": "benchmark_result", "ref": "bm-1", "seed": 42, "planClass": "bh-bench-1",
        "runAt": 1_700_000_000_000, "profileSource": "saved", "trialRef": None,
        "profileFingerprint": "0123abcd4567ef89",
        "exercises": [{"ref": f"ex-{i + 1}", "kind": kind, "trials": trials,
                       "metrics": {m: PERFECT[m] for m in bench.EXERCISE_METRICS[kind]}}
                      for i, (kind, trials) in enumerate(SUITE)],
    }
    payload.update(overrides)
    return payload


def with_metric(name: str, value, kind: str = "target_acquisition") -> dict:
    payload = result()
    for exercise in payload["exercises"]:
        if exercise["kind"] == kind:
            exercise["metrics"][name] = value
    return payload


# ------------------------------------------------------------------ la liste blanche


def test_the_server_rebuilds_a_result_key_by_key():
    raw = result()
    normalized = bench.normalize(raw)
    assert normalized == bench.normalize(normalized), "relire un résumé rangé doit rendre le même résumé"
    assert normalized["exercises"][0]["metrics"]["missed_click_count"] == 0
    assert isinstance(normalized["exercises"][0]["metrics"]["missed_click_count"], int)
    # `planClass` absent vaut la classe courante (rien n'a été rangé avant elle).
    raw.pop("planClass")
    assert bench.normalize(raw)["planClass"] == "bh-bench-1"
    # Une latence de relâchement peut être négative (définition de l'épisode).
    assert bench.normalize(result())["exercises"][3]["metrics"]["release_latency_ms"] == -12.0


def _drop(payload: dict, key: str) -> dict:
    payload = copy.deepcopy(payload)
    payload.pop(key)
    return payload


def _metrics_without(name: str) -> dict:
    payload = result()
    payload["exercises"][0]["metrics"].pop(name)
    return payload


REFUSALS = [
    (result(frames=[[0.1, 0.2]]), "barehands_session_key_unknown"),
    (result(scores={"global": 90}), "barehands_session_key_unknown"),
    (with_metric("landmarks", [1, 2]), "barehands_session_key_unknown"),
    (_metrics_without("acquisition_ms"), "barehands_benchmark_metric_missing"),
    (with_metric("missed_click_count", 7), "barehands_benchmark_invalid"),
    (with_metric("missed_click_count", 1.5), "barehands_benchmark_invalid"),
    (with_metric("acquisition_ms", -1), "barehands_benchmark_invalid"),
    (with_metric("press_latency_ms", -2500), "barehands_benchmark_invalid"),
    (with_metric("acquisition_ms", True), "barehands_benchmark_invalid"),
    (with_metric("acquisition_ms", "900"), "barehands_benchmark_invalid"),
    (with_metric("drag_success_rate", 1.5, "drag_drop"), "barehands_benchmark_invalid"),
    (result(seed=-1), "barehands_benchmark_seed_invalid"),
    (result(seed=True), "barehands_benchmark_seed_invalid"),
    (result(seed=4294967296), "barehands_benchmark_seed_invalid"),
    (result(profileSource="trial"), "barehands_benchmark_profile_invalid"),
    (result(trialRef="tr-3"), "barehands_benchmark_profile_invalid"),
    (result(profileFingerprint="XYZ"), "barehands_benchmark_profile_invalid"),
    (result(planClass="bh-bench-9"), "barehands_benchmark_invalid"),
    (result(schemaVersion=2), "barehands_schema_version_unsupported"),
    (result(ref="ex-1"), "barehands_session_ref_invalid"),
    (result(exercises=[]), "barehands_benchmark_invalid"),
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


def test_storing_is_bounded_deduplicated_and_clearable(tmp_path):
    for index in range(bench.SUMMARY_MAX + 5):
        stored = bench.store(tmp_path, result(runAt=1000 + index, seed=index))
    assert stored["stored"] == bench.SUMMARY_MAX and stored["dropped"] == 1
    loaded = bench.load(tmp_path)
    run_ats = [entry["result"]["runAt"] for entry in loaded["results"]]
    assert run_ats == sorted(run_ats) and run_ats[0] == 1005, "les plus anciens sortent du plafond"
    again = bench.store(tmp_path, result(runAt=1000 + bench.SUMMARY_MAX + 4, seed=bench.SUMMARY_MAX + 4))
    assert again["duplicate"] is True and again["stored"] == bench.SUMMARY_MAX
    # Sur le disque : des résultats du contrat, rien d'autre.
    document = json.loads(bench.store_path(tmp_path).read_text(encoding="utf-8"))
    assert set(document) == {"schema", "schemaVersion", "results"}
    for entry in document["results"]:
        assert set(entry) == {"id", "result"}
        assert set(entry["result"]) == set(bench.RESULT_KEYS)
    cleared = bench.clear(tmp_path)
    assert cleared == {"cleared": bench.SUMMARY_MAX}
    assert bench.load(tmp_path)["results"] == []


def test_an_unreadable_stored_entry_is_skipped_and_counted_never_copied(tmp_path):
    bench.store(tmp_path, result())
    path = bench.store_path(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["results"].append({"id": "x", "result": {**result(runAt=5), "frames": [[1, 2, 3]]}})
    path.write_text(json.dumps(document), encoding="utf-8")
    loaded = bench.load(tmp_path)
    assert loaded["skipped"] == 1 and len(loaded["results"]) == 1
    path.write_text("{pas du json", encoding="utf-8")
    assert bench.load(tmp_path) == {"results": [], "skipped": 1, "max": bench.SUMMARY_MAX}


class Request:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        if self._payload is _BROKEN:
            raise ValueError("pas du json")
        return self._payload


_BROKEN = object()


def test_the_routes_store_list_and_clear_and_say_so_in_the_journal(tmp_path):
    from aiohttp import web

    from jarvis.runtime.control_center import ControlCenter

    runtime = tmp_path / "runtime"
    control = ControlCenter(runtime_root=runtime, project_root=tmp_path, barehands_vendor_root=tmp_path / "vendor")
    body = json.loads(asyncio.run(control.save_barehands_benchmark(Request(result()))).text)
    assert body["stored"] == 1 and body["duplicate"] is False
    listed = json.loads(asyncio.run(control.get_barehands_benchmarks(Request(None))).text)
    assert listed["results"][0]["id"] == body["id"] and listed["max"] == bench.SUMMARY_MAX
    with pytest.raises(web.HTTPBadRequest) as caught:
        asyncio.run(control.save_barehands_benchmark(Request(result(frames=[]))))
    assert caught.value.headers["X-Jarvis-Error-Code"] == "barehands_session_key_unknown"
    with pytest.raises(web.HTTPBadRequest):
        asyncio.run(control.save_barehands_benchmark(Request(_BROKEN)))
    cleared = json.loads(asyncio.run(control.clear_barehands_benchmarks(Request(None))).text)
    assert cleared == {"cleared": 1}
    trace = read_jsonl_tail(RuntimeJournal(runtime).trace_path, limit=50)
    kinds = [line.get("kind") for line in trace]
    assert kinds.count("barehands.benchmark_recorded") == 1
    assert kinds.count("barehands.benchmark_cleared") == 1
    errors = read_jsonl_tail(RuntimeJournal(runtime).error_path, limit=20)
    assert sum(1 for line in errors if line.get("kind") == "barehands.benchmark_rejected") == 2


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
        [node, "-"], input=f"const C=require({json.dumps(str(CONTRACTS))});" + source,
        capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_python_tables_mirror_the_contract():
    tables = _node("""
      const metrics=[...new Set(Object.values(C.BENCHMARK_EXERCISE_METRICS).flat())];
      process.stdout.write(JSON.stringify({exercises:C.BENCHMARK_EXERCISE_METRICS,
        bounds:Object.fromEntries(metrics.map(m=>{const s=C.CALIBRATION_METRIC[m];return [m,[s.min,s.max,s.integer,s.perTrial]]})),
        classes:C.BENCHMARK_PLAN_CLASSES,sources:C.BENCHMARK_PROFILE_SOURCES,
        max:[C.BENCHMARK_EXERCISES_MAX,C.BENCHMARK_TRIALS_MAX],version:C.SESSION_SCHEMA_VERSION,
        retention:C.DATA_RETENTION.benchmark_result}));
    """)
    assert {k: list(v) for k, v in bench.EXERCISE_METRICS.items()} == tables["exercises"]
    assert {k: [v[0], v[1], v[2], v[3]] for k, v in bench.METRIC_BOUNDS.items()} == tables["bounds"]
    assert list(bench.PLAN_CLASSES) == tables["classes"]
    assert list(bench.PROFILE_SOURCES) == tables["sources"]
    assert [bench.EXERCISES_MAX, bench.TRIALS_MAX] == tables["max"]
    assert bench.SCHEMA_VERSION == tables["version"]
    assert tables["retention"] == "persistent"


def test_python_and_the_contract_give_the_same_verdict_on_every_sample():
    samples = [result(), result(planClass=None, trialRef=None)] + [payload for payload, _ in REFUSALS
                                                                   if isinstance(payload, dict)]
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
        assert py == js, (py, js, {k: payload.get(k) for k in ("seed", "profileSource", "trialRef", "planClass")})

"""Slice 05 worker protocol: job and result codecs, isolation guard, fixture containment."""

from __future__ import annotations

import json

import pytest

from jarvis.testlab import worker as worker_module
from jarvis.testlab.catalog import load_catalog
from jarvis.testlab.jobs import (
    FAILURE_CODES,
    FAILURE_ISOLATION_VIOLATION,
    FAILURE_RUNNER_FAILED,
    RESULT_FILE_NAME,
    WORKER_LOG_NAME,
    WorkerJob,
    WorkerResult,
    WorkerStatus,
    worker_failure,
)
from jarvis.testlab.maintenance import MaintenancePolicy
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runs import ArtifactKind, ArtifactRef, RunFailure
from jarvis.testlab.scenarios import Scenario, ScenarioStep
from jarvis.testlab.selftest import (
    SELFTEST_IMPLEMENTATION_PREFIX,
    catalog_implementations,
    selftest_implementations,
    write_selftest_catalog,
)
from jarvis.testlab.validation import TestLabError

RUN_ID = "tlr-20260917T120000000Z-" + "0" * 16
FINGERPRINT = "a" * 64


def a_job(**changes) -> WorkerJob:
    values = dict(run_id=RUN_ID, diagnostic_id="selftest.worker", diagnostic_version=1,
                  diagnostic_fingerprint=FINGERPRINT, profile=ProfileName.VIRTUAL,
                  implementation="testlab.selftest.virtual", store_root="C:/tmp/store",
                  scratch_root="C:/tmp/work/run", catalog_root="C:/tmp/catalog",
                  parameters={"mode": "measure"}, max_duration_s=30.0)
    values.update(changes)
    return WorkerJob(**values)


# ------------------------------------------------------------------ codecs

def test_a_job_round_trips_through_its_document():
    scenario = Scenario("selftest_prelude", (ScenarioStep("time.wait", {"at_ms": 5}),))
    job = a_job(scenario=scenario, overrides={"voice.turn_mode": "manual"})
    assert WorkerJob.from_dict(json.loads(json.dumps(job.to_dict()))) == job


def test_a_job_document_is_strict():
    payload = a_job().to_dict()
    payload["unexpected"] = 1
    with pytest.raises(TestLabError, match="testlab_fields_mismatch"):
        WorkerJob.from_dict(payload)
    payload = a_job().to_dict()
    payload["schema"] = "jarvis.testlab.run"
    with pytest.raises(TestLabError, match="testlab_schema_unsupported"):
        WorkerJob.from_dict(payload)
    with pytest.raises(TestLabError):
        a_job(max_duration_s=0)
    with pytest.raises(TestLabError):
        a_job(implementation="Not A Name")


def test_a_measured_result_round_trips():
    ref = ArtifactRef(ArtifactKind.REPORT, "report.json", "application/json", "b" * 64, 12)
    result = WorkerResult(RUN_ID, WorkerStatus.MEASURED, metrics={"selftest.value": 0}, score=42.0,
                          join_ids={"conversation_id": "c-1"}, artifacts=(ref,))
    assert WorkerResult.from_dict(json.loads(json.dumps(result.to_dict()))) == result


def test_a_failed_result_carries_a_failure_and_no_measurement():
    result = WorkerResult(RUN_ID, WorkerStatus.FAILED, failure=worker_failure(FAILURE_RUNNER_FAILED, "boom"))
    assert WorkerResult.from_dict(result.to_dict()) == result
    with pytest.raises(TestLabError, match="failure is set exactly"):
        WorkerResult(RUN_ID, WorkerStatus.FAILED)
    with pytest.raises(TestLabError, match="failure is set exactly"):
        WorkerResult(RUN_ID, WorkerStatus.MEASURED, failure=RunFailure("runner_failed"))
    with pytest.raises(TestLabError, match="no metrics"):
        WorkerResult(RUN_ID, WorkerStatus.FAILED, metrics={"selftest.value": 1},
                     failure=RunFailure("runner_failed"))


def test_only_vocabulary_failure_codes_are_accepted():
    assert worker_failure(FAILURE_RUNNER_FAILED).code in FAILURE_CODES
    with pytest.raises(TestLabError, match="supervisor vocabulary"):
        worker_failure("made_up_code")


def test_every_failure_code_is_a_stable_snake_case_name():
    assert all(code.islower() and code.replace("_", "").isalnum() for code in FAILURE_CODES)


# --------------------------------------------------------------- isolation

def test_is_inside_refuses_a_sibling_directory(tmp_path):
    root = tmp_path / "scratch"
    (root / "runtime").mkdir(parents=True)
    (tmp_path / "other").mkdir()
    assert worker_module.is_inside(root / "runtime", root)
    assert worker_module.is_inside(root, root)
    assert not worker_module.is_inside(tmp_path / "other", root)
    assert not worker_module.is_inside(root.parent, root)


def test_the_isolation_guard_refuses_a_runtime_outside_the_scratch(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    (scratch / "runtime").mkdir(parents=True)
    (scratch / "data").mkdir()
    monkeypatch.setenv("JARVIS_TESTLAB_RUN_SCRATCH", str(scratch))
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path / "live-runtime"))
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(scratch / "data"))
    with pytest.raises(worker_module.WorkerRefusal) as refusal:
        worker_module.check_isolation(scratch)
    assert refusal.value.code == FAILURE_ISOLATION_VIOLATION
    assert "runtime_root" in refusal.value.detail


def test_the_isolation_guard_refuses_a_missing_declaration(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.delenv("JARVIS_TESTLAB_RUN_SCRATCH", raising=False)
    with pytest.raises(worker_module.WorkerRefusal) as refusal:
        worker_module.check_isolation(scratch)
    assert refusal.value.code == FAILURE_ISOLATION_VIOLATION


def test_the_isolation_guard_accepts_run_local_roots(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    (scratch / "runtime").mkdir(parents=True)
    (scratch / "data").mkdir()
    monkeypatch.setenv("JARVIS_TESTLAB_RUN_SCRATCH", str(scratch))
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(scratch / "runtime"))
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(scratch / "data"))
    worker_module.check_isolation(scratch)


# ------------------------------------------------------------- worker log

def test_the_worker_log_is_bounded_and_single_line(tmp_path):
    log = worker_module.WorkerLog(tmp_path / WORKER_LOG_NAME)
    log.write("first\nsecond")
    for index in range(worker_module.MAX_LOG_LINES + 10):
        log.write(f"line {index}")
    lines = (tmp_path / WORKER_LOG_NAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == worker_module.MAX_LOG_LINES
    assert lines[0].endswith("first second")
    assert lines[-1].endswith("worker log truncated: line budget reached")


def test_an_unreadable_job_file_is_a_structured_refusal(tmp_path):
    with pytest.raises(worker_module.WorkerRefusal) as refusal:
        worker_module.read_job(tmp_path / "missing.json")
    assert refusal.value.code == "worker_job_invalid"
    (tmp_path / "job.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(worker_module.WorkerRefusal):
        worker_module.read_job(tmp_path / "job.json")


def test_a_result_is_published_atomically(tmp_path):
    result = WorkerResult(RUN_ID, WorkerStatus.MEASURED, metrics={"selftest.value": 0})
    worker_module.write_result(tmp_path, result)
    stored = json.loads((tmp_path / RESULT_FILE_NAME).read_text(encoding="utf-8"))
    assert WorkerResult.from_dict(stored) == result
    assert not list(tmp_path.glob(".result-*"))


# ------------------------------------------------------- fixture containment

def test_the_official_catalog_never_references_a_fixture_implementation():
    catalog = load_catalog()
    names = {availability.implementation.name
             for entry in catalog.entries for availability in entry.profiles.values()}
    assert not any(name.startswith(SELFTEST_IMPLEMENTATION_PREFIX) for name in names)


def test_the_fixture_registry_only_adds_fixture_names():
    added = {entry.name for entry in selftest_implementations()}
    assert all(name.startswith(SELFTEST_IMPLEMENTATION_PREFIX) for name in added)
    assert added <= set(catalog_implementations().entries)


def test_the_fixture_catalog_loads_and_resolves_its_runner(tmp_path):
    root = write_selftest_catalog(tmp_path / "catalog")
    entry = load_catalog(root, implementations=catalog_implementations()).describe("selftest.worker")
    availability = entry.resources_and_cost(ProfileName.VIRTUAL)
    assert availability.available
    assert availability.requires == frozenset()
    assert availability.cost.max_cost_usd == 0


# -------------------------------------------------------------- maintenance

def test_a_maintenance_policy_validates_its_bounds():
    with pytest.raises(TestLabError):
        MaintenancePolicy(interval_s=0)
    with pytest.raises(TestLabError):
        MaintenancePolicy(stale_temporary_s=-1)
    with pytest.raises(TestLabError):
        MaintenancePolicy(retention=object())

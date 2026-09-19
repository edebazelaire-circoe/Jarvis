"""Slice 12 end to end: cross-profile execution, ad-hoc to official, comparison, retention.

Contract: `docs/testlab.md` ("Where to start", "Promotion", "Comparison", "Retention",
"Rollout gate"). These are the four things the Test Lab promises a caller, and until now
each half had a test while the WORKFLOW had none.

In process, with doubles, on a temp root: no worker process, no device, no provider, no
human. The subprocess path is `tests/integration/test_testlab_virtual_runs.py`; what is
new here is the composition of published declarations, runners, the store, promotion,
comparison and retention into the sequence a person actually performs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis.testlab.api import TestLabApi
from jarvis.testlab.audio.runners import SelfEchoAudioRunner
from jarvis.testlab.catalog import LOCK_FILE_NAME, load_catalog
from jarvis.testlab.compare import compare_runs
from jarvis.testlab.composition import TestLab, TestLabConfig
from jarvis.testlab.diagnostics import resolve_parameters
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.implementations import default_implementations
from jarvis.testlab.maintenance import MaintenancePolicy
from jarvis.testlab.manifests import CatalogLock
from jarvis.testlab.outcomes import RunOutcomeClass, classify_run
from jarvis.testlab.primitives import AT_MS
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.retention import TestLabRetentionPolicy
from jarvis.testlab.runners import RunArtifacts, RunContext
from jarvis.testlab.runs import CodeIdentity, RunStatus, TestRun, complete_run, transition_run
from jarvis.testlab.scenarios import Scenario, ScenarioStep
from jarvis.testlab.selftest import catalog_implementations
from jarvis.testlab.supervisor import SupervisorPolicy, derive_assertion_results
from jarvis.testlab.virtual.runners import ScenarioRunner, SelfEchoRunner
from tests.fakes.testlab import CONFIG, ENVIRONMENT, NONCE, REVISION, T0

pytestmark = pytest.mark.asyncio

CATALOG_ROOT = Path(__file__).resolve().parents[2] / "jarvis" / "testlab" / "official"
RUN_BUDGET_S = 240.0
#: Short on purpose everywhere: what is under test is the workflow, not the acoustics.
FAST = {"output.duration_ms": 1000, "echo.candidate_count": 2}


def catalog(root: Path | None = None):
    return load_catalog(root or CATALOG_ROOT, implementations=catalog_implementations())


def run_id(index: int) -> str:
    return format_run_id(T0, f"{index:016x}")


def build_context(tmp_path: Path, spec, profile: ProfileName, *, index: int = 1, parameters=None,
                  scenario=None) -> RunContext:
    """A `RunContext` on a real run store, exactly as a worker builds one."""
    values = resolve_parameters(spec.parameters, dict(parameters or {}))
    store = FilesystemTestRunStore(tmp_path / "store")
    identifier = run_id(index)
    store.create_run(TestRun(run_id=identifier, diagnostic_id=spec.diagnostic_id, diagnostic_version=spec.version,
                             profile=profile, status=RunStatus.QUEUED, created_at=T0,
                             code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                             diagnostic_fingerprint=spec.fingerprint(), parameters=values,
                             environment=ENVIRONMENT))
    runtime_dir, data_root = tmp_path / f"runtime-{index}", tmp_path / f"data-{index}"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    return RunContext(run_id=identifier, diagnostic=spec, profile=profile, parameters=values, overrides={},
                      scenario=scenario, runtime_dir=runtime_dir, data_root=data_root,
                      artifacts=RunArtifacts(store, identifier), cancelled=asyncio.Event(),
                      deadline=asyncio.get_running_loop().time() + RUN_BUDGET_S, log=lambda message: None)


def store_terminal(context: RunContext, outcome) -> TestRun:
    """Write the terminal record the SUPERVISOR would write from this outcome, and return it.

    The verdict comes from the declaration, through the supervisor's own
    `derive_assertion_results`: nothing in this file judges a run.
    """
    store = FilesystemTestRunStore(context.data_root.parent / "store")
    metrics = dict(outcome.metrics)
    stored = store.get_run(context.run_id)
    running = store.update_run(transition_run(stored, RunStatus.RUNNING, at=T0), expected=stored)
    # The supervisor references what the runner COMMITTED (`RunContext.committed`), not
    # only the rare extras an outcome carries: `put_artifact` writes the bytes and the
    # record gains the reference when the run is concluded (the Slice 08 `commit_record`
    # idiom). Without this the run has no `trace.jsonl` and cannot have a bundle at all.
    committed = {ref.path: ref for ref in (*context.committed, *outcome.artifacts)}
    return store.update_run(
        complete_run(running, at=T0, metrics=metrics,
                     artifacts=tuple(committed[path] for path in sorted(committed)),
                     assertion_results=derive_assertion_results(context.diagnostic, metrics)),
        expected=running)


# ---------------------------------------------- cross-profile execution

async def test_one_declaration_runs_on_two_profiles_and_the_two_runs_are_not_comparable(tmp_path):
    """`voice.self_echo` v3 declares `virtual`, `audio` and `hardware:auto`.

    The first two are free, so both run here, against the SAME published declaration and
    the same blocking assertions. What the profiles do NOT share is the substitution:
    `virtual` uses the echo-guard double, `audio` the real WebRTC canceller. That is why
    `compare_runs` refuses to put the two side by side - a difference between them would
    be the profile, not the product, and the comparison says so instead of computing a
    delta nobody could interpret.
    """
    spec = catalog().describe("voice.self_echo", version=3).diagnostic
    assert {ProfileName.VIRTUAL, ProfileName.AUDIO, ProfileName.HARDWARE_AUTO} <= set(spec.profiles)

    virtual_context = build_context(tmp_path / "virtual", spec, ProfileName.VIRTUAL, parameters=FAST)
    virtual_outcome = await SelfEchoRunner().run(virtual_context)
    audio_context = build_context(tmp_path / "audio", spec, ProfileName.AUDIO, parameters=FAST)
    audio_outcome = await SelfEchoAudioRunner().run(audio_context)

    declared = {metric.name for metric in spec.metrics}
    for outcome in (virtual_outcome, audio_outcome):
        measured = dict(outcome.metrics)
        assert set(measured) <= declared, "a runner may not report a metric the declaration has not declared"
        for assertion in spec.assertions:
            if assertion.blocking:
                assert assertion.metric in measured, assertion.assertion_id

    virtual_run = store_terminal(virtual_context, virtual_outcome)
    audio_run = store_terminal(audio_context, audio_outcome)
    assert virtual_run.diagnostic_fingerprint == audio_run.diagnostic_fingerprint
    assert {classify_run(virtual_run).outcome, classify_run(audio_run).outcome} <= {
        RunOutcomeClass.PASSED, RunOutcomeClass.FAILED}

    comparison = compare_runs(virtual_run, audio_run, metrics=spec)
    assert comparison.comparable is False
    assert [item.reason.value for item in comparison.incomparable] == ["different_profile"]


# --------------------------------------------------------- run comparison

async def test_two_runs_of_one_diagnostic_compare_metric_by_metric_with_their_direction(tmp_path):
    """Change ONE parameter, run twice, read the deltas. This is step 4 of "Where to start"."""
    spec = catalog().describe("voice.self_echo", version=3).diagnostic
    baseline_context = build_context(tmp_path, spec, ProfileName.VIRTUAL, index=1,
                                     parameters={**FAST, "output.duration_ms": 900})
    baseline = store_terminal(baseline_context, await SelfEchoRunner().run(baseline_context))
    candidate_context = build_context(tmp_path, spec, ProfileName.VIRTUAL, index=2,
                                      parameters={**FAST, "output.duration_ms": 1400})
    candidate = store_terminal(candidate_context, await SelfEchoRunner().run(candidate_context))

    comparison = compare_runs(baseline, candidate, metrics=spec)
    assert comparison.comparable and comparison.incomparable == ()
    document = comparison.to_dict()
    assert {item["metric"] for item in document["metrics"]} >= {"barge_in.false_confirmed_count",
                                                                "output.completed"}
    # The parameter that moved is reported as a DIFFERENCE, never as an incomparability:
    # that is exactly what a sweep varies.
    assert any("output.duration_ms" in str(item) for item in document["differences"])
    # `output.played_ms` moved with the parameter, and the comparison knows which way is better.
    played = next(item for item in document["metrics"] if item["metric"] == "output.played_ms")
    assert played["baseline"] == 900 and played["candidate"] == 1400


# ------------------------------- ad-hoc -> promotion -> official diagnostic

SCENARIO = Scenario("voice.rollout_probe", (
    ScenarioStep("user.turn", {AT_MS: 0, "turn_id": "t1", "content_tag": "hello"}),
    ScenarioStep("control.checkpoint", {AT_MS: 200, "checkpoint_id": "settled"}),
))

SKELETON = {
    "diagnostic_id": "voice.rollout_probe",
    "title": "Rollout probe",
    "description": "An ad-hoc reproduction promoted after review (Slice 12 workflow test).",
    "profiles": [{"name": "virtual", "implementation": "testlab.scenario.virtual", "requires": [],
                  "cost": {"max_duration_s": 60, "max_cost_usd": 0}}],
    "parameters": [],
    "metrics": [{"name": "scenario.steps_performed", "unit": "count", "direction": "neutral",
                 "description": None},
                {"name": "scenario.checkpoints_reached", "unit": "count", "direction": "neutral",
                 "description": None},
                {"name": "scenario.expectations_declared", "unit": "count", "direction": "neutral",
                 "description": None},
                {"name": "scenario.expectations_failed_count", "unit": "count", "direction": "lower_better",
                 "description": None}],
    "assertions": [{"assertion_id": "every_step_performed", "metric": "scenario.steps_performed",
                    "comparator": "ge", "threshold": 2, "blocking": True, "description": None},
                   {"assertion_id": "expectations_met", "metric": "scenario.expectations_failed_count",
                    "comparator": "eq", "threshold": 0, "blocking": True, "description": None}],
    "score": {"method": "none", "components": []},
    "override_allowlist": [],
}


async def test_an_ad_hoc_scenario_becomes_an_official_diagnostic_that_runs(tmp_path):
    """The whole workflow, in the order `docs/testlab.md` ("Promotion") prescribes.

    1. run the ad-hoc scenario until it measures something, and keep the run id;
    2. promote it: pure, writes nothing, returns the manifest TEXT and a lock entry;
    3. publish that text and that entry the way a human reviewer does;
    4. load the catalog, which is what refuses a hole, a drift or an unlocked manifest;
    5. run the PROMOTED declaration and get the same measurement.
    """
    from jarvis.testlab.promotion import promote_scenario

    # 1. the ad-hoc run, against a declaration nobody has published.
    ad_hoc_spec = catalog().describe("speech.stale_supersession", version=2).diagnostic
    del ad_hoc_spec  # the ad-hoc declaration below is the one under test; this only proves the catalog loads

    empty = tmp_path / "catalog"
    empty.mkdir(parents=True)
    (empty / LOCK_FILE_NAME).write_text(CatalogLock().render(), encoding="utf-8")
    before = catalog(empty)
    assert before.list_diagnostics() == ()

    # 2. promotion is pure and writes nothing.
    result = promote_scenario(SCENARIO, SKELETON, published=before.published_fingerprints("voice.rollout_probe"),
                              implementations=default_implementations())
    assert result.version == 1 and not result.existing
    assert not (empty / result.path).exists(), "promotion must write nothing"

    # 3. the human's publication step: the manifest text, then the lock entry.
    path = empty / result.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.manifest_text, encoding="utf-8")
    lock = CatalogLock.decode_text((empty / LOCK_FILE_NAME).read_text(encoding="utf-8"))
    (empty / LOCK_FILE_NAME).write_text(lock.with_entry(result.lock_entry).render(), encoding="utf-8")

    # 4. loading is the gate: it is what refuses drift, a hole or an unlocked manifest.
    published = catalog(empty)
    entry = published.describe("voice.rollout_probe")
    assert entry.diagnostic.version == 1
    assert entry.resources_and_cost(ProfileName.VIRTUAL).available

    # 5. the promoted declaration runs, and its own scenario is what executes.
    context = build_context(tmp_path, entry.diagnostic, ProfileName.VIRTUAL, index=3,
                            scenario=entry.manifest.scenario)
    outcome = await ScenarioRunner().run(context)
    assert outcome.metrics["scenario.steps_performed"] == 2
    assert outcome.metrics["scenario.expectations_failed_count"] == 0
    run = store_terminal(context, outcome)
    assert classify_run(run).outcome is RunOutcomeClass.PASSED
    assert run.diagnostic_fingerprint == entry.diagnostic.fingerprint()

    # Re-promoting the same content is idempotent: the reviewer can run the flow twice.
    again = promote_scenario(SCENARIO, SKELETON,
                             published=published.published_fingerprints("voice.rollout_probe"),
                             implementations=default_implementations())
    assert again.existing and again.version == 1


# ----------------------------------------- retention through the facade

async def test_one_upkeep_pass_reclaims_space_in_all_three_stores(tmp_path):
    """`testlab retention --apply`, through the facade, on runs AND sweeps AND bundles."""
    from datetime import timedelta

    from jarvis.testlab.bundle_builder import build_diagnostic_bundle
    import tests.fakes.testlab_bundle as fx

    root = tmp_path / "runtime" / "testlab"
    # Age bounds nothing here (these records are all "now" as far as the bound is concerned):
    # one run is over the run count, and the one bundle is over the archive byte budget.
    policy = TestLabRetentionPolicy(enabled=True, max_age=timedelta(days=3650), max_runs=1, max_bundle_bytes=1)
    lab = TestLab(TestLabConfig(
        root=root, work_root=root / "work", runtime_root=tmp_path / "runtime", data_root=tmp_path / "data",
        policy=SupervisorPolicy(maintenance=MaintenancePolicy(enabled=True, retention=policy))))
    api = TestLabApi(lab)

    # Two terminal runs, one bundle, and nothing running.
    spec = catalog().describe("voice.self_echo", version=3).diagnostic
    for index in (1, 2):
        stored = lab.store.create_run(TestRun(
            run_id=run_id(index), diagnostic_id=spec.diagnostic_id, diagnostic_version=spec.version,
            profile=ProfileName.VIRTUAL, status=RunStatus.QUEUED, created_at=T0,
            code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
            diagnostic_fingerprint=spec.fingerprint(),
            parameters=resolve_parameters(spec.parameters, dict(FAST)), environment=ENVIRONMENT))
        running = lab.store.update_run(transition_run(stored, RunStatus.RUNNING, at=T0), expected=stored)
        lab.store.update_run(transition_run(running, RunStatus.CANCELLED, at=T0), expected=running)
    bundle = lab.bundle_store.put_bundle(build_diagnostic_bundle(fx.selector(), context=fx.context()))

    plan = await api.retention_plan()
    assert plan["enabled"] and len(plan["deletions"]) == 1, "one run over the bound"
    assert plan["archive"]["enabled"]
    assert [item["entry_id"] for item in plan["archive"]["deletions"]] == [bundle.bundle_id]

    before = sum(item.stat().st_size for item in root.rglob("*") if item.is_file())
    report = await api.maintain()
    after = sum(item.stat().st_size for item in root.rglob("*") if item.is_file())

    assert report["ran"] and len(report["deleted"]) == 1
    assert report["archive"]["ran"]
    assert [item["entry_id"] for item in report["archive"]["deleted"]] == [bundle.bundle_id]
    assert after < before, "the upkeep pass reclaimed no space"
    assert len((await api.query_runs())["runs"]) == 1
    assert (await api.list_bundles())["bundles"] == []
    await api.aclose()


async def test_retention_never_deletes_the_bundle_a_stored_run_points_at(tmp_path):
    """The rule that makes a run's own evidence safe: a referenced bundle is not collectable."""
    from datetime import timedelta

    from jarvis.testlab.bundle_builder import build_diagnostic_bundle
    import tests.fakes.testlab_bundle as fx

    root = tmp_path / "runtime" / "testlab"
    policy = TestLabRetentionPolicy(enabled=True, max_age=timedelta(days=3650), max_runs=1000, max_bundles=1)
    lab = TestLab(TestLabConfig(
        root=root, work_root=root / "work", runtime_root=tmp_path / "runtime", data_root=tmp_path / "data",
        policy=SupervisorPolicy(maintenance=MaintenancePolicy(enabled=True, retention=policy))))
    api = TestLabApi(lab)

    spec = catalog().describe("voice.self_echo", version=3).diagnostic
    stored = lab.store.create_run(TestRun(
        run_id=run_id(7), diagnostic_id=spec.diagnostic_id, diagnostic_version=spec.version,
        profile=ProfileName.VIRTUAL, status=RunStatus.QUEUED, created_at=T0,
        code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
        diagnostic_fingerprint=spec.fingerprint(),
        parameters=resolve_parameters(spec.parameters, dict(FAST)), environment=ENVIRONMENT))
    running = lab.store.update_run(transition_run(stored, RunStatus.RUNNING, at=T0), expected=stored)
    lab.store.update_run(transition_run(running, RunStatus.CANCELLED, at=T0), expected=running)
    bundle = lab.bundle_store.put_bundle(build_diagnostic_bundle(fx.selector(), context=fx.context()))
    lab.store.attach_bundle(stored.run_id, bundle.bundle_id)

    plan = await api.retention_plan()
    assert plan["archive"]["deletions"] == []
    assert plan["archive"]["blocked_referenced"] == 1
    report = await api.maintain()
    assert report["archive"]["deleted"] == []
    assert (await api.get_bundle(bundle.bundle_id))["bundle"]["bundle_id"] == bundle.bundle_id
    await api.aclose()


async def test_a_profile_the_declaration_does_not_offer_is_refused_by_the_catalog(tmp_path):
    """`voice.barge_in_response` is `hardware:guided` only, and `--profile virtual` is the default.

    The refusal must come from the CATALOG, before anything is created or locked. When it
    came from the supervisor instead, an operator running this with the Control Center open
    was told `testlab_supervisor_work_root_busy`, which names the wrong cause entirely.
    """
    from jarvis.testlab.catalog import CatalogError

    root = tmp_path / "runtime" / "testlab"
    lab = TestLab(TestLabConfig(
        root=root, work_root=root / "work", runtime_root=tmp_path / "runtime", data_root=tmp_path / "data",
        policy=SupervisorPolicy(maintenance=MaintenancePolicy(enabled=False))))
    api = TestLabApi(lab)

    with pytest.raises(CatalogError) as caught:
        await api.check_run_request("voice.barge_in_response", ProfileName.VIRTUAL)
    assert "does not declare profile virtual" in caught.value.detail
    assert lab.started is False and not root.exists(), "a refusal must create nothing"

    # The profile it DOES declare passes the same check (the grant is a later, separate gate).
    assert await api.check_run_request("voice.barge_in_response", ProfileName.HARDWARE_GUIDED)

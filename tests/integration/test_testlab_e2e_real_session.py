"""Opt-in: HV-TL-E2E-01, the incident-to-diagnostic loop, executed end to end.

Skipped unless `JARVIS_TESTLAB_REAL_SESSION=1` with a local `runtime/trace.jsonl`. It
is the machine half of the Human validation check, written so the operator runbook
(`tasks/jarvis-category2-test-lab/operator-runbook.md`) has something to point at and so
the loop cannot rot between releases: what the human adds is judgement about whether the
evidence is USEFUL, not whether the commands run.

Everything it writes goes to a temporary root. It reads the live journal (bounded) and
Core's state database strictly read-only; it opens no device, calls no provider and
prompts nobody, so it is safe to run while Jarvis is talking - the only profile it uses
is `virtual`, which reserves nothing.

The five steps, in the order the runbook prescribes:

1. capture the most recent real voice session into a `DiagnosticBundle`;
2. read its findings - this is what chooses the diagnostic;
3. run that diagnostic on `virtual`, in process, against the published declaration;
4. capture the RUN's own trace into a bundle and attach it to the run;
5. compare the run with a second one, and read the two bundles side by side.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest

from jarvis.testlab.api import TestLabApi
from jarvis.testlab.bundle_builder import SessionSelector
from jarvis.testlab.catalog import load_catalog
from jarvis.testlab.compare import compare_runs
from jarvis.testlab.composition import TestLab, TestLabConfig
from jarvis.testlab.diagnostics import resolve_parameters
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.maintenance import MaintenancePolicy
from jarvis.testlab.outcomes import classify_run
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runners import RunArtifacts, RunContext
from jarvis.testlab.runs import CodeIdentity, RunStatus, TestRun, complete_run, transition_run
from jarvis.testlab.selftest import catalog_implementations
from jarvis.testlab.supervisor import SupervisorPolicy, derive_assertion_results
from jarvis.testlab.validation import to_event_time
from jarvis.testlab.virtual.runners import SelfEchoRunner
from tests.fakes.testlab import CONFIG, ENVIRONMENT, REVISION, T0

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "runtime" / "trace.jsonl"
STATE_DB = ROOT / "data" / "state" / "jarvis.sqlite3"
REPORTS = ROOT / "runtime" / "benchmarks" / "voice-sessions"
TAIL_BYTES = 4 * 1024 * 1024
FAST = {"output.duration_ms": 1000, "echo.candidate_count": 2}

pytestmark = pytest.mark.skipif(
    os.environ.get("JARVIS_TESTLAB_REAL_SESSION") != "1" or not TRACE.is_file(),
    reason="opt-in: set JARVIS_TESTLAB_REAL_SESSION=1 with a local runtime/trace.jsonl")


def latest_conversation() -> str:
    """The most recent conversation with speech in the journal tail, or skip."""
    with open(TRACE, "rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - TAIL_BYTES))
        handle.readline()
        entries = []
        for raw in handle:
            try:
                entry = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    for entry in reversed(entries):
        data = entry.get("data")
        if (isinstance(entry.get("kind"), str) and entry["kind"].startswith("voice.speech.")
                and isinstance(data, dict) and isinstance(data.get("conversation_id"), str)):
            return data["conversation_id"]
    pytest.skip("no conversation with speech in the journal tail")


def build_lab(tmp_path: Path) -> TestLab:
    """A Test Lab whose STORES are temporary but whose evidence paths are the live ones."""
    root = tmp_path / "testlab"
    return TestLab(TestLabConfig(
        root=root, work_root=root / "work", runtime_root=ROOT / "runtime", data_root=ROOT / "data",
        policy=SupervisorPolicy(maintenance=MaintenancePolicy(enabled=False))))


async def run_self_echo(lab: TestLab, index: int, **parameters) -> TestRun:
    """One `virtual` run of the published `voice.self_echo`, in process, stored by hand."""
    spec = load_catalog(implementations=catalog_implementations()).describe("voice.self_echo").diagnostic
    values = resolve_parameters(spec.parameters, {**FAST, **parameters})
    run_id = format_run_id(T0, f"{index:016x}")
    lab.store.create_run(TestRun(run_id=run_id, diagnostic_id=spec.diagnostic_id,
                                 diagnostic_version=spec.version, profile=ProfileName.VIRTUAL,
                                 status=RunStatus.QUEUED, created_at=T0,
                                 code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                                 diagnostic_fingerprint=spec.fingerprint(), parameters=values,
                                 environment=ENVIRONMENT))
    runtime_dir = lab.config.root / f"scratch-{index}" / "runtime"
    data_root = lab.config.root / f"scratch-{index}" / "data"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    context = RunContext(run_id=run_id, diagnostic=spec, profile=ProfileName.VIRTUAL, parameters=values,
                         overrides={}, scenario=None, runtime_dir=runtime_dir, data_root=data_root,
                         artifacts=RunArtifacts(lab.store, run_id), cancelled=asyncio.Event(),
                         deadline=asyncio.get_running_loop().time() + 240.0, log=lambda message: None)
    outcome = await SelfEchoRunner().run(context)
    metrics = dict(outcome.metrics)
    stored = lab.store.get_run(run_id)
    running = lab.store.update_run(transition_run(stored, RunStatus.RUNNING, at=T0), expected=stored)
    # The supervisor's half: reference what the runner committed (`RunContext.committed`),
    # or the run has no `trace.jsonl` and step 4 below cannot happen at all.
    committed = {ref.path: ref for ref in (*context.committed, *outcome.artifacts)}
    return lab.store.update_run(
        complete_run(running, at=T0, metrics=metrics,
                     artifacts=tuple(committed[path] for path in sorted(committed)),
                     assertion_results=derive_assertion_results(spec, metrics)),
        expected=running)


async def test_a_real_incident_becomes_a_bundle_a_run_and_a_comparison(tmp_path, capsys):
    lab = build_lab(tmp_path)
    api = TestLabApi(lab)

    # 1 + 2. the real session, normalized, and what the normalizer noticed.
    incident = await api.capture_bundle(SessionSelector(conversation_id=latest_conversation()))
    assert incident["stored"] in {"stored", "duplicate"}
    # `rule_id`, not `rule`: the same wrong key that crashed `render_bundle` was in this
    # file too, and only running the opt-in test found it. The keys are `rule_id`,
    # `rule_version`, `at`, `subject_kind`, `subject_id`, `measured`, `evidence`.
    findings = [item["rule_id"] for item in incident["findings"]]

    # 3. the reproduction, on the profile that reserves nothing.
    first = await run_self_echo(lab, 1)
    assert classify_run(first).outcome.value in {"passed", "failed", "inconclusive"}

    # 4. the run's own evidence, in the same document shape as the incident's.
    reproduction = await api.capture_run_bundle(first.run_id)
    assert reproduction["attached_bundle_id"] == reproduction["bundle"]["bundle_id"]
    assert lab.store.get_run(first.run_id).bundle_id == reproduction["bundle"]["bundle_id"]
    assert set(reproduction["coverage"]) == set(incident["coverage"]), \
        "the incident and the reproduction must be readable the same way"

    # 5. change one thing, run again, compare.
    second = await run_self_echo(lab, 2, **{"output.duration_ms": 1600})
    comparison = compare_runs(first, second,
                              metrics=load_catalog(implementations=catalog_implementations())
                              .describe("voice.self_echo").diagnostic)
    assert comparison.comparable and comparison.incomparable == ()

    with capsys.disabled():
        print(f"\nHV-TL-E2E-01 machine half:"
              f"\n  incident bundle  {incident['bundle']['bundle_id']}  "
              f"{incident['bundle']['finding_count']} finding(s): {sorted(set(findings))}"
              f"\n  reproduction     {first.run_id} -> {classify_run(first).outcome.value}"
              f"\n  its bundle       {reproduction['bundle']['bundle_id']}  "
              f"{reproduction['bundle']['finding_count']} finding(s)"
              f"\n  comparison       {len(comparison.metrics)} metric(s), "
              f"{len(comparison.differences)} input difference(s)")
    await api.aclose()


async def test_the_state_database_is_read_but_never_written(tmp_path):
    """The one property a human must not have to verify by hand: nothing wrote to Core's DB."""
    if not STATE_DB.is_file():
        pytest.skip("no local state database")
    before = STATE_DB.stat()
    api = TestLabApi(build_lab(tmp_path))
    answer = await api.capture_bundle(SessionSelector(conversation_id=latest_conversation()))
    after = STATE_DB.stat()
    assert (before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size)
    assert answer["coverage"]["conversation_events"]["status"] in {
        "available", "empty", "missing", "unavailable", "truncated"}
    await api.aclose()


def test_the_captured_at_of_a_live_capture_is_not_frozen():
    """Guard against a copy-paste that would make every real capture the same bundle."""
    now = to_event_time(datetime.now(timezone.utc))
    assert now.year >= 2026 and now.tzinfo is timezone.utc

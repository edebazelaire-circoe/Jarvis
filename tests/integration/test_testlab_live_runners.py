"""The `live` profile, proven end to end against a provider DOUBLE — no network, no cost.

The only thing the `live` profile changes from `audio` is the Realtime session, and
that is exactly the seam these tests replace: everything else in the run (the writer,
the duplex capture, the real echo canceller, the journal, the metadata artifact, the
usage folding and the budget abort) is the code a real run executes.

One opt-in test at the end, behind `JARVIS_TESTLAB_LIVE=1` and `OPENAI_API_KEY`,
opens a REAL session. It has never been executed: Slice 08 leaves the first real
provider call to the human gate of Slices 09 and 12.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from jarvis.testlab.catalog import load_catalog
from jarvis.testlab.diagnostics import DiagnosticSpec, resolve_parameters
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.jobs import FAILURE_COST_BUDGET_EXCEEDED
from jarvis.testlab.live.cost import PROVIDER_FINAL_SOURCE, USAGE_KIND, CostModel
from jarvis.testlab.live.registry import LIVE_RUNNERS
from jarvis.testlab.live.runners import (
    METADATA_ARTIFACT,
    SETTINGS_FILE_NAME,
    METADATA_SCHEMA,
    LiveRunError,
    LiveScenarioRunner,
    QueueLatencyLiveRunner,
)
from jarvis.testlab.live.session import API_KEY_ENV, LIVE_OPT_IN_ENV, resolve_identity
from jarvis.testlab.outcomes import RunOutcomeClass
from jarvis.testlab.profiles import Capability, CostBounds, ProfileName, ProfileSpec
from jarvis.testlab.runners import CostBudgetExceeded, MeasurementUnavailable, RunArtifacts, RunContext
from jarvis.testlab.runs import CodeIdentity, RunStatus, TestRun
from jarvis.testlab.selftest import catalog_implementations
from jarvis.testlab.virtual.harness import FakeRealtimeSession
from jarvis.testlab.worker import runner_failure_code
from tests.fakes.testlab import CONFIG, ENVIRONMENT, NONCE, REVISION, T0
from tests.integration.test_testlab_audio_runners import commit_record

pytestmark = pytest.mark.asyncio

CATALOG_ROOT = Path(__file__).resolve().parents[2] / "jarvis" / "testlab" / "official"
RUN_ID = format_run_id(T0, NONCE)
RUN_BUDGET_S = 240.0
#: The model a live run on THIS host would resolve, read exactly as the runner reads it,
#: so the price fixture always applies to the model the estimate is computed for.
MODEL = resolve_identity().model_id

live_only = pytest.mark.skipif(
    os.getenv("JARVIS_TESTLAB_LIVE") != "1" or not os.getenv("OPENAI_API_KEY"),
    reason="requires JARVIS_TESTLAB_LIVE=1 and OPENAI_API_KEY (a real, paid provider session)",
)


# --------------------------------------------------------- the provider double

class UsageEmittingSession(FakeRealtimeSession):
    """A provider double that also behaves like a provider financially.

    It plays its own audio (a real provider is not driven by the runner) and emits
    `voice.realtime.usage` with the same six fields
    `jarvis/runtime/realtime_frontend_session.py` emits, so the cost path folds real
    payload shapes and not an invention of this test.
    """

    #: Tokens billed per speech, in order. The last entry is reported as the final total.
    usage_steps: tuple[tuple[int, int], ...] = ((20_000, 10_000),)

    def arm_usage(self, journal) -> None:
        self._journal = journal
        self._usage_index = 0

    async def speak(self, request, *, output_id: str | None = None) -> str:
        result = await super().speak(request, output_id=output_id)
        await self.play_audio(chunks=1)
        self._emit_usage()
        await self.finish_output(status="completed", transcript=request.text)
        return result

    def _emit_usage(self) -> None:
        journal = getattr(self, "_journal", None)
        if journal is None:
            return
        index = min(getattr(self, "_usage_index", 0), len(self.usage_steps) - 1)
        self._usage_index = index + 1
        input_tokens, output_tokens = self.usage_steps[index]
        journal.emit(USAGE_KIND, "Realtime session usage updated", data={
            "conversation_id": "conv-double", "session_id": self.session_id,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "duration_seconds": 1.5 * (index + 1),
            "source": PROVIDER_FINAL_SOURCE if index == len(self.usage_steps) - 1 else "provider_delta"})


def double_factory(session_class=UsageEmittingSession):
    sessions: list[FakeRealtimeSession] = []

    async def factory(context, session_id: str):
        del context
        session = session_class(name=f"double-{len(sessions) + 1}", session_id=session_id)
        sessions.append(session)
        return session

    factory.sessions = sessions  # type: ignore[attr-defined]
    return factory


# ------------------------------------------------------------------- fixtures

def queue_latency_live_spec(*, max_cost_usd: float | None = None) -> DiagnosticSpec:
    """`voice.queue_latency` with the `live` profile: v2, PUBLISHED by Slice 09.

    Read from the catalog rather than restated, so the runner and the declaration it is
    judged by cannot drift apart. `max_cost_usd` narrows the published bound for the test
    that proves the mid-run budget stops a session; it never widens it.
    """
    catalog = load_catalog(CATALOG_ROOT, implementations=catalog_implementations())
    spec = catalog.describe("voice.queue_latency", version=2).diagnostic
    assert ProfileName.LIVE in spec.profiles, "v2 is the version that adds the live profile"
    if max_cost_usd is None:
        return spec
    published = spec.profiles[ProfileName.LIVE]
    assert max_cost_usd <= published.cost.max_cost_usd, "a test may tighten the budget, never widen it"
    live = ProfileSpec(published.name, published.implementation,
                       CostBounds(published.cost.max_duration_s, max_cost_usd), published.requires)
    return DiagnosticSpec(diagnostic_id=spec.diagnostic_id, version=spec.version, title=spec.title,
                          domain=spec.domain, description=spec.description,
                          profiles={**dict(spec.profiles), ProfileName.LIVE: live},
                          parameters=spec.parameters, metrics=spec.metrics, assertions=spec.assertions,
                          score=spec.score)


def build_context(tmp_path: Path, spec: DiagnosticSpec, *, parameters=None, scenario=None,
                  pricing: dict | None = None) -> RunContext:
    parameters = resolve_parameters(spec.parameters, dict(parameters or {}))
    store = FilesystemTestRunStore(tmp_path / "store")
    store.create_run(TestRun(run_id=RUN_ID, diagnostic_id=spec.diagnostic_id, diagnostic_version=spec.version,
                             profile=ProfileName.LIVE, status=RunStatus.QUEUED, created_at=T0,
                             code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                             diagnostic_fingerprint=spec.fingerprint(), parameters=parameters,
                             environment=ENVIRONMENT))
    runtime_dir, data_root = tmp_path / "runtime", tmp_path / "data"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    # The settings COPY the supervisor writes into the scratch: the one place a run
    # reads its prices from (`jarvis.testlab.live.runners.read_pricing`).
    (runtime_dir / SETTINGS_FILE_NAME).write_text(
        json.dumps({"live_pricing": pricing} if pricing else {}), encoding="utf-8")
    return RunContext(run_id=RUN_ID, diagnostic=spec, profile=ProfileName.LIVE, parameters=parameters,
                      overrides={}, scenario=scenario, runtime_dir=runtime_dir, data_root=data_root,
                      artifacts=RunArtifacts(store, RUN_ID), cancelled=asyncio.Event(),
                      deadline=asyncio.get_running_loop().time() + RUN_BUDGET_S, log=lambda message: None)


def metadata_of(context: RunContext) -> dict:
    commit_record(context)
    return json.loads(context.artifacts.read(METADATA_ARTIFACT).decode("utf-8"))


def token_pricing(model_id: str, *, input_price: float, output_price: float) -> dict:
    from jarvis.runtime.pricing import PRICING_SCHEMA_VERSION

    return {model_id: {"schema_version": PRICING_SCHEMA_VERSION, "model_id": model_id, "currency": "usd",
                                  "input_price_per_million_tokens": input_price,
                                  "output_price_per_million_tokens": output_price,
                       "source": "Slice 08 test fixture",
                       "effective_at": "2026-01-01T00:00:00+00:00"}}


FAST = {"speech.request_count": 1, "brain.result_delay_ms": 0}


# ------------------------------------------------------------ the live runner

async def test_the_live_runner_measures_the_provider_latency_and_records_its_identity(tmp_path):
    spec = queue_latency_live_spec()
    context = build_context(tmp_path, spec, parameters=FAST)
    factory = double_factory()
    outcome = await QueueLatencyLiveRunner(session_factory=factory).run(context)
    metrics = dict(outcome.metrics)
    assert metrics["speech.delivered_count"] == 1
    assert "speech.started_to_first_audio_ms" in metrics and metrics["speech.started_to_first_audio_ms"] >= 0
    assert "speech.queue_free_to_started_ms" in metrics

    document = metadata_of(context)
    assert document["schema"] == METADATA_SCHEMA and document["schema_version"] == 1
    provider = document["provider"]
    assert provider["provider"] == "openai" and provider["model_id"]
    assert provider["session_id"] == factory.sessions[0].session_id
    assert provider["session_id"].startswith(RUN_ID), "the session id is derived from the run id"
    assert document["chain"]["aec_engaged"] is True and document["chain"]["device_opened"] is False


async def test_usage_is_folded_from_the_journal_lines_a_real_session_emits(tmp_path):
    spec = queue_latency_live_spec()
    context = build_context(tmp_path, spec, parameters=FAST)
    await QueueLatencyLiveRunner(session_factory=double_factory()).run(context)
    cost = metadata_of(context)["cost"]
    assert cost["usage"]["input_tokens"] == 20_000 and cost["usage"]["output_tokens"] == 10_000
    assert cost["usage"]["updates"] >= 1 and cost["usage"]["final"] is True
    assert cost["max_cost_usd"] == 0.50


async def test_an_unpriced_model_records_no_cost_and_names_the_basis(tmp_path):
    """No price table ships; an unpriced run says `unpriced` rather than guessing a number."""
    context = build_context(tmp_path, queue_latency_live_spec(), parameters=FAST)
    await QueueLatencyLiveRunner(session_factory=double_factory()).run(context)
    cost = metadata_of(context)["cost"]
    assert cost["cost_usd"] is None and cost["cost_basis"] == "unpriced"


async def test_a_configured_price_turns_the_usage_into_a_recorded_estimate(tmp_path):
    spec = queue_latency_live_spec()
    pricing = token_pricing(MODEL, input_price=5.0, output_price=20.0)
    context = build_context(tmp_path, spec, parameters=FAST, pricing=pricing)
    await QueueLatencyLiveRunner(session_factory=double_factory()).run(context)
    cost = metadata_of(context)["cost"]
    assert cost["model_id"] == MODEL
    assert cost["cost_basis"] == "provider_tokens"
    # 20 000 input at 5/M + 10 000 output at 20/M = 0.10 + 0.20
    assert cost["cost_usd"] == pytest.approx(0.30)
    assert cost["estimate"]["pricing_source"] == "Slice 08 test fixture"


async def test_the_budget_aborts_the_run_mid_flight_and_reads_inconclusive(tmp_path):
    """The declared ceiling is 0.01 USD and the double bills far more: the run must stop."""
    class Expensive(UsageEmittingSession):
        usage_steps = ((10_000_000, 10_000_000),)

    spec = queue_latency_live_spec(max_cost_usd=0.01)
    pricing = token_pricing(MODEL, input_price=5.0, output_price=20.0)
    context = build_context(tmp_path, spec, parameters=FAST, pricing=pricing)
    assert CostModel.from_settings(MODEL, pricing).priced
    with pytest.raises(CostBudgetExceeded) as caught:
        await QueueLatencyLiveRunner(session_factory=double_factory(Expensive)).run(context)
    assert caught.value.code == "testlab_cost_budget_exceeded"
    assert "0.0100 USD budget" in caught.value.detail
    # The worker gives it its own code, and the outcome table reads it as inconclusive.
    assert runner_failure_code(caught.value) == FAILURE_COST_BUDGET_EXCEEDED
    from jarvis.testlab.outcomes import FAILURE_OUTCOMES

    assert FAILURE_OUTCOMES[FAILURE_COST_BUDGET_EXCEEDED] is RunOutcomeClass.INCONCLUSIVE


async def test_a_provider_that_never_speaks_is_inconclusive_not_a_crash(tmp_path):
    """No audio from the provider is a finding about the provider, never a lab defect."""
    class Mute(FakeRealtimeSession):
        async def speak(self, request, *, output_id: str | None = None) -> str:
            return await super().speak(request, output_id=output_id)  # no audio, no completion

    context = build_context(tmp_path, queue_latency_live_spec(), parameters=FAST)
    context.deadline = asyncio.get_running_loop().time() + 25.0
    with pytest.raises(MeasurementUnavailable) as caught:
        await QueueLatencyLiveRunner(session_factory=double_factory(Mute)).run(context)
    assert caught.value.code in ("testlab_live_run_failed", "testlab_virtual_run_failed")
    assert runner_failure_code(caught.value) == "measurement_unavailable"


async def test_the_live_runner_refuses_to_open_a_real_session_without_the_opt_in(tmp_path, monkeypatch):
    """`session_factory=None` means the real provider, and the gates are checked first."""
    monkeypatch.delenv(LIVE_OPT_IN_ENV, raising=False)
    monkeypatch.setenv(API_KEY_ENV, "sk-not-used")
    context = build_context(tmp_path, queue_latency_live_spec(), parameters=FAST)
    with pytest.raises(LiveRunError) as caught:
        await QueueLatencyLiveRunner().run(context)
    assert caught.value.code == "testlab_live_opt_in_missing"
    assert LIVE_OPT_IN_ENV in caught.value.detail


async def test_a_live_run_without_a_key_is_refused_before_any_socket(tmp_path, monkeypatch):
    monkeypatch.setenv(LIVE_OPT_IN_ENV, "1")
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    context = build_context(tmp_path, queue_latency_live_spec(), parameters=FAST)
    with pytest.raises(LiveRunError) as caught:
        await QueueLatencyLiveRunner().run(context)
    assert API_KEY_ENV in caught.value.detail


async def test_the_generic_live_runner_needs_a_scenario(tmp_path):
    context = build_context(tmp_path, queue_latency_live_spec(), parameters=FAST)
    with pytest.raises(LiveRunError):
        await LiveScenarioRunner(session_factory=double_factory()).run(context)


async def test_every_registered_live_name_builds_a_runner():
    registry = catalog_implementations()
    for name, class_name in LIVE_RUNNERS.items():
        entry = registry.resolve(name, ProfileName.LIVE)
        assert entry.factory is not None
        assert type(entry.factory()).__name__ == class_name


# ------------------------------------------------------------ the human gate

@live_only
async def test_a_real_provider_session_measures_real_latency(tmp_path):
    """OPT-IN, PAID, NEVER RUN IN CI. The first real execution is the Slice 09/12 human gate.

    It opens a real Realtime session, times one turn and records provider identity,
    usage and cost. Slice 08 wrote it and did not run it: its result is "unverified",
    not "passed".
    """
    spec = queue_latency_live_spec(max_cost_usd=0.25)
    parameters = {"speech.request_count": 1, "brain.result_delay_ms": 0}
    context = build_context(tmp_path, spec, parameters=parameters)
    outcome = await QueueLatencyLiveRunner().run(context)
    metrics = dict(outcome.metrics)
    assert metrics["speech.delivered_count"] >= 1
    assert metrics["speech.started_to_first_audio_ms"] > 0, "a real provider cannot answer instantly"
    document = metadata_of(context)
    assert document["provider"]["session_id"]
    assert document["cost"]["usage"]["updates"] >= 1, "a real session reports its usage"

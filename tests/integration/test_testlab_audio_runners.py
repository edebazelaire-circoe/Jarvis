"""The `audio` profile against the real production audio chain, in this process.

No device and no provider: the PortAudio stream is the harness double and the
Realtime session is the deterministic one, but the writer, the duplex capture, the
WebRTC echo canceller and the near-end detector are the production objects, working
on real samples. That is exactly the half the `virtual` profile cannot prove.

The decisive pair of tests is `test_the_real_echo_canceller_refuses_jarvis_own_echo`
and `test_a_real_near_end_voice_over_the_echo_is_confirmed`: the same run, the same
code, the same stimulus schedule, and the only difference is whether the injected
microphone signal correlates with what Jarvis played. One passes, the other fails.
A diagnostic that could not tell them apart would be worthless.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from jarvis.testlab.audio.chain import INPUT_BLOCK_MS, build_capture
from jarvis.testlab.audio.fixtures import AudioFixtureRoot, build_reference_clip, build_silence, write_wav_pcm16
from jarvis.testlab.audio.runners import (
    CLIP_ARTIFACT,
    DEFAULT_ECHO_GAIN_DB,
    ECHO_COUPLING_PARAMETER,
    DEFAULT_CLIP_REF,
    METADATA_ARTIFACT,
    METADATA_SCHEMA,
    AudioInjector,
    AudioScenarioRunner,
    SelfEchoAudioRunner,
    store_clip,
)
from jarvis.testlab.catalog import load_catalog
from jarvis.testlab.diagnostics import (
    AssertionSpec,
    Comparator,
    DiagnosticSpec,
    MetricDirection,
    MetricSpec,
    MetricUnit,
    ParameterSpec,
    ParameterType,
    assertions_verdict,
    evaluate_assertion,
    resolve_parameters,
)
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.profiles import CostBounds, ProfileName, ProfileSpec
from jarvis.testlab.runners import MeasurementUnavailable, RunArtifacts, RunContext
from jarvis.testlab.runs import ArtifactKind, CodeIdentity, RunStatus, TestRun
from jarvis.testlab.scenarios import Scenario, ScenarioStep
from jarvis.testlab.selftest import catalog_implementations
from jarvis.testlab.store import ArtifactWriteLimits
from tests.fakes.testlab import CONFIG, ENVIRONMENT, NONCE, REVISION, T0

pytestmark = pytest.mark.asyncio

CATALOG_ROOT = Path(__file__).resolve().parents[2] / "jarvis" / "testlab" / "official"
RUN_ID = format_run_id(T0, NONCE)
RUN_BUDGET_S = 240.0
#: Short on purpose: the point is the acoustic decision, not the length of the output.
FAST_PARAMETERS = {"output.duration_ms": 1000, "echo.candidate_count": 2}


#: The `echo.coupling_db` ParameterSpec of the proposed v2, kept here in the shape the
#: proposal file carries so the test and the manifest cannot drift apart.
ECHO_COUPLING_SPEC = ParameterSpec(
    ECHO_COUPLING_PARAMETER, ParameterType.FLOAT, default=DEFAULT_ECHO_GAIN_DB, minimum=-60.0, maximum=0.0,
    description="Acoustic coupling of the injected echo, in dB relative to what Jarvis played (audio profile).")


def self_echo_audio_spec() -> DiagnosticSpec:
    """`voice.self_echo` with the `audio` profile added: the v2 proposed for approval."""
    base = load_catalog(CATALOG_ROOT, implementations=catalog_implementations()).describe("voice.self_echo").diagnostic
    audio = ProfileSpec(ProfileName.AUDIO, "voice.self_echo.audio", CostBounds(300, 0))
    return DiagnosticSpec(diagnostic_id=base.diagnostic_id, version=2, title=base.title, domain=base.domain,
                          description=base.description, profiles={**dict(base.profiles), ProfileName.AUDIO: audio},
                          parameters=(*base.parameters, ECHO_COUPLING_SPEC), metrics=base.metrics,
                          assertions=base.assertions, score=base.score)


def scenario_audio_spec() -> DiagnosticSpec:
    """An ad-hoc diagnostic on `testlab.scenario.audio`, declaring what that runner can measure."""
    return DiagnosticSpec(
        diagnostic_id="voice.audio_probe", version=1, title="Ad-hoc audio scenario probe", domain="voice",
        profiles={ProfileName.AUDIO: ProfileSpec(ProfileName.AUDIO, "testlab.scenario.audio", CostBounds(300, 0))},
        metrics=(MetricSpec("scenario.steps_performed", MetricUnit.COUNT, MetricDirection.NEUTRAL),
                 MetricSpec("audio.injected_block_count", MetricUnit.COUNT, MetricDirection.NEUTRAL),
                 MetricSpec("audio.injected_ms", MetricUnit.MS, MetricDirection.NEUTRAL)),
        assertions=(AssertionSpec("audio_reached_the_chain", "audio.injected_block_count", Comparator.GE, 1,
                                  blocking=True),))


def build_context(tmp_path: Path, spec: DiagnosticSpec, *, parameters=None, scenario=None,
                  allow_audio: bool = False, budget_s: float = RUN_BUDGET_S) -> RunContext:
    parameters = resolve_parameters(spec.parameters, dict(parameters or {}))
    store = FilesystemTestRunStore(tmp_path / "store", limits=ArtifactWriteLimits(allow_audio=allow_audio))
    store.create_run(TestRun(run_id=RUN_ID, diagnostic_id=spec.diagnostic_id, diagnostic_version=spec.version,
                             profile=ProfileName.AUDIO, status=RunStatus.QUEUED, created_at=T0,
                             code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                             diagnostic_fingerprint=spec.fingerprint(), parameters=parameters,
                             environment=ENVIRONMENT))
    runtime_dir, data_root = tmp_path / "runtime", tmp_path / "data"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    return RunContext(run_id=RUN_ID, diagnostic=spec, profile=ProfileName.AUDIO, parameters=parameters,
                      overrides={}, scenario=scenario, runtime_dir=runtime_dir, data_root=data_root,
                      artifacts=RunArtifacts(store, RUN_ID), cancelled=asyncio.Event(),
                      deadline=asyncio.get_running_loop().time() + budget_s, log=lambda message: None)


def commit_record(context: RunContext, *, allow_audio: bool = False) -> None:
    """Reference the committed artifacts in the record, exactly as the supervisor does.

    `read_artifact` serves only what the RECORD references (Slice 02), so a test that
    wants to read back a runner's evidence must first do the supervisor's half.
    """
    from jarvis.testlab.runs import complete_run, transition_run

    store = FilesystemTestRunStore(context.data_root.parent / "store",
                                   limits=ArtifactWriteLimits(allow_audio=allow_audio))
    stored = store.get_run(RUN_ID)
    running = transition_run(stored, RunStatus.RUNNING, at=T0)
    store.update_run(running, expected=stored)
    store.update_run(complete_run(running, at=T0, assertion_results=(), metrics={}, score=None,
                                  artifacts=tuple(context.committed)), expected=running)


def metadata_of(context: RunContext) -> dict:
    commit_record(context)
    return json.loads(context.artifacts.read(METADATA_ARTIFACT).decode("utf-8"))


def verdict_of(spec: DiagnosticSpec, metrics) -> str:
    index = spec.metric_index
    results = tuple(evaluate_assertion(item, index[item.metric], metrics.get(item.metric))
                    for item in spec.assertions)
    return assertions_verdict(results).value


# ------------------------------------------------------------ the real chain

async def test_the_real_echo_canceller_refuses_jarvis_own_echo(tmp_path):
    """Jarvis's own output comes back as the microphone signal; no candidate may be confirmed."""
    spec = self_echo_audio_spec()
    context = build_context(tmp_path, spec, parameters=FAST_PARAMETERS)
    outcome = await SelfEchoAudioRunner().run(context)
    metrics = dict(outcome.metrics)
    assert metrics["barge_in.false_confirmed_count"] == 0
    assert metrics["barge_in.rejected_count"] == FAST_PARAMETERS["echo.candidate_count"]
    assert metrics["output.completed"] is True
    assert metrics["output.played_ms"] >= FAST_PARAMETERS["output.duration_ms"]
    assert verdict_of(spec, metrics) == "passed"


async def test_a_real_near_end_voice_over_the_echo_is_confirmed(tmp_path):
    """The same run with a loud uncorrelated voice in the microphone: the guard must open.

    This is what makes the diagnostic non-vacuous on this profile. A stack that simply
    never confirmed anything would pass the test above; it fails this one.
    """
    class NearEndVoice(SelfEchoAudioRunner):
        async def inject_echo_candidate(self, context, stack):
            AudioInjector(stack).inject_pcm(build_reference_clip(duration_ms=400, frequencies=(330, 1450),
                                                                 peak=0.95, attack_ms=5, release_ms=5))
            await stack.session.interrupt()

    spec = self_echo_audio_spec()
    context = build_context(tmp_path, spec, parameters={"output.duration_ms": 1000, "echo.candidate_count": 1})
    outcome = await NearEndVoice().run(context)
    metrics = dict(outcome.metrics)
    assert metrics["barge_in.false_confirmed_count"] >= 1
    assert verdict_of(spec, metrics) == "failed"


async def test_the_run_records_what_the_chain_actually_exercised(tmp_path):
    spec = self_echo_audio_spec()
    context = build_context(tmp_path, spec, parameters=FAST_PARAMETERS)
    await SelfEchoAudioRunner().run(context)
    document = metadata_of(context)
    assert document["schema"] == METADATA_SCHEMA and document["schema_version"] == 1
    assert document["profile"] == "audio" and document["run_id"] == RUN_ID
    assert document["sample_rate"] == 24_000 and document["input_block_ms"] == INPUT_BLOCK_MS
    assert document["device_opened"] is False, "the audio profile never opens a device"
    assert document["input_device"] is None and document["output_device"] is None
    assert document["duplex_engaged"] is True
    assert document["aec_engaged"] is True and document["canceller"] == "WebRtcEchoCanceller"
    assert document["echo_coupling_db"] < 0 and document["reference_peak_dbfs"] > -20
    assert "C:\\" not in json.dumps(document), "metadata carries no host path"


async def test_a_stimulus_the_stack_never_answers_is_inconclusive_not_a_crash(tmp_path):
    """A stack deaf to provider VAD must not read as a passing self-echo run."""
    class SilentOnset(SelfEchoAudioRunner):
        async def inject_echo_candidate(self, context, stack):
            return None  # no provider onset at all: nothing to decide

    context = build_context(tmp_path, self_echo_audio_spec(), parameters=FAST_PARAMETERS, budget_s=25.0)
    with pytest.raises(MeasurementUnavailable) as caught:
        await SilentOnset().run(context)
    assert "barge-in decision" in caught.value.detail


async def test_without_the_canceller_the_run_says_so_instead_of_pretending(tmp_path):
    """A measurement taken without the AEC must never be read as a measurement of the AEC."""
    build = build_capture(echo_cancellation=False)
    assert build.aec_engaged is False
    assert build.aec_unavailable_reason == "disabled_by_parameter"
    assert build.to_dict()["canceller"] is None


# ------------------------------------------------------------ audio.inject

def _step(at_ms: int, primitive: str, **args) -> ScenarioStep:
    return ScenarioStep(primitive, {"at_ms": at_ms, **args})


async def test_the_generic_audio_runner_injects_a_declared_fixture(tmp_path):
    scenario = Scenario(scenario_id="inject_probe", title="Inject a fixture",
                        steps=(_step(0, "audio.inject", audio_ref=DEFAULT_CLIP_REF),
                               _step(1200, "audio.inject", audio_ref="silence-500ms.wav", gain_db=-6.0),
                               _step(1800, "control.checkpoint", checkpoint_id="injected")))
    spec = scenario_audio_spec()
    context = build_context(tmp_path, spec, scenario=scenario)
    outcome = await AudioScenarioRunner().run(context)
    metrics = dict(outcome.metrics)
    assert metrics["scenario.steps_performed"] == 3
    assert metrics["audio.injected_block_count"] == 30, "1000 ms + 500 ms of 50 ms production blocks"
    assert metrics["audio.injected_ms"] == 1500
    assert verdict_of(spec, metrics) == "passed"
    injected = metadata_of(context)["injected"]
    assert [item["ref"] for item in injected] == [DEFAULT_CLIP_REF, "silence-500ms.wav"]
    assert injected[1]["gain_db"] == -6.0 and injected[1]["duration_ms"] == 500


async def test_audio_inject_refuses_a_fixture_outside_the_root_as_inconclusive(tmp_path):
    """A scenario cannot reach a file a reviewer did not put in the fixture root."""
    scenario = Scenario(scenario_id="inject_escape", title="Escape the root",
                        steps=(_step(0, "audio.inject", audio_ref="clips/nowhere.wav"),))
    context = build_context(tmp_path, scenario_audio_spec(), scenario=scenario)
    with pytest.raises(MeasurementUnavailable) as caught:
        await AudioScenarioRunner().run(context)
    assert caught.value.code in ("testlab_audio_fixture_unknown", "testlab_virtual_step_failed")


async def test_a_traversal_audio_ref_never_even_reaches_the_runner():
    """The Slice 02 path rule refuses it when the scenario is checked, before any run exists.

    The worker checks a supplied scenario before a single step executes, so an
    `audio_ref` that tries to leave the root is a REFUSED run, not an inconclusive one.
    """
    from jarvis.testlab.primitives import DEFAULT_PRIMITIVES, check_scenario
    from jarvis.testlab.validation import TestLabError

    scenario = Scenario(scenario_id="traversal_probe", title="Traversal",
                        steps=(_step(0, "audio.inject", audio_ref="../../secret.wav"),))
    with pytest.raises(TestLabError) as caught:
        check_scenario(scenario, primitives=DEFAULT_PRIMITIVES, profiles=(ProfileName.AUDIO,))
    assert caught.value.code == "testlab_primitive_args_invalid"


async def test_the_generic_audio_runner_refuses_a_diagnostic_it_cannot_measure(tmp_path):
    spec = DiagnosticSpec(
        diagnostic_id="voice.audio_probe", version=1, title="Undeclarable", domain="voice",
        profiles={ProfileName.AUDIO: ProfileSpec(ProfileName.AUDIO, "testlab.scenario.audio", CostBounds(60, 0))},
        metrics=(MetricSpec("barge_in.false_confirmed_count", MetricUnit.COUNT, MetricDirection.LOWER_BETTER),),
        assertions=(AssertionSpec("none", "barge_in.false_confirmed_count", Comparator.EQ, 0, blocking=True),))
    scenario = Scenario(scenario_id="probe", title="Probe",
                        steps=(_step(0, "audio.inject", audio_ref=DEFAULT_CLIP_REF),))
    context = build_context(tmp_path, spec, scenario=scenario)
    with pytest.raises(MeasurementUnavailable) as caught:
        await AudioScenarioRunner().run(context)
    assert "cannot measure" in caught.value.detail


async def test_a_run_without_a_scenario_is_inconclusive(tmp_path):
    context = build_context(tmp_path, scenario_audio_spec(), scenario=None)
    with pytest.raises(MeasurementUnavailable):
        await AudioScenarioRunner().run(context)


# --------------------------------------------------------- audio artifacts

async def test_an_audio_clip_is_stored_only_when_the_store_allows_audio(tmp_path):
    """Never by default: the store refuses the write and the run keeps its measurement."""
    spec = scenario_audio_spec()
    pcm = build_silence(duration_ms=200)

    refusing = build_context(tmp_path / "off", spec, allow_audio=False)
    assert store_clip(refusing, pcm) is False
    assert refusing.committed == []

    allowing = build_context(tmp_path / "on", spec, allow_audio=True)
    assert store_clip(allowing, pcm) is True
    ref = allowing.committed[0]
    assert ref.kind is ArtifactKind.AUDIO_CLIP and ref.media_type == "audio/wav"
    assert ref.path == CLIP_ARTIFACT and len(ref.path) <= 171
    commit_record(allowing, allow_audio=True)
    assert allowing.artifacts.read(CLIP_ARTIFACT)[:4] == b"RIFF"


async def test_an_audio_clip_over_the_kind_cap_is_refused_and_logged(tmp_path):
    """32 MiB is the `audio_clip` cap; the run learns, it does not die."""
    from jarvis.testlab.store import DEFAULT_ARTIFACT_MAX_BYTES

    context = build_context(tmp_path, scenario_audio_spec(), allow_audio=True)
    lines: list[str] = []
    context.log = lines.append
    oversized = bytes(DEFAULT_ARTIFACT_MAX_BYTES[ArtifactKind.AUDIO_CLIP] + 64)
    assert store_clip(context, oversized) is False
    assert lines and "testlab_store_artifact_too_large" in lines[0]


async def test_a_fixture_root_a_test_declares_is_honoured_and_still_contained(tmp_path):
    root = tmp_path / "own-fixtures"
    write_wav_pcm16(root / "local.wav", build_silence(duration_ms=100), 24_000)
    declared = AudioFixtureRoot(root)
    assert declared.refs() == ("local.wav",)
    assert declared.resolve("local.wav").parent == root.resolve()


async def test_the_echo_coupling_is_a_declared_parameter_the_run_honours(tmp_path):
    """Slice 08 rework: `echo.coupling_db` is declared, so it can be swept and overridden.

    The runner used to read it with a literal default that no manifest declared, which
    made it unreachable from a `RunRequest` and invisible to `check_run_against_spec`.
    """
    spec = self_echo_audio_spec()
    declared = {item.name: item for item in spec.parameters}
    assert ECHO_COUPLING_PARAMETER in declared
    coupling = declared[ECHO_COUPLING_PARAMETER]
    assert coupling.default == DEFAULT_ECHO_GAIN_DB
    assert (coupling.minimum, coupling.maximum) == (-60.0, 0.0)

    # A supplied value travels the ordinary declared path and reaches the stimulus.
    context = build_context(tmp_path, spec, parameters={**FAST_PARAMETERS, ECHO_COUPLING_PARAMETER: -30.0})
    assert context.parameters[ECHO_COUPLING_PARAMETER] == -30.0
    await SelfEchoAudioRunner().run(context)
    document = metadata_of(context)
    assert document["echo_coupling_db"] == -30.0
    assert document["echo_peak_dbfs"] == pytest.approx(document["reference_peak_dbfs"] - 30.0, abs=0.5)


async def test_an_out_of_range_coupling_is_refused_by_the_declaration(tmp_path):
    """Being declared is what makes it bounded: +20 dB of "echo" is not a room."""
    from jarvis.testlab.validation import TestLabError

    spec = self_echo_audio_spec()
    with pytest.raises(TestLabError):
        resolve_parameters(spec.parameters, {ECHO_COUPLING_PARAMETER: 20.0})

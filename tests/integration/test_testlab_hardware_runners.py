"""The `hardware:auto` and `hardware:guided` runners, over a simulated room.

**No device is opened and no human is needed.** `sys.modules["sounddevice"]` is the
double in `tests/fakes/sounddevice_double.py`, so the PortAudio open, the production
callback, the production chunked writer, the production duplex capture and the real
WebRTC echo canceller all run exactly as they do on the workstation — over a room that
is a few lines of arithmetic. The human is `HeadlessPrompter` or a scripted one.

The tests that matter are the pairs:

- `test_the_room_echo_never_confirms_a_barge_in` against
  `test_a_real_voice_in_the_room_is_confirmed_as_a_barge_in`: the same run, the same
  schedule, the only difference being whether the microphone hears Jarvis's own echo or
  a loud uncorrelated voice. One reports 0 confirmations, the other reports one. A
  diagnostic that could not tell them apart would be worthless.
- `test_a_late_acknowledgement_on_a_tolerant_step_is_evidence_and_the_run_continues`
  against `test_a_late_acknowledgement_on_the_interrupt_step_is_inconclusive`: the same
  late human, and whether it voids the measurement is a property of the STEP.

Every device failure and every way a human can not do a step ends `MeasurementUnavailable`,
which the worker records as `measurement_unavailable` and reads as `inconclusive`. None
of them may ever read as a crash, and none of them may leave a stream open.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from jarvis.runtime.audio_devices import AudioDiagnosticError
from jarvis.testlab.catalog import DEFAULT_CATALOG_ROOT
from jarvis.testlab.diagnostics import (
    AssertionSpec,
    Comparator,
    DiagnosticSpec,
    MetricDirection,
    MetricSpec,
    MetricUnit,
    assertions_verdict,
    evaluate_assertion,
    resolve_parameters,
)
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.hardware.devices import (
    DEVICE_INPUT_UNAVAILABLE,
    DEVICE_NO_OUTPUT,
    DEVICE_NO_SIGNAL,
    DEVICE_OPEN_FAILED,
    DEVICE_OUTPUT_UNAVAILABLE,
    DeviceUnavailable,
)
from jarvis.testlab.hardware.prompts import (
    PROMPT_LATE,
    PROMPT_REFUSED,
    PROMPT_TIMED_OUT,
    PROMPTER_FAILED,
    TRANSCRIPT_ARTIFACT,
    TRANSCRIPT_SCHEMA,
    GuidedPrompt,
    GuidedPromptUnavailable,
    HeadlessPrompter,
    PromptOutcome,
    PromptReply,
)
from jarvis.testlab.hardware.runners import (
    FIRST_ONSET_BLOCK,
    HARDWARE_RUN_FAILED,
    FIRST_ONSET_METRIC,
    GUIDED_CLAIM_UNMEASURED,
    GUIDED_STEP_NOT_FOLLOWED,
    METADATA_ARTIFACT,
    PROMPT_DONE,
    PROMPT_INTERRUPT,
    PROMPT_SILENCE,
    TRUE_CONFIRMED_METRIC,
    GuidedScenarioRunner,
    HardwareScenarioRunner,
    SelfEchoGuidedRunner,
    SelfEchoHardwareRunner,
)
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.manifests import decode_manifest_text
from jarvis.testlab.profiles import CostBounds, ProfileName, ProfileSpec
from jarvis.testlab.runners import MeasurementUnavailable, RunArtifacts, RunCancelled, RunContext
from jarvis.testlab.runs import ArtifactKind, CodeIdentity, RunStatus, TestRun
from jarvis.testlab.scenarios import Scenario, ScenarioStep
from jarvis.testlab.store import ArtifactWriteLimits
from tests.fakes.sounddevice_double import FakeRoom, FakeSoundDevice, install, speech_like
from tests.fakes.testlab import CONFIG, ENVIRONMENT, NONCE, REVISION, T0

pytestmark = pytest.mark.asyncio

#: The two manifests PUBLISHED by Slice 12, read from the catalog rather than restated so
#: the runners and the declarations that judge them cannot drift. `voice.self_echo` v3
#: carries the `hardware:auto` NEGATIVE claim; the guided POSITIVE claim is its own
#: diagnostic, with a blocking assertion, because a gate that never opens satisfies the
#: negative one perfectly while being completely broken.
PUBLISHED_V3 = DEFAULT_CATALOG_ROOT / "voice" / "self_echo.v3.json"
PUBLISHED_GUIDED = DEFAULT_CATALOG_ROOT / "voice" / "barge_in_response.v1.json"
RUN_ID = format_run_id(T0, NONCE)
RUN_BUDGET_S = 120.0
#: Short on purpose: the point is the acoustic decision, not the length of the output.
FAST = {"output.duration_ms": 1200, "echo.candidate_count": 2}
#: Repeats behind the defaults distribution assertions. One run cannot tell a coin flip
#: from a measurement, which is the whole reason those assertions exist.
DEFAULTS_REPEATS = 3
#: Attempts a test gets to reach the situation it describes. Some guided runs end in the
#: ANTI-VACUITY refusal instead — the stack answered none of the provider onsets, about one
#: in ten at these settings. That is an honest `inconclusive` and a property of this room's
#: acoustics, not of the rule under test, so a test that asserted one outcome was measuring
#: the double. Retrying past it, and asserting the situation was reached at least once,
#: keeps the assertion sharp instead of widening it.
GUIDED_ATTEMPTS = 4


def is_anti_vacuity(exc: MeasurementUnavailable) -> bool:
    """Did this run refuse because the stack decided on none of the onsets it was given?"""
    return exc.code == HARDWARE_RUN_FAILED and "answered none of" in exc.detail


async def guided_attempts(build_run, *, attempts: int = GUIDED_ATTEMPTS):
    """Run a guided scenario repeatedly; return every result that is not an anti-vacuity refusal.

    `build_run` is an async callable taking the attempt index and returning the run's
    outcome, or raising. Results come back as `("outcome", metrics, context, store)` or
    `("refused", exc, context, store)`, anti-vacuity refusals dropped.
    """
    results = []
    skipped = 0
    for index in range(attempts):
        context, store, coroutine = build_run(index)
        try:
            outcome = await coroutine
        except MeasurementUnavailable as exc:
            if is_anti_vacuity(exc):
                skipped += 1
                continue
            results.append(("refused", exc, context, store))
        else:
            results.append(("outcome", outcome, context, store))
    assert results, (f"all {attempts} attempts ended in the anti-vacuity refusal; the situation "
                     "this test describes was never reached")
    return results, skipped


def self_echo_spec() -> DiagnosticSpec:
    return decode_manifest_text(PUBLISHED_V3.read_text(encoding="utf-8")).diagnostic


def guided_spec(*, blocking: bool = True) -> DiagnosticSpec:
    """The guided diagnostic. `blocking=False` drops the assertion that makes a zero a VERDICT.

    Whether "the human interrupted and nothing was confirmed" reads `failed` or
    `inconclusive` is a property of the DECLARATION, and both halves are exercised.
    """
    from dataclasses import replace

    spec = decode_manifest_text(PUBLISHED_GUIDED.read_text(encoding="utf-8")).diagnostic
    if blocking:
        return spec
    return replace(spec, assertions=tuple(item for item in spec.assertions
                                          if item.metric != TRUE_CONFIRMED_METRIC))


def scenario_spec(profile: ProfileName, implementation: str) -> DiagnosticSpec:
    """An ad-hoc diagnostic on a generic hardware runner, declaring what that runner measures."""
    metrics = [MetricSpec("scenario.steps_performed", MetricUnit.COUNT, MetricDirection.NEUTRAL),
               MetricSpec("audio.played_ms", MetricUnit.MS, MetricDirection.NEUTRAL),
               MetricSpec("audio.captured_ms", MetricUnit.MS, MetricDirection.NEUTRAL)]
    if profile is ProfileName.HARDWARE_GUIDED:
        metrics.append(MetricSpec("guided.prompt_count", MetricUnit.COUNT, MetricDirection.NEUTRAL))
        metrics.append(MetricSpec("guided.unfollowed_count", MetricUnit.COUNT, MetricDirection.LOWER_BETTER))
    return DiagnosticSpec(
        diagnostic_id="voice.hardware_probe", version=1, title="Ad-hoc hardware scenario probe",
        domain="voice",
        profiles={profile: ProfileSpec(profile, implementation, CostBounds(300, 0), _requires(profile))},
        metrics=tuple(metrics),
        assertions=(AssertionSpec("audio_reached_the_device", "audio.played_ms", Comparator.GE, 1,
                                  blocking=True),))


def _requires(profile: ProfileName):
    from jarvis.testlab.profiles import Capability

    devices = frozenset({Capability.AUDIO_INPUT_DEVICE, Capability.AUDIO_OUTPUT_DEVICE})
    return devices | ({Capability.HUMAN_PRESENCE} if profile is ProfileName.HARDWARE_GUIDED else frozenset())


def build_context(tmp_path: Path, spec: DiagnosticSpec, profile: ProfileName, *, parameters=None,
                  scenario=None, allow_audio: bool = False, budget_s: float = RUN_BUDGET_S,
                  settings: dict | None = None) -> tuple[RunContext, FilesystemTestRunStore]:
    parameters = resolve_parameters(spec.parameters, dict(parameters or {}))
    store = FilesystemTestRunStore(tmp_path / "store", limits=ArtifactWriteLimits(allow_audio=allow_audio))
    store.create_run(TestRun(run_id=RUN_ID, diagnostic_id=spec.diagnostic_id,
                             diagnostic_version=spec.version, profile=profile, status=RunStatus.QUEUED,
                             created_at=T0, code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                             diagnostic_fingerprint=spec.fingerprint(), parameters=parameters,
                             environment=ENVIRONMENT))
    scratch = tmp_path / "scratch"
    runtime_dir, data_root = scratch / "runtime", scratch / "data"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    if settings is not None:
        (runtime_dir / "control-center-settings.json").write_text(json.dumps(settings), encoding="utf-8")
    context = RunContext(run_id=RUN_ID, diagnostic=spec, profile=profile, parameters=parameters,
                         overrides={}, scenario=scenario, runtime_dir=runtime_dir, data_root=data_root,
                         artifacts=RunArtifacts(store, RUN_ID), cancelled=asyncio.Event(),
                         # `print`, not a sink: pytest captures it and shows it only when the
                         # test fails, which is exactly when the run log is worth reading.
                         deadline=asyncio.get_running_loop().time() + budget_s, log=print)
    return context, store


def artifact(context: RunContext, store: FilesystemTestRunStore, path: str) -> dict:
    """One committed artifact, after the supervisor's half of the commit.

    `read_artifact` serves only what the RECORD references (Slice 02), so a test that
    reads a runner's evidence back must reference it first, exactly as the supervisor does.
    """
    from jarvis.testlab.runs import complete_run, transition_run

    stored = store.get_run(RUN_ID)
    if stored.status is RunStatus.QUEUED:
        running = transition_run(stored, RunStatus.RUNNING, at=T0)
        store.update_run(running, expected=stored)
        store.update_run(complete_run(running, at=T0, assertion_results=(), metrics={}, score=None,
                                      artifacts=tuple(context.committed)), expected=running)
    return json.loads(store.read_artifact(RUN_ID, path).decode("utf-8"))


def committed(context: RunContext) -> list[str]:
    return [ref.path for ref in context.committed]


def verdict_of(spec: DiagnosticSpec, metrics) -> str:
    """The verdict the SUPERVISOR would derive from these metrics, by the same code."""
    index = spec.metric_index
    return assertions_verdict(tuple(evaluate_assertion(item, index[item.metric], metrics.get(item.metric))
                                    for item in spec.assertions)).value


# ------------------------------------------------------------ hardware:auto

async def test_the_room_echo_never_confirms_a_barge_in(tmp_path, monkeypatch):
    """The decisive negative: the production canceller, on real samples, in a quiet room."""
    fake = install(monkeypatch, FakeSoundDevice(room=FakeRoom(coupling=0.25)))
    context, store = build_context(tmp_path, self_echo_spec(), ProfileName.HARDWARE_AUTO, parameters=FAST)
    outcome = await SelfEchoHardwareRunner().run(context)
    assert outcome.metrics["barge_in.false_confirmed_count"] == 0
    assert outcome.metrics["barge_in.rejected_count"] >= 1, "the stack must DECIDE, not stay silent"
    assert outcome.metrics["output.played_ms"] > 0 and outcome.metrics["output.completed"] is True
    # Non-vacuous: the room really did carry Jarvis's output back into the capture path.
    assert fake.room.played and fake.room.captured
    assert verdict_of(context.diagnostic, outcome.metrics) == "passed"


async def test_a_real_voice_in_the_room_is_confirmed_as_a_barge_in(tmp_path, monkeypatch):
    """The matching positive: a loud uncorrelated voice must get through the same gate.

    Without this the negative test above would be satisfied by a stack that is simply
    deaf, which is the failure mode an acoustic diagnostic exists to catch.

    The voice starts WHEN the onset is raised, not before. A loud sound that was there
    from the first frame is this room's noise floor as far as the production near-end
    detector is concerned, and it is right about that — a barge-in is a change.
    """
    room = FakeRoom(coupling=0.25)
    install(monkeypatch, FakeSoundDevice(room=room))

    class SomebodySpeaks(SelfEchoHardwareRunner):
        async def raise_onset(self, context, stack) -> bool:
            room.near_end = speech_like()
            await wait_until_confirmed(stack.audio)
            # RETURN it: the seam reports whether an onset was actually raised, and a
            # `None` here reads as "declined", so the run raised nothing at all and then
            # reported that it could not measure. It passed anyway for a while, because the
            # capture's own near-end signal was reaching the bridge and producing a local
            # barge-in — the right answer for the wrong reason, which stopped being true
            # the moment the room got a realistic noise floor.
            return await super().raise_onset(context, stack)

    context, store = build_context(tmp_path, self_echo_spec(), ProfileName.HARDWARE_AUTO, parameters=FAST)
    outcome = await SomebodySpeaks().run(context)
    assert outcome.metrics["barge_in.false_confirmed_count"] >= 1
    assert verdict_of(context.diagnostic, outcome.metrics) == "failed"


async def test_a_hardware_run_records_what_it_exercised(tmp_path, monkeypatch):
    install(monkeypatch, FakeSoundDevice(room=FakeRoom()))
    context, store = build_context(tmp_path, self_echo_spec(), ProfileName.HARDWARE_AUTO,
                               parameters={**FAST, "device.input": "3", "device.output": "4"})
    await SelfEchoHardwareRunner().run(context)
    metadata = artifact(context, store, METADATA_ARTIFACT)
    assert metadata["profile"] == "hardware:auto" and metadata["device_opened"] is True
    assert metadata["input_device"] == "3" and metadata["output_device"] == "4"
    assert metadata["duplex_engaged"] is True and metadata["echo_source"] == "room"
    # The artifact paths stay far inside the 171-character budget the store leaves.
    assert all(len(path) <= 171 for path in committed(context))
    assert "trace.jsonl" in committed(context)


async def test_the_declared_device_wins_over_the_configured_one(tmp_path, monkeypatch):
    """Declared parameter, else the workstation's configured device, else PortAudio's default."""
    fake = install(monkeypatch, FakeSoundDevice(room=FakeRoom()))
    context, store = build_context(tmp_path, self_echo_spec(), ProfileName.HARDWARE_AUTO, parameters=FAST,
                               settings={"audio_input_device": "7", "audio_output_device": ""})
    await SelfEchoHardwareRunner().run(context)
    assert ("input", 7) in fake.checked and ("output", None) in fake.checked
    metadata = artifact(context, store, METADATA_ARTIFACT)
    assert metadata["input_device"] == "7" and metadata["output_device"] is None


# ------------------------------------------------- device failures and release

@pytest.mark.parametrize("kwargs,code", [
    ({"input_error": AudioDiagnosticError("audio_input_unavailable", "busy")}, DEVICE_INPUT_UNAVAILABLE),
    ({"output_error": AudioDiagnosticError("audio_output_unavailable", "busy")}, DEVICE_OUTPUT_UNAVAILABLE),
])
async def test_a_device_the_preflight_refuses_is_inconclusive_and_opens_nothing(tmp_path, monkeypatch,
                                                                                kwargs, code):
    fake = install(monkeypatch, FakeSoundDevice(room=FakeRoom(), **kwargs))
    context, store = build_context(tmp_path, self_echo_spec(), ProfileName.HARDWARE_AUTO, parameters=FAST)
    with pytest.raises(DeviceUnavailable) as caught:
        await SelfEchoHardwareRunner().run(context)
    assert caught.value.code == code
    assert isinstance(caught.value, MeasurementUnavailable), "a device failure is never a crash"
    assert fake.streams == [], "the pre-flight must refuse before anything is opened"


async def test_a_device_that_fails_at_open_time_is_inconclusive_not_a_crash(tmp_path, monkeypatch):
    """The pre-flight passed and the device went away anyway: still "could not measure"."""
    install(monkeypatch, FakeSoundDevice(room=FakeRoom(), open_error=OSError("device disappeared")))
    context, store = build_context(tmp_path, self_echo_spec(), ProfileName.HARDWARE_AUTO, parameters=FAST,
                               budget_s=20.0)
    with pytest.raises(MeasurementUnavailable) as caught:
        await SelfEchoHardwareRunner().run(context)
    assert caught.value.code == DEVICE_OPEN_FAILED


async def test_the_device_is_released_when_the_run_is_cancelled(tmp_path, monkeypatch):
    fake = install(monkeypatch, FakeSoundDevice(room=FakeRoom()))

    class CancellingRunner(SelfEchoHardwareRunner):
        async def run(self, context):
            context.cancelled.set()
            return await super().run(context)

    context, store = build_context(tmp_path, self_echo_spec(), ProfileName.HARDWARE_AUTO, parameters=FAST)
    with pytest.raises(RunCancelled):
        await CancellingRunner().run(context)
    assert fake.open_streams == [], "a cancelled run must not keep the microphone"


async def test_the_device_is_released_when_the_run_outlives_its_budget(tmp_path, monkeypatch):
    """A deadline in the past: every bounded wait gives up at once, and nothing stays open."""
    fake = install(monkeypatch, FakeSoundDevice(room=FakeRoom()))
    context, store = build_context(tmp_path, self_echo_spec(), ProfileName.HARDWARE_AUTO, parameters=FAST,
                               budget_s=0.0)
    with pytest.raises(MeasurementUnavailable):
        await SelfEchoHardwareRunner().run(context)
    assert fake.open_streams == []


async def test_the_device_is_released_when_the_runner_crashes(tmp_path, monkeypatch):
    fake = install(monkeypatch, FakeSoundDevice(room=FakeRoom()))

    class BrokenRunner(SelfEchoHardwareRunner):
        async def run(self, context):
            from jarvis.testlab.hardware.runners import hardware_voice_stack, open_device_session

            async with hardware_voice_stack(context) as (stack, _journal, _core, _build, _selection):
                await open_device_session(context, stack)
                raise ZeroDivisionError("a defect of ours, mid-run")

    context, store = build_context(tmp_path, self_echo_spec(), ProfileName.HARDWARE_AUTO, parameters=FAST)
    with pytest.raises(ZeroDivisionError):
        await BrokenRunner().run(context)
    assert fake.open_streams == [], "even our own defect must give the devices back"


# --------------------------------------------------------- hardware:guided

class ScriptedHuman:
    """A `GuidedPrompter` that answers on cue and then talks OVER Jarvis, like a person.

    Written here rather than reusing `HeadlessPrompter` because the interesting guided
    cases are about what the MICROPHONE hears during a step, and about WHEN. The voice
    starts once the far end exists — after Jarvis has actually begun playing — which is
    what a person does and the only case the production near-end detector can call: a
    sound that predates the far end is that room's noise floor, and the detector is right
    about that. The runner documents the same limit, so a test that started the voice
    first would be exercising a case the product cannot see.
    """

    def __init__(self, room: FakeRoom, *, speaks_on: tuple[str, ...] = (), delays: dict | None = None,
                 refuses: tuple[str, ...] = (), silent_on: tuple[str, ...] = (),
                 speaks_immediately: bool = False, voice_peak: float = 0.95) -> None:
        #: Start talking before Jarvis does, instead of over him. A real case, and the one
        #: the detector cannot call: a sound that predates the far end is this room's noise
        #: floor. The room is still audibly not empty, which the silent-window baselines see.
        self.speaks_immediately = speaks_immediately
        #: How loudly. Quiet enough and the person is audibly in the room without beating
        #: this room's echo, which is "they spoke and were not heard" — a measurement.
        self.voice_peak = voice_peak
        self.room = room
        self.speaks_on = frozenset(speaks_on)
        self.delays = dict(delays or {})
        self.refuses = frozenset(refuses)
        self.silent_on = frozenset(silent_on)
        self.shown: list[GuidedPrompt] = []
        self.voices: list[asyncio.Future] = []

    async def present(self, prompt: GuidedPrompt) -> PromptReply:
        self.shown.append(prompt)
        self.room.near_end = b""
        if prompt.prompt_id in self.speaks_on:
            if self.speaks_immediately:
                self.room.near_end = speech_like(peak=self.voice_peak)
            else:
                self.voices.append(asyncio.ensure_future(self._speak_while_jarvis_does()))
        delay = self.delays.get(prompt.prompt_id, 0.0)
        if delay:
            await asyncio.sleep(delay)
        if prompt.prompt_id in self.silent_on:
            await asyncio.Event().wait()
        return PromptReply(refused=prompt.prompt_id in self.refuses,
                           acknowledged=prompt.prompt_id not in self.refuses)

    async def _speak_while_jarvis_does(self) -> None:
        """Wait for the far end, then talk. The same shape as the `hardware:auto` positive case."""
        played = len(self.room.played)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 30.0
        # Two blocks, not one: the far end has to be unambiguous before the voice starts,
        # or the detector is entitled to read it as this room s floor.
        while len(self.room.played) < played + 2 and loop.time() < deadline:
            await asyncio.sleep(0.005)
        self.room.near_end = speech_like(peak=self.voice_peak)


def guided_context(tmp_path, *, blocking: bool = False, **options):
    """A guided run context. Non-blocking by default: most tests are about the FLOW, and the
    declaration that turns a zero into a verdict has its own test."""
    return build_context(tmp_path, guided_spec(blocking=blocking), ProfileName.HARDWARE_GUIDED,
                         parameters=options.pop("parameters", FAST), **options)


async def test_a_guided_run_addresses_the_human_at_every_step_and_records_each_one(tmp_path, monkeypatch):
    room = FakeRoom(coupling=0.25)
    install(monkeypatch, FakeSoundDevice(room=room))
    human = ScriptedHuman(room, speaks_on=(PROMPT_INTERRUPT,))
    context, store = guided_context(tmp_path)
    outcome = await SelfEchoGuidedRunner(prompter=human).run(context)

    assert [prompt.prompt_id for prompt in human.shown] == [PROMPT_SILENCE, PROMPT_INTERRUPT, PROMPT_DONE]
    assert [prompt.action.value for prompt in human.shown] == ["remain_silent", "interrupt", "acknowledge"]
    assert all(prompt.deadline_s > 0 and prompt.text for prompt in human.shown)
    assert human.shown[1].phrase, "an interrupt step must tell the human what to say"

    transcript = artifact(context, store, TRANSCRIPT_ARTIFACT)
    assert transcript["schema"] == TRANSCRIPT_SCHEMA and transcript["prompt_count"] == 3
    records = {record["prompt_id"]: record for record in transcript["records"]}
    for record in records.values():
        assert record["shown_at"] > 0 and record["acknowledged_at"] >= record["shown_at"]
        assert record["response_ms"] is not None and record["outcome"] == "acknowledged"
    assert records[PROMPT_SILENCE]["observed_voice"] is False
    assert records[PROMPT_INTERRUPT]["observed_voice"] is True
    assert records[PROMPT_INTERRUPT]["followed"] is True

    # The two claims a guided run exists to make, and they are counted separately.
    assert outcome.metrics["barge_in.false_confirmed_count"] == 0
    assert outcome.metrics[TRUE_CONFIRMED_METRIC] >= 1
    assert outcome.metrics["guided.prompt_count"] == 3
    assert outcome.metrics["guided.late_prompt_count"] == 0


async def test_a_prompt_nobody_answers_is_inconclusive_and_releases_the_device(tmp_path, monkeypatch):
    """Nobody is in the room. That is "we could not measure", and the device goes back."""
    monkeypatch.setattr("jarvis.testlab.hardware.prompts.LATE_GRACE_S", 0.1)
    fake = install(monkeypatch, FakeSoundDevice(room=FakeRoom()))
    spec = scenario_spec(ProfileName.HARDWARE_GUIDED, "testlab.scenario.hardware_guided")
    scenario = hardware_scenario(("human.silence", {"at_ms": 0, "prompt_id": "be-quiet",
                                                    "deadline_ms": 100}))
    context, store = build_context(tmp_path, spec, ProfileName.HARDWARE_GUIDED, scenario=scenario)
    with pytest.raises(GuidedPromptUnavailable) as caught:
        await GuidedScenarioRunner(prompter=HeadlessPrompter(default=None)).run(context)
    assert caught.value.code == PROMPT_TIMED_OUT
    assert isinstance(caught.value, MeasurementUnavailable), "an absent human is never a product failure"
    assert fake.open_streams == []
    # The evidence of the step that stopped the run is kept.
    record = artifact(context, store, TRANSCRIPT_ARTIFACT)["records"][0]
    assert record["outcome"] == "timed_out" and record["acknowledged_at"] is None


async def test_a_human_who_refuses_is_inconclusive(tmp_path, monkeypatch):
    room = FakeRoom()
    install(monkeypatch, FakeSoundDevice(room=room))
    context, store = guided_context(tmp_path)
    with pytest.raises(GuidedPromptUnavailable) as caught:
        await SelfEchoGuidedRunner(prompter=ScriptedHuman(room, refuses=(PROMPT_SILENCE,))).run(context)
    assert caught.value.code == PROMPT_REFUSED
    assert artifact(context, store, TRANSCRIPT_ARTIFACT)["records"][0]["outcome"] == "refused"


async def test_a_late_acknowledgement_on_a_tolerant_step_is_evidence_and_the_run_continues(tmp_path,
                                                                                           monkeypatch):
    """The deadline is declared per step, so a late answer is measured, not guessed."""
    install(monkeypatch, FakeSoundDevice(room=FakeRoom()))
    spec = scenario_spec(ProfileName.HARDWARE_GUIDED, "testlab.scenario.hardware_guided")
    scenario = hardware_scenario(
        ("human.acknowledge", {"at_ms": 0, "prompt_id": "done", "deadline_ms": 100}))
    context, store = build_context(tmp_path, spec, ProfileName.HARDWARE_GUIDED, scenario=scenario)
    outcome = await GuidedScenarioRunner(prompter=HeadlessPrompter(delay=0.35)).run(context)
    assert outcome.metrics["guided.prompt_count"] == 1
    record = artifact(context, store, TRANSCRIPT_ARTIFACT)["records"][0]
    assert record["outcome"] == "late" and record["response_ms"] >= 300
    assert record["acknowledged_at"] - record["shown_at"] >= 300


async def test_a_late_acknowledgement_on_the_interrupt_step_is_inconclusive(tmp_path, monkeypatch):
    """`interrupt` is timing-critical by declaration: a late answer means we did not measure it."""
    install(monkeypatch, FakeSoundDevice(room=FakeRoom()))
    spec = scenario_spec(ProfileName.HARDWARE_GUIDED, "testlab.scenario.hardware_guided")
    scenario = hardware_scenario(
        ("human.interrupt", {"at_ms": 0, "prompt_id": "cut-in", "text": "jarvis arrete toi",
                             "deadline_ms": 100}))
    context, store = build_context(tmp_path, spec, ProfileName.HARDWARE_GUIDED, scenario=scenario)
    with pytest.raises(GuidedPromptUnavailable) as caught:
        await GuidedScenarioRunner(prompter=HeadlessPrompter(delay=0.35)).run(context)
    assert caught.value.code == PROMPT_LATE
    assert artifact(context, store, TRANSCRIPT_ARTIFACT)["records"][0]["outcome"] == "late"


async def test_a_human_who_speaks_during_the_silent_step_voids_the_measurement(tmp_path, monkeypatch):
    """The human did the wrong thing. It is evidence, and THIS diagnostic says it invalidates.

    They start talking WHILE Jarvis is speaking, which is what breaking the silence looks
    like and the only case the production detector can call. A voice that was already
    there before the run began is that room's noise floor; the runner catches that one
    with its baseline measurement, which `test_a_noisy_room_cannot_support_the_silent_claim`
    covers.

    Repeated, because some attempts end in the anti-vacuity refusal instead and that is a
    property of the room rather than of this rule. Every attempt that DID reach the
    situation must void the claim, and at least one must have reached it.
    """
    rooms: list[FakeRoom] = []

    def build(index):
        room = FakeRoom(coupling=0.25)
        rooms.append(room)
        install(monkeypatch, FakeSoundDevice(room=room))
        human = ScriptedHuman(room, speaks_on=(PROMPT_SILENCE, PROMPT_INTERRUPT))
        context, store = guided_context(tmp_path / f"run{index}")
        return context, store, SelfEchoGuidedRunner(prompter=human).run(context)

    results, _skipped = await guided_attempts(build)
    for kind, value, context, store in results:
        assert kind == "refused", "a human who broke the silence must never reach a verdict"
        assert value.code == GUIDED_STEP_NOT_FOLLOWED
        records = {item["prompt_id"]: item
                   for item in artifact(context, store, TRANSCRIPT_ARTIFACT)["records"]}
        assert records[PROMPT_SILENCE]["observed_voice"] is True
        assert records[PROMPT_SILENCE]["followed"] is False
        # The SAME observation on the interrupt step is not a problem: it is the measurement.
        if PROMPT_INTERRUPT in records:
            assert records[PROMPT_INTERRUPT]["followed"] is True


async def test_a_presenter_that_breaks_is_inconclusive_not_a_crash(tmp_path, monkeypatch):
    install(monkeypatch, FakeSoundDevice(room=FakeRoom()))
    context, store = guided_context(tmp_path)
    prompter = HeadlessPrompter(raises=(PROMPT_SILENCE,))
    with pytest.raises(GuidedPromptUnavailable) as caught:
        await SelfEchoGuidedRunner(prompter=prompter).run(context)
    assert caught.value.code == PROMPTER_FAILED


# ------------------------------------------------ the generic scenario runners

def hardware_scenario(*steps) -> Scenario:
    return Scenario("voice.hardware_probe", tuple(ScenarioStep(name, args) for name, args in steps))


async def test_audio_inject_on_a_hardware_profile_plays_through_the_output_device(tmp_path, monkeypatch):
    """Same primitive, the one meaning this profile can give it: the room, not the capture queue."""
    fake = install(monkeypatch, FakeSoundDevice(room=FakeRoom()))
    spec = scenario_spec(ProfileName.HARDWARE_AUTO, "testlab.scenario.hardware_auto")
    scenario = hardware_scenario(
        ("audio.inject", {"at_ms": 0, "audio_ref": "reference-tone-1s.wav"}),
        ("control.checkpoint", {"at_ms": 0, "checkpoint_id": "played"}))
    context, store = build_context(tmp_path, spec, ProfileName.HARDWARE_AUTO, scenario=scenario)
    outcome = await HardwareScenarioRunner().run(context)
    assert outcome.metrics["scenario.steps_performed"] == 2
    assert outcome.metrics["audio.played_ms"] > 0 and outcome.metrics["audio.captured_ms"] > 0
    assert fake.room.played, "the fixture must reach the real output device"


async def test_a_guided_scenario_performs_every_human_primitive(tmp_path, monkeypatch):
    room = FakeRoom()
    install(monkeypatch, FakeSoundDevice(room=room))
    spec = scenario_spec(ProfileName.HARDWARE_GUIDED, "testlab.scenario.hardware_guided")
    scenario = hardware_scenario(
        ("human.silence", {"at_ms": 0, "prompt_id": "be-quiet"}),
        ("audio.inject", {"at_ms": 0, "audio_ref": "reference-tone-1s.wav"}),
        ("human.speak", {"at_ms": 0, "prompt_id": "say-it", "text": "jarvis quelle heure est-il"}),
        ("human.interrupt", {"at_ms": 0, "prompt_id": "cut-in", "text": "jarvis arrete toi"}),
        ("human.acknowledge", {"at_ms": 0, "prompt_id": "done", "deadline_ms": 5000}))
    context, store = build_context(tmp_path, spec, ProfileName.HARDWARE_GUIDED, scenario=scenario)
    prompter = HeadlessPrompter()
    outcome = await GuidedScenarioRunner(prompter=prompter).run(context)
    assert [prompt.prompt_id for prompt in prompter.shown] == ["be-quiet", "say-it", "cut-in", "done"]
    assert [prompt.action.value for prompt in prompter.shown] == [
        "remain_silent", "say_phrase", "interrupt", "acknowledge"]
    assert prompter.shown[1].phrase == "jarvis quelle heure est-il"
    assert prompter.shown[3].deadline_s == 5.0
    assert outcome.metrics["guided.prompt_count"] == 4
    assert outcome.metrics["guided.unfollowed_count"] == 0
    assert TRANSCRIPT_ARTIFACT in committed(context)


async def test_the_generic_runner_refuses_a_diagnostic_it_cannot_measure(tmp_path, monkeypatch):
    install(monkeypatch, FakeSoundDevice(room=FakeRoom()))
    spec = DiagnosticSpec(
        diagnostic_id="voice.hardware_probe", version=1, title="Probe", domain="voice",
        profiles={ProfileName.HARDWARE_AUTO: ProfileSpec(
            ProfileName.HARDWARE_AUTO, "testlab.scenario.hardware_auto", CostBounds(60, 0),
            _requires(ProfileName.HARDWARE_AUTO))},
        metrics=(MetricSpec("echo.coupling_measured_db", MetricUnit.DB, MetricDirection.NEUTRAL),),
        assertions=(AssertionSpec("coupling_measured", "echo.coupling_measured_db", Comparator.LE, 0,
                                  blocking=True),))
    context, store = build_context(tmp_path, spec, ProfileName.HARDWARE_AUTO,
                               scenario=hardware_scenario(("time.wait", {"at_ms": 0})))
    with pytest.raises(MeasurementUnavailable) as caught:
        await HardwareScenarioRunner().run(context)
    assert "cannot measure" in caught.value.detail


# -------------------------------------------------------------- audio clips

async def test_an_audio_clip_of_the_room_is_stored_only_when_it_was_allowed(tmp_path, monkeypatch):
    """A hardware clip is a recording of the user's room, so all three Slice 08 gates hold."""
    from jarvis.testlab.hardware.runners import CLIP_ARTIFACT, store_clip

    install(monkeypatch, FakeSoundDevice(room=FakeRoom()))
    refused, _refused_store = build_context(tmp_path / "off", self_echo_spec(), ProfileName.HARDWARE_AUTO,
                               parameters=FAST, allow_audio=False)
    allowed, _allowed_store = build_context(tmp_path / "on", self_echo_spec(), ProfileName.HARDWARE_AUTO,
                               parameters=FAST, allow_audio=True)
    assert store_clip(refused, b"\x00\x01" * 100) is False
    assert store_clip(allowed, b"\x00\x01" * 100) is True
    assert [ref.kind for ref in allowed.committed] == [ArtifactKind.AUDIO_CLIP]
    assert committed(allowed) == [CLIP_ARTIFACT] and len(CLIP_ARTIFACT) <= 171


# --------------------------------------------- anti-vacuity of the evidence

async def test_a_run_whose_microphone_delivered_nothing_is_inconclusive(tmp_path, monkeypatch):
    """"No false barge-in" from a dead microphone is an empty run, not a passing one."""
    from jarvis.testlab.hardware.runners import check_device_evidence

    class Dead:
        captured_bytes = 0
        capture_signals: list[str] = []
        run_peak_dbfs = None

    context, store = build_context(tmp_path, self_echo_spec(), ProfileName.HARDWARE_AUTO, parameters=FAST)
    with pytest.raises(DeviceUnavailable) as caught:
        check_device_evidence(context, Dead(), played_ms=500)
    assert caught.value.code == DEVICE_NO_SIGNAL
    with pytest.raises(DeviceUnavailable) as caught:
        check_device_evidence(context, Dead(), played_ms=0)
    assert caught.value.code == DEVICE_NO_OUTPUT


async def test_the_prompt_outcome_vocabulary_is_closed():
    """Every way a prompt can end has a name; nothing silently falls through."""
    assert {item.value for item in PromptOutcome} == {
        "acknowledged", "late", "timed_out", "refused", "prompter_failed"}


async def wait_for_capture_blocks(room: FakeRoom, blocks: int, *, timeout: float = 5.0) -> None:
    """Let the simulated microphone deliver a few more blocks of whatever is in the room now."""
    loop = asyncio.get_running_loop()
    target = len(room.captured) + blocks
    deadline = loop.time() + timeout
    while len(room.captured) < target and loop.time() < deadline:
        await asyncio.sleep(0.01)


async def wait_until_confirmed(audio, *, timeout: float = 10.0) -> None:
    """Wait until the PRODUCT would act on the voice that is in the room now.

    The same predicate the runner uses, `DeviceAudio.heard_voice_since`, and for the same
    reasons. Not the `NEAR_END` signal: it is an EDGE that fires once and then goes quiet
    for the rest of the utterance, so a test waiting on it missed a voice the detector was
    reporting on every frame, 10 runs out of 10. Not the latch alone either: it can be left
    over from the echo, and waiting on it raised the stimulus before the voice had arrived.

    Not a sleep: how long the detector needs is its business, not the test's.
    """
    loop = asyncio.get_running_loop()
    mark = audio.mark()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if audio.heard_voice_since(mark):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"the capture never reported a voice this stack would act on: "
                         f"{audio.near_frames_since(mark)} near frames, "
                         f"latched={audio.near_end_confirmed}")


async def test_a_noisy_room_cannot_support_the_silent_claim(tmp_path, monkeypatch):
    """A voice that predates the far end is this room's floor: the BASELINE catches it.

    The other half of the pair above, and the reason the silent step is judged on two
    sources rather than one. Nothing here depends on a detector transition.
    """
    room = FakeRoom(coupling=0.25, near_end=speech_like())
    install(monkeypatch, FakeSoundDevice(room=room))
    context, store = guided_context(tmp_path)
    with pytest.raises(GuidedPromptUnavailable) as caught:
        await SelfEchoGuidedRunner(prompter=HeadlessPrompter()).run(context)
    assert caught.value.code == GUIDED_STEP_NOT_FOLLOWED
    record = artifact(context, store, TRANSCRIPT_ARTIFACT)["records"][0]
    assert record["prompt_id"] == PROMPT_SILENCE and record["followed"] is False


async def test_an_interrupt_nothing_confirmed_is_inconclusive_not_a_silent_pass(tmp_path, monkeypatch):
    """The human says they interrupted, the stack confirms nothing: the claim was NOT made.

    A guided run exists to prove a real voice gets through the echo gate. One that reads
    `passed` because no blocking assertion happened to cover the metric is exactly the
    failure the profile was built to prevent.
    """
    room = FakeRoom(coupling=0.25)
    install(monkeypatch, FakeSoundDevice(room=room))
    context, store = guided_context(tmp_path)
    # A human who acknowledges every step and never makes a sound.
    with pytest.raises(GuidedPromptUnavailable) as caught:
        await SelfEchoGuidedRunner(prompter=HeadlessPrompter()).run(context)
    assert caught.value.code == GUIDED_CLAIM_UNMEASURED
    assert isinstance(caught.value, MeasurementUnavailable)
    assert not room.near_end, "the room really was empty for the whole run"
    records = {item["prompt_id"]: item for item in artifact(context, store, TRANSCRIPT_ARTIFACT)["records"]}
    assert records[PROMPT_INTERRUPT]["outcome"] == "acknowledged"
    # The PROVENANCE of the decision is stored, so a reader can tell a person from an echo.
    assert records[PROMPT_INTERRUPT]["observed_voice"] is False
    assert records[PROMPT_INTERRUPT]["certain"] is False
    assert records[PROMPT_INTERRUPT]["room_after_dbfs"] <= records[PROMPT_INTERRUPT]["voice_floor_dbfs"]


async def test_a_declaration_that_blocks_on_the_positive_claim_reports_the_zero_instead(tmp_path,
                                                                                        monkeypatch):
    """Whether a zero is a VERDICT or a measurement failure is the declaration's call.

    Declare a blocking assertion on `barge_in.true_confirmed_count` and the runner reports
    the zero so the supervisor can FAIL the run on it. Its pair,
    `test_an_interrupt_nothing_confirmed_is_inconclusive_not_a_silent_pass`, holds the other
    end: with no such assertion the runner cannot express the verdict, so it says
    `inconclusive` rather than passing quietly.

    REPEATED, AND ASSERTED AS A DISTRIBUTION, because the situation cannot be dialled in.
    A person quiet enough that the gate never opens on them and a person loud enough to be
    certifiably in the room are separated by only a few dB — the two are the SAME
    microphone measurement — so at the margin an attempt sometimes lands on "they were
    heard" instead, and an attempt can also end in the anti-vacuity refusal. Lowering the
    voice does not fix it: at -40 dBFS, 19 dB under this room's echo, three suite runs in
    ten still had an attempt where the gate opened, and a person who predates or outlives
    the utterance is confirmed 16 times out of 16.

    So the test asserts the SHAPE instead of one outcome, which is stronger than the
    single-run version it replaces:

    * the person is certifiably in the room on EVERY attempt — the zero is a result, never
      a failure to observe;
    * the branch this test exists for must OCCUR at least once;
    * wherever the gate stayed shut, the declaration must turn the zero into `failed`;
    * and wherever it opened, the same declaration must return `passed`.

    The last one is what keeps this from being "accept both outcomes": a runner that failed
    every guided run, or one that passed every one, is caught by one of the two halves.
    """
    spec = guided_spec(blocking=True)
    assert any(item.metric == TRUE_CONFIRMED_METRIC and item.blocking for item in spec.assertions)

    def build(index):
        room = FakeRoom(coupling=0.25)
        install(monkeypatch, FakeSoundDevice(room=room))
        # A person who speaks too quietly to beat their own room's echo: audibly in the
        # room, so the claim IS measurable, but usually not loud enough for the gate to
        # open on them. "They spoke and were not heard" is the measurement, and the
        # declaration judges it.
        #
        # The level buys MARGIN, not certainty. This voice lands near -40 dBFS: 10 dB clear
        # of VOICE_FLOOR_DBFS (-50), so the person is always certifiably present, and about
        # 19 dB under this room's in-window echo (~-21 dBFS), which makes the gate staying
        # shut the common case rather than a guaranteed one. It is not guaranteed because
        # the near-end verdict accumulates over the window and the window's length moves
        # with the machine's scheduling; the assertions below are written for that.
        human = ScriptedHuman(room, speaks_on=(PROMPT_INTERRUPT,), voice_peak=0.01)
        context, store = build_context(tmp_path / f"run{index}", spec, ProfileName.HARDWARE_GUIDED,
                                       parameters=FAST)
        return context, store, SelfEchoGuidedRunner(prompter=human).run(context)

    results, _skipped = await guided_attempts(build)
    unheard: list[str] = []
    heard: list[str] = []
    for kind, value, context, store in results:
        assert kind == "outcome", (
            f"a measurable person must produce a verdict, not {getattr(value, 'code', value)}")
        # The premise, checked rather than assumed: this person WAS measurably in the room
        # on every attempt. That is what makes the zero a RESULT rather than a failure to
        # observe, and it is the part that must never drift.
        record = {item["prompt_id"]: item
                  for item in artifact(context, store, TRANSCRIPT_ARTIFACT)["records"]}[
                      PROMPT_INTERRUPT]
        assert record["certain"] is True, record
        assert record["room_after_dbfs"] > record["voice_floor_dbfs"], record
        verdict = verdict_of(spec, value.metrics)
        if value.metrics[TRUE_CONFIRMED_METRIC] == 0:
            unheard.append(verdict)
        else:
            heard.append(verdict)

    # THE assertion, and it is about the declaration rather than about the room: the branch
    # this test exists for must actually occur, and wherever it occurs the zero must come
    # back as `failed`.
    assert unheard, (
        "a person the gate never opened on did not occur in any of the "
        f"{len(results)} attempts, so the rule under test was never exercised; verdicts {heard}")
    assert all(item == "failed" for item in unheard), (
        f"the declaration must turn the zero into a verdict, got {unheard}")
    # And the other direction, on the attempts where the quiet voice did beat the echo: the
    # same declaration must PASS them. Asserting only the first half would be satisfied by a
    # runner that failed every guided run.
    assert all(item == "passed" for item in heard), (
        f"the same declaration must pass a person who WAS heard, got {heard}")


async def test_the_first_candidate_offset_is_measured_when_the_declaration_asks_for_it(tmp_path,
                                                                                       monkeypatch):
    """The 400 ms convergence gap is evidence, not an invisible constant."""
    install(monkeypatch, FakeSoundDevice(room=FakeRoom(coupling=0.25)))
    context, store = build_context(tmp_path, self_echo_spec(), ProfileName.HARDWARE_AUTO,
                                   parameters=FAST)
    outcome = await SelfEchoHardwareRunner().run(context)
    assert outcome.metrics[FIRST_ONSET_METRIC] >= FIRST_ONSET_BLOCK * 100
    del store


async def test_an_undeclared_metric_is_never_reported(tmp_path, monkeypatch):
    """The published v2 does not declare the offset; reporting it would fail the run.

    `check_run_against_spec` refuses a completed run carrying a metric its declaration
    never mentioned, which reads `crashed`. The runner offers, the declaration selects.
    """
    from dataclasses import replace

    install(monkeypatch, FakeSoundDevice(room=FakeRoom(coupling=0.25)))
    base = self_echo_spec()
    spec = replace(base, metrics=tuple(item for item in base.metrics
                                       if item.name != FIRST_ONSET_METRIC))
    context, store = build_context(tmp_path, spec, ProfileName.HARDWARE_AUTO, parameters=FAST)
    outcome = await SelfEchoHardwareRunner().run(context)
    assert FIRST_ONSET_METRIC not in outcome.metrics
    assert set(outcome.metrics) <= {item.name for item in spec.metrics}
    del store


async def test_a_microphone_that_streams_digital_silence_is_inconclusive(tmp_path, monkeypatch):
    """Counting bytes is not enough: a dead input delivers as many as a working one."""
    from jarvis.testlab.hardware.runners import check_device_evidence

    class Silent:
        captured_bytes = 48_000
        capture_signals: list[str] = []
        run_peak_dbfs = -90.3

    context, _store = build_context(tmp_path, self_echo_spec(), ProfileName.HARDWARE_AUTO,
                                    parameters=FAST)
    with pytest.raises(DeviceUnavailable) as caught:
        check_device_evidence(context, Silent(), played_ms=800)
    assert caught.value.code == DEVICE_NO_SIGNAL and "digital silence" in caught.value.detail


# ------------------------------------------------- at the DECLARED DEFAULTS

#: The seeds' own declared defaults, which is what HV-TL-HW-01 and any real caller will
#: use. `FAST` above exists so the flow tests stay quick; these exist because two defects
#: lived in the gap between 1 200 ms and 8 000 ms and no test anywhere covered it.
def declared_defaults(spec) -> dict:
    return {item.name: item.default for item in spec.parameters
            if item.name in ("output.duration_ms", "echo.candidate_count")}


async def test_hardware_auto_measures_at_its_declared_defaults(tmp_path, monkeypatch, capsys):
    """The seed must MEASURE at 8 000 ms, which is the duration a real caller will use.

    It asserts the diagnostic, not the acoustics. Whether a long utterance produces a false
    confirmation is the MEASUREMENT — and on this room it sometimes does, which is
    `Issues/self-barge-in-after-seconds-of-speech.md` and a question only hardware settles.
    Asserting zero here would pin a double's room model as if it were the product.

    What is pinned: the run completes at the default, plays the whole utterance, decides on
    every candidate it raises, honours the canceller's pre-roll, and reports a verdict
    derived from its metrics rather than from anything the runner decided.
    """
    room = FakeRoom(coupling=0.25)
    install(monkeypatch, FakeSoundDevice(room=room))
    spec = self_echo_spec()
    defaults = declared_defaults(spec)
    assert defaults["output.duration_ms"] >= 8000, "the default is what this test is for"
    context, store = build_context(tmp_path, spec, ProfileName.HARDWARE_AUTO, parameters=defaults,
                                   budget_s=300.0)
    outcome = await SelfEchoHardwareRunner().run(context)
    metrics = dict(outcome.metrics)
    with capsys.disabled():
        print(f"\nhardware:auto at declared defaults -> {metrics}")
    confirmed = metrics["barge_in.false_confirmed_count"]
    assert metrics[FIRST_ONSET_METRIC] >= FIRST_ONSET_BLOCK * 100, "the pre-roll was honoured"
    assert confirmed + metrics["barge_in.rejected_count"] >= 1, "the stack must DECIDE, not stay silent"
    if confirmed:
        # The finding, not a test failure. It reads `failed`, which is what a caller must see.
        assert verdict_of(spec, metrics) == "failed"
        assert metrics["output.played_ms"] > 0
    else:
        assert metrics["output.played_ms"] >= defaults["output.duration_ms"] - 200
        assert verdict_of(spec, metrics) == "passed"
    del store


async def test_an_empty_room_never_certifies_a_human_interrupt_at_the_defaults(tmp_path, monkeypatch):
    """The defect this pins: an EMPTY room reported "a real human voice got through".

    Deterministic from 2 500 ms of speech upward, because both gates were satisfied by
    Jarvis's own sound — the in-window microphone peak carries the echo at a voice's level,
    and the near-end detector raises on the canceller's residual over a long utterance. The
    claim now needs evidence Jarvis cannot produce, and an empty room has none of it.

    Two assertions, and the second is why this is not a widened test. The INVARIANT holds
    on every attempt: an empty room never reaches a verdict. And across the attempts the
    described branch must actually occur — the run must at least once refuse BECAUSE the
    claim was unmeasurable, not only because the stack happened to decide nothing.
    """
    spec = guided_spec(blocking=True)

    def build(index):
        room = FakeRoom(coupling=0.25)
        install(monkeypatch, FakeSoundDevice(room=room))
        context, store = build_context(tmp_path / f"run{index}", spec, ProfileName.HARDWARE_GUIDED,
                                       parameters=declared_defaults(spec), budget_s=300.0)
        return context, store, SelfEchoGuidedRunner(prompter=HeadlessPrompter()).run(context)

    results, _skipped = await guided_attempts(build)
    codes = []
    for kind, value, context, store in results:
        assert kind == "refused", "an empty room must never reach a verdict"
        codes.append(value.code)
        records = {item["prompt_id"]: item
                   for item in artifact(context, store, TRANSCRIPT_ARTIFACT)["records"]}
        interrupt = records.get(PROMPT_INTERRUPT)
        if interrupt is not None and interrupt.get("certain") is not None:
            assert interrupt["observed_voice"] is False
            assert interrupt["certain"] is False
            assert interrupt["room_after_dbfs"] <= interrupt["voice_floor_dbfs"]
    assert GUIDED_CLAIM_UNMEASURED in codes or GUIDED_STEP_NOT_FOLLOWED in codes, codes


async def test_a_real_voice_is_measurable_at_the_declared_defaults(tmp_path, monkeypatch, capsys):
    """A compliant human must get a MEASUREMENT at the defaults, not a coin flip.

    This is the deliverable: HV-TL-HW-01 puts a person in front of the run once, and the
    report they sign has to distinguish "Jarvis is deaf to me" from harness noise. So the
    assertion is on the DISTRIBUTION over repeats, not on one run — and it asserts the
    claim was measured, never that a particular verdict came out, because the verdict is
    the measurement.

    It used to early-return on two refusal codes and otherwise accept any verdict, which
    made three genuine "a real human voice did not get through" failures green.
    """
    spec = guided_spec(blocking=True)
    defaults = declared_defaults(spec)
    measured: list[int] = []
    refused: list[str] = []
    for index in range(DEFAULTS_REPEATS):
        room = FakeRoom(coupling=0.25)
        install(monkeypatch, FakeSoundDevice(room=room))
        context, store = build_context(tmp_path / f"run{index}", spec, ProfileName.HARDWARE_GUIDED,
                                       parameters=defaults, budget_s=300.0)
        human = ScriptedHuman(room, speaks_on=(PROMPT_INTERRUPT,))
        try:
            outcome = await SelfEchoGuidedRunner(prompter=human).run(context)
        except MeasurementUnavailable as exc:
            refused.append(exc.code)
            continue
        assert TRUE_CONFIRMED_METRIC in outcome.metrics, "a measured run reports the claim"
        measured.append(int(outcome.metrics[TRUE_CONFIRMED_METRIC]))
        record = {item["prompt_id"]: item
                  for item in artifact(context, store, TRANSCRIPT_ARTIFACT)["records"]}[PROMPT_INTERRUPT]
        assert record["certain"] is True, "the person must be certified by evidence that cannot be Jarvis"
        del store
    with capsys.disabled():
        print(f"\nguided defaults x{DEFAULTS_REPEATS}: measured={measured} refused={refused}")
    # The distribution, asserted rather than described. A refusal is honest and the
    # operator retries; a measured run that did not hear the person is the defect this
    # whole Slice exists to make impossible.
    assert len(measured) >= DEFAULTS_REPEATS - 1, f"too many refusals: {refused}"
    assert all(count >= 1 for count in measured), (
        f"a compliant human was not heard in {measured.count(0)} of {len(measured)} measured runs")

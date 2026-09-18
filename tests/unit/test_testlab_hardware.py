"""Hardware device selection, the guided contract, the prompt channel and the gates.

Nothing here opens a device and nothing here needs a human: the device layer is
exercised through a `sounddevice` double, the guided layer through a scripted prompter,
and the supervisor gates through a fake launcher. That is deliberate — the whole point
of the Slice is that a run is refused, or reported honestly, BEFORE a microphone is
touched, so a test that had to touch one would be testing the wrong thing.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path

import pytest

from jarvis.runtime.audio_devices import AudioDiagnosticError
from jarvis.testlab.catalog import Catalog
from jarvis.testlab.devices import ContentionState
from jarvis.testlab.diagnostics import (
    AssertionSpec,
    Comparator,
    DiagnosticSpec,
    MetricDirection,
    MetricSpec,
    MetricUnit,
)
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.hardware.channel import (
    ACK_SCHEMA,
    PROMPT_ACK_FILE_NAME,
    PROMPT_FILE_NAME,
    PROMPT_SCHEMA,
    FilePrompter,
    PromptWatcher,
)
from jarvis.testlab.hardware.devices import (
    DEVICE_ID_INVALID,
    DEVICE_UNMAPPED,
    DEVICE_INPUT_UNAVAILABLE,
    DEVICE_OUTPUT_UNAVAILABLE,
    DIAGNOSTIC_FAILURES,
    AudioBackendProbe,
    DeviceSelection,
    DeviceUnavailable,
    as_device_failure,
    check_device_formats,
    hardware_contention_detector,
    read_configured_devices,
    resolve_device_selection,
)
from jarvis.testlab.hardware.prompts import (
    GUIDED_OPT_IN_ENV,
    LATE_GRACE_S,
    MAX_PROMPT_DEADLINE_S,
    MAX_PROMPTS_PER_RUN,
    PROMPT_LIMIT,
    PROMPT_REFUSED,
    PROMPT_TIMED_OUT,
    PROMPTER_FAILED,
    TRANSCRIPT_ARTIFACT,
    TRANSCRIPT_SCHEMA,
    GuidedAction,
    GuidedPrompt,
    GuidedPromptUnavailable,
    GuidedSession,
    HeadlessPrompter,
    PromptOutcome,
    PromptReply,
    guided_opt_in,
    prompt_for,
)
from jarvis.testlab.hardware.registry import HARDWARE_RUNNERS, hardware_implementations
from jarvis.testlab.jobs import FAILURE_DEVICE_CONTENTION, FAILURE_HUMAN_PRESENCE_MISSING
from jarvis.testlab.manifests import CatalogLock, DiagnosticManifest, lock_entry_for
from jarvis.testlab.outcomes import RunOutcomeClass, classify_run, outcome_of
from jarvis.testlab.primitives import (
    DEFAULT_PRIMITIVES,
    MAX_PROMPT_DEADLINE_MS,
    ALL_PROFILES,
    ArgRule,
    PrimitiveArgError,
    PrimitiveError,
    PRIMITIVE_PROFILE_UNSUPPORTED,
    check_scenario,
)
from jarvis.testlab.profiles import Capability, CostBounds, ProfileName, ProfileSpec, ResourceGrant
from jarvis.testlab.runners import MeasurementUnavailable, RunCancelled
from jarvis.testlab.runs import RunStatus, check_artifact_path
from jarvis.testlab.scenarios import Scenario, ScenarioStep
from jarvis.testlab.selftest import catalog_implementations
from jarvis.testlab.store import ArtifactWriteLimits
from jarvis.testlab.supervisor import RunRequest, RunSupervisor, SupervisorPolicy
from jarvis.testlab.validation import SIMPLE_NAME, TestLabError, scan_private
from tests.fakes.sounddevice_double import FakeSoundDevice, install
from tests.unit.test_testlab_supervisor import FakeLauncher, _clock, _code, _nonce

pytestmark = pytest.mark.asyncio


# ------------------------------------------------------------ device selection

async def test_a_declared_device_wins_over_the_configured_one_and_both_over_the_default():
    assert resolve_device_selection({}, (None, None)) == DeviceSelection(None, None,
                                                                         "system_default", "system_default")
    settings = resolve_device_selection({}, ("2", "Speakers"))
    assert settings == DeviceSelection(2, "Speakers", "settings", "settings")
    declared = resolve_device_selection({"device.input": "5", "device.output": 6}, ("2", "Speakers"))
    assert declared == DeviceSelection(5, 6, "parameter", "parameter")
    # An empty parameter is "no preference", which is what a manifest default carries.
    assert resolve_device_selection({"device.input": "", "device.output": ""},
                                    ("2", None)).input_device == 2


async def test_device_ids_are_normalised_exactly_as_the_product_normalises_them():
    from jarvis.runtime.audio_devices import normalize_device_id

    for value in ("3", 3, "Microphone (USB)", "", None):
        assert resolve_device_selection({"device.input": value}).input_device == normalize_device_id(value)


async def test_an_impossible_device_id_is_a_measurement_failure_not_a_crash():
    with pytest.raises(DeviceUnavailable) as caught:
        resolve_device_selection({"device.input": -1})
    assert caught.value.code == DEVICE_ID_INVALID
    assert isinstance(caught.value, MeasurementUnavailable)


async def test_the_configured_devices_come_from_the_runs_own_settings_copy(tmp_path):
    assert read_configured_devices(tmp_path) == (None, None), "an absent copy is the normal first-run state"
    (tmp_path / "control-center-settings.json").write_text(
        json.dumps({"audio_input_device": "4", "audio_output_device": "5"}), encoding="utf-8")
    assert read_configured_devices(tmp_path) == ("4", "5")
    (tmp_path / "control-center-settings.json").write_text("{not json", encoding="utf-8")
    assert read_configured_devices(tmp_path) == (None, None)


# --------------------------------------------------------- the failure mapping

async def test_every_product_device_error_maps_to_a_measurement_failure():
    """The Slice 08 carry-over: the detector cannot see a third application holding the mic."""
    for code in DIAGNOSTIC_FAILURES:
        failure = as_device_failure(AudioDiagnosticError(code, "message from the product"))
        assert isinstance(failure, MeasurementUnavailable), code
        assert failure.code == DIAGNOSTIC_FAILURES[code][0]
        assert code in failure.detail, "the product's own code stays in the sentence"
    assert outcome_of(RunStatus.ERRORED, "measurement_unavailable") is RunOutcomeClass.INCONCLUSIVE


async def test_the_three_codes_slice_08_carried_forward_are_all_covered():
    for code in ("audio_input_unavailable", "audio_input_no_signal", "audio_output_unavailable"):
        assert code in DIAGNOSTIC_FAILURES


@pytest.mark.parametrize("code", ["audio_something_new", "AUDIO WEIRD/code", "", "a\nb", "x" * 400])
async def test_an_uncatalogued_device_error_lands_on_one_stable_code(code):
    """A `RunFailure.code` is an identifier callers branch on, never a synthesised message."""
    failure = as_device_failure(AudioDiagnosticError(code, "a code we never saw"))
    assert isinstance(failure, MeasurementUnavailable)
    assert failure.code == DEVICE_UNMAPPED
    assert SIMPLE_NAME.fullmatch(failure.code), "the code stays a lowercase snake_case name"
    assert failure.detail == " ".join(failure.detail.split()), "the detail stays a single line"
    assert len(failure.detail) <= 400 and failure.detail.isprintable()


async def test_the_format_preflight_names_which_end_refused(monkeypatch):
    install(monkeypatch, FakeSoundDevice(input_error=AudioDiagnosticError("x", "y")))
    fake = FakeSoundDevice(input_error=RuntimeError("held by another application"))
    install(monkeypatch, fake)
    with pytest.raises(DeviceUnavailable) as caught:
        check_device_formats(DeviceSelection())
    assert caught.value.code == DEVICE_INPUT_UNAVAILABLE

    install(monkeypatch, FakeSoundDevice(output_error=RuntimeError("no such device")))
    with pytest.raises(DeviceUnavailable) as caught:
        check_device_formats(DeviceSelection())
    assert caught.value.code == DEVICE_OUTPUT_UNAVAILABLE


async def test_the_preflight_asks_about_the_selected_devices_and_opens_nothing(monkeypatch):
    fake = install(monkeypatch, FakeSoundDevice())
    check_device_formats(DeviceSelection(3, "Speakers", "parameter", "parameter"))
    assert fake.checked == [("input", 3), ("output", "Speakers")]
    assert fake.streams == []


# ------------------------------------------------------ the optional gate probe

async def test_a_transient_hardware_probe_failure_becomes_unknown_inside_the_probe(monkeypatch):
    """It must never reach the gate: an exception there reads `supervisor_fault`, our defect.

    A missing sound driver is not our defect, so the probe answers `unknown` — which
    refuses the run, fail-closed — and names what it could not reach.
    """
    install(monkeypatch, FakeSoundDevice(enumeration_error=RuntimeError("PortAudio blew up")))
    evidence = AudioBackendProbe().probe()
    assert evidence.state is ContentionState.UNKNOWN
    assert "audio backend" in evidence.detail and "audio_device_enumeration_failed" in evidence.detail


async def test_the_backend_probe_never_raises_whatever_the_backend_does():
    class Exploding:
        def list_devices(self):
            raise MemoryError("native")

    evidence = AudioBackendProbe(diagnostics=Exploding()).probe()
    assert evidence.state is ContentionState.UNKNOWN and "MemoryError" in evidence.detail


async def test_the_backend_probe_says_free_only_when_the_host_has_both_ends(monkeypatch):
    install(monkeypatch, FakeSoundDevice())
    assert AudioBackendProbe().probe().state is ContentionState.FREE
    install(monkeypatch, FakeSoundDevice(devices=[]))
    assert AudioBackendProbe().probe().state is ContentionState.UNKNOWN


async def test_the_hardware_detector_combines_both_probes_fail_closed(tmp_path, monkeypatch):
    install(monkeypatch, FakeSoundDevice())
    detector = hardware_contention_detector(tmp_path)
    report = detector.detect()
    assert {item.source for item in report.evidence} == {"live_voice_runtime", "audio_backend"}
    assert report.available is True, "an empty runtime root and a working backend is free"
    install(monkeypatch, FakeSoundDevice(devices=[]))
    assert hardware_contention_detector(tmp_path).detect().available is False


# ---------------------------------------------------------------- the prompts

@dataclass
class StubContext:
    """The little of `RunContext` a `GuidedSession` touches."""

    run_id: str = "tlr-20260918T000000000Z-0011223344556677"
    profile: ProfileName = ProfileName.HARDWARE_GUIDED
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    lines: list[str] = field(default_factory=list)
    artifacts: list[tuple[str, bytes]] = field(default_factory=list)

    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise RunCancelled()

    def log(self, message: str) -> None:
        self.lines.append(message)

    def put_artifact(self, path, *, kind, media_type, data):  # noqa: ANN001
        self.artifacts.append((path, data))
        return path


def session(prompter, **options) -> tuple[GuidedSession, StubContext]:
    context = StubContext()
    return GuidedSession(context=context, prompter=prompter, clock=lambda: 1_800_000_000.0, **options), context


async def test_a_prompt_declares_an_id_an_action_a_sentence_and_a_deadline():
    prompt = prompt_for(GuidedAction.INTERRUPT, "cut-in", phrase="jarvis arrete toi")
    assert prompt.prompt_id == "cut-in" and prompt.action is GuidedAction.INTERRUPT
    assert prompt.text and prompt.deadline_s > 0
    assert prompt.expects_voice is True and prompt.strict_timing is True
    assert prompt_for(GuidedAction.REMAIN_SILENT, "quiet").expects_voice is False
    assert prompt_for(GuidedAction.ACKNOWLEDGE, "done").strict_timing is False
    assert GuidedPrompt.from_dict(prompt.to_dict()) == prompt


@pytest.mark.parametrize("kwargs", [
    {"prompt_id": "not a safe id"}, {"prompt_id": "x" * 100}, {"text": ""}, {"text": "line\nline"},
    {"deadline_s": 0.0}, {"deadline_s": MAX_PROMPT_DEADLINE_S + 1}, {"expects_voice": "yes"},
])
async def test_a_malformed_prompt_is_refused(kwargs):
    base = {"prompt_id": "quiet", "action": GuidedAction.REMAIN_SILENT, "text": "Ne dites rien.",
            "deadline_s": 10.0}
    with pytest.raises(TestLabError):
        GuidedPrompt(**{**base, **kwargs})


async def test_a_spoken_action_must_carry_the_phrase_the_human_says():
    with pytest.raises(TestLabError):
        GuidedPrompt(prompt_id="say", action=GuidedAction.SAY_PHRASE, text="Dites la phrase.")


async def test_an_acknowledged_prompt_is_recorded_with_both_timestamps():
    guided, context = session(HeadlessPrompter())
    record = await guided.ask(prompt_for(GuidedAction.ACKNOWLEDGE, "done", deadline_s=5.0))
    assert record.outcome is PromptOutcome.ACKNOWLEDGED
    assert record.shown_at == 1_800_000_000_000 and record.acknowledged_at >= record.shown_at
    assert record.response_ms is not None and record.usable
    assert guided.prompt_count == 1 and guided.late_count == 0
    assert any("guided prompt done" in line for line in context.lines), "the expected path is logged too"


async def test_an_unanswered_prompt_is_could_not_measure_and_keeps_its_record():
    guided, _ = session(HeadlessPrompter(default=None), grace_s=0.05)
    with pytest.raises(GuidedPromptUnavailable) as caught:
        await guided.ask(prompt_for(GuidedAction.REMAIN_SILENT, "quiet", deadline_s=0.1))
    assert caught.value.code == PROMPT_TIMED_OUT and isinstance(caught.value, MeasurementUnavailable)
    assert guided.records[0].outcome is PromptOutcome.TIMED_OUT
    assert guided.records[0].acknowledged_at is None


async def test_a_refusal_is_a_legitimate_answer_and_never_a_product_failure():
    guided, _ = session(HeadlessPrompter(default=PromptReply(acknowledged=False, refused=True,
                                                             note="pas maintenant")))
    with pytest.raises(GuidedPromptUnavailable) as caught:
        await guided.ask(prompt_for(GuidedAction.ACKNOWLEDGE, "done", deadline_s=5.0))
    assert caught.value.code == PROMPT_REFUSED
    assert guided.records[0].outcome is PromptOutcome.REFUSED and guided.records[0].note == "pas maintenant"


async def test_a_late_answer_is_evidence_on_a_tolerant_step_and_void_on_a_timing_critical_one():
    tolerant, _ = session(HeadlessPrompter(delay=0.35), grace_s=5.0)
    record = await tolerant.ask(prompt_for(GuidedAction.ACKNOWLEDGE, "done", deadline_s=0.1))
    assert record.outcome is PromptOutcome.LATE and record.usable and tolerant.late_count == 1

    strict, _ = session(HeadlessPrompter(delay=0.35), grace_s=5.0)
    with pytest.raises(GuidedPromptUnavailable) as caught:
        await strict.ask(prompt_for(GuidedAction.INTERRUPT, "cut-in", phrase="stop", deadline_s=0.1))
    assert caught.value.code == "testlab_guided_prompt_late"
    assert strict.records[0].outcome is PromptOutcome.LATE


async def test_a_presenter_that_breaks_is_our_problem_but_still_only_could_not_measure():
    guided, _ = session(HeadlessPrompter(raises=("done",)))
    with pytest.raises(GuidedPromptUnavailable) as caught:
        await guided.ask(prompt_for(GuidedAction.ACKNOWLEDGE, "done", deadline_s=5.0))
    assert caught.value.code == PROMPTER_FAILED
    assert isinstance(caught.value, MeasurementUnavailable)


async def test_a_presenter_that_returns_nonsense_is_a_presenter_failure():
    class Nonsense:
        async def present(self, prompt):
            return "yes"

    guided, _ = session(Nonsense())
    with pytest.raises(GuidedPromptUnavailable) as caught:
        await guided.ask(prompt_for(GuidedAction.ACKNOWLEDGE, "done", deadline_s=5.0))
    assert caught.value.code == PROMPTER_FAILED


async def test_a_cancelled_run_stops_waiting_for_the_human_at_once():
    guided, context = session(HeadlessPrompter(default=None), grace_s=30.0)
    context.cancelled.set()
    with pytest.raises(RunCancelled):
        await guided.ask(prompt_for(GuidedAction.REMAIN_SILENT, "quiet", deadline_s=300.0))


async def test_a_cancellation_during_a_prompt_wins_over_the_deadline():
    prompter = HeadlessPrompter(default=None)
    guided, context = session(prompter, grace_s=30.0)

    async def cancel_soon():
        await asyncio.sleep(0.05)
        context.cancelled.set()

    task = asyncio.ensure_future(cancel_soon())
    with pytest.raises(RunCancelled):
        await guided.ask(prompt_for(GuidedAction.REMAIN_SILENT, "quiet", deadline_s=300.0))
    await task


async def test_what_the_microphone_heard_is_an_observation_the_diagnostic_reads():
    guided, _ = session(HeadlessPrompter())
    await guided.ask(prompt_for(GuidedAction.REMAIN_SILENT, "quiet", deadline_s=5.0))
    await guided.ask(prompt_for(GuidedAction.INTERRUPT, "cut-in", phrase="stop", deadline_s=5.0))
    guided.observe("quiet", voice=True, peak_dbfs=-3.21)
    guided.observe("cut-in", voice=True, peak_dbfs=-4.0)
    # The SAME observation: the silent step was not followed, the interrupt step was.
    assert guided.record_of("quiet").followed is False
    assert guided.record_of("cut-in").followed is True
    assert guided.unfollowed == ("quiet",)
    assert guided.record_of("quiet").observed_peak_dbfs == -3.2
    with pytest.raises(TestLabError):
        guided.observe("never-shown", voice=True)


async def test_the_transcript_is_a_bounded_report_of_every_step():
    guided, context = session(HeadlessPrompter())
    await guided.ask(prompt_for(GuidedAction.REMAIN_SILENT, "quiet", deadline_s=5.0))
    guided.observe("quiet", voice=False, peak_dbfs=-70.0)
    guided.commit()
    path, payload = context.artifacts[0]
    document = json.loads(payload.decode("utf-8"))
    assert path == TRANSCRIPT_ARTIFACT and check_artifact_path(path) is None
    assert len(path) <= 171
    assert document["schema"] == TRANSCRIPT_SCHEMA and document["schema_version"] == 1
    assert document["run_id"] == context.run_id and document["profile"] == "hardware:guided"
    assert document["prompt_count"] == 1 and document["unfollowed"] == []
    record = document["records"][0]
    assert record["prompt_id"] == "quiet" and record["action"] == "remain_silent"
    assert record["outcome"] == "acknowledged" and record["observed_peak_dbfs"] == -70.0
    # Nothing in the evidence is a private field name (no prompt CONTENT is a metric).
    scan_private(document, "guided_transcript")


async def test_a_run_may_not_address_the_human_without_end():
    guided, _ = session(HeadlessPrompter())
    for index in range(MAX_PROMPTS_PER_RUN):
        await guided.ask(prompt_for(GuidedAction.ACKNOWLEDGE, f"step-{index}", deadline_s=5.0))
    with pytest.raises(GuidedPromptUnavailable) as caught:
        await guided.ask(prompt_for(GuidedAction.ACKNOWLEDGE, "one-too-many", deadline_s=5.0))
    assert caught.value.code == PROMPT_LIMIT


async def test_an_empty_run_commits_no_transcript():
    guided, context = session(HeadlessPrompter())
    guided.commit()
    assert context.artifacts == []


# ------------------------------------------------------------- the file channel

async def test_a_worker_and_a_presenter_agree_through_two_files(tmp_path):
    prompter = FilePrompter(tmp_path, poll_interval_s=0.01)
    watcher = PromptWatcher(tmp_path)
    prompt = prompt_for(GuidedAction.SAY_PHRASE, "say-it", phrase="jarvis quelle heure est-il")

    async def answer() -> None:
        for _ in range(500):
            pending = watcher.pending()
            if pending is not None:
                shown, sequence = pending
                assert shown == prompt, "the presenter sees exactly what the worker published"
                watcher.acknowledge(shown.prompt_id, sequence, note="dit")
                return
            await asyncio.sleep(0.01)
        raise AssertionError("the prompt never appeared on disk")

    answering = asyncio.ensure_future(answer())
    reply = await prompter.present(prompt)
    await answering
    assert reply.acknowledged and reply.refused is False and reply.note == "dit"
    assert not (tmp_path / PROMPT_FILE_NAME).exists(), "a finished prompt is never left on disk"
    assert not (tmp_path / PROMPT_ACK_FILE_NAME).exists()


async def test_a_stale_acknowledgement_cannot_answer_the_next_prompt(tmp_path):
    prompter = FilePrompter(tmp_path, poll_interval_s=0.01)
    watcher = PromptWatcher(tmp_path)
    # An answer to sequence 1 left behind, then a new prompt: it must NOT be consumed.
    (tmp_path / PROMPT_ACK_FILE_NAME).write_text(json.dumps(
        {"schema": ACK_SCHEMA, "schema_version": 1, "sequence": 1, "prompt_id": "quiet",
         "acknowledged": True, "refused": False, "note": None}), encoding="utf-8")
    prompt = prompt_for(GuidedAction.REMAIN_SILENT, "quiet")
    presenting = asyncio.ensure_future(prompter.present(prompt))
    await asyncio.sleep(0.1)
    assert not presenting.done(), "a previous step's answer must not satisfy this one"
    pending = watcher.pending()
    assert pending is not None and pending[1] == 1
    # `present` cleared the stale file before publishing, so the sequence is the new one.
    watcher.acknowledge("quiet", pending[1])
    assert (await presenting).acknowledged


async def test_the_presenter_refusal_reaches_the_worker(tmp_path):
    prompter = FilePrompter(tmp_path, poll_interval_s=0.01)
    watcher = PromptWatcher(tmp_path)
    presenting = asyncio.ensure_future(prompter.present(prompt_for(GuidedAction.ACKNOWLEDGE, "done")))
    for _ in range(200):
        pending = watcher.pending()
        if pending is not None:
            watcher.acknowledge("done", pending[1], refused=True)
            break
        await asyncio.sleep(0.01)
    reply = await presenting
    assert reply.refused is True and reply.acknowledged is False


async def test_a_prompt_document_a_presenter_cannot_decode_is_shown_to_nobody(tmp_path):
    (tmp_path / PROMPT_FILE_NAME).write_text("{not json", encoding="utf-8")
    assert PromptWatcher(tmp_path).pending() is None
    (tmp_path / PROMPT_FILE_NAME).write_text(json.dumps(
        {"schema": PROMPT_SCHEMA, "schema_version": 1, "sequence": 1, "prompt": {"nope": 1}}),
        encoding="utf-8")
    assert PromptWatcher(tmp_path).pending() is None


async def test_the_channel_files_sit_beside_the_worker_protocol_files(tmp_path):
    prompter = FilePrompter(tmp_path)
    assert prompter.prompt_path == tmp_path / "prompt.json"
    assert prompter.ack_path == tmp_path / "prompt-ack.json"


# ------------------------------------------------------------- the vocabulary

GUIDED_PRIMITIVES = ("human.silence", "human.speak", "human.interrupt", "human.acknowledge")


async def test_the_human_family_exists_and_is_guided_only():
    for name in GUIDED_PRIMITIVES:
        spec = DEFAULT_PRIMITIVES.get(name)
        assert spec.profiles == frozenset({ProfileName.HARDWARE_GUIDED}), name
        assert spec.family.value == "human" and "prompt_id" in spec.required
    assert set(GUIDED_PRIMITIVES) <= DEFAULT_PRIMITIVES.for_profile(ProfileName.HARDWARE_GUIDED)
    assert not set(GUIDED_PRIMITIVES) & DEFAULT_PRIMITIVES.for_profile(ProfileName.HARDWARE_AUTO)


async def test_the_guided_steps_cover_the_four_actions_the_slice_requires():
    """Remain silent, say this phrase, interrupt at the cue, acknowledge."""
    assert {action.value for action in GuidedAction} == {
        "remain_silent", "say_phrase", "interrupt", "acknowledge"}


async def test_a_spoken_guided_step_must_declare_the_phrase():
    for name in ("human.speak", "human.interrupt"):
        assert "text" in DEFAULT_PRIMITIVES.get(name).required
        with pytest.raises(PrimitiveArgError) as caught:
            check_scenario(Scenario("voice.p", (ScenarioStep(name, {"at_ms": 0, "prompt_id": "a"}),)))
        assert caught.value.rule is ArgRule.FIELDS


async def test_a_guided_step_is_refused_on_every_other_profile():
    scenario = Scenario("voice.p", (ScenarioStep("human.silence", {"at_ms": 0, "prompt_id": "quiet"}),))
    check_scenario(scenario, profiles=(ProfileName.HARDWARE_GUIDED,))
    for profile in ALL_PROFILES - {ProfileName.HARDWARE_GUIDED}:
        with pytest.raises(PrimitiveError) as caught:
            check_scenario(scenario, profiles=(profile,))
        assert caught.value.code == PRIMITIVE_PROFILE_UNSUPPORTED


async def test_user_speech_is_no_longer_declared_for_the_guided_profile():
    """A step that asks a person for something needs an id, a deadline and an acknowledgement."""
    for name in ("user.speech", "user.interrupt"):
        assert ProfileName.HARDWARE_GUIDED not in DEFAULT_PRIMITIVES.get(name).profiles
        assert ProfileName.VIRTUAL in DEFAULT_PRIMITIVES.get(name).profiles


async def test_the_declared_deadline_bound_is_the_one_the_session_enforces():
    assert MAX_PROMPT_DEADLINE_MS == int(MAX_PROMPT_DEADLINE_S * 1000)
    step = ScenarioStep("human.acknowledge", {"at_ms": 0, "prompt_id": "done",
                                              "deadline_ms": MAX_PROMPT_DEADLINE_MS + 1})
    with pytest.raises(PrimitiveArgError):
        check_scenario(Scenario("voice.p", (step,)))


async def test_a_guided_scenario_carries_no_private_data():
    scenario = Scenario("voice.p", (
        ScenarioStep("human.silence", {"at_ms": 0, "prompt_id": "quiet", "text": "Ne dites rien."}),
        ScenarioStep("human.speak", {"at_ms": 10, "prompt_id": "say-it", "text": "jarvis bonjour"})))
    check_scenario(scenario, profiles=(ProfileName.HARDWARE_GUIDED,))
    scan_private(scenario.to_dict(), "scenario")


async def test_audio_inject_is_declared_for_both_hardware_profiles():
    """Same primitive, the one meaning each profile can give it (capture path, or the speaker)."""
    spec = DEFAULT_PRIMITIVES.get("audio.inject")
    assert {ProfileName.HARDWARE_AUTO, ProfileName.HARDWARE_GUIDED} <= spec.profiles


# ---------------------------------------------------------------- the registry

async def test_every_hardware_name_is_registered_for_its_own_profile():
    registry = catalog_implementations()
    for name, (profile, class_name) in HARDWARE_RUNNERS.items():
        entry = registry.resolve(name, profile)
        assert entry.factory is not None and entry.unavailable_reason is None
        runner = entry.factory()
        assert type(runner).__name__ == class_name and callable(getattr(runner, "run", None))


async def test_no_declared_implementation_name_is_reserved_any_more_except_the_fixture():
    registry = catalog_implementations()
    reserved = sorted(name for name, entry in registry.entries.items() if entry.factory is None)
    assert reserved == ["testlab.selftest.reserved"]


async def test_a_hardware_registration_cannot_take_another_profiles_name():
    from jarvis.testlab.implementations import default_implementations

    registry = default_implementations().registering(hardware_implementations())
    with pytest.raises(TestLabError):
        registry.registering(hardware_implementations())


# ------------------------------------------------------- the supervisor gates

GUIDED_CAPABILITIES = frozenset({Capability.AUDIO_INPUT_DEVICE, Capability.AUDIO_OUTPUT_DEVICE,
                                 Capability.HUMAN_PRESENCE})
GUIDED_GRANT = ResourceGrant(GUIDED_CAPABILITIES, max_cost_usd=0)
PRESENT = {GUIDED_OPT_IN_ENV: "1"}


def guided_spec() -> DiagnosticSpec:
    return DiagnosticSpec(
        diagnostic_id="voice.guided_probe", version=1, title="Guided probe fixture", domain="voice",
        profiles={ProfileName.HARDWARE_GUIDED: ProfileSpec(
            ProfileName.HARDWARE_GUIDED, "testlab.scenario.hardware_guided", CostBounds(60, 0),
            GUIDED_CAPABILITIES)},
        metrics=(MetricSpec("guided.prompt_count", MetricUnit.COUNT, MetricDirection.NEUTRAL),),
        assertions=(AssertionSpec("addressed", "guided.prompt_count", Comparator.GE, 0, blocking=True),))


class _Detector:
    def __init__(self, state: ContentionState = ContentionState.FREE) -> None:
        self.state = state
        self.calls = 0

    def detect(self):
        from jarvis.testlab.devices import ContentionEvidence, ContentionReport

        self.calls += 1
        evidence = ContentionEvidence("double", self.state, f"the double states {self.state.value}")
        holder = "the Jarvis voice runtime" if self.state is ContentionState.BUSY else None
        return ContentionReport(self.state, holder, (evidence,))


def _supervisor(tmp_path: Path, spec: DiagnosticSpec, *, detector=None, base_environ=None,
                lease: Path | None | object = ...):
    manifest = DiagnosticManifest(spec)
    catalog = Catalog.build([(manifest.relative_path, manifest)], CatalogLock((lock_entry_for(manifest),)),
                            primitives=DEFAULT_PRIMITIVES, implementations=catalog_implementations())
    store = FilesystemTestRunStore(tmp_path / "store", limits=ArtifactWriteLimits(allow_audio=False))
    launcher = FakeLauncher("measure")
    supervisor = RunSupervisor(
        store=store, work_root=tmp_path / "work", catalog=catalog, catalog_root=tmp_path / "catalog",
        policy=SupervisorPolicy(poll_interval_s=0.02, startup_timeout_s=5, heartbeat_timeout_s=5,
                                cancel_grace_s=1, max_queue_wait_s=5),
        launcher=launcher, settings_path=None, diagnostics=None, clock=_clock(0), nonce=_nonce(),
        code_probe=_code, environment={"os": "windows", "python_version": "3.14.6"},
        base_environ=base_environ, contention=detector, device_lease_path=lease)
    return supervisor, launcher


async def test_a_guided_run_is_refused_when_nobody_declared_a_human_present(tmp_path):
    supervisor, launcher = _supervisor(tmp_path, guided_spec(), detector=_Detector(), base_environ={})
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.guided_probe", ProfileName.HARDWARE_GUIDED,
                                                    grant=GUIDED_GRANT))
        run = await supervisor.wait(run_id, timeout_s=30)
    assert run.status is RunStatus.ERRORED and run.failure.code == FAILURE_HUMAN_PRESENCE_MISSING
    assert classify_run(run).outcome is RunOutcomeClass.REFUSED
    assert launcher.workers == [], "nobody's time is spent showing prompts to an empty chair"


async def test_the_presence_opt_in_is_the_operator_saying_so_and_nothing_derives_it():
    assert guided_opt_in({}) is False and guided_opt_in({GUIDED_OPT_IN_ENV: "true"}) is False
    assert guided_opt_in({GUIDED_OPT_IN_ENV: "1"}) is True


async def test_contention_refuses_a_guided_run_before_the_device_is_touched(tmp_path):
    detector = _Detector(ContentionState.BUSY)
    supervisor, launcher = _supervisor(tmp_path, guided_spec(), detector=detector, base_environ=PRESENT)
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.guided_probe", ProfileName.HARDWARE_GUIDED,
                                                    grant=GUIDED_GRANT))
        run = await supervisor.wait(run_id, timeout_s=30)
    assert run.failure.code == FAILURE_DEVICE_CONTENTION
    assert classify_run(run).outcome is RunOutcomeClass.REFUSED
    assert launcher.workers == [], "the refusal happens before a worker exists"


async def test_an_unknown_contention_answer_refuses_a_guided_run_too(tmp_path):
    supervisor, launcher = _supervisor(tmp_path, guided_spec(), detector=_Detector(ContentionState.UNKNOWN),
                                       base_environ=PRESENT)
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.guided_probe", ProfileName.HARDWARE_GUIDED,
                                                    grant=GUIDED_GRANT))
        run = await supervisor.wait(run_id, timeout_s=30)
    assert run.failure.code == FAILURE_DEVICE_CONTENTION and launcher.workers == []


async def test_the_shared_lease_stops_a_second_hardware_run_reaching_for_the_same_microphone(tmp_path):
    """Two work roots, one laptop microphone: the second is refused, never raced."""
    from jarvis.testlab.devices import DeviceLease

    lease = tmp_path / "shared.device.lock"
    held = DeviceLease(lease)
    held.acquire()
    try:
        supervisor, launcher = _supervisor(tmp_path / "second", guided_spec(), detector=_Detector(),
                                           base_environ=PRESENT, lease=lease)
        async with supervisor:
            run_id = await supervisor.submit(RunRequest("voice.guided_probe", ProfileName.HARDWARE_GUIDED,
                                                        grant=GUIDED_GRANT))
            run = await supervisor.wait(run_id, timeout_s=30)
    finally:
        held.release()
    assert run.failure.code == FAILURE_DEVICE_CONTENTION and launcher.workers == []


async def test_a_guided_run_needs_the_human_presence_capability_in_the_grant(tmp_path):
    from jarvis.testlab.jobs import FAILURE_PERMISSION_DENIED

    grant = ResourceGrant(frozenset({Capability.AUDIO_INPUT_DEVICE, Capability.AUDIO_OUTPUT_DEVICE}))
    supervisor, launcher = _supervisor(tmp_path, guided_spec(), detector=_Detector(), base_environ=PRESENT)
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.guided_probe", ProfileName.HARDWARE_GUIDED,
                                                    grant=grant))
        run = await supervisor.wait(run_id, timeout_s=30)
    assert run.failure.code == FAILURE_PERMISSION_DENIED and launcher.workers == []


async def test_a_hardware_run_may_store_an_audio_clip_only_when_all_three_gates_agree(tmp_path):
    from jarvis.testlab.supervisor import AUDIO_CAPABLE_PROFILES

    assert {ProfileName.HARDWARE_AUTO, ProfileName.HARDWARE_GUIDED} <= AUDIO_CAPABLE_PROFILES

    async def job(*, asked: bool, store_allows: bool) -> bool:
        spec = guided_spec()
        manifest = DiagnosticManifest(spec)
        catalog = Catalog.build([(manifest.relative_path, manifest)],
                                CatalogLock((lock_entry_for(manifest),)), primitives=DEFAULT_PRIMITIVES,
                                implementations=catalog_implementations())
        root = tmp_path / f"{asked}-{store_allows}"
        store = FilesystemTestRunStore(root / "store",
                                       limits=ArtifactWriteLimits(allow_audio=store_allows))
        launcher = FakeLauncher("measure")
        supervisor = RunSupervisor(
            store=store, work_root=root / "work", catalog=catalog, catalog_root=root / "catalog",
            policy=SupervisorPolicy(poll_interval_s=0.02, startup_timeout_s=5, heartbeat_timeout_s=5,
                                    cancel_grace_s=1, max_queue_wait_s=5),
            launcher=launcher, settings_path=None, diagnostics=None, clock=_clock(0), nonce=_nonce(),
            code_probe=_code, environment={"os": "windows", "python_version": "3.14.6"},
            base_environ=PRESENT, contention=_Detector(), device_lease_path=None)
        async with supervisor:
            run_id = await supervisor.submit(RunRequest("voice.guided_probe",
                                                        ProfileName.HARDWARE_GUIDED, grant=GUIDED_GRANT,
                                                        allow_audio_artifacts=asked))
            await supervisor.wait(run_id, timeout_s=30)
        return launcher.workers[0].job.allow_audio

    assert await job(asked=True, store_allows=True) is True
    assert await job(asked=False, store_allows=True) is False
    assert await job(asked=True, store_allows=False) is False


async def test_the_guided_gate_runs_after_the_provider_opt_in_so_a_refusal_names_the_first_cause(tmp_path):
    """Order in the external gate: everything that only OBSERVES, then the one thing that TAKES."""
    from jarvis.testlab.jobs import FAILURE_LIVE_OPT_IN_MISSING

    spec = DiagnosticSpec(
        diagnostic_id="voice.guided_probe", version=1, title="Guided probe fixture", domain="voice",
        profiles={ProfileName.HARDWARE_GUIDED: ProfileSpec(
            ProfileName.HARDWARE_GUIDED, "testlab.scenario.hardware_guided", CostBounds(60, 0.1),
            GUIDED_CAPABILITIES | {Capability.REALTIME_PROVIDER})},
        metrics=(MetricSpec("guided.prompt_count", MetricUnit.COUNT, MetricDirection.NEUTRAL),),
        assertions=(AssertionSpec("addressed", "guided.prompt_count", Comparator.GE, 0, blocking=True),))
    lease = tmp_path / "shared.device.lock"
    supervisor, launcher = _supervisor(tmp_path, spec, detector=_Detector(), base_environ={}, lease=lease)
    grant = ResourceGrant(GUIDED_CAPABILITIES | {Capability.REALTIME_PROVIDER}, max_cost_usd=1.0)
    async with supervisor:
        run_id = await supervisor.submit(RunRequest("voice.guided_probe", ProfileName.HARDWARE_GUIDED,
                                                    grant=grant))
        run = await supervisor.wait(run_id, timeout_s=30)
    assert run.failure.code == FAILURE_LIVE_OPT_IN_MISSING and launcher.workers == []
    # And the lease, the only thing the gate TAKES, was never taken by the refused run.
    from jarvis.testlab.devices import DeviceLease

    other = DeviceLease(lease)
    other.acquire()
    other.release()


# ----------------------------------------------------------- the artifact rules

async def test_every_hardware_artifact_path_fits_the_budget_and_the_path_rule():
    from jarvis.testlab.hardware.runners import CLIP_ARTIFACT, METADATA_ARTIFACT

    for path in (METADATA_ARTIFACT, CLIP_ARTIFACT, TRANSCRIPT_ARTIFACT):
        check_artifact_path(path)
        assert len(path) <= 171, path


async def test_the_late_grace_is_a_bound_a_caller_can_see():
    assert 0 < LATE_GRACE_S <= MAX_PROMPT_DEADLINE_S


# --------------------------------------------------- the provider-onset seam

async def test_an_onset_seam_that_forgets_to_answer_is_a_defect_not_a_decline():
    """`None` is not "declined": it would silently turn every candidate into one.

    That is exactly what happened — a test seam dropped its `return`, every onset read as
    declined, and the run reported it could not measure while looking healthy. It went
    unnoticed because the capture's own near-end signal was reaching the bridge and
    producing a barge-in anyway: the right answer for the wrong reason.
    """
    from jarvis.testlab.hardware.runners import raise_provider_onset

    async def forgetful(context, stack):
        del context, stack

    with pytest.raises(TestLabError) as caught:
        await raise_provider_onset(None, None, forgetful)
    assert "must return whether it raised" in caught.value.detail

    async def declines(context, stack):
        del context, stack
        return False

    assert await raise_provider_onset(None, None, declines) is False

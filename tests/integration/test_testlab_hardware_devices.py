"""OPT-IN: the Test Lab hardware profiles against this workstation's REAL devices.

Skipped unless the switch is set. Nothing in the default suite may open a device: the
workstation Jarvis owns the laptop microphone and speakers (READINESS B9), and a test
that took them would interrupt a live conversation. The default hardware coverage lives
in `test_testlab_hardware_runners.py`, which runs the same production code over a
`sounddevice` double.

Three levels, each a deliberate act:

- `JARVIS_TESTLAB_HARDWARE=1` runs `hardware:auto` on the real speaker and microphone.
  It plays a short tone out loud and records the room for a couple of seconds. It
  REFUSES to run unless the Slice 08 contention detector says the devices are free — a
  skip, never a steal.
- `JARVIS_TESTLAB_GUIDED=1` additionally runs one `hardware:guided` scenario, which
  needs a HUMAN at the keyboard following the prompts. It is the automated half of
  HV-TL-HW-01; the operator script is
  `tasks/jarvis-category2-test-lab/slices/09-hardware-guided/operator-script.md`.
- Both are independent of `JARVIS_TESTLAB_LIVE`: no hardware profile calls a provider.

**Never executed as part of Slice 09.** These tests are written and left skipped. Their
result is "unverified", not "passed": no real device has been opened and no human has
been prompted by this code. That is the Human's call, and it is what HV-TL-HW-01 is for.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from jarvis.testlab.devices import ContentionState, default_contention_detector
from jarvis.testlab.diagnostics import assertions_verdict, evaluate_assertion, resolve_parameters
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.hardware.channel import FilePrompter, PromptWatcher
from jarvis.testlab.hardware.devices import DeviceUnavailable, hardware_contention_detector
from jarvis.testlab.hardware.prompts import (
    TRANSCRIPT_ARTIFACT,
    GuidedPromptUnavailable,
    guided_opt_in,
)
from jarvis.testlab.hardware.runners import (
    METADATA_ARTIFACT,
    PROMPT_DONE,
    PROMPT_INTERRUPT,
    PROMPT_SILENCE,
    SelfEchoGuidedRunner,
    SelfEchoHardwareRunner,
)
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.manifests import decode_manifest_text
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runners import RunArtifacts, RunContext
from jarvis.testlab.runs import CodeIdentity, RunStatus, TestRun
from jarvis.testlab.store import ArtifactWriteLimits
from tests.fakes.testlab import CONFIG, ENVIRONMENT, NONCE, REVISION, T0

pytestmark = pytest.mark.asyncio

REPO_ROOT = Path(__file__).resolve().parents[2]
#: The runtime root the workstation Jarvis publishes its voice signals in.
LIVE_RUNTIME_ROOT = Path(os.getenv("JARVIS_TESTLAB_LIVE_RUNTIME") or (REPO_ROOT / "runtime"))
SLICE_09 = REPO_ROOT / "tasks/jarvis-category2-test-lab/slices/09-hardware-guided"
#: The two manifests this Slice PROPOSES: the `hardware:auto` negative claim, and the
#: guided positive claim as its own diagnostic with a blocking assertion.
PROPOSED_V3 = SLICE_09 / "proposed-voice.self_echo.v3.json"
PROPOSED_GUIDED = SLICE_09 / "proposed-voice.barge_in_response.v1.json"
RUN_ID = format_run_id(T0, NONCE)
#: Short: the human is standing there, and the acoustic claim does not need a monologue.
PARAMETERS = {"output.duration_ms": 3000, "echo.candidate_count": 3}

hardware_only = pytest.mark.skipif(
    os.getenv("JARVIS_TESTLAB_HARDWARE") != "1",
    reason="requires JARVIS_TESTLAB_HARDWARE=1 (opens this workstation's microphone and speaker)")
guided_only = pytest.mark.skipif(
    os.getenv("JARVIS_TESTLAB_HARDWARE") != "1" or os.getenv("JARVIS_TESTLAB_GUIDED") != "1",
    reason="requires JARVIS_TESTLAB_HARDWARE=1 and JARVIS_TESTLAB_GUIDED=1 (needs a human in the room)")


def require_free_devices() -> None:
    """Refuse to touch the devices unless the detector positively says they are free."""
    report = default_contention_detector(LIVE_RUNTIME_ROOT).detect()
    if not report.available:
        pytest.skip(f"the audio devices are not free, so this test will not take them: {report.reason()}")


def spec_for(profile: ProfileName):
    source = PROPOSED_GUIDED if profile is ProfileName.HARDWARE_GUIDED else PROPOSED_V3
    return decode_manifest_text(source.read_text(encoding="utf-8")).diagnostic


def build_context(tmp_path: Path, profile: ProfileName):
    spec = spec_for(profile)
    parameters = resolve_parameters(spec.parameters, dict(PARAMETERS))
    store = FilesystemTestRunStore(tmp_path / "store", limits=ArtifactWriteLimits(allow_audio=False))
    store.create_run(TestRun(run_id=RUN_ID, diagnostic_id=spec.diagnostic_id,
                             diagnostic_version=spec.version, profile=profile, status=RunStatus.QUEUED,
                             created_at=T0, code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                             diagnostic_fingerprint=spec.fingerprint(), parameters=parameters,
                             environment=ENVIRONMENT))
    scratch = tmp_path / "scratch"
    (scratch / "runtime").mkdir(parents=True, exist_ok=True)
    (scratch / "data").mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    context = RunContext(run_id=RUN_ID, diagnostic=spec, profile=profile, parameters=parameters,
                         overrides={}, scenario=None, runtime_dir=scratch / "runtime",
                         data_root=scratch / "data", artifacts=RunArtifacts(store, RUN_ID),
                         cancelled=asyncio.Event(),
                         deadline=asyncio.get_running_loop().time() + 600.0, log=lines.append)
    return context, store, lines


def verdict_of(spec, metrics) -> str:
    index = spec.metric_index
    return assertions_verdict(tuple(evaluate_assertion(item, index[item.metric], metrics.get(item.metric))
                                    for item in spec.assertions)).value


@hardware_only
async def test_the_contention_detector_answers_before_any_hardware_run():
    """The gate every hardware run passes through, on the real runtime root."""
    report = hardware_contention_detector(LIVE_RUNTIME_ROOT).detect()
    assert report.state in tuple(ContentionState) and report.reason()
    assert {item.source for item in report.evidence} == {"live_voice_runtime", "audio_backend"}


@hardware_only
async def test_self_echo_on_the_real_speaker_and_microphone(tmp_path, capsys):
    """OPT-IN AND GATED. Plays a tone out loud and records the room for a few seconds.

    This is `hardware:auto`: no human, so the only claim it can make is the negative one
    — nothing confirmed a barge-in while the room was (assumed) quiet. Read it together
    with the guided test below, which is the one that proves the gate still opens.
    """
    require_free_devices()
    context, store, lines = build_context(tmp_path, ProfileName.HARDWARE_AUTO)
    try:
        outcome = await SelfEchoHardwareRunner().run(context)
    except DeviceUnavailable as exc:
        pytest.skip(f"this workstation could not carry the measurement ({exc.code}): {exc.detail}")
    with capsys.disabled():
        print("\n".join(lines))
    metrics = dict(outcome.metrics)
    assert metrics["output.played_ms"] > 0, "nothing came out of the speaker"
    assert metrics["barge_in.false_confirmed_count"] == 0
    assert verdict_of(context.diagnostic, metrics) == "passed"
    # The evidence a human reads afterwards: what was exercised, on which device.
    assert METADATA_ARTIFACT in [ref.path for ref in context.committed]
    del store


@guided_only
async def test_the_guided_self_echo_with_a_human_in_the_room(tmp_path, capsys):
    """HV-TL-HW-01, automated half. A HUMAN must be at this keyboard, following the prompts.

    The prompts are printed here and answered here, which is what Slice 10's CLI and
    Slice 11's UI will do properly; this presenter exists so the flow can be exercised
    before either of them is written.
    """
    require_free_devices()
    assert guided_opt_in(), "the presence opt-in is what says a human is here"
    context, store, lines = build_context(tmp_path, ProfileName.HARDWARE_GUIDED)

    class ConsoleHuman:
        """The simplest possible presenter: print the step, wait for Enter."""

        def __init__(self) -> None:
            self.shown: list[str] = []

        async def present(self, prompt):
            from jarvis.testlab.hardware.prompts import PromptReply

            self.shown.append(prompt.prompt_id)
            with capsys.disabled():
                print(f"\n>>> {prompt.action.value.upper()} ({prompt.deadline_s:.0f} s): {prompt.text}")
                if prompt.phrase:
                    print(f'>>> say: "{prompt.phrase}"')
                print(">>> press Enter when done")
                await asyncio.get_running_loop().run_in_executor(None, input)
            return PromptReply()

    human = ConsoleHuman()
    try:
        outcome = await SelfEchoGuidedRunner(prompter=human).run(context)
    except GuidedPromptUnavailable as exc:
        pytest.skip(f"the guided run could not be completed ({exc.code}): {exc.detail}")
    except DeviceUnavailable as exc:
        pytest.skip(f"this workstation could not carry the measurement ({exc.code}): {exc.detail}")
    with capsys.disabled():
        print("\n".join(lines))
    assert human.shown == [PROMPT_SILENCE, PROMPT_INTERRUPT, PROMPT_DONE]
    metrics = dict(outcome.metrics)
    assert metrics["guided.prompt_count"] == 3
    assert metrics["barge_in.false_confirmed_count"] == 0, "Jarvis interrupted itself on its own echo"
    assert metrics["barge_in.true_confirmed_count"] >= 1, "a real human voice did not get through the gate"
    assert metrics["barge_in.first_candidate_offset_ms"] >= 400, "the pre-roll was honoured"
    assert TRANSCRIPT_ARTIFACT in [ref.path for ref in context.committed]


@guided_only
async def test_the_file_channel_carries_a_prompt_to_a_presenter_and_back(tmp_path):
    """The channel Slices 10 and 11 drive, exercised end to end on a real filesystem.

    Not gated on the devices: it opens nothing. It is here rather than in the default
    suite only because it is the guided flow's plumbing and belongs beside it; the unit
    tests cover the same contract with no filesystem of the user's involved.
    """
    from jarvis.testlab.hardware.prompts import GuidedAction, prompt_for

    prompter = FilePrompter(tmp_path, poll_interval_s=0.01)
    watcher = PromptWatcher(tmp_path)
    prompt = prompt_for(GuidedAction.ACKNOWLEDGE, "done")

    async def answer() -> None:
        while True:
            pending = watcher.pending()
            if pending is not None:
                watcher.acknowledge(pending[0].prompt_id, pending[1])
                return
            await asyncio.sleep(0.01)

    answering = asyncio.ensure_future(answer())
    reply = await prompter.present(prompt)
    await answering
    assert reply.acknowledged

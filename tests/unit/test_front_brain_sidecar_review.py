"""Independent session-sidecar races. No production fallback or shared fake edits."""
import asyncio
from datetime import datetime, timezone
import json
import time

import httpx
import pytest

from jarvis.adapters.openai_front_brain import LunaFrontBrainAnalyzer
from jarvis.domain.front_brain_hints import FrontBrainHintResult, FrontBrainHintValue, HintAnalysisStatus
from jarvis.domain.reflex_policy import ReflexAction
from jarvis.domain.speech_presentation import SpeechDependency, SpeechSource
from jarvis.domain.voice_events import UserCommitSource, UserTranscriptCommitted, UserTranscriptDelta, VoiceEvent
from jarvis.domain.voice_frontend import VoiceContext, VoiceContextMessage, VoiceContextRole, VoiceCorrelation, VoiceObservation
from jarvis.runtime.front_brain_sidecar import FrontBrainSidecar, FrontBrainSidecarConfig


class Diagnostics:
    def __init__(self):
        self.records = []
    def emit(self, channel, message, *, data=None, **kwargs):
        self.records.append((channel, data))


class ControlledAnalyzer:
    def __init__(self, *, resist=False):
        self.requests, self.gates = [], []
        self.active = self.peak = self.cancelled = 0
        self.resist = resist
    async def analyze(self, request):
        self.requests.append(request)
        gate = asyncio.Event()
        self.gates.append(gate)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            while not gate.is_set():
                try:
                    await gate.wait()
                except asyncio.CancelledError:
                    self.cancelled += 1
                    if not self.resist:
                        raise
            return FrontBrainHintResult(request.request_id, HintAnalysisStatus.AVAILABLE,
                FrontBrainHintValue(suggested_action=ReflexAction.DELEGATE, intent_hypothesis="PRIVATE hypothesis"), time.monotonic_ns())
        finally:
            self.active -= 1


def event(revision=1, text="PRIVATE input", *, item="item", transcript=None, final=False):
    transcript = transcript or "transcript-" + item
    payload = UserTranscriptCommitted(transcript, text, revision, UserCommitSource.APPLICATION) if final else UserTranscriptDelta(transcript, text, revision)
    return VoiceEvent(f"{item}-{transcript}-{revision}", revision,
        VoiceCorrelation("session", turn_id="voice-turn-" + item, provider_input_id=item),
        VoiceObservation(datetime.now(timezone.utc), time.monotonic_ns()), payload)


async def until(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(.001)


def sidecar(analyzer, *, diagnostics=None, **config):
    obj = FrontBrainSidecar(analyzer, session_id="session", configuration_id="config",
        config=FrontBrainSidecarConfig(debounce_s=0, min_interval_s=0, **config), diagnostics=diagnostics)
    obj.update_context(VoiceContext(), source=None, source_complete=True)
    obj.start()
    return obj


def test_default_constructor_is_usable_without_context_override():
    assert FrontBrainSidecar(ControlledAnalyzer(), session_id="session", configuration_id="config") is not None


@pytest.mark.asyncio
async def test_one_flight_latest_pending_keeps_only_latest_exact_revision():
    analyzer = ControlledAnalyzer()
    worker = sidecar(analyzer)
    try:
        worker.allow_item("item", "permission")
        worker.observe(event())
        await until(lambda: len(analyzer.requests) == 1)
        for revision in range(2, 101):
            worker.observe(event(revision, "x"))
        await asyncio.sleep(.01)
        assert len(analyzer.requests) == 1 and analyzer.active == 1
        analyzer.gates[0].set()
        await until(lambda: len(analyzer.requests) == 2)
        assert analyzer.requests[1].input.text == "PRIVATE input" + "x" * 99
        assert analyzer.requests[1].input.revision == 100
        assert analyzer.peak == 1
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_final_cancels_partial_and_reserves_final_budget_without_refund():
    analyzer = ControlledAnalyzer()
    worker = sidecar(analyzer)
    try:
        worker.allow_item("item", "permission")
        worker.observe(event())
        await until(lambda: len(analyzer.requests) == 1)
        analyzer.gates[0].set()
        worker.observe(event(2, " revised"))
        await until(lambda: len(analyzer.requests) == 2)
        worker.update_source(source=SpeechSource("core-turn", "corr", "intent", 1), source_complete=True)
        worker.observe(event(3, "FINAL", final=True))
        worker.admit_item("item", SpeechSource("core-turn", "corr", "intent", 1))
        await until(lambda: len(analyzer.requests) == 3)
        assert analyzer.cancelled == 1 and analyzer.peak == 1
        assert analyzer.requests[-1].input.text == "FINAL" and analyzer.requests[-1].input.committed
        assert worker._items["item"].reservation == 3 * worker.config.reservation_per_call
        worker.admit_item("item", SpeechSource("core-turn", "corr", "intent", 1))
        await asyncio.sleep(.01)
        assert len(analyzer.requests) == 3
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_cancel_resistant_partial_cannot_consume_or_displace_final():
    analyzer, diagnostics = ControlledAnalyzer(resist=True), Diagnostics()
    worker = sidecar(analyzer, diagnostics=diagnostics)
    try:
        worker.allow_item("item", "permission")
        worker.observe(event())
        await until(lambda: len(analyzer.requests) == 1)
        worker.update_source(source=SpeechSource("core-turn", "corr", "intent", 1), source_complete=True)
        worker.observe(event(2, "FINAL", final=True))
        worker.admit_item("item", SpeechSource("core-turn", "corr", "intent", 1))
        await until(lambda: analyzer.cancelled >= 1)
        assert len(analyzer.requests) == 1
        analyzer.gates[0].set()
        await until(lambda: len(analyzer.requests) == 2)
        analyzer.gates[1].set()
        await until(lambda: any(channel == "voice.hint.consumed" for channel, _ in diagnostics.records))
        consumed = [data["request_id"] for channel, data in diagnostics.records if channel == "voice.hint.consumed"]
        assert consumed == [analyzer.requests[1].request_id]
        assert "PRIVATE" not in json.dumps(diagnostics.records)
    finally:
        for gate in analyzer.gates:
            gate.set()
        await worker.close()


@pytest.mark.asyncio
async def test_permission_is_per_item_and_rejected_item_never_resurrects():
    analyzer = ControlledAnalyzer()
    worker = sidecar(analyzer)
    try:
        worker.allow_item("A", "permission-A")
        worker.observe(event(item="B"))
        await asyncio.sleep(.01)
        assert not analyzer.requests
        worker.reject_item("B", "foreign")
        worker.allow_item("B", "new-permission")
        worker.observe(event(2, item="B", final=True))
        worker.admit_item("B", SpeechSource("core-B", "corr-B", "intent-B", 1))
        await asyncio.sleep(.01)
        assert not analyzer.requests and worker._items["B"].record is None
        worker.observe(event(item="A"))
        await until(lambda: len(analyzer.requests) == 1)
        assert analyzer.requests[0].input.correlation.provider_input_id == "A"
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_conflicting_transcript_identity_invalidates_old_speculation():
    analyzer, diagnostics = ControlledAnalyzer(resist=True), Diagnostics()
    worker = sidecar(analyzer, diagnostics=diagnostics)
    try:
        worker.allow_item("item", "permission")
        worker.observe(event())
        await until(lambda: len(analyzer.requests) == 1)
        worker.observe(event(2, "different group", transcript="other-transcript"))
        analyzer.gates[0].set()
        await until(lambda: analyzer.active == 0)
        await asyncio.sleep(.01)
        assert not [data for channel, data in diagnostics.records if channel == "voice.hint.consumed"]
    finally:
        for gate in analyzer.gates:
            gate.set()
        await worker.close()


@pytest.mark.asyncio
async def test_saturation_disables_speculation_without_evicting_rejection_tombstones():
    analyzer = ControlledAnalyzer()
    worker = sidecar(analyzer, max_items=2)
    try:
        worker.reject_item("A", "foreign")
        worker.reject_item("B", "foreign")
        worker.allow_item("C", "permission-C")
        worker.observe(event(item="C"))
        worker.allow_item("A", "permission-A")
        worker.observe(event(2, item="A"))
        await asyncio.sleep(.01)
        assert worker._disabled and len(worker._items) == 2 and not analyzer.requests
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_close_joins_cancel_resistant_owned_task_and_fences_late_observations():
    analyzer = ControlledAnalyzer(resist=True)
    worker = sidecar(analyzer)
    worker.allow_item("item", "permission")
    worker.observe(event())
    await until(lambda: len(analyzer.requests) == 1)
    closing = asyncio.create_task(worker.close())
    try:
        await until(lambda: analyzer.cancelled >= 1)
        assert not closing.done()
        worker.observe(event(2, "LATE", final=True))
        worker.allow_item("late", "permission")
        analyzer.gates[0].set()
        await asyncio.wait_for(closing, 1)
        assert analyzer.active == 0 and len(analyzer.requests) == 1
        assert worker._worker is None and worker._flight is None
    finally:
        for gate in analyzer.gates:
            gate.set()
        await worker.close()


@pytest.mark.asyncio
async def test_dispatch_reserves_before_analyzer_and_timeout_never_refunds():
    observed = []
    class TimeoutAnalyzer:
        async def analyze(self, request):
            observed.append(worker._items["item"].reservation)
            return FrontBrainHintResult(request.request_id, HintAnalysisStatus.TIMED_OUT, None, time.monotonic_ns())
    worker = sidecar(TimeoutAnalyzer())
    try:
        worker.allow_item("item", "permission")
        worker.observe(event())
        await until(lambda: len(observed) == 1)
        worker.observe(event(2, " revised"))
        await until(lambda: len(observed) == 2)
        assert observed == [worker.config.reservation_per_call, 2 * worker.config.reservation_per_call]
        assert worker._items["item"].reservation == observed[-1]
        assert worker.config.reservation_per_call >= 131072 + 4096
    finally:
        await worker.close()


def test_config_cannot_claim_reservation_below_request_and_output_ceiling():
    with pytest.raises(ValueError):
        FrontBrainSidecarConfig(reservation_per_call=512)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["é" * 8192, "😀" * 8192, "\x01" * 8192], ids=["utf8", "astral", "escaped"])
async def test_full_serialized_request_ceiling_covers_metadata_and_escaping(text):
    calls = []
    dependencies = tuple(SpeechDependency(str(index).ljust(256, "w"), "c" * 256) for index in range(16))
    source = SpeechSource("t" * 256, "c" * 256, "i" * 256, 1, dependencies)
    def respond(req):
        calls.append(req)
        assert len(req.content) <= 131072
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message",
            "role": "assistant", "status": "completed", "content": [{"type": "output_text",
            "text": json.dumps(FrontBrainHintValue().to_payload())}]}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        analyzer = LunaFrontBrainAnalyzer(api_key="test-only", client=client)
        worker = sidecar(analyzer)
        try:
            worker.update_context(VoiceContext(1, (VoiceContextMessage(VoiceContextRole.USER, text),)),
                                  source=source, source_complete=True)
            worker.allow_item("item", "permission")
            worker.observe(event(text=text, final=True))
            worker.admit_item("item", source)
            await until(lambda: worker._items["item"].final_dispatched and worker._flight is None)
            record = worker._items["item"]
            assert record.reservation == worker.config.reservation_per_call
            # A valid character-bounded request can still exceed the serialized byte cap.
            # Refusing presentation must not become a silent truncation or refund.
            if text.startswith("\x01"):
                assert not calls
            else:
                assert len(calls) == 1
                assert text in json.loads(json.loads(calls[0].content)["input"][0]["content"][0]["text"])["input"]["text"]
        finally:
            await worker.close()

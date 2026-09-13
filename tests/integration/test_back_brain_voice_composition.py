"""Independent job + actual voice/Core composition; external work is barrier-controlled."""
import asyncio
import base64
import json
from types import SimpleNamespace

from aiohttp.test_utils import TestServer

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.back_brain import BackBrainResult
from jarvis.domain.v2 import JobProgress
from jarvis.domain.voice_architecture import VoiceArchitectureId
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import realtime_audio
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.realtime_frontend_session import RealtimeFrontendSession
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.runtime.back_brain_delegation import conversation_tools
from tests.fakes.audio_device import BufferedOutputStream
from tests.integration.test_voice_production_composition import ControlledWake, ControlledWire
from tests.unit.test_v2_voice_toggle import FakeHttpSession


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(.002)


async def test_job_survives_a_second_direct_turn_and_frontend_replacement_without_speech(tmp_path, monkeypatch):
    class Worker:
        def __init__(self):
            self.entered, self.release = asyncio.Event(), asyncio.Event()
            self.jobs, self.cancelled = [], []
            self.finished = False

        async def execute_with_progress(self, job, progress):
            self.jobs.append(job)
            self.entered.set()
            await progress.emit(job.id, JobProgress(phase="agent_started"))
            await self.release.wait()  # Simulated 90-second work, no wall-clock sleep.
            self.finished = True
            await progress.emit(job.id, JobProgress(phase="finalizing"))
            return BackBrainResult("Durable factual job result", "controlled", "selected-model", "job-session").to_payload()

        async def cancel_owned(self, job_id):
            if not self.finished:
                self.cancelled.append(job_id)
                self.release.set()
            return True

        async def cleanup_owned(self, job_id):
            return self.finished

        async def cancel(self, job_id):
            await self.cancel_owned(job_id)

    class Backend:
        calls = []
        async def run_turn(self, turn, sink):
            self.calls.append(turn)
            raise AssertionError("reserved admitted source must not run the conversational backend")

    worker, backend = Worker(), Backend()
    core = JarvisCoreApplication(data_root=tmp_path / "data", workers={"back_brain": worker}, brain_backend=backend)
    await core.start()
    core.jobs.progress_min_interval_s = 0
    token = "test-token-for-independent-job-11"
    server = TestServer(LocalProtocolServer(core, host="127.0.0.1", port=0, token=token)._app())
    await server.start_server()
    client = LocalCoreClient(host="127.0.0.1", port=server.port, token=token)
    wires, admissions, acknowledgements, devices = [], [], [], []
    submit_entered, submit_release = asyncio.Event(), asyncio.Event()
    real_submit = core.back_brain.submit
    async def gated_submit(request):
        submit_entered.set()
        await submit_release.wait()
        return await real_submit(request)
    monkeypatch.setattr(core.back_brain, "submit", gated_submit)
    from jarvis.runtime.speech_scheduler import SpeechScheduler
    real_enqueue = SpeechScheduler.enqueue_controller_speech
    def capture_ack(scheduler, request):
        acknowledgements.append(request)
        real_enqueue(scheduler, request)
    monkeypatch.setattr(SpeechScheduler, "enqueue_controller_speech", capture_ack)
    original_admit = RealtimeFrontendSession.admit_conversation

    async def capture_admission(session, *args, **kwargs):
        accepted = await original_admit(session, *args, **kwargs)
        admissions.append(accepted)
        return accepted
    monkeypatch.setattr(RealtimeFrontendSession, "admit_conversation", capture_admission)

    async def factory(context):
        wire = ControlledWire()
        wires.append(wire)
        return await RealtimeFrontendSession.connect(api_key="controlled", model="gpt-realtime-2.1", voice="cedar",
            context=context, conversational=True, continuous_brain=True, auto_turn=True, tools=conversation_tools(), session=FakeHttpSession(wire))

    class Audio(realtime_audio.SoundDeviceRealtimeAudio):
        async def start(self):
            self._output = BufferedOutputStream()
            devices.append(self._output)
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", Audio)
    runtime = PersistentVoiceRuntime(wakeword=ControlledWake(), core=client, realtime_factory=factory,
        auto_turn=True, conversation_architecture=VoiceArchitectureId.SIMPLE,
        journal=RuntimeJournal(tmp_path / "runtime"))

    def user(wire, item_id, text, previous=None):
        wire.push("input_audio_buffer.speech_started", item_id=item_id, audio_start_ms=0)
        wire.push("input_audio_buffer.speech_stopped", item_id=item_id, audio_end_ms=100)
        wire.push("input_audio_buffer.committed", item_id=item_id, previous_item_id=previous)
        wire.push("conversation.item.input_audio_transcription.completed", item_id=item_id, transcript=text)

    try:
        await runtime.activate()
        first = runtime._session
        conversation_id = runtime.runtime.conversation_id
        user(wires[0], "input-a", "Jarvis, prépare le rapport demandé.")
        await until(lambda: admissions and any(e["type"] == "response.create" for e in wires[0].sent))
        response = next(e["response"] for e in wires[0].sent if e["type"] == "response.create")
        wires[0].push("response.created", response={"id": "response-a", "metadata": response["metadata"]})
        def delegate(call_id):
            wires[0].push("response.function_call_arguments.done", response_id="response-a", call_id=call_id,
                          name="back_brain_delegate", arguments="{}")
        delegate("delegate-a")
        wires[0].push("response.done", response={"id": "response-a", "status": "completed", "output": []})
        await asyncio.wait_for(submit_entered.wait(), 2)
        assert not acknowledgements and not worker.jobs
        submit_release.set()
        await until(lambda: any(e.get("item", {}).get("call_id") == "delegate-a" for e in wires[0].sent))
        tool_result = next(json.loads(e["item"]["output"]) for e in wires[0].sent if e.get("item", {}).get("call_id") == "delegate-a")
        accepted = SimpleNamespace(job_id=tool_result["task_id"])
        assert tool_result["status"] == "accepted"
        assert len(acknowledgements) == 1
        ack = acknowledgements[0]
        assert ack.text == "Je m’en occupe." and ack.source == admissions[0].source
        assert ack.correlation_id == admissions[0].correlation_id and ack.work_id == accepted.job_id
        await asyncio.wait_for(worker.entered.wait(), 2)
        assert not worker.release.is_set()
        async with asyncio.timeout(2):
            while (await client.back_brain_task_status(conversation_id, accepted.job_id))["progress"] is None:
                await asyncio.sleep(.002)
        assert (await client.back_brain_task_status(conversation_id, accepted.job_id))["progress"]["phase"] == "agent_started"
        delegate("delegate-a")  # Duplicate wire delivery and a distinct call for the same source.
        delegate("delegate-a-retry")
        await until(lambda: any(e.get("item", {}).get("call_id") == "delegate-a-retry" for e in wires[0].sent))
        assert len(acknowledgements) == 1 and len(worker.jobs) == 1
        await until(lambda: sum(e["type"] == "response.create" for e in wires[0].sent) == 2)
        ack_response = [e["response"] for e in wires[0].sent if e["type"] == "response.create"][1]
        wires[0].push("response.created", response={"id": "ack-a", "metadata": ack_response["metadata"]})
        wires[0].push("response.output_item.added", response_id="ack-a", item={"id": "ack-message", "type": "message"})
        wires[0].push("response.output_audio_transcript.done", response_id="ack-a", item_id="ack-message", content_index=0, output_index=0, transcript=ack.text)
        wires[0].push("response.output_audio.delta", response_id="ack-a", item_id="ack-message", content_index=0, output_index=0, delta=base64.b64encode(b"\1\0" * 2400).decode())
        wires[0].push("response.output_audio.done", response_id="ack-a", item_id="ack-message", content_index=0, output_index=0)
        wires[0].push("response.done", response={"id": "ack-a", "status": "completed", "output": [{"id": "ack-message", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "audio", "transcript": ack.text}]}]})
        await until(lambda: devices[0].draining.is_set())
        before = (await core.voice_ledger.snapshot(conversation_id))["snapshot"]
        assert not any(s["confirmed_text"] for s in before["speeches"])
        devices[0].consume()
        async with asyncio.timeout(3):
            while not any(s["confirmed_text"] == ack.text for s in (await core.voice_ledger.snapshot(conversation_id))["snapshot"]["speeches"]):
                await asyncio.sleep(.002)
        # The atomic job acceptance reserved the same source for execution.
        await client.submit_brain_turn(conversation_id, content="Jarvis, prépare le rapport demandé.",
                                       correlation_id=admissions[0].correlation_id, provider_item_id="input-a")
        assert not backend.calls

        user(wires[0], "input-b", "Jarvis, combien font deux plus deux ?", "input-a")
        await until(lambda: len(admissions) == 2 and sum(e["type"] == "response.create" for e in wires[0].sent) == 3)
        assert not worker.release.is_set()
        assert len(worker.jobs) == 1
        assert worker.jobs[0].payload["provenance"]["source"] == admissions[0].source.to_payload()
        await runtime.mute()
        assert not worker.cancelled
        await runtime.activate()
        assert runtime._session is not first and runtime.runtime.conversation_id == conversation_id
        assert (await client.back_brain_task_status(conversation_id, accepted.job_id))["status"] == "running"
        assert not worker.cancelled
        worker.release.set()
        async with asyncio.timeout(5):
            while (status := await client.back_brain_task_status(conversation_id, accepted.job_id))["status"] != "completed":
                await asyncio.sleep(.002)
        assert status["result"]["text"] == "Durable factual job result"
        assert status["source_current"] is False
        assert status["progress"]["phase"] == "finalizing"
        assert not any(e["type"] == "response.create" for e in wires[1].sent)
        turns = await core.conversations.list_turns(conversation_id)
        assert [turn.kind.value for turn in turns] == ["user", "assistant", "user"]
        assert len(acknowledgements) == 1  # Completion never requests speech.
        assert not backend.calls
    finally:
        worker.release.set()
        submit_release.set()
        await runtime.mute()
        await client.close()
        await server.close()
        await core.stop()

    restarted = JarvisCoreApplication(data_root=tmp_path / "data", workers={"back_brain": worker}, brain_backend=backend)
    await restarted.start()
    reopened = TestServer(LocalProtocolServer(restarted, host="127.0.0.1", port=0, token=token)._app())
    await reopened.start_server()
    reader = LocalCoreClient(host="127.0.0.1", port=reopened.port, token=token)
    try:
        restored = await reader.back_brain_task_status(conversation_id, accepted.job_id)
        assert restored["status"] == "completed" and restored["result"] == status["result"]
        assert restored["provenance"] == status["provenance"]
        assert len(worker.jobs) == 1 and not worker.cancelled
    finally:
        await reader.close()
        await reopened.close()
        await restarted.stop()

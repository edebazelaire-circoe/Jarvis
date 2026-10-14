"""Côté Voice : rapports du canal vocal, demande « Passer au chat » exécutée une fois, pannes jamais levées.

Un vrai `PersistentVoiceRuntime` (architecture legacy, aucun fournisseur
ouvert) face à un faux Core qui porte le **vrai** `VoiceChannelService` en
mémoire : la boucle de supervision réelle (`_voice_timeout_loop`) fait la
bascule de bout en bout sans réseau.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from jarvis import app
from jarvis.core.voice_channel import VoiceChannelService
from jarvis.domain.v2 import VoiceLifecycleState
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture


class Journal:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append({"kind": kind, "level": level, "data": data or {}})

    def kinds(self, prefix: str = "voice.channel.") -> list[str]:
        return [e["kind"] for e in self.events if e["kind"].startswith(prefix)]


class WakeWord:
    async def detections(self):
        if False:
            yield ""

    async def suspend(self):
        return None

    async def suspend_for_active_session(self):
        return None

    async def resume(self):
        return None

    async def close(self):
        return None


class Core:
    """Faux Core : le canal vocal est le vrai service ; toute autre méthode appelée est notée (et ne doit pas l'être)."""

    def __init__(self) -> None:
        self.service = VoiceChannelService()
        self.service.started_at -= 10.0  # hors période de grâce
        self.reports: list[dict] = []
        self.failure: BaseException | None = None
        self.delay_s = 0.0
        self.other_calls: list[str] = []

    async def voice_channel_report(self, payload, *, timeout_s):
        self.reports.append(payload)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.failure is not None:
            raise self.failure
        return self.service.report(payload)

    async def create_conversation(self):
        return {"id": "conv-1"}

    async def current_session(self):  # activation seulement : un Core sans Sessions
        from jarvis.protocol.client import CoreProtocolError
        raise CoreProtocolError(404, "session_not_found", "no session")

    async def context(self, conversation_id):
        return {}

    async def close(self):
        return None

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        async def recorded(*args, **kwargs):
            self.other_calls.append(name)
            raise AssertionError(f"Core.{name} must not be called by the voice channel")

        return recorded


def runtime(core: Core, journal: Journal, realtime_factory=None) -> PersistentVoiceRuntime:
    async def no_provider(_context):
        raise RuntimeError("no provider in this test")

    return PersistentVoiceRuntime(wakeword=WakeWord(), core=core, realtime_factory=realtime_factory or no_provider,
                                  journal=journal, voice_arch=VoiceArchitecture.LEGACY)


def count_mutes(voice: PersistentVoiceRuntime, effect=None) -> list[object]:
    calls: list[object] = []
    original = voice.mute

    async def mute(reason=None):
        calls.append(reason)
        if effect is not None:
            return await effect()
        return await original(reason)

    voice.mute = mute  # type: ignore[method-assign]
    return calls


def request_disable(core: Core) -> str:
    status, body = core.service.disable({"client_request_id": str(uuid.uuid4())})
    assert status == 202
    return body["request_id"]


async def test_reports_carry_one_incarnation_and_a_strictly_increasing_seq():
    core, journal = Core(), Journal()
    voice = runtime(core, journal)
    channel = app.VoiceChannelReporting()
    for _ in range(3):
        await app._report_voice_channel(voice, journal, channel)
    assert [r["seq"] for r in core.reports] == [1, 2, 3]
    assert {r["voice_incarnation_id"] for r in core.reports} == {voice.voice_incarnation_id}
    assert voice.voice_incarnation_id.startswith("voice-")
    assert core.reports[0]["lifecycle_state"] == "background"
    assert core.service.write_gate() is None
    assert runtime(Core(), journal).voice_incarnation_id != voice.voice_incarnation_id


async def test_a_request_mutes_once_then_acknowledges_and_unlocks_the_chat():
    core, journal = Core(), Journal()
    voice = runtime(core, journal)
    voice.runtime.state = VoiceLifecycleState.ACTIVE
    mutes = count_mutes(voice)
    channel = app.VoiceChannelReporting()
    brain_work = asyncio.create_task(asyncio.sleep(60), name="long-brain-work")
    subagent = asyncio.create_task(asyncio.sleep(60), name="sub-agent")
    try:
        await app._report_voice_channel(voice, journal, channel)
        assert core.service.write_gate() == "voice_active"
        request_id = request_disable(core)
        assert core.service.write_gate() == "voice_switching"

        await app._report_voice_channel(voice, journal, channel)  # demande reçue -> mute -> ack immédiat
        await app._report_voice_channel(voice, journal, channel)  # même demande : pas de second mute
        await app._report_voice_channel(voice, journal, channel)

        assert [getattr(r, "value", r) for r in mutes] == ["user"]
        assert voice.runtime.state is VoiceLifecycleState.BACKGROUND
        acks = [r["ack"] for r in core.reports if r["ack"] is not None]
        assert acks == [{"request_id": request_id, "result": "accepted", "code": None}]
        assert core.service.write_gate() is None
        assert core.service.snapshot()["voice"]["request"]["status"] == "accepted"
        assert channel.pending_ack is None
        # Le Brain et les sous-agents continuent ; Core n'est appelé que pour le canal.
        assert not brain_work.done() and not subagent.done()
        assert core.other_calls == []
        assert journal.kinds() == ["voice.channel.disable_accepted"]
    finally:
        brain_work.cancel()
        subagent.cancel()


async def test_a_mute_that_raises_is_acknowledged_failed():
    core, journal = Core(), Journal()
    voice = runtime(core, journal)
    voice.runtime.state = VoiceLifecycleState.ACTIVE

    async def broken():
        raise OSError("device busy")

    mutes = count_mutes(voice, broken)
    channel = app.VoiceChannelReporting()
    await app._report_voice_channel(voice, journal, channel)
    request_id = request_disable(core)
    await app._report_voice_channel(voice, journal, channel)
    await app._report_voice_channel(voice, journal, channel)

    assert len(mutes) == 1
    assert [r["ack"] for r in core.reports if r["ack"]] == [
        {"request_id": request_id, "result": "failed", "code": "voice_disable_failed"}]
    request = core.service.snapshot()["voice"]["request"]
    assert (request["status"], request["code"]) == ("failed", "voice_disable_failed")
    assert core.service.write_gate() == "voice_active"  # reste verrouillé, rien de perdu
    failed = [e for e in journal.events if e["kind"] == "voice.channel.disable_failed"]
    assert failed and failed[0]["data"]["exception_type"] == "OSError"


async def test_a_mute_that_leaves_error_is_acknowledged_failed():
    core, journal = Core(), Journal()
    voice = runtime(core, journal)
    voice.runtime.state = VoiceLifecycleState.ACTIVE

    async def stuck():
        voice.runtime.state = VoiceLifecycleState.ERROR

    count_mutes(voice, stuck)
    channel = app.VoiceChannelReporting()
    await app._report_voice_channel(voice, journal, channel)
    request_disable(core)
    await app._report_voice_channel(voice, journal, channel)
    assert core.service.snapshot()["voice"]["request"]["status"] == "failed"
    assert core.service.write_gate() == "voice_error"


async def test_already_in_background_acknowledges_without_muting():
    core, journal = Core(), Journal()
    voice = runtime(core, journal)
    voice.runtime.state = VoiceLifecycleState.ACTIVE
    channel = app.VoiceChannelReporting()
    await app._report_voice_channel(voice, journal, channel)
    request_id = request_disable(core)
    voice.runtime.state = VoiceLifecycleState.BACKGROUND  # mute par la touche entre-temps
    mutes = count_mutes(voice)
    assert core.service.write_gate() == "voice_switching"  # demande toujours en attente côté Core
    # Le rapport `background` conclut déjà la demande : Voice ne la reçoit plus et ne coupe rien.
    await app._report_voice_channel(voice, journal, channel)
    assert mutes == []
    assert core.service.snapshot()["voice"]["request"] == {"request_id": request_id, "status": "accepted",
                                                            "code": None}


async def test_core_unreachable_never_raises_and_is_journaled_once_per_episode():
    core, journal = Core(), Journal()
    voice = runtime(core, journal)
    channel = app.VoiceChannelReporting()
    core.failure = ConnectionRefusedError("core down")
    for _ in range(3):
        await app._report_voice_channel(voice, journal, channel)
    assert journal.kinds() == ["voice.channel.report_failed"]
    core.failure = None
    await app._report_voice_channel(voice, journal, channel)
    core.failure = asyncio.TimeoutError()
    await app._report_voice_channel(voice, journal, channel)
    await app._report_voice_channel(voice, journal, channel)
    assert journal.kinds() == ["voice.channel.report_failed", "voice.channel.report_restored",
                               "voice.channel.report_failed"]
    assert all(e["level"] == "warning" for e in journal.events if e["kind"] == "voice.channel.report_failed")


async def test_an_ack_that_could_not_be_delivered_is_resent():
    core, journal = Core(), Journal()
    voice = runtime(core, journal)
    voice.runtime.state = VoiceLifecycleState.ACTIVE
    count_mutes(voice)
    channel = app.VoiceChannelReporting()
    await app._report_voice_channel(voice, journal, channel)
    request_id = request_disable(core)

    real = core.voice_channel_report

    async def drop_acks(payload, *, timeout_s):
        if payload["ack"] is not None and core.failure is None:
            core.failure = ConnectionResetError("lost")
            core.reports.append(payload)
            raise core.failure
        return await real(payload, timeout_s=timeout_s)

    core.voice_channel_report = drop_acks  # type: ignore[method-assign]
    await app._report_voice_channel(voice, journal, channel)
    assert channel.pending_ack == {"request_id": request_id, "result": "accepted", "code": None}
    core.failure = None
    core.voice_channel_report = real  # type: ignore[method-assign]
    await app._report_voice_channel(voice, journal, channel)
    assert channel.pending_ack is None
    assert core.service.snapshot()["voice"]["request"]["status"] == "accepted"


async def test_a_voice_without_channel_support_is_skipped():
    class Bare:
        pass

    await app._report_voice_channel(Bare(), None, app.VoiceChannelReporting())


async def test_connecting_is_reported_before_the_microphone_opens():
    core, journal = Core(), Journal()
    seen: list[str] = []

    async def factory(_context):
        seen.append(core.service.snapshot()["voice"]["state"])
        raise RuntimeError("stop before the provider")

    voice = runtime(core, journal, factory)
    with pytest.raises(RuntimeError):
        await voice.activate()
    assert core.reports[0]["lifecycle_state"] == "connecting"
    assert seen == ["connecting"]


async def test_a_slow_core_delays_activation_at_most_half_a_second():
    core, journal = Core(), Journal()
    core.delay_s = 5.0
    reached: list[float] = []

    async def factory(_context):
        reached.append(time.monotonic())
        raise RuntimeError("stop before the provider")

    voice = runtime(core, journal, factory)
    start = time.monotonic()
    with pytest.raises(RuntimeError):
        await voice.activate()
    assert reached and reached[0] - start < 1.5
    assert journal.kinds() == ["voice.channel.report_failed"]


async def test_the_supervision_loop_switches_to_chat_within_two_seconds():
    core, journal = Core(), Journal()
    voice = runtime(core, journal)
    voice.runtime.state = VoiceLifecycleState.ACTIVE
    mutes = count_mutes(voice)

    class Signals:
        def heartbeat(self):
            return None

    core.service.report(voice.voice_channel_report())
    request_disable(core)
    started = time.monotonic()
    loop = asyncio.create_task(app._voice_timeout_loop(voice, Signals(), journal))
    try:
        while core.service.write_gate() is not None and time.monotonic() - started < 3.0:
            await asyncio.sleep(0.05)
        elapsed = time.monotonic() - started
    finally:
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)
    assert core.service.write_gate() is None and elapsed <= 2.0
    assert len(mutes) == 1
    assert core.other_calls == []

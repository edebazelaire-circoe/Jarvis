"""Voice prend sa conversation dans la Session Core ouverte (handoff board-session, Slice 03).

À l'activation, `PersistentVoiceRuntime` lit `GET /v1/sessions/current` et
utilise `binding.conversation_id` ; le pointeur `.voice_conversation` n'est
plus qu'un cache, relu seulement face à un Core sans Sessions. Même style que
`test_v2_voice_toggle.py` : le fournisseur Realtime lève juste après avoir reçu
son contexte, ce qui arrête l'activation au point observé.
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.voice_switch import VoiceSwitchBus
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture

TOKEN = "t" * 48


class FakeWakeWord:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False

    async def detections(self):
        while not self.closed:
            yield await self.queue.get()

    async def suspend(self) -> None:
        return None

    async def suspend_for_active_session(self) -> None:
        return None

    async def resume(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})

    def kinds(self) -> list[str]:
        return [str(event["kind"]) for event in self.events]


class PointerCore:
    """Core sans Sessions (ou double ancien) : seulement conversations et contexte."""

    def __init__(self) -> None:
        self.created = 0
        self.contexts: list[str] = []

    async def create_conversation(self) -> dict[str, str]:
        self.created += 1
        return {"id": f"created-{self.created}"}

    async def context(self, conversation_id: str) -> dict[str, object]:
        self.contexts.append(conversation_id)
        return {"conversation_id": conversation_id}

    async def close(self) -> None:
        return None


class SessionCore(PointerCore):
    def __init__(self, conversation_id: str = "bound-conversation") -> None:
        super().__init__()
        self.conversation_id = conversation_id
        self.reads = 0

    async def current_session(self) -> dict[str, object]:
        self.reads += 1
        return {"session": {"jarvis_session_id": "jsess_" + "a" * 32},
                "binding": {"jarvis_session_id": "jsess_" + "a" * 32, "board_id": "default",
                            "conversation_id": self.conversation_id}}


class OldCore(PointerCore):
    """Core d'avant les Sessions : la route n'existe pas, aiohttp répond 404 en texte."""

    async def current_session(self) -> dict[str, object]:
        raise CoreProtocolError(404, "http_error", "Not Found")


def _runtime(core, journal, *, initial=None, switch_bus=None) -> tuple[PersistentVoiceRuntime, list]:
    contexts: list[dict[str, object]] = []

    async def realtime_factory(context):
        contexts.append(context)
        raise RuntimeError("stop after context")

    runtime = PersistentVoiceRuntime(
        wakeword=FakeWakeWord(), core=core, realtime_factory=realtime_factory, journal=journal,
        voice_arch=VoiceArchitecture.LEGACY, initial_conversation_id=initial,
        switch_bus=switch_bus, configuration_id="cfg-1" if switch_bus is not None else None,
    )
    return runtime, contexts


async def _activate(runtime: PersistentVoiceRuntime) -> None:
    with pytest.raises(RuntimeError, match="stop after context"):
        await runtime.activate()


async def test_activation_uses_the_current_session_binding_over_the_pointer(tmp_path):
    bus = VoiceSwitchBus(tmp_path)
    bus.remember_conversation("stale-pointer", "cfg-1")
    core, journal = SessionCore(), RecordingJournal()
    runtime, contexts = _runtime(core, journal, initial=bus.conversation_id(), switch_bus=bus)
    await _activate(runtime)
    assert runtime.runtime.conversation_id == "bound-conversation"
    assert core.contexts == ["bound-conversation"] and core.created == 0
    assert contexts == [{"conversation_id": "bound-conversation"}]
    assert bus.conversation_id() == "bound-conversation"  # le pointeur reste écrit, comme cache
    assert {"voice.session.selected", "voice.session.rebound"} <= set(journal.kinds())


async def test_each_activation_rereads_the_session(tmp_path):
    core, journal = SessionCore(), RecordingJournal()
    runtime, _ = _runtime(core, journal)
    await _activate(runtime)
    runtime.runtime.state = runtime.runtime.state.__class__.BACKGROUND
    core.conversation_id = "after-new-session"
    await _activate(runtime)
    assert core.reads == 2 and runtime.runtime.conversation_id == "after-new-session"


@pytest.mark.parametrize("core_type", [OldCore, PointerCore])
async def test_a_core_without_sessions_falls_back_to_the_pointer(tmp_path, core_type):
    bus = VoiceSwitchBus(tmp_path)
    bus.remember_conversation("remembered", "cfg-1")
    core, journal = core_type(), RecordingJournal()
    runtime, _ = _runtime(core, journal, initial=bus.conversation_id(), switch_bus=bus)
    await _activate(runtime)
    assert runtime.runtime.conversation_id == "remembered"
    assert core.contexts == ["remembered"] and core.created == 0
    if core_type is OldCore:
        assert "voice.session.unsupported" in journal.kinds()


async def test_a_core_without_sessions_and_no_pointer_creates_a_conversation():
    core, journal = OldCore(), RecordingJournal()
    runtime, _ = _runtime(core, journal)
    await _activate(runtime)
    assert runtime.runtime.conversation_id == "created-1"


async def test_a_session_refusal_other_than_404_is_not_bypassed():
    class Busy(SessionCore):
        async def current_session(self):
            raise CoreProtocolError(503, "core_unavailable", "core is not ready")

    core = Busy()
    runtime, contexts = _runtime(core, RecordingJournal(), initial="remembered")
    with pytest.raises(CoreProtocolError):
        await runtime.activate()
    assert not contexts and core.contexts == []


async def test_a_core_with_no_open_session_falls_back_to_the_pointer():
    class NoSession(SessionCore):
        async def current_session(self):
            raise CoreProtocolError(404, "session_not_found", "no session is open")

    core, journal = NoSession(), RecordingJournal()
    runtime, _ = _runtime(core, journal, initial="remembered")
    await _activate(runtime)
    assert runtime.runtime.conversation_id == "remembered"
    assert "voice.session.unsupported" in journal.kinds()


async def test_a_damaged_store_binding_not_found_is_raised_never_bypassed():
    """404 `binding_not_found` : Board actif sans liaison, base abîmée. Jamais comblé par le pointeur."""

    class Damaged(SessionCore):
        async def current_session(self):
            raise CoreProtocolError(404, "binding_not_found", "session has no binding for its active board")

    core = Damaged()
    runtime, contexts = _runtime(core, RecordingJournal(), initial="remembered")
    with pytest.raises(CoreProtocolError) as raised:
        await runtime.activate()
    assert raised.value.code == "binding_not_found"
    assert not contexts and core.contexts == []


async def test_a_malformed_session_answer_is_refused():
    class Broken(SessionCore):
        async def current_session(self):
            return {"session": {}, "binding": {}}

    runtime, contexts = _runtime(Broken(), RecordingJournal())
    with pytest.raises(ValueError, match="conversation_id"):
        await runtime.activate()
    assert not contexts


async def test_activation_against_a_real_core_picks_the_session_conversation(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        bus = VoiceSwitchBus(tmp_path / "runtime")
        runtime, contexts = _runtime(client, RecordingJournal(), switch_bus=bus)
        await _activate(runtime)
        expected = (await core.sessions.current()).binding.conversation_id
        assert runtime.runtime.conversation_id == expected == bus.conversation_id()
        assert contexts and contexts[0]["conversation_id"] == expected
        # Nouvelle Session : l'activation suivante suit la nouvelle liaison.
        _, view = await core.sessions.start_new_session()
        runtime.runtime.state = runtime.runtime.state.__class__.BACKGROUND
        await _activate(runtime)
        assert runtime.runtime.conversation_id == view.binding.conversation_id != expected
    finally:
        await client.close()
        await server.stop()
        await core.stop()

"""Barge-in Solo Owner : seule la confirmation locale du propriétaire coupe JARVIS (tâche 05).

Handoff `tasks/jarvis_solo_owner_duplex_handoff/`, D04, D05, D09. Ce fichier
prouve, pour l'autorité `BargeInAuthority.OWNER` :

- qu'une parole proche quelconque ne baisse ni ne coupe la voix de JARVIS ;
- que le propriétaire confirmé coupe localement, avant tout appel fournisseur,
  que le `speech_started` du fournisseur arrive avant, après ou jamais — et
  sans jamais couper deux fois ;
- qu'un `speech_started` seul (une autre voix) ne coupe rien ;
- que les états périmés ou d'une autre session sont écartés ;
- qu'une annulation ou une troncature refusée ne fait pas tomber Voice ;
- qu'un réglage `open_room` rend exactement le comportement acoustique d'avant.

Les tests de salle ouverte (`test_v2_barge_in.py`, `test_voice_duplex.py`)
restent inchangés : ils sont la preuve de non-régression.
"""

from __future__ import annotations

import asyncio
import base64
import math
import threading

import numpy as np
import pytest

from jarvis.adapters.fake_speaker_verifier import ScriptedSpeakerVerifier
from jarvis.audio.duplex import CaptureProcessor
from jarvis.audio.speaker_shadow import SpeakerVerificationWorker
from jarvis.domain.speaker import (
    ConversationAuthorization,
    ConversationMode,
    OwnerState,
    OwnerStateSnapshot,
    SpeakerVerificationMode,
    VerifierAvailability,
)
from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.runtime.realtime_audio import (
    BARGE_IN_AUTHORITY_KIND,
    BARGE_IN_OWNER_CONFIRMED_KIND,
    BARGE_IN_PROVIDER_ADVISORY_KIND,
    NEAR_END_SIGNAL,
    BargeInAuthority,
    RealtimeConversationBridge,
    SoundDeviceRealtimeAudio,
)
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture

CONVERSATION = "conv-owner"
RATE = 24000
TIMEOUT_S = 2.0
SOLO_OWNER = ConversationAuthorization(mode=ConversationMode.SOLO_OWNER, verification=SpeakerVerificationMode.ENFORCE)


# --------------------------------------------------------------------------
# Outillage


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})

    def of(self, kind: str) -> list[dict[str, object]]:
        return [event for event in self.events if event["kind"] == kind]

    def count(self, kind: str) -> int:
        return len(self.of(kind))


class RecordingCore:
    def __init__(self) -> None:
        self.brain_turns: list[dict[str, object]] = []
        self.turns: list[dict[str, object]] = []
        self.tool_calls: list[str] = []

    async def submit_brain_turn(self, conversation_id: str, *, content: str, correlation_id: str, source: str = "realtime", addressing: str = "addressed", provider_item_id=None, interrupted_speech_id=None):  # noqa: ANN001,E501
        self.brain_turns.append({"content": content, "interrupted_speech_id": interrupted_speech_id})
        return {"turn_id": f"turn-{len(self.brain_turns)}", "revision": len(self.brain_turns), "duplicate": False}

    async def append_turn(self, conversation_id: str, *, kind: str, content: str, correlation_id=None, metadata=None):  # noqa: ANN001
        self.turns.append({"kind": kind, "content": content})
        return {"id": f"turn-{len(self.turns)}"}

    async def call_tool(self, name: str, arguments: dict[str, object], *, conversation_id: str) -> dict[str, object]:
        self.tool_calls.append(name)
        return {"ok": True}


class ControllableSession:
    def __init__(self, calls: list[str] | None = None) -> None:
        self.calls = calls if calls is not None else []
        self.cancel_error: Exception | None = None
        self.truncate_error: Exception | None = None

    async def send_audio(self, pcm: bytes) -> None:
        del pcm

    async def finish_input(self) -> bool:
        return True

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        del call_id, result

    async def send_context(self, text: str) -> None:
        del text

    async def events(self):  # pragma: no cover - les tests injectent les évènements
        return
        yield

    async def close(self) -> None:
        return None

    async def speak(self, request) -> str:  # noqa: ANN001
        del request
        return "out-x"

    async def cancel_output(self, cursor=None) -> None:  # noqa: ANN001
        self.calls.append("cancel_output")
        if self.cancel_error is not None:
            raise self.cancel_error

    async def truncate(self, cursor) -> None:  # noqa: ANN001
        self.calls.append("truncate")
        if self.truncate_error is not None:
            raise self.truncate_error


class FakeCapture:
    """Ce que le bridge lit de la capture duplex : l'horloge du flux."""

    def __init__(self, stream_ms: int) -> None:
        self.stream_ms = stream_ms

    def clear_reference(self) -> None:
        return None


class RecordingAudio(SoundDeviceRealtimeAudio):
    """Audio sans périphérique : gain, arrêts et garde d'écho observables."""

    def __init__(self, calls: list[str] | None = None, *, guarded: bool = False, gate_open: bool = True) -> None:
        super().__init__()
        self.calls = calls if calls is not None else []
        self.guarded = guarded
        self.gate_open = gate_open
        self.gains: list[float] = []
        self.released = 0
        self.stop_output_calls = 0
        self.fake_capture: FakeCapture | None = None
        # Lecture retenue : le premier bloc attend ce feu vert (audio en file).
        self.hold: asyncio.Event | None = None

    @property
    def has_echo_guard(self) -> bool:
        return self.guarded

    @property
    def echo_guard_open(self) -> bool:
        return self.gate_open

    @property
    def far_end_recent(self) -> bool:
        return False

    def release_near_end(self) -> None:
        self.released += 1

    def set_output_gain(self, gain: float) -> None:
        self.gains.append(gain)
        super().set_output_gain(gain)

    async def play_b64(self, value: str) -> None:
        if self.hold is not None:
            await self.hold.wait()
        self._credit_written(self._output_epoch, len(base64.b64decode(value)))

    async def stop_output(self) -> None:
        self.stop_output_calls += 1
        self.calls.append("stop_output")
        await super().stop_output()

    async def close(self) -> None:
        return None


class FakeOwnerSource:
    """`OwnerStateSource` pilotable : publie depuis un autre fil, comme le vérificateur."""

    def __init__(self, baseline: OwnerStateSnapshot | None = None) -> None:
        self.availability = VerifierAvailability.READY
        self.owner_state = baseline or OwnerStateSnapshot()
        self.listeners: list = []

    def add_owner_listener(self, listener):  # noqa: ANN001, ANN201
        self.listeners.append(listener)

        def remove() -> None:
            if listener in self.listeners:
                self.listeners.remove(listener)

        return remove

    def publish(self, snapshot: OwnerStateSnapshot) -> None:
        self.owner_state = snapshot

        def run() -> None:
            for listener in list(self.listeners):
                listener(snapshot)

        thread = threading.Thread(target=run, name="fake-speaker-verifier")
        thread.start()
        thread.join()


def snapshot(
    sequence: int,
    *,
    state: OwnerState = OwnerState.OWNER_CONFIRMED,
    session: int = 1,
    far_end: bool = True,
    onset: int = 1500,
    confirmed: int = 1700,
) -> OwnerStateSnapshot:
    owner = state is OwnerState.OWNER_CONFIRMED
    return OwnerStateSnapshot(
        sequence=sequence,
        session=session,
        state=state,
        stream_ms=confirmed,
        candidate_onset_ms=None if state is OwnerState.IDLE else onset,
        owner_onset_ms=onset if owner else None,
        confirmed_ms=confirmed if owner else None,
        owner_score=0.91 if state in {OwnerState.OWNER_CONFIRMED, OwnerState.REJECTED} else None,
        evidence_ms=1500,
        far_end=far_end,
    )


def event(message_type: str, **payload: object) -> ProtocolEnvelope:
    return ProtocolEnvelope(message_type=message_type, payload=payload)


def audio_delta(chunks: int, **payload: object) -> ProtocolEnvelope:
    pcm = base64.b64encode(b"\x01\x00" * (SoundDeviceRealtimeAudio.OUTPUT_CHUNK_FRAMES * chunks)).decode()
    return event("realtime.audio", pcm_b64=pcm, **payload)


def build_bridge(
    audio,  # noqa: ANN001
    *,
    source=None,  # noqa: ANN001
    session=None,  # noqa: ANN001
    core=None,  # noqa: ANN001
    journal=None,  # noqa: ANN001
    authority: BargeInAuthority = BargeInAuthority.OWNER,
    **options,  # noqa: ANN003
) -> RealtimeConversationBridge:
    return RealtimeConversationBridge(
        core=core or RecordingCore(),
        session=session or ControllableSession(),
        conversation_id=CONVERSATION,
        audio=audio,
        on_addressed=lambda: None,
        on_mute=lambda: None,
        auto_turn=True,
        continuous=True,
        journal=journal,
        barge_in_authority=authority,
        owner_source=source,
        **options,
    )


async def until(predicate, *, timeout: float = TIMEOUT_S) -> None:  # noqa: ANN001
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition jamais atteinte")


class Live:
    """Un bridge qui consomme un flux fournisseur alimenté au fil du test."""

    def __init__(self, bridge: RealtimeConversationBridge) -> None:
        self.bridge = bridge
        self.queue: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "Live":
        async def stream():
            while (item := await self.queue.get()) is not None:
                yield item

        self.task = asyncio.create_task(self.bridge._consume(stream()))
        await asyncio.sleep(0)
        return self

    async def send(self, *events: ProtocolEnvelope) -> None:
        for item in events:
            await self.queue.put(item)
            await self.idle()

    async def idle(self) -> None:
        # Laisser le lecteur (ou un rappel `call_soon_threadsafe`) déposer
        # l'élément, puis attendre qu'il soit traité — audio joué compris.
        for _ in range(3):
            await asyncio.sleep(0)
        await self.bridge.wait_idle()

    async def __aexit__(self, *exc_info) -> None:  # noqa: ANN002
        await self.queue.put(None)
        assert self.task is not None
        await asyncio.wait_for(self.task, timeout=TIMEOUT_S)


def jarvis_speaking(output: str = "out-1", speech: str = "speech-1", chunks: int = 2) -> list[ProtocolEnvelope]:
    return [
        event("realtime.output_started", output_id=output, speech_id=speech, response_id="resp-1"),
        audio_delta(chunks, output_id=output, speech_id=speech, response_id="resp-1", item_id="item-1"),
    ]


# --------------------------------------------------------------------------
# 1. Une autre voix ne baisse ni ne coupe JARVIS


async def test_non_owner_near_end_neither_ducks_nor_cuts_jarvis():
    """D04 : la parole proche n'est qu'un candidat, le volume ne bouge pas d'un cran."""

    audio, source, journal = RecordingAudio(), FakeOwnerSource(), RecordingJournal()
    session = ControllableSession()
    bridge = build_bridge(audio, source=source, session=session, journal=journal, barge_in_confirm_s=0.05)

    async with Live(bridge) as live:
        await live.send(*jarvis_speaking())
        assert bridge._playing
        bridge._on_capture_signal(NEAR_END_SIGNAL)
        await live.idle()
        # Le vérificateur juge : ce n'est pas le propriétaire.
        source.publish(snapshot(1, state=OwnerState.CANDIDATE))
        source.publish(snapshot(2, state=OwnerState.REJECTED))
        await live.idle()
        # Faute de confirmation acoustique, la garde se referme — sans rien au volume.
        await until(lambda: journal.count("voice.barge_in_rejected") == 1)

    assert audio.gains == []
    assert audio.stop_output_calls == 0 and session.calls == []
    assert journal.count("voice.barge_in") == 0
    assert journal.of("voice.barge_in_pending")[0]["data"]["authority"] == "owner"
    rejected = journal.of("voice.barge_in_rejected")[0]["data"]
    assert rejected["authority"] == "owner" and rejected["code"] == "barge_in_not_confirmed"
    assert audio.released == 1  # le détecteur apprend l'écho, comme en salle ouverte


async def test_provider_speech_alone_never_cuts_jarvis():
    """D09 : le VAD du fournisseur entend toute voix ; sans propriétaire, il ne coupe rien."""

    audio, source, journal = RecordingAudio(guarded=True, gate_open=True), FakeOwnerSource(), RecordingJournal()
    session = ControllableSession()
    bridge = build_bridge(audio, source=source, session=session, journal=journal, barge_in_confirm_s=0.05)

    async with Live(bridge) as live:
        await live.send(*jarvis_speaking())
        bridge._on_capture_signal(NEAR_END_SIGNAL)
        await live.idle()
        await live.send(event("realtime.speech_started", item_id="item-voisin"))
        # Le délai acoustique est passé : la parole était réelle, la garde reste ouverte.
        await asyncio.sleep(0.12)
        await live.idle()

    assert audio.stop_output_calls == 0 and session.calls == []
    assert audio.gains == [] and audio.released == 0
    assert journal.count("voice.barge_in") == 0 and journal.count("voice.barge_in_ignored") == 0
    advisory = journal.of(BARGE_IN_PROVIDER_ADVISORY_KIND)
    assert [item["data"]["relation"] for item in advisory] == ["awaiting_owner"]
    assert advisory[0]["data"]["owner_state"] == "idle" and advisory[0]["data"]["guard_open"] is True


async def test_provider_speech_behind_a_closed_guard_does_not_cut_either():
    audio, journal = RecordingAudio(guarded=True, gate_open=False), RecordingJournal()
    bridge = build_bridge(audio, source=FakeOwnerSource(), journal=journal)

    async with Live(bridge) as live:
        await live.send(*jarvis_speaking(), event("realtime.speech_started"))

    assert audio.stop_output_calls == 0
    assert journal.of(BARGE_IN_PROVIDER_ADVISORY_KIND)[0]["data"]["guard_open"] is False


# --------------------------------------------------------------------------
# 2. Le propriétaire confirmé coupe localement, fournisseur ou pas


async def test_owner_confirmation_stops_jarvis_without_any_provider_event():
    """Arrêt local d'abord, annulation et troncature ensuite ; le fournisseur n'a rien dit."""

    calls: list[str] = []
    audio, source, journal = RecordingAudio(calls), FakeOwnerSource(), RecordingJournal()
    audio.fake_capture = FakeCapture(stream_ms=2100)
    audio.capture = audio.fake_capture  # type: ignore[assignment]
    session, core = ControllableSession(calls), RecordingCore()
    interruptions: list[object] = []
    bridge = build_bridge(audio, source=source, session=session, core=core, journal=journal)
    bridge.on_interruption = interruptions.append

    async with Live(bridge) as live:
        await live.send(*jarvis_speaking(chunks=3))
        source.publish(snapshot(1, onset=1500, confirmed=1700))
        await until(lambda: journal.count("voice.barge_in") == 1)
        await live.send(event("realtime.transcript", text="Jarvis, attends, lis-moi plutôt mes messages.", item_id="item-u"))

    assert calls == ["stop_output", "cancel_output", "truncate"]
    assert audio.stop_output_calls == 1
    assert journal.of("voice.barge_in")[0]["data"]["trigger"] == "owner"
    data = journal.of(BARGE_IN_OWNER_CONFIRMED_KIND)[0]["data"]
    assert (data["owner_onset_ms"], data["confirmed_ms"], data["stop_stream_ms"]) == (1500, 1700, 2100)
    assert (data["confirm_ms"], data["confirm_to_stop_ms"], data["onset_to_stop_ms"]) == (200, 400, 600)
    assert data["provider_speech_started"] is False and data["provider_lead_ms"] is None
    assert data["speech_id"] == "speech-1" and data["played_ms"] == 300
    # Scalaires seulement : ni audio, ni empreinte.
    assert all(value is None or isinstance(value, (int, float, str, bool)) for value in data.values())
    # L'interruption est marquée et portée par le tour suivant ; aucun travail annulé.
    assert interruptions and interruptions[0].speech_id == "speech-1"
    assert core.brain_turns[-1]["interrupted_speech_id"] == "speech-1"
    assert core.tool_calls == [] and core.turns == []


async def test_provider_speech_before_the_confirmation_never_cuts_twice():
    calls: list[str] = []
    audio, source, journal = RecordingAudio(calls), FakeOwnerSource(), RecordingJournal()
    clock = ManualClock()
    bridge = build_bridge(audio, source=source, session=ControllableSession(calls), journal=journal, clock=clock)

    async with Live(bridge) as live:
        await live.send(*jarvis_speaking())
        await live.send(event("realtime.speech_started", item_id="item-owner"))
        assert audio.stop_output_calls == 0  # pas encore de propriétaire : JARVIS continue
        clock.now += 0.9
        source.publish(snapshot(1))
        await until(lambda: audio.stop_output_calls == 1)
        await live.idle()
        # Nouveau segment du fournisseur pendant la même intervention.
        await live.send(event("realtime.speech_started", item_id="item-owner-2"))

    assert calls == ["stop_output", "cancel_output", "truncate"]
    data = journal.of(BARGE_IN_OWNER_CONFIRMED_KIND)[0]["data"]
    assert data["provider_speech_started"] is True and data["provider_lead_ms"] == 900


async def test_provider_speech_after_the_local_stop_is_correlated_not_recut():
    """L'audio reçu attend encore d'être jeté : `_output_live()` est vrai, rien n'est à recouper."""

    calls: list[str] = []
    audio, source, journal = RecordingAudio(calls), FakeOwnerSource(), RecordingJournal()
    audio.hold = asyncio.Event()
    clock = ManualClock()
    bridge = build_bridge(audio, source=source, session=ControllableSession(calls), journal=journal, clock=clock)

    async with Live(bridge) as live:
        await live.queue.put(event("realtime.output_started", output_id="out-1", speech_id="speech-1"))
        for _ in range(5):
            await live.queue.put(audio_delta(2, output_id="out-1", speech_id="speech-1", item_id="item-1"))
        await until(lambda: bridge._playing and bridge._queued_audio >= 4)
        source.publish(snapshot(1))
        await until(lambda: journal.count("voice.barge_in") == 1)
        assert bridge._output_live()  # des blocs condamnés attendent encore
        clock.now += 0.35
        await live.queue.put(event("realtime.speech_started", item_id="item-owner"))
        await until(lambda: journal.count(BARGE_IN_PROVIDER_ADVISORY_KIND) == 1)
        # Le propriétaire est confirmé une seconde fois dans la même intervention.
        source.publish(snapshot(2, state=OwnerState.REJECTED))
        source.publish(snapshot(3))
        audio.hold.set()
        await live.idle()

    assert audio.stop_output_calls == 1
    assert calls.count("cancel_output") == 1 and calls.count("truncate") == 1
    advisory = journal.of(BARGE_IN_PROVIDER_ADVISORY_KIND)[0]["data"]
    assert advisory["relation"] == "after_owner_stop" and advisory["lag_ms"] == 350


async def test_cancel_and_truncate_failures_do_not_kill_voice():
    audio, source, journal = RecordingAudio(), FakeOwnerSource(), RecordingJournal()
    session, core = ControllableSession(), RecordingCore()
    session.cancel_error = RuntimeError("socket busy")
    session.truncate_error = ValueError("no provider item to truncate")
    bridge = build_bridge(audio, source=source, session=session, core=core, journal=journal)

    async with Live(bridge) as live:
        await live.send(*jarvis_speaking())
        source.publish(snapshot(1))
        await until(lambda: journal.count("voice.barge_in") == 1)
        await live.send(
            event("realtime.error", error={"code": "invalid_value", "message": "Audio content of 200ms is already shorter"}),
            event("realtime.transcript", text="Jarvis, stop.", item_id="item-u"),
        )

    codes = {item["data"]["code"] for item in journal.of("voice.barge_in_degraded")}
    assert {"barge_in_cancel_failed", "barge_in_truncate_failed", "invalid_value"} <= codes
    assert journal.count("provider.error") == 0
    assert audio.stop_output_calls == 1
    assert core.brain_turns[-1]["content"] == "Jarvis, stop."  # la session a continué


# --------------------------------------------------------------------------
# 3. Ce qui ne doit rien couper


async def test_stale_and_foreign_session_snapshots_are_ignored():
    audio, journal = RecordingAudio(), RecordingJournal()
    source = FakeOwnerSource(baseline=snapshot(10, state=OwnerState.IDLE, session=3))
    bridge = build_bridge(audio, source=source, journal=journal)

    async with Live(bridge) as live:
        await live.send(*jarvis_speaking())
        source.publish(snapshot(9, session=3))  # publié avant ce bridge
        source.publish(snapshot(11, session=2))  # session précédente de la capture
        source.publish(snapshot(12, state=OwnerState.IDLE, session=3))
        source.publish(snapshot(12, session=3))  # séquence déjà vue
        await live.idle()
        assert audio.stop_output_calls == 0
        source.publish(snapshot(13, session=3))
        await until(lambda: audio.stop_output_calls == 1)

    assert journal.of(BARGE_IN_OWNER_CONFIRMED_KIND)[0]["data"]["sequence"] == 13


@pytest.mark.parametrize("case", ["never_spoke", "finished", "not_far_end"])
async def test_a_confirmation_while_jarvis_is_silent_stops_nothing(case):  # noqa: ANN001
    audio, source, journal = RecordingAudio(), FakeOwnerSource(), RecordingJournal()
    session = ControllableSession()
    bridge = build_bridge(audio, source=source, session=session, journal=journal)

    async with Live(bridge) as live:
        if case != "never_spoke":
            await live.send(*jarvis_speaking())
        if case == "finished":
            await live.send(event("realtime.response_done", status="completed", output_id="out-1", speech_id="speech-1"))
        source.publish(snapshot(1, far_end=case != "not_far_end"))
        await live.idle()

    assert audio.stop_output_calls == 0 and session.calls == []
    assert journal.count("voice.barge_in") == 0


# --------------------------------------------------------------------------
# 4. Autorité : bornes, repli explicite, retour arrière


def test_owner_authority_is_refused_without_a_source_or_outside_continuous():
    with pytest.raises(ValueError):
        build_bridge(RecordingAudio(), source=None)
    with pytest.raises(ValueError):
        RealtimeConversationBridge(
            core=RecordingCore(),
            session=ControllableSession(),
            conversation_id=CONVERSATION,
            audio=RecordingAudio(),
            on_addressed=lambda: None,
            on_mute=lambda: None,
            continuous=False,
            barge_in_authority=BargeInAuthority.OWNER,
            owner_source=FakeOwnerSource(),
        )


async def test_open_room_keeps_the_acoustic_barge_in_even_with_a_verifier():
    """Retour arrière : autorité acoustique, l'état du propriétaire n'est même pas écouté."""

    audio, source, journal = RecordingAudio(), FakeOwnerSource(), RecordingJournal()
    bridge = build_bridge(audio, source=source, journal=journal, authority=BargeInAuthority.ACOUSTIC,
                          barge_in_sustain_s=0.05)

    async with Live(bridge) as live:
        await live.send(*jarvis_speaking())
        assert source.listeners == []
        bridge._on_capture_signal(NEAR_END_SIGNAL)
        await live.idle()
        assert audio.gains == []
        await live.send(event("realtime.speech_started"))
        # Confirmée, la parole baisse la voix ; elle ne coupe que si elle dure
        # (17/09/2026 : l'écho de JARVIS se confirmait lui-même).
        assert audio.gains == [bridge.barge_in_duck_gain]
        await asyncio.sleep(0.15)
        await live.idle()

    assert audio.stop_output_calls == 1
    assert audio.gains == [bridge.barge_in_duck_gain, 1.0]
    assert "trigger" not in journal.of("voice.barge_in")[0]["data"]
    assert journal.of(BARGE_IN_AUTHORITY_KIND) == [] and journal.of(BARGE_IN_PROVIDER_ADVISORY_KIND) == []


async def test_a_verifier_failure_mid_session_fails_closed_and_ends_the_session():
    """Tâche 07 : plus de repli acoustique — rien ne baisse, rien ne coupe, la session se désactive en disant pourquoi."""

    audio, source, journal = RecordingAudio(), FakeOwnerSource(), RecordingJournal()
    refused: list[tuple[str, str]] = []
    mutes: list[bool] = []
    bridge = build_bridge(audio, source=source, journal=journal, on_authorization_refused=lambda *args: refused.append(args))
    bridge.on_mute = lambda: mutes.append(True)

    live = Live(bridge)
    async with live:
        await live.send(*jarvis_speaking())
        assert journal.of(BARGE_IN_AUTHORITY_KIND) == []  # prêt : rien à signaler
        source.availability = VerifierAvailability.FAILED
        bridge._on_capture_signal(NEAR_END_SIGNAL)
        await until(lambda: live.task.done())

    closed = journal.of(BARGE_IN_AUTHORITY_KIND)
    assert len(closed) == 1 and closed[0]["level"] == "warning"
    assert closed[0]["data"]["code"] == "owner_verifier_unavailable" and closed[0]["data"]["input"] == "closed"
    assert closed[0]["data"]["authority"] == "owner"  # jamais « acoustic »
    assert audio.gains == [] and audio.stop_output_calls == 0
    (event_,) = journal.of("voice.authorization_refused")
    assert event_["data"]["phase"] == "session" and event_["data"]["code"] == "owner_verifier_unavailable"
    assert refused and refused[0][0] == "owner_verifier_unavailable" and "open_room" in refused[0][1]
    assert mutes == [True]


async def test_the_owner_listener_is_released_with_the_session():
    source = FakeOwnerSource()
    bridge = build_bridge(RecordingAudio(), source=source)

    async with Live(bridge):
        assert len(source.listeners) == 1

    assert source.listeners == []
    source.publish(snapshot(1))  # après la session : sans effet, sans exception


# --------------------------------------------------------------------------
# 5. Chaîne réelle : capture duplex → fil du vérificateur → boucle


def _tone(seconds: float, *, amplitude: float, freq: float = 220.0) -> bytes:
    t = np.arange(int(RATE * seconds)) / RATE
    return (amplitude * np.sin(2 * math.pi * freq * t) * 32767).astype(np.int16).tobytes()


def _mix(*parts: bytes) -> bytes:
    arrays = [np.frombuffer(part, dtype=np.int16).astype(np.int32) for part in parts]
    total = np.zeros(max(len(array) for array in arrays), dtype=np.int32)
    for array in arrays:
        total[: len(array)] += array
    return total.clip(-32768, 32767).astype(np.int16).tobytes()


class _PassThroughCanceller:
    def process_render(self, frame: bytes) -> None:
        del frame

    def process_capture(self, frame: bytes) -> bytes:
        return frame


def _run_capture(processor: CaptureProcessor, mic: bytes, reference: bytes) -> None:
    """Comme PortAudio : blocs de 50 ms, référence en avance, dans un autre fil."""

    block, pushed = 1200 * 2, 0
    for offset in range(0, len(mic), block):
        while pushed < min(len(reference), offset + 4800 * 2):
            processor.push_reference(reference[pushed:pushed + 4800])
            pushed += 4800
        processor.process(mic[offset:offset + block])


async def test_the_real_verifier_worker_drives_the_owner_cut_end_to_end():
    """JARVIS parle 3 s ; le propriétaire le coupe à 1,5 s. Confirmé à 1,7 s, coupé aussitôt."""

    worker = SpeakerVerificationWorker(ScriptedSpeakerVerifier([0.99] * 40), sample_rate=RATE, max_pending_ms=60_000)
    # Forme de production : la capture duplex porte le tampon de rejeu, sans
    # lequel l'activation refuse Solo Owner (`solo_owner_capture_unsupported`).
    processor = CaptureProcessor(
        capture_rate=RATE, render_rate=RATE, canceller=_PassThroughCanceller(), observer=worker, owner_buffer_ms=2500
    )
    audio, journal = RecordingAudio(), RecordingJournal()
    audio.capture = processor
    silence = bytes(int(RATE * 1.5) * 2)
    mic = _mix(_tone(3.0, amplitude=0.02), silence + _tone(1.5, amplitude=0.4, freq=180.0))
    bridge = build_bridge(audio, source=worker, journal=journal)
    try:
        async with Live(bridge) as live:
            await live.send(*jarvis_speaking())
            await asyncio.to_thread(_run_capture, processor, mic, _tone(3.0, amplitude=0.3))
            assert await asyncio.to_thread(worker.flush, TIMEOUT_S)
            await until(lambda: audio.stop_output_calls == 1)
            await live.idle()
    finally:
        processor.close()

    assert audio.gains == []  # la parole proche n'a jamais touché au volume
    data = journal.of(BARGE_IN_OWNER_CONFIRMED_KIND)[0]["data"]
    assert (data["owner_onset_ms"], data["confirmed_ms"], data["confirm_ms"]) == (1500, 1700, 200)
    assert 1700 <= data["stop_stream_ms"] <= 3000
    assert data["onset_to_stop_ms"] == data["stop_stream_ms"] - 1500


# --------------------------------------------------------------------------
# 6. Runtime : l'autorité retenue à l'activation


class _Wake:
    async def close(self) -> None:
        return None


class _Capture:
    def __init__(self, observer=None, *, owner_buffer_ms: int = 2500) -> None:  # noqa: ANN001
        self.observer = observer
        self.owner_buffer_ms = owner_buffer_ms


def _runtime(*, authorization=None, arch=VoiceArchitecture.CONTINUOUS_BRAIN):  # noqa: ANN001, ANN202
    journal = RecordingJournal()
    runtime = PersistentVoiceRuntime(
        wakeword=_Wake(),  # type: ignore[arg-type]
        core=object(),  # type: ignore[arg-type]
        realtime_factory=None,  # type: ignore[arg-type]
        journal=journal,  # type: ignore[arg-type]
        auto_turn=True,
        voice_arch=arch,
        authorization=authorization,
    )
    return runtime, journal


def test_open_room_selects_the_acoustic_authority_silently():
    runtime, journal = _runtime()

    assert runtime._barge_in_policy(_Capture(FakeOwnerSource())) == (BargeInAuthority.ACOUSTIC, None)
    assert journal.events == []


def test_solo_owner_with_a_ready_verifier_selects_the_owner_authority():
    runtime, journal = _runtime(authorization=SOLO_OWNER)
    source = FakeOwnerSource()

    authority, selected = runtime._barge_in_policy(_Capture(source))

    assert (authority, selected) == (BargeInAuthority.OWNER, source)
    data = journal.of(BARGE_IN_AUTHORITY_KIND)[0]["data"]
    assert data["authority"] == "owner" and data["status"] == "ready" and data["availability"] == "ready"


@pytest.mark.parametrize(
    "capture,availability",
    [(None, "not_installed"), (_Capture(None), "not_installed"), ("failed", "failed")],
    ids=["no_capture", "no_verifier", "failed_verifier"],
)
def test_solo_owner_without_a_usable_verifier_is_refused_never_the_open_room(capture, availability):  # noqa: ANN001
    """Tâche 07 : le repli acoustique de la tâche 05 est remplacé par un refus."""

    from jarvis.domain.errors import ConfigurationError

    runtime, journal = _runtime(authorization=SOLO_OWNER)
    if capture == "failed":
        source = FakeOwnerSource()
        source.availability = VerifierAvailability.FAILED
        capture = _Capture(source)

    code, message, details = runtime._authorization_refusal(capture)
    assert code == "solo_owner_unavailable" and details == {"availability": availability}
    assert "open_room" in message
    # Jamais d'autorité acoustique en silence : sans source, lever ; avec une
    # source qui lâche après l'acceptation, l'autorité reste au propriétaire
    # et le bridge referme l'entrée (voir `test_a_verifier_failure_mid_session_…`).
    if availability == "failed":
        assert runtime._barge_in_policy(capture)[0] is BargeInAuthority.OWNER
    else:
        with pytest.raises(ConfigurationError):
            runtime._barge_in_policy(capture)
        assert journal.of(BARGE_IN_AUTHORITY_KIND) == []


def test_solo_owner_under_legacy_is_refused_and_says_why():
    runtime, journal = _runtime(authorization=SOLO_OWNER, arch=VoiceArchitecture.LEGACY)

    assert runtime._authorization_refusal(None)[0] == "solo_owner_requires_continuous_brain"


class ManualClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

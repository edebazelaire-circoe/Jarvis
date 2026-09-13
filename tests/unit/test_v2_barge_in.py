"""Séquence de barge-in côté surface (tâche 09c).

Ce fichier prouve les étapes 1 à 6 de la spec §12 : la parole de l'utilisateur
arrête la lecture locale **avant** tout aller-retour réseau, l'annulation et la
troncature partent avec le bon identifiant de sortie et le bon curseur, la
parole coupée est marquée telle quelle, le tour utilisateur suivant porte
`interrupted_speech_id`, et le travail en cours n'est pas touché.

Ce qui n'est **pas** prouvé ici, et ne peut l'être que sur poste réel : que le
son cesse effectivement dans les haut-parleurs, et en combien de millisecondes.
`abort()` est appelé sur un double ; PortAudio, lui, n'est pas dans la boucle.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import threading

from jarvis.core.brain_service import BrainOrchestrator
from jarvis.core.v2_services import ConversationService, CoreEventBus
from jarvis.domain.v2 import (
    SPEECH_DELIVERY_PARTIAL,
    PlaybackCursor,
    ProtocolEnvelope,
    SpeechKind,
    SpeechPriority,
    SpeechProvenance,
    SpeechRequest,
    TurnKind,
    utc_now,
)
from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
from jarvis.runtime.speech_scheduler import SpeechScheduler
from tests.fakes.speech_context import context as speech_context_payload, source as speech_source

CONVERSATION = "conv-barge-in"
CHUNK_FRAMES = SoundDeviceRealtimeAudio.OUTPUT_CHUNK_FRAMES
CHUNK_BYTES = CHUNK_FRAMES * SoundDeviceRealtimeAudio._BYTES_PER_FRAME
CHUNK_MS = 100  # 2400 trames à 24 kHz
TIMEOUT_S = 2.0


def pcm_b64(chunks: int) -> str:
    return base64.b64encode(b"\x01\x00" * (CHUNK_FRAMES * chunks)).decode()


class FakeOutputStream:
    """Flux de sortie qui dénonce toute libération pendant une écriture."""

    def __init__(self, *, block_first_write: threading.Event | None = None, latency: object = None) -> None:
        self.block_first_write = block_first_write
        self.latency = latency
        self.writes: list[bytes] = []
        self.writing = False
        self.aborted = 0
        self.started = 0
        self.stopped = 0
        self.closed = False
        self.freed_while_writing = False

    def write(self, pcm) -> None:  # noqa: ANN001
        self.writing = True
        try:
            if self.block_first_write is not None and not self.writes:
                assert self.block_first_write.wait(5), "l'écriture n'a jamais été libérée"
            self.writes.append(bytes(pcm))
        finally:
            self.writing = False

    def start(self) -> None:
        self.started += 1

    def abort(self, *, ignore_errors=True) -> None:
        self.aborted += 1
        self.freed_while_writing |= self.writing

    def stop(self, *, ignore_errors=True) -> None:
        self.stopped += 1
        self.freed_while_writing |= self.writing

    def close(self, *, ignore_errors=True) -> None:
        self.freed_while_writing |= self.writing
        self.closed = True


class FakeInputStream:
    """Micro : le barge-in ne doit jamais le fermer."""

    def __init__(self) -> None:
        self.stopped = False
        self.closed = False

    def stop(self, *, ignore_errors=True) -> None:
        self.stopped = True

    def abort(self, *, ignore_errors=True) -> None:
        self.stopped = True

    def close(self, *, ignore_errors=True) -> None:
        self.closed = True


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.changed = asyncio.Event()

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})
        self.changed.set()

    def count(self, kind: str) -> int:
        return sum(1 for event in self.events if event["kind"] == kind)

    def of(self, kind: str) -> list[dict[str, object]]:
        return [event for event in self.events if event["kind"] == kind]

    async def wait_until(self, predicate) -> None:  # noqa: ANN001
        while True:
            self.changed.clear()
            if predicate():
                return
            await asyncio.wait_for(self.changed.wait(), timeout=TIMEOUT_S)


class RecordingCore:
    """Core vu de la surface : ingress cerveau, tours, et flux d'évènements."""

    def __init__(self) -> None:
        self.brain_turns: list[dict[str, object]] = []
        self.turns: list[dict[str, object]] = []
        self.tool_calls: list[str] = []
        self.queue: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()
        self.current_speech_context = speech_context_payload(CONVERSATION)

    async def submit_brain_turn(
        self,
        conversation_id: str,
        *,
        content: str,
        correlation_id: str,
        source: str = "realtime",
        addressing: str = "addressed",
        provider_item_id=None,  # noqa: ANN001
        interrupted_speech_id=None,  # noqa: ANN001
    ) -> dict[str, object]:
        self.brain_turns.append(
            {
                "conversation_id": conversation_id,
                "content": content,
                "correlation_id": correlation_id,
                "source": source,
                "provider_item_id": provider_item_id,
                "interrupted_speech_id": interrupted_speech_id,
            }
        )
        return {"turn_id": f"turn-{len(self.brain_turns)}", "revision": len(self.brain_turns), "duplicate": False}

    async def append_turn(self, conversation_id: str, *, kind: str, content: str, correlation_id=None, metadata=None):  # noqa: ANN001
        self.turns.append(
            {
                "conversation_id": conversation_id,
                "kind": kind,
                "content": content,
                "correlation_id": correlation_id,
                "metadata": metadata or {},
            }
        )
        return {"id": f"turn-{len(self.turns)}"}

    async def call_tool(self, name: str, arguments: dict[str, object], *, conversation_id: str) -> dict[str, object]:
        del arguments, conversation_id
        self.tool_calls.append(name)
        return {"ok": True}

    async def speech_context(self, conversation_id: str):
        assert conversation_id == CONVERSATION
        return self.current_speech_context

    async def events(self, *, on_connected=None):
        if on_connected is not None:
            result = on_connected()
            if inspect.isawaitable(result):
                await result
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def publish(self, envelope: ProtocolEnvelope) -> None:
        if "current_speech_source" in envelope.payload:
            self.current_speech_context = {
                key: envelope.payload[key] for key in speech_context_payload(CONVERSATION)
            }
        await self.queue.put(envelope)


class ControllableSession:
    """Pile vocale de test qui implémente `RealtimeOutputControl`."""

    # These unit tests retain the compatibility history port. Canonical heard
    # evidence is exercised independently through the real facade/device tests.
    canonical_history = False

    def __init__(self) -> None:
        self.spoken: list[SpeechRequest] = []
        self.cancelled: list[PlaybackCursor | None] = []
        self.truncated: list[PlaybackCursor] = []
        self.active_output_id: str | None = None
        self.truncate_error: Exception | None = None
        self.calls: list[str] = []

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

    async def speak(self, request: SpeechRequest) -> str:
        self.spoken.append(request)
        output_id = f"out-{len(self.spoken)}"
        self.active_output_id = output_id
        return output_id

    async def speak_reserved(self, request: SpeechRequest, *, output_id: str) -> str:
        self.spoken.append(request)
        self.active_output_id = output_id
        return output_id

    async def invalidate_unstarted_output(self, output_id: str) -> None:
        if self.active_output_id == output_id:
            self.active_output_id = None

    async def cancel_output(self, cursor: PlaybackCursor | None = None) -> None:
        self.calls.append("cancel_output")
        self.cancelled.append(cursor)

    async def truncate(self, cursor: PlaybackCursor) -> None:
        self.calls.append("truncate")
        if self.truncate_error is not None:
            raise self.truncate_error
        self.truncated.append(cursor)


class BlindSession(ControllableSession):
    """Pile sans contrôles de sortie : la forme de Gemini Live (Décision 21)."""

    speak = None  # type: ignore[assignment]
    speak_reserved = None  # type: ignore[assignment]
    invalidate_unstarted_output = None  # type: ignore[assignment]
    cancel_output = None  # type: ignore[assignment]
    truncate = None  # type: ignore[assignment]


class CountingAudio(SoundDeviceRealtimeAudio):
    """Comptabilise sans périphérique et note l'ordre des étapes d'arrêt."""

    def __init__(self, calls: list[str] | None = None) -> None:
        super().__init__()
        self.calls = calls if calls is not None else []
        self.stop_output_calls = 0
        self.closed = False

    async def play_b64(self, value: str) -> None:
        self._credit_written(self._output_epoch, len(base64.b64decode(value)))

    async def stop_output(self) -> None:
        self.stop_output_calls += 1
        self.calls.append("stop_output")
        await super().stop_output()

    async def close(self) -> None:
        self.closed = True


def build_bridge(
    *,
    audio: SoundDeviceRealtimeAudio,
    session: object,
    core: object,
    journal: RecordingJournal | None = None,
    continuous: bool = True,
    on_interruption=None,  # noqa: ANN001
) -> RealtimeConversationBridge:
    return RealtimeConversationBridge(
        core=core,
        session=session,
        conversation_id=CONVERSATION,
        audio=audio,
        on_addressed=lambda: None,
        on_mute=lambda: None,
        auto_turn=True,
        continuous=continuous,
        journal=journal,
        on_interruption=on_interruption,
    )


async def feed(bridge: RealtimeConversationBridge, events: list[ProtocolEnvelope]) -> None:
    async def stream():
        for event in events:
            yield event
            # Le fournisseur réel n'envoie pas tout d'un bloc : chaque
            # évènement est traité — audio joué compris — avant le suivant.
            await bridge.wait_idle()

    await bridge._consume(stream())


def output_started(**payload: object) -> ProtocolEnvelope:
    return ProtocolEnvelope(message_type="realtime.output_started", payload=payload)


def audio_delta(chunks: int, **payload: object) -> ProtocolEnvelope:
    return ProtocolEnvelope(message_type="realtime.audio", payload={"pcm_b64": pcm_b64(chunks), **payload})


def speech_started() -> ProtocolEnvelope:
    return ProtocolEnvelope(message_type="realtime.speech_started", payload={})


def transcript(text: str, *, item_id: str = "item-user-1") -> ProtocolEnvelope:
    return ProtocolEnvelope(message_type="realtime.transcript", payload={"text": text, "item_id": item_id})


async def until(predicate, *, timeout: float = TIMEOUT_S) -> None:  # noqa: ANN001
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition jamais atteinte")


# --------------------------------------------------------------------------
# 1. L'arrêt de sortie coupe la parole sans emporter le micro


async def test_stop_output_aborts_playback_and_leaves_the_microphone_open():
    """Le manque bloquant identifié par 09a : couper la voix sans fermer l'entrée."""

    output, microphone = FakeOutputStream(), FakeInputStream()
    audio = SoundDeviceRealtimeAudio()
    audio._output, audio._input = output, microphone
    audio.set_active_output(speech_id="speech-1", output_id="out-1")

    await audio.stop_output()

    assert output.aborted == 1  # le tampon est jeté, pas vidé
    assert microphone.stopped is False and microphone.closed is False
    assert audio._input is microphone and audio._output is output
    assert audio._closing is False  # l'objet reste utilisable


async def test_the_stream_stays_usable_for_the_next_output():
    """Un flux arrêté refuse les écritures : le barge-in doit le relancer."""

    output = FakeOutputStream()
    audio = SoundDeviceRealtimeAudio()
    audio._output = output
    audio.set_active_output(speech_id="speech-1", output_id="out-1")
    await audio.play_b64(pcm_b64(2))

    await audio.stop_output()
    audio.set_active_output(speech_id="speech-2", output_id="out-2")
    await audio.play_b64(pcm_b64(1))

    assert output.started == 1
    assert len(output.writes) == 3  # les deux premiers blocs, puis celui d'après
    assert audio.playback_cursor().played_ms == CHUNK_MS


async def test_stop_output_reports_what_was_played_not_what_was_queued():
    """Le curseur lu juste après l'arrêt est exact : `abort()` a jeté le reste.

    L'écriture en vol est libérée **après** que l'arrêt a été demandé : c'est le
    cas qui compte, et c'est aussi celui qui a montré qu'un simple drapeau rendu
    à la fin de `stop_output()` ne suffisait pas — le thread d'écriture pouvait
    reprendre le verrou après `abort()` et remettre du son.
    """

    gate = threading.Event()
    output = FakeOutputStream(block_first_write=gate)
    audio = SoundDeviceRealtimeAudio()
    audio._output = output
    audio.set_active_output(speech_id="speech-1", output_id="out-1", item_id="item-1")
    epoch = audio._playback_epoch

    playing = asyncio.create_task(audio.play_b64(pcm_b64(10)))  # 1 s de parole
    await until(lambda: output.writing)

    stopping = asyncio.create_task(audio.stop_output())
    await until(lambda: audio._playback_epoch != epoch)
    gate.set()
    await asyncio.wait_for(stopping, timeout=5)
    await asyncio.wait_for(playing, timeout=5)

    assert len(output.writes) == 1  # 900 ms n'ont jamais atteint le périphérique
    cursor = audio.playback_cursor()
    assert cursor is not None and cursor.played_ms == CHUNK_MS


async def test_stop_output_never_frees_the_stream_while_portaudio_is_writing():
    """Régression 0xC0000005 : `abort()` n'est appelé que le verrou tenu."""

    gate = threading.Event()
    output = FakeOutputStream(block_first_write=gate)
    audio = SoundDeviceRealtimeAudio()
    audio._output = output
    audio.set_active_output(speech_id="speech-1", output_id="out-1")

    playing = asyncio.create_task(audio.play_b64(pcm_b64(4)))
    await until(lambda: output.writing)

    stopping = asyncio.create_task(audio.stop_output())
    await asyncio.sleep(0.05)
    assert not stopping.done(), "stop_output() a abandonné le flux sans attendre l'écriture en vol"

    gate.set()
    await asyncio.wait_for(stopping, timeout=5)
    await asyncio.wait_for(playing, timeout=5)

    assert output.freed_while_writing is False
    assert output.aborted == 1


# --------------------------------------------------------------------------
# 2. La parole de l'utilisateur interrompt la sortie en cours


async def test_user_speech_stops_local_playback_before_any_provider_call():
    """Étapes 2 à 4 : l'arrêt local d'abord, le réseau ensuite."""

    calls: list[str] = []
    audio, session, journal = CountingAudio(calls), ControllableSession(), RecordingJournal()
    session.calls = calls
    bridge = build_bridge(audio=audio, session=session, core=RecordingCore(), journal=journal)

    await feed(
        bridge,
        [
            output_started(output_id="out-1", speech_id="speech-1", response_id="resp-1"),
            audio_delta(3, output_id="out-1", speech_id="speech-1", response_id="resp-1", item_id="item-1"),
            speech_started(),
        ],
    )

    assert audio.stop_output_calls == 1
    assert calls == ["stop_output", "cancel_output", "truncate"]
    assert journal.count("voice.barge_in") == 1


async def test_cancel_and_truncate_carry_the_active_output_and_cursor():
    """Le fournisseur reçoit l'identifiant de sortie et les ms réellement jouées."""

    audio, session = CountingAudio(), ControllableSession()
    bridge = build_bridge(audio=audio, session=session, core=RecordingCore())

    await feed(
        bridge,
        [
            output_started(output_id="out-1", speech_id="speech-1", response_id="resp-1"),
            audio_delta(4, output_id="out-1", speech_id="speech-1", response_id="resp-1", item_id="item-1"),
            speech_started(),
        ],
    )

    assert len(session.cancelled) == 1 and len(session.truncated) == 1
    cursor = session.truncated[0]
    assert session.cancelled[0] == cursor
    assert cursor.speech_id == "speech-1"
    assert cursor.provider_response_id == "resp-1"
    assert cursor.provider_item_id == "item-1"
    assert cursor.played_ms == 4 * CHUNK_MS


async def test_the_journal_records_the_truncation_point_and_the_stop_latency():
    """Décision 27 : l'observabilité de cette séquence passe par `RuntimeJournal`."""

    audio, session, journal = CountingAudio(), ControllableSession(), RecordingJournal()
    bridge = build_bridge(audio=audio, session=session, core=RecordingCore(), journal=journal)

    await feed(
        bridge,
        [
            output_started(output_id="out-1", speech_id="speech-1"),
            audio_delta(2, output_id="out-1", speech_id="speech-1", item_id="item-1"),
            speech_started(),
        ],
    )

    data = journal.of("voice.barge_in")[0]["data"]
    assert data["speech_id"] == "speech-1"
    assert data["played_ms"] == 2 * CHUNK_MS
    assert data["provider_item_id"] == "item-1"
    assert isinstance(data["stop_latency_ms"], float)


async def test_audio_still_streaming_after_the_cancel_is_not_played():
    """L'annulation fait un aller-retour : les blocs en vol ne doivent plus sortir."""

    audio, session = CountingAudio(), ControllableSession()
    bridge = build_bridge(audio=audio, session=session, core=RecordingCore())

    await feed(
        bridge,
        [
            output_started(output_id="out-1", speech_id="speech-1"),
            audio_delta(2, output_id="out-1", speech_id="speech-1"),
            speech_started(),
            audio_delta(5, output_id="out-1", speech_id="speech-1"),  # en vol au moment du barge-in
        ],
    )

    assert audio.playback_cursor().played_ms == 2 * CHUNK_MS


async def test_a_finished_output_is_no_longer_interruptible():
    """Rien ne joue : la parole de l'utilisateur ouvre un tour, elle ne coupe rien."""

    audio, session, journal = CountingAudio(), ControllableSession(), RecordingJournal()
    bridge = build_bridge(audio=audio, session=session, core=RecordingCore(), journal=journal)

    await feed(
        bridge,
        [
            output_started(output_id="out-1", speech_id="speech-1"),
            audio_delta(1, output_id="out-1", speech_id="speech-1"),
            ProtocolEnvelope(
                message_type="realtime.response_done",
                payload={"status": "completed", "output_id": "out-1", "speech_id": "speech-1"},
            ),
            speech_started(),
        ],
    )

    assert audio.stop_output_calls == 0
    assert session.cancelled == []
    assert journal.count("voice.barge_in") == 0
    assert journal.count("voice.speech_started") == 1  # la trace habituelle demeure


async def test_the_legacy_path_keeps_its_half_duplex_behaviour():
    """Décision 20 : le chemin de repli ne change pas de comportement."""

    audio, session, journal = CountingAudio(), ControllableSession(), RecordingJournal()
    bridge = build_bridge(
        audio=audio, session=session, core=RecordingCore(), journal=journal, continuous=False
    )

    await feed(
        bridge,
        [
            output_started(output_id="out-1", speech_id="speech-1"),
            audio_delta(2, output_id="out-1", speech_id="speech-1"),
            speech_started(),
        ],
    )

    assert audio.stop_output_calls == 0
    assert session.cancelled == [] and session.truncated == []
    assert journal.count("voice.barge_in") == 0


# --------------------------------------------------------------------------
# 3. Piles sans curseur : rien n'explose


async def test_a_stack_without_output_identifiers_still_stops_speaking():
    """Gemini Live n'émet aucun identifiant de sortie (Décision 21)."""

    audio, session, journal = CountingAudio(), ControllableSession(), RecordingJournal()
    bridge = build_bridge(audio=audio, session=session, core=RecordingCore(), journal=journal)

    await feed(bridge, [audio_delta(2), speech_started()])

    assert audio.playback_cursor() is None
    assert audio.stop_output_calls == 1
    assert session.cancelled == [None]  # annuler reste possible
    assert session.truncated == []  # tronquer, non : aucun élément à viser
    codes = {event["data"].get("code") for event in journal.of("voice.barge_in_degraded")}
    assert "barge_in_without_cursor" in codes


async def test_a_stack_without_output_control_degrades_without_raising():
    audio, journal = CountingAudio(), RecordingJournal()
    bridge = build_bridge(audio=audio, session=BlindSession(), core=RecordingCore(), journal=journal)

    await feed(
        bridge,
        [
            output_started(output_id="out-1", speech_id="speech-1"),
            audio_delta(1, output_id="out-1", speech_id="speech-1"),
            speech_started(),
        ],
    )

    assert audio.stop_output_calls == 1  # le son s'arrête quand même
    codes = {event["data"].get("code") for event in journal.of("voice.barge_in_degraded")}
    assert "barge_in_without_output_control" in codes


async def test_an_impossible_truncation_is_reported_not_raised():
    audio, session, journal = CountingAudio(), ControllableSession(), RecordingJournal()
    session.truncate_error = ValueError("no provider item to truncate for speech 'speech-1'")
    bridge = build_bridge(audio=audio, session=session, core=RecordingCore(), journal=journal)

    await feed(
        bridge,
        [
            output_started(output_id="out-1", speech_id="speech-1"),
            audio_delta(1, output_id="out-1", speech_id="speech-1"),
            speech_started(),
            transcript("Jarvis, laisse tomber."),
        ],
    )

    codes = {event["data"].get("code") for event in journal.of("voice.barge_in_degraded")}
    assert "barge_in_truncate_failed" in codes


# --------------------------------------------------------------------------
# 4. Le tour utilisateur suivant porte l'interruption, et rien d'autre


async def test_the_next_authoritative_turn_carries_the_interrupted_speech_id():
    """Étape 6 : le cerveau apprend qu'il a été coupé, et sur quelle phrase."""

    audio, session, core = CountingAudio(), ControllableSession(), RecordingCore()
    bridge = build_bridge(audio=audio, session=session, core=core)

    await feed(
        bridge,
        [
            output_started(output_id="out-1", speech_id="speech-1"),
            audio_delta(3, output_id="out-1", speech_id="speech-1", item_id="item-1"),
            speech_started(),
            transcript("Jarvis, oublie ça et lis-moi mes messages."),
        ],
    )

    assert len(core.brain_turns) == 1
    assert core.brain_turns[0]["interrupted_speech_id"] == "speech-1"
    assert core.brain_turns[0]["content"] == "Jarvis, oublie ça et lis-moi mes messages."


async def test_the_interruption_marker_is_consumed_by_a_single_turn():
    """Un tour non interrompu ne doit pas hériter du précédent."""

    audio, session, core = CountingAudio(), ControllableSession(), RecordingCore()
    bridge = build_bridge(audio=audio, session=session, core=core)

    await feed(
        bridge,
        [
            output_started(output_id="out-1", speech_id="speech-1"),
            audio_delta(1, output_id="out-1", speech_id="speech-1"),
            speech_started(),
            transcript("Jarvis, arrête.", item_id="item-user-1"),
            transcript("Jarvis, quelle heure est-il ?", item_id="item-user-2"),
        ],
    )

    assert [turn["interrupted_speech_id"] for turn in core.brain_turns] == ["speech-1", None]


async def test_a_turn_without_interruption_carries_no_marker():
    audio, session, core = CountingAudio(), ControllableSession(), RecordingCore()
    bridge = build_bridge(audio=audio, session=session, core=core)

    await feed(bridge, [transcript("Jarvis, quelle heure est-il ?")])

    assert core.brain_turns[0]["interrupted_speech_id"] is None


async def test_barging_in_never_cancels_work():
    """Décisions 15 et 35 : couper la parole n'est pas annuler la tâche."""

    audio, session, core = CountingAudio(), ControllableSession(), RecordingCore()
    bridge = build_bridge(audio=audio, session=session, core=core)

    await feed(
        bridge,
        [
            output_started(output_id="out-1", speech_id="speech-1"),
            audio_delta(2, output_id="out-1", speech_id="speech-1", item_id="item-1"),
            speech_started(),
            transcript("Jarvis, laisse tomber."),
        ],
    )

    # La surface n'a aucun moyen d'annuler : ni outil Core, ni tour hors ingress
    # cerveau. Seul le cerveau peut retirer un travail, sur décision nommée.
    assert core.tool_calls == []
    assert core.turns == []
    assert len(core.brain_turns) == 1


# --------------------------------------------------------------------------
# 5. L'historique ne prétend pas que l'audio tronqué a été entendu


def speech_request(text: str, *, kind: SpeechKind = SpeechKind.RESULT, speech_id: str = "speech-1") -> SpeechRequest:
    return SpeechRequest(
        conversation_id=CONVERSATION,
        text=text,
        kind=kind,
        priority=SpeechPriority.NORMAL,
        id=speech_id,
        correlation_id="corr-1",
        work_id="work-1",
        created_at=utc_now(),
        source=speech_source("corr-1", work_id="work-1"),
    )


def speech_envelope(request: SpeechRequest) -> ProtocolEnvelope:
    return ProtocolEnvelope(
        message_type="brain.speech.requested",
        payload=request.to_payload(),
        correlation_id=request.correlation_id,
        conversation_id=request.conversation_id,
    )


def build_scheduler(core: RecordingCore, session: ControllableSession, journal=None) -> SpeechScheduler:  # noqa: ANN001
    return SpeechScheduler(
        core=core,
        conversation_id=CONVERSATION,
        session=session,
        journal=journal,
        reconnect_delay_s=0.0,
        output_timeout_s=5.0,
    )


async def finish_output(scheduler: SpeechScheduler, session: ControllableSession, *, status: str) -> None:
    # The scheduler reserves opaque output IDs before its provider await.
    # Keep the current production correlation instead of inventing out-N.
    active = scheduler._active
    assert active is not None
    output_id = active.output_id
    if session.active_output_id == output_id:
        session.active_output_id = None
    await scheduler.note_output_event(
        ProtocolEnvelope(
            message_type="realtime.response_done", payload={"output_id": output_id, "status": status}
        )
    )


async def test_an_interrupted_speech_is_persisted_as_partially_delivered():
    """Critère d'acceptation 2, versant « ne pas mentir par excès »."""

    core, session = RecordingCore(), ControllableSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    try:
        await core.publish(speech_envelope(speech_request("Voici les trois messages en attente.")))
        await until(lambda: len(session.spoken) == 1)
        reserved_output = session.active_output_id

        scheduler.note_interruption(PlaybackCursor(speech_id="speech-1", played_ms=1200))
        await finish_output(scheduler, session, status="cancelled")
        await until(lambda: len(core.turns) == 1)

        metadata = core.turns[0]["metadata"]
        assert metadata["provenance"] == SpeechProvenance.BRAIN.value
        assert metadata["delivery"] == SPEECH_DELIVERY_PARTIAL
        assert metadata["played_ms"] == 1200
        assert metadata["output_id"] == reserved_output
        assert metadata["speech_id"] == "speech-1" and metadata["work_id"] == "work-1"
        assert core.turns[0]["correlation_id"] == "corr-1"
        # Le texte n'est jamais réécrit (Décision 13) : c'est la métadonnée qui
        # dit qu'il n'a pas été entendu jusqu'au bout.
        assert core.turns[0]["content"] == "Voici les trois messages en attente."
    finally:
        await scheduler.stop()


async def test_a_speech_interrupted_before_the_first_audio_leaves_no_turn():
    """Rien n'a été entendu : l'historique ne doit rien affirmer du tout."""

    core, session, journal = RecordingCore(), ControllableSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        await core.publish(speech_envelope(speech_request("Voici les trois messages en attente.")))
        await until(lambda: len(session.spoken) == 1)

        scheduler.note_interruption(PlaybackCursor(speech_id="speech-1", played_ms=0))
        await finish_output(scheduler, session, status="cancelled")
        await journal.wait_until(lambda: journal.count("voice.speech.interrupted") == 1)

        assert core.turns == []
    finally:
        await scheduler.stop()


async def test_a_completed_speech_keeps_its_untouched_metadata():
    """Non-régression : une phrase dite en entier n'est pas marquée partielle."""

    core, session = RecordingCore(), ControllableSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    try:
        await core.publish(speech_envelope(speech_request("Voici les trois messages en attente.")))
        await until(lambda: len(session.spoken) == 1)
        await finish_output(scheduler, session, status="completed")
        await until(lambda: len(core.turns) == 1)

        assert "delivery" not in core.turns[0]["metadata"]
        assert "played_ms" not in core.turns[0]["metadata"]
    finally:
        await scheduler.stop()


async def test_an_interruption_without_cursor_does_not_raise():
    """Le curseur peut être `None` : l'ordonnanceur marque quand même la coupure."""

    core, session, journal = RecordingCore(), ControllableSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        await core.publish(speech_envelope(speech_request("Voici les trois messages en attente.")))
        await until(lambda: len(session.spoken) == 1)

        scheduler.note_interruption(None)
        await finish_output(scheduler, session, status="completed")
        await journal.wait_until(lambda: journal.count("voice.speech.interrupted") == 1)

        assert core.turns == []  # ms entendues inconnues : on n'affirme rien
    finally:
        await scheduler.stop()


async def test_note_interruption_without_active_speech_is_a_no_op():
    core, session = RecordingCore(), ControllableSession()
    scheduler = build_scheduler(core, session)

    scheduler.note_interruption(PlaybackCursor(speech_id="speech-1", played_ms=800))

    assert core.turns == []


async def test_core_does_not_count_a_truncated_sentence_as_a_known_fact(tmp_path):
    """Critère d'acceptation 2 dans l'état public : Core n'a pas la mémoire large."""

    from jarvis.adapters.jsonl_history import JsonlHistoryStore
    from jarvis.adapters.sqlite_state import SQLiteStateRepository

    repository = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await repository.initialize()
    conversations = ConversationService(repository, JsonlHistoryStore(tmp_path / "history"))
    orchestrator = BrainOrchestrator(conversations=conversations, events=CoreEventBus())
    try:
        conversation = await conversations.create()
        await conversations.append_turn(
            conversation.id,
            TurnKind.ASSISTANT,
            "Le vol de demain est annulé.",
            correlation_id="corr-1",
            metadata={
                "provenance": SpeechProvenance.BRAIN.value,
                "speech_kind": SpeechKind.RESULT.value,
                "delivery": SPEECH_DELIVERY_PARTIAL,
                "played_ms": 400,
            },
        )

        snapshot = await orchestrator.rehydrate(conversation.id)

        assert snapshot["known_public_facts"] == []

        # Témoin : la même phrase, entendue en entier, est bien un fait public.
        other = await conversations.create()
        await conversations.append_turn(
            other.id,
            TurnKind.ASSISTANT,
            "Le vol de demain est annulé.",
            correlation_id="corr-2",
            metadata={
                "provenance": SpeechProvenance.BRAIN.value,
                "speech_kind": SpeechKind.RESULT.value,
            },
        )

        assert (await orchestrator.rehydrate(other.id))["known_public_facts"] == ["Le vol de demain est annulé."]
    finally:
        await orchestrator.stop()
        await repository.close()


# --------------------------------------------------------------------------
# 6. Course exigée par l'étape 8 : le résultat arrive pendant l'interruption


async def test_a_brain_result_arriving_during_the_interruption_is_still_spoken():
    """Le résultat n'est ni perdu ni prononcé par-dessus la coupure."""

    core, session = RecordingCore(), ControllableSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    try:
        await core.publish(speech_envelope(speech_request("Je regarde.", kind=SpeechKind.PROGRESS)))
        await until(lambda: len(session.spoken) == 1)

        # Exactement au même tour de boucle : le résultat entre en file pendant
        # que l'utilisateur coupe la phrase en cours.
        await core.publish(speech_envelope(speech_request("Trois messages.", speech_id="speech-2")))
        scheduler.note_interruption(PlaybackCursor(speech_id="speech-1", played_ms=500))
        await finish_output(scheduler, session, status="cancelled")

        await until(lambda: len(session.spoken) == 2)
        await finish_output(scheduler, session, status="completed")
        await until(lambda: len(core.turns) == 2)

        assert [request.text for request in session.spoken] == ["Je regarde.", "Trois messages."]
        assert core.turns[0]["metadata"]["delivery"] == SPEECH_DELIVERY_PARTIAL
        assert "delivery" not in core.turns[1]["metadata"]
    finally:
        await scheduler.stop()


async def test_the_race_resolves_the_same_way_in_the_reverse_order():
    """Interruption d'abord, résultat ensuite : même issue, pas d'ordre chanceux."""

    core, session = RecordingCore(), ControllableSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    try:
        await core.publish(speech_envelope(speech_request("Je regarde.", kind=SpeechKind.PROGRESS)))
        await until(lambda: len(session.spoken) == 1)

        scheduler.note_interruption(PlaybackCursor(speech_id="speech-1", played_ms=500))
        await finish_output(scheduler, session, status="cancelled")
        await core.publish(speech_envelope(speech_request("Trois messages.", speech_id="speech-2")))

        await until(lambda: len(session.spoken) == 2)
        await finish_output(scheduler, session, status="completed")
        await until(lambda: len(core.turns) == 2)

        assert core.turns[0]["metadata"]["delivery"] == SPEECH_DELIVERY_PARTIAL
        assert core.turns[1]["content"] == "Trois messages."
    finally:
        await scheduler.stop()


async def test_a_progress_queued_during_the_interruption_is_dropped_by_the_new_turn():
    """La progression périmée par la nouvelle intention n'est jamais prononcée."""

    core, session = RecordingCore(), ControllableSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    try:
        await core.publish(speech_envelope(speech_request("Je regarde.", kind=SpeechKind.PROGRESS)))
        await until(lambda: len(session.spoken) == 1)

        await core.publish(
            speech_envelope(speech_request("J'y suis presque.", kind=SpeechKind.PROGRESS, speech_id="speech-2"))
        )
        scheduler.note_interruption(PlaybackCursor(speech_id="speech-1", played_ms=500))
        await until(lambda: scheduler.pending_count == 1)

        # Le tour utilisateur qui a coupé la parole devient autoritaire côté
        # Core, qui republie la révision d'intention (09b).
        await core.publish(
            ProtocolEnvelope(
                message_type="brain.turn.accepted",
                payload={**speech_context_payload(CONVERSATION, "corr-2", epoch=2), "revision": 2},
                conversation_id=CONVERSATION,
            )
        )
        await until(lambda: scheduler.pending_count == 0)
        await finish_output(scheduler, session, status="cancelled")

        assert [request.text for request in session.spoken] == ["Je regarde."]
        retired = next(item for item in scheduler.presentation_snapshot()["candidates"] if item["speech_id"] == "speech-2")
        assert retired["status"] == "superseded" and retired["reason"] == "stale_source"

        # The same old work may finish after the new intent. Its result remains
        # available for a future explicit selection; the old voice is deferred.
        late_result = speech_request("Trois messages.", speech_id="speech-3")
        await core.publish(speech_envelope(late_result))
        await until(lambda: late_result.id in scheduler._deferred)
        assert scheduler._deferred[late_result.id].text == late_result.text
        assert scheduler._deferred[late_result.id].source == late_result.source
        deferred = next(item for item in scheduler.presentation_snapshot()["candidates"] if item["speech_id"] == late_result.id)
        assert deferred["status"] == "deferred" and deferred["reason"] == "stale_source"
        assert [request.text for request in session.spoken] == ["Je regarde."]
        assert not any(turn["content"] == late_result.text for turn in core.turns)
    finally:
        await scheduler.stop()

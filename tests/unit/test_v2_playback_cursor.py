"""Comptabilité de lecture audio (tâche 09a).

Le barge-in doit tronquer l'historique fournisseur « à hauteur de ce qui a été
réellement entendu » (spec §12). Ces tests fixent cette comptabilité et, surtout,
vérifient qu'elle n'a rien changé à l'invariant de sûreté PortAudio : aucun flux
n'est libéré tant qu'un thread est à l'intérieur, et lire le curseur n'attend
jamais la fin d'une écriture.
"""

from __future__ import annotations

import asyncio
import base64
import threading

from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio


CHUNK_FRAMES = SoundDeviceRealtimeAudio.OUTPUT_CHUNK_FRAMES
CHUNK_BYTES = CHUNK_FRAMES * SoundDeviceRealtimeAudio._BYTES_PER_FRAME
CHUNK_MS = 100  # 2400 trames à 24 kHz


def pcm_b64(chunks: int) -> str:
    return base64.b64encode(b"\x01\x00" * (CHUNK_FRAMES * chunks)).decode()


class FakeOutputStream:
    """Flux de sortie qui signale toute libération pendant une écriture."""

    def __init__(self, *, block_first_write: threading.Event | None = None, latency: object = None) -> None:
        self.block_first_write = block_first_write
        self.latency = latency
        self.writes: list[bytes] = []
        self.writing = False
        self.aborted = False
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
        return None

    def abort(self, *, ignore_errors=True) -> None:
        self.aborted = True
        self.freed_while_writing |= self.writing

    def stop(self, *, ignore_errors=True) -> None:
        self.freed_while_writing |= self.writing

    def close(self, *, ignore_errors=True) -> None:
        self.freed_while_writing |= self.writing
        self.closed = True


async def _until(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition jamais atteinte"
        await asyncio.sleep(0.005)


def _audio(stream: FakeOutputStream) -> SoundDeviceRealtimeAudio:
    audio = SoundDeviceRealtimeAudio()
    audio._output = stream
    return audio


# --------------------------------------------------------------------------
# 1. La position avance avec l'audio effectivement écrit


async def test_the_cursor_advances_with_the_audio_written_to_the_device():
    audio = _audio(FakeOutputStream())
    audio.set_active_output(speech_id="speech-1", output_id="out-1", response_id="resp-1", item_id="item-1")

    await audio.play_b64(pcm_b64(3))

    assert audio.written_output_ms == 3 * CHUNK_MS
    cursor = audio.playback_cursor()
    assert cursor is not None
    assert cursor.speech_id == "speech-1"
    assert cursor.played_ms == 3 * CHUNK_MS
    assert cursor.provider_response_id == "resp-1"
    assert cursor.provider_item_id == "item-1"


async def test_the_cursor_is_unavailable_until_an_output_is_declared():
    """Gemini Live n'émet aucun identifiant de sortie (Décision 21)."""
    audio = _audio(FakeOutputStream())

    await audio.play_b64(pcm_b64(2))

    assert audio.playback_cursor() is None
    # La comptabilité brute continue : seule l'identité manque pour tronquer.
    assert audio.written_output_ms == 2 * CHUNK_MS


# --------------------------------------------------------------------------
# 2. Écrit n'est pas joué : la latence du périphérique est retranchée


async def test_played_is_lower_than_written_by_the_device_buffer():
    """`write()` rend la main quand l'audio est dans le tampon, pas dans le haut-parleur."""
    audio = _audio(FakeOutputStream(latency=0.2))  # 200 ms de tampon annoncés
    audio.set_active_output(speech_id="speech-1", output_id="out-1")

    await audio.play_b64(pcm_b64(5))

    assert audio.written_output_ms == 500
    assert audio.played_output_ms == 300
    cursor = audio.playback_cursor()
    assert cursor is not None and cursor.played_ms == 300


async def test_played_never_goes_negative_when_less_than_one_buffer_was_written():
    audio = _audio(FakeOutputStream(latency=0.2))
    audio.set_active_output(speech_id="speech-1", output_id="out-1")

    await audio.play_b64(pcm_b64(1))

    assert audio.written_output_ms == 100
    assert audio.played_output_ms == 0


async def test_an_unreadable_latency_falls_back_to_written_audio():
    audio = _audio(FakeOutputStream(latency="inconnue"))
    audio.set_active_output(speech_id="speech-1", output_id="out-1")

    await audio.play_b64(pcm_b64(2))

    assert audio.played_output_ms == 200


# --------------------------------------------------------------------------
# 3. Remise à zéro au changement de sortie


async def test_a_new_output_restarts_the_cursor_from_zero():
    audio = _audio(FakeOutputStream())
    audio.set_active_output(speech_id="speech-1", output_id="out-1", item_id="item-1")
    await audio.play_b64(pcm_b64(4))

    audio.set_active_output(speech_id="speech-2", output_id="out-2", item_id="item-2")

    assert audio.written_output_ms == 0
    cursor = audio.playback_cursor()
    assert cursor is not None
    assert cursor.speech_id == "speech-2"
    assert cursor.played_ms == 0
    assert cursor.provider_item_id == "item-2"

    await audio.play_b64(pcm_b64(1))
    assert audio.playback_cursor().played_ms == CHUNK_MS


async def test_redeclaring_the_same_output_completes_ids_without_losing_the_position():
    """`item_id` n'arrive qu'après l'ouverture de la sortie : le compteur doit survivre."""
    audio = _audio(FakeOutputStream())
    audio.set_active_output(speech_id="speech-1", output_id="out-1", response_id="resp-1")
    await audio.play_b64(pcm_b64(2))

    audio.set_active_output(speech_id="speech-1", output_id="out-1", response_id="resp-1", item_id="item-1")

    cursor = audio.playback_cursor()
    assert cursor is not None
    assert cursor.played_ms == 2 * CHUNK_MS
    assert cursor.provider_item_id == "item-1"


async def test_an_output_started_without_speech_id_falls_back_to_the_output_id():
    """Un réflexe de surface n'a pas de `SpeechRequest` : il reste tronquable."""
    audio = _audio(FakeOutputStream())
    audio.set_active_output(output_id="out-9", response_id="resp-9", item_id="item-9")

    await audio.play_b64(pcm_b64(1))

    cursor = audio.playback_cursor()
    assert cursor is not None
    assert cursor.speech_id == "out-9"
    assert cursor.provider_response_id == "resp-9"


async def test_bytes_written_for_the_previous_output_are_not_credited_to_the_next():
    """Bascule de sortie pendant une écriture en vol : rien ne déborde."""
    gate = threading.Event()
    stream = FakeOutputStream(block_first_write=gate)
    audio = _audio(stream)
    audio.set_active_output(speech_id="speech-1", output_id="out-1")

    playing = asyncio.create_task(audio.play_b64(pcm_b64(2)))
    await _until(lambda: stream.writing)

    audio.set_active_output(speech_id="speech-2", output_id="out-2")
    gate.set()
    await asyncio.wait_for(playing, timeout=5)

    assert stream.writes  # l'audio de la sortie précédente a bien fini de sortir
    assert audio.written_output_ms == 0
    assert audio.playback_cursor().played_ms == 0


# --------------------------------------------------------------------------
# 4. Après un arrêt : ce qui a été joué, pas ce qui restait en file


async def test_after_a_stop_the_cursor_reports_played_audio_not_queued_audio():
    gate = threading.Event()
    stream = FakeOutputStream(block_first_write=gate)
    audio = _audio(stream)
    audio.set_active_output(speech_id="speech-1", output_id="out-1", item_id="item-1")

    playing = asyncio.create_task(audio.play_b64(pcm_b64(10)))  # 1 s de parole
    await _until(lambda: stream.writing)

    closing = asyncio.create_task(audio.close())
    await _until(lambda: audio._closing)  # l'arrêt est demandé avant de libérer l'écriture
    gate.set()
    await asyncio.wait_for(closing, timeout=5)
    await asyncio.gather(playing, return_exceptions=True)

    # Un seul bloc est parti au périphérique ; les 900 ms restantes n'ont jamais
    # été écrites et ne doivent pas apparaître dans l'historique fournisseur.
    assert len(stream.writes) == 1
    cursor = audio.playback_cursor()
    assert cursor is not None
    assert cursor.played_ms == CHUNK_MS
    assert stream.aborted is True
    assert stream.freed_while_writing is False


async def test_the_cursor_survives_close_so_the_barge_in_can_still_truncate():
    """`close()` lâche le flux ; 09c lit le curseur juste après."""
    stream = FakeOutputStream(latency=0.05)
    audio = _audio(stream)
    audio.set_active_output(speech_id="speech-1", output_id="out-1", item_id="item-1")
    await audio.play_b64(pcm_b64(4))

    await audio.close()

    cursor = audio.playback_cursor()
    assert cursor is not None
    assert cursor.speech_id == "speech-1"
    assert cursor.played_ms == 350  # 400 ms écrites - 50 ms de tampon jeté par abort()
    assert audio._output is None


async def test_writes_dropped_by_the_closing_flag_are_never_counted():
    audio = _audio(FakeOutputStream())
    audio.set_active_output(speech_id="speech-1", output_id="out-1")
    await audio.close()

    await audio.play_b64(pcm_b64(3))

    assert audio.written_output_ms == 0
    assert audio.playback_cursor().played_ms == 0


# --------------------------------------------------------------------------
# 5. L'invariant de concurrence PortAudio est inchangé


async def test_reading_the_cursor_never_waits_for_an_in_flight_portaudio_write():
    """Le verrou du curseur n'est jamais tenu pendant qu'un thread est dans PortAudio."""
    gate = threading.Event()
    stream = FakeOutputStream(block_first_write=gate)
    audio = _audio(stream)
    audio.set_active_output(speech_id="speech-1", output_id="out-1")

    playing = asyncio.create_task(audio.play_b64(pcm_b64(5)))
    await _until(lambda: stream.writing)

    cursor = await asyncio.wait_for(asyncio.to_thread(audio.playback_cursor), timeout=2)

    assert cursor is not None
    assert cursor.played_ms == 0  # rien n'est crédité avant le retour de write()
    gate.set()
    await asyncio.wait_for(playing, timeout=5)
    assert audio.playback_cursor().played_ms == 5 * CHUNK_MS


async def test_close_still_never_frees_the_stream_while_portaudio_is_writing():
    """Régression du crash 0xC0000005 : la comptabilité n'a rien relâché."""
    gate = threading.Event()
    stream = FakeOutputStream(block_first_write=gate)
    audio = _audio(stream)
    audio.set_active_output(speech_id="speech-1", output_id="out-1")

    playing = asyncio.create_task(audio.play_b64(pcm_b64(1)))
    await _until(lambda: stream.writing)

    playing.cancel()
    closing = asyncio.create_task(audio.close())
    await asyncio.sleep(0.05)
    assert not closing.done(), "close() a libéré le flux sans attendre l'écriture en vol"

    gate.set()
    await asyncio.wait_for(closing, timeout=5)
    await asyncio.gather(playing, return_exceptions=True)

    assert stream.freed_while_writing is False
    assert stream.closed is True
    assert stream.aborted is True


# --------------------------------------------------------------------------
# 6. Câblage du bridge : la sortie active suit les évènements du fournisseur


class _SilentAudio(SoundDeviceRealtimeAudio):
    """Comptabilise sans périphérique : `play_b64` crédite directement."""

    async def play_b64(self, value: str) -> None:
        self._credit_written(self._output_epoch, len(base64.b64decode(value)))


def _bridge(audio: SoundDeviceRealtimeAudio) -> RealtimeConversationBridge:
    return RealtimeConversationBridge(
        core=object(),
        session=object(),
        conversation_id="conv-1",
        audio=audio,
        on_addressed=lambda: None,
        on_mute=lambda: None,
    )


async def _feed(bridge: RealtimeConversationBridge, events: list[ProtocolEnvelope]) -> None:
    async def stream():
        for event in events:
            yield event
            # Le fournisseur réel n'envoie pas tout d'un bloc : chaque
            # évènement est traité — audio joué compris — avant le suivant.
            await bridge.wait_idle()

    await bridge._consume(stream())


async def test_the_bridge_binds_the_cursor_to_the_provider_output():
    audio = _SilentAudio()
    bridge = _bridge(audio)

    await _feed(
        bridge,
        [
            ProtocolEnvelope(
                message_type="realtime.output_started",
                payload={"output_id": "out-1", "speech_id": "speech-1", "response_id": "resp-1", "item_id": None},
            ),
            ProtocolEnvelope(
                message_type="realtime.audio",
                payload={
                    "pcm_b64": pcm_b64(2),
                    "output_id": "out-1",
                    "speech_id": "speech-1",
                    "response_id": "resp-1",
                    "item_id": "item-1",  # n'existe qu'à partir du premier bloc
                },
            ),
        ],
    )

    cursor = audio.playback_cursor()
    assert cursor is not None
    assert cursor.speech_id == "speech-1"
    assert cursor.provider_item_id == "item-1"
    assert cursor.played_ms == 2 * CHUNK_MS


async def test_the_bridge_resets_the_cursor_on_the_next_output():
    audio = _SilentAudio()
    bridge = _bridge(audio)

    await _feed(
        bridge,
        [
            ProtocolEnvelope(message_type="realtime.output_started", payload={"output_id": "out-1", "speech_id": "speech-1"}),
            ProtocolEnvelope(message_type="realtime.audio", payload={"pcm_b64": pcm_b64(3), "output_id": "out-1", "speech_id": "speech-1"}),
            ProtocolEnvelope(message_type="realtime.output_started", payload={"output_id": "out-2", "speech_id": "speech-2"}),
        ],
    )

    cursor = audio.playback_cursor()
    assert cursor is not None
    assert cursor.speech_id == "speech-2"
    assert cursor.played_ms == 0

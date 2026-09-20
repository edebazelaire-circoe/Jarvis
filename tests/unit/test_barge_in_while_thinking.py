"""Reprendre la main pendant que le cerveau réfléchit (19/09/2026).

Retour à l'oral : « il n'y a que quand tu es en mode parole que j'arrive à
t'interrompre, mais je n'arrive pas à t'interrompre quand tu es en violet ou en
bleu ». Les deux portes du barge-in exigeaient `_output_live()`, c'est-à-dire de
l'audio en train de jouer : un cerveau silencieux ne pouvait pas être coupé, le
tour continuait, et sa réponse tombait ensuite par-dessus la question suivante.

Ces tests font tourner la **vraie** capture duplex (`jarvis.audio.duplex`) sur du
vrai PCM : les compteurs de trames proches, la marge d'énergie et le plancher de
bruit sont ceux du détecteur, pas des valeurs posées à la main. C'est la seule
façon de prouver ensemble les deux moitiés de la correction :

- une vraie voix pendant la réflexion abandonne le tour et rend la main ;
- l'écho seul, pendant la parole, ne coupe toujours rien — la protection du
  18/09/2026 (treize coupures à tort en une journée) reste entière ;
- une réflexion coupée par du silence ne s'abandonne pas davantage.
"""

from __future__ import annotations

import asyncio

from jarvis.audio.duplex import CaptureProcessor, NEAR_END
from jarvis.runtime.realtime_audio import NEAR_END_SIGNAL, SoundDeviceRealtimeAudio
from tests.unit.test_voice_duplex import (
    ControllableSession, RATE, RecordingCore, RecordingJournal, audio_delta, build_bridge,
    event, mix, noise, silence, tone, until,
)

# Fenêtres raccourcies : ce qui est prouvé ici est la décision, pas la patience.
# Les seuils de preuve, eux, gardent leur nature — il faut de vraies
# millisecondes de voix locale et une vraie marge d'énergie pour couper.
SUSTAIN_S = 0.25
MIN_VOICED_MS = 200.0


class CapturedAudio(SoundDeviceRealtimeAudio):
    """Audio sans périphérique, mais avec la vraie capture duplex derrière.

    Tout ce dont le barge-in se sert pour juger — `has_echo_guard`,
    `echo_guard_open`, `near_end_frame_counters`, `near_end_diagnostics` — vient
    donc du détecteur réel, alimenté par du PCM réel.
    """

    def __init__(self, capture: CaptureProcessor) -> None:
        super().__init__(capture=capture)
        self.gains: list[float] = []
        self.stop_output_calls = 0

    def set_output_gain(self, gain: float) -> None:
        self.gains.append(gain)
        super().set_output_gain(gain)

    async def play_b64(self, value: str) -> None:
        import base64

        self._credit_written(self._output_epoch, len(base64.b64decode(value)))

    async def stop_output(self) -> None:
        self.stop_output_calls += 1
        await super().stop_output()

    async def close(self) -> None:
        return None


class Microphone:
    """Pousse du vrai PCM dans la capture, plus vite que le temps réel.

    Le bridge échantillonne sa preuve toutes les 50 ms d'horloge de boucle ; la
    preuve, elle, se compte en trames de 10 ms **intégrées par le détecteur**.
    Pousser 50 ms d'audio tous les 2 ms laisse donc la fenêtre voir passer de
    vraies millisecondes de voix sans faire durer le test.
    """

    BLOCK = 1200  # 50 ms à 24 kHz

    def __init__(self, capture: CaptureProcessor) -> None:
        self.capture = capture
        self.signals = 0
        self._task: asyncio.Task | None = None

    def play(self, mic: bytes, reference: bytes = b"") -> None:
        self._task = asyncio.create_task(self._pump(mic, reference))

    async def _pump(self, mic: bytes, reference: bytes) -> None:
        pushed = 0
        for offset in range(0, len(mic), self.BLOCK * 2):
            while pushed < min(len(reference), (offset + self.BLOCK * 4)):
                self.capture.push_reference(reference[pushed:pushed + self.BLOCK * 2])
                pushed += self.BLOCK * 2
            _out, emitted = self.capture.process(mic[offset:offset + self.BLOCK * 2])
            self.signals += sum(1 for signal in emitted if signal == NEAR_END)
            await asyncio.sleep(0.002)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None


def _bridge(**options):
    capture = CaptureProcessor(capture_rate=RATE, render_rate=RATE)
    audio = CapturedAudio(capture)
    session, journal, core = ControllableSession(), RecordingJournal(), RecordingCore()
    abandoned: list[str | None] = []
    listened: list[bool] = []
    thinking: list[bool] = []
    bridge = build_bridge(
        audio,
        session=session,
        core=core,
        journal=journal,
        on_turn_abandoned=abandoned.append,
        on_brain_pending=thinking.append,
        on_listening=lambda: listened.append(True),
        barge_in_confirm_s=1.5,
        barge_in_sustain_s=SUSTAIN_S,
        barge_in_min_voiced_ms=MIN_VOICED_MS,
        **options,
    )
    return bridge, audio, capture, session, journal, core, abandoned, listened, thinking


async def _consume(bridge):
    queue: asyncio.Queue = asyncio.Queue()

    async def stream():
        while (item := await queue.get()) is not None:
            yield item

    return queue, asyncio.create_task(bridge._consume(stream()))


async def _finish(queue, running, microphone=None):
    if microphone is not None:
        await microphone.stop()
    await queue.put(None)
    await asyncio.wait_for(running, timeout=3.0)


# --------------------------------------------------------------------------
# 1. Le cerveau réfléchit : la main se reprend


async def test_the_brain_holds_the_floor_between_the_submitted_turn_and_its_first_word():
    bridge, *_ = _bridge()

    assert not bridge._brain_floor() and not bridge._floor_live()
    assert await bridge._submit_brain_turn("Jarvis, prépare le rapport", provider_item_id="item-1")

    # Rien ne joue, et pourtant il y a quelque chose à reprendre : c'est
    # exactement la fenêtre pendant laquelle l'interruption n'existait pas.
    assert not bridge._output_live()
    assert bridge._brain_floor() and bridge._floor_live()


async def test_a_real_voice_during_thinking_abandons_the_turn_and_gives_the_floor_back():
    bridge, audio, capture, session, journal, core, abandoned, listened, thinking = _bridge()
    queue, running = await _consume(bridge)
    microphone = Microphone(capture)
    try:
        assert await bridge._submit_brain_turn("Jarvis, prépare le rapport", provider_item_id="item-1")
        correlation_id = core.brain_turns[-1]["correlation_id"]
        # Ce que fait le chemin du transcript juste après un tour accepté :
        # publier « le cerveau doit encore répondre ». C'est le fait d'où la
        # surface tire son violet.
        await bridge._note_brain_pending(True)
        listened.clear()

        # Une vraie voix, à un vrai niveau, dans un vrai silence de JARVIS.
        # Le détecteur de parole proche ne signale rien ici, et c'est normal :
        # son signal ne sert qu'à ouvrir la garde d'écho, qui est déjà ouverte
        # puisque le haut-parleur se tait. La porte, pendant la réflexion, est
        # donc le `speech_started` du fournisseur — et la preuve reste locale.
        microphone.play(mix(silence(0.3) + tone(3.0, amplitude=0.4, freq=180.0), noise(3.3, amplitude=0.001)))
        await until(lambda: capture.voiced_frames >= 10, timeout=3.0)
        await queue.put(event("realtime.speech_started", item_id="user-item"))
        await until(lambda: journal.count("voice.barge_in_confirming") == 1)
        await until(lambda: journal.count("voice.barge_in") == 1, timeout=3.0)

        # Le tour est vraiment abandonné, pas seulement tu : la corrélation part
        # en aval, où la file se purge et Core arrête la tâche du cerveau.
        assert journal.count("voice.brain_turn_abandoned") == 1
        assert abandoned == [correlation_id]
        assert not bridge._brain_floor() and not bridge._floor_live()
        # La main est rendue : le cerveau ne doit plus rien, et l'écran repasse
        # à l'écoute au lieu de rester au violet de la réflexion.
        assert thinking == [True, False]
        assert listened

        # La preuve mesurée était bien locale, et bien tenue.
        rejected = journal.count("voice.barge_in_rejected")
        assert rejected == 0, journal.of("voice.barge_in_rejected")
        assert journal.of("voice.barge_in")[-1]["data"]["speech_id"] is None
        assert bridge._interrupted_speech_id is None  # aucune phrase n'a été coupée

        # Rien n'a été demandé au fournisseur : il ne générait pas.
        assert "truncate" not in session.calls
        assert journal.count("voice.barge_in_degraded") == 0
    finally:
        await _finish(queue, running, microphone)


async def test_silence_during_thinking_never_abandons_the_turn():
    """Le pendant négatif du cas précédent : sans voix, pas d'abandon.

    Un `speech_started` du fournisseur suivi d'un `speech_stopped` — le profil
    d'un faux départ — ne doit pas suffire. La décision prise sur une fin de
    parole pendant la réflexion reste adossée à la preuve locale.
    """

    bridge, audio, capture, session, journal, core, abandoned, listened, thinking = _bridge()
    queue, running = await _consume(bridge)
    microphone = Microphone(capture)
    try:
        assert await bridge._submit_brain_turn("Jarvis, prépare le rapport", provider_item_id="item-1")
        microphone.play(mix(silence(2.0), noise(2.0, amplitude=0.0005)))
        await until(lambda: capture.processed_frames >= 10, timeout=3.0)
        await queue.put(event("realtime.speech_started", item_id="ghost"))
        await until(lambda: journal.count("voice.barge_in_confirming") == 1)
        await queue.put(event("realtime.speech_stopped", item_id="ghost"))
        await until(lambda: journal.count("voice.barge_in_rejected") == 1)
        await asyncio.sleep(0.4)

        assert journal.count("voice.barge_in") == 0
        assert abandoned == []
        assert bridge._brain_floor()  # le cerveau garde la main, il n'a pas fini
        assert journal.of("voice.barge_in_rejected")[-1]["data"]["code"] == "barge_in_local_voice_too_short"
    finally:
        await _finish(queue, running, microphone)


# --------------------------------------------------------------------------
# 2. Pendant la parole, la protection anti-écho du 18/09 reste entière


async def test_jarvis_own_echo_still_does_not_interrupt_him_while_he_speaks():
    """Le scénario du 18/09/2026, rejoué sur la vraie capture.

    L'écho résiduel ouvre un candidat, la garde s'ouvre, le VAD du fournisseur
    « confirme » — et rien ne doit être coupé, parce qu'aucune trame proche n'a
    été comptée pendant la fenêtre. Ouvrir le barge-in à la réflexion ne devait
    rien relâcher ici : ce test le vérifie.
    """

    bridge, audio, capture, session, journal, core, abandoned, listened, thinking = _bridge()
    queue, running = await _consume(bridge)
    microphone = Microphone(capture)
    try:
        await queue.put(event("realtime.output_started", output_id="out-1", speech_id="out-1"))
        await queue.put(audio_delta(40, output_id="out-1", speech_id="out-1", item_id="item-1", content_index=0))
        await until(lambda: bridge._playing)

        # JARVIS parle ; le micro ne reçoit que sa propre voix, atténuée.
        reference = tone(3.0, amplitude=0.3)
        microphone.play(mix(tone(3.0, amplitude=0.02), noise(3.0, amplitude=0.001)), reference)
        await asyncio.sleep(0.05)
        bridge._on_capture_signal(NEAR_END_SIGNAL)
        await until(lambda: journal.count("voice.barge_in_pending") == 1)
        await queue.put(event("realtime.speech_started", item_id="echo-item"))
        await until(lambda: journal.count("voice.barge_in_confirming") == 1)
        await until(lambda: journal.count("voice.barge_in_rejected") == 1, timeout=3.0)
        await asyncio.sleep(0.2)

        assert journal.count("voice.barge_in") == 0
        assert audio.stop_output_calls == 0 and "cancel_output" not in session.calls
        assert abandoned == []
        # Le volume est rendu : une fin de phrase ne reste pas atténuée.
        assert audio.gains[-1] == 1.0
        assert journal.of("voice.barge_in_rejected")[-1]["data"]["code"].startswith("barge_in_local_voice")
    finally:
        await _finish(queue, running, microphone)


async def test_the_brain_floor_is_released_once_the_brain_speaks():
    """La main revient au chemin audio dès que le cerveau ouvre la bouche.

    Sans cela, la porte de la réflexion resterait ouverte pendant toute la
    phrase, et un tour sans réponse armerait le micro indéfiniment.
    """

    bridge, audio, capture, session, journal, core, abandoned, listened, thinking = _bridge()
    queue, running = await _consume(bridge)
    try:
        assert await bridge._submit_brain_turn("Jarvis, prépare le rapport", provider_item_id="item-1")
        assert bridge._brain_floor()

        # Un réflexe de surface (sans `speech_id`) ne dit rien du cerveau.
        await queue.put(event("realtime.response_done", output_id="reflex-1", status="completed"))
        await bridge.wait_idle()
        assert bridge._brain_floor()

        # La parole du cerveau, elle, rend la main.
        await queue.put(event("realtime.response_done", output_id="out-1", speech_id="speech-1", status="completed"))
        await until(lambda: not bridge._brain_floor())
        assert not bridge._floor_live()
    finally:
        await _finish(queue, running)

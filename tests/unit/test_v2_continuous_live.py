"""Cycle de vie LIVE continu : une session ACTIVE couvre plusieurs tours.

Ce fichier prouve le contrat introduit par la Décision 08. Le contrat inverse —
une réponse terminée rend la main au mot d'éveil — reste prouvé en mode legacy
dans `test_v2_voice_toggle.py`, qui n'est pas rendu obsolète par celui-ci.

Ce qui n'est **pas** prouvé ici : le comportement acoustique. Garder le micro
ouvert pendant que les haut-parleurs jouent expose un risque de larsen que
seul un poste réel peut mesurer. Aucun test de ce fichier n'affirme que l'écho
est traité ; le mode legacy reste le repli half-duplex.
"""

from __future__ import annotations

import asyncio
import base64
import threading
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.domain.errors import ConfigurationError
from jarvis.domain.v2 import PlaybackCursor, ProtocolEnvelope, SpeechRequest, VoiceLifecycleState
from jarvis.runtime.realtime_audio import SoundDeviceRealtimeAudio
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture, parse_voice_arch

TIMEOUT_S = 1.0


class FakeClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class FakeWakeWord:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.resumed = asyncio.Event()
        self.suspensions = 0
        self.closed = False

    async def detections(self):
        while not self.closed:
            yield await self.queue.get()

    async def suspend(self) -> None:
        return None

    async def suspend_for_active_session(self) -> None:
        self.suspensions += 1

    async def resume(self) -> None:
        self.resumed.set()

    async def close(self) -> None:
        self.closed = True


class FakeCore:
    """Core vu depuis Voice, avec un travail en cours qu'un mute ne doit pas toucher."""

    def __init__(self) -> None:
        self.turns: list[tuple[str, str]] = []
        self.brain_turns: list[dict[str, object]] = []
        self.jobs = {"job-1": "running"}
        self.cancel_calls: list[str] = []
        self.closed = False
        # `/v1/events` : en mode continu l'ordonnanceur de parole s'y abonne
        # pendant toute la session. Ce flux reste ouvert et muet tant que le
        # test ne pousse rien — la restitution de la parole du cerveau est
        # prouvée dans `test_v2_speech_scheduler.py`.
        self.core_events: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()
        self.event_subscriptions = 0

    async def create_conversation(self) -> dict[str, str]:
        return {"id": "conversation-1"}

    async def context(self, conversation_id: str) -> dict[str, object]:
        del conversation_id
        return {}

    async def append_turn(self, conversation_id: str, *, kind: str, content: str, correlation_id=None, metadata=None) -> None:  # noqa: ANN001
        del conversation_id, correlation_id, metadata
        self.turns.append((kind, content))

    async def events(self):
        self.event_subscriptions += 1
        while True:
            event = await self.core_events.get()
            if event is None:
                return
            yield event

    async def submit_brain_turn(self, conversation_id: str, *, content: str, correlation_id: str, source: str = "realtime", addressing: str = "addressed", provider_item_id=None, interrupted_speech_id=None) -> dict[str, object]:  # noqa: ANN001
        """Ingress cerveau : c'est par là que passe un tour utilisateur en continu."""
        self.brain_turns.append({"conversation_id": conversation_id, "content": content, "correlation_id": correlation_id, "source": source, "addressing": addressing, "provider_item_id": provider_item_id, "interrupted_speech_id": interrupted_speech_id})
        return {"turn_id": f"turn-{len(self.brain_turns)}", "correlation_id": correlation_id, "revision": len(self.brain_turns), "duplicate": False}

    async def call_tool(self, name: str, arguments: dict[str, object], *, conversation_id: str) -> dict[str, object]:
        del arguments, conversation_id
        if name == "cancel_job":
            self.cancel_calls.append(name)
        return {"ok": True}

    async def close(self) -> None:
        self.closed = True


class ContinuousSession:
    """Pile capable de piloter sa sortie : elle satisfait `RealtimeOutputControl`.

    Le flux d'évènements est piloté par le test, ce qui permet d'enchaîner
    plusieurs tours sur la même session sans dépendre d'un fournisseur.
    """

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()
        self.closed = False
        self.finish_calls = 0
        self.cancelled_outputs: list[PlaybackCursor | None] = []
        self.audio_bytes = 0

    async def send_audio(self, pcm: bytes) -> None:
        self.audio_bytes += len(pcm)

    async def finish_input(self) -> bool:
        self.finish_calls += 1
        return True

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        del call_id, result

    async def send_context(self, text: str) -> None:
        del text

    async def keepalive(self) -> None:
        return None

    async def speak(self, request: SpeechRequest) -> str:
        return f"out-{request.id}"

    async def cancel_output(self, cursor: PlaybackCursor | None = None) -> None:
        self.cancelled_outputs.append(cursor)

    async def truncate(self, cursor: PlaybackCursor) -> None:
        del cursor

    async def events(self):
        while True:
            event = await self.inbox.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        self.closed = True

    async def push(self, message_type: str, **payload: object) -> None:
        await self.inbox.put(ProtocolEnvelope(message_type=message_type, payload=payload))


class NoOutputControlSession:
    """`RealtimeSession` complet, sans speak/cancel_output/truncate.

    C'est la forme de Gemini Live aujourd'hui, qui reste sur le chemin legacy
    (Décision 21).
    """

    def __init__(self) -> None:
        self.closed = False

    async def send_audio(self, pcm: bytes) -> None:
        del pcm

    async def finish_input(self) -> bool:
        return True

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        del call_id, result

    async def send_context(self, text: str) -> None:
        del text

    async def events(self):
        while True:
            await asyncio.sleep(3600)
            yield  # pragma: no cover - jamais atteint

    async def close(self) -> None:
        self.closed = True


class FakeAudio(SoundDeviceRealtimeAudio):
    """Micro observable : on veut voir quand — et si — l'entrée est fermée."""

    instances: list["FakeAudio"] = []
    pcm = b"\x01\x00" * 2400

    def __init__(self, *, input_device=None, output_device=None, **rates) -> None:  # noqa: ANN001
        super().__init__(input_device=input_device, output_device=output_device, **rates)
        self.started = asyncio.Event()
        self.stop_input_calls = 0
        self.closed = False
        self.__class__.instances.append(self)

    async def start(self) -> None:
        self._enqueue(self.pcm)
        self.started.set()

    async def stop_input(self) -> None:
        self.stop_input_calls += 1
        await super().stop_input()

    async def play_b64(self, value: str) -> None:
        del value

    async def close(self) -> None:
        self.closed = True


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.changed = asyncio.Event()

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})
        self.changed.set()

    def count(self, kind: str) -> int:
        return sum(1 for event in self.events if event["kind"] == kind)

    async def wait_until(self, predicate) -> None:
        """Attendre qu'un jalon soit journalisé, sans dormir en temps réel."""

        while True:
            self.changed.clear()
            if predicate():
                return
            await asyncio.wait_for(self.changed.wait(), timeout=TIMEOUT_S)


class RecordingSignals:
    def __init__(self) -> None:
        self.states: list[str] = []
        self.alerts: list[str | None] = []

    def state(self, value: str) -> None:
        self.states.append(value)

    def alert(self, message: str | None) -> None:
        self.alerts.append(message)

    def heartbeat(self) -> None:
        return None

    def offline(self) -> None:
        return None


def _runtime(monkeypatch, *, session, clock=None, journal=None, signals=None, timeout_s=90.0):
    import jarvis.runtime.realtime_audio as realtime_audio

    FakeAudio.instances.clear()
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)

    async def factory(context):
        del context
        return session

    wakeword = FakeWakeWord()
    core = FakeCore()
    runtime = PersistentVoiceRuntime(
        wakeword=wakeword,  # type: ignore[arg-type]
        core=core,  # type: ignore[arg-type]
        realtime_factory=factory,  # type: ignore[arg-type]
        active_timeout_s=timeout_s,
        clock=clock,
        signals=signals,  # type: ignore[arg-type]
        journal=journal,  # type: ignore[arg-type]
        auto_turn=True,
        voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN,
    )
    return runtime, wakeword, core


async def _wake(runtime, wakeword, journal):
    run_task = asyncio.create_task(runtime.run())
    await wakeword.queue.put("f9")
    await journal.wait_until(lambda: journal.count("audio.start") == 1)
    return run_task


async def _play_one_turn(session: ContinuousSession) -> None:
    await session.push("realtime.input_committed", item_id="item-1")
    await session.push("realtime.audio", pcm_b64="")
    await session.push("realtime.audio_done")
    await session.push("realtime.response_done", status="completed")


async def test_one_wake_and_two_turns_keep_the_session_active(monkeypatch):
    """Décision 08 : `response.done` ne vaut plus `mute()`.

    Un seul éveil, une seule session, un seul micro — et deux tours complets.
    """
    session = ContinuousSession()
    journal = RecordingJournal()
    signals = RecordingSignals()
    runtime, wakeword, _ = _runtime(monkeypatch, session=session, journal=journal, signals=signals)
    run_task = await _wake(runtime, wakeword, journal)
    try:
        await _play_one_turn(session)
        await journal.wait_until(lambda: journal.count("voice.turn_completed") == 1)
        assert runtime.runtime.state is VoiceLifecycleState.ACTIVE

        await _play_one_turn(session)
        await journal.wait_until(lambda: journal.count("voice.turn_completed") == 2)

        assert runtime.runtime.state is VoiceLifecycleState.ACTIVE
        assert journal.count("voice.input_submitted") == 2
        assert journal.count("voice.background") == 0
        # Une seule session, un seul micro, jamais refermé entre les tours.
        assert session.closed is False
        assert session.finish_calls == 0
        assert len(FakeAudio.instances) == 1
        assert FakeAudio.instances[0].stop_input_calls == 0
        assert FakeAudio.instances[0].closed is False
        # Le fond n'est jamais réaffiché : on repasse en écoute après chaque tour.
        assert signals.states == [
            "idle", "thinking", "listening",
            "thinking", "speaking", "listening",
            "thinking", "speaking", "listening",
        ]
        assert wakeword.suspensions == 1
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_a_response_without_its_own_commit_still_returns_to_listening(monkeypatch):
    """La projection ne doit pas rester bloquée sur « speaking ».

    En continu, le VAD serveur peut interrompre une réponse : la réponse
    suivante n'a alors plus de commit qui lui corresponde. Se fier au drapeau
    de commit laisserait le visage en train de parler pour toujours.
    """
    session = ContinuousSession()
    journal = RecordingJournal()
    signals = RecordingSignals()
    runtime, wakeword, _ = _runtime(monkeypatch, session=session, journal=journal, signals=signals)
    run_task = await _wake(runtime, wakeword, journal)
    try:
        await session.push("realtime.audio", pcm_b64="")
        await session.push("realtime.audio_done")
        await session.push("realtime.response_done", status="completed")
        await journal.wait_until(lambda: journal.count("voice.turn_completed") == 1)

        assert runtime.runtime.state is VoiceLifecycleState.ACTIVE
        assert signals.states[-1] == "listening"
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_jarvis_mute_returns_to_background_without_touching_core_work(monkeypatch):
    """Décision 11 : mute est une commande d'état vocal, pas d'annulation."""
    session = ContinuousSession()
    journal = RecordingJournal()
    runtime, wakeword, core = _runtime(monkeypatch, session=session, journal=journal)
    run_task = await _wake(runtime, wakeword, journal)
    try:
        await _play_one_turn(session)
        await journal.wait_until(lambda: journal.count("voice.turn_completed") == 1)

        await session.push("realtime.transcript", text="Jarvis mute")
        await asyncio.wait_for(wakeword.resumed.wait(), timeout=TIMEOUT_S)

        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert session.closed is True
        # Le mute rend la main sans attendre le bridge : celui-ci ferme le micro
        # en sortant de sa boucle, et c'est ce jalon qui atteste l'extinction.
        await journal.wait_until(lambda: journal.count("audio.stop") == 1)
        assert FakeAudio.instances[0].closed is True
        # Le mute n'est pas une demande : il ne part pas au cerveau, y compris
        # depuis que les tours incertains y partent (Décision 44).
        assert core.brain_turns == []
        # Le travail de Core continue : rien n'a été annulé, rien n'a été fermé.
        assert core.jobs == {"job-1": "running"}
        assert core.cancel_calls == []
        assert core.closed is False
        # La conversation survit au mute : le prochain éveil la reprend.
        assert runtime.runtime.conversation_id == "conversation-1"
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_useful_inactivity_timeout_returns_to_background(monkeypatch):
    session = ContinuousSession()
    journal = RecordingJournal()
    clock = FakeClock()
    runtime, wakeword, core = _runtime(
        monkeypatch, session=session, journal=journal, clock=clock, timeout_s=10
    )
    run_task = await _wake(runtime, wakeword, journal)
    try:
        clock.advance(11)
        assert await runtime.check_timeout() is True
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert session.closed is True
        assert core.closed is False
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_a_zero_timeout_keeps_the_session_until_the_wake_key(monkeypatch):
    """« Le mode vocal doit rester continu tant que je n'ai pas éteint la
    conversation avec F9. » Délai à 0 : des heures de silence ne rendent pas la
    main, la touche de réveil si."""
    session = ContinuousSession()
    journal = RecordingJournal()
    clock = FakeClock()
    runtime, wakeword, core = _runtime(
        monkeypatch, session=session, journal=journal, clock=clock, timeout_s=0
    )
    run_task = await _wake(runtime, wakeword, journal)
    try:
        await _play_one_turn(session)
        await journal.wait_until(lambda: journal.count("voice.turn_completed") == 1)

        for _ in range(3):
            clock.advance(3 * 3600)
            assert await runtime.check_timeout() is False
        assert runtime.runtime.state is VoiceLifecycleState.ACTIVE
        assert session.closed is False
        assert FakeAudio.instances[0].stop_input_calls == 0
        assert journal.count("voice.timeout") == 0
        assert journal.count("voice.timeout_deferred") == 0
        assert journal.count("voice.background") == 0

        await wakeword.queue.put("f9")
        await asyncio.wait_for(wakeword.resumed.wait(), timeout=TIMEOUT_S)

        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert journal.count("voice.manual_cancel") == 1
        assert session.closed is True
        # Rendre la main ne coupe toujours pas le travail de Core (Décision 11).
        assert core.closed is False
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_ambient_speech_and_partial_transcripts_do_not_rearm_the_timeout(monkeypatch):
    """Décision 10 : le silence de la pièce n'est pas le critère.

    Une transcription partielle est une observation révisable (Décision 07) et
    une phrase ambiante n'est adressée à personne : ni l'une ni l'autre ne
    prolonge la session.

    Depuis la Décision 44, cette longue phrase est **routée** vers le cerveau au
    lieu d'être jetée — et ce test devient la preuve que router et réarmer
    restent deux choses distinctes : le tour part, le minuteur ne bouge pas, la
    session rend la main à l'échéance.
    """
    session = ContinuousSession()
    journal = RecordingJournal()
    clock = FakeClock()
    runtime, wakeword, core = _runtime(
        monkeypatch, session=session, journal=journal, clock=clock, timeout_s=10
    )
    run_task = await _wake(runtime, wakeword, journal)
    try:
        clock.advance(8)
        for text in ("il", "il fait", "il fait beau"):
            await session.push("realtime.transcript_delta", text=text, item_id="item-1")
        ambient = "une longue conversation ambiante entre plusieurs personnes qui ne concerne pas du tout l'assistant"
        await session.push("realtime.transcript", text=ambient)
        await journal.wait_until(
            lambda: any(
                event["kind"] == "voice.transcript" and event["data"].get("addressing") != "addressed"
                for event in journal.events
            )
        )
        await journal.wait_until(lambda: journal.count("voice.brain_turn_submitted") == 1)

        # Le tour est bien parti au cerveau, marqué du doute (Décision 44)...
        assert [(turn["content"], turn["addressing"]) for turn in core.brain_turns] == [
            (ambient, "uncertain")
        ]

        # ... et pourtant le minuteur n'a pas bougé (Décision 10).
        clock.advance(3)
        assert runtime.activity.expired() is True
        assert await runtime.check_timeout() is True
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_an_addressed_turn_rearms_the_timeout(monkeypatch):
    """Le pendant du test précédent : ce qui compte, c'est d'être adressé."""
    session = ContinuousSession()
    journal = RecordingJournal()
    clock = FakeClock()
    runtime, wakeword, core = _runtime(
        monkeypatch, session=session, journal=journal, clock=clock, timeout_s=10
    )
    run_task = await _wake(runtime, wakeword, journal)
    try:
        clock.advance(8)
        await session.push("realtime.transcript", text="Et demain ?")
        # En continu, un tour adressé part vers l'ingress cerveau, pas vers
        # `append_turn()` : c'est le chemin unique de la Décision 30.
        await journal.wait_until(lambda: [t["content"] for t in core.brain_turns] == ["Et demain ?"])

        clock.advance(3)
        assert runtime.activity.expired() is False
        assert await runtime.check_timeout() is False
        assert runtime.runtime.state is VoiceLifecycleState.ACTIVE
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_jarvis_speaking_counts_as_useful_activity(monkeypatch):
    """Une sortie vocale ouverte rend du temps à l'utilisateur (Décision 10)."""
    session = ContinuousSession()
    journal = RecordingJournal()
    clock = FakeClock()
    runtime, wakeword, _ = _runtime(
        monkeypatch, session=session, journal=journal, clock=clock, timeout_s=10
    )
    run_task = await _wake(runtime, wakeword, journal)
    try:
        clock.advance(8)
        await session.push("realtime.output_started", output_id="out-1", speech_id="speech-1")
        await journal.wait_until(lambda: journal.count("voice.output_started") == 1)

        clock.advance(3)
        assert runtime.activity.expired() is False
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_user_speech_interrupts_jarvis_and_marks_the_next_turn(monkeypatch):
    """Tâche 09c, câblage complet : du VAD serveur jusqu'à l'ingress cerveau.

    Les détails de la séquence sont éprouvés dans `test_v2_barge_in.py` ; ce
    qui se joue ici est le fil de bout en bout — le runtime relie bien le
    bridge, l'ordonnanceur de parole et Core — et le fait que la session
    survive à l'interruption au lieu de se refermer.
    """
    session = ContinuousSession()
    journal = RecordingJournal()
    runtime, wakeword, core = _runtime(monkeypatch, session=session, journal=journal)
    run_task = await _wake(runtime, wakeword, journal)
    try:
        await session.push("realtime.output_started", output_id="out-1", speech_id="speech-1", response_id="resp-1")
        await session.push("realtime.audio", pcm_b64="", output_id="out-1", speech_id="speech-1", item_id="item-1")
        await journal.wait_until(lambda: journal.count("voice.output_started") == 1)

        await session.push("realtime.speech_started")
        await journal.wait_until(lambda: journal.count("voice.barge_in") == 1)

        await session.push("realtime.transcript", text="Jarvis, oublie ça et lis mes messages.", item_id="item-2")
        await journal.wait_until(lambda: journal.count("voice.brain_turn_submitted") == 1)

        assert core.brain_turns[-1]["interrupted_speech_id"] == "speech-1"
        assert [cursor.speech_id for cursor in session.cancelled_outputs] == ["speech-1"]
        # Le micro n'a pas été refermé : c'est tout l'intérêt de `stop_output()`.
        assert FakeAudio.instances[0].stop_input_calls == 0
        assert FakeAudio.instances[0].closed is False
        assert session.closed is False
        # Aucune annulation de travail n'est partie de la surface (Décision 35).
        assert core.cancel_calls == []
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_continuous_mode_refuses_a_stack_without_output_control(monkeypatch):
    """Décisions 21 et 22 : pas de dégradation silencieuse vers le legacy."""
    session = NoOutputControlSession()
    journal = RecordingJournal()
    signals = RecordingSignals()
    runtime, _, _ = _runtime(monkeypatch, session=session, journal=journal, signals=signals)

    with pytest.raises(ConfigurationError, match="ne sait pas piloter la sortie audio"):
        await runtime.activate()

    assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
    assert session.closed is True
    refusal = next(event for event in journal.events if event["kind"] == "voice.arch_unsupported")
    assert refusal["level"] == "error"
    assert refusal["data"]["code"] == "voice_arch_stack_without_output_control"
    assert "legacy" in str(signals.alerts[-1])


def test_continuous_mode_refuses_manual_turn_taking():
    """Le mode continu suppose un découpage des tours par le fournisseur.

    En mode manuel, un tour se termine en fermant le flux d'entrée ; enchaîner
    demanderait de rouvrir PortAudio à chaque tour. On refuse plutôt que de
    faire semblant.
    """
    with pytest.raises(ConfigurationError, match="mode de tour automatique"):
        PersistentVoiceRuntime(
            wakeword=None,  # type: ignore[arg-type]
            core=None,  # type: ignore[arg-type]
            realtime_factory=None,  # type: ignore[arg-type]
            auto_turn=False,
            voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN,
        )


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, VoiceArchitecture.LEGACY),
        ("", VoiceArchitecture.LEGACY),
        ("legacy", VoiceArchitecture.LEGACY),
        (" Continuous_Brain ", VoiceArchitecture.CONTINUOUS_BRAIN),
    ],
)
def test_voice_arch_parsing_defaults_to_legacy(raw, expected):
    assert parse_voice_arch(raw) is expected


def test_voice_arch_rejects_unknown_values():
    with pytest.raises(ConfigurationError, match="JARVIS_VOICE_ARCH"):
        parse_voice_arch("continuous")


def test_settings_default_to_the_legacy_voice_architecture(monkeypatch, tmp_path):
    from jarvis.v2_config import V2Settings

    monkeypatch.delenv("JARVIS_VOICE_ARCH", raising=False)
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))

    assert V2Settings.load().voice_arch is VoiceArchitecture.LEGACY


async def test_audio_close_never_frees_the_stream_under_a_running_write():
    """L'invariant d'extinction PortAudio, que le mode continu ne doit pas casser.

    Le thread de lecture survit à l'annulation de la tâche qui l'a lancé.
    Libérer le flux pendant qu'il écrit est une violation d'accès qui tue le
    processus sans qu'aucun `except` ne s'exécute : `close()` doit donc attendre
    la fin du bloc en cours avant d'appeler `abort()`.
    """
    audio = SoundDeviceRealtimeAudio()

    class BlockingOutputStream:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.writing = threading.Event()
            self.release = threading.Event()

        def write(self, data) -> None:  # noqa: ANN001
            del data
            self.calls.append("write:start")
            self.writing.set()
            assert self.release.wait(timeout=5)
            self.calls.append("write:end")

        def abort(self) -> None:
            self.calls.append("abort")

        def stop(self) -> None:  # pragma: no cover - la sortie utilise abort()
            self.calls.append("stop")

        def close(self) -> None:
            self.calls.append("close")

    stream = BlockingOutputStream()
    audio._output = stream
    playback = asyncio.create_task(audio.play_b64(base64.b64encode(b"\x00" * 4800).decode()))
    await asyncio.to_thread(stream.writing.wait, 5)

    closing = asyncio.create_task(audio.close())
    await asyncio.sleep(0)
    # Le verrou est tenu par le thread de lecture : la fermeture doit attendre.
    assert not closing.done()
    assert "abort" not in stream.calls

    stream.release.set()
    await asyncio.wait_for(playback, timeout=5)
    await asyncio.wait_for(closing, timeout=5)

    assert stream.calls == ["write:start", "write:end", "abort", "close"]

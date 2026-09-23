"""Slice 05 - capture partagée de PRESENTATION et lane d'adresse explicite.

Ce que cette suite doit prouver, et la manière dont elle le prouve :

- « exactement un propriétaire physique de l'entrée » est **compté**
  (`jarvis.audio.input_ownership`), jamais affirmé en prose ;
- chaque phrase d'en-tête de la forme « X ne peut jamais arriver » a son test à
  l'endroit exact où elle se casserait (leçon des quatre blocages de la
  Slice 04) ;
- aucun test n'inspecte du texte source : uniquement des comportements et des
  valeurs (leçon des trois tests de la Slice 03) ;
- **le vrai micro n'est jamais ouvert.** Aucun `sounddevice` réel n'est importé
  par les chemins exercés ici ; la fabrique de flux est injectée.
"""

from __future__ import annotations

import array
import asyncio
import math
import sys
import time

import pytest

from jarvis.adapters.wakeword_keyboard import KeyboardWakeWordBackend
from jarvis.adapters.wakeword_shared_pcm import SharedPcmWakeWordBackend
from jarvis.audio import input_ownership
from jarvis.audio.capture_hub import (
    MAX_CONSECUTIVE_SINK_FAILURES,
    MAX_PREROLL_MS,
    MAX_SUBSCRIBER_BLOCKS,
    SINK_FAILURE_WINDOW_S,
    AudioCaptureHub,
    AudioCaptureHubError,
    CaptureHubState,
    PreRollRing,
)
from jarvis.audio.resampling import StreamingPcm16Resampler
from jarvis.domain.explicit_address import (
    MAX_TRIGGER_AGE_S,
    ExplicitAddressError,
    ExplicitAddressSource,
    ExplicitAddressTrigger,
)
from jarvis.adapters.wakeword_shared_pcm import WakeWordDetectorFailed
from jarvis.runtime.explicit_address_lane import (
    DEFAULT_LANE_QUEUE_SIZE,
    ExplicitAddressLane,
    ExplicitAddressLaneClosed,
)
from jarvis.runtime.presentation_audio import (
    CommandPreRoll,
    PresentationAudioError,
    PresentationAudioSession,
)
from jarvis.runtime.realtime_audio import SoundDeviceRealtimeAudio

HUB_RATE = 24000
BLOCK_FRAMES = 1200  # 50 ms
BLOCK = b"\x11\x22" * BLOCK_FRAMES


@pytest.fixture(autouse=True)
def clean_input_registry():
    """Le compteur de propriétaires est un état de processus : sans remise à
    zéro, un test qui échoue laisserait un propriétaire fantôme et le verdict
    du test suivant ne voudrait plus rien dire."""

    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


class RecordingJournal:
    """Journal en mémoire. Ce qui compte est ce qui a été **dit**, pas où."""

    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:  # noqa: ANN001
        self.entries.append({"kind": kind, "message": message, "level": level, "data": data or {}})

    def codes(self, level: str | None = None) -> list[str]:
        return [
            str(entry["data"].get("code"))  # type: ignore[union-attr]
            for entry in self.entries
            if (level is None or entry["level"] == level) and entry["data"].get("code")  # type: ignore[union-attr]
        ]

    def kinds(self) -> list[str]:
        return [str(entry["kind"]) for entry in self.entries]

    def of_kind(self, kind: str) -> list[dict[str, object]]:
        return [entry for entry in self.entries if entry["kind"] == kind]


class FakeCaptureDevice:
    """Un périphérique d'entrée faux : il compte ses ouvertures et pousse ce
    qu'on lui donne, dans le thread appelant."""

    def __init__(self, *, fail_with: BaseException | None = None) -> None:
        self.fail_with = fail_with
        self.opens = 0
        self.callback = None
        self.stopped = 0
        self.closed = 0
        self.samplerate: int | None = None
        self.blocksize: int | None = None

    def factory(self, *, samplerate, channels, dtype, device, blocksize, callback):  # noqa: ANN001
        if self.fail_with is not None:
            raise self.fail_with
        self.opens += 1
        self.samplerate, self.blocksize, self.callback = samplerate, blocksize, callback
        return self

    # Forme `sounddevice` attendue par `_shutdown_input_stream`.
    def stop(self) -> None:
        self.stopped += 1

    def close(self) -> None:
        self.closed += 1

    def push(self, block: bytes = BLOCK) -> None:
        assert self.callback is not None, "le flux n'a pas été ouvert"
        self.callback(block, len(block) // 2, None, None)


class PortAudioError(Exception):
    """Même forme que l'erreur de sounddevice : (message, code)."""


class FakeOutputStream:
    """Sortie factice. Aucun test de cette suite ne touche un vrai haut-parleur."""

    def start(self) -> None: ...
    def stop(self, *, ignore_errors=True) -> None: ...
    def abort(self, *, ignore_errors=True) -> None: ...
    def close(self, *, ignore_errors=True) -> None: ...
    def write(self, pcm) -> None: ...  # noqa: ANN001


class OutputOnlySoundDevice:
    """`sounddevice` double : la sortie est factice, l'entrée est interdite.

    Utilisé partout où le chemin interactif tourne sur la capture partagée.
    L'entrée lève plutôt que de rendre un objet : si un jour le raccord
    régresse et rouvre un micro, le test doit tomber, pas passer.
    """

    @staticmethod
    def RawInputStream(**kwargs):  # noqa: ANN003
        raise AssertionError("aucun flux d'entrée ne doit être ouvert ici")

    @staticmethod
    def RawOutputStream(**kwargs):  # noqa: ANN003
        return FakeOutputStream()


class FakeWakeEngine:
    """Moteur de mot d'éveil faux : détecte au n-ième appel de `process`."""

    def __init__(self, *, sample_rate: int = 16000, frame_length: int = 512,
                 detect_after: int | None = None, raise_after: int | None = None) -> None:
        self.sample_rate = sample_rate
        self.frame_length = frame_length
        self.detect_after = detect_after
        self.raise_after = raise_after
        self.calls = 0
        self.frames: list[tuple[int, ...]] = []
        self.deleted = 0

    def process(self, pcm) -> int:  # noqa: ANN001
        self.calls += 1
        self.frames.append(tuple(pcm))
        if self.raise_after is not None and self.calls >= self.raise_after:
            raise RuntimeError("porcupine exploded")
        if self.detect_after is not None and self.calls >= self.detect_after:
            return 0
        return -1

    def delete(self) -> None:
        self.deleted += 1


class FakeTriggerBackend:
    """Source d'adresse explicite pilotée par un test."""

    def __init__(self, *, label: str = "f9", raise_with: BaseException | None = None) -> None:
        self.label = label
        self.raise_with = raise_with
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.suspended = False
        self.active_session_suspended = False
        self.resumed = False
        self.closed = False

    async def detections(self):
        if self.raise_with is not None:
            raise self.raise_with
        while not self.closed:
            yield await self.queue.get()

    async def suspend(self) -> None:
        self.suspended = True

    async def suspend_for_active_session(self) -> None:
        self.active_session_suspended = True

    async def resume(self) -> None:
        self.resumed = True

    async def close(self) -> None:
        self.closed = True


def make_hub(device: FakeCaptureDevice, **kwargs) -> AudioCaptureHub:
    kwargs.setdefault("sample_rate", HUB_RATE)
    kwargs.setdefault("block_frames", BLOCK_FRAMES)
    return AudioCaptureHub(stream_factory=device.factory, **kwargs)


async def until(predicate, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition jamais atteinte"
        await asyncio.sleep(0.005)


def sine_block(frames: int, rate: int, hz: float = 440.0) -> bytes:
    return array.array(
        "h", [int(8000 * math.sin(2 * math.pi * hz * i / rate)) for i in range(frames)]
    ).tobytes()


# --------------------------------------------------------------------------
# 1. Exactement un propriétaire physique de l'entrée, compté
# --------------------------------------------------------------------------


async def test_presentation_holds_exactly_one_physical_input_owner_and_the_count_says_so(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", OutputOnlySoundDevice)
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(),
        wake_engine_factory=lambda: FakeWakeEngine(),
        stream_factory=device.factory,
        sample_rate=HUB_RATE,
        block_frames=BLOCK_FRAMES,
    )
    assert input_ownership.open_input_stream_count() == 0

    await session.start()
    try:
        # Le hub a ouvert un flux, le détecteur de mot d'éveil aucun, et le
        # chemin interactif branché sur la capture partagée aucun non plus.
        assert device.opens == 1
        assert session.physical_input_owners() == 1
        assert [entry.owner for entry in input_ownership.open_input_streams()] == [
            input_ownership.OWNER_CAPTURE_HUB
        ]
        assert session.wake is not None and session.wake.opens_input_stream is False

        audio = SoundDeviceRealtimeAudio(input_source=session.realtime_input_source())
        await audio.start()
        assert device.opens == 1, "le chemin interactif a ouvert un second micro"
        assert session.physical_input_owners() == 1
        await audio.close()
    finally:
        await session.stop()
    assert session.physical_input_owners() == 0
    assert device.stopped == 1 and device.closed == 1


async def test_the_interactive_path_with_a_shared_source_opens_no_sounddevice_stream(monkeypatch):
    """Preuve par le module : `sd.RawInputStream` n'est pas appelé du tout."""

    constructed: list[str] = []

    class FakeOutput:
        def start(self) -> None: ...
        def stop(self, *, ignore_errors=True) -> None: ...
        def abort(self, *, ignore_errors=True) -> None: ...
        def close(self, *, ignore_errors=True) -> None: ...
        def write(self, pcm) -> None: ...  # noqa: ANN001

    class FakeSoundDevice:
        @staticmethod
        def RawInputStream(**kwargs):  # noqa: ANN003
            constructed.append("input")
            raise AssertionError("aucun flux d'entrée ne doit être ouvert ici")

        @staticmethod
        def RawOutputStream(**kwargs):  # noqa: ANN003
            constructed.append("output")
            return FakeOutput()

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)
    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    audio = SoundDeviceRealtimeAudio(input_source=hub.attach_input)
    await audio.start()

    assert constructed == ["output"]
    assert input_ownership.open_input_stream_count(input_ownership.OWNER_REALTIME_AUDIO) == 0
    assert input_ownership.open_input_stream_count() == 1

    # Et le PCM du hub arrive bien dans la file d'envoi du chemin interactif.
    device.push(BLOCK)
    await asyncio.sleep(0)
    assert audio.captured_bytes == len(BLOCK)

    await audio.close()
    # Fermer le chemin interactif ne rend pas le micro : le hub le tient encore.
    assert input_ownership.open_input_stream_count() == 1
    assert device.closed == 0
    await hub.close()
    assert input_ownership.open_input_stream_count() == 0


# --------------------------------------------------------------------------
# 2. D14 - SIMPLE est une frontière de régression
# --------------------------------------------------------------------------


async def test_simple_keeps_its_own_input_stream_and_its_two_owners(monkeypatch):
    """SIMPLE n'est pas touché : le chemin interactif ouvre son flux, Porcupine
    le sien, et le compte le dit — deux, comme avant cette Slice."""

    from jarvis.adapters.wakeword_porcupine import PorcupineWakeWordBackend

    class FakeStream:
        def __init__(self) -> None:
            self.started = False
        def start(self) -> None:
            self.started = True
        def stop(self, *, ignore_errors=True) -> None: ...
        def abort(self, *, ignore_errors=True) -> None: ...
        def close(self, *, ignore_errors=True) -> None: ...
        def write(self, pcm) -> None: ...  # noqa: ANN001

    inputs: list[FakeStream] = []

    class FakeSoundDevice:
        @staticmethod
        def RawInputStream(**kwargs):  # noqa: ANN003
            stream = FakeStream()
            inputs.append(stream)
            return stream

        @staticmethod
        def RawOutputStream(**kwargs):  # noqa: ANN003
            return FakeStream()

    class FakePorcupine:
        @staticmethod
        def create(**kwargs):  # noqa: ANN003
            return FakeWakeEngine()

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)
    monkeypatch.setitem(sys.modules, "pvporcupine", FakePorcupine)

    audio = SoundDeviceRealtimeAudio()  # aucun `input_source` : le chemin SIMPLE
    await audio.start()
    assert len(inputs) == 1, "SIMPLE doit toujours ouvrir son propre flux d'entrée"
    assert input_ownership.open_input_stream_count(input_ownership.OWNER_REALTIME_AUDIO) == 1

    wake = PorcupineWakeWordBackend(access_key="k", keyword="jarvis")
    await wake.start()
    assert input_ownership.open_input_stream_count() == 2, (
        "le chemin SIMPLE possède délibérément deux flux ; la Slice 05 ne le change pas"
    )

    # Et il se rend exactement comme avant : `suspend()` libère le sien.
    await wake.suspend()
    assert input_ownership.open_input_stream_count() == 1
    await wake.close()
    await audio.close()
    assert input_ownership.open_input_stream_count() == 0


async def test_a_failed_porcupine_teardown_still_releases_its_place_in_the_count(monkeypatch):
    """« Un propriétaire fantôme ne peut jamais rester dans le compte » : même
    quand `stop()` lève, le registre doit lâcher le flux."""

    from jarvis.adapters.wakeword_porcupine import PorcupineWakeWordBackend

    class ExplodingStream:
        def start(self) -> None: ...
        def stop(self) -> None:
            raise OSError("device vanished")
        def close(self) -> None: ...

    class FakeSoundDevice:
        @staticmethod
        def RawInputStream(**kwargs):  # noqa: ANN003
            return ExplodingStream()

    class FakePorcupine:
        @staticmethod
        def create(**kwargs):  # noqa: ANN003
            return FakeWakeEngine()

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)
    monkeypatch.setitem(sys.modules, "pvporcupine", FakePorcupine)

    wake = PorcupineWakeWordBackend(access_key="k")
    await wake.start()
    assert input_ownership.open_input_stream_count() == 1
    await wake.suspend()
    assert input_ownership.open_input_stream_count() == 0


def test_releasing_a_stream_the_registry_never_saw_is_a_silent_no_op():
    """La libération est totale par contrat : un flux de sortie, ou un flux
    déjà retiré, ne doit jamais faire lever un chemin de fermeture."""

    stranger = object()
    input_ownership.release_input_stream(stranger)
    input_ownership.register_input_stream("x", stranger)
    input_ownership.release_input_stream(stranger)
    input_ownership.release_input_stream(stranger)
    assert input_ownership.open_input_stream_count() == 0


# --------------------------------------------------------------------------
# 3. Activation qui échoue fort : périphérique pris, perdu, ou ambigu
# --------------------------------------------------------------------------


async def test_a_busy_microphone_refuses_presentation_loudly_and_leaves_nothing_open():
    journal = RecordingJournal()
    device = FakeCaptureDevice(
        fail_with=PortAudioError("Error opening RawInputStream: Device unavailable", -9985)
    )
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory, journal=journal,
    )

    with pytest.raises(PresentationAudioError) as raised:
        await session.start()

    assert raised.value.code == "capture_device_busy"
    # Le message cite la panne réelle plutôt qu'une formule générique.
    assert "Device unavailable" in str(raised.value)
    assert "capture_device_busy" in journal.codes(level="error")
    assert session.physical_input_owners() == 0
    assert session.started is False
    assert session.hub.state is CaptureHubState.IDLE


async def test_an_unknown_open_failure_is_named_as_unavailable_not_as_busy():
    journal = RecordingJournal()
    device = FakeCaptureDevice(fail_with=OSError("no such device"))
    hub = make_hub(device, journal=journal)

    with pytest.raises(AudioCaptureHubError) as raised:
        await hub.open()

    assert raised.value.code == "capture_device_unavailable"
    assert "no such device" in str(raised.value)
    assert hub.open_input_streams == 0


async def test_presentation_refuses_to_start_when_another_owner_already_holds_the_microphone():
    """« Jamais deux flux concurrents » : le refus arrive **avant** l'ouverture,
    puisque après il serait trop tard."""

    journal = RecordingJournal()
    squatter = object()
    input_ownership.register_input_stream(input_ownership.OWNER_REALTIME_AUDIO, squatter)
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory, journal=journal,
    )

    with pytest.raises(PresentationAudioError) as raised:
        await session.start()

    assert raised.value.code == "presentation_second_microphone_owner"
    assert device.opens == 0, "aucun second flux ne doit avoir été ouvert"
    assert "presentation_second_microphone_owner" in journal.codes(level="error")


async def test_a_second_owner_appearing_during_the_open_cancels_the_activation():
    """L'invariante est vérifiée après coup, pas seulement avant : si le compte
    n'est pas 1 une fois le flux ouvert, on rend le micro au lieu de rester à deux."""

    journal = RecordingJournal()
    intruder = object()
    device = FakeCaptureDevice()

    def factory(**kwargs):  # noqa: ANN003
        # Un autre propriétaire s'inscrit pendant l'ouverture.
        input_ownership.register_input_stream(input_ownership.OWNER_WAKEWORD_PORCUPINE, intruder)
        return device.factory(**kwargs)

    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=factory, journal=journal,
    )

    with pytest.raises(PresentationAudioError) as raised:
        await session.start()

    assert raised.value.code == "presentation_input_owner_ambiguous"
    assert device.stopped == 1 and device.closed == 1, "le micro du hub doit avoir été rendu"
    assert input_ownership.open_input_stream_count(input_ownership.OWNER_CAPTURE_HUB) == 0
    assert "presentation_input_owner_ambiguous" in journal.codes(level="error")


async def test_a_microphone_that_stops_delivering_is_declared_lost_once_and_loudly():
    journal = RecordingJournal()
    now = [1000.0]
    lost: list[str] = []
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal, clock=lambda: now[0],
                   silence_timeout_s=2.5, on_device_lost=lost.append)
    await hub.open()
    device.push()
    assert hub.check_liveness() is True

    now[0] += 2.4
    assert hub.check_liveness() is True, "sous le seuil, rien n'est perdu"
    now[0] += 0.2
    assert hub.check_liveness() is False
    assert hub.state is CaptureHubState.LOST
    assert lost == ["capture_device_lost"]
    assert "capture_device_lost" in journal.codes(level="error")

    # Dit **une fois** : un poste muet ne doit pas écrire une ligne par tick.
    now[0] += 10.0
    hub.check_liveness()
    hub.check_liveness()
    assert journal.codes(level="error").count("capture_device_lost") == 1
    assert lost == ["capture_device_lost"]

    # Et la perte n'est pas un cul-de-sac : le périphérique mort est rendu,
    # sinon le compte de propriétaires resterait à 1 pour toujours et toute
    # activation ultérieure serait refusée à cause de son propre cadavre.
    assert await hub.reap_lost_device() is True
    assert hub.open_input_streams == 0
    assert input_ownership.open_input_stream_count() == 0
    assert device.stopped == 1 and device.closed == 1
    assert "capture_device_released" in journal.codes(level="warning")
    await hub.close()


async def test_a_listener_that_explodes_on_device_loss_does_not_hide_the_loss():
    journal = RecordingJournal()
    now = [0.0]
    device = FakeCaptureDevice()

    def explode(code: str) -> None:
        raise RuntimeError("listener down")

    hub = make_hub(device, journal=journal, clock=lambda: now[0], on_device_lost=explode)
    await hub.open()
    now[0] += 99.0
    assert hub.check_liveness() is False
    assert "capture_device_lost" in journal.codes(level="error")
    assert "capture_device_lost_listener_failed" in journal.codes(level="error")
    await hub.close()


async def test_the_presentation_session_records_a_lost_device_without_being_asked_twice():
    journal = RecordingJournal()
    now = [0.0]
    seen: list[str] = []
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory,
        journal=journal, on_device_lost=seen.append,
    )
    session.hub.clock = lambda: now[0]
    await session.start()
    assert session.device_lost is False
    now[0] += 99.0
    session.hub.check_liveness()
    assert session.device_lost is True and seen == ["capture_device_lost"]
    await session.stop()


# --------------------------------------------------------------------------
# 4. Arrêt sûr, redémarrage, idempotence
# --------------------------------------------------------------------------


async def test_a_stopped_session_refuses_to_restart_instead_of_capturing_while_deaf():
    """Le défaut que ce refus remplace : `stop()` puis `start()` rouvrait le
    micro, réinscrivait le propriétaire, et rendait `started=True` avec une lane
    fermée et zéro abonné — PRESENTATION captait la salle, ne pouvait plus
    jamais être adressée, et sa trace annonçait les deux sources vivantes."""

    journal = RecordingJournal()
    device = FakeCaptureDevice()
    manual = FakeTriggerBackend()
    session = PresentationAudioSession.build(
        manual_backend=manual, wake_engine_factory=lambda: FakeWakeEngine(),
        stream_factory=device.factory, journal=journal,
    )
    await session.start()
    await session.stop()
    assert session.physical_input_owners() == 0

    with pytest.raises(PresentationAudioError) as raised:
        await session.start()

    assert raised.value.code == "presentation_session_stopped"
    assert device.opens == 1, "le micro ne doit pas avoir été rouvert"
    assert session.physical_input_owners() == 0
    assert session.started is False
    assert "presentation_session_stopped" in journal.codes(level="error")
    # Et aucune ligne ne peut prétendre que la capture a redémarré.
    assert len(journal.of_kind("presentation.audio.started")) == 1


async def test_a_fresh_session_takes_over_after_a_stop_which_is_the_supported_path():
    device = FakeCaptureDevice()
    first = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory,
    )
    await first.start()
    assert first.physical_input_owners() == 1
    await first.stop()
    assert first.physical_input_owners() == 0

    second = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory,
    )
    await second.start()
    assert second.physical_input_owners() == 1
    assert device.opens == 2
    # La seconde séance est réellement adressable, ce que la première version
    # de ce test ne vérifiait pas.
    assert second.lane.live_sources == (ExplicitAddressSource.MANUAL_KEY,)
    assert second.lane.closed is False
    await second.stop()
    assert second.physical_input_owners() == 0
    assert device.closed == 2


async def test_starting_twice_is_a_no_op_and_stopping_twice_stays_idempotent():
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory,
    )
    await session.start()
    await session.start()
    assert device.opens == 1
    await session.stop()
    await session.stop()
    assert device.closed == 1
    assert session.physical_input_owners() == 0


async def test_closing_a_subscription_never_closes_the_physical_stream():
    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    first = hub.subscribe("ambient")
    second = hub.subscribe("other")

    first.close()
    first.close()  # idempotent
    assert device.closed == 0
    assert hub.open_input_streams == 1
    assert [entry.name for entry in hub.subscriptions] == ["other"]

    device.push()
    await asyncio.sleep(0)
    assert second.pending == 1, "l'abonné restant continue d'être servi"
    await hub.close()
    assert device.closed == 1


async def test_a_hub_closed_then_reopened_serves_again_and_refuses_subscriptions_in_between():
    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    await hub.close()

    with pytest.raises(AudioCaptureHubError) as raised:
        hub.subscribe("too-late")
    assert raised.value.code == "capture_hub_closed"

    await hub.open()
    assert hub.open_input_streams == 1
    subscription = hub.subscribe("again")
    device.push()
    await asyncio.sleep(0)
    assert subscription.pending == 1
    await hub.close()


async def test_a_block_arriving_after_close_reaches_nobody_and_raises_nothing():
    """« Aucune exception ne remonte dans le thread PortAudio » : un dernier
    callback après la fermeture est un cas réel, pas une hypothèse."""

    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    subscription = hub.subscribe("ambient")
    await hub.close()

    device.push()  # ne doit rien lever
    assert subscription.pending == 0
    assert hub.blocks_captured == 0


# --------------------------------------------------------------------------
# 5. Contre-pression : un abonné lent n'arrête personne
# --------------------------------------------------------------------------


async def test_a_slow_subscriber_drops_its_own_blocks_and_stalls_nobody_else():
    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    slow = hub.subscribe("slow", max_blocks=4)
    fast = hub.subscribe("fast", max_blocks=64)
    received: list[bytes] = []

    async def drain() -> None:
        async for block in fast.blocks():
            received.append(block)

    task = asyncio.create_task(drain())
    for _ in range(40):
        device.push()
        await asyncio.sleep(0)

    await until(lambda: len(received) == 40)
    assert len(received) == 40, "l'abonné rapide a tout reçu malgré le lent"
    assert slow.pending == 4 and slow.pending <= slow.max_blocks
    assert slow.dropped == 36
    assert slow.delivered == 40

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await hub.close()


async def test_a_full_queue_keeps_the_present_and_discards_the_backlog():
    """La politique est unique et fixe : écarter le plus ancien."""

    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    subscription = hub.subscribe("ambient", max_blocks=2)
    for index in range(4):
        device.push(bytes([index, 0]) * 4)

    assert [block[0] for block in list(subscription._blocks)] == [2, 3]
    assert subscription.dropped == 2
    await hub.close()


def test_a_subscriber_queue_can_never_be_asked_for_more_than_the_hard_ceiling():
    device = FakeCaptureDevice()
    hub = make_hub(device)
    assert hub.subscribe("greedy", max_blocks=10_000).max_blocks == MAX_SUBSCRIBER_BLOCKS
    assert hub.subscribe("tiny", max_blocks=0).max_blocks == 1


async def test_an_inline_subscriber_failing_once_neither_detaches_nor_stops_the_others():
    """La différence délibérée avec le verrou permanent de `CaptureProcessor.observer`."""

    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal)
    await hub.open()
    calls = {"n": 0}

    def flaky(block: bytes) -> None:
        calls["n"] += 1
        if calls["n"] in (1, 3):
            raise ValueError("boom")

    inline = hub.subscribe("interactive", sink=flaky)
    queued = hub.subscribe("ambient")

    device.push()
    device.push()
    device.push()
    device.push()
    assert calls["n"] == 4, "l'abonné en ligne est toujours appelé après un échec isolé"
    assert inline.failures == 2 and inline.consecutive_failures == 0
    assert inline.closed is False
    assert queued.delivered == 4, "l'échec d'un abonné n'en prive aucun autre"

    # Et l'échec a été dit — depuis la boucle, jamais depuis le thread audio.
    assert "capture_sink_failed" not in journal.codes()
    hub._drain_notices()
    assert journal.codes(level="error").count("capture_sink_failed") == 2
    await hub.close()


async def test_an_inline_subscriber_failing_three_times_in_a_row_is_detached_saying_why():
    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal)
    await hub.open()

    def always_fails(block: bytes) -> None:
        raise ValueError("boom")

    inline = hub.subscribe("interactive", sink=always_fails)
    survivor = hub.subscribe("ambient")
    for _ in range(MAX_CONSECUTIVE_SINK_FAILURES + 2):
        device.push()

    assert inline.failures == MAX_CONSECUTIVE_SINK_FAILURES
    assert inline.detached_reason == "capture_sink_failed"
    hub._drain_notices()
    assert inline not in hub.subscriptions
    assert survivor in hub.subscriptions and survivor.delivered == MAX_CONSECUTIVE_SINK_FAILURES + 2
    assert hub.open_input_streams == 1, "le micro reste ouvert pour les autres lanes"
    await hub.close()


async def test_an_inline_subscriber_cannot_ask_for_another_sample_rate():
    """Rééchantillonner dans le thread PortAudio est exactement le travail
    lourd qui n'a pas le droit d'y entrer : le refus est explicite."""

    device = FakeCaptureDevice()
    hub = make_hub(device)
    with pytest.raises(AudioCaptureHubError) as raised:
        hub.subscribe("interactive", sample_rate=16000, sink=lambda block: None)
    assert raised.value.code == "capture_subscription_rate_mismatch"
    assert hub.subscriptions == ()


async def test_calling_blocks_on_an_inline_subscription_is_refused_rather_than_silent():
    device = FakeCaptureDevice()
    hub = make_hub(device)
    inline = hub.subscribe("interactive", sink=lambda block: None)
    with pytest.raises(AudioCaptureHubError) as raised:
        await anext(inline.blocks())
    assert raised.value.code == "capture_subscription_inline"


# --------------------------------------------------------------------------
# 6. Pré-roll : borné, en mémoire seulement
# --------------------------------------------------------------------------


def test_the_preroll_ring_never_holds_more_than_its_capacity():
    ring = PreRollRing(sample_rate=HUB_RATE, preroll_ms=200)
    assert ring.capacity_bytes == int(HUB_RATE * 0.2) * 2
    for _ in range(100):  # 5 s de blocs de 50 ms pour 200 ms de capacité
        ring.append(BLOCK)
        assert ring.bytes_held <= ring.capacity_bytes
    assert ring.evicted_bytes > 0
    assert len(ring.snapshot()) <= ring.capacity_bytes


def test_a_preroll_larger_than_the_hard_ceiling_is_clamped_rather_than_granted():
    ring = PreRollRing(sample_rate=HUB_RATE, preroll_ms=60_000)
    assert ring.preroll_ms == MAX_PREROLL_MS
    assert ring.clamped is True
    assert ring.capacity_bytes == int(HUB_RATE * MAX_PREROLL_MS / 1000) * 2


async def test_the_command_preroll_is_bounded_and_says_when_it_was_truncated():
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory, preroll_ms=200,
    )
    await session.start()
    trigger = ExplicitAddressTrigger.admitted(ExplicitAddressSource.MANUAL_KEY, "f9", sequence=0)

    fresh = session.command_preroll(trigger)
    assert fresh.pcm == b"" and fresh.truncated is False and fresh.duration_ms == 0

    for _ in range(100):
        device.push()
    full = session.command_preroll(trigger)
    assert len(full.pcm) <= session.hub.preroll.capacity_bytes
    assert full.duration_ms <= 200
    assert full.truncated is True
    assert full.to_payload()["preroll_ms"] == full.duration_ms
    await session.stop()


def test_a_command_preroll_never_shows_raw_audio_in_its_repr_or_its_payload():
    """Un `repr()` recopié dans un journal suffirait à faire fuir du PCM brut :
    « cela ne peut jamais arriver » est donc un test."""

    trigger = ExplicitAddressTrigger.admitted(ExplicitAddressSource.WAKE_WORD, "jarvis", sequence=3)
    preroll = CommandPreRoll(trigger=trigger, pcm=b"\xde\xad" * 1000, sample_rate=HUB_RATE, truncated=False)
    text = repr(preroll)
    assert "\\xde" not in text and "dead" not in text.lower()
    assert "duration_ms=41" in text  # 1000 echantillons a 24 kHz
    payload = repr(preroll.to_payload())
    assert "\\xde" not in payload
    assert preroll.to_payload()["preroll_bytes"] == 2000


async def test_a_long_presentation_capture_writes_no_file_anywhere(tmp_path, monkeypatch):
    """L'audio brut ne touche jamais le disque. Mesuré, pas affirmé."""

    monkeypatch.chdir(tmp_path)
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(),
        wake_engine_factory=lambda: FakeWakeEngine(),
        stream_factory=device.factory,
    )
    await session.start()
    ambient = session.hub.subscribe("ambient")
    for _ in range(600):  # 30 s de capture
        device.push()
        await asyncio.sleep(0)
    await session.stop()

    assert list(tmp_path.rglob("*")) == []
    assert session.hub.bytes_captured == 600 * len(BLOCK)
    assert ambient.dropped > 0, "la borne a bien mordu au lieu de tout garder"


# --------------------------------------------------------------------------
# 7. Le mot d'éveil, nourri par le PCM partagé
# --------------------------------------------------------------------------


async def test_the_wake_detector_reads_shared_pcm_instead_of_a_second_device():
    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    engine = FakeWakeEngine(sample_rate=16000, frame_length=512, detect_after=3)
    wake = SharedPcmWakeWordBackend(hub=hub, engine_factory=lambda: engine, keyword="jarvis")
    detections = wake.detections()
    pending = asyncio.create_task(anext(detections))
    await until(lambda: any(sub.name == "wake_word" for sub in hub.subscriptions))

    assert device.opens == 1, "le détecteur n'a ouvert aucun périphérique"
    assert input_ownership.open_input_stream_count() == 1
    subscription = next(sub for sub in hub.subscriptions if sub.name == "wake_word")
    assert subscription.sample_rate == 16000 and hub.sample_rate == 24000

    for _ in range(4):
        device.push(sine_block(BLOCK_FRAMES, HUB_RATE))
        await asyncio.sleep(0)

    assert await asyncio.wait_for(pending, timeout=2) == "jarvis"
    # Les trames vues par le moteur sont bien à sa fréquence, pas à celle du hub.
    assert len(engine.frames[0]) == 512
    await wake.close()
    assert input_ownership.open_input_stream_count() == 1
    await hub.close()


async def test_a_wake_engine_that_explodes_says_so_and_leaves_the_manual_key_alive():
    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal)
    await hub.open()
    engine = FakeWakeEngine(raise_after=1)
    wake = SharedPcmWakeWordBackend(hub=hub, engine_factory=lambda: engine, journal=journal)
    manual = FakeTriggerBackend(label="f9")
    lane = ExplicitAddressLane(journal=journal)
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, manual)
    lane.add_source(ExplicitAddressSource.WAKE_WORD, wake)
    triggers = lane.triggers()
    await lane.start()
    await wake.start()

    for _ in range(4):
        device.push()
        await asyncio.sleep(0)
    await until(lambda: wake.engine_failed)

    assert wake.failure_code == "wake_engine_failed"
    assert "wake_engine_failed" in journal.codes(level="error")
    assert hub.open_input_streams == 1, "le micro n'est pas perdu avec le détecteur"

    await manual.queue.put("f9")
    trigger = await asyncio.wait_for(anext(triggers), timeout=2)
    assert trigger.source is ExplicitAddressSource.MANUAL_KEY
    await lane.close()
    await hub.close()


async def test_a_wake_engine_that_cannot_be_built_never_subscribes_and_never_retries_in_a_loop():
    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal)
    await hub.open()
    attempts = {"n": 0}

    def explode():
        attempts["n"] += 1
        raise RuntimeError("no porcupine access key")

    wake = SharedPcmWakeWordBackend(hub=hub, engine_factory=explode, journal=journal)
    await wake.start()
    await wake.start()
    await wake.resume()

    assert attempts["n"] == 1
    assert wake.failure_code == "wake_engine_unavailable"
    assert hub.subscriptions == (), "aucun abonnement laissé derrière un moteur absent"
    assert "wake_engine_unavailable" in journal.codes(level="error")
    await wake.close()
    await hub.close()


async def test_suspending_the_shared_wake_detector_does_not_release_the_microphone():
    """`PorcupineWakeWordBackend.suspend()` ferme son périphérique ; celui-ci ne
    peut pas, et ne doit pas — le micro sert aussi aux autres lanes."""

    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    engine = FakeWakeEngine(detect_after=1)
    wake = SharedPcmWakeWordBackend(hub=hub, engine_factory=lambda: engine)
    await wake.start()

    await wake.suspend_for_active_session()
    for _ in range(4):
        device.push()
        await asyncio.sleep(0)
    await asyncio.sleep(0.02)

    assert device.closed == 0 and hub.open_input_streams == 1
    assert wake.detections_count == 0, "suspendu, il ne détecte plus"

    await wake.resume()
    for _ in range(4):
        device.push()
        await asyncio.sleep(0)
    await until(lambda: wake.detections_count > 0)
    await wake.close()
    await hub.close()


async def test_the_wake_detector_drops_a_detection_rather_than_growing_its_queue():
    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal)
    await hub.open()
    engine = FakeWakeEngine(detect_after=1)
    wake = SharedPcmWakeWordBackend(hub=hub, engine_factory=lambda: engine, journal=journal)
    await wake.start()
    for _ in range(40):
        device.push()
        await asyncio.sleep(0)
    await until(lambda: wake.dropped > 0)

    assert wake._queue.qsize() == 4
    assert "wake_detection_dropped" in journal.codes(level="warning")
    await wake.close()
    await hub.close()


# --------------------------------------------------------------------------
# 8. D05 - un seul type typé, à horloge monotone
# --------------------------------------------------------------------------


def test_both_sources_normalize_to_one_type_carrying_source_and_monotonic_time():
    key = ExplicitAddressTrigger.admitted(ExplicitAddressSource.MANUAL_KEY, "f9", sequence=0)
    word = ExplicitAddressTrigger.admitted(ExplicitAddressSource.WAKE_WORD, "jarvis", sequence=1)
    assert type(key) is type(word)
    assert key.source is not word.source
    assert word.monotonic_s >= key.monotonic_s
    assert key.authorizes_actions is False and word.authorizes_actions is False


def test_a_trigger_refuses_a_wall_clock_or_an_unbounded_label():
    with pytest.raises(ExplicitAddressError) as raised:
        ExplicitAddressTrigger(ExplicitAddressSource.MANUAL_KEY, "f9", float("nan"), 0)
    assert raised.value.code == "explicit_address_time_invalid"

    with pytest.raises(ExplicitAddressError) as raised:
        ExplicitAddressTrigger(ExplicitAddressSource.MANUAL_KEY, "f9", -1.0, 0)
    assert raised.value.code == "explicit_address_time_invalid"

    with pytest.raises(ExplicitAddressError) as raised:
        ExplicitAddressTrigger(ExplicitAddressSource.MANUAL_KEY, "x" * 64, 1.0, 0)
    assert raised.value.code == "explicit_address_label_invalid"

    with pytest.raises(ExplicitAddressError) as raised:
        ExplicitAddressTrigger("manual_key", "f9", 1.0, 0)  # type: ignore[arg-type]
    assert raised.value.code == "explicit_address_source_unknown"

    with pytest.raises(ExplicitAddressError) as raised:
        ExplicitAddressTrigger(ExplicitAddressSource.MANUAL_KEY, "f9", 1.0, True)  # type: ignore[arg-type]
    assert raised.value.code == "explicit_address_sequence_invalid"


def test_a_triggers_age_can_never_be_negative_even_with_a_clock_that_walks_backwards():
    trigger = ExplicitAddressTrigger(ExplicitAddressSource.WAKE_WORD, "jarvis", 100.0, 0)
    assert trigger.age_s(90.0) == 0.0
    assert trigger.is_fresh(90.0) is True
    assert trigger.age_s(100.5) == pytest.approx(0.5)
    assert trigger.is_fresh(100.0 + MAX_TRIGGER_AGE_S + 0.001) is False


def test_a_trigger_is_frozen_so_its_admission_time_cannot_be_rewritten():
    trigger = ExplicitAddressTrigger(ExplicitAddressSource.MANUAL_KEY, "f9", 5.0, 0)
    with pytest.raises((AttributeError, TypeError)):
        trigger.monotonic_s = 99.0  # type: ignore[misc]


async def test_the_lane_stamps_each_trigger_with_a_strictly_increasing_sequence():
    manual = FakeTriggerBackend()
    lane = ExplicitAddressLane()
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, manual)
    triggers = lane.triggers()
    await lane.start()
    seen: list[ExplicitAddressTrigger] = []
    for _ in range(3):
        await manual.queue.put("f9")
        seen.append(await asyncio.wait_for(anext(triggers), timeout=2))

    assert [trigger.sequence for trigger in seen] == [0, 1, 2]
    assert all(b.monotonic_s >= a.monotonic_s for a, b in zip(seen, seen[1:]))
    await lane.close()


# --------------------------------------------------------------------------
# 9. D04 - la lane n'attend aucun travail ambiant
# --------------------------------------------------------------------------


async def test_a_manual_trigger_is_admitted_at_once_while_the_ambient_path_is_saturated():
    """D04, la preuve : ambiant délibérément saturé, latence mesurée.

    L'ambiant est saturé pour de vrai — sa file déborde et son consommateur
    accumule du retard — et le test le vérifie avant de conclure quoi que ce
    soit sur la latence du déclencheur.
    """

    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal)
    await hub.open()
    ambient = hub.subscribe("ambient", max_blocks=4)
    manual = FakeTriggerBackend()
    lane = ExplicitAddressLane(journal=journal)
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, manual)
    triggers = lane.triggers()
    await lane.start()

    ambient_done = {"n": 0}

    async def slow_ambient() -> None:
        async for _ in ambient.blocks():
            await asyncio.sleep(0.02)  # un travail ambiant lent, exprès
            ambient_done["n"] += 1

    async def flood() -> None:
        for _ in range(200):
            device.push()
            await asyncio.sleep(0)

    ambient_task = asyncio.create_task(slow_ambient())
    flood_task = asyncio.create_task(flood())
    await until(lambda: ambient.dropped > 0, timeout=5)

    started = time.monotonic()
    await manual.queue.put("f9")
    trigger = await asyncio.wait_for(anext(triggers), timeout=2)
    latency = time.monotonic() - started

    assert trigger.source is ExplicitAddressSource.MANUAL_KEY
    assert ambient.dropped > 0, "l'ambiant n'était pas réellement saturé"
    assert ambient_done["n"] < 200, "l'ambiant était bien en retard"
    # Budget large exprès : ce qui est prouvé est l'indépendance, pas une
    # performance. Sous une lane dépendante de l'ambiant, la valeur serait de
    # l'ordre de 200 x 20 ms = 4 s.
    assert latency < 0.25, f"déclencheur retardé par l'ambiant: {latency:.3f}s"
    assert lane.last_delivery_latency_s is not None and lane.last_delivery_latency_s < 0.25
    # La latence est consignée, pas seulement asservie.
    assert lane.stats()["last_delivery_latency_s"] is not None

    flood_task.cancel()
    ambient_task.cancel()
    await asyncio.gather(flood_task, ambient_task, return_exceptions=True)
    await lane.close()
    await hub.close()


async def test_the_wake_word_still_reaches_the_lane_while_the_ambient_path_is_saturated():
    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    ambient = hub.subscribe("ambient", max_blocks=2)
    engine = FakeWakeEngine(detect_after=1)
    wake = SharedPcmWakeWordBackend(hub=hub, engine_factory=lambda: engine)
    lane = ExplicitAddressLane()
    lane.add_source(ExplicitAddressSource.WAKE_WORD, wake)
    triggers = lane.triggers()
    await lane.start()
    await wake.start()

    async def slow_ambient() -> None:
        async for _ in ambient.blocks():
            await asyncio.sleep(0.05)

    ambient_task = asyncio.create_task(slow_ambient())

    async def flood() -> None:
        for _ in range(60):
            device.push()
            await asyncio.sleep(0)

    flood_task = asyncio.create_task(flood())
    trigger = await asyncio.wait_for(anext(triggers), timeout=3)

    assert trigger.source is ExplicitAddressSource.WAKE_WORD and trigger.label == "jarvis"
    assert ambient.dropped > 0

    flood_task.cancel()
    ambient_task.cancel()
    await asyncio.gather(flood_task, ambient_task, return_exceptions=True)
    await lane.close()
    await hub.close()


async def test_a_source_that_explodes_does_not_take_the_other_source_with_it():
    journal = RecordingJournal()
    broken = FakeTriggerBackend(raise_with=RuntimeError("pynput missing"))
    manual = FakeTriggerBackend()
    lane = ExplicitAddressLane(journal=journal)
    lane.add_source(ExplicitAddressSource.WAKE_WORD, broken)
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, manual)
    triggers = lane.triggers()
    await lane.start()
    await until(lambda: "wake_word" in lane.source_failures)

    assert lane.live_sources == (ExplicitAddressSource.MANUAL_KEY,)
    assert "explicit_address_source_failed" in journal.codes(level="error")

    await manual.queue.put("f9")
    trigger = await asyncio.wait_for(anext(triggers), timeout=2)
    assert trigger.source is ExplicitAddressSource.MANUAL_KEY
    await lane.close()


async def test_a_full_lane_drops_the_oldest_press_and_says_which_one():
    journal = RecordingJournal()
    manual = FakeTriggerBackend()
    lane = ExplicitAddressLane(journal=journal)
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, manual)
    await lane.start()
    for _ in range(DEFAULT_LANE_QUEUE_SIZE + 2):
        lane._admit(ExplicitAddressSource.MANUAL_KEY, "f9")

    assert lane._queue.qsize() == DEFAULT_LANE_QUEUE_SIZE
    assert lane.dropped == 2
    assert lane.admitted == DEFAULT_LANE_QUEUE_SIZE + 2
    dropped = journal.of_kind("explicit_address.dropped")
    assert [entry["data"]["discarded"]["sequence"] for entry in dropped] == [0, 1]  # type: ignore[index]
    # Ce qui reste est le **présent** : les quatre appuis les plus récents.
    remaining = [lane._queue.get_nowait().sequence for _ in range(DEFAULT_LANE_QUEUE_SIZE)]
    assert remaining == [2, 3, 4, 5]
    await lane.close()


async def test_a_trigger_served_late_is_delivered_and_named_rather_than_dropped():
    journal = RecordingJournal()
    now = [0.0]
    manual = FakeTriggerBackend()
    lane = ExplicitAddressLane(journal=journal, clock=lambda: now[0])
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, manual)
    triggers = lane.triggers()
    await lane.start()
    lane._admit(ExplicitAddressSource.MANUAL_KEY, "f9")
    now[0] += MAX_TRIGGER_AGE_S + 2.0

    trigger = await asyncio.wait_for(anext(triggers), timeout=2)
    assert trigger.sequence == 0, "l'appui n'est jamais perdu"
    assert lane.stale_deliveries == 1
    assert "explicit_address_stale" in journal.codes(level="warning")
    assert lane.last_delivery_latency_s == pytest.approx(MAX_TRIGGER_AGE_S + 2.0)
    await lane.close()


async def test_a_backend_label_out_of_contract_is_refused_without_inventing_a_trigger():
    journal = RecordingJournal()
    lane = ExplicitAddressLane(journal=journal, clock=lambda: float("inf"))
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, FakeTriggerBackend())
    assert lane._admit(ExplicitAddressSource.MANUAL_KEY, "f9") is None
    assert lane.admitted == 0 and lane._queue.qsize() == 0
    assert "explicit_address_label_refused" in journal.codes(level="error")


async def test_an_empty_label_falls_back_to_the_source_rather_than_being_refused():
    lane = ExplicitAddressLane()
    lane.add_source(ExplicitAddressSource.WAKE_WORD, FakeTriggerBackend())
    trigger = lane._admit(ExplicitAddressSource.WAKE_WORD, "")
    assert trigger is not None and trigger.label == "wake_word"


# --------------------------------------------------------------------------
# 10. La lane remplace le backend composite sans changer ses semantiques
# --------------------------------------------------------------------------


async def test_the_lane_is_a_drop_in_wake_backend_whose_two_views_share_one_queue():
    manual = FakeTriggerBackend()
    lane = ExplicitAddressLane()
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, manual)
    detections = lane.detections()
    await lane.start()
    await manual.queue.put("f9")
    assert await asyncio.wait_for(anext(detections), timeout=2) == "f9"
    assert lane.delivered == 1
    assert lane._queue.qsize() == 0, "les deux vues partagent une file, pas deux"
    await lane.close()


async def test_the_lane_forwards_suspend_for_active_session_without_reinterpreting_it():
    """`KeyboardWakeWordBackend.suspend_for_active_session()` garde la touche
    armée pour qu'un second appui soumette le tour. La lane ne doit surtout pas
    l'écraser — c'est la régression que D14 interdit le plus explicitement."""

    keyboard = KeyboardWakeWordBackend(key_name="f9")
    keyboard._enabled = False  # comme après un `suspend()`
    lane = ExplicitAddressLane()
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, keyboard)

    # `start()` du clavier a besoin de pynput ; on ne teste que la sémantique
    # de réarmement, pas l'écoute globale du clavier.
    keyboard.start = _noop_start(keyboard)  # type: ignore[method-assign]
    await lane.suspend_for_active_session()
    assert keyboard._enabled is True, "la touche manuelle doit rester armée"

    await lane.suspend()
    assert keyboard._enabled is False
    await lane.resume()
    assert keyboard._enabled is True
    await lane.close()


class _FakeListener:
    def stop(self) -> None: ...


def _noop_start(backend):
    async def start() -> None:
        backend._listener = _FakeListener()
    return start


async def test_closing_the_lane_closes_its_sources_exactly_like_the_composite_backend_did():
    first = FakeTriggerBackend()
    second = FakeTriggerBackend()
    lane = ExplicitAddressLane()
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, first)
    lane.add_source(ExplicitAddressSource.WAKE_WORD, second)
    await lane.start()
    await lane.close()
    await lane.close()  # idempotent
    assert first.closed and second.closed


async def test_a_lane_without_a_single_source_refuses_to_start_instead_of_listening_to_nothing():
    lane = ExplicitAddressLane()
    with pytest.raises(ValueError):
        await lane.start()


# --------------------------------------------------------------------------
# 11. Rééchantillonnage continu
# --------------------------------------------------------------------------


def test_resampling_block_by_block_gives_exactly_the_one_shot_result():
    """L'invariante qui justifie ce module : pas de raccord entre deux blocs."""

    raw = sine_block(2400, 24000)
    whole = StreamingPcm16Resampler(source_rate=24000, target_rate=16000).process(raw)
    blocked = StreamingPcm16Resampler(source_rate=24000, target_rate=16000)
    pieces = b"".join(blocked.process(raw[index:index + 480]) for index in range(0, len(raw), 480))
    assert pieces == whole
    assert len(whole) // 2 == 1600
    assert blocked.frames_in == 2400 and blocked.frames_out == 1600


@pytest.mark.parametrize("chunk_samples", [101, 137, 7, 480])
def test_resampling_stays_continuous_even_when_blocks_do_not_divide_the_ratio(chunk_samples):
    """La coupure qui compte vraiment : un bloc dont la taille ne tombe pas
    juste sur le pas de rééchantillonnage laisse une position **fractionnaire**
    à reporter. Un bloc de 240 échantillons à 24 -> 16 kHz n'en laisse aucune
    (240 est multiple de 1,5) et ne teste donc pas le report ; c'est ce trou
    qui avait laissé survivre la mutation « oublier l'échantillon précédent »."""

    raw = sine_block(2400, 24000)
    whole = StreamingPcm16Resampler(source_rate=24000, target_rate=16000).process(raw)
    streamed = StreamingPcm16Resampler(source_rate=24000, target_rate=16000)
    step = chunk_samples * 2
    pieces = b"".join(streamed.process(raw[index:index + step]) for index in range(0, len(raw), step))
    assert pieces == whole, f"raccord perdu avec des blocs de {chunk_samples} échantillons"


def test_the_resampler_actually_carries_the_previous_block_across_the_seam():
    """Contrôle direct de l'état reporté : sans lui, la première valeur du
    second bloc serait recalculée depuis lui-même au lieu d'être interpolée
    avec la fin du précédent."""

    rising = array.array("h", [1000 * index for index in range(11)]).tobytes()
    resampler = StreamingPcm16Resampler(source_rate=24000, target_rate=16000)
    resampler.process(rising)
    # 11 échantillons, pas 1,5 : positions 0..9, la suivante tombe à 10.5 -> report -0.5.
    assert resampler._previous == 10000
    assert resampler._position == pytest.approx(-0.5)

    falling = array.array("h", [0] * 11).tobytes()
    out = array.array("h")
    out.frombytes(resampler.process(falling))
    # À -0.5, on interpole entre 10000 (bloc précédent) et 0 (bloc courant).
    assert out[0] == 5000


def test_resampling_preserves_the_signal_rather_than_returning_silence_or_noise():
    raw = sine_block(2400, 24000, hz=440.0)
    out = StreamingPcm16Resampler(source_rate=24000, target_rate=16000).process(raw)
    samples = array.array("h")
    samples.frombytes(out)
    peak = max(abs(value) for value in samples)
    assert 7000 <= peak <= 8200, f"amplitude perdue ou saturée: {peak}"


def test_matching_rates_pass_through_untouched():
    resampler = StreamingPcm16Resampler(source_rate=24000, target_rate=24000)
    assert resampler.passthrough is True
    assert resampler.process(BLOCK) is BLOCK


def test_a_block_cut_in_the_middle_of_a_sample_is_refused_rather_than_turned_into_noise():
    resampler = StreamingPcm16Resampler(source_rate=24000, target_rate=16000)
    with pytest.raises(ValueError):
        resampler.process(b"\x01\x02\x03")


def test_upsampling_and_clipping_stay_inside_int16():
    loud = array.array("h", [32767, -32768] * 100).tobytes()
    out = StreamingPcm16Resampler(source_rate=16000, target_rate=24000).process(loud)
    samples = array.array("h")
    samples.frombytes(out)
    assert all(-32768 <= value <= 32767 for value in samples)
    assert len(samples) > 200


# --------------------------------------------------------------------------
# 12. L'etat lisible, pour que chaque garantie soit constatable
# --------------------------------------------------------------------------


async def test_the_session_reports_who_owns_the_microphone_and_what_each_lane_did():
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(),
        wake_engine_factory=lambda: FakeWakeEngine(),
        stream_factory=device.factory,
    )
    await session.start()
    device.push()
    stats = session.stats()

    assert stats["started"] is True
    assert stats["physical_input_owners"] == 1
    assert stats["input_owners"] == [
        {"owner": input_ownership.OWNER_CAPTURE_HUB, "label": "None"}
    ]
    assert stats["hub"]["open_input_streams"] == 1  # type: ignore[index]
    assert stats["hub"]["blocks_captured"] == 1  # type: ignore[index]
    assert stats["wake"]["opens_input_stream"] is False  # type: ignore[index]
    assert stats["lane"]["live_sources"] == ["manual_key", "wake_word"]  # type: ignore[index]
    await session.stop()


async def test_the_shared_input_source_is_refused_before_the_capture_is_started():
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory,
    )
    with pytest.raises(PresentationAudioError) as raised:
        session.realtime_input_source()
    assert raised.value.code == "presentation_capture_not_started"


async def test_the_hub_logs_the_expected_path_so_silence_never_means_both_fine_and_dead():
    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal)
    await hub.open()
    hub.subscribe("ambient")
    await hub.close()
    assert "audio.capture_hub.opened" in journal.kinds()
    assert "audio.capture_hub.subscribed" in journal.kinds()
    assert "audio.capture_hub.closed" in journal.kinds()


# --------------------------------------------------------------------------
# 13. Le raccord dans PersistentVoiceRuntime : PRESENTATION seulement
# --------------------------------------------------------------------------


class _FakeCore:
    """Core minimal : le raccord testé ici ne lui parle pas."""


def _voice_runtime(**kwargs):
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime

    async def factory(context):  # noqa: ANN001
        raise AssertionError("aucune session ne doit etre ouverte ici")

    return PersistentVoiceRuntime(
        wakeword=FakeTriggerBackend(), core=_FakeCore(), realtime_factory=factory, **kwargs
    )


def _set_mode(runtime, mode: str) -> None:
    assert runtime.interaction_mode.adopt({"mode": mode, "revision": 1, "epoch": "e1"})


async def test_simple_never_receives_a_shared_input_source_even_when_one_exists():
    """D14 : en SIMPLE le chemin existant n'est pas seulement inchange, il n'est
    pas atteint."""

    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory,
    )
    await session.start()
    runtime = _voice_runtime(presentation_audio=session)

    assert runtime.interaction_mode.mode.value == "assistant"
    assert runtime._shared_input_source() is None
    await session.stop()


async def test_a_voice_runtime_without_presentation_capture_behaves_exactly_as_before():
    runtime = _voice_runtime()
    _set_mode(runtime, "presentation")
    assert runtime.presentation_audio is None
    assert runtime._shared_input_source() is None


async def test_presentation_hands_the_bridge_the_shared_capture_instead_of_a_second_microphone(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", OutputOnlySoundDevice)
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory,
    )
    await session.start()
    runtime = _voice_runtime(presentation_audio=session)
    _set_mode(runtime, "presentation")

    source = runtime._shared_input_source()
    assert source is not None
    audio = SoundDeviceRealtimeAudio(input_source=source)
    await audio.start()
    assert device.opens == 1
    assert input_ownership.open_input_stream_count() == 1

    device.push()
    await asyncio.sleep(0)
    assert audio.captured_bytes == len(BLOCK)

    await audio.close()
    await session.stop()


async def test_a_presentation_capture_that_never_started_degrades_loudly_rather_than_silently():
    journal = RecordingJournal()
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory,
    )
    runtime = _voice_runtime(presentation_audio=session, journal=journal)
    _set_mode(runtime, "presentation")

    assert runtime._shared_input_source() is None, "le tour s'ouvre sur un flux, pas zero"
    assert "presentation_capture_not_started" in journal.codes(level="error")


async def test_a_failed_output_open_leaves_no_phantom_input_owner_behind(monkeypatch):
    """Un proprietaire fantome bloquerait PRESENTATION pour toujours : le
    registre doit suivre la fermeture reelle, y compris sur un chemin d'echec."""

    class FakeInput:
        def start(self) -> None: ...
        def stop(self, *, ignore_errors=True) -> None: ...
        def close(self, *, ignore_errors=True) -> None: ...

    class FailingSoundDevice:
        @staticmethod
        def RawInputStream(**kwargs):  # noqa: ANN003
            return FakeInput()

        @staticmethod
        def RawOutputStream(**kwargs):  # noqa: ANN003
            raise OSError("device unavailable")

    monkeypatch.setitem(sys.modules, "sounddevice", FailingSoundDevice)
    audio = SoundDeviceRealtimeAudio()
    with pytest.raises(RuntimeError):
        await audio.start()
    assert input_ownership.open_input_stream_count() == 0
    await audio.close()
    assert input_ownership.open_input_stream_count() == 0


async def test_an_input_stream_whose_close_fails_still_frees_its_place_in_the_count(monkeypatch):
    class StubbornInput:
        def start(self) -> None: ...
        def stop(self, *, ignore_errors=True) -> None: ...
        def close(self, *, ignore_errors=True) -> None:
            raise OSError("close refused")

    class FakeOutput:
        def start(self) -> None: ...
        def stop(self, *, ignore_errors=True) -> None: ...
        def abort(self, *, ignore_errors=True) -> None: ...
        def close(self, *, ignore_errors=True) -> None: ...
        def write(self, pcm) -> None: ...  # noqa: ANN001

    class FakeSoundDevice:
        @staticmethod
        def RawInputStream(**kwargs):  # noqa: ANN003
            return StubbornInput()

        @staticmethod
        def RawOutputStream(**kwargs):  # noqa: ANN003
            return FakeOutput()

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)
    audio = SoundDeviceRealtimeAudio()
    await audio.start()
    assert input_ownership.open_input_stream_count() == 1
    with pytest.raises(RuntimeError):
        await audio.close()  # l'echec remonte, comme avant cette Slice
    assert input_ownership.open_input_stream_count() == 0


# --------------------------------------------------------------------------
# 14. Le compte est exhaustif, et il se prouve en enumerant les ouvreurs
# --------------------------------------------------------------------------


#: Tous les sites du depot qui ouvrent une entree physique, et le proprietaire
#: sous lequel chacun doit s'inscrire. Mettre a jour cette table fait partie de
#: l'ajout d'un ouvreur : c'est exactement ce que le test ci-dessous impose.
EXPECTED_INPUT_OPENERS = {
    "jarvis/adapters/wakeword_porcupine.py": "OWNER_WAKEWORD_PORCUPINE",
    "jarvis/audio/capture.py": "OWNER_AUDIO_RECORDER",
    "jarvis/audio/capture_hub.py": "OWNER_CAPTURE_HUB",
    "jarvis/runtime/audio_devices.py": "OWNER_DEVICE_PROBE",
    "jarvis/runtime/owner_voice.py": "OWNER_OWNER_VOICE_ENROLLMENT",
    "jarvis/runtime/realtime_audio.py": "OWNER_REALTIME_AUDIO",
}


def test_every_site_that_opens_a_physical_input_registers_its_owner():
    """Le seul test de cette suite qui regarde du texte source, et c'est voulu.

    La regle de cette tache est d'assurer sur des comportements et des valeurs,
    jamais sur du texte source, parce que trois tests de la Slice 03 ont rate
    le bug qu'ils existaient pour attraper. **Elle ne s'applique pas ici**, et
    il ne faut pas supprimer ce test au nom de cette regle : ce qu'il verifie
    est l'*absence* d'un appel non inscrit, dans des fichiers que ce test
    n'importe pas et dont la plupart des chemins n'ouvriraient un vrai micro
    qu'au prix d'un peripherique reel. Aucun test comportemental ne peut
    prouver qu'un septieme ouvreur n'existe pas.

    Ce qu'il empeche est concret : avec un `SoundDeviceRecorder` vivant et non
    inscrit, `PresentationAudioSession.start()` lisait un registre vide,
    passait son refus d'avant-ouverture, ouvrait le hub, relisait 1, et
    demarrait a deux flux concurrents en journalisant une activation reussie.
    """

    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "jarvis"
    opener = re.compile(r"(?:sd|sounddevice)\.(RawInputStream|rec)\(")
    #: Le registre lui-meme cite `sd.rec(` dans sa prose pour decrire ce test.
    #: Il n'ouvre rien ; l'exclure est plus honnete que de rendre la regex
    #: assez subtile pour distinguer un appel d'une citation.
    registry = "jarvis/audio/input_ownership.py"
    found: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root.parent).as_posix()
        if relative == registry:
            continue
        hits = len(opener.findall(path.read_text(encoding="utf-8-sig")))
        if hits:
            found[relative] = hits

    assert set(found) == set(EXPECTED_INPUT_OPENERS), (
        "un site ouvre une entree physique sans etre declare ici ; inscrivez-le "
        "dans jarvis/audio/input_ownership.py puis ajoutez-le a EXPECTED_INPUT_OPENERS"
    )
    for relative, owner_constant in EXPECTED_INPUT_OPENERS.items():
        text = (root.parent / relative).read_text(encoding="utf-8-sig")
        assert "register_input_stream(" in text, f"{relative} n'inscrit aucun proprietaire"
        assert "release_input_stream(" in text, f"{relative} ne libere aucun proprietaire"
        assert owner_constant in text, f"{relative} n'utilise pas {owner_constant}"


async def test_a_live_recorder_blocks_presentation_instead_of_being_invisible():
    """Le defaut que l'exhaustivite du registre corrige, joue de bout en bout."""

    journal = RecordingJournal()
    recorder_stream = object()
    input_ownership.register_input_stream(
        input_ownership.OWNER_AUDIO_RECORDER, recorder_stream, label="micro"
    )
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory, journal=journal,
    )

    with pytest.raises(PresentationAudioError) as raised:
        await session.start()

    assert raised.value.code == "presentation_second_microphone_owner"
    assert "audio_recorder" in str(raised.value)
    assert device.opens == 0
    input_ownership.release_input_stream(recorder_stream)


def test_a_stream_collected_without_a_close_does_not_leave_a_phantom_owner():
    """Sans ce filet, une seule fuite bloquerait PRESENTATION pour toujours et
    aucun chemin ne pourrait la purger."""

    import gc

    class Stream:
        pass

    stream = Stream()
    input_ownership.register_input_stream(input_ownership.OWNER_AUDIO_RECORDER, stream)
    assert input_ownership.open_input_stream_count() == 1
    del stream
    gc.collect()
    assert input_ownership.open_input_stream_count() == 0


# --------------------------------------------------------------------------
# 15. Aucune activation ne garde le micro pour personne
# --------------------------------------------------------------------------


async def test_a_failed_lane_start_gives_the_microphone_back_instead_of_holding_it():
    """Le seul chemin d'activation qui laissait le micro pris : hub ouvert,
    `started` faux, et le `start()` suivant refusant en designant son propre
    hub comme l'intrus."""

    journal = RecordingJournal()
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory, journal=journal,
    )

    async def explode() -> None:
        raise RuntimeError("pynput missing")

    session.lane.start = explode  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="pynput missing"):
        await session.start()

    assert session.physical_input_owners() == 0, "le micro doit avoir ete rendu"
    assert device.stopped == 1 and device.closed == 1
    assert session.started is False
    assert "presentation_sources_failed" in journal.codes(level="error")


async def test_a_source_that_raises_while_closing_does_not_keep_the_microphone():
    """`KeyboardWakeWordBackend.close()` appelle `listener.stop()` de pynput,
    qui peut lever a la demolition. Sans `finally`, `hub.close()` ne tournait
    jamais et le micro restait tenu jusqu'a la fin du processus."""

    journal = RecordingJournal()
    device = FakeCaptureDevice()
    manual = FakeTriggerBackend()

    async def explode() -> None:
        raise OSError("listener teardown failed")

    manual.close = explode  # type: ignore[method-assign]
    session = PresentationAudioSession.build(
        manual_backend=manual, stream_factory=device.factory, journal=journal,
    )
    await session.start()
    await session.stop()

    assert session.physical_input_owners() == 0
    assert device.closed == 1
    assert "explicit_address_source_close_failed" in journal.codes(level="error")


async def test_a_wake_backend_that_raises_while_closing_does_not_keep_the_microphone():
    """`stop()` ferme la lane **puis** le detecteur ; c'est le second qui n'a
    aucune isolation interne, donc c'est lui qui prouve le `finally`. Sans ce
    `finally`, `hub.close()` ne tournait jamais et le micro restait tenu
    jusqu'a la fin du processus."""

    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(),
        wake_engine_factory=lambda: FakeWakeEngine(),
        stream_factory=device.factory,
    )
    await session.start()
    assert session.wake is not None

    async def explode() -> None:
        raise OSError("engine teardown failed")

    session.wake.close = explode  # type: ignore[method-assign]

    with pytest.raises(OSError, match="engine teardown failed"):
        await session.stop()

    assert session.physical_input_owners() == 0, "le micro doit avoir ete rendu quand meme"
    assert device.closed == 1


async def test_one_source_failing_to_close_does_not_stop_the_others_from_closing():
    first = FakeTriggerBackend()
    second = FakeTriggerBackend()

    async def explode() -> None:
        raise OSError("boom")

    first.close = explode  # type: ignore[method-assign]
    lane = ExplicitAddressLane(journal=RecordingJournal())
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, first)
    lane.add_source(ExplicitAddressSource.WAKE_WORD, second)
    await lane.start()
    await lane.close()
    assert second.closed is True


# --------------------------------------------------------------------------
# 16. Un detecteur mort se rend, et se dit a la lane
# --------------------------------------------------------------------------


async def test_a_dying_wake_engine_releases_its_subscription_instead_of_being_fed_forever():
    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal)
    await hub.open()
    wake = SharedPcmWakeWordBackend(
        hub=hub, engine_factory=lambda: FakeWakeEngine(raise_after=1), journal=journal,
    )
    await wake.start()
    for _ in range(4):
        device.push()
        await asyncio.sleep(0)
    await until(lambda: wake.engine_failed)
    await until(lambda: hub.subscriptions == ())

    assert wake.stats()["subscribed"] is False
    assert hub.open_input_streams == 1, "le micro reste, seul le detecteur part"
    dropped_before = hub.blocks_captured
    for _ in range(10):
        device.push()
    assert hub.blocks_captured == dropped_before + 10
    await wake.close()
    await hub.close()


async def test_a_wake_engine_dying_mid_session_reaches_the_lane_instead_of_hanging():
    """Sans cela `detections()` restait bloquee sur une file qui ne se
    remplirait plus, `source_failures` restait vide, et `live_sources`
    declarait le mot d'eveil vivant apres sa mort."""

    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal)
    await hub.open()
    wake = SharedPcmWakeWordBackend(
        hub=hub, engine_factory=lambda: FakeWakeEngine(raise_after=2), journal=journal,
    )
    manual = FakeTriggerBackend()
    lane = ExplicitAddressLane(journal=journal)
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, manual)
    lane.add_source(ExplicitAddressSource.WAKE_WORD, wake)
    triggers = lane.triggers()
    await lane.start()

    for _ in range(6):
        device.push()
        await asyncio.sleep(0)
    await until(lambda: "wake_word" in lane.source_failures, timeout=3)

    assert lane.live_sources == (ExplicitAddressSource.MANUAL_KEY,)
    assert lane.source_failures["wake_word"] == "WakeWordDetectorFailed"
    assert "explicit_address_source_failed" in journal.codes(level="error")

    await manual.queue.put("f9")
    trigger = await asyncio.wait_for(anext(triggers), timeout=2)
    assert trigger.source is ExplicitAddressSource.MANUAL_KEY
    await lane.close()
    await hub.close()


async def test_a_wake_backend_that_never_started_raises_on_detections_rather_than_blocking():
    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()

    def explode():
        raise RuntimeError("no porcupine access key")

    wake = SharedPcmWakeWordBackend(hub=hub, engine_factory=explode)
    with pytest.raises(WakeWordDetectorFailed) as raised:
        await asyncio.wait_for(anext(wake.detections()), timeout=2)
    assert raised.value.code == "wake_engine_unavailable"
    await wake.close()
    await hub.close()


async def test_suspending_a_dead_detector_keeps_its_failure_reachable():
    """Le jeton de panne se remet apres une purge : la panne ne s'efface pas
    avec la file."""

    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    wake = SharedPcmWakeWordBackend(hub=hub, engine_factory=lambda: FakeWakeEngine(raise_after=1))
    await wake.start()
    for _ in range(3):
        device.push()
        await asyncio.sleep(0)
    await until(lambda: wake.engine_failed)

    await wake.suspend()
    with pytest.raises(WakeWordDetectorFailed):
        await asyncio.wait_for(anext(wake.detections()), timeout=2)
    await wake.close()
    await hub.close()


# --------------------------------------------------------------------------
# 17. Une perte de peripherique n'est pas un cul-de-sac
# --------------------------------------------------------------------------


async def test_a_turn_opened_after_a_device_loss_refuses_the_shared_capture():
    """S'abonner a un hub mort donnerait un tour qui n'entend rien et ne le dit
    pas : un silence identique a celui d'une piece calme."""

    journal = RecordingJournal()
    now = [0.0]
    device = FakeCaptureDevice()
    session = PresentationAudioSession.build(
        manual_backend=FakeTriggerBackend(), stream_factory=device.factory, journal=journal,
    )
    session.hub.clock = lambda: now[0]
    await session.start()
    assert session.realtime_input_source().__func__ is type(session.hub).attach_input

    now[0] += 99.0
    session.hub.check_liveness()
    assert session.device_lost is True

    with pytest.raises(PresentationAudioError) as raised:
        session.realtime_input_source()
    assert raised.value.code == "presentation_capture_device_lost"
    assert "presentation.audio.device_lost" in journal.kinds()
    await session.stop()


async def test_a_lost_hub_can_be_reopened_once_its_dead_stream_has_been_reaped():
    device = FakeCaptureDevice()
    now = [0.0]
    hub = make_hub(device, clock=lambda: now[0])
    await hub.open()
    now[0] += 99.0
    hub.check_liveness()
    await hub.reap_lost_device()
    assert input_ownership.open_input_stream_count() == 0

    await hub.open()
    assert hub.open_input_streams == 1
    assert input_ownership.open_input_stream_count() == 1, "un seul, pas le cadavre plus le neuf"
    assert device.opens == 2
    await hub.close()


async def test_the_supervisor_reaps_a_lost_device_without_being_asked():
    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal, silence_timeout_s=0.1)
    await hub.open()
    await until(lambda: hub.state is CaptureHubState.LOST, timeout=3)
    await until(lambda: input_ownership.open_input_stream_count() == 0, timeout=3)
    assert hub.open_input_streams == 0
    assert "capture_device_released" in journal.codes(level="warning")
    await hub.close()


# --------------------------------------------------------------------------
# 18. La contre-pression se dit, et la suspension compte ce qu'elle jette
# --------------------------------------------------------------------------


async def test_backpressure_is_not_only_counted_but_said():
    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal)
    await hub.open()
    subscription = hub.subscribe("ambient", max_blocks=2)
    for _ in range(20):
        device.push()

    assert subscription.dropped == 18
    assert hub.report_backpressure() == 1
    lines = journal.of_kind("audio.capture_hub.backpressure")
    assert len(lines) == 1
    assert lines[0]["level"] == "warning"
    assert lines[0]["data"]["dropped"] == 18  # type: ignore[index]
    assert lines[0]["data"]["since_last"] == 18  # type: ignore[index]

    # Rien de neuf a dire tant que le compte n'a pas bouge : une salle bruyante
    # ne doit pas inonder le journal a 4 Hz.
    assert hub.report_backpressure() == 0
    device.push()
    device.push()
    assert hub.report_backpressure() == 1
    assert journal.of_kind("audio.capture_hub.backpressure")[-1]["data"]["since_last"] == 2  # type: ignore[index]
    await hub.close()


async def test_suspending_the_lane_counts_and_names_the_presses_it_throws_away():
    journal = RecordingJournal()
    manual = FakeTriggerBackend()
    lane = ExplicitAddressLane(journal=journal)
    lane.add_source(ExplicitAddressSource.MANUAL_KEY, manual)
    await lane.start()
    lane._admit(ExplicitAddressSource.MANUAL_KEY, "f9")
    lane._admit(ExplicitAddressSource.MANUAL_KEY, "f9")

    await lane.suspend_for_active_session()
    assert lane.discarded == 2
    assert "explicit_address_discarded" in journal.codes(level="warning")
    assert lane.stats()["discarded"] == 2
    await lane.close()


async def test_suspending_the_shared_wake_detector_counts_what_it_erases():
    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal)
    await hub.open()
    wake = SharedPcmWakeWordBackend(
        hub=hub, engine_factory=lambda: FakeWakeEngine(detect_after=1), journal=journal,
    )
    await wake.start()
    for _ in range(4):
        device.push()
        await asyncio.sleep(0)
    await until(lambda: wake.detections_count > 0)

    await wake.suspend()
    assert wake.discarded >= 1
    assert "wake_detection_discarded" in journal.codes(level="warning")
    await wake.close()
    await hub.close()


# --------------------------------------------------------------------------
# 19. Le pre-roll ne raconte pas la seance precedente
# --------------------------------------------------------------------------


def test_clearing_the_preroll_forgets_that_it_was_ever_truncated():
    """`truncated` etait un verrou a vie : un anneau neuf se declarait tronque
    en ne tenant rien, ce qui decrivait la seance d'avant."""

    ring = PreRollRing(sample_rate=HUB_RATE, preroll_ms=50)
    for _ in range(10):
        ring.append(BLOCK)
    assert ring.evicted_bytes > 0
    ring.clear()
    assert ring.evicted_bytes == 0 and ring.bytes_held == 0


async def test_a_second_session_does_not_inherit_the_truncation_of_the_first():
    device = FakeCaptureDevice()
    hub = make_hub(device, preroll_ms=50)
    await hub.open()
    for _ in range(10):
        device.push()
    assert hub.preroll.evicted_bytes > 0
    await hub.close()

    await hub.open()
    trigger = ExplicitAddressTrigger.admitted(ExplicitAddressSource.MANUAL_KEY, "f9", sequence=0)
    session = PresentationAudioSession(hub=hub, lane=ExplicitAddressLane())
    assert session.command_preroll(trigger).truncated is False
    await hub.close()


# --------------------------------------------------------------------------
# 20. Le raccord PortAudio, jusqu'a sa mise en route
# --------------------------------------------------------------------------


async def test_a_shared_input_delivers_nothing_before_start_just_like_a_real_stream(monkeypatch):
    """Un `RawInputStream` ne livre rien avant `.start()`. L'abonnement partage
    non plus, desormais : sans cela des blocs arrivaient entre `subscribe()` et
    l'ouverture de la sortie, une fenetre que le chemin d'origine n'a pas."""

    monkeypatch.setitem(sys.modules, "sounddevice", OutputOnlySoundDevice)
    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    received: list[bytes] = []
    subscription = hub.attach_input(lambda block, frames, t, status: received.append(block))

    assert subscription.started is False
    device.push()
    assert received == [], "rien avant start()"

    subscription.start()
    device.push()
    assert len(received) == 1

    subscription.stop()
    device.push()
    assert len(received) == 1, "rien apres stop()"
    await hub.close()


async def test_the_interactive_path_receives_nothing_until_its_own_start_completes(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", OutputOnlySoundDevice)
    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    audio = SoundDeviceRealtimeAudio(input_source=hub.attach_input)
    await audio.start()
    device.push()
    await asyncio.sleep(0)
    assert audio.captured_bytes == len(BLOCK)
    await audio.close()
    await hub.close()


async def test_closing_a_shared_subscription_from_a_worker_thread_is_safe(monkeypatch):
    """`SoundDeviceRealtimeAudio._shutdown_stream` tourne dans un
    `asyncio.to_thread` ; `asyncio.Event.set()` hors de la boucle n'est pas sur
    et leve sous PYTHONASYNCIODEBUG."""

    monkeypatch.setitem(sys.modules, "sounddevice", OutputOnlySoundDevice)
    asyncio.get_running_loop().set_debug(True)
    try:
        device = FakeCaptureDevice()
        hub = make_hub(device)
        await hub.open()
        audio = SoundDeviceRealtimeAudio(input_source=hub.attach_input)
        await audio.start()
        assert len(hub.subscriptions) == 1

        await audio.close()
        await until(lambda: hub.subscriptions == ())
        assert hub.open_input_streams == 1, "fermer l'abonne ne ferme pas le micro"
        await hub.close()
    finally:
        asyncio.get_running_loop().set_debug(False)


# --------------------------------------------------------------------------
# 21. La limite assumee : un abonne EN LIGNE n'est pas isole
# --------------------------------------------------------------------------


async def test_a_slow_inline_sink_starves_its_siblings_and_that_is_the_documented_limit():
    """Mesure de la limite plutot que decouverte plus tard : un sink en ligne
    s'execute *sur* le thread de capture, donc il retarde tout le bloc. C'est
    le prix de l'annulation d'echo dans le thread audio, et c'est pourquoi il
    n'existe qu'un seul abonne en ligne."""

    device = FakeCaptureDevice()
    hub = make_hub(device)
    await hub.open()
    order: list[str] = []

    def slow(block: bytes) -> None:
        order.append("inline")
        time.sleep(0.01)

    inline = hub.subscribe("interactive", sink=slow)
    inline.start()
    queued = hub.subscribe("ambient")

    started = time.monotonic()
    for _ in range(10):
        device.push()
    elapsed = time.monotonic() - started

    assert len(order) == 10
    assert elapsed >= 0.09, f"le sink lent n'a pas retarde le thread de capture: {elapsed:.3f}s"
    # L'abonne en file a bien recu ses blocs, mais il les a recus **en retard**,
    # derriere le sink : c'est la limite, et elle est ecrite dans l'en-tete du
    # module et dans docs/presentation-audio-capture.md.
    assert queued.delivered == 10
    await hub.close()


async def test_an_inline_failure_burst_spread_over_time_does_not_detach_the_lane():
    """La fenetre est ce qui rend le compteur honnete : sans elle, trois
    accrocs isoles espaces d'une minute finiraient par detacher l'abonne, ce
    qui est exactement le resultat que cette politique existe pour eviter."""

    journal = RecordingJournal()
    now = [0.0]
    device = FakeCaptureDevice()
    hub = make_hub(device, journal=journal, clock=lambda: now[0])
    await hub.open()

    def always_fails(block: bytes) -> None:
        raise ValueError("boom")

    inline = hub.subscribe("interactive", sink=always_fails)
    inline.start()
    for _ in range(MAX_CONSECUTIVE_SINK_FAILURES + 5):
        device.push()
        now[0] += SINK_FAILURE_WINDOW_S + 0.5  # un accroc isole, puis une accalmie

    assert inline.failures == MAX_CONSECUTIVE_SINK_FAILURES + 5
    assert inline.consecutive_failures == 1
    assert inline.closed is False, "des accrocs espaces ne sont pas une panne"
    assert inline.detached_reason is None

    # Rapproches, en revanche, ils detachent.
    for _ in range(MAX_CONSECUTIVE_SINK_FAILURES):
        device.push()
        now[0] += 0.05
    assert inline.detached_reason == "capture_sink_failed"
    await hub.close()

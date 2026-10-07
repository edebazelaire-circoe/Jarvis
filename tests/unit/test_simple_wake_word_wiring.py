"""Slice 05 (jarvis-wake-word) - le détecteur SIMPLE à flux propre accepte un moteur injecté.

Ce que cette suite doit prouver, par des comportements et jamais par du texte
source (la seule exception, la conformité des ouvreurs, vit dans
`test_presentation_audio_capture.py`) :

- **D1, le défaut ne change rien.** Bloc absent ou `enabled=false` : la
  composition SIMPLE est celle d'avant (Porcupine si clé, rien sinon), aucun
  flux n'est ouvert, `openwakeword` n'est jamais atteint.
- **Un seul fournisseur de repos.** Porcupine ET openWakeWord présents : celui du
  bloc, l'autre n'est même pas instancié. Jamais deux flux de repos.
- **Le rappel PortAudio ne fait que mettre en file.** Le test regarde le thread
  qui appelle `engine.process` : ni le thread du rappel, ni la boucle asyncio.
  Le moteur est le vrai `OpenWakeWordEngine` (seul le modèle ONNX est remplacé),
  donc `wake_frame_invalid` tomberait si une trame n'était pas un TUPLE de 1280
  entiers.
- **File bornée, perte comptée et dite**, rappel jamais bloqué.
- **D14 / anti-écho** : un flux au repos, fermé pendant ACTIVE, rouvert après
  `mute()`, zéro après `close()`, le propriétaire libéré sur toute sortie.
- **Panne dite** (`wake_engine_unavailable`, `wake_engine_failed`), sans flux
  inutile, F9 intacte.

Aucun vrai micro, aucun `openwakeword`, aucun `onnxruntime`.
"""

from __future__ import annotations

import asyncio
import queue
import sys
import threading

import pytest

from jarvis.adapters import wakeword_openwakeword as oww
from jarvis.adapters import wakeword_porcupine
from jarvis.adapters.wakeword_composite import CompositeWakeWordBackend
from jarvis.adapters.wakeword_own_stream import (
    PCM_QUEUE_BLOCKS,
    OwnStreamWakeWordBackend,
)
from jarvis.audio import input_ownership
from jarvis.runtime import simple_wake_word
from jarvis.runtime import wake_word_settings as wws

from tests.unit.test_ambient_ingestion_lane import RecordingJournal, until

FRAME = oww.FRAME_LENGTH  # 1280 échantillons, 80 ms à 16 kHz


@pytest.fixture(autouse=True)
def clean_input_registry():
    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


# --------------------------------------------------------------------------
# Doubles
# --------------------------------------------------------------------------


class FakeScorer:
    """Le modèle ONNX remplacé : il note qui l'appelle, avec quoi, et rend un score."""

    def __init__(self, *, scores=None, default: float = 0.0, fail_after: int | None = None,
                 gate: threading.Event | None = None) -> None:
        self.scores = list(scores or [])
        self.default = default
        self.fail_after = fail_after
        self.gate = gate
        self.entered = threading.Event()
        self.frames: list[object] = []
        self.threads: list[int] = []
        self.closed = 0

    def score(self, pcm) -> float:  # noqa: ANN001
        self.frames.append(pcm)
        self.threads.append(threading.get_ident())
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(5), "le test n'a jamais libéré le moteur"
        if self.fail_after is not None and len(self.frames) > self.fail_after:
            raise RuntimeError("onnx exploded")
        return self.scores.pop(0) if self.scores else self.default

    def close(self) -> None:
        self.closed += 1


def install_scorer(monkeypatch, scorer: FakeScorer) -> list[tuple]:
    calls: list[tuple] = []

    def fake_load(spec, model_dir):  # noqa: ANN001
        calls.append((spec.key, model_dir))
        return scorer

    monkeypatch.setattr(oww, "_load_scorer", fake_load)
    return calls


class FakeRawInputStream:
    """`sd.RawInputStream` factice : il garde son rappel et note son cycle de vie."""

    def __init__(self, registry: "FakeSoundDevice", kwargs: dict) -> None:
        self.registry = registry
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.started = False
        self.stopped = 0
        self.closed = 0

    def start(self) -> None:
        if self.registry.fail_start:
            raise OSError("device busy")
        self.started = True

    def stop(self) -> None:
        self.stopped += 1
        if self.registry.fail_stop:
            raise OSError("stop failed")

    def close(self) -> None:
        self.closed += 1
        if self.registry.fail_close:
            raise OSError("close failed")


class FakeSoundDevice:
    """Le module `sounddevice` factice ; `rates_refused` simule un taux non pris en charge."""

    def __init__(self) -> None:
        self.streams: list[FakeRawInputStream] = []
        self.attempts: list[dict] = []
        self.fail_open = False
        self.fail_start = False
        self.fail_stop = False
        self.fail_close = False
        self.rates_refused: set[int] = set()

    def RawInputStream(self, **kwargs):  # noqa: ANN003, N802
        self.attempts.append(kwargs)
        if self.fail_open or kwargs["samplerate"] in self.rates_refused:
            raise OSError("invalid sample rate")
        stream = FakeRawInputStream(self, kwargs)
        self.streams.append(stream)
        return stream


@pytest.fixture
def sd(monkeypatch) -> FakeSoundDevice:
    fake = FakeSoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return fake


def pcm_block(samples: int, value: int = 1000) -> bytes:
    import array

    return array.array("h", [value] * samples).tobytes()


def from_portaudio_thread(stream: FakeRawInputStream, *blocks: bytes) -> int:
    """Appeler le rappel depuis un thread à part, comme PortAudio. Rend son identifiant."""

    seen: list[int] = []

    def run() -> None:
        seen.append(threading.get_ident())
        for block in blocks:
            stream.callback(block, len(block) // 2, None, None)

    thread = threading.Thread(target=run, name="fake-portaudio")
    thread.start()
    thread.join(5)
    assert not thread.is_alive(), "le rappel PortAudio est resté bloqué"
    return seen[0]


def settings(**fields) -> wws.WakeWordSettings:
    provider = fields.get("provider", wws.DEFAULT_PROVIDER)
    fields.setdefault("keyword", wws.default_keyword(provider))
    return wws.WakeWordSettings(**fields)


def oww_backend(monkeypatch, scorer: FakeScorer | None = None, *, journal=None,
                fallback_sample_rate=None, **kwargs) -> tuple[OwnStreamWakeWordBackend, FakeScorer]:
    scorer = scorer or FakeScorer()
    install_scorer(monkeypatch, scorer)
    backend = OwnStreamWakeWordBackend(
        engine_factory=oww.openwakeword_engine_factory(keyword="hey_jarvis", sensitivity=0.5, cooldown_ms=2000,
                                                       journal=journal),
        keyword="hey_jarvis", provider="openwakeword", device=3,
        fallback_sample_rate=fallback_sample_rate, journal=journal, **kwargs,
    )
    return backend, scorer


def lines(journal: RecordingJournal, kind: str) -> list[dict]:
    return [entry for entry in journal.entries if entry["kind"] == kind]


# --------------------------------------------------------------------------
# 1. D1 : le défaut est le comportement d'avant
# --------------------------------------------------------------------------


@pytest.fixture
def porcupine_spy(monkeypatch):
    built: list[dict] = []

    class SpyPorcupine:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            built.append(kwargs)

    monkeypatch.setattr(simple_wake_word, "PorcupineWakeWordBackend", SpyPorcupine)
    return built


@pytest.mark.parametrize("block", [None, settings(enabled=False), settings(enabled=False, provider="openwakeword")])
def test_disabled_by_default_opens_no_stream_in_simple(monkeypatch, sd, porcupine_spy, block):
    scorer_calls = install_scorer(monkeypatch, FakeScorer())

    backends = simple_wake_word.simple_wake_backends(
        block=block, access_key="", keyword="jarvis", device=None,
    )

    assert backends == []
    assert porcupine_spy == [] and scorer_calls == [] and sd.attempts == []
    assert input_ownership.open_input_stream_count() == 0


@pytest.mark.parametrize("block", [None, settings(enabled=False), settings(enabled=False, provider="openwakeword"),
                                   settings(enabled=True)])
def test_porcupine_path_is_unchanged(monkeypatch, sd, porcupine_spy, block):
    scorer_calls = install_scorer(monkeypatch, FakeScorer())

    backends = simple_wake_word.simple_wake_backends(
        block=block, access_key="KEY", keyword="computer", device=7,
    )

    assert len(backends) == 1 and type(backends[0]).__name__ == "SpyPorcupine"
    assert porcupine_spy == [{"access_key": "KEY", "keyword": "computer", "device": 7}]
    assert scorer_calls == [] and sd.attempts == []


def test_the_real_porcupine_backend_is_what_the_default_builds(sd):
    backends = simple_wake_word.simple_wake_backends(
        block=None, access_key="KEY", keyword="jarvis", device=2,
    )

    assert [type(backend) for backend in backends] == [wakeword_porcupine.PorcupineWakeWordBackend]
    assert backends[0].device == 2 and sd.attempts == []


def test_both_providers_present_builds_only_the_one_the_block_names(monkeypatch, sd, porcupine_spy):
    """Politique : jamais deux flux de repos. Une clé Porcupine ET openWakeWord activé :
    openWakeWord seul, Porcupine n'est même pas instancié."""

    install_scorer(monkeypatch, FakeScorer())

    backends = simple_wake_word.simple_wake_backends(
        block=settings(enabled=True, provider="openwakeword"), access_key="KEY", keyword="jarvis", device=None,
    )

    assert [type(backend) for backend in backends] == [OwnStreamWakeWordBackend]
    assert porcupine_spy == []


def test_the_policy_never_yields_two_resting_backends(monkeypatch, sd, porcupine_spy):
    install_scorer(monkeypatch, FakeScorer())
    for block in (None, settings(enabled=False), settings(enabled=True), settings(enabled=True, provider="openwakeword")):
        for key in ("", "KEY"):
            backends = simple_wake_word.simple_wake_backends(block=block, access_key=key, keyword="jarvis", device=None)
            assert len(backends) <= 1, (block, key)


def test_the_openwakeword_choice_reuses_the_presentation_selection(monkeypatch, sd):
    """Une seule sélection de fabrique : SIMPLE appelle celle de la Slice 04."""

    from jarvis.runtime import presentation_runtime

    calls: list[dict] = []
    real = presentation_runtime.openwakeword_engine_selection

    def spy(block, **kwargs):  # noqa: ANN001, ANN003
        calls.append(kwargs)
        return real(block, **kwargs)

    monkeypatch.setattr(presentation_runtime, "openwakeword_engine_selection", spy)
    install_scorer(monkeypatch, FakeScorer())

    simple_wake_word.simple_wake_backends(
        block=settings(enabled=True, provider="openwakeword"), access_key="", keyword="jarvis", device=None,
    )

    assert len(calls) == 1


# --------------------------------------------------------------------------
# 2. Un seul flux, inscrit, inférence hors rappel, trames en tuples de 1280
# --------------------------------------------------------------------------


async def test_enabled_opens_exactly_one_registered_stream(monkeypatch, sd):
    backend, _ = oww_backend(monkeypatch)

    await backend.start()
    await backend.start()  # idempotent

    assert len(sd.streams) == 1 and sd.streams[0].started
    assert input_ownership.open_input_stream_count() == 1
    assert [entry.owner for entry in input_ownership.open_input_streams()] == [
        input_ownership.OWNER_WAKEWORD_OPENWAKEWORD
    ]
    kwargs = sd.streams[0].kwargs
    assert (kwargs["samplerate"], kwargs["channels"], kwargs["dtype"], kwargs["device"]) == (16000, 1, "int16", 3)
    await backend.close()
    assert input_ownership.open_input_stream_count() == 0


async def test_concurrent_start_and_resume_never_open_two_streams(monkeypatch, sd):
    backend, _ = oww_backend(monkeypatch)

    await asyncio.gather(backend.start(), backend.resume(), backend.start())

    assert len(sd.attempts) == 1
    assert input_ownership.open_input_stream_count() == 1
    await backend.close()


async def test_the_portaudio_callback_never_runs_inference(monkeypatch, sd):
    backend, scorer = oww_backend(monkeypatch)
    await backend.start()
    loop_thread = threading.get_ident()

    callback_thread = from_portaudio_thread(sd.streams[0], pcm_block(FRAME), pcm_block(FRAME))
    await until(lambda: len(scorer.frames) == 2)

    assert scorer.threads, "aucune inférence n'a eu lieu"
    assert callback_thread not in scorer.threads, "l'inférence a tourné dans le rappel PortAudio"
    assert loop_thread not in scorer.threads, "l'inférence a tourné sur la boucle asyncio"
    await backend.close()


async def test_frames_reach_the_engine_as_tuples_of_1280_ints(monkeypatch, sd):
    backend, scorer = oww_backend(monkeypatch)
    await backend.start()

    # Des blocs de 512 échantillons : 5 blocs = 2560 = exactement deux trames.
    from_portaudio_thread(sd.streams[0], *[pcm_block(512, value=index + 1) for index in range(5)])
    await until(lambda: len(scorer.frames) == 2)

    for frame in scorer.frames:
        assert type(frame) is tuple and len(frame) == FRAME
        assert all(type(sample) is int for sample in frame)
    assert scorer.frames[0][:512] == (1,) * 512 and scorer.frames[0][512:1024] == (2,) * 512
    assert backend.engine_failed is False
    await backend.close()


async def test_a_partial_frame_waits_for_the_rest(monkeypatch, sd):
    backend, scorer = oww_backend(monkeypatch)
    await backend.start()

    from_portaudio_thread(sd.streams[0], pcm_block(FRAME - 1))
    await asyncio.sleep(0.15)
    assert scorer.frames == []
    from_portaudio_thread(sd.streams[0], pcm_block(1))
    await until(lambda: len(scorer.frames) == 1)
    await backend.close()


async def test_a_microphone_at_another_rate_is_resampled_to_16k_off_the_callback(monkeypatch, sd):
    sd.rates_refused = {16000}
    backend, scorer = oww_backend(monkeypatch, fallback_sample_rate=24000)
    await backend.start()

    assert [attempt["samplerate"] for attempt in sd.attempts] == [16000, 24000]
    assert input_ownership.open_input_stream_count() == 1
    callback_thread = from_portaudio_thread(sd.streams[0], *[pcm_block(1920) for _ in range(4)])  # 4 x 80 ms
    await until(lambda: len(scorer.frames) >= 3)

    assert all(len(frame) == FRAME for frame in scorer.frames)
    assert callback_thread not in scorer.threads
    await backend.close()


async def test_when_no_rate_is_usable_the_stream_is_said_not_opened(monkeypatch, sd):
    sd.fail_open = True
    journal = RecordingJournal()
    backend, _ = oww_backend(monkeypatch, journal=journal, fallback_sample_rate=24000)

    await backend.start()  # ne lève pas : Jarvis démarre, F9 reste

    assert input_ownership.open_input_stream_count() == 0
    assert "wake_input_unavailable" in journal.codes("error")
    assert backend.engine_failed is False  # une panne de périphérique peut se réessayer
    sd.fail_open = False
    await backend.resume()
    assert input_ownership.open_input_stream_count() == 1
    await backend.close()


async def test_a_missing_sounddevice_is_said_without_building_the_engine(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    journal = RecordingJournal()
    scorer_calls = install_scorer(monkeypatch, FakeScorer())
    backend = OwnStreamWakeWordBackend(
        engine_factory=oww.openwakeword_engine_factory(), keyword="hey_jarvis", journal=journal,
    )

    await backend.start()

    assert scorer_calls == []
    assert "wake_input_unavailable" in journal.codes("error")
    assert input_ownership.open_input_stream_count() == 0


# --------------------------------------------------------------------------
# 3. File bornée : perte comptée et dite, rappel jamais bloqué
# --------------------------------------------------------------------------


async def test_a_full_queue_drops_counted_frames_without_blocking(monkeypatch, sd):
    gate = threading.Event()
    journal = RecordingJournal()
    backend, scorer = oww_backend(monkeypatch, FakeScorer(gate=gate), journal=journal)
    await backend.start()
    stream = sd.streams[0]

    from_portaudio_thread(stream, pcm_block(FRAME))
    assert await asyncio.to_thread(scorer.entered.wait, 5), "le consommateur n'a pas démarré"
    # Le moteur est maintenant bloqué ; la file se remplit puis déborde, et le rappel revient chaque fois.
    overflow = 5
    from_portaudio_thread(stream, *[pcm_block(FRAME) for _ in range(PCM_QUEUE_BLOCKS + overflow)])

    assert backend.pcm_blocks_dropped == overflow
    gate.set()
    await until(lambda: lines(journal, "wake.own_stream.dropped"))
    said = lines(journal, "wake.own_stream.dropped")[0]
    assert said["level"] == "warning" and said["data"]["code"] == "wake_pcm_dropped"
    assert said["data"]["pcm_blocks_dropped"] >= 1
    await backend.close()
    assert lines(journal, "wake.own_stream.stopped")[-1]["data"]["pcm_blocks_dropped"] == overflow


async def test_suspend_does_not_wait_for_a_stuck_inference_forever(monkeypatch, sd):
    gate = threading.Event()
    journal = RecordingJournal()
    backend, scorer = oww_backend(monkeypatch, FakeScorer(gate=gate), journal=journal)
    await backend.start()
    from_portaudio_thread(sd.streams[0], pcm_block(FRAME))
    assert await asyncio.to_thread(scorer.entered.wait, 5)

    backend.join_timeout_s = 0.05
    await backend.suspend()

    assert input_ownership.open_input_stream_count() == 0
    assert "wake_consumer_stuck" in journal.codes("warning")
    gate.set()


# --------------------------------------------------------------------------
# 4. D14 / anti-écho : fermé pendant ACTIVE, rouvert après mute(), jamais deux flux
# --------------------------------------------------------------------------


async def test_stream_is_closed_during_active_and_reopened_after_mute(monkeypatch, sd):
    backend, scorer = oww_backend(monkeypatch)
    await backend.start()
    first = sd.streams[0]
    peak = [input_ownership.open_input_stream_count()]

    await backend.suspend_for_active_session()
    assert first.stopped == 1 and first.closed == 1
    assert input_ownership.open_input_stream_count() == 0

    # Pendant ACTIVE, c'est le flux de la session Realtime qui possède le micro.
    realtime = object()
    input_ownership.register_input_stream(input_ownership.OWNER_REALTIME_AUDIO, realtime)
    peak.append(input_ownership.open_input_stream_count())
    # Un rappel en retard de l'ancien flux ne fait plus rien.
    from_portaudio_thread(first, pcm_block(FRAME))
    await asyncio.sleep(0.15)
    assert scorer.frames == []
    input_ownership.release_input_stream(realtime)

    await backend.resume()  # fin de mute()
    peak.append(input_ownership.open_input_stream_count())
    assert len(sd.streams) == 2 and sd.streams[1].started
    from_portaudio_thread(sd.streams[1], pcm_block(FRAME))
    await until(lambda: len(scorer.frames) == 1)

    assert max(peak) == 1, "deux propriétaires du micro à la fois"
    await backend.close()
    assert input_ownership.open_input_stream_count() == 0
    assert sd.streams[1].closed == 1


async def test_a_resumed_detector_starts_from_a_clean_engine(monkeypatch, sd):
    """Rien de la séance précédente (ni sa voix ni son état) ne survit à la suspension."""

    backend, scorer = oww_backend(monkeypatch)
    await backend.start()
    await backend.suspend_for_active_session()
    assert scorer.closed == 1
    await backend.resume()
    assert scorer.closed == 1  # le moteur neuf n'est pas encore fermé
    await backend.close()
    assert scorer.closed == 2


async def test_a_detection_pending_at_suspension_is_discarded(monkeypatch, sd):
    backend, scorer = oww_backend(monkeypatch, FakeScorer(default=0.99))
    await backend.start()
    from_portaudio_thread(sd.streams[0], pcm_block(FRAME))
    await until(lambda: backend.detections_count == 1)

    await backend.suspend_for_active_session()
    await backend.resume()

    assert backend._queue.empty()
    await backend.close()


async def test_close_is_final_and_releases_everything(monkeypatch, sd):
    backend, scorer = oww_backend(monkeypatch)
    await backend.start()

    await backend.close()
    await backend.resume()
    await backend.start()

    assert input_ownership.open_input_stream_count() == 0
    assert len(sd.streams) == 1 and scorer.closed == 1


# --------------------------------------------------------------------------
# 5. Le propriétaire est libéré sur toutes les sorties
# --------------------------------------------------------------------------


@pytest.mark.parametrize("failing", ["fail_stop", "fail_close"])
@pytest.mark.parametrize("exit_through", ["suspend", "suspend_for_active_session", "close"])
async def test_close_releases_the_owner_even_if_stream_close_fails(monkeypatch, sd, failing, exit_through):
    journal = RecordingJournal()
    backend, _ = oww_backend(monkeypatch, journal=journal)
    await backend.start()
    setattr(sd, failing, True)

    await getattr(backend, exit_through)()

    assert input_ownership.open_input_stream_count() == 0
    assert "wake_input_close_failed" in journal.codes("warning")
    await backend.close()


async def test_a_stream_that_fails_to_start_is_closed_and_released(monkeypatch, sd):
    sd.fail_start = True
    backend, scorer = oww_backend(monkeypatch, journal=RecordingJournal())

    await backend.start()

    assert input_ownership.open_input_stream_count() == 0
    assert sd.streams[0].closed == 1
    assert scorer.closed == 1, "le moteur construit pour rien doit être libéré"


# --------------------------------------------------------------------------
# 6. Panne dite, sans casser F9
# --------------------------------------------------------------------------


class FakeF9:
    """La touche manuelle : un backend qui ne dépend ni du micro ni du moteur."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()

    async def detections(self):
        while True:
            yield await self.queue.get()

    async def suspend(self) -> None: ...
    async def suspend_for_active_session(self) -> None: ...
    async def resume(self) -> None: ...
    async def close(self) -> None: ...


async def test_a_missing_extra_is_said_without_opening_a_stream_and_f9_still_works(monkeypatch, sd):
    def missing(spec, model_dir):  # noqa: ANN001
        raise oww.WakeEngineError("wake_engine_unavailable", "openwakeword absent",
                                  cause_code="wake_package_missing")

    monkeypatch.setattr(oww, "_load_scorer", missing)
    journal = RecordingJournal()
    f9 = FakeF9()
    backends = simple_wake_word.simple_wake_backends(
        block=settings(enabled=True, provider="openwakeword"), access_key="", keyword="jarvis", device=None,
        journal=journal,
    )
    composite = CompositeWakeWordBackend([f9, *backends])
    detections = composite.detections()
    pending = asyncio.create_task(anext(detections))
    await asyncio.sleep(0.1)

    failed = lines(journal, "wake.own_stream.failed")
    assert failed and failed[0]["level"] == "error"
    assert failed[0]["data"]["code"] == "wake_engine_unavailable"
    assert failed[0]["data"]["cause_code"] == "wake_package_missing"
    assert sd.attempts == [] and input_ownership.open_input_stream_count() == 0
    assert backends[0].engine_failed and backends[0].failure_code == "wake_engine_unavailable"

    await f9.queue.put("f9")
    assert await asyncio.wait_for(pending, 2) == "f9"
    await composite.suspend()
    await composite.suspend_for_active_session()
    await composite.resume()  # ne relance pas un moteur tombé
    assert sd.attempts == []
    await composite.close()


async def test_a_refused_configuration_is_said_not_fatal(monkeypatch, sd):
    scorer_calls = install_scorer(monkeypatch, FakeScorer())
    journal = RecordingJournal()
    backends = simple_wake_word.simple_wake_backends(
        block=settings(enabled=True, provider="openwakeword", keyword="not_a_model"),
        access_key="", keyword="jarvis", device=None, journal=journal,
    )

    await backends[0].start()

    assert scorer_calls == [] and sd.attempts == []
    failed = lines(journal, "wake.own_stream.failed")[0]["data"]
    assert failed["code"] == "wake_engine_unavailable" and failed["cause_code"] == "wake_config_invalid"


async def test_an_inference_failure_stops_the_detector_says_so_and_frees_the_microphone(monkeypatch, sd):
    journal = RecordingJournal()
    backend, scorer = oww_backend(monkeypatch, FakeScorer(fail_after=1), journal=journal)
    f9 = FakeF9()
    composite = CompositeWakeWordBackend([f9, backend])
    detections = composite.detections()
    pending = asyncio.create_task(anext(detections))
    await until(lambda: len(sd.streams) == 1)

    from_portaudio_thread(sd.streams[0], pcm_block(FRAME), pcm_block(FRAME))
    await until(lambda: backend.engine_failed)
    await until(lambda: input_ownership.open_input_stream_count() == 0)

    failed = lines(journal, "wake.own_stream.failed")[0]
    assert failed["data"]["code"] == "wake_engine_failed"
    assert failed["data"]["cause_code"] == "wake_inference_failed"
    assert sd.streams[0].closed == 1 and scorer.closed == 1

    await f9.queue.put("f9")
    assert await asyncio.wait_for(pending, 2) == "f9"
    await composite.resume()
    assert len(sd.streams) == 1, "un détecteur tombé ne rouvre pas le micro"
    await composite.close()


# --------------------------------------------------------------------------
# 7. Détection : étiquette vers Voice, traces sans audio ni texte
# --------------------------------------------------------------------------


ALLOWED_DATA_KEYS = {
    "code", "cause_code", "keyword", "provider", "score", "threshold", "engine_sample_rate",
    "stream_sample_rate", "resampled", "dropped", "discarded", "pcm_blocks_dropped", "frames",
    "detections", "device",
}


async def test_detection_reaches_voice_as_a_wake_word_label(monkeypatch, sd):
    journal = RecordingJournal()
    backend, _ = oww_backend(monkeypatch, FakeScorer(scores=[0.0, 0.97]), journal=journal)
    composite = CompositeWakeWordBackend([FakeF9(), backend])
    detections = composite.detections()
    pending = asyncio.create_task(anext(detections))
    await until(lambda: len(sd.streams) == 1)

    from_portaudio_thread(sd.streams[0], pcm_block(FRAME), pcm_block(FRAME))

    assert await asyncio.wait_for(pending, 3) == "hey_jarvis"
    detected = lines(journal, "wake.own_stream.detected")
    assert len(detected) == 1
    data = detected[0]["data"]
    assert data["keyword"] == "hey_jarvis" and data["provider"] == "openwakeword"
    assert data["score"] == pytest.approx(0.97) and data["threshold"] == pytest.approx(0.5)
    await composite.close()


async def test_traces_carry_scalars_only_and_no_audio_is_persisted(monkeypatch, sd, tmp_path):
    monkeypatch.chdir(tmp_path)
    journal = RecordingJournal()
    backend, _ = oww_backend(monkeypatch, FakeScorer(default=0.99), journal=journal)
    await backend.start()
    from_portaudio_thread(sd.streams[0], pcm_block(FRAME, value=4242))
    await until(lambda: backend.detections_count == 1)
    await backend.suspend_for_active_session()
    await backend.resume()
    await backend.close()

    assert journal.entries
    for entry in journal.entries:
        assert set(entry["data"]) <= ALLOWED_DATA_KEYS, entry
        assert all(isinstance(value, (str, int, float, bool)) for value in entry["data"].values()), entry
    assert "4242" not in journal.blob() and "bytes" not in journal.blob()
    assert list(tmp_path.iterdir()) == [], "le détecteur a écrit un fichier"
    assert not backend._carry and backend._pcm is None


async def test_a_porcupine_style_engine_is_traced_without_score(monkeypatch, sd):
    class IntEngine:
        frame_length = 512
        sample_rate = 16000

        def __init__(self) -> None:
            self.calls = 0

        def process(self, pcm) -> int:  # noqa: ANN001
            self.calls += 1
            assert type(pcm) is tuple and len(pcm) == 512
            return 0 if self.calls == 1 else -1

        def delete(self) -> None: ...

    journal = RecordingJournal()
    backend = OwnStreamWakeWordBackend(engine_factory=IntEngine, keyword="jarvis", provider="porcupine", journal=journal)
    await backend.start()
    from_portaudio_thread(sd.streams[0], pcm_block(512), pcm_block(512))
    await until(lambda: backend.detections_count == 1)

    data = lines(journal, "wake.own_stream.detected")[0]["data"]
    assert data == {"keyword": "jarvis", "provider": "porcupine"}
    await backend.close()

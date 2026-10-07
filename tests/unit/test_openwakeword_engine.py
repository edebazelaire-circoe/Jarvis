"""Slice 02 de `jarvis-wake-word` : `OpenWakeWordEngine` derrière `WakeWordEngine`.

Aucun test de cette suite n'a besoin d'`openwakeword`, d'`onnxruntime`, du
réseau ni d'un micro : le modèle est un faux qui rejoue des scores injectés, et
quand le chargement réel est exercé, c'est contre un faux module `openwakeword`
posé dans `sys.modules`. Le seul test contre le vrai modèle est marqué `live`
et reste ignoré sans opt-in explicite.
"""

from __future__ import annotations

import ast
import asyncio
import math
import os
from pathlib import Path
import sys
import types

import pytest

from jarvis.adapters import wakeword_model_catalog as catalog
from jarvis.adapters import wakeword_openwakeword as oww
from jarvis.adapters.wakeword_openwakeword import (
    DEFAULT_SLOW_CALL_MS,
    OpenWakeWordEngine,
    WakeEngineError,
    openwakeword_engine_factory,
    threshold_from_sensitivity,
)
from jarvis.adapters.wakeword_shared_pcm import SharedPcmWakeWordBackend, WakeWordEngine
from jarvis.audio import input_ownership
from jarvis.audio.capture_hub import AudioCaptureHub

FRAME = tuple(range(-640, 640))  # 1280 échantillons int16
SILENCE = (0,) * 1280


class ScriptedModel:
    """Modèle faux : rejoue des scores, compte ce qu'on lui fait."""

    def __init__(self, scores, *, raise_at: int | None = None, close_raises: bool = False) -> None:
        self.scores = list(scores)
        self.raise_at = raise_at
        self.close_raises = close_raises
        self.calls = 0
        self.closed = 0

    def score(self, pcm) -> float:  # noqa: ANN001
        self.calls += 1
        if self.raise_at is not None and self.calls >= self.raise_at:
            raise RuntimeError("onnx exploded")
        return self.scores[min(self.calls - 1, len(self.scores) - 1)]

    def close(self) -> None:
        self.closed += 1
        if self.close_raises:
            raise OSError("release failed")


class RecordingJournal:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:  # noqa: ANN001
        self.entries.append({"kind": kind, "message": message, "level": level, "data": data or {}})


class StepClock:
    """Horloge déterministe : chaque lecture avance du pas donné."""

    def __init__(self, step_s: float) -> None:
        self.step_s = step_s
        self.now = 0.0
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        self.now += self.step_s if self.reads % 2 == 0 else 0.0
        return self.now


def make_engine(scores, **kwargs) -> tuple[OpenWakeWordEngine, ScriptedModel]:
    model = ScriptedModel(scores)
    kwargs.setdefault("threshold", 0.5)
    kwargs.setdefault("cooldown_frames", 4)
    return OpenWakeWordEngine(model=model, **kwargs), model


# --------------------------------------------------------------------------
# Seuil, score, cooldown
# --------------------------------------------------------------------------


def test_a_score_below_the_threshold_is_not_a_detection():
    engine, _ = make_engine([0.49])
    assert engine.process(FRAME) == -1
    assert engine.below_threshold == 1 and engine.detections == 0


def test_a_score_above_the_threshold_is_a_detection():
    engine, _ = make_engine([0.97])
    assert engine.process(FRAME) == 0
    assert engine.detections == 1


def test_a_score_exactly_at_the_threshold_is_a_detection():
    engine, _ = make_engine([0.5])
    assert engine.process(FRAME) == 0


def test_last_score_is_exposed():
    engine, _ = make_engine([0.1, 0.97, 0.3], cooldown_frames=0)
    assert engine.last_score is None
    engine.process(FRAME)
    assert engine.last_score == pytest.approx(0.1)
    engine.process(FRAME)
    assert engine.last_score == pytest.approx(0.97)
    engine.process(FRAME)
    assert engine.last_score == pytest.approx(0.3)


def test_one_utterance_yields_one_detection_during_the_cooldown():
    engine, _ = make_engine([0.9] * 5, cooldown_frames=4)
    results = [engine.process(FRAME) for _ in range(5)]
    assert results == [0, -1, -1, -1, -1]
    assert engine.detections == 1 and engine.cooldown_ignored == 4


def test_a_detection_after_the_cooldown_is_accepted():
    engine, _ = make_engine([0.9] * 6, cooldown_frames=3)
    results = [engine.process(FRAME) for _ in range(6)]
    assert results == [0, -1, -1, -1, 0, -1]
    assert engine.detections == 2


def test_the_cooldown_counts_frames_not_wall_clock_time():
    clock = StepClock(0.0)
    engine, _ = make_engine([0.9, 0.9, 0.9], cooldown_frames=1, clock=clock)
    assert [engine.process(FRAME) for _ in range(3)] == [0, -1, 0]


def test_frames_below_the_threshold_still_consume_the_cooldown_and_are_counted():
    engine, _ = make_engine([0.9, 0.1, 0.1, 0.9], cooldown_frames=2)
    assert [engine.process(FRAME) for _ in range(4)] == [0, -1, -1, 0]
    assert engine.below_threshold == 2 and engine.cooldown_ignored == 0


def test_a_zero_cooldown_lets_every_loud_frame_through():
    engine, _ = make_engine([0.9, 0.9], cooldown_frames=0)
    assert [engine.process(FRAME) for _ in range(2)] == [0, 0]


# --------------------------------------------------------------------------
# Sensibilité et configuration
# --------------------------------------------------------------------------


def test_sensitivity_maps_monotonically_to_the_threshold():
    values = [threshold_from_sensitivity(step / 20) for step in range(21)]
    assert all(later < earlier for earlier, later in zip(values, values[1:]))
    assert all(0.0 < value < 1.0 for value in values)
    assert threshold_from_sensitivity(0.5) == pytest.approx(0.5)


@pytest.mark.parametrize("bad", [-0.01, 1.01, float("nan"), float("inf"), "0.5", None, True])
def test_out_of_range_sensitivity_is_refused_loudly(bad):
    with pytest.raises(WakeEngineError) as caught:
        threshold_from_sensitivity(bad)
    assert caught.value.code == "wake_config_invalid"


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5, float("nan"), "0.5", None])
def test_an_invalid_threshold_is_refused(bad):
    with pytest.raises(WakeEngineError) as caught:
        OpenWakeWordEngine(model=ScriptedModel([0.0]), threshold=bad)
    assert caught.value.code == "wake_config_invalid"


@pytest.mark.parametrize("bad", [-1, 1.5, None, True, "3"])
def test_an_invalid_cooldown_is_refused(bad):
    with pytest.raises(WakeEngineError) as caught:
        OpenWakeWordEngine(model=ScriptedModel([0.0]), threshold=0.5, cooldown_frames=bad)
    assert caught.value.code == "wake_config_invalid"


@pytest.mark.parametrize("bad", [0, -5, float("nan"), None, "40"])
def test_an_invalid_slow_call_threshold_is_refused(bad):
    with pytest.raises(WakeEngineError) as caught:
        OpenWakeWordEngine(model=ScriptedModel([0.0]), threshold=0.5, slow_call_ms=bad)
    assert caught.value.code == "wake_config_invalid"


def test_the_engine_declares_the_openwakeword_geometry_and_identity():
    engine, _ = make_engine([0.0])
    assert engine.frame_length == 1280 and engine.sample_rate == 16000
    assert engine.provider == "openwakeword" and engine.keyword == "hey_jarvis"
    assert engine.threshold == 0.5


# --------------------------------------------------------------------------
# Trames refusées, pannes dites
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frame",
    [
        (0,) * 1279,
        (0,) * 1281,
        (),
        (0,) * 1279 + (32768,),
        (0,) * 1279 + (-32769,),
        (0,) * 1279 + (0.5,),
        (0,) * 1279 + (True,),
        (0,) * 1279 + ("a",),
        b"\x00" * 2560,
        "x" * 1280,
        None,
        12,
    ],
)
def test_a_malformed_frame_raises_and_never_reaches_the_model(frame):
    engine, model = make_engine([0.9])
    with pytest.raises(WakeEngineError) as caught:
        engine.process(frame)
    assert caught.value.code == "wake_frame_invalid"
    assert model.calls == 0 and engine.last_score is None


def test_the_int16_extremes_are_accepted():
    engine, model = make_engine([0.0])
    engine.process((-32768,) * 640 + (32767,) * 640)
    assert model.calls == 1


def test_an_inference_failure_is_said_and_keeps_the_cause():
    model = ScriptedModel([0.1], raise_at=2)
    engine = OpenWakeWordEngine(model=model, threshold=0.5)
    engine.process(FRAME)
    with pytest.raises(WakeEngineError) as caught:
        engine.process(FRAME)
    assert caught.value.code == "wake_inference_failed"
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "RuntimeError" in str(caught.value)
    assert engine.failures == 1


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.5, 1.5, "0.9", None])
def test_a_score_outside_zero_one_is_an_inference_failure(bad):
    engine, _ = make_engine([bad])
    with pytest.raises(WakeEngineError) as caught:
        engine.process(FRAME)
    assert caught.value.code == "wake_inference_failed"


def test_delete_is_idempotent_and_releases_the_model_once():
    engine, model = make_engine([0.0])
    engine.delete()
    engine.delete()
    assert model.closed == 1


def test_a_deleted_engine_refuses_frames():
    engine, _ = make_engine([0.0])
    engine.delete()
    with pytest.raises(WakeEngineError) as caught:
        engine.process(FRAME)
    assert caught.value.code == "wake_engine_closed"


def test_delete_after_an_inference_failure_still_releases_the_model():
    model = ScriptedModel([0.1], raise_at=1)
    engine = OpenWakeWordEngine(model=model, threshold=0.5)
    with pytest.raises(WakeEngineError):
        engine.process(FRAME)
    engine.delete()
    assert model.closed == 1


def test_a_failing_release_is_raised_once_then_the_engine_stays_deleted():
    model = ScriptedModel([0.0], close_raises=True)
    engine = OpenWakeWordEngine(model=model, threshold=0.5)
    with pytest.raises(OSError):
        engine.delete()
    engine.delete()
    assert model.closed == 1


# --------------------------------------------------------------------------
# Chronométrage
# --------------------------------------------------------------------------


def test_the_default_slow_call_threshold_is_the_d7_guard_of_forty_milliseconds():
    assert DEFAULT_SLOW_CALL_MS == 40.0


def test_a_slow_inference_is_traced_with_its_duration_and_no_audio():
    journal = RecordingJournal()
    engine, _ = make_engine([0.1], journal=journal, clock=StepClock(0.075))
    engine.process(FRAME)
    assert engine.slow_calls == 1
    assert engine.last_process_ms == pytest.approx(75.0)
    (entry,) = journal.entries
    assert entry["kind"] == "wake.openwakeword.slow_inference"
    assert entry["level"] == "warning"
    data = entry["data"]
    assert data["code"] == "wake_inference_slow"
    assert data["duration_ms"] == pytest.approx(75.0) and data["threshold_ms"] == 40.0
    assert FRAME not in data.values() and "pcm" not in data


def test_a_fast_inference_is_not_traced():
    journal = RecordingJournal()
    engine, _ = make_engine([0.1], journal=journal, clock=StepClock(0.005))
    engine.process(FRAME)
    assert journal.entries == [] and engine.slow_calls == 0
    assert engine.max_process_ms == pytest.approx(5.0)


def test_the_slow_call_threshold_is_configurable():
    journal = RecordingJournal()
    engine, _ = make_engine([0.1], journal=journal, clock=StepClock(0.075), slow_call_ms=100.0)
    engine.process(FRAME)
    assert journal.entries == [] and engine.slow_calls == 0


def test_slow_traces_are_throttled_but_every_slow_call_is_counted():
    journal = RecordingJournal()
    engine, _ = make_engine([0.1], journal=journal, clock=StepClock(0.075))
    for _ in range(30):
        engine.process(FRAME)
    assert engine.slow_calls == 30
    assert 1 <= len(journal.entries) < 30
    assert journal.entries[-1]["data"]["slow_calls"] <= 30


def test_a_failing_inference_is_timed_and_does_not_hide_behind_a_slow_trace():
    journal = RecordingJournal()
    model = ScriptedModel([0.1], raise_at=1)
    engine = OpenWakeWordEngine(model=model, threshold=0.5, journal=journal, clock=StepClock(0.075))
    with pytest.raises(WakeEngineError):
        engine.process(FRAME)
    assert engine.slow_calls == 1


# --------------------------------------------------------------------------
# Pas de persistance, pas de flux, contrat
# --------------------------------------------------------------------------


def test_the_engine_opens_no_stream_and_writes_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    input_ownership.reset_for_test()
    journal = RecordingJournal()
    engine, _ = make_engine([0.9, 0.1], journal=journal, clock=StepClock(0.075))
    engine.process(FRAME)
    engine.process(FRAME)
    engine.delete()
    assert list(tmp_path.iterdir()) == []
    assert input_ownership.open_input_stream_count() == 0
    # Le moteur ne retient aucune trame ni aucun échantillon.
    for value in vars(engine).values():
        assert value is not FRAME
        assert not isinstance(value, (bytes, bytearray, tuple)) or value == ()
    assert all("pcm" not in str(entry).lower() for entry in journal.entries)


def test_the_engine_satisfies_the_wakeword_engine_contract():
    engine, _ = make_engine([0.0])
    for name in ("frame_length", "sample_rate", "process", "delete"):
        assert hasattr(WakeWordEngine, name) or name in WakeWordEngine.__annotations__
        assert hasattr(engine, name)
    assert isinstance(engine.frame_length, int) and engine.frame_length > 0
    assert isinstance(engine.sample_rate, int) and engine.sample_rate > 0
    assert engine.process(SILENCE) < 0


def test_importing_the_module_never_imports_the_heavy_dependencies():
    tree = ast.parse(Path(oww.__file__).read_text(encoding="utf-8"))
    heavy = {"openwakeword", "onnxruntime", "numpy", "scipy", "sklearn", "tflite_runtime"}
    top_level = {
        alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert top_level.isdisjoint(heavy), top_level & heavy


# --------------------------------------------------------------------------
# Fabrique : import paresseux, modèles du catalogue, erreurs dites
# --------------------------------------------------------------------------


def test_building_the_factory_validates_its_arguments_but_loads_nothing(monkeypatch):
    monkeypatch.setitem(sys.modules, "openwakeword", None)
    factory = openwakeword_engine_factory(keyword="hey_jarvis", sensitivity=0.5, cooldown_ms=2000)
    assert callable(factory)
    for kwargs in (
        {"sensitivity": 2.0},
        {"cooldown_ms": -1},
        {"cooldown_ms": float("nan")},
        {"keyword": "melspectrogram"},
        {"keyword": "alexa"},
    ):
        base = {"keyword": "hey_jarvis", "sensitivity": 0.5, "cooldown_ms": 2000, **kwargs}
        with pytest.raises(WakeEngineError) as caught:
            openwakeword_engine_factory(**base)
        assert caught.value.code == "wake_config_invalid"


def test_the_cooldown_is_converted_from_milliseconds_to_frames():
    assert oww.cooldown_frames_from_ms(0) == 0
    assert oww.cooldown_frames_from_ms(80) == 1
    assert oww.cooldown_frames_from_ms(81) == 2
    assert oww.cooldown_frames_from_ms(2000) == 25


def test_without_the_extra_the_factory_says_wake_engine_unavailable(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "openwakeword", None)
    build = openwakeword_engine_factory(
        keyword="hey_jarvis", sensitivity=0.5, cooldown_ms=2000, model_dir=tmp_path
    )
    with pytest.raises(WakeEngineError) as caught:
        build()
    assert caught.value.code == "wake_engine_unavailable"
    assert caught.value.cause_code == "wake_package_missing"


def _install_fake_package(monkeypatch, *, predict=None, created=None):
    """Pose un faux `openwakeword` : aucun onnxruntime requis."""

    class FakeModel:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            if created is not None:
                created.append(self)

        def predict(self, frame):  # noqa: ANN001
            return predict(frame) if predict else {"hey_jarvis_v0.1": 0.75}

    package = types.ModuleType("openwakeword")
    module = types.ModuleType("openwakeword.model")
    module.Model = FakeModel
    package.model = module
    monkeypatch.setitem(sys.modules, "openwakeword", package)
    monkeypatch.setitem(sys.modules, "openwakeword.model", module)
    return FakeModel


def test_missing_models_are_said_and_nothing_is_downloaded(monkeypatch, tmp_path):
    _install_fake_package(monkeypatch)

    def refuse_network(*args, **kwargs):
        raise AssertionError("aucun téléchargement implicite")

    monkeypatch.setattr(catalog.urllib.request, "urlopen", refuse_network)
    build = openwakeword_engine_factory(
        keyword="hey_jarvis", sensitivity=0.5, cooldown_ms=2000, model_dir=tmp_path
    )
    with pytest.raises(WakeEngineError) as caught:
        build()
    assert caught.value.code == "wake_engine_unavailable"
    assert caught.value.cause_code == "wake_model_missing"
    assert list(tmp_path.iterdir()) == []


def test_a_tampered_model_is_refused_as_unavailable(monkeypatch, tmp_path):
    _install_fake_package(monkeypatch)
    for spec in catalog.MODELS:
        spec.path(tmp_path).write_bytes(b"not the model")
    build = openwakeword_engine_factory(
        keyword="hey_jarvis", sensitivity=0.5, cooldown_ms=2000, model_dir=tmp_path
    )
    with pytest.raises(WakeEngineError) as caught:
        build()
    assert caught.value.code == "wake_engine_unavailable"
    assert caught.value.cause_code == "wake_model_mismatch"


def test_the_factory_builds_an_engine_from_the_catalog_models(monkeypatch, tmp_path):
    created: list[object] = []
    scores = {"value": 0.75}
    _install_fake_package(
        monkeypatch, created=created, predict=lambda frame: {"hey_jarvis_v0.1": scores["value"]}
    )
    paths = {spec.key: spec.path(tmp_path) for spec in catalog.MODELS}
    monkeypatch.setattr(catalog, "verified_paths", lambda model_dir=None: paths)
    monkeypatch.setattr(oww.catalog, "verified_paths", lambda model_dir=None: paths)

    build = openwakeword_engine_factory(
        keyword="hey_jarvis", sensitivity=0.8, cooldown_ms=1600, model_dir=tmp_path
    )
    engine = build()
    (model,) = created
    assert model.kwargs["inference_framework"] == "onnx"
    assert model.kwargs["wakeword_models"] == [str(paths["hey_jarvis"])]
    assert model.kwargs["melspec_model_path"] == str(paths["melspectrogram"])
    assert model.kwargs["embedding_model_path"] == str(paths["embedding"])
    assert engine.threshold == pytest.approx(threshold_from_sensitivity(0.8))
    assert engine.process(FRAME) == 0 and engine.last_score == pytest.approx(0.75)
    scores["value"] = 0.1
    # cooldown de 1600 ms = 20 trames
    assert [engine.process(FRAME) for _ in range(3)] == [-1, -1, -1]
    engine.delete()
    engine.delete()
    with pytest.raises(WakeEngineError):
        engine.process(FRAME)


def test_the_real_scorer_hands_int16_samples_to_the_model_and_picks_the_keyword_score(monkeypatch, tmp_path):
    import numpy as np

    seen: list[object] = []

    def predict(frame):  # noqa: ANN001
        seen.append(frame)
        return {"hey_jarvis_v0.1": 0.25}

    _install_fake_package(monkeypatch, predict=predict)
    paths = {spec.key: spec.path(tmp_path) for spec in catalog.MODELS}
    monkeypatch.setattr(oww.catalog, "verified_paths", lambda model_dir=None: paths)
    engine = openwakeword_engine_factory(
        keyword="hey_jarvis", sensitivity=0.5, cooldown_ms=0, model_dir=tmp_path
    )()
    engine.process(FRAME)
    (frame,) = seen
    assert isinstance(frame, np.ndarray) and frame.dtype == np.int16 and frame.shape == (1280,)
    assert engine.last_score == pytest.approx(0.25)


def test_a_model_that_returns_no_score_for_the_keyword_is_an_inference_failure(monkeypatch, tmp_path):
    _install_fake_package(monkeypatch, predict=lambda frame: {})
    paths = {spec.key: spec.path(tmp_path) for spec in catalog.MODELS}
    monkeypatch.setattr(oww.catalog, "verified_paths", lambda model_dir=None: paths)
    engine = openwakeword_engine_factory(
        keyword="hey_jarvis", sensitivity=0.5, cooldown_ms=0, model_dir=tmp_path
    )()
    with pytest.raises(WakeEngineError) as caught:
        engine.process(FRAME)
    assert caught.value.code == "wake_inference_failed"


# --------------------------------------------------------------------------
# Bout en bout : SharedPcmWakeWordBackend + hub + faux périphérique
# --------------------------------------------------------------------------

HUB_RATE = 24000
BLOCK_FRAMES = 1200  # 50 ms
BLOCK = b"\x11\x22" * BLOCK_FRAMES


class FakeCaptureDevice:
    def __init__(self) -> None:
        self.opens = 0
        self.callback = None

    def factory(self, *, samplerate, channels, dtype, device, blocksize, callback):  # noqa: ANN001
        self.opens += 1
        self.callback = callback
        return self

    def stop(self) -> None: ...

    def close(self) -> None: ...

    def push(self, block: bytes = BLOCK) -> None:
        assert self.callback is not None
        self.callback(block, len(block) // 2, None, None)


async def until(predicate, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition jamais atteinte"
        await asyncio.sleep(0.005)


@pytest.fixture(autouse=True)
def clean_input_registry():
    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


async def test_the_shared_pcm_backend_runs_the_engine_end_to_end_with_one_detection_per_utterance():
    device = FakeCaptureDevice()
    hub = AudioCaptureHub(stream_factory=device.factory, sample_rate=HUB_RATE, block_frames=BLOCK_FRAMES)
    await hub.open()
    # Trame 3 à 6 : une seule énonciation étalée sur quatre trames de 80 ms.
    model = ScriptedModel([0.0, 0.0, 0.9, 0.9, 0.9, 0.9, 0.0, 0.0])
    engine = OpenWakeWordEngine(model=model, threshold=0.5, cooldown_frames=5)
    wake = SharedPcmWakeWordBackend(hub=hub, engine_factory=lambda: engine, keyword="jarvis")
    detections = wake.detections()
    pending = asyncio.create_task(anext(detections))
    await until(lambda: any(sub.name == "wake_word" for sub in hub.subscriptions))
    subscription = next(sub for sub in hub.subscriptions if sub.name == "wake_word")
    assert subscription.sample_rate == 16000 and hub.sample_rate == HUB_RATE

    for _ in range(14):  # 700 ms à 24 kHz = 8 trames de 1280 à 16 kHz
        device.push()
        await asyncio.sleep(0)
    await until(lambda: engine.frames_seen >= 8)

    assert await asyncio.wait_for(pending, timeout=2) == "jarvis"
    assert wake.detections_count == 1, "une énonciation = une détection"
    assert engine.cooldown_ignored == 3
    assert device.opens == 1 and input_ownership.open_input_stream_count() == 1
    await wake.close()
    assert model.closed == 1, "le backend libère le moteur à la fermeture"
    await hub.close()


async def test_an_inference_failure_stops_the_detector_loudly_and_keeps_the_microphone():
    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = AudioCaptureHub(stream_factory=device.factory, sample_rate=HUB_RATE, block_frames=BLOCK_FRAMES)
    await hub.open()
    model = ScriptedModel([0.0], raise_at=2)
    engine = OpenWakeWordEngine(model=model, threshold=0.5)
    wake = SharedPcmWakeWordBackend(hub=hub, engine_factory=lambda: engine, journal=journal)
    await wake.start()
    for _ in range(8):
        device.push()
        await asyncio.sleep(0)
    await until(lambda: wake.engine_failed)

    assert wake.failure_code == "wake_engine_failed"
    assert hub.open_input_streams == 1
    assert model.closed == 1
    assert hub.subscriptions == ()
    await wake.close()
    await hub.close()


async def test_a_missing_extra_is_reported_as_wake_engine_unavailable_without_crashing_voice(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "openwakeword", None)
    journal = RecordingJournal()
    device = FakeCaptureDevice()
    hub = AudioCaptureHub(stream_factory=device.factory, sample_rate=HUB_RATE, block_frames=BLOCK_FRAMES)
    await hub.open()
    factory = openwakeword_engine_factory(
        keyword="hey_jarvis", sensitivity=0.5, cooldown_ms=2000, model_dir=tmp_path
    )
    wake = SharedPcmWakeWordBackend(hub=hub, engine_factory=factory, journal=journal)
    await wake.start()

    assert wake.engine_failed and wake.failure_code == "wake_engine_unavailable"
    assert hub.subscriptions == ()
    assert hub.open_input_streams == 1, "le micro reste ouvert pour les autres lanes"
    await wake.close()
    await hub.close()


# --------------------------------------------------------------------------
# Live (opt-in) : vrai modèle, jamais dans la suite par défaut
# --------------------------------------------------------------------------

LIVE_MODEL_DIR = os.environ.get("JARVIS_LIVE_WAKEWORD_MODEL_DIR")
LIVE_CLIP = os.environ.get("JARVIS_LIVE_WAKEWORD_CLIP")


def _live_ready() -> bool:
    if not LIVE_MODEL_DIR:
        return False
    try:
        import openwakeword  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.live
@pytest.mark.skipif(not _live_ready(), reason="JARVIS_LIVE_WAKEWORD_MODEL_DIR et l'extra wakeword requis")
def test_the_real_model_scores_silence_low_and_releases_cleanly():
    engine = openwakeword_engine_factory(
        keyword="hey_jarvis", sensitivity=0.5, cooldown_ms=2000, model_dir=Path(LIVE_MODEL_DIR)
    )()
    try:
        for _ in range(30):
            assert engine.process(SILENCE) == -1
        assert engine.last_score is not None and engine.last_score < 0.5
    finally:
        engine.delete()
        engine.delete()


@pytest.mark.live
@pytest.mark.skipif(
    not (_live_ready() and LIVE_CLIP), reason="JARVIS_LIVE_WAKEWORD_CLIP (wav mono 16 bits 16 kHz) requis"
)
def test_the_real_model_detects_the_reference_phrase():
    import wave

    with wave.open(LIVE_CLIP, "rb") as handle:
        assert handle.getframerate() == 16000 and handle.getnchannels() == 1 and handle.getsampwidth() == 2
        raw = handle.readframes(handle.getnframes())
    samples = [int.from_bytes(raw[i : i + 2], "little", signed=True) for i in range(0, len(raw) - 1, 2)]
    padded = [0] * 16000 + samples + [0] * 16000
    engine = openwakeword_engine_factory(
        keyword="hey_jarvis", sensitivity=0.5, cooldown_ms=2000, model_dir=Path(LIVE_MODEL_DIR)
    )()
    try:
        hits = sum(
            1
            for start in range(0, len(padded) - 1279, 1280)
            if engine.process(tuple(padded[start : start + 1280])) == 0
        )
    finally:
        engine.delete()
    assert hits == 1

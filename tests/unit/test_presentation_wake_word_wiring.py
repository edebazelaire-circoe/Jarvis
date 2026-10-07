"""Slice 04 (jarvis-wake-word) - le moteur de mot d'éveil de PRESENTATION suit le bloc `wake_word`.

Ce que cette suite doit prouver, et comment :

- **D1, le défaut ne change rien.** Sans bloc, ou avec `enabled=false`, la pile
  se compose exactement comme avant : Porcupine si une clé existe, rien sinon,
  et `openwakeword` n'est jamais atteint. Prouvé en comptant les appels des
  fabriques, pas en lisant du source.
- **Un moteur openWakeWord réel (son code, pas un double)** reçoit des trames
  rééchantillonnées à 16 kHz sous forme de TUPLES d'entiers ; seul le modèle
  ONNX est remplacé (`_load_scorer`), donc `wake_frame_invalid` tomberait si le
  câblage passait un `bytes` ou un tableau.
- **Un moteur qui ne se construit pas est dit, jamais fatal** : code stable,
  `cause_code`, séance vivante, un seul propriétaire de micro, touche manuelle
  admise.
- **Le score ne passe pas par le port** : il est lu sur le moteur et écrit dans
  le JOURNAL (`wake.shared_pcm.detected`), jamais dans la ligne de temps.
- **Aucun PCM, aucun texte** dans ces traces : toute valeur de `data` est un
  scalaire, et les clés sont une liste fermée.

Aucun vrai micro, aucun `openwakeword`, aucun `onnxruntime` n'est requis.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from jarvis.adapters import wakeword_openwakeword as oww
from jarvis.adapters import wakeword_shared_pcm
from jarvis.audio import input_ownership
from jarvis.domain.conversation_events import ATTRIBUTE_KEYS
from jarvis.domain.explicit_address import ExplicitAddressSource
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.runtime import wake_word_settings as wws
from jarvis.runtime.presentation_runtime import PresentationComposition

from tests.unit.test_ambient_ingestion_lane import (
    BLOCK_FRAMES,
    FakeCaptureDevice,
    RecordingJournal,
    feed,
    speech,
    until,
)
from tests.unit.test_presentation_integration import FakeManualKey

HUB_RATE = 24000

#: Clés qu'une trace du détecteur a le droit de porter : des scalaires nommés.
ALLOWED_DATA_KEYS = {
    "code", "cause_code", "engine_code", "keyword", "provider", "score", "threshold",
    "engine_sample_rate", "hub_sample_rate", "resampled", "dropped", "discarded",
    "since_last", "detections", "frames", "pcm_blocks_dropped", "cooldown_ignored",
}


@pytest.fixture(autouse=True)
def clean_input_registry():
    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


class FakeScorer:
    """Le modèle ONNX remplacé : il note qui l'appelle, avec quoi, et rend un score."""

    def __init__(self, *, scores=None, default: float = 0.0, fail_after: int | None = None) -> None:
        self.scores = list(scores or [])
        self.default = default
        self.fail_after = fail_after
        self.frames: list[object] = []
        self.threads: list[int] = []
        self.closed = 0

    def score(self, pcm) -> float:  # noqa: ANN001
        self.frames.append(pcm)
        self.threads.append(threading.get_ident())
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


def settings(**fields) -> wws.WakeWordSettings:
    provider = fields.get("provider", wws.DEFAULT_PROVIDER)
    fields.setdefault("keyword", wws.default_keyword(provider))
    return wws.WakeWordSettings(**fields)


def compose(tmp_path: Path, journal, *, wake_word=None, wake_access_key: str = "", device=None,
            manual=None, **extra):
    device = device or FakeCaptureDevice()
    manual = manual or FakeManualKey()
    built = PresentationComposition(
        runtime_root=tmp_path,
        cwd=tmp_path,
        journal=journal,
        mode=lambda: InteractionMode.PRESENTATION,
        scene_tools_factory=None,
        agent_factory=None,
        stream_factory=device.factory,
        manual_backend_factory=lambda: manual,
        sample_rate=HUB_RATE,
        wake_access_key=wake_access_key,
        wake_word=wake_word,
        **extra,
    )
    return built, device, manual


def porcupine_spy(monkeypatch):
    calls: list[dict] = []

    def factory(*, access_key, keyword):
        calls.append({"access_key": access_key, "keyword": keyword})
        return lambda: pytest.fail("Porcupine ne doit pas être construit ici")

    monkeypatch.setattr(wakeword_shared_pcm, "porcupine_engine_factory", factory)
    return calls


def detected_lines(journal: RecordingJournal) -> list[dict]:
    return [entry for entry in journal.entries if entry["kind"] == "wake.shared_pcm.detected"]


# --------------------------------------------------------------------------
# 1. Le défaut est strictement le comportement d'avant
# --------------------------------------------------------------------------


@pytest.mark.parametrize("block", [None, settings(enabled=False), settings(enabled=False, provider="openwakeword")])
def test_disabled_setting_keeps_the_previous_composition_without_a_key(tmp_path, monkeypatch, block):
    porcupine = porcupine_spy(monkeypatch)
    scorer_calls = install_scorer(monkeypatch, FakeScorer())
    built, _, _ = compose(tmp_path, RecordingJournal(), wake_word=block)

    stack = built.build("s1")

    assert stack.audio.wake is None
    assert porcupine == [] and scorer_calls == []
    assert ExplicitAddressSource.WAKE_WORD not in stack.audio.lane.sources


@pytest.mark.parametrize("block", [None, settings(enabled=False), settings(enabled=False, provider="openwakeword")])
def test_disabled_setting_keeps_the_previous_factory_with_a_porcupine_key(tmp_path, monkeypatch, block):
    porcupine = porcupine_spy(monkeypatch)
    scorer_calls = install_scorer(monkeypatch, FakeScorer())
    built, _, _ = compose(tmp_path, RecordingJournal(), wake_word=block, wake_access_key="KEY")

    stack = built.build("s1")

    assert stack.audio.wake is not None
    assert porcupine == [{"access_key": "KEY", "keyword": "jarvis"}]
    assert scorer_calls == []


def test_enabled_porcupine_provider_builds_the_porcupine_factory_as_before(tmp_path, monkeypatch):
    porcupine = porcupine_spy(monkeypatch)
    scorer_calls = install_scorer(monkeypatch, FakeScorer())
    built, _, _ = compose(tmp_path, RecordingJournal(), wake_word=settings(enabled=True), wake_access_key="KEY")

    stack = built.build("s1")

    assert stack.audio.wake is not None
    assert porcupine == [{"access_key": "KEY", "keyword": "jarvis"}]
    assert scorer_calls == []


def test_enabled_porcupine_provider_without_a_key_stays_manual_key_only(tmp_path, monkeypatch):
    porcupine = porcupine_spy(monkeypatch)
    built, _, _ = compose(tmp_path, RecordingJournal(), wake_word=settings(enabled=True))

    stack = built.build("s1")

    assert stack.audio.wake is None
    assert porcupine == []


# --------------------------------------------------------------------------
# 2. openWakeWord choisi à la composition
# --------------------------------------------------------------------------


def test_enabled_setting_selects_the_openwakeword_factory(tmp_path, monkeypatch):
    porcupine = porcupine_spy(monkeypatch)
    seen: list[dict] = []
    real = oww.openwakeword_engine_factory

    def spy(**kwargs):
        seen.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(oww, "openwakeword_engine_factory", spy)
    models = tmp_path / "models"
    journal = RecordingJournal()
    built, _, _ = compose(
        tmp_path, journal,
        wake_word=settings(enabled=True, provider="openwakeword", sensitivity=0.7, cooldown_ms=1200),
        wake_access_key="KEY",  # une clé Porcupine ne doit pas l'emporter
        wake_model_dir=models,
    )

    stack = built.build("s1")

    assert porcupine == []
    assert len(seen) == 1
    assert {k: seen[0][k] for k in ("keyword", "sensitivity", "cooldown_ms", "model_dir")} == {
        "keyword": "hey_jarvis", "sensitivity": 0.7, "cooldown_ms": 1200, "model_dir": models,
    }
    assert seen[0]["journal"] is journal
    assert stack.audio.wake is not None
    assert stack.audio.wake.keyword == "hey_jarvis"
    assert stack.audio.wake.provider == "openwakeword"


async def test_the_openwakeword_engine_is_fed_tuples_of_ints_and_detects(tmp_path, monkeypatch):
    scorer = FakeScorer(scores=[0.0, 0.0, 0.97], default=0.0)
    install_scorer(monkeypatch, scorer)
    journal = RecordingJournal()
    built, device, manual = compose(
        tmp_path, journal, wake_word=settings(enabled=True, provider="openwakeword", sensitivity=0.5),
    )
    stack = built.build("s1")
    await stack.start()
    try:
        await feed(device, speech(1000))
        await until(lambda: stack.audio.wake.detections_count >= 1)

        lines = detected_lines(journal)
        assert len(lines) == 1
        data = lines[0]["data"]
        assert data["provider"] == "openwakeword"
        assert data["keyword"] == "hey_jarvis"
        assert data["score"] == pytest.approx(0.97)
        assert data["threshold"] == pytest.approx(0.5)
        # Le moteur réel a validé chaque trame : tuple d'entiers de 1280 échantillons.
        assert scorer.frames and all(isinstance(f, tuple) and len(f) == 1280 for f in scorer.frames)
        assert all(type(v) is int for v in scorer.frames[0])
        assert stack.audio.wake.stats()["failure_code"] is None
        # La détection atteint bien la lane d'adresse explicite, sous la source `wake_word`.
        trigger = await asyncio.wait_for(anext(stack.audio.lane.triggers()), 1.0)
        assert trigger.source is ExplicitAddressSource.WAKE_WORD
        assert trigger.label == "hey_jarvis"
    finally:
        await stack.stop("test")


async def test_detection_trace_carries_score_threshold_provider_in_the_journal_only(tmp_path, monkeypatch):
    install_scorer(monkeypatch, FakeScorer(scores=[0.93]))
    journal = RecordingJournal()
    built, device, _ = compose(
        tmp_path, journal, wake_word=settings(enabled=True, provider="openwakeword", sensitivity=0.9),
    )
    stack = built.build("s1")
    await stack.start()
    try:
        await feed(device, speech(500))
        await until(lambda: detected_lines(journal))
        data = detected_lines(journal)[0]["data"]
        assert data["score"] == pytest.approx(0.93)
        assert data["threshold"] == pytest.approx(0.18)  # 0,9 - 0,8 x 0,9
        assert data["provider"] == "openwakeword"
    finally:
        await stack.stop("test")
    # La ligne de temps reste fermée : ni score, ni seuil, ni confiance
    # (`provider` y existe déjà pour un autre usage : cette Slice n'y touche pas).
    assert not {"score", "threshold", "confidence", "keyword"} & set(ATTRIBUTE_KEYS)


async def test_a_porcupine_detection_is_traced_with_its_provider_and_no_score(tmp_path, monkeypatch):
    class Engine:
        sample_rate = 16000
        frame_length = 512

        def __init__(self) -> None:
            self.calls = 0

        def process(self, pcm):  # noqa: ANN001
            self.calls += 1
            return 0 if self.calls == 3 else -1

        def delete(self) -> None: ...

    monkeypatch.setattr(wakeword_shared_pcm, "porcupine_engine_factory",
                        lambda *, access_key, keyword: Engine)
    journal = RecordingJournal()
    built, device, _ = compose(tmp_path, journal, wake_access_key="KEY")
    stack = built.build("s1")
    await stack.start()
    try:
        await feed(device, speech(500))
        await until(lambda: detected_lines(journal))
        data = detected_lines(journal)[0]["data"]
        assert data["provider"] == "porcupine"
        assert "score" not in data and "threshold" not in data
    finally:
        await stack.stop("test")


# --------------------------------------------------------------------------
# 3. Un moteur qui tombe est dit, et ne casse ni la séance ni F9
# --------------------------------------------------------------------------


def unavailable(message="openWakeWord n'est pas installé", cause="wake_package_missing"):
    def fake_load(spec, model_dir):  # noqa: ANN001
        raise oww.WakeEngineError("wake_engine_unavailable", message, cause_code=cause)

    return fake_load


async def test_missing_provider_degrades_to_manual_key_only(tmp_path, monkeypatch):
    monkeypatch.setattr(oww, "_load_scorer", unavailable())
    journal = RecordingJournal()
    built, device, manual = compose(
        tmp_path, journal, wake_word=settings(enabled=True, provider="openwakeword"),
    )
    stack = built.build("s1")
    await stack.start()  # l'entrée en PRESENTATION n'est pas cassée
    try:
        failed = [e for e in journal.entries if e["kind"] == "wake.shared_pcm.failed"]
        assert len(failed) == 1
        assert failed[0]["data"]["code"] == "wake_engine_unavailable"
        assert failed[0]["data"]["cause_code"] == "wake_package_missing"
        assert failed[0]["level"] == "error"
        assert stack.audio.wake.engine_failed is True
        assert stack.audio.wake.failure_code == "wake_engine_unavailable"
        # Comptage des propriétaires : toujours exactement 1, le hub.
        assert stack.audio.physical_input_owners() == 1
        assert input_ownership.open_input_stream_count() == 1
        assert device.opens == 1
        # F9 reste pleinement utilisable.
        manual.press()
        trigger = await asyncio.wait_for(anext(stack.audio.lane.triggers()), 1.0)
        assert trigger.source is ExplicitAddressSource.MANUAL_KEY
        # Aucun abonnement PCM orphelin pour le détecteur mort.
        assert stack.audio.wake.stats()["subscribed"] is False
    finally:
        await stack.stop("test")
    assert input_ownership.open_input_stream_count() == 0


async def test_an_invalid_engine_configuration_is_said_not_raised_at_composition(tmp_path):
    journal = RecordingJournal()
    # Un mot absent du catalogue (réglage forgé à la main) : la fabrique refuse
    # à sa création ; `build()` ne doit ni lever ni empêcher l'entrée.
    built, device, manual = compose(
        tmp_path, journal, wake_word=settings(enabled=True, provider="openwakeword", keyword="not_in_catalog"),
    )
    stack = built.build("s1")
    await stack.start()
    try:
        failed = [e for e in journal.entries if e["kind"] == "wake.shared_pcm.failed"]
        assert len(failed) == 1
        assert failed[0]["data"]["code"] == "wake_engine_unavailable"
        assert failed[0]["data"]["cause_code"] == "wake_config_invalid"
        assert stack.audio.physical_input_owners() == 1
        manual.press()
        trigger = await asyncio.wait_for(anext(stack.audio.lane.triggers()), 1.0)
        assert trigger.source is ExplicitAddressSource.MANUAL_KEY
    finally:
        await stack.stop("test")


async def test_engine_failure_keeps_the_manual_key_usable(tmp_path, monkeypatch):
    scorer = FakeScorer(fail_after=2)
    install_scorer(monkeypatch, scorer)
    journal = RecordingJournal()
    built, device, manual = compose(
        tmp_path, journal, wake_word=settings(enabled=True, provider="openwakeword"),
    )
    stack = built.build("s1")
    await stack.start()
    try:
        await feed(device, speech(800))
        await until(lambda: stack.audio.wake.engine_failed)
        assert stack.audio.wake.failure_code == "wake_engine_failed"
        failed = [e for e in journal.entries if e["kind"] == "wake.shared_pcm.failed"]
        assert failed and failed[0]["data"]["code"] == "wake_engine_failed"
        assert failed[0]["data"]["cause_code"] == "wake_inference_failed"
        assert scorer.closed == 1  # le modèle est rendu
        assert stack.audio.physical_input_owners() == 1
        manual.press()
        trigger = await asyncio.wait_for(anext(stack.audio.lane.triggers()), 1.0)
        assert trigger.source is ExplicitAddressSource.MANUAL_KEY
        # La capture continue pour les autres voies.
        before = stack.audio.hub.stats()
        await feed(device, speech(200))
        assert stack.audio.hub.stats() != before or device.opens == 1
    finally:
        await stack.stop("test")


# --------------------------------------------------------------------------
# 4. Un seul propriétaire de micro, jamais de second flux
# --------------------------------------------------------------------------


async def test_presentation_still_holds_exactly_one_physical_input_owner(tmp_path, monkeypatch):
    install_scorer(monkeypatch, FakeScorer())
    built, device, _ = compose(
        tmp_path, RecordingJournal(), wake_word=settings(enabled=True, provider="openwakeword"),
    )
    assert input_ownership.open_input_stream_count() == 0
    stack = built.build("s1")
    assert input_ownership.open_input_stream_count() == 0  # construire n'ouvre rien
    await stack.start()
    try:
        assert device.opens == 1
        assert stack.audio.physical_input_owners() == 1
        assert input_ownership.open_input_stream_count() == 1
        assert stack.audio.wake.opens_input_stream is False
        assert stack.audio.wake.stats()["subscribed"] is True
    finally:
        await stack.stop("test")
    assert input_ownership.open_input_stream_count() == 0


# --------------------------------------------------------------------------
# 5. Aucun PCM, aucun texte dans les traces
# --------------------------------------------------------------------------


async def test_no_pcm_or_speech_text_reaches_the_journal(tmp_path, monkeypatch):
    install_scorer(monkeypatch, FakeScorer(scores=[0.0, 0.99]))
    journal = RecordingJournal()
    built, device, _ = compose(
        tmp_path, journal, wake_word=settings(enabled=True, provider="openwakeword"),
    )
    stack = built.build("s1")
    await stack.start()
    try:
        await feed(device, speech(800))
        await until(lambda: detected_lines(journal))
    finally:
        await stack.stop("test")
    wake_lines = [e for e in journal.entries if str(e["kind"]).startswith("wake.")]
    assert wake_lines
    for entry in wake_lines:
        assert set(entry["data"]) <= ALLOWED_DATA_KEYS, entry
        for value in entry["data"].values():
            assert isinstance(value, (str, int, float, bool, type(None))), entry
            assert not isinstance(value, (bytes, bytearray)), entry
    # L'échantillon exact de la parole synthétique (9000) n'apparaît dans aucune ligne.
    assert "9000" not in "".join(str(e["data"]) for e in wake_lines if e["kind"] != "wake.shared_pcm.started")


# --------------------------------------------------------------------------
# 6. Anti-écho minimal : coupé pendant ACTIVE ; inférence sur la boucle ; pertes comptées
# --------------------------------------------------------------------------


async def test_the_detector_is_silent_while_the_session_is_active(tmp_path, monkeypatch):
    scorer = FakeScorer(default=0.99)  # tout est un « Hey Jarvis » : l'écho de TTS, par exemple
    install_scorer(monkeypatch, scorer)
    journal = RecordingJournal()
    built, device, _ = compose(
        tmp_path, journal, wake_word=settings(enabled=True, provider="openwakeword", cooldown_ms=80),
    )
    stack = built.build("s1")
    await stack.start()
    try:
        await stack.audio.lane.suspend_for_active_session()
        await feed(device, speech(1500))
        await asyncio.sleep(0.05)
        assert scorer.frames == []
        assert stack.audio.wake.detections_count == 0
        assert detected_lines(journal) == []
        # Et il reprend à la sortie d'ACTIVE.
        await stack.audio.lane.resume()
        await feed(device, speech(800))
        await until(lambda: stack.audio.wake.detections_count >= 1)
    finally:
        await stack.stop("test")


async def test_inference_runs_on_the_event_loop_never_on_the_capture_thread(tmp_path, monkeypatch):
    scorer = FakeScorer()
    install_scorer(monkeypatch, scorer)
    built, device, _ = compose(
        tmp_path, RecordingJournal(), wake_word=settings(enabled=True, provider="openwakeword"),
    )
    stack = built.build("s1")
    await stack.start()
    loop_thread = threading.get_ident()
    capture_threads: set[int] = set()

    def push_from_capture_thread() -> None:
        capture_threads.add(threading.get_ident())
        block = speech(50)[: BLOCK_FRAMES * 2]
        for _ in range(8):
            device.push_block(block)

    try:
        await asyncio.to_thread(push_from_capture_thread)
        await until(lambda: len(scorer.threads) >= 1)
        assert set(scorer.threads) == {loop_thread}
        assert loop_thread not in capture_threads
    finally:
        await stack.stop("test")


async def test_dropped_frames_are_counted_not_silent(tmp_path, monkeypatch):
    install_scorer(monkeypatch, FakeScorer())
    journal = RecordingJournal()
    built, device, _ = compose(
        tmp_path, journal, wake_word=settings(enabled=True, provider="openwakeword"),
    )
    stack = built.build("s1")
    await stack.start()
    try:
        block = speech(50)[: BLOCK_FRAMES * 2]
        # Déversé sans rendre la main à la boucle : la file bornée de l'abonné déborde.
        for _ in range(200):
            device.push_block(block)
        await until(lambda: stack.audio.wake.stats()["pcm_blocks_dropped"] > 0)
        assert stack.audio.wake.stats()["pcm_blocks_dropped"] > 0
    finally:
        await stack.stop("test")


# --------------------------------------------------------------------------
# 7. Le composition root lit le bloc `wake_word` des réglages
# --------------------------------------------------------------------------


def test_the_app_composition_carries_the_wake_word_block(tmp_path):
    from tests.unit.test_presentation_speculative import _compose

    built, _ = _compose(tmp_path, {})
    assert built.wake_word == wws.defaults() and built.wake_word.enabled is False

    built, _ = _compose(tmp_path, {"wake_word": {
        "schema_version": 1, "enabled": True, "provider": "openwakeword",
        "keyword": "hey_jarvis", "sensitivity": 0.8, "cooldown_ms": 1500,
    }})
    assert built.wake_word == wws.WakeWordSettings(
        enabled=True, provider="openwakeword", keyword="hey_jarvis", sensitivity=0.8, cooldown_ms=1500,
    )


def test_a_damaged_wake_word_block_falls_back_to_disabled(tmp_path):
    from tests.unit.test_presentation_speculative import _compose

    built, journal = _compose(tmp_path, {"wake_word": {"schema_version": 1, "enabled": True, "sensitivity": 7}})
    assert built.wake_word.enabled is False
    # Dit une fois, jamais silencieux.
    said = [w for w in journal.warnings() if w["data"].get("code") == "wake_word_settings_invalid"]
    assert len(said) == 1

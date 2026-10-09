"""Slice 06 (jarvis-wake-word) - F9 et mot d'éveil : un seul chemin, la source en métadonnée.

Ce que cette suite prouve, et comment :

- **Un seul chemin.** Depuis BACKGROUND, F9 et une détection de mot d'éveil
  (un double par famille : touche, `SharedPcm`, flux propre) donnent les MÊMES
  transitions d'état visibles, les mêmes appels au détecteur, les mêmes
  événements du journal (hors métadonnées de source). Comparaison de deux
  relevés complets, pas d'assertions séparées qui pourraient diverger.
- **La source n'est jamais une branche.** Elle est du vocabulaire existant
  (`ExplicitAddressSource` : `wake_word` / `manual_key`), posée dans la trace
  `voice.wake` et sur `voice.connecting` ; les étiquettes du détecteur (`f9`,
  `jarvis`) sont mappées en UN endroit.
- **Le journal, pas la timeline.** Fournisseur, score et seuil (finis seulement)
  vont dans `voice.wake` ; `ATTRIBUTE_KEYS` reste fermé.
- **Une seule sortie vers BACKGROUND** pour F9, « Jarvis mute », le délai
  d'inactivité et l'arrêt Live du Control Center (D2).
- **La veille vocale reste minuscule** : la même reconnaissance exacte que
  « Jarvis mute », quelques variantes fermées, jamais au milieu d'une demande.

Aucun micro, aucun réseau : tout est double.
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.adapters.wakeword_composite import CompositeWakeWordBackend
from jarvis.adapters.wakeword_keyboard import KeyboardWakeWordBackend
from jarvis.domain.conversation_events import ATTRIBUTE_KEYS
from jarvis.domain.explicit_address import ExplicitAddressSource
from jarvis.domain.v2 import VoiceLifecycleState
from jarvis.runtime.realtime_audio import SoundDeviceRealtimeAudio
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime, activation_source_for_label
from jarvis.v2_config import VoiceArchitecture
from tests.unit.test_v2_voice_toggle import (
    FakeAudio,
    FakeAutoTurnSession,
    FakeCore,
    RecordingJournal,
    RecordingSignals,
)

#: Métadonnées qui ont le droit de différer entre F9 et le mot d'éveil.
SOURCE_KEYS = {"source", "keyword", "provider", "score", "threshold"}


# --------------------------------------------------------------------------
# Doubles
# --------------------------------------------------------------------------


class FakeDetector:
    """Un détecteur d'une famille : il rend une étiquette et, s'il en a, ses mesures."""

    def __init__(self, label: str, facts: dict[str, object] | None = None) -> None:
        self.label = label
        self.facts = facts
        self.queue: asyncio.Queue[tuple[str, dict[str, object] | None]] = asyncio.Queue()
        self.last_detection: dict[str, object] | None = None
        self.calls: list[str] = []
        self.resumed = asyncio.Event()
        self.closed = False

    def emit(self) -> None:
        # Comme les vrais detecteurs : la mesure voyage avec le mot et n'est publiee
        # qu'au moment ou `detections()` le rend.
        self.queue.put_nowait((self.label, dict(self.facts) if self.facts is not None else None))

    async def detections(self):
        while not self.closed:
            label, facts = await self.queue.get()
            self.last_detection = facts
            yield label

    async def suspend(self) -> None:
        self.calls.append("suspend")

    async def suspend_for_active_session(self) -> None:
        self.calls.append("suspend_for_active_session")

    async def resume(self) -> None:
        self.calls.append("resume")
        self.resumed.set()

    async def close(self) -> None:
        self.closed = True


class QuietSession(FakeAutoTurnSession):
    """Une séance qui reste ouverte : aucun événement ne la ramène au fond."""

    async def events(self):
        await asyncio.Event().wait()
        yield  # pragma: no cover


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 10, 7, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current


@pytest.fixture
def audio(monkeypatch):
    import jarvis.runtime.realtime_audio as realtime_audio

    FakeAudio.instances.clear()
    FakeAudio.order = []
    monkeypatch.setattr(FakeAudio, "pcm", b"")
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)
    return FakeAudio


async def _no_start(self) -> None:  # noqa: ANN001
    return None


def keyboard_backend(monkeypatch, key: str = "f9") -> KeyboardWakeWordBackend:
    monkeypatch.setattr(KeyboardWakeWordBackend, "start", _no_start)
    return KeyboardWakeWordBackend(key_name=key)


class Rig:
    """Un runtime réel, le clavier réel, un détecteur factice, composés comme `app.py`."""

    def __init__(self, monkeypatch, detector: FakeDetector, **runtime_kwargs) -> None:  # noqa: ANN003
        self.keyboard = keyboard_backend(monkeypatch)
        self.detector = detector
        self.wake = CompositeWakeWordBackend([self.keyboard, detector])
        self.journal = RecordingJournal()
        self.signals = RecordingSignals()
        self.factory_calls = 0
        self.session = QuietSession()

        async def factory(context):  # noqa: ANN001
            del context
            self.factory_calls += 1
            return self.session

        self.runtime = PersistentVoiceRuntime(
            wakeword=self.wake, core=FakeCore(), realtime_factory=factory,  # type: ignore[arg-type]
            journal=self.journal, signals=self.signals, auto_turn=True,  # type: ignore[arg-type]
            voice_arch=VoiceArchitecture.LEGACY, **runtime_kwargs,
        )
        self.task = asyncio.create_task(self.runtime.run())

    @property
    def state(self) -> VoiceLifecycleState:
        return self.runtime.runtime.state

    def kinds(self) -> list[str]:
        return [str(event["kind"]) for event in self.journal.events]

    def events(self, kind: str) -> list[dict[str, object]]:
        return [event for event in self.journal.events if event["kind"] == kind]

    async def press_f9(self) -> None:
        self.keyboard._detected()

    async def say_jarvis(self) -> None:
        self.detector.emit()

    async def until_active(self) -> None:
        await _until(lambda: self.state is VoiceLifecycleState.ACTIVE and FakeAudio.instances)
        await asyncio.wait_for(FakeAudio.instances[0].started.wait(), timeout=1)

    async def until_background(self, resumed_before: int) -> None:
        await _until(lambda: self.state is VoiceLifecycleState.BACKGROUND
                     and self.detector.calls.count("resume") > resumed_before)

    async def close(self) -> None:
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        await self.wake.close()


async def _until(predicate, timeout: float = 2.0) -> None:  # noqa: ANN001
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


def strip_source(events: list[dict[str, object]]) -> list[tuple]:
    """Le journal sans ce qui a le droit de différer : source, mot, fournisseur, mesures."""

    return [(event["kind"], event["message"], event["level"],
             {key: value for key, value in dict(event["data"]).items() if key not in SOURCE_KEYS})  # type: ignore[arg-type]
            for event in events]


FAMILIES = [
    pytest.param("shared_pcm", {"provider": "openwakeword", "score": 0.81, "threshold": 0.5}, id="shared_pcm"),
    pytest.param("own_stream", {"provider": "openwakeword", "score": 0.77, "threshold": 0.5}, id="own_stream"),
    pytest.param("porcupine", None, id="no_measure"),
]


async def run_scenario(monkeypatch, trigger: str, facts) -> dict:  # noqa: ANN001
    """BACKGROUND -> ACTIVE -> mute, déclenché par `f9` ou par le mot d'éveil."""

    rig = Rig(monkeypatch, FakeDetector("jarvis", facts))
    try:
        assert rig.state is VoiceLifecycleState.BACKGROUND
        await (rig.press_f9() if trigger == "f9" else rig.say_jarvis())
        await rig.until_active()
        active_calls = list(rig.detector.calls)
        resumes = rig.detector.calls.count("resume")
        await rig.runtime.mute()
        await rig.until_background(resumes)
        return {
            "states": list(rig.signals.states),
            "alerts": list(rig.signals.alerts),
            "journal": strip_source(rig.journal.events),
            "detector_calls_when_active": active_calls,
            "detector_calls": list(rig.detector.calls),
            "factory_calls": rig.factory_calls,
            "audio_instances": len(FakeAudio.instances),
            "final": rig.state,
            "raw": rig.journal.events,
        }
    finally:
        await rig.close()


# --------------------------------------------------------------------------
# 1. Un seul chemin
# --------------------------------------------------------------------------


@pytest.mark.parametrize("label, facts", FAMILIES)
async def test_f9_and_the_wake_word_reach_active_through_the_same_path(monkeypatch, audio, label, facts) -> None:
    reference = await run_scenario(monkeypatch, "f9", facts)
    audio.instances.clear()
    candidate = await run_scenario(monkeypatch, "wake", facts)

    assert reference["final"] is candidate["final"] is VoiceLifecycleState.BACKGROUND
    for key in ("states", "alerts", "journal", "detector_calls_when_active", "detector_calls",
                "factory_calls", "audio_instances"):
        assert candidate[key] == reference[key], key
    # activate() une fois, la détection suspendue une fois, reprise une fois.
    assert candidate["factory_calls"] == 1
    assert candidate["detector_calls"].count("suspend_for_active_session") == 1
    assert candidate["detector_calls"].count("resume") == 1
    kinds = [entry[0] for entry in candidate["journal"]]
    assert kinds.count("voice.connecting") == kinds.count("voice.active") == kinds.count("voice.background") == 1


@pytest.mark.parametrize("label, facts", FAMILIES)
async def test_the_source_label_is_traced_and_does_not_change_behaviour(monkeypatch, audio, label, facts) -> None:
    f9 = await run_scenario(monkeypatch, "f9", facts)
    audio.instances.clear()
    wake = await run_scenario(monkeypatch, "wake", facts)

    def wake_event(run: dict) -> dict:
        return next(event for event in run["raw"] if event["kind"] == "voice.wake")["data"]

    assert wake_event(f9)["source"] == ExplicitAddressSource.MANUAL_KEY.value == "manual_key"
    assert wake_event(wake)["source"] == ExplicitAddressSource.WAKE_WORD.value == "wake_word"
    assert wake_event(f9)["keyword"] == "f9" and wake_event(wake)["keyword"] == "jarvis"
    # Jamais un second vocabulaire.
    assert "keyboard_f9" not in json.dumps(f9["raw"]) + json.dumps(wake["raw"])
    # La source suit l'activation jusque dans `voice.connecting`.
    connecting = lambda run: next(e for e in run["raw"] if e["kind"] == "voice.connecting")["data"]  # noqa: E731
    assert connecting(f9)["source"] == "manual_key"
    assert connecting(wake)["source"] == "wake_word"


@pytest.mark.parametrize("label, facts", FAMILIES)
async def test_the_detector_measures_reach_the_journal_only_when_the_detector_has_them(
    monkeypatch, audio, label, facts,
) -> None:
    run = await run_scenario(monkeypatch, "wake", facts)
    data = next(event for event in run["raw"] if event["kind"] == "voice.wake")["data"]
    if facts is None:
        assert not {"provider", "score", "threshold"} & set(data)
    else:
        assert (data["provider"], data["score"], data["threshold"]) == ("openwakeword", 0.81 if label == "shared_pcm" else 0.77, 0.5)


async def test_f9_never_inherits_the_measures_of_an_earlier_wake_word(monkeypatch, audio) -> None:
    rig = Rig(monkeypatch, FakeDetector("jarvis", {"provider": "openwakeword", "score": 0.9, "threshold": 0.5}))
    try:
        await rig.say_jarvis()
        await rig.until_active()
        resumes = rig.detector.calls.count("resume")
        await rig.runtime.mute()
        await rig.until_background(resumes)
        await rig.press_f9()
        await _until(lambda: len(rig.events("voice.wake")) == 2)
        assert not {"provider", "score", "threshold"} & set(rig.events("voice.wake")[1]["data"])
        assert rig.events("voice.wake")[1]["data"]["source"] == "manual_key"
    finally:
        await rig.close()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, "0.5", None])
async def test_a_non_finite_or_foreign_measure_is_left_out_and_the_journal_stays_valid_json(
    monkeypatch, audio, bad,
) -> None:
    rig = Rig(monkeypatch, FakeDetector("jarvis", {"provider": "openwakeword", "score": bad, "threshold": bad}))
    try:
        await rig.say_jarvis()
        await rig.until_active()
        data = rig.events("voice.wake")[0]["data"]
        assert "score" not in data and "threshold" not in data
        assert data["provider"] == "openwakeword"
        json.loads(json.dumps(rig.journal.events, allow_nan=False))
    finally:
        await rig.close()


async def test_state_before_and_after_are_traced(monkeypatch, audio) -> None:
    rig = Rig(monkeypatch, FakeDetector("jarvis"))
    try:
        await rig.say_jarvis()
        await rig.until_active()
        await _until(lambda: rig.events("voice.wake.outcome"))
        wake, outcome = rig.events("voice.wake")[0]["data"], rig.events("voice.wake.outcome")[0]["data"]
        assert wake["state_before"] == VoiceLifecycleState.BACKGROUND.value
        assert outcome["state_before"] == VoiceLifecycleState.BACKGROUND.value
        assert outcome["state_after"] == VoiceLifecycleState.ACTIVE.value
        assert outcome["source"] == "wake_word"
        assert rig.kinds().index("voice.wake") < rig.kinds().index("voice.connecting") \
            < rig.kinds().index("voice.active") < rig.kinds().index("voice.wake.outcome")
    finally:
        await rig.close()


async def test_a_refused_activation_traces_the_state_it_ended_in(monkeypatch, audio) -> None:
    rig = Rig(monkeypatch, FakeDetector("jarvis"))

    async def failing(context):  # noqa: ANN001
        raise RuntimeError("provider down")

    rig.runtime.realtime_factory = failing  # type: ignore[assignment]
    try:
        await rig.say_jarvis()
        await _until(lambda: rig.events("voice.wake.outcome"))
        outcome = rig.events("voice.wake.outcome")[0]["data"]
        assert outcome["state_before"] == "background"
        assert outcome["state_after"] == rig.state.value != "active"
    finally:
        await rig.close()


# --------------------------------------------------------------------------
# 2. Une détection pendant ACTIVE n'active pas deux fois
# --------------------------------------------------------------------------


@pytest.mark.parametrize("trigger", ["f9", "wake"])
async def test_a_detection_while_active_does_not_activate_twice(monkeypatch, audio, trigger) -> None:
    rig = Rig(monkeypatch, FakeDetector("jarvis"))
    try:
        await (rig.press_f9() if trigger == "f9" else rig.say_jarvis())
        await rig.until_active()
        assert rig.factory_calls == 1
        # Rafale pendant la séance : jamais une seconde ouverture.
        resumes = rig.detector.calls.count("resume")
        for _ in range(3):
            rig.detector.emit()
        await rig.until_background(resumes)
        assert rig.factory_calls == 1
        assert rig.kinds().count("voice.connecting") == 1
        assert len(FakeAudio.instances) == 1
    finally:
        await rig.close()


async def test_a_burst_of_direct_activations_opens_one_session(monkeypatch, audio) -> None:
    rig = Rig(monkeypatch, FakeDetector("jarvis"))
    try:
        await rig.say_jarvis()
        await rig.until_active()
        await asyncio.gather(*(rig.runtime.activate(ExplicitAddressSource.WAKE_WORD) for _ in range(4)))
        assert rig.factory_calls == 1 and rig.kinds().count("voice.connecting") == 1
    finally:
        await rig.close()


async def test_a_burst_before_the_first_activation_finishes_opens_one_session(monkeypatch, audio) -> None:
    rig = Rig(monkeypatch, FakeDetector("jarvis"))
    try:
        for _ in range(4):
            rig.detector.emit()
        await rig.until_active()
        await asyncio.sleep(0.05)
        assert rig.factory_calls == 1
    finally:
        await rig.close()


# --------------------------------------------------------------------------
# 3. Appelants sans source
# --------------------------------------------------------------------------


async def test_rebind_board_still_activates_without_a_source(monkeypatch, audio) -> None:
    rig = Rig(monkeypatch, FakeDetector("jarvis"))
    try:
        await rig.say_jarvis()
        await rig.until_active()
        rig.runtime._rebind_target = "conversation-1"
        assert await rig.runtime.rebind_board() is True
        assert rig.state is VoiceLifecycleState.ACTIVE
        connecting = rig.events("voice.connecting")
        assert len(connecting) == 2
        assert connecting[0]["data"]["source"] == "wake_word"
        assert "source" not in connecting[1]["data"]  # réouverture interne : aucun geste, aucune source
    finally:
        await rig.close()


async def test_activate_without_a_source_stays_valid(monkeypatch, audio) -> None:
    rig = Rig(monkeypatch, FakeDetector("jarvis"))
    try:
        await rig.runtime.activate()
        assert rig.state is VoiceLifecycleState.ACTIVE
        assert "source" not in rig.events("voice.connecting")[0]["data"]
    finally:
        await rig.close()


# --------------------------------------------------------------------------
# 4. Le mappage des étiquettes : un seul endroit, le vocabulaire existant
# --------------------------------------------------------------------------


@pytest.mark.parametrize("label, key, expected", [
    ("f9", "f9", ExplicitAddressSource.MANUAL_KEY),
    ("F9", "f9", ExplicitAddressSource.MANUAL_KEY),
    ("  f9 ", "f9", ExplicitAddressSource.MANUAL_KEY),
    ("f10", "f10", ExplicitAddressSource.MANUAL_KEY),
    ("jarvis", "f9", ExplicitAddressSource.WAKE_WORD),
    ("hey_jarvis", "f9", ExplicitAddressSource.WAKE_WORD),
    ("f10", "f9", ExplicitAddressSource.WAKE_WORD),
    ("", "f9", None),
    (None, "f9", None),
    (42, "f9", None),
])
def test_labels_map_to_the_existing_vocabulary(label, key, expected) -> None:
    assert activation_source_for_label(label, manual_key=key) is expected


async def test_a_non_default_manual_key_is_reported_as_manual_key(monkeypatch, audio) -> None:
    rig = Rig(monkeypatch, FakeDetector("jarvis"), manual_wake_key="f10")
    rig.keyboard.key_name = "f10"
    try:
        rig.keyboard._detected()
        await rig.until_active()
        assert rig.events("voice.wake")[0]["data"]["source"] == "manual_key"
    finally:
        await rig.close()


def test_app_hands_the_configured_manual_key_to_the_runtime() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "jarvis" / "app.py").read_text(encoding="utf-8")
    assert "manual_wake_key=manual_key" in source


def test_the_timeline_attribute_keys_stay_closed() -> None:
    for forbidden in ("score", "threshold", "state_before", "state_after", "keyword"):
        assert forbidden not in ATTRIBUTE_KEYS


# --------------------------------------------------------------------------
# 5. Les mesures traversent Composite et l'aiguillage sans changer l'étiquette
# --------------------------------------------------------------------------


async def test_the_composite_exposes_the_measures_of_the_detection_it_just_yielded() -> None:
    measured = FakeDetector("jarvis", {"provider": "openwakeword", "score": 0.6, "threshold": 0.5})
    silent = FakeDetector("f9")
    composite = CompositeWakeWordBackend([silent, measured])
    detections = composite.detections()
    try:
        measured.emit()
        assert await asyncio.wait_for(anext(detections), 1) == "jarvis"
        assert composite.last_detection == {"provider": "openwakeword", "score": 0.6, "threshold": 0.5}
        silent.emit()
        assert await asyncio.wait_for(anext(detections), 1) == "f9"
        assert composite.last_detection is None
    finally:
        await detections.aclose()
        await composite.close()


async def test_the_presentation_router_renders_the_same_label_and_forwards_the_simple_measures() -> None:
    from jarvis.runtime.presentation_runtime import PresentationWakeRouter

    simple = FakeDetector("jarvis", {"provider": "openwakeword", "score": 0.6, "threshold": 0.5})
    router = PresentationWakeRouter(simple=simple)
    detections = router.detections()
    try:
        simple.emit()
        assert await asyncio.wait_for(anext(detections), 1) == "jarvis"
        assert router.simple_detections == 1 and router.armed == 0
        assert router.last_detection == {"provider": "openwakeword", "score": 0.6, "threshold": 0.5}
    finally:
        await detections.aclose()
        await router.close()


async def test_the_shared_pcm_backend_publishes_its_measures_with_finite_values_only() -> None:
    from jarvis.adapters.wakeword_shared_pcm import SharedPcmWakeWordBackend

    class Engine:
        provider = "openwakeword"
        last_score = 0.62
        threshold = 0.5

    backend = SharedPcmWakeWordBackend(hub=object(), engine_factory=lambda: Engine())  # type: ignore[arg-type]
    backend._engine = Engine()  # type: ignore[assignment]
    backend.start = _no_start.__get__(backend)  # type: ignore[method-assign]
    backend._detected()
    detections = backend.detections()
    try:
        await asyncio.wait_for(anext(detections), 1)
        assert backend.last_detection == {"provider": "openwakeword", "score": 0.62, "threshold": 0.5}
        assert all(not isinstance(value, float) or math.isfinite(value) for value in backend.last_detection.values())

        class Mute:
            provider = "porcupine"

        backend._engine = Mute()  # type: ignore[assignment]
        backend._detected()
        await asyncio.wait_for(anext(detections), 1)
        assert backend.last_detection == {"provider": "porcupine"}
    finally:
        await detections.aclose()


# --------------------------------------------------------------------------
# 6. Le retour au repos : quatre chemins, une sortie
# --------------------------------------------------------------------------


async def _rest_via_f9(rig: Rig) -> None:
    await rig.press_f9()


async def _rest_via_jarvis_mute(rig: Rig) -> None:
    # « Jarvis mute » : le pont appelle `on_mute`, branché sur `mute()` du runtime.
    assert rig.runtime._bridge.on_mute == rig.runtime.mute
    await rig.runtime._bridge.on_mute()


async def _rest_via_idle_timeout(rig: Rig) -> None:
    rig.clock.current += timedelta(seconds=rig.runtime.activity.timeout_s + 1)
    assert await rig.runtime.check_timeout() is True


async def _rest_via_live_stop(rig: Rig) -> None:
    from jarvis.app import _handle_live_ui_supervision

    runtime = rig.runtime

    class VoiceView:
        def live_runtime_report(self) -> dict:
            return {"session_id": "live-1"}

        async def mute(self, reason=None) -> None:  # noqa: ANN001
            await runtime.mute(reason)

    class Signals:
        accepted: list = []

        def live_runtime(self, report) -> None:  # noqa: ANN001
            del report

        def read_live_stop_request(self) -> dict:
            return {"request_id": "r1", "session_id": "live-1"}

        def complete_live_stop(self, request, status, message=None) -> None:  # noqa: ANN001
            del request, message
            self.accepted.append(status)

    assert await _handle_live_ui_supervision(VoiceView(), Signals(), None, None) == "r1"
    assert Signals.accepted == ["accepted"]


REST_PATHS = [_rest_via_f9, _rest_via_jarvis_mute, _rest_via_idle_timeout, _rest_via_live_stop]


@pytest.mark.parametrize("rest_path", REST_PATHS, ids=lambda fn: fn.__name__.removeprefix("_rest_via_"))
async def test_mute_returns_to_background_and_rearms_the_detector(monkeypatch, audio, rest_path) -> None:
    clock = FakeClock()
    rig = Rig(monkeypatch, FakeDetector("jarvis"), clock=clock, active_timeout_s=30.0)
    rig.clock = clock
    try:
        await rig.say_jarvis()
        await rig.until_active()
        resumes = rig.detector.calls.count("resume")
        await rest_path(rig)
        await rig.until_background(resumes)
        # Même sortie : fond, détection reprise une fois, une session fermée, un seul `voice.background`.
        assert rig.state is VoiceLifecycleState.BACKGROUND
        assert rig.detector.calls.count("resume") == resumes + 1
        assert rig.session.closed is True
        assert rig.kinds().count("voice.background") == 1
        assert rig.signals.states[-1] == "idle"
        # Et le mot d'éveil repart : une nouvelle détection rouvre une séance.
        rig.session = QuietSession()
        await rig.say_jarvis()
        await _until(lambda: rig.kinds().count("voice.connecting") == 2)
    finally:
        await rig.close()


async def test_every_rest_path_leaves_the_same_journal_tail(monkeypatch, audio) -> None:
    tails = []
    for rest_path in REST_PATHS:
        audio.instances.clear()
        clock = FakeClock()
        rig = Rig(monkeypatch, FakeDetector("jarvis"), clock=clock, active_timeout_s=30.0)
        rig.clock = clock
        try:
            await rig.say_jarvis()
            await rig.until_active()
            resumes = rig.detector.calls.count("resume")
            await rest_path(rig)
            await rig.until_background(resumes)
            tails.append(strip_source(rig.journal.events)[-1])
        finally:
            await rig.close()
    assert len({repr(tail) for tail in tails}) == 1, tails
    assert tails[0][0] == "voice.background"


# --------------------------------------------------------------------------
# 7. Veille vocale minimale (D2) : même reconnaissance exacte que « Jarvis mute »
# --------------------------------------------------------------------------


from tests.unit.test_presentation_turn_authority import make_bridge, say  # noqa: E402


@pytest.mark.parametrize("phrase", [
    "Jarvis mute",
    "Jarvis, mute",
    "jarvis mute.",
    "Jarvis, stop listening",
    "Jarvis stop listening.",
    "JARVIS, STOP LISTENING!",
    "Jarvis, arrête d'écouter",
    "Jarvis arrête d’écouter.",
    "Jarvis, arrete d'ecouter",
])
async def test_the_closed_sleep_phrases_cut_the_session_like_jarvis_mute(phrase) -> None:
    bridge, core, calls = make_bridge(turns=None, engaged=True)
    assert await say(bridge, phrase) is True
    assert calls.mute == 1
    assert core.brain_turns == []


@pytest.mark.parametrize("phrase", [
    "stop listening",
    "arrête d'écouter",
    "mute",
    "Jarvis, ne mute pas",
    "Jarvis, tu peux mute le son de la vidéo",
    "Jarvis stop listening to the music and play the report",
    "Jarvis, explique-moi pourquoi stop listening est une mauvaise phrase",
    "dis à Marc d'arrêter d'écouter Jarvis",
    "Jarvis, arrête d'écouter la radio et lis mes mails",
    "Jarvis stop",
    "Jarvis go to sleep",
    "Jarvis, va dormir",
    "Jarvis, goodnight",
    "Jarvis, mets-toi en veille",
    "Jarvis please stop listening",
    "Jarvis stop listening now",
])
async def test_no_free_form_sleep_phrase_is_recognised(phrase) -> None:
    bridge, _core, calls = make_bridge(turns=None, engaged=True)
    await say(bridge, phrase)
    assert calls.mute == 0


# --------------------------------------------------------------------------
# 8. Rework QA P1 : la mesure est APPARIEE a sa detection
# --------------------------------------------------------------------------


class ScoredEngine:
    """Un moteur dont le dernier score change entre deux detections (comme openWakeWord)."""

    provider = "openwakeword"
    threshold = 0.5

    def __init__(self) -> None:
        self.last_score = 0.0


def shared_pcm_backend():
    from jarvis.adapters.wakeword_shared_pcm import SharedPcmWakeWordBackend

    engine = ScoredEngine()
    backend = SharedPcmWakeWordBackend(hub=object(), engine_factory=lambda: engine)  # type: ignore[arg-type]
    backend._engine = engine  # type: ignore[assignment]
    backend.start = _no_start.__get__(backend)  # type: ignore[method-assign]  # pas de hub reel
    return backend, engine


def detect(backend, engine: ScoredEngine, score: float) -> None:
    engine.last_score = score
    backend._detected()


async def drain(composite: CompositeWakeWordBackend, count: int) -> list[tuple[str, object]]:
    detections = composite.detections()
    seen: list[tuple[str, object]] = []
    try:
        for _ in range(count):
            label = await asyncio.wait_for(anext(detections), 1)
            seen.append((label, composite.last_detection))
    finally:
        await detections.aclose()
    return seen


async def test_two_close_wake_words_each_keep_their_own_score() -> None:
    backend, engine = shared_pcm_backend()
    composite = CompositeWakeWordBackend([backend])
    try:
        detect(backend, engine, 0.6)
        detect(backend, engine, 0.99)  # avant que la pompe ne soit passee
        seen = await drain(composite, 2)
    finally:
        await composite.close()
    assert [facts["score"] for _, facts in seen] == [0.6, 0.99]  # type: ignore[index]


async def test_f9_between_two_wake_words_carries_no_measure_and_does_not_shift_the_others(monkeypatch) -> None:
    backend, engine = shared_pcm_backend()
    keyboard = keyboard_backend(monkeypatch)  # vrai backend F9, sans ecouteur pynput reel
    composite = CompositeWakeWordBackend([keyboard, backend])
    detections = composite.detections()
    seen: list[tuple[str, object]] = []
    try:
        for trigger in (lambda: detect(backend, engine, 0.6), keyboard._detected,
                        lambda: detect(backend, engine, 0.9), keyboard._detected):
            trigger()
            seen.append((await asyncio.wait_for(anext(detections), 1), composite.last_detection))
    finally:
        await detections.aclose()
        await composite.close()
    assert [label for label, _ in seen] == [backend.keyword, "f9", backend.keyword, "f9"]
    assert [None if facts is None else facts["score"] for _, facts in seen] == [0.6, None, 0.9, None]  # type: ignore[index]


async def test_a_detection_lost_to_a_full_queue_does_not_shift_the_pairing() -> None:
    from jarvis.adapters.wakeword_shared_pcm import DETECTION_QUEUE_SIZE

    backend, engine = shared_pcm_backend()
    scores = [round(0.5 + 0.05 * index, 2) for index in range(DETECTION_QUEUE_SIZE + 2)]
    for score in scores:
        detect(backend, engine, score)
    assert backend.dropped == 2
    seen = []
    detections = backend.detections()
    try:
        for _ in range(DETECTION_QUEUE_SIZE):
            await asyncio.wait_for(anext(detections), 1)
            seen.append(backend.last_detection["score"])  # type: ignore[index]
    finally:
        await detections.aclose()
    assert seen == scores[:DETECTION_QUEUE_SIZE]


# --------------------------------------------------------------------------
# 9. Rework QA S5 : le VRAI detecteur a flux propre publie sa mesure
# --------------------------------------------------------------------------


async def test_the_real_own_stream_detector_publishes_the_measure_of_the_word_it_hands_over(monkeypatch) -> None:
    from tests.unit import test_simple_wake_word_wiring as wiring

    fake_sd = wiring.FakeSoundDevice()
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", fake_sd)
    journal = wiring.RecordingJournal()
    backend, _ = wiring.oww_backend(
        monkeypatch, wiring.FakeScorer(scores=[0.0, 0.97, 0.0, 0.0, 0.83]), journal=journal,
    )
    composite = CompositeWakeWordBackend([backend])
    detections = composite.detections()
    try:
        pending = asyncio.create_task(anext(detections))
        await wiring.until(lambda: len(fake_sd.streams) == 1)
        frame = wiring.pcm_block(wiring.FRAME)
        wiring.from_portaudio_thread(fake_sd.streams[0], frame, frame, frame, frame, frame)
        assert await asyncio.wait_for(pending, 3) == "hey_jarvis"
        assert composite.last_detection == {"provider": "openwakeword", "score": 0.97, "threshold": 0.5}
        assert backend.last_detection == composite.last_detection and "keyword" not in backend.last_detection  # type: ignore[operator]
        traced = [entry["data"] for entry in journal.entries if entry["kind"] == "wake.own_stream.detected"]
        assert traced[0]["score"] == composite.last_detection["score"]
    finally:
        await detections.aclose()
        await composite.close()


async def test_voice_wake_and_own_stream_detected_carry_the_same_score(monkeypatch, audio) -> None:
    from tests.unit import test_simple_wake_word_wiring as wiring

    fake_sd = wiring.FakeSoundDevice()
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", fake_sd)
    backend, _ = wiring.oww_backend(monkeypatch, wiring.FakeScorer(scores=[0.0, 0.97]))
    rig = Rig(monkeypatch, backend)  # type: ignore[arg-type]
    backend.journal = rig.journal
    try:
        await wiring.until(lambda: len(fake_sd.streams) == 1)
        frame = wiring.pcm_block(wiring.FRAME)
        wiring.from_portaudio_thread(fake_sd.streams[0], frame, frame)
        await _until(lambda: rig.events("voice.wake"))
        wake = rig.events("voice.wake")[0]["data"]
        traced = rig.events("wake.own_stream.detected")[0]["data"]
        assert (wake["provider"], wake["score"], wake["threshold"]) == ("openwakeword", 0.97, 0.5)
        assert wake["score"] == traced["score"] and wake["threshold"] == traced["threshold"]
    finally:
        await rig.close()


# --------------------------------------------------------------------------
# 10. Rework QA P2 : `source` garde le vocabulaire normalise, l'etiquette brute est `keyword`
# --------------------------------------------------------------------------


async def test_manual_submit_traces_the_normalised_source_and_the_raw_keyword(monkeypatch, audio) -> None:
    from tests.unit.test_v2_voice_toggle import FakeRealtimeSession, FakeWakeWord

    session = FakeRealtimeSession([])
    journal = RecordingJournal()

    async def factory(context):  # noqa: ANN001
        return session

    runtime = PersistentVoiceRuntime(
        wakeword=FakeWakeWord(), core=FakeCore(), realtime_factory=factory,  # type: ignore[arg-type]
        journal=journal, voice_arch=VoiceArchitecture.LEGACY,  # type: ignore[arg-type]
    )
    await runtime.activate()
    await runtime.submit_active_turn(source="f9")
    submit = next(e for e in journal.events if e["kind"] == "voice.manual_submit")["data"]
    assert submit == {"source": "manual_key", "keyword": "f9"}


async def test_submit_active_turn_behaviour_does_not_depend_on_the_label() -> None:
    """`source` n'est consomme que par la trace : deux etiquettes, meme issue."""

    outcomes = []
    for label in ("f9", "jarvis"):
        runtime = PersistentVoiceRuntime(
            wakeword=None, core=FakeCore(), realtime_factory=None,  # type: ignore[arg-type]
            journal=RecordingJournal(), voice_arch=VoiceArchitecture.LEGACY,  # type: ignore[arg-type]
        )
        outcomes.append((await runtime.submit_active_turn(source=label), runtime.runtime.state))
    assert outcomes[0] == outcomes[1]

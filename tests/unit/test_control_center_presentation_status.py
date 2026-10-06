"""Bloc `presentation` de `GET /api/status` (handoff presentation-interaction-mode, Slice 10, P7).

Voice écrit le relevé de son coordinateur PRESENTATION dans `.voice_presentation`
(`VisualSignalBus.presentation`) ; le Control Center le relit à chaque sondage,
comme `.voice_capture`. Ce fichier épingle les deux moitiés du contrat :

- le relevé est **fait de scalaires** — un fichier écrit par un autre processus
  ne fait passer ni liste, ni objet, ni phrase, ni clé inconnue ;
- il disparaît (`null`) dès que Voice ne bat plus.

Le premier cas fait écrire le relevé par le **vrai** coordinateur, composé par
la même composition qu'en production : ce qui est vérifié est ce que Voice
publie, pas ce que le test imagine qu'il publie.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain.interaction_mode import InteractionMode
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.presentation_runtime import PresentationCoordinator, PresentationWakeRouter
from jarvis.runtime.visual_signals import VisualSignalBus
from tests.unit.test_ambient_ingestion_lane import RecordingJournal
from tests.unit.test_presentation_integration import FakeSimpleWake, composition

PLANTED = "Ducroix a dit que la marge est de 31 pour cent"
EXPECTED_KEYS = {
    "event", "active", "session_id", "entered", "entry_failures", "left", "last_failure_code",
    "blockers", "blocker_code", "physical_input_owners", "ambient_deaf", "ambient_degraded",
    "segments_pending", "analysis_pending", "trigger_latency_s", "enrichment_lag_s",
    "speculative_in_flight", "speculative_free_explicit_slots", "speculative_staged", "attention_live", "ts",
}


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "PORCUPINE_ACCESS_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


async def _presentation(control: ControlCenter) -> object:
    return json.loads((await control.status(None)).text)["presentation"]


def _scalar(value: object) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


async def test_status_exposes_presentation_scalars_only(control, tmp_path):
    signals = VisualSignalBus(tmp_path)
    signals.heartbeat()
    journal = RecordingJournal()
    built, _, _, _ = composition(tmp_path, journal)
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake(), journal=journal),
        build=built.build, journal=journal, signals=signals,
    )
    await coordinator.apply(InteractionMode.PRESENTATION)
    try:
        report = await _presentation(control)
    finally:
        await coordinator.aclose()

    assert set(report) == EXPECTED_KEYS
    assert all(_scalar(value) for value in report.values()), report
    assert (report["event"], report["active"], report["entered"]) == ("entered", True, 1)
    assert report["session_id"].startswith("pres-")
    assert report["physical_input_owners"] == 1 and report["attention_live"] == 0
    # Voice arrêté proprement : le relevé est retiré.
    assert not (tmp_path / VisualSignalBus.PRESENTATION_FILE).exists()

    # Un fichier écrit à la main (ou par un Voice plus récent) ne fait rien passer d'autre.
    signals.presentation({
        "event": "tick", "active": True, "session_id": "pres-x", "entered": "deux",
        "attention_live": [1, 2], "trigger_latency_s": float("nan"), "blocker_code": PLANTED * 3,
        "detail": {"transcript": PLANTED}, "room_text": PLANTED, "ambient_deaf": 1,
    })
    report = await _presentation(control)
    assert set(report) == EXPECTED_KEYS
    assert all(_scalar(value) for value in report.values()), report
    assert report["entered"] is None and report["attention_live"] is None
    assert report["trigger_latency_s"] is None and report["ambient_deaf"] is None
    assert len(report["blocker_code"]) == 64
    assert "room_text" not in report and "detail" not in report


async def test_presentation_report_hidden_when_voice_offline(control, tmp_path):
    signals = VisualSignalBus(tmp_path)
    signals.heartbeat()
    signals.presentation({"event": "entered", "active": True, "session_id": "pres-y", "entered": 1})
    assert (await _presentation(control))["active"] is True

    # Battement périmé : Voice ne tient plus ce relevé à jour.
    (tmp_path / ".voice_heartbeat").write_text("0\n", encoding="utf-8")
    assert await _presentation(control) is None

    # Voice éteint (`offline`) : le fichier lui-même est retiré.
    signals.heartbeat()
    signals.offline()
    assert not (tmp_path / VisualSignalBus.PRESENTATION_FILE).exists()
    assert await _presentation(control) is None

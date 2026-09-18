from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.audio_devices import AudioDiagnosticError
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.visual_signals import VisualSignalBus


CONTROL_CENTER_HTML = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html"


def test_visual_signal_bus_writes_supported_states(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.state("thinking")
    assert (tmp_path / ".voice_state").read_text(encoding="utf-8").strip() == "thinking"


def test_visual_signal_bus_tracks_heartbeat_and_clears_stale_visuals(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.state("listening")
    bus.alert("active")
    bus.waveform([0.5])
    bus.heartbeat()

    assert float((tmp_path / ".voice_heartbeat").read_text(encoding="utf-8")) <= time.time()

    bus.offline()
    assert (tmp_path / ".voice_state").read_text(encoding="utf-8").strip() == "idle"
    assert not (tmp_path / ".voice_heartbeat").exists()
    assert not (tmp_path / ".voice_alert").exists()
    assert not (tmp_path / ".voice_waveform").exists()
    bus.alert("provider failed")
    assert "provider failed" in (tmp_path / ".voice_alert").read_text(encoding="utf-8")
    bus.alert(None)
    assert not (tmp_path / ".voice_alert").exists()


def test_visual_signal_bus_writes_waveform(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.waveform([1.0, -2.0, 3.0])
    payload = json.loads((tmp_path / ".voice_waveform").read_text(encoding="utf-8"))
    assert payload["samples"] == [1.0, -2.0, 3.0]
    assert payload["ts"] > 0


def test_runtime_journal_splits_errors_and_trace(tmp_path):
    journal = RuntimeJournal(tmp_path)
    journal.emit("voice.start", "started")
    journal.emit("provider.error", "boom", level="error", data={"code": "bad"})

    trace = read_jsonl_tail(journal.trace_path)
    errors = read_jsonl_tail(journal.error_path)
    assert [item["kind"] for item in trace] == ["voice.start", "provider.error"]
    assert [item["kind"] for item in errors] == ["provider.error"]
    assert errors[0]["data"]["code"] == "bad"


def test_runtime_journal_tail_limit(tmp_path):
    journal = RuntimeJournal(tmp_path)
    for index in range(5):
        journal.emit("event", str(index))
    assert [item["message"] for item in read_jsonl_tail(journal.trace_path, limit=2)] == ["3", "4"]


def test_control_center_keeps_pointer_visible_and_explains_configured_voice_toggle():
    html = CONTROL_CENTER_HTML.read_text(encoding="utf-8")
    assert "pointer-events:none;cursor:default" in html
    assert "F9 · DÉMARRER" in html
    # Under server VAD the key never means "send" while a turn is open: it can
    # only cancel. The "send" wording is kept for the manual turn mode.
    assert "s.voice_turn_mode==='manual'?`${k} · ENVOYER`:`${k} · ANNULER`" in html
    assert "`${k} · ANNULER`" in html
    assert "`${k} · INTERROMPRE`" in html
    assert "persistence==='audio_input_device'" in html
    assert "persistence==='audio_output_device'" in html
    assert "Tester micro + sortie" in html


def test_background_notifications_are_round_pills_in_the_main_interface_not_a_tool():
    """Retour utilisateur du 16/09/2026 : pas de bouton « BGD » parmi les outils.

    Le bouton Agents reste l'entrée de gestion des sous-agents ; les
    notifications d'arrière-plan sont de petites pastilles rondes de
    l'interface principale, accolées à lui, qui s'ouvrent et s'acquittent sur
    place.
    """
    html = CONTROL_CENTER_HTML.read_text(encoding="utf-8")
    dock = html[html.index('<nav class="dock"') : html.index("</nav>", html.index('<nav class="dock"'))]
    assert 'data-panel="background"' not in html and "BGD" not in dock and "bgBadge" not in html
    assert 'id="agentsButton"' in dock
    # Hors de la barre d'outils, juste après elle, et jamais dans les réglages.
    after_dock = html[html.index("</nav>", html.index('<nav class="dock"')) :]
    assert after_dock.index('id="bgPills"') < after_dock.index('id="panel"')
    assert "id:'background'" not in html
    assert ".bgpill{" in html and "border-radius:50%" in html[html.index(".bgpill{") :][:400]
    assert "renderBackgroundPills(s.background)" in html
    # Chaque pastille s'acquitte seule, et mène au panneau Agents.
    assert "JSON.stringify({seq:data.seq,category})" in html
    assert "openAgentsAt(id?'trace':'list',id||null)" in html
    work = CONTROL_CENTER_HTML.with_name("control_center_work.js").read_text(encoding="utf-8")
    assert 'html[data-jarvis-theme="omega"] .bgpills{' in work


def test_settings_window_is_a_modal_that_closes_on_an_outside_click():
    """La fenêtre de réglages est une modale centrée, dimensionnée en % d'écran.

    Ces assertions portent sur des choix demandés explicitement : un clic à
    l'extérieur ferme, et la taille suit la fenêtre plutôt qu'un nombre de
    pixels. Les champs eux-mêmes ne sont pas vérifiés ici : ils sont décrits
    par le serveur, pas écrits en dur dans la page.
    """
    html = CONTROL_CENTER_HTML.read_text(encoding="utf-8")
    assert ".modal{width:82vw;height:82vh" in html
    assert "overlay.addEventListener('mousedown',event=>{if(event.target===overlay)closeSettings()})" in html
    for label in ("Voix", "Prompts", "Agent / CLI", "API Keys", "Raccourcis"):
        assert f"label:'{label}'" in html
    assert "id:'config'" not in html
    # Les listes de modèles passent par le catalogue du serveur : aucune liste
    # de modèles ne doit être écrite dans la page.
    assert "/api/models?provider=" in html


def test_control_center_defaults_manual_voice_toggle_to_f9(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    assert control._settings()["manual_wake_key"] == "f9"


@pytest.mark.asyncio
async def test_control_center_rejects_stale_listening_state(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.state("listening")
    (tmp_path / ".voice_heartbeat").write_text("0\n", encoding="utf-8")
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)

    response = await control.status(None)
    payload = json.loads(response.text)

    assert payload["voice_online"] is False
    assert payload["voice_state"] == "idle"
    assert (tmp_path / ".voice_state").read_text(encoding="utf-8").strip() == "idle"


@pytest.mark.asyncio
async def test_control_center_accepts_live_listening_state(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.state("listening")
    bus.heartbeat()
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)

    response = await control.status(None)
    payload = json.loads(response.text)

    assert payload["voice_online"] is True
    assert payload["voice_state"] == "listening"


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


class FakeAudioDiagnostics:
    def __init__(
        self,
        *,
        failure: AudioDiagnosticError | None = None,
        list_failure: AudioDiagnosticError | None = None,
    ) -> None:
        self.failure = failure
        self.list_failure = list_failure
        self.tests: list[tuple[object, object]] = []

    def list_devices(self) -> dict[str, object]:
        if self.list_failure is not None:
            raise self.list_failure
        return {
            "inputs": [{"id": 3, "name": "Test Mic", "hostapi": "WASAPI", "channels": 1}],
            "outputs": [{"id": 7, "name": "Test Speaker", "hostapi": "WASAPI", "channels": 2}],
            "defaults": {"input": 3, "output": 7},
            "sample_rate": 24_000,
        }

    def test_record_and_playback(self, *, input_device, output_device) -> dict[str, object]:  # noqa: ANN001
        self.tests.append((input_device, output_device))
        if self.failure is not None:
            raise self.failure
        return {"ok": True, "peak_dbfs": -8.5, "rms_dbfs": -18.2, "duration_s": 2.0, "sample_rate": 24_000}


@pytest.mark.asyncio
async def test_control_center_persists_audio_device_selection(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)

    response = await control.save_settings(JsonRequest({"audio_input_device": "3", "audio_output_device": "7"}))  # type: ignore[arg-type]
    payload = json.loads(response.text)

    assert payload["audio_input_device"] == "3"
    assert payload["audio_output_device"] == "7"
    saved = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert saved["audio_input_device"] == "3"
    assert saved["audio_output_device"] == "7"


@pytest.mark.asyncio
async def test_control_center_audio_test_uses_selected_devices_and_emits_trace(tmp_path):
    diagnostics = FakeAudioDiagnostics()
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, audio_diagnostics=diagnostics)  # type: ignore[arg-type]

    response = await control.audio_test(JsonRequest({"input_device": "3", "output_device": "7"}))  # type: ignore[arg-type]
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["ok"] is True
    assert diagnostics.tests == [(3, 7)]
    # `scene.display_mcp_unconfigured` : ce harnais ne donne pas les coordonnées de Core
    # et la scène est allumée par défaut ; ce n'est pas la trace observée ici.
    trace = [item for item in read_jsonl_tail(control.journal.trace_path) if item["kind"].startswith("audio.")]
    assert [item["kind"] for item in trace] == ["audio.test.started", "audio.test.completed"]
    assert trace[0]["data"]["correlation_id"] == trace[1]["data"]["correlation_id"]


@pytest.mark.asyncio
async def test_control_center_lists_audio_devices_with_trace(tmp_path):
    diagnostics = FakeAudioDiagnostics()
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, audio_diagnostics=diagnostics)  # type: ignore[arg-type]

    response = await control.audio_devices(None)
    payload = json.loads(response.text)

    assert payload["ok"] is True
    assert payload["inputs"][0]["name"] == "Test Mic"
    assert payload["outputs"][0]["name"] == "Test Speaker"
    trace = read_jsonl_tail(control.journal.trace_path)
    assert trace[-1]["kind"] == "audio.devices.listed"


@pytest.mark.asyncio
async def test_control_center_audio_test_returns_stable_failure_code(tmp_path):
    diagnostics = FakeAudioDiagnostics(failure=AudioDiagnosticError("audio_input_no_signal", "Aucun signal."))
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, audio_diagnostics=diagnostics)  # type: ignore[arg-type]

    response = await control.audio_test(JsonRequest({"input_device": "3", "output_device": "7"}))  # type: ignore[arg-type]
    payload = json.loads(response.text)

    assert response.status == 422
    assert payload["code"] == "audio_input_no_signal"
    errors = read_jsonl_tail(control.journal.error_path)
    assert errors[-1]["kind"] == "audio.test.failed"
    assert errors[-1]["data"]["code"] == "audio_input_no_signal"


@pytest.mark.asyncio
async def test_control_center_audio_device_failure_is_actionable(tmp_path):
    diagnostics = FakeAudioDiagnostics(
        list_failure=AudioDiagnosticError("audio_device_enumeration_failed", "Périphériques indisponibles."),
    )
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, audio_diagnostics=diagnostics)  # type: ignore[arg-type]

    response = await control.audio_devices(None)
    payload = json.loads(response.text)

    assert response.status == 503
    assert payload["code"] == "audio_device_enumeration_failed"
    errors = read_jsonl_tail(control.journal.error_path)
    assert errors[-1]["kind"] == "audio.devices.failed"


@pytest.mark.asyncio
async def test_control_center_rejects_invalid_audio_device_id(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, audio_diagnostics=FakeAudioDiagnostics())  # type: ignore[arg-type]

    response = await control.audio_test(JsonRequest({"input_device": "-1", "output_device": "7"}))  # type: ignore[arg-type]
    payload = json.loads(response.text)

    assert response.status == 400
    assert payload["code"] == "audio_test_invalid_request"
    errors = read_jsonl_tail(control.journal.error_path)
    assert errors[-1]["data"]["code"] == "audio_test_invalid_request"


def test_visual_bus_publishes_even_when_replace_is_blocked(tmp_path, monkeypatch):
    """Windows opens files without FILE_SHARE_DELETE, so a Control Center poll of
    the bus can make os.replace fail. The signal must still reach the reader."""
    bus = VisualSignalBus(tmp_path)
    monkeypatch.setattr(VisualSignalBus, "REPLACE_BACKOFF_S", 0.0)
    attempts = {"count": 0}
    original = Path.replace

    def blocked(self, target):
        attempts["count"] += 1
        raise PermissionError("[WinError 5] Access is denied")

    monkeypatch.setattr(Path, "replace", blocked)
    bus.heartbeat()
    monkeypatch.setattr(Path, "replace", original)

    assert attempts["count"] == VisualSignalBus.REPLACE_ATTEMPTS
    heartbeat = tmp_path / ".voice_heartbeat"
    assert float(heartbeat.read_text(encoding="utf-8").strip()) > 0
    assert not (tmp_path / ".voice_heartbeat.tmp").exists()


def test_visual_bus_recovers_after_a_transient_replace_failure(tmp_path, monkeypatch):
    bus = VisualSignalBus(tmp_path)
    monkeypatch.setattr(VisualSignalBus, "REPLACE_BACKOFF_S", 0.0)
    original = Path.replace
    calls = {"count": 0}

    def flaky(self, target):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("[WinError 5] Access is denied")
        return original(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    bus.state("listening")
    monkeypatch.setattr(Path, "replace", original)

    assert calls["count"] == 2
    assert (tmp_path / ".voice_state").read_text(encoding="utf-8").strip() == "listening"


@pytest.mark.asyncio
async def test_control_center_persists_voice_timbre_and_turn_mode(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    settings = control._settings()
    assert settings["realtime_voice"] == "cedar"
    assert settings["voice_turn_mode"] == "auto"

    class Payload:
        @staticmethod
        async def json():
            return {"realtime_voice": "ash", "voice_turn_mode": "manual"}

    response = await control.save_settings(Payload())  # type: ignore[arg-type]
    stored = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert stored["realtime_voice"] == "ash"
    assert stored["voice_turn_mode"] == "manual"
    assert json.loads(response.text)["realtime_voice"] == "ash"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{"realtime_voice": "not-a-voice"}, {"voice_turn_mode": "sometimes"}],
)
async def test_control_center_rejects_unknown_voice_settings(tmp_path, payload):
    from aiohttp import web

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)

    class Payload:
        @staticmethod
        async def json():
            return payload

    with pytest.raises(web.HTTPBadRequest):
        await control.save_settings(Payload())  # type: ignore[arg-type]
    assert not (tmp_path / "control-center-settings.json").exists()


@pytest.mark.asyncio
async def test_status_reports_turn_mode_for_the_key_hint(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    payload = json.loads((await control.status(None)).text)  # type: ignore[arg-type]
    assert payload["voice_turn_mode"] == "auto"

    (tmp_path / "control-center-settings.json").write_text(
        json.dumps({"voice_turn_mode": "manual"}), encoding="utf-8"
    )
    payload = json.loads((await control.status(None)).text)  # type: ignore[arg-type]
    assert payload["voice_turn_mode"] == "manual"

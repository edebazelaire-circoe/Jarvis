from __future__ import annotations

import asyncio
import json

import pytest

import jarvis.app as app
import jarvis.environment as environment


@pytest.fixture(autouse=True)
def isolated_project_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "PROJECT_ROOT", tmp_path)


@pytest.mark.asyncio
async def test_no_subcommand_defaults_to_health_without_missing_namespace_fields(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(app.AppConfig, "load", lambda path=None: sentinel)
    seen = {}

    async def fake_health(config, *, skip_audio):
        seen["config"] = config
        seen["skip_audio"] = skip_audio
        return 0

    monkeypatch.setattr(app, "_health", fake_health)
    assert await app._amain([]) == 0
    assert seen == {"config": sentinel, "skip_audio": False}


@pytest.mark.asyncio
async def test_health_skip_audio_flag_is_forwarded(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(app.AppConfig, "load", lambda path=None: sentinel)
    seen = {}

    async def fake_health(config, *, skip_audio):
        seen["skip_audio"] = skip_audio
        return 0

    monkeypatch.setattr(app, "_health", fake_health)
    assert await app._amain(["health", "--skip-audio"]) == 0
    assert seen["skip_audio"] is True


@pytest.mark.asyncio
async def test_heartbeat_loop_survives_a_locked_bus_file():
    """A blocked bus write must not silently end the loop: a missing heartbeat is
    what the Control Center reads as "voice OFFLINE" and blanks the face for."""
    import asyncio

    published = []

    class FlakySignals:
        def __init__(self):
            self.calls = 0

        def heartbeat(self):
            self.calls += 1
            if self.calls == 1:
                raise PermissionError("[WinError 5] Access is denied")
            published.append(self.calls)

    class Voice:
        def __init__(self):
            self.checks = 0

        async def check_timeout(self):
            self.checks += 1
            return False

    class Journal:
        def __init__(self):
            self.events = []

        def emit(self, kind, message, *, level="info", data=None):
            self.events.append((kind, level, message))

    signals, voice, journal = FlakySignals(), Voice(), Journal()
    task = asyncio.create_task(app._voice_timeout_loop(voice, signals, journal))
    try:
        for _ in range(300):
            if len(published) >= 2:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert len(published) >= 2
    assert voice.checks >= 2
    assert [event[0] for event in journal.events] == ["voice.heartbeat_degraded"]
    assert journal.events[0][1] == "warning"


# ---------------------------------------------------------------------------
# Architecture vocale : le réglage du Control Center passe devant l'environnement


class _StopVoice(Exception):
    """Levée par le faux runtime : le montage de Voice est allé au bout."""


class _FakeCoreClient:
    def __init__(self, **_kwargs) -> None:
        pass

    async def health(self) -> dict[str, object]:
        return {"ready": True}

    async def close(self) -> None:
        pass


class _FakeWakeBackend:
    """Réveil clavier neutre : le vrai accroche le clavier de la machine."""

    def __init__(self, **_kwargs) -> None:
        pass


def _voice_startup(tmp_path, monkeypatch, *, env_arch: str | None, overrides: dict) -> dict:
    """Monter `_run_voice_v2` jusqu'au runtime vocal, sans audio ni réseau.

    Rend ce que le runtime a reçu, plus les arguments d'une connexion OpenAI
    déclenchée à la main (`connect`) : c'est là que se lit le modèle retenu.
    """
    from jarvis.adapters import wakeword_keyboard
    from jarvis.adapters.openai_realtime import OpenAIRealtimeSession
    from jarvis.protocol import client as protocol_client
    from jarvis.runtime import voice_v2

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "core.token").write_text("jeton-de-test", encoding="utf-8")
    (runtime_root / "control-center-settings.json").write_text(json.dumps(overrides), encoding="utf-8")
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-de-test")
    for name in (
        "PORCUPINE_ACCESS_KEY", "OPENAI_REALTIME_MODEL", "JARVIS_AUDIO_INPUT_DEVICE",
        "JARVIS_AUDIO_OUTPUT_DEVICE", "JARVIS_VOICE_STACK", "JARVIS_VOICE_TURN_MODE",
    ):
        monkeypatch.delenv(name, raising=False)
    if env_arch is None:
        monkeypatch.delenv("JARVIS_VOICE_ARCH", raising=False)
    else:
        monkeypatch.setenv("JARVIS_VOICE_ARCH", env_arch)
    monkeypatch.setattr(protocol_client, "LocalCoreClient", _FakeCoreClient)
    monkeypatch.setattr(wakeword_keyboard, "KeyboardWakeWordBackend", _FakeWakeBackend)

    captured: dict = {"runtime_root": runtime_root}

    class FakeRuntime:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        async def check_timeout(self) -> bool:
            return False

        async def run(self) -> None:
            raise _StopVoice

        async def close(self) -> None:
            pass

    async def fake_connect(**kwargs):
        captured["connect"] = kwargs
        from jarvis.domain.v2 import ProtocolEnvelope

        class ConnectedSession:
            """Provider boundary double; canonical startup still requires ACK."""
            active_output_id = None

            def __init__(self):
                self.closed = asyncio.Event()

            async def events(self):
                yield ProtocolEnvelope(message_type="realtime.session_updated", payload={
                    "session_id": "test-provider-session", "instructions": kwargs["instructions_override"],
                })
                await self.closed.wait()

            async def close(self):
                self.closed.set()

        return ConnectedSession()

    monkeypatch.setattr(voice_v2, "PersistentVoiceRuntime", FakeRuntime)
    monkeypatch.setattr(OpenAIRealtimeSession, "connect", staticmethod(fake_connect))
    return captured


async def _start_voice(captured: dict) -> dict:
    """Lancer Voice, déclencher une connexion, rendre l'évènement `voice.stack`."""
    from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail

    with pytest.raises(_StopVoice):
        await app._run_voice_v2()
    session = await captured["realtime_factory"]({})
    try:
        from jarvis.runtime.realtime_frontend_session import RealtimeFrontendSession
        from jarvis.domain.voice_frontend import FrontendState
        assert isinstance(session, RealtimeFrontendSession)
        assert session.frontend.state is FrontendState.ACTIVE
    finally:
        await session.close()
    trace = read_jsonl_tail(RuntimeJournal(captured["runtime_root"]).trace_path, limit=100)
    return next(item for item in trace if item.get("kind") == "voice.stack")


@pytest.mark.parametrize(
    ("selection", "expected"),
    [("legacy", "legacy"), ("continuous_brain", "continuous_brain"), ("simple", "simple")],
)
async def test_operational_architecture_provenance_matches_the_runtime(
    tmp_path, monkeypatch, selection, expected,
):
    from jarvis.domain.voice_architecture import SimpleVoiceConfig, VoiceModelRef
    from jarvis.runtime import voice_switch
    from jarvis.runtime.voice_architecture_config import VoiceArchitectureSettings

    overrides = {"voice_arch": selection}
    if selection == "simple":
        overrides = {
            "voice_architecture": VoiceArchitectureSettings(
                SimpleVoiceConfig(VoiceModelRef("openai", "gpt-realtime-2.1"))
            ).to_dict()
        }
    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides=overrides)

    class CapturingSwitchCoordinator:
        def __init__(self, **kwargs) -> None:
            captured["switch_architecture"] = kwargs["architecture"]

        async def poll(self) -> bool:
            return False

    monkeypatch.setattr(voice_switch, "VoiceSwitchCoordinator", CapturingSwitchCoordinator)
    await _start_voice(captured)

    assert captured["metric_recorder_factory"]().architecture == expected
    assert captured["switch_architecture"] == expected


async def test_voice_honours_the_control_center_architecture(tmp_path, monkeypatch):
    from jarvis.adapters.openai_realtime import CONTINUOUS_BRAIN_OPERATING_RULES, JARVIS_PERSONA
    from jarvis.runtime.realtime_tools import tools_for
    from jarvis.v2_config import DEFAULT_CONTINUOUS_SURFACE_MODEL, VoiceArchitecture

    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides={"voice_arch": "continuous_brain"})
    stack_event = await _start_voice(captured)

    assert captured["voice_arch"] is VoiceArchitecture.CONTINUOUS_BRAIN
    # Mode continu : Voice ne joint plus l'agent, Core s'en charge.
    assert captured["claude"] is None
    assert captured["connect"]["continuous_brain"] is True
    assert captured["connect"]["instructions_override"] == JARVIS_PERSONA + " " + CONTINUOUS_BRAIN_OPERATING_RULES
    assert captured["connect"]["tools"] == tools_for(continuous_brain=True)
    # Sans OPENAI_REALTIME_MODEL, le modèle conseillé suit l'architecture effective.
    assert captured["connect"]["model"] == DEFAULT_CONTINUOUS_SURFACE_MODEL
    assert stack_event["data"]["arch"] == "continuous_brain"
    assert stack_event["data"]["arch_source"] == "settings"


async def test_the_control_center_architecture_wins_over_the_environment(tmp_path, monkeypatch):
    from jarvis.adapters.openai_realtime import JARVIS_PERSONA, OPERATING_RULES
    from jarvis.runtime.claude_gateway import ClaudeGateway
    from jarvis.runtime.realtime_tools import tools_for
    from jarvis.v2_config import DEFAULT_REALTIME_MODEL, VoiceArchitecture

    captured = _voice_startup(tmp_path, monkeypatch, env_arch="continuous_brain", overrides={"voice_arch": "legacy"})
    stack_event = await _start_voice(captured)

    assert captured["voice_arch"] is VoiceArchitecture.LEGACY
    assert isinstance(captured["claude"], ClaudeGateway)
    assert captured["connect"]["continuous_brain"] is False
    assert captured["connect"]["instructions_override"] == JARVIS_PERSONA + " " + OPERATING_RULES
    assert captured["connect"]["tools"] == tools_for(continuous_brain=False)
    # L'environnement seul aurait retenu le modèle du mode continu.
    assert captured["connect"]["model"] == DEFAULT_REALTIME_MODEL
    assert stack_event["data"]["arch_source"] == "settings"


async def test_an_empty_setting_falls_back_to_the_environment(tmp_path, monkeypatch):
    from jarvis.v2_config import VoiceArchitecture

    captured = _voice_startup(tmp_path, monkeypatch, env_arch="continuous_brain", overrides={"voice_arch": ""})
    stack_event = await _start_voice(captured)

    assert captured["voice_arch"] is VoiceArchitecture.CONTINUOUS_BRAIN
    assert stack_event["data"]["arch_source"] == "env"


async def test_an_explicit_realtime_model_is_kept_whatever_the_architecture(tmp_path, monkeypatch):
    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides={"voice_arch": "continuous_brain"})
    monkeypatch.setenv("OPENAI_REALTIME_MODEL", "un-modele-a-moi")
    await _start_voice(captured)

    assert captured["connect"]["model"] == "un-modele-a-moi"


async def test_an_unknown_architecture_in_the_settings_file_stops_voice_clearly(tmp_path, monkeypatch):
    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides={"voice_arch": "duplex"})

    with pytest.raises(RuntimeError, match="Architecture vocale inconnue"):
        await app._run_voice_v2()
    assert "voice_arch" not in captured


async def test_an_invalid_explicit_voice_configuration_marks_pending_restart_failed(
    tmp_path, monkeypatch,
):
    from jarvis.runtime import voice_switch

    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides={
        "voice_architecture": {
            "schema_version": 1,
            "config": {"architecture": "invalid"},
            "compatibility": None,
        },
    })
    failure_codes = []

    class CapturingSwitchBus:
        def __init__(self, _root) -> None:
            pass

        def mark_pending_restart_failed(self, *, code: str) -> None:
            failure_codes.append(code)

    monkeypatch.setattr(voice_switch, "VoiceSwitchBus", CapturingSwitchBus)

    with pytest.raises(RuntimeError, match="configuration invalide"):
        await app._run_voice_v2()

    assert failure_codes == ["replacement_configuration_invalid"]
    assert "voice_arch" not in captured and "connect" not in captured


async def test_explicit_duplex_reaches_credential_gate_before_session(tmp_path, monkeypatch):
    from jarvis.domain.voice_architecture import DuplexVoiceConfig, VoiceModelRef
    from jarvis.runtime.voice_architecture_config import VoiceArchitectureSettings

    config = DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1"))
    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides={
        "voice_architecture": VoiceArchitectureSettings(config).to_dict(),
    })
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await app._run_voice_v2()
    assert "voice_arch" not in captured
    assert "connect" not in captured


async def test_explicit_duplex_factory_selects_live_session(tmp_path, monkeypatch):
    from jarvis.domain.voice_architecture import DuplexVoiceConfig, VoiceModelRef
    from jarvis.runtime.live_frontend_session import LiveFrontendSession
    from jarvis.runtime.voice_architecture_config import VoiceArchitectureSettings

    config = DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1"))
    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides={
        "voice_architecture": VoiceArchitectureSettings(config).to_dict(),
    })
    connection = {}

    async def connect(**kwargs):
        connection.update(kwargs)
        return object()

    monkeypatch.setattr(LiveFrontendSession, "connect", staticmethod(connect))
    with pytest.raises(_StopVoice):
        await app._run_voice_v2()
    result = await captured["realtime_factory"]({"voice_ledger": {"revision": 1}})

    assert result is not None
    assert connection["architecture_config"] == config
    assert connection["voice"]
    assert captured["conversation_architecture"].value == "duplex"


async def test_the_duplex_capture_has_no_speaker_verifier_by_default(tmp_path, monkeypatch):
    """Tâche 02 Solo Owner : la couture existe, rien n'y est branché."""

    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides={"voice_arch": "continuous_brain"})
    await _start_voice(captured)

    processor = captured["capture_factory"]()

    assert processor.observer is None


async def test_an_injected_speaker_verifier_observes_the_capture_in_shadow(tmp_path, monkeypatch):
    from jarvis.adapters.fake_speaker_verifier import ScriptedSpeakerVerifier
    from jarvis.audio.speaker_shadow import SpeakerVerificationWorker

    verifier = ScriptedSpeakerVerifier()
    monkeypatch.setattr(app, "_speaker_verifier", lambda *args, **kwargs: verifier)
    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides={"voice_arch": "continuous_brain"})
    await _start_voice(captured)

    processor = captured["capture_factory"]()
    try:
        assert isinstance(processor.observer, SpeakerVerificationWorker)
        assert processor.observer.telemetry.verifier is verifier
    finally:
        processor.close()
    assert verifier.closed


async def test_only_solo_owner_gives_the_capture_an_owner_replay_buffer(tmp_path, monkeypatch):
    """Tâche 06 Solo Owner : tampon de rejeu dimensionné par `owner_buffer_ms`, absent en salle ouverte."""

    monkeypatch.setattr(app, "_speaker_verifier", lambda *args, **kwargs: None)
    (tmp_path / "solo").mkdir()
    (tmp_path / "room").mkdir()
    solo = _voice_startup(
        tmp_path / "solo",
        monkeypatch,
        env_arch=None,
        overrides={"voice_arch": "continuous_brain", "conversation_mode": "solo_owner", "owner_buffer_ms": 1800},
    )
    await _start_voice(solo)
    assert solo["capture_factory"]().owner_buffer_ms == 1800

    room = _voice_startup(tmp_path / "room", monkeypatch, env_arch=None, overrides={"voice_arch": "continuous_brain"})
    await _start_voice(room)
    processor = room["capture_factory"]()
    assert processor.owner_buffer_ms == 0 and processor.set_owner_gate(True) is False


async def test_voice_receives_the_conversation_authorization(tmp_path, monkeypatch):
    """Tâche 05 Solo Owner : le mode choisi atteint le runtime, qui en tire l'autorité du barge-in."""
    from jarvis.domain.speaker import ConversationMode, SpeakerVerificationMode

    captured = _voice_startup(
        tmp_path, monkeypatch, env_arch=None, overrides={"voice_arch": "continuous_brain", "conversation_mode": "solo_owner"}
    )
    await _start_voice(captured)

    assert captured["authorization"].mode is ConversationMode.SOLO_OWNER
    assert captured["authorization"].verification is SpeakerVerificationMode.ENFORCE


async def test_an_invalid_conversation_setting_is_handed_to_voice_to_refuse_and_say_so(tmp_path, monkeypatch):
    """Tâche 07 : plus de salle ouverte gardée en silence — le runtime reçoit l'erreur et refuse d'écouter."""
    from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail

    captured = _voice_startup(
        tmp_path, monkeypatch, env_arch=None, overrides={"voice_arch": "continuous_brain", "conversation_mode": "salon"}
    )
    await _start_voice(captured)

    assert captured["authorization_error"].code == "conversation_mode_unknown"
    trace = read_jsonl_tail(RuntimeJournal(captured["runtime_root"]).trace_path, limit=100)
    invalid = [item for item in trace if item.get("kind") == "voice.authorization_invalid"]
    assert invalid and invalid[0]["data"]["code"] == "conversation_mode_unknown"
    assert "n'écoutera pas" in invalid[0]["message"]


async def test_a_valid_conversation_setting_carries_no_error(tmp_path, monkeypatch):
    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides={"voice_arch": "continuous_brain"})
    await _start_voice(captured)

    assert captured["authorization_error"] is None

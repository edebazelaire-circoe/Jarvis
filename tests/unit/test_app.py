from __future__ import annotations

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
        return object()

    monkeypatch.setattr(voice_v2, "PersistentVoiceRuntime", FakeRuntime)
    monkeypatch.setattr(OpenAIRealtimeSession, "connect", staticmethod(fake_connect))
    return captured


async def _start_voice(captured: dict) -> dict:
    """Lancer Voice, déclencher une connexion, rendre l'évènement `voice.stack`."""
    from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail

    with pytest.raises(_StopVoice):
        await app._run_voice_v2()
    await captured["realtime_factory"]({})
    trace = read_jsonl_tail(RuntimeJournal(captured["runtime_root"]).trace_path, limit=100)
    return next(item for item in trace if item.get("kind") == "voice.stack")


async def test_voice_honours_the_control_center_architecture(tmp_path, monkeypatch):
    from jarvis.v2_config import DEFAULT_CONTINUOUS_SURFACE_MODEL, VoiceArchitecture

    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides={"voice_arch": "continuous_brain"})
    stack_event = await _start_voice(captured)

    assert captured["voice_arch"] is VoiceArchitecture.CONTINUOUS_BRAIN
    # Mode continu : Voice ne joint plus l'agent, Core s'en charge.
    assert captured["claude"] is None
    assert captured["connect"]["continuous_brain"] is True
    # Sans OPENAI_REALTIME_MODEL, le modèle conseillé suit l'architecture effective.
    assert captured["connect"]["model"] == DEFAULT_CONTINUOUS_SURFACE_MODEL
    assert stack_event["data"]["arch"] == "continuous_brain"
    assert stack_event["data"]["arch_source"] == "settings"


async def test_the_control_center_architecture_wins_over_the_environment(tmp_path, monkeypatch):
    from jarvis.runtime.claude_gateway import ClaudeGateway
    from jarvis.v2_config import DEFAULT_REALTIME_MODEL, VoiceArchitecture

    captured = _voice_startup(tmp_path, monkeypatch, env_arch="continuous_brain", overrides={"voice_arch": "legacy"})
    stack_event = await _start_voice(captured)

    assert captured["voice_arch"] is VoiceArchitecture.LEGACY
    assert isinstance(captured["claude"], ClaudeGateway)
    assert captured["connect"]["continuous_brain"] is False
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

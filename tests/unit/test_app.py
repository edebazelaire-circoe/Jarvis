from __future__ import annotations

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

from __future__ import annotations

import pytest

import jarvis.app as app


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

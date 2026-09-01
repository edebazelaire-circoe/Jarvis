from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.config import AppConfig, ComponentConfig
from jarvis.runtime.health import run_health_checks

from conftest import RecordingBoard


class HealthyRecorder:
    def preflight(self):
        return {"name": "Fake microphone"}


@pytest.mark.asyncio
async def test_optional_board_failure_is_warning_not_global_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    example = tmp_path / "config" / "jarvis.example.toml"
    example.write_text(
        '''[openai]\nbase_url="https://api.openai.com/v1"\ntranscription_model="stt"\nagent_model="agent"\ntts_model="tts"\ntts_voice="voice"\ntimeout_s=10\n[runtime]\nptt_key="f9"\nmemory_dir="./memory"\nruntime_dir="./runtime"\nlog_level="INFO"\nlog_content=false\nconfirmation_timeout_s=30\n[audio]\nsample_rate=16000\nchannels=1\n[board]\nenabled=true\nurl="http://127.0.0.1:8794"\n[visualizer]\nenabled=false\nurl="http://127.0.0.1:8790"\n''',
        encoding="utf-8",
    )
    config = AppConfig.load(example)
    report = await run_health_checks(
        config,
        board=RecordingBoard(fail=True),
        recorder=HealthyRecorder(),
    )
    assert report.status == "warn"
    board = next(c for c in report.checks if c.name == "barehands")
    assert board.status == "warn" and board.required is False


@pytest.mark.asyncio
async def test_voice_only_health_does_not_warn_about_unneeded_third_party(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    example = config_dir / "jarvis.example.toml"
    example.write_text(
        '''[openai]\nbase_url="https://api.openai.com/v1"\ntranscription_model="stt"\nagent_model="agent"\ntts_model="tts"\ntts_voice="voice"\ntimeout_s=10\n[runtime]\nptt_key="f9"\nmemory_dir="./memory"\nruntime_dir="./runtime"\nlog_level="INFO"\nlog_content=false\nconfirmation_timeout_s=30\n[audio]\nsample_rate=16000\nchannels=1\n[board]\nenabled=false\nurl="http://127.0.0.1:8794"\n[visualizer]\nenabled=false\nurl="http://127.0.0.1:8790"\n''',
        encoding="utf-8",
    )
    config = AppConfig.load(example)
    report = await run_health_checks(config, recorder=HealthyRecorder())
    third_party = next(c for c in report.checks if c.name == "third_party")
    assert third_party.status == "disabled"
    assert report.status == "ok"

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.config import AppConfig
from jarvis.domain.errors import ConfigurationError


def config_text(
    board_url="http://127.0.0.1:8794",
    visualizer_url="http://localhost:8790",
    openai_base_url="https://api.openai.com/v1",
):
    return f'''
[openai]
base_url = "{openai_base_url}"
transcription_model = "stt"
agent_model = "agent"
tts_model = "tts"
tts_voice = "voice"
timeout_s = 10

[runtime]
ptt_key = "f9"
memory_dir = "./memory"
runtime_dir = "./runtime"
log_level = "INFO"
log_content = false
confirmation_timeout_s = 30

[audio]
sample_rate = 16000
channels = 1

[board]
enabled = true
url = "{board_url}"

[visualizer]
enabled = true
url = "{visualizer_url}"
'''


def test_config_accepts_loopback_and_models_are_configurable(tmp_path, monkeypatch):
    path = tmp_path / "jarvis.toml"
    path.write_text(config_text(), encoding="utf-8")
    monkeypatch.setenv("OPENAI_AGENT_MODEL", "agent-override")
    cfg = AppConfig.load(path)
    assert cfg.openai.agent_model == "agent-override"
    assert cfg.board.url == "http://127.0.0.1:8794"


@pytest.mark.parametrize("bad", ["https://127.0.0.1:8794", "http://192.168.1.3:8794", "http://example.com"])
def test_component_urls_are_strict_loopback(tmp_path, bad):
    path = tmp_path / "jarvis.toml"
    path.write_text(config_text(board_url=bad), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        AppConfig.load(path)


def test_remote_openai_base_url_must_use_https(tmp_path):
    path = tmp_path / "jarvis.toml"
    path.write_text(config_text(openai_base_url="http://api.example.com/v1"), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="HTTPS"):
        AppConfig.load(path)


def test_loopback_http_openai_base_url_is_allowed_for_local_test_proxy(tmp_path):
    path = tmp_path / "jarvis.toml"
    path.write_text(config_text(openai_base_url="http://127.0.0.1:9000/v1"), encoding="utf-8")
    cfg = AppConfig.load(path)
    assert cfg.openai.base_url == "http://127.0.0.1:9000/v1"

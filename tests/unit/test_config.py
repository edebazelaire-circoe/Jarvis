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


# ---------------------------------------------------------------------------
# Délai d'activité utile de la voix v0.2
# ---------------------------------------------------------------------------


def _v2_settings(tmp_path, monkeypatch, timeout: str | None):
    from jarvis.v2_config import V2Settings

    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))
    if timeout is None:
        monkeypatch.delenv("JARVIS_ACTIVE_TIMEOUT_S", raising=False)
    else:
        monkeypatch.setenv("JARVIS_ACTIVE_TIMEOUT_S", timeout)
    return V2Settings.load()


@pytest.mark.parametrize("raw, expected", [(None, 90.0), ("0", 0.0), ("5", 5.0), ("120", 120.0)])
def test_active_timeout_accepts_zero_as_never(tmp_path, monkeypatch, raw, expected):
    assert _v2_settings(tmp_path, monkeypatch, raw).active_timeout_s == expected


@pytest.mark.parametrize("raw", ["3", "4.9", "-1", "abc", "inf"])
def test_active_timeout_rejects_negative_short_and_invalid_values(tmp_path, monkeypatch, raw):
    with pytest.raises(ConfigurationError, match="JARVIS_ACTIVE_TIMEOUT_S"):
        _v2_settings(tmp_path, monkeypatch, raw)


@pytest.mark.parametrize(
    "stored, expected",
    [
        ({}, 45.0),
        ({"active_timeout_s": ""}, 45.0),
        ({"active_timeout_s": "0"}, 0.0),
        ({"active_timeout_s": 0}, 0.0),
        ({"active_timeout_s": "120"}, 120.0),
        # Écrites à la main : Voice démarre quand même, sur la valeur de l'environnement.
        ({"active_timeout_s": "3"}, 45.0),
        ({"active_timeout_s": "-1"}, 45.0),
        ({"active_timeout_s": "abc"}, 45.0),
    ],
)
def test_voice_reads_the_settings_timeout_and_falls_back_on_invalid_values(stored, expected):
    from jarvis.app import _active_timeout_from

    assert _active_timeout_from(stored, 45.0) == expected


# --- racine mémoire unique (handoff mémoire, Slice 02) --------------------------------------------------------
def default_memory_config(tmp_path):
    path = tmp_path / "jarvis.toml"
    path.write_text(config_text().replace('memory_dir = "./memory"\n', ""), encoding="utf-8")
    return path


def test_memory_dir_defaults_to_the_data_root_not_the_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path / "root"))
    monkeypatch.delenv("JARVIS_MEMORY_DIR", raising=False)
    monkeypatch.setattr("jarvis.config.LEGACY_DATA_ROOT", tmp_path / "no-legacy")
    cfg = AppConfig.load(default_memory_config(tmp_path))
    assert cfg.runtime.memory_dir == (tmp_path / "root" / "memory").resolve()


def test_explicit_memory_dir_wins_and_adopts_nothing(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    (legacy / "memory").mkdir(parents=True)
    (legacy / "memory" / "a.md").write_text("# A", encoding="utf-8")
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path / "root"))
    monkeypatch.delenv("JARVIS_MEMORY_DIR", raising=False)
    monkeypatch.setattr("jarvis.config.LEGACY_DATA_ROOT", legacy)
    path = tmp_path / "jarvis.toml"
    path.write_text(config_text(), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert AppConfig.load(path).runtime.memory_dir == (tmp_path / "memory").resolve()
    monkeypatch.setenv("JARVIS_MEMORY_DIR", str(tmp_path / "env-memory"))
    assert AppConfig.load(path).runtime.memory_dir == (tmp_path / "env-memory").resolve()
    assert not (tmp_path / "root").exists()


def test_default_memory_dir_adopts_the_legacy_folder_by_copy_only_and_once(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    (legacy / "memory" / "notes").mkdir(parents=True)
    (legacy / "memory" / "notes" / "a.md").write_text("# A\n\nun", encoding="utf-8")
    (legacy / "memory" / "Jarvis-V1.md").write_text("# versionné", encoding="utf-8")
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path / "root"))
    monkeypatch.delenv("JARVIS_MEMORY_DIR", raising=False)
    monkeypatch.setattr("jarvis.config.LEGACY_DATA_ROOT", legacy)
    path = default_memory_config(tmp_path)
    memory = AppConfig.load(path).runtime.memory_dir
    assert (memory / "notes" / "a.md").read_text(encoding="utf-8") == "# A\n\nun"
    assert not (memory / "Jarvis-V1.md").exists()
    assert (legacy / "memory" / "notes" / "a.md").exists() and (legacy / "memory" / "Jarvis-V1.md").exists()
    (memory / "notes" / "a.md").unlink()
    assert AppConfig.load(path).runtime.memory_dir == memory
    assert not (memory / "notes" / "a.md").exists(), "a second load never copies again"

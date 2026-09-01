from pathlib import Path
import json

import scripts.dev_start as launcher
from scripts.dev_start import _without_provider_secrets


def test_optional_ui_environment_drops_provider_and_board_secrets():
    source = {
        "OPENAI_API_KEY": "provider-secret",
        "JARVIS_BOARD_TOKEN": "board-secret",
        "PATH": "/usr/bin",
        "JARVIS_LOG_LEVEL": "INFO",
    }
    clean = _without_provider_secrets(source)
    assert "OPENAI_API_KEY" not in clean
    assert "JARVIS_BOARD_TOKEN" not in clean
    assert clean["PATH"] == "/usr/bin"
    assert source["OPENAI_API_KEY"] == "provider-secret"


def test_generated_ui_configs_follow_jarvis_paths_and_ports(tmp_path, monkeypatch):
    root = tmp_path / "project"
    third_party = root / "third_party"
    (third_party / "barehands").mkdir(parents=True)
    (third_party / "ai-visualizer").mkdir(parents=True)
    memory = tmp_path / "custom-memory"
    runtime = tmp_path / "custom-runtime"
    monkeypatch.setattr(launcher, "ROOT", root)
    monkeypatch.setattr(launcher, "THIRD_PARTY", third_party)

    launcher._write_runtime_configs(
        board=True,
        visualizer=True,
        memory_dir=memory,
        runtime_dir=runtime,
        board_port=8894,
        visualizer_port=8890,
    )

    board = json.loads((third_party / "barehands" / "barehands.json").read_text(encoding="utf-8"))
    visualizer = json.loads(
        (third_party / "ai-visualizer" / "ai-visualizer.json").read_text(encoding="utf-8")
    )
    assert board["port"] == 8894
    assert board["orbs"][0]["path"] == str(memory.resolve())
    assert visualizer["port"] == 8890
    assert visualizer["bus_dir"] == str(runtime.resolve())


def test_existing_barehands_config_is_resynced_without_erasing_custom_orbs(tmp_path, monkeypatch):
    root = tmp_path / "project"
    third_party = root / "third_party"
    barehands = third_party / "barehands"
    barehands.mkdir(parents=True)
    memory = tmp_path / "new-memory"
    runtime = tmp_path / "runtime"
    stale = {
        "name": "CUSTOM NAME",
        "port": 8794,
        "state_timeout_s": 42,
        "orbs": [
            {"title": "Memory", "path": "/old/path", "kind": "notes"},
            {"title": "Research", "path": "/research", "kind": "notes"},
            {"title": "My Props", "path": "/props", "kind": "media"},
        ],
    }
    (barehands / "barehands.json").write_text(json.dumps(stale), encoding="utf-8")
    monkeypatch.setattr(launcher, "ROOT", root)
    monkeypatch.setattr(launcher, "THIRD_PARTY", third_party)

    launcher._write_runtime_configs(
        board=True,
        visualizer=False,
        memory_dir=memory,
        runtime_dir=runtime,
        board_port=9994,
        visualizer_port=9990,
    )

    updated = json.loads((barehands / "barehands.json").read_text(encoding="utf-8"))
    assert updated["name"] == "CUSTOM NAME"
    assert updated["state_timeout_s"] == 42
    assert updated["port"] == 9994
    memory_orbs = [orb for orb in updated["orbs"] if orb.get("title") == "Memory"]
    assert len(memory_orbs) == 1
    assert memory_orbs[0]["path"] == str(memory.resolve())
    assert {orb.get("title") for orb in updated["orbs"]} >= {"Research", "My Props"}
    assert next(orb for orb in updated["orbs"] if orb.get("title") == "My Props")["path"] == "/props"


def test_invalid_existing_barehands_config_fails_closed(tmp_path, monkeypatch):
    root = tmp_path / "project"
    third_party = root / "third_party"
    barehands = third_party / "barehands"
    barehands.mkdir(parents=True)
    (barehands / "barehands.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(launcher, "ROOT", root)
    monkeypatch.setattr(launcher, "THIRD_PARTY", third_party)

    import pytest
    with pytest.raises(ValueError, match="invalid Barehands config"):
        launcher._write_runtime_configs(
            board=True,
            visualizer=False,
            memory_dir=tmp_path / "memory",
            runtime_dir=tmp_path / "runtime",
            board_port=8794,
            visualizer_port=8790,
        )

"""Slice 09 (jarvis-wake-word, Issue 003) - `scripts/check_wake_word_disabled.py`.

Le script compose le mot d'éveil de SIMPLE avec le réglage `enabled=false` dans un
runtime temporaire et un FAUX `sounddevice`, puis lit le registre des propriétaires
du micro. Il ne regarde pas le JARVIS vivant (voir la fiche HV-WAKEWORD-MIC-01-i).
Aucun vrai micro n'est ouvert ici : le faux module est installé par le script, et
ces tests vérifient qu'il est retiré ensuite.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from jarvis.audio import input_ownership

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_wake_word_disabled.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("check_wake_word_disabled_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def clean_registry():
    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


@pytest.fixture
def tool():
    return load_tool()


def test_with_the_switch_off_no_stream_is_opened_and_the_owner_count_is_zero(tool, capsys):
    assert tool.main([]) == 0
    output = capsys.readouterr().out
    assert "input_ownership" in output
    assert output.count("propriétaires du micro : 0") >= 3
    assert "tentatives d'ouverture : 0" in output


def test_the_default_settings_are_the_disabled_ones(tool):
    from jarvis.runtime import wake_word_settings

    assert wake_word_settings.load({}).enabled is False
    results = tool.run_checks()
    assert [r["scenario"] for r in results if r["expect_open"] is False]
    assert all(r["owners"] == 0 and r["open_attempts"] == 0 for r in results if r["expect_open"] is False)


def test_the_positive_control_proves_the_count_can_move(tool):
    control = [r for r in tool.run_checks() if r["expect_open"] is True]
    assert len(control) == 1
    assert control[0]["owners"] == 1 and control[0]["open_attempts"] == 1
    assert control[0]["owner_labels"] == ["wakeword_openwakeword"]


def test_a_stream_left_open_makes_the_check_exit_non_zero(tool, monkeypatch, capsys):
    async def leaky(block, access_key):  # noqa: ANN001
        import sounddevice as sd  # le faux module, installé par le script

        stream = sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", callback=lambda *a: None)
        input_ownership.register_input_stream("wakeword_openwakeword", stream)
        return []

    monkeypatch.setattr(tool, "_compose_and_start", leaky)
    assert tool.main([]) == 1
    assert "DÉFAUT" in capsys.readouterr().out


def test_the_fake_sound_device_is_removed_afterwards_and_the_real_one_never_imported(tool):
    sentinel = object()
    sys.modules["sounddevice"] = sentinel
    try:
        tool.run_checks()
        assert sys.modules["sounddevice"] is sentinel
    finally:
        sys.modules.pop("sounddevice", None)
    tool.run_checks()
    assert "sounddevice" not in sys.modules


def test_json_output_and_the_stated_limit(tool, capsys):
    assert tool.main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True and report["checks"]
    assert "JARVIS vivant" in report["limit"]
    assert tool.main([]) == 0
    assert "ne regarde pas le JARVIS vivant" in capsys.readouterr().out


def test_the_script_names_no_personal_path_and_uses_a_temporary_runtime(tool, capsys):
    assert tool.main([]) == 0
    output = capsys.readouterr().out
    assert str(Path.home()) not in output and str(ROOT) not in output


def test_the_script_never_imports_a_real_audio_library():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"sounddevice", "pvporcupine", "pyaudio", "openwakeword", "onnxruntime"}), imported


# -- Rework QA : un scénario éteint EXIGE zéro détecteur composé -------------------------------


def _mutant_selection_without_the_enabled_condition():
    """`openwakeword_engine_selection` privée de `enabled is not True` (le mutant M10)."""

    from jarvis.adapters import wakeword_openwakeword
    from jarvis.runtime import presentation_runtime, wake_word_settings

    def mutant(block, *, model_dir, journal):
        if block is None or getattr(block, "provider", None) != wake_word_settings.PROVIDER_OPENWAKEWORD:
            return None
        factory = wakeword_openwakeword.openwakeword_engine_factory(
            keyword=block.keyword, sensitivity=block.sensitivity, cooldown_ms=block.cooldown_ms,
            model_dir=model_dir, journal=journal,
        )
        return factory, str(block.keyword)

    assert presentation_runtime.openwakeword_engine_selection is not mutant
    return mutant


def _install_fake_scorer(monkeypatch):
    """Le paquet openwakeword « présent » : le moteur se construit et le flux s'ouvre."""

    from jarvis.adapters import wakeword_openwakeword as oww

    class Scorer:
        def score(self, pcm):  # noqa: ANN001
            return 0.0

        def close(self):
            return None

    monkeypatch.setattr(oww, "_load_scorer", lambda spec, model_dir: Scorer())


def test_the_mutant_without_the_enabled_condition_turns_the_check_red_with_the_package_absent(
    tool, monkeypatch, capsys
):
    from jarvis.runtime import presentation_runtime

    # Sans le paquet : le moteur échoue avant d'ouvrir le flux, le compte de flux reste 0.
    monkeypatch.setattr(
        presentation_runtime, "openwakeword_engine_selection",
        _mutant_selection_without_the_enabled_condition(),
    )
    results = tool.run_checks()
    bad = [r for r in results if not r["ok"]]
    assert bad, "le mutant doit être vu"
    assert all(r["owners"] == 0 and r["open_attempts"] == 0 for r in bad)
    assert all(r["detectors_composed"] >= 1 for r in bad)
    assert tool.main([]) == 1
    assert "DÉFAUT" in capsys.readouterr().out


def test_the_mutant_without_the_enabled_condition_turns_the_check_red_with_the_package_present(
    tool, monkeypatch
):
    from jarvis.runtime import presentation_runtime

    _install_fake_scorer(monkeypatch)
    monkeypatch.setattr(
        presentation_runtime, "openwakeword_engine_selection",
        _mutant_selection_without_the_enabled_condition(),
    )
    assert tool.main([]) == 1
    assert any(not r["ok"] for r in tool.run_checks())


def test_a_disabled_scenario_with_a_composed_detector_is_a_defect_even_with_zero_owners(tool, monkeypatch):
    async def composes_but_opens_nothing(block, access_key):  # noqa: ANN001
        return [object()]

    monkeypatch.setattr(tool, "_compose_and_start", composes_but_opens_nothing)
    results = tool.run_checks()
    simple_off = [r for r in results if r["surface"] == "SIMPLE" and not r["expect_open"] and not r["by_design"]]
    assert simple_off and all(r["owners"] == 0 and r["open_attempts"] == 0 for r in simple_off)
    assert all(r["detectors_composed"] == 1 and r["ok"] is False for r in simple_off)


def test_the_three_disabled_settings_are_checked_on_both_surfaces_and_compose_nothing(tool):
    results = tool.run_checks()
    for surface in ("SIMPLE", "PRESENTATION"):
        rows = [r for r in results if r["surface"] == surface and not r["expect_open"] and not r["by_design"]]
        assert len(rows) == 3, surface
        assert all(r["detectors_composed"] == 0 and r["owners"] == 0 and r["open_attempts"] == 0 for r in rows)
        assert all(r["ok"] for r in rows)
    assert any("openwakeword" in r["scenario"] for r in results if r["surface"] == "PRESENTATION")


def test_the_fake_picovoice_key_scenario_composes_porcupine_by_design_and_says_so(tool, capsys):
    results = tool.run_checks()
    keyed = [r for r in results if r["by_design"]]
    assert len(keyed) == 1
    assert keyed[0]["detector_types"] == ["PorcupineWakeWordBackend"]
    assert keyed[0]["owners"] == 0 and keyed[0]["open_attempts"] == 0 and keyed[0]["ok"] is True
    assert "clé Picovoice" in keyed[0]["scenario"]
    assert "par conception" in tool.LIMIT and "sans clé" in tool.LIMIT
    assert tool.main([]) == 0
    assert "par conception" in capsys.readouterr().out

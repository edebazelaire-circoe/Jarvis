"""Slice 05b (jarvis-presentation-edition-v1-2, HD-V12-01) - le mot de réveil d'un profil vierge selon le poste.

Trois cas, distingués par une seule question (`wake_word_install.installed_engine_ready`) :

- **produit installé + moteur présent** (build interne : openwakeword et onnxruntime importables, trois modèles
  vérifiés dans le paquet) : un bloc `wake_word` absent vaut « openWakeWord armé, hey_jarvis » ; l'utilisateur le
  désactive par les Réglages et son choix écrit fait foi ;
- **produit installé sans moteur** (build de production) : défauts sûrs, F9 seul ;
- **checkout de développement** (édition `full` du poste du développeur) : jamais un produit installé, donc
  `DEFAULT_ENABLED = False` reste la règle.

Aucun micro, aucun `openwakeword`, aucun `onnxruntime` n'est importé ici.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from jarvis import private_runtime as PR
from jarvis.adapters import wakeword_model_catalog as catalog
from jarvis.adapters.wakeword_own_stream import OwnStreamWakeWordBackend
from jarvis.installation import PRODUCT_MARKER, marker_payload
from jarvis.runtime import simple_wake_word, voice_lifecycle, wake_word_install
from jarvis.runtime import wake_word_settings as wws

ready = wake_word_install.installed_engine_ready.__wrapped__  # sans le cache par processus


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """Un paquet installé (marqueur dans `app/`) dont `models/wake-word` porte trois petits modèles épinglés."""

    root = tmp_path / "Jarvis"
    (root / "app").mkdir(parents=True)
    (root / "app" / PRODUCT_MARKER).write_text(json.dumps(marker_payload()), encoding="utf-8")
    layout = PR.layout_for(root / "app")
    models = layout.wake_models_dir
    models.mkdir(parents=True)
    specs = []
    for key, filename in (("melspectrogram", "melspectrogram.onnx"), ("embedding", "embedding_model.onnx"),
                          ("hey_jarvis", "hey_jarvis_v0.1.onnx")):
        data = f"model {key}".encode()
        (models / filename).write_bytes(data)
        specs.append(catalog.WakeModelSpec(key=key, filename=filename, sha256=hashlib.sha256(data).hexdigest(),
                                           size=len(data), role=key))
    monkeypatch.setattr(PR, "package_layout", lambda: layout)
    monkeypatch.setattr(catalog, "MODELS", tuple(specs))
    monkeypatch.setattr(wake_word_install, "engine_modules_present", lambda: True)
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path / "elsewhere"))
    return layout


@pytest.fixture
def engine_ready(monkeypatch):
    def set_ready(value: bool) -> None:
        monkeypatch.setattr(wake_word_install, "installed_engine_ready", lambda: value)
    return set_ready


# ---------------------------------------------------------------------- la condition


def test_the_development_checkout_is_never_an_installed_engine():
    assert PR.package_layout() is None, "ce test tourne depuis un checkout, sans marqueur produit"
    assert ready() is False
    assert wws.DEFAULT_ENABLED is False
    assert wws.load({}) == wws.defaults() and wws.load({}).enabled is False


def test_an_installed_product_with_its_bundled_engine_is_ready(installed):
    assert catalog.bundled_model_dir() == installed.wake_models_dir
    # Le paquet fait foi, même si JARVIS_RUNTIME_DIR désigne un autre dossier.
    assert catalog.default_model_dir() == installed.wake_models_dir
    assert wake_word_install.destination() == "dossier du programme : models/wake-word"
    assert ready() is True


def test_an_installed_product_without_the_wake_modules_is_not_ready(installed, monkeypatch):
    monkeypatch.setattr(wake_word_install, "engine_modules_present", lambda: False)
    assert ready() is False


@pytest.mark.parametrize("damage", ["missing", "altered"])
def test_an_installed_product_with_a_missing_or_altered_model_is_not_ready(installed, damage):
    target = installed.wake_models_dir / "hey_jarvis_v0.1.onnx"
    if damage == "missing":
        target.unlink()
    else:
        target.write_bytes(b"model hey_jarviX")
    assert ready() is False


def test_a_production_package_has_no_bundled_models(installed):
    for path in installed.wake_models_dir.iterdir():
        path.unlink()
    installed.wake_models_dir.rmdir()
    assert catalog.bundled_model_dir() is None
    assert ready() is False


def test_the_bundled_install_command_says_there_is_nothing_to_install():
    refused = wake_word_install.install_refusal(installed=True, edition="presentation", bundled=True)
    assert refused.startswith(wake_word_install.INSTALL_REFUSED) and "rien à installer" in refused
    assert "n'est pas livré" in wake_word_install.install_refusal(installed=True, edition="presentation")
    assert wake_word_install.install_refusal(installed=False, edition="full", bundled=True) is None


# ---------------------------------------------------------------------- le défaut du profil vierge


def test_a_blank_profile_arms_hey_jarvis_when_the_installed_engine_is_present(engine_ready):
    engine_ready(True)
    current = wws.load({})
    assert (current.enabled, current.provider, current.keyword) == (True, "openwakeword", "hey_jarvis")
    view = wws.describe({})
    assert view["enabled"] is True and view["present"] is False and "actif par défaut" in view["state"]


def test_the_user_can_turn_the_default_off_and_the_written_choice_wins(engine_ready):
    engine_ready(True)
    settings: dict = {}
    wws.apply(settings, {"enabled": False})
    assert settings["wake_word"]["enabled"] is False and settings["wake_word"]["provider"] == "openwakeword"
    assert wws.load(settings).enabled is False


def test_an_unreadable_block_still_gives_the_safe_defaults(engine_ready):
    engine_ready(True)
    assert wws.load({"wake_word": "abîmé"}).enabled is False
    assert wws.load({"wake_word": {"schema_version": 1, "enabled": "oui"}}).enabled is False


def test_without_the_engine_a_blank_profile_keeps_f9_only(engine_ready):
    engine_ready(False)
    assert wws.load({}) == wws.defaults()
    wake = voice_lifecycle.wake_engine({})
    assert wake["configured"] is False and "F9" in wake["message"]
    assert simple_wake_word.simple_wake_backends(block=wws.load({}), access_key="", keyword="jarvis", device=None) == []


def test_the_armed_default_reaches_the_voice_status_and_the_sleep_detector(engine_ready, monkeypatch):
    engine_ready(True)
    monkeypatch.setattr(wake_word_install, "package_installed", lambda: True)
    monkeypatch.setattr(wake_word_install, "read_states", lambda: [
        wake_word_install.ModelState(spec, "verified", None) for spec in catalog.MODELS])
    wake = voice_lifecycle.wake_engine({})
    assert (wake["configured"], wake["provider"], wake["keyword"], wake["available"]) == (True, "openwakeword", "hey_jarvis", True)
    backends = simple_wake_word.simple_wake_backends(block=wws.load({}), access_key="", keyword="jarvis", device=None)
    assert len(backends) == 1 and isinstance(backends[0], OwnStreamWakeWordBackend)


def test_an_installed_engine_whose_models_went_missing_is_said_not_silent(engine_ready, monkeypatch):
    """Le défaut armé suit le moteur au démarrage ; si les modèles disparaissent ensuite, l'état le dit."""

    engine_ready(True)
    monkeypatch.setattr(wake_word_install, "package_installed", lambda: True)
    monkeypatch.setattr(wake_word_install, "read_states", lambda: [
        wake_word_install.ModelState(spec, "missing", "wake_model_missing") for spec in catalog.MODELS])
    wake = voice_lifecycle.wake_engine({})
    assert wake["available"] is False and wake["code"] == "wake_model_missing"


def test_readiness_is_read_once_per_process():
    assert hasattr(wake_word_install.installed_engine_ready, "cache_clear")

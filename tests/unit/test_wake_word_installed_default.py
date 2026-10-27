"""Slice 05b (jarvis-presentation-edition-v1-2, HD-V12-01) - le mot de réveil d'un profil vierge selon le poste.

Trois cas, distingués par une seule question (`wake_word_install.installed_build_ships_engine`) :

- **produit installé dont le paquet livre le moteur** (build interne : marqueur produit + manifeste avec un bloc
  `models.wake_word`) : un bloc `wake_word` absent vaut « openWakeWord armé, hey_jarvis » ; l'utilisateur le
  désactive par les Réglages et son choix écrit fait foi. Si un fichier du moteur manque ensuite, le réglage reste
  activé et l'état dit pourquoi il n'écoute pas (QA S05b MA1) ;
- **produit installé de production** (manifeste sans `models`) : défauts sûrs, F9 seul ;
- **checkout de développement** (édition `full` du poste du développeur) : pas de marqueur produit, donc jamais armé,
  même avec le moteur et des modèles vérifiés présents (`DEFAULT_ENABLED = False` reste la règle).

Aucun micro, aucun `openwakeword`, aucun `onnxruntime` n'est importé ici.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from jarvis import private_runtime as PR
from jarvis.adapters import wakeword_model_catalog as catalog
from jarvis.adapters.wakeword_own_stream import OwnStreamWakeWordBackend
from jarvis.domain import product_readiness as readiness
from jarvis.installation import PRODUCT_MARKER, marker_payload
from jarvis.runtime import simple_wake_word, voice_lifecycle, wake_word_install
from jarvis.runtime import wake_word_settings as wws

ships = wake_word_install.installed_build_ships_engine.__wrapped__  # sans le cache par processus


def make_package(root, *, marker: bool = True, models_block: bool = True):
    """Un dossier de paquet : `app/` (+ marqueur), manifeste (+ bloc `models`), trois petits modèles épinglés."""

    (root / "app").mkdir(parents=True)
    if marker:
        (root / "app" / PRODUCT_MARKER).write_text(json.dumps(marker_payload()), encoding="utf-8")
    manifest = {"schema": PR.RUNTIME_MANIFEST_SCHEMA, "schema_version": PR.RUNTIME_MANIFEST_VERSION,
                "product": {"edition": "presentation", "channel": "internal" if models_block else "production"},
                "runtimes": {}, "excluded": []}
    if models_block:
        manifest["models"] = {"root": "models", "tree_sha256": "x", "files": 3, "wake_word": "models/wake-word"}
    (root / PR.RUNTIME_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    models = PR.PackageLayout(root).wake_models_dir
    models.mkdir(parents=True)
    specs = []
    for key, filename in (("melspectrogram", "melspectrogram.onnx"), ("embedding", "embedding_model.onnx"),
                          ("hey_jarvis", "hey_jarvis_v0.1.onnx")):
        data = f"model {key}".encode()
        (models / filename).write_bytes(data)
        specs.append(catalog.WakeModelSpec(key=key, filename=filename, sha256=hashlib.sha256(data).hexdigest(),
                                           size=len(data), role=key))
    return tuple(specs)


@pytest.fixture
def package(tmp_path, monkeypatch):
    """`package(marker=..., models_block=...)` : ce processus devient ce paquet (`package_layout` lu par le marqueur)."""

    def build(**options):
        root = tmp_path / "Jarvis"
        specs = make_package(root, **options)
        monkeypatch.setattr(PR, "package_layout", lambda: PR.layout_for(root / "app"))
        monkeypatch.setattr(catalog, "MODELS", specs)
        monkeypatch.setattr(wake_word_install, "package_installed", lambda: True)  # moteur Python « présent »
        monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path / "elsewhere"))
        return PR.PackageLayout(root)
    return build


@pytest.fixture
def engine_ready(monkeypatch):
    def set_ready(value: bool) -> None:
        monkeypatch.setattr(wake_word_install, "installed_build_ships_engine", lambda: value)
    return set_ready


# ---------------------------------------------------------------------- la condition


def test_the_development_checkout_is_never_an_installed_engine():
    assert PR.package_layout() is None, "ce test tourne depuis un checkout, sans marqueur produit"
    assert ships() is False
    assert wws.DEFAULT_ENABLED is False
    assert wws.load({}) == wws.defaults() and wws.load({}).enabled is False


def test_without_the_product_marker_engine_and_verified_models_never_arm_the_default(package, monkeypatch):
    """QA S05b m2 : le marqueur produit, et lui seul, sépare le checkout du produit installé."""

    layout = package(marker=False)
    monkeypatch.setattr(catalog, "bundled_model_dir", lambda: layout.wake_models_dir)  # modèles vérifiés « présents »
    assert PR.package_layout() is None
    assert all(state.state == "verified" for state in wake_word_install.read_states())
    assert wake_word_install.package_installed() is True
    assert ships() is False
    monkeypatch.setattr(wake_word_install, "installed_build_ships_engine", ships)
    assert wws.load({}).enabled is False


def test_the_same_package_with_its_marker_arms_the_default(package):
    layout = package(marker=True)
    assert catalog.bundled_model_dir() == layout.wake_models_dir
    # Le paquet fait foi, même si JARVIS_RUNTIME_DIR désigne un autre dossier.
    assert catalog.default_model_dir() == layout.wake_models_dir
    assert wake_word_install.destination() == "dossier du programme : models/wake-word"
    assert ships() is True


def test_an_installed_production_package_never_arms_the_default(package):
    package(models_block=False)
    assert ships() is False


def test_an_unreadable_manifest_keeps_the_safe_default(package):
    layout = package()
    layout.manifest_path.write_text("{not json", encoding="utf-8")
    assert ships() is False


@pytest.mark.parametrize("damage, code", [("missing", "wake_model_missing"), ("altered", "wake_model_mismatch"),
                                          ("package", "wake_package_missing")])
def test_a_broken_engine_stays_enabled_and_says_why_it_does_not_listen(package, monkeypatch, damage, code):
    """QA S05b MA1 : au démarrage suivant, un modèle ou le paquet Python manquant ne fait pas retomber en silence sur
    « aucun mot de réveil » : le réglage reste activé, l'état et la préparation disent la panne, F9 reste."""

    layout = package()
    target = layout.wake_models_dir / "hey_jarvis_v0.1.onnx"
    if damage == "missing":
        target.unlink()
    elif damage == "altered":
        target.write_bytes(b"model hey_jarviX")
    else:
        monkeypatch.setattr(wake_word_install, "package_installed", lambda: False)
    assert ships() is True
    monkeypatch.setattr(wake_word_install, "installed_build_ships_engine", ships)
    current = wws.load({})
    assert (current.enabled, current.provider) == (True, "openwakeword")
    wake = voice_lifecycle.wake_engine({})
    assert (wake["configured"], wake["available"], wake["code"]) == (True, False, code)
    assert "F9" in wake["message"] and "Aucun mot de réveil" not in wake["message"]
    view = voice_lifecycle.project(preference="sleep", voice_online=True, runtime_state="background", launcher=None,
                                   key=voice_lifecycle.ProviderKey(True, label="OpenAI"), wake=wake, manual_key="F9")
    assert view["wake"]["manual_armed"] is True and view["wake"]["voice_word"]["armed"] is False
    item = readiness._voice_item(SimpleNamespace(voice=readiness.Probe(value=view)))
    assert item.detail == code and wake["message"] in item.summary and "F9 la réveille" in item.summary


def test_the_bundled_install_command_says_there_is_nothing_to_install():
    refused = wake_word_install.install_refusal(installed=True, edition="presentation", bundled=True)
    assert refused.startswith(wake_word_install.INSTALL_REFUSED) and "rien à installer" in refused
    assert "n'est pas livré" in wake_word_install.install_refusal(installed=True, edition="presentation")
    assert wake_word_install.install_refusal(installed=False, edition="full", bundled=True) is None


# ---------------------------------------------------------------------- le défaut du profil vierge


def test_a_blank_profile_arms_hey_jarvis_when_the_installed_build_ships_the_engine(engine_ready):
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


def test_a_build_without_the_engine_keeps_f9_only_on_a_blank_profile(engine_ready):
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


def test_readiness_is_read_once_per_process():
    assert hasattr(wake_word_install.installed_build_ships_engine, "cache_clear")

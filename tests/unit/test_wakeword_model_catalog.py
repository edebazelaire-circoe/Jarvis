"""Catalogue des modèles openWakeWord : épinglage SHA-256, refus d'un artefact altéré, installation à la demande.

Aucun accès réseau : `urlopen` est remplacé par un faux partout, et une garde
automatique fait échouer tout test qui tenterait d'ouvrir une vraie connexion.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib
import os
from pathlib import Path
import sys
import urllib.request

import pytest

from jarvis.adapters import file_replace
from jarvis.adapters import wakeword_model_catalog as catalog


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.offset = 0

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        end = len(self.payload) if size < 0 else self.offset + size
        block = self.payload[self.offset : end]
        self.offset += len(block)
        return block


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("un test du catalogue a tenté d'ouvrir le réseau")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def fake_spec(payload: bytes, **changes) -> catalog.WakeModelSpec:
    base = catalog.MODELS[0]
    return replace(base, sha256=hashlib.sha256(payload).hexdigest(), size=len(payload), **changes)


def serve(monkeypatch, payload: bytes) -> list[str]:
    urls: list[str] = []

    def fake_urlopen(request, timeout=None):
        urls.append(request.full_url)
        return FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return urls


def spec_for(content: bytes, *, size: int | None = None) -> catalog.WakeModelSpec:
    """Spec dont le SHA-256 est celui de `content` et la taille épinglée `size` (défaut : len(content))."""

    spec = fake_spec(content)
    return spec if size is None else replace(spec, size=size)


def assert_installs_nothing_but(tmp_path, *names: str) -> None:
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(names)


# --- Un contrôle à la fois : chaque artefact altéré n'échoue que sur UN des deux contrôles. ---


def test_a_download_of_the_same_size_but_another_sha256_installs_nothing(tmp_path, monkeypatch):
    expected, altered = b"modele-attendu", b"modele-altere!"
    assert len(expected) == len(altered) and expected != altered  # seul le SHA-256 peut refuser
    serve(monkeypatch, altered)

    with pytest.raises(catalog.WakeModelError) as caught:
        catalog.download_spec(fake_spec(expected), tmp_path)

    assert caught.value.code == "wake_model_mismatch"
    assert_installs_nothing_but(tmp_path)


def test_a_download_shorter_than_the_pinned_size_installs_nothing(tmp_path, monkeypatch):
    short = b"modele"
    spec = spec_for(short, size=len(short) + 8)  # le SHA-256 est celui du contenu reçu : seule la taille refuse
    serve(monkeypatch, short)

    with pytest.raises(catalog.WakeModelError) as caught:
        catalog.download_spec(spec, tmp_path)

    assert caught.value.code == "wake_model_mismatch"
    assert_installs_nothing_but(tmp_path)


def test_a_download_longer_than_the_pinned_size_installs_nothing(tmp_path, monkeypatch):
    long = b"modele-attendu-et-plus"
    spec = spec_for(long, size=len(long) - 8)  # SHA-256 du contenu reçu : seule la taille refuse
    serve(monkeypatch, long)

    with pytest.raises(catalog.WakeModelError) as caught:
        catalog.download_spec(spec, tmp_path)

    assert caught.value.code == "wake_model_mismatch"
    assert_installs_nothing_but(tmp_path)


def test_an_installed_model_of_the_same_size_but_another_sha256_is_refused(tmp_path):
    expected, altered = b"modele-attendu", b"modele-altere!"
    assert len(expected) == len(altered) and expected != altered
    (tmp_path / catalog.MODELS[0].filename).write_bytes(altered)

    with pytest.raises(catalog.WakeModelError) as caught:
        catalog.verify_spec(fake_spec(expected), tmp_path)
    assert caught.value.code == "wake_model_mismatch"


@pytest.mark.parametrize("extra", [-8, 8], ids=["shorter-than-pinned", "longer-than-pinned"])
def test_an_installed_model_of_another_size_is_refused_even_if_its_sha256_matches(tmp_path, extra):
    content = b"modele-attendu"
    spec = spec_for(content, size=len(content) + extra)  # SHA-256 correct : seule la taille refuse
    (tmp_path / spec.filename).write_bytes(content)

    with pytest.raises(catalog.WakeModelError) as caught:
        catalog.verify_spec(spec, tmp_path)
    assert caught.value.code == "wake_model_mismatch"


def test_a_verified_model_is_installed_under_the_runtime_root(tmp_path, monkeypatch):
    payload = b"modele-attendu"
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))
    spec = fake_spec(payload)
    monkeypatch.setattr(catalog, "MODELS", (spec,))
    serve(monkeypatch, payload)

    installed = catalog.ensure_models()

    target = tmp_path / "wake-word" / "models" / spec.filename
    assert installed == {spec.key: target}
    assert target.read_bytes() == payload
    assert catalog.default_model_dir() == target.parent
    assert not list(target.parent.glob("*.part"))


def test_the_default_model_dir_is_the_git_ignored_runtime_folder(monkeypatch):
    monkeypatch.delenv("JARVIS_RUNTIME_DIR", raising=False)
    root = Path(__file__).resolve().parents[2]
    assert catalog.default_model_dir() == root / "runtime" / "wake-word" / "models"
    ignored = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/runtime/" in ignored


def test_an_installed_model_is_not_downloaded_again(tmp_path, monkeypatch):
    payload = b"modele-attendu"
    spec = fake_spec(payload)
    urls = serve(monkeypatch, payload)
    catalog.download_spec(spec, tmp_path)
    catalog.download_spec(spec, tmp_path)
    assert len(urls) == 1


def test_an_altered_installed_model_is_refused_and_left_untouched(tmp_path):
    payload = b"modele-attendu"
    spec = fake_spec(payload)
    (tmp_path / spec.filename).write_bytes(b"modele-altere!")

    with pytest.raises(catalog.WakeModelError) as caught:
        catalog.verify_spec(spec, tmp_path)
    assert caught.value.code == "wake_model_mismatch"

    # `download_spec` sans `force` ne réécrit pas non plus un fichier altéré : il le refuse.
    with pytest.raises(catalog.WakeModelError) as caught:
        catalog.download_spec(spec, tmp_path)
    assert caught.value.code == "wake_model_mismatch"
    assert (tmp_path / spec.filename).read_bytes() == b"modele-altere!"


def test_a_missing_model_is_reported_with_its_own_code(tmp_path):
    with pytest.raises(catalog.WakeModelError) as caught:
        catalog.verify_spec(fake_spec(b"x"), tmp_path)
    assert caught.value.code == "wake_model_missing"


def test_a_truncated_installed_model_is_refused(tmp_path):
    spec = fake_spec(b"modele-attendu")
    (tmp_path / spec.filename).write_bytes(b"modele")
    with pytest.raises(catalog.WakeModelError) as caught:
        catalog.verify_spec(spec, tmp_path)
    assert caught.value.code == "wake_model_mismatch"


def test_a_download_stops_at_the_pinned_size_instead_of_filling_the_disk(tmp_path, monkeypatch):
    spec = replace(catalog.MODELS[0], size=1 << 20)
    response = FakeResponse(bytes(8 << 20))
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=None: response)

    with pytest.raises(catalog.WakeModelError) as caught:
        catalog.download_spec(spec, tmp_path)

    assert caught.value.code == "wake_model_mismatch"
    assert response.offset <= spec.size + (1 << 20)
    assert list(tmp_path.iterdir()) == []


def test_a_failed_network_read_is_a_coded_error_that_installs_nothing(tmp_path, monkeypatch):
    def broken(request, timeout=None):
        raise OSError("réseau coupé")

    monkeypatch.setattr(urllib.request, "urlopen", broken)
    with pytest.raises(catalog.WakeModelError) as caught:
        catalog.download_spec(fake_spec(b"modele-attendu"), tmp_path)
    assert caught.value.code == "wake_model_download_failed"
    assert list(tmp_path.iterdir()) == []


def test_an_install_blocked_by_the_filesystem_is_a_coded_error(tmp_path, monkeypatch):
    payload = b"modele-attendu"
    spec = fake_spec(payload)
    serve(monkeypatch, payload)
    monkeypatch.setattr(file_replace.time, "sleep", lambda seconds: None)

    def locked(source, destination):
        raise PermissionError("verrou")

    monkeypatch.setattr(os, "replace", locked)
    with pytest.raises(catalog.WakeModelError) as caught:
        catalog.download_spec(spec, tmp_path)
    assert caught.value.code == "wake_model_install_failed"
    assert list(tmp_path.iterdir()) == []


def test_ensure_models_verifies_what_is_already_there_without_the_network(tmp_path):
    first = fake_spec(b"un", key="a", filename="a.onnx")
    second = fake_spec(b"deux", key="b", filename="b.onnx")
    (tmp_path / "a.onnx").write_bytes(b"un")
    (tmp_path / "b.onnx").write_bytes(b"deux")
    assert set(catalog.ensure_models(tmp_path, specs=(first, second))) == {"a", "b"}


def test_the_catalog_pins_the_three_models_the_engine_needs():
    assert {spec.key for spec in catalog.MODELS} == {"melspectrogram", "embedding", "hey_jarvis"}
    for spec in catalog.MODELS:
        assert len(spec.sha256) == 64 and set(spec.sha256) <= set("0123456789abcdef")
        assert spec.size > 0
        assert spec.url.startswith("https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/")
        assert spec.url.endswith(spec.filename) and spec.filename.endswith(".onnx")
    assert catalog.find_model("hey_jarvis").filename == "hey_jarvis_v0.1.onnx"
    assert catalog.find_model("inconnu") is None


def test_the_catalog_records_the_license_and_its_source():
    for spec in catalog.MODELS:
        assert spec.license == "CC-BY-NC-SA-4.0"
        assert "github.com/dscripka/openWakeWord" in spec.license_source
        assert "vérifié le 2026-10-07" in spec.license_source
        assert spec.payload()["model_license"] == spec.license


@pytest.mark.parametrize(
    "filename",
    ["", "   ", "../evil.onnx", "..", "a/b.onnx", "a\\b.onnx", "/etc/passwd", "C:\\x.onnx", "C:x.onnx", "a..b.onnx"],
)
def test_a_spec_filename_must_be_a_plain_file_name(filename):
    with pytest.raises(ValueError, match="invalide"):
        replace(catalog.MODELS[0], filename=filename)


def test_the_pinned_filenames_are_plain_file_names():
    for spec in catalog.MODELS:
        assert spec.path(Path("dossier")).parent == Path("dossier")


class _ForbiddenImportFinder:
    """Faux finder : toute tentative d'importer la bibliothèque lourde est enregistrée puis échoue."""

    HEAVY = ("openwakeword", "onnxruntime")

    def __init__(self) -> None:
        self.attempts: list[str] = []

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in self.HEAVY:
            self.attempts.append(name)
            raise ImportError(f"import interdit de {name} par le catalogue")
        return None


def test_importing_and_using_the_catalog_never_imports_the_heavy_libraries(tmp_path, monkeypatch):
    # Discriminant même sans l'extra installé : un `import openwakeword` (ou onnxruntime)
    # au niveau module ou dans une fonction du catalogue est capté par le faux finder.
    finder = _ForbiddenImportFinder()
    for name in list(sys.modules):
        if name.split(".")[0] in finder.HEAVY:
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])

    importlib.reload(catalog)  # l'import du module doit réussir et ne rien tenter
    assert finder.attempts == []

    content = b"modele-attendu"
    spec = replace(catalog.MODELS[0], sha256=hashlib.sha256(content).hexdigest(), size=len(content))
    serve(monkeypatch, content)
    catalog.download_spec(spec, tmp_path)
    catalog.verify_spec(spec, tmp_path)
    catalog.find_model("hey_jarvis")
    catalog.default_model_dir()
    assert finder.attempts == []
    assert not any(name.split(".")[0] in finder.HEAVY for name in sys.modules)


def test_no_network_is_touched_at_import_or_by_the_tests():
    # La garde automatique fait échouer le moindre `urlopen` ; recharger le module
    # (l'import) ne doit donc rien ouvrir, ni importer openwakeword ou onnxruntime.
    before = {name for name in ("openwakeword", "onnxruntime") if name in sys.modules}
    importlib.reload(catalog)
    after = {name for name in ("openwakeword", "onnxruntime") if name in sys.modules}
    assert after == before

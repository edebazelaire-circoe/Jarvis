"""Déclaration de la dépendance openWakeWord : facultative, jamais importée au chargement, aucun modèle versionné."""

from __future__ import annotations

from pathlib import Path
import getpass
import subprocess
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "tasks" / "jarvis-wake-word"


def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def names(requirements: list[str]) -> set[str]:
    out = set()
    for requirement in requirements:
        name = requirement
        for separator in "<>=!~[; ":
            name = name.split(separator)[0]
        out.add(name.lower().replace("_", "-"))
    return out


def test_the_wakeword_extra_is_declared_and_optional():
    project = pyproject()
    extra = project["optional-dependencies"]["wakeword"]
    assert "openwakeword" in names(extra)
    assert "onnxruntime" in names(extra)
    for requirement in extra:
        assert "<" in requirement, f"borne haute manquante : {requirement}"
    # Facultative : ni dans les dépendances obligatoires, ni dans l'extra `voice`.
    assert "openwakeword" not in names(project["dependencies"])
    assert "openwakeword" not in names(project["optional-dependencies"]["voice"])
    assert "onnxruntime" not in names(project["optional-dependencies"]["voice"])


def test_importing_jarvis_does_not_import_openwakeword():
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import jarvis\n"
        "import jarvis.adapters.wakeword_shared_pcm\n"
        "import jarvis.adapters.wakeword_model_catalog\n"
        "bad = [m for m in ('openwakeword', 'onnxruntime', 'scipy', 'sklearn') if m in sys.modules]\n"
        "print(bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr


def test_no_model_artifact_is_tracked_by_git():
    try:
        done = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=ROOT, timeout=60)
    except FileNotFoundError:
        pytest.skip("git indisponible")
    if done.returncode != 0:
        pytest.skip("pas un dépôt git")
    tracked = [line for line in done.stdout.splitlines() if line.lower().endswith((".onnx", ".tflite", ".ppn", ".pv"))]
    assert tracked == []


SWEPT = (
    ROOT / "third_party" / "README.md",
    ROOT / "jarvis" / "adapters" / "wakeword_model_catalog.py",
    ROOT / "scripts" / "measure_wakeword_inference.py",
    TASK / "LOG.md",
    TASK / "slices" / "01-feasibility-dependencies" / "SLICE.md",
)


def test_the_notice_the_tooling_and_the_evidence_keep_no_personal_path_or_user_name():
    home = str(Path.home())
    forbidden = {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}
    forbidden.add(Path.home().name)
    try:
        forbidden.add(getpass.getuser())
    except Exception:  # noqa: BLE001 - aucun nom d'utilisateur disponible : le chemin suffit
        pass
    forbidden = {item for item in forbidden if len(item) >= 3}
    for path in SWEPT:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for item in forbidden:
            assert item.lower() not in text.lower(), f"{path.name} contient une identité locale"

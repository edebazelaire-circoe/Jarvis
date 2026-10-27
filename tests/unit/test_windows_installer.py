"""Installeur Windows (presentation-edition-v1 Slice 07, HV-PACKAGE-10) : amorce C# compilée par le .NET Framework de
Windows, paquet zippé déterministe accolé, remorque lisible, refus d'un paquet altéré, extraction réelle silencieuse.

L'essai d'extraction lance l'amorce compilée en mode silencieux vers des dossiers de `tmp_path` et une ruche simulée :
jamais le vrai registre, le vrai menu Démarrer ni `%LOCALAPPDATA%`.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import zipfile

import pytest

from jarvis import private_runtime as PR
from tests.unit.test_product_setup import make_package
from tests.unit.test_windows_packaging import B

pytestmark = pytest.mark.skipif(os.name != "nt", reason="amorce Windows")


def csc_available() -> bool:
    try:
        B.find_csc()
        return True
    except B.BuildError:
        return False


def test_the_stub_source_declares_its_silent_and_injectable_options():
    source = B.STUB_SOURCE.read_text(encoding="utf-8")
    for option in ("--silent", "--target", "--start-menu", "--desktop", "--no-desktop", "--registry-file", "--result", "--log",
                   "--launch"):
        assert f'"{option}"' in source, option
    assert '"JVSETUP1"' in source and "jarvis.product_setup install" in source and "-B -m jarvis launch" in source
    assert "SafeEntry" in source  # aucun nom du zip ne sort du dossier d'extraction


def test_the_payload_zip_is_deterministic_and_carries_the_whole_package(tmp_path):
    package = make_package(tmp_path / "pkg")
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    assert B.zip_package(package, first) == B.zip_package(package, second)
    assert PR.file_sha256(first) == PR.file_sha256(second)
    with zipfile.ZipFile(first) as bundle:
        names = sorted(bundle.namelist())
    assert names == [relative for relative, _path in PR.iter_tree(package)]


def test_a_damaged_package_never_becomes_an_installer(tmp_path):
    package = make_package(tmp_path / "pkg")
    (package / "runtime" / "node" / "node.exe").write_bytes(b"tampered")
    with pytest.raises(B.BuildError, match="paquet altéré"):
        B.command_installer(type("A", (), {"package": str(package), "out": str(tmp_path / "out" / "setup.exe")})())
    assert not (tmp_path / "out" / "setup.exe").exists()


@pytest.mark.skipif(not csc_available(), reason="compilateur C# du .NET Framework absent")
def test_the_installer_is_stub_plus_zip_plus_trailer_and_extracts_for_real(tmp_path):
    package = make_package(tmp_path / "pkg")
    setup = tmp_path / "out" / "JARVIS-Setup.exe"
    assert B.command_installer(type("A", (), {"package": str(package), "out": str(setup)})()) == 0
    offset, length = B.read_trailer(setup)
    with open(setup, "rb") as handle:
        assert handle.read(2) == b"MZ"
        handle.seek(offset)
        payload = handle.read(length)
    zipped = tmp_path / "payload.zip"
    zipped.write_bytes(payload)
    with zipfile.ZipFile(zipped) as bundle:
        assert PR.RUNTIME_MANIFEST in bundle.namelist()

    # Exécution silencieuse réelle : l'amorce extrait le paquet à côté de la cible et lance son Python. Ici le
    # « python.exe » du paquet factice n'est pas exécutable : l'issue doit être un échec DIT (journal, code 1), le
    # dossier d'extraction nettoyé, aucune cible créée.
    target = tmp_path / "Programs" / "CIRCOE" / "Jarvis"
    log = tmp_path / "setup.log"
    done = subprocess.run([str(setup), "/S", "--target", str(target), "--registry-file", str(tmp_path / "hive.json"),
                           "--no-desktop", "--log", str(log)], timeout=120)
    assert done.returncode == 1
    text = log.read_text(encoding="utf-8")
    assert "extraction vers" in text and "ÉCHEC" in text
    assert not target.exists()
    assert not list(target.parent.glob(".jarvis-setup-*"))
    assert not (tmp_path / "hive.json").exists()


ECHO_SOURCE = """using System; using System.IO;
class Echo { static int Main(string[] args) {
  File.WriteAllLines(Environment.GetEnvironmentVariable("JV_ECHO_OUT"), args); return 0; } }
"""


def compile_echo(folder: Path) -> Path:
    """Un « python.exe » qui écrit les arguments reçus (un par ligne) : ce que Python verrait dans `sys.argv`."""

    source, exe = folder / "echo.cs", folder / "echo.exe"
    folder.mkdir(parents=True, exist_ok=True)
    source.write_text(ECHO_SOURCE, encoding="utf-8")
    subprocess.run([str(B.find_csc()), "/nologo", "/target:exe", f"/out:{exe}", str(source)], check=True,
                   capture_output=True, timeout=120)
    return exe


def build_installer(package: Path, out: Path) -> Path:
    assert B.command_installer(type("A", (), {"package": str(package), "out": str(out)})()) == 0
    return out


@pytest.mark.skipif(not csc_available(), reason="compilateur C# du .NET Framework absent")
def test_the_stub_passes_a_target_with_a_trailing_backslash_intact_to_python(tmp_path):
    """Revue m2 / sonde P4 : `"D:\\Apps\\Jarvis\\"` avalait `--progress … --result …` dans un seul argument."""

    echo = compile_echo(tmp_path / "echo")
    setup = build_installer(make_package(tmp_path / "pkg", python_exe=echo.read_bytes()), tmp_path / "out" / "setup.exe")
    target = tmp_path / "Programs with space" / "CIRCOE" / "Jarvis"
    seen = tmp_path / "argv.txt"
    done = subprocess.run([str(setup), "/S", "--target", str(target) + "\\", "--registry-file", str(tmp_path / "hive.json"),
                           "--start-menu", str(tmp_path / "Start Menu") + "\\", "--no-desktop", "--log", str(tmp_path / "s.log")],
                          env={**os.environ, "JV_ECHO_OUT": str(seen)}, timeout=120)
    assert done.returncode == 1  # l'écho ne rend pas d'issue : échec dit
    argv = seen.read_text(encoding="utf-8").splitlines()
    assert argv[:4] == ["-B", "-m", "jarvis.product_setup", "install"]
    pairs = dict(zip(argv[4::2], argv[5::2]))
    assert pairs["--target"] == str(target) and pairs["--start-menu"] == str(tmp_path / "Start Menu")
    assert pairs["--progress"].endswith("progress.jsonl") and pairs["--result"].endswith("result.json")
    assert "--no-desktop" in argv and "--registry-file" in pairs


@pytest.mark.skipif(not csc_available(), reason="compilateur C# du .NET Framework absent")
def test_the_stub_refuses_a_zip_entry_that_leaves_the_extraction_folder(tmp_path):
    """Revue m10 : `SafeEntry` (zip slip) n'était éprouvé par aucun essai."""

    stub = tmp_path / "stub.exe"
    B.compile_stub(stub)
    payload = tmp_path / "evil.zip"
    with zipfile.ZipFile(payload, "w") as bundle:
        bundle.writestr("runtime-manifest.json", "{}")
        bundle.writestr("../../escaped.txt", "pwned")
    setup = tmp_path / "out" / "setup.exe"
    setup.parent.mkdir()
    offset, length = stub.stat().st_size, payload.stat().st_size
    setup.write_bytes(stub.read_bytes() + payload.read_bytes() + B.SETUP_MAGIC + offset.to_bytes(8, "little")
                      + length.to_bytes(8, "little"))
    target = tmp_path / "Programs" / "CIRCOE" / "Jarvis"
    log = tmp_path / "setup.log"
    done = subprocess.run([str(setup), "/S", "--target", str(target), "--registry-file", str(tmp_path / "hive.json"),
                           "--no-desktop", "--log", str(log)], timeout=120)
    assert done.returncode == 1
    assert "nom refusé dans le paquet : ../../escaped.txt" in log.read_text(encoding="utf-8")
    assert not list(tmp_path.rglob("escaped.txt")) and not target.exists()
    assert not list(target.parent.glob(".jarvis-setup-*"))


@pytest.mark.skipif(not csc_available(), reason="compilateur C# du .NET Framework absent")
def test_an_unknown_argument_in_silent_mode_never_opens_a_dialog(tmp_path):
    """QA runtime m3 : `/S --bogus` ouvrait une boîte de dialogue qu'aucune personne ne fermerait (CI, déploiement)."""

    stub = tmp_path / "stub.exe"
    B.compile_stub(stub)
    log = tmp_path / "setup.log"
    done = subprocess.run([str(stub), "/S", "--bogus", "--log", str(log)], timeout=60, capture_output=True)
    assert done.returncode == 2
    assert "argument refusé : argument inconnu : --bogus" in log.read_text(encoding="utf-8")


def test_read_trailer_refuses_a_file_without_payload(tmp_path):
    plain = tmp_path / "plain.exe"
    plain.write_bytes(b"MZ" + b"\0" * 100)
    with pytest.raises(B.BuildError, match="remorque"):
        B.read_trailer(plain)
    bogus = tmp_path / "bogus.exe"
    bogus.write_bytes(b"MZ" + b"\0" * 10 + B.SETUP_MAGIC + (5).to_bytes(8, "little") + (10 ** 9).to_bytes(8, "little"))
    with pytest.raises(B.BuildError, match="incohérente"):
        B.read_trailer(bogus)

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


def test_read_trailer_refuses_a_file_without_payload(tmp_path):
    plain = tmp_path / "plain.exe"
    plain.write_bytes(b"MZ" + b"\0" * 100)
    with pytest.raises(B.BuildError, match="remorque"):
        B.read_trailer(plain)
    bogus = tmp_path / "bogus.exe"
    bogus.write_bytes(b"MZ" + b"\0" * 10 + B.SETUP_MAGIC + (5).to_bytes(8, "little") + (10 ** 9).to_bytes(8, "little"))
    with pytest.raises(B.BuildError, match="incohérente"):
        B.read_trailer(bogus)

"""Liens de dossier pour les tests, sans privilège sur Windows.

Une jonction (`mklink /J`) ne demande aucun droit particulier et `safe_folders.is_link` la reconnaît (point d'analyse) ; un
lien symbolique, lui, exige le mode développeur sous Windows. Ces tests doivent donc tourner partout : on crée une jonction sous
Windows, un lien symbolique ailleurs, et on ne `skip` que si rien n'est possible.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


def make_dir_link(link: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
        if done.returncode != 0:
            pytest.skip(f"mklink /J failed: {done.stdout.strip()} {done.stderr.strip()}")
        return
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation impossible here: {exc}")


def remove_dir_link(link: Path) -> None:
    """Retire le lien lui-même (jamais sa cible)."""

    os.rmdir(link) if os.name == "nt" else os.unlink(link)

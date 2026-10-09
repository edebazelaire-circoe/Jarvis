"""Épreuve RÉELLE d'isolation dans Chrome (Slice 06) : lance `scripts/remotion_isolation_harness.py`.

Ignorée par défaut (2 à 3 minutes, Chrome, Node, un environnement Remotion installé). Pour l'exercer :

    JARVIS_REMOTION_RUNTIME_DIR=<racine privée>/local_capabilities/remotion/runtime pytest tests/unit/test_remotion_isolation_real.py

Le harnais n'utilise qu'une racine de données et un profil Chrome jetables : jamais le JARVIS vivant.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = os.environ.get("JARVIS_REMOTION_RUNTIME_DIR")
CHROME = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe"
pytestmark = pytest.mark.skipif(not RUNTIME or not Path(RUNTIME, "install-record.json").is_file() or not CHROME.is_file() or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR, Chrome and Node")


def test_every_hostile_scene_is_neutralised_in_a_real_browser_and_the_benign_one_renders(tmp_path):
    evidence = tmp_path / "evidence.json"
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "remotion_isolation_harness.py"), "--work-dir", str(tmp_path / "work"),
                           "--runtime-dir", RUNTIME, "--evidence", str(evidence)], capture_output=True, text=True, timeout=900)
    report = json.loads(evidence.read_text(encoding="utf-8")) if evidence.is_file() else {}
    failed = [name for name, check in report.get("checks", {}).items() if not check["ok"]]
    assert done.returncode == 0 and report.get("verdict") == "PASSED", (failed, done.stdout[-400:], done.stderr[-400:])
    assert len(report["checks"]) >= 25 and report["attacker_requests_outside_controls_and_ablations"] == []

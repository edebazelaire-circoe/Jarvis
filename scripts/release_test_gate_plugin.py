"""Greffon pytest de `scripts/release_test_gate.py` : écrit l'issue de chaque test (nodeid, phase, résultat) en JSON.

Chargé par `python -m pytest -p scripts.release_test_gate_plugin` ; le fichier de sortie est `JARVIS_TEST_GATE_REPORT`.
Aucun effet sans cette variable. Le texte des échecs n'est pas copié (seulement nodeid et phase) : le détail reste
dans la sortie de pytest.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_OUTCOMES: dict[str, dict[str, str]] = {}


def pytest_runtest_logreport(report) -> None:
    row = _OUTCOMES.setdefault(report.nodeid, {})
    if report.failed:
        row[report.when] = "failed"
    elif report.skipped:
        row.setdefault(report.when, "skipped")
    elif report.when == "call":
        row["call"] = "passed"


def pytest_collectreport(report) -> None:
    if report.failed:  # an import error of a test file is a failure of that file, never a silent skip
        _OUTCOMES.setdefault(report.nodeid or "<collection>", {})["collect"] = "failed"


def pytest_sessionfinish(session, exitstatus) -> None:
    target = os.environ.get("JARVIS_TEST_GATE_REPORT")
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"exitstatus": int(exitstatus), "tests": _OUTCOMES}, indent=1) + "\n", encoding="utf-8")

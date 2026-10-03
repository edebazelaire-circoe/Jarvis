"""Les preuves committées du handoff prefab-foundation ne gardent aucune identité locale (Slice 09).

Le balayage (`privacy_sweep.py` dans les preuves de la Slice 09) lit ses cibles à l'exécution :
dossier personnel, noms d'utilisateur de la machine, adresses, formes de jeton. Ce test le fait
tourner sur tout le dossier du handoff, et vérifie qu'il voit vraiment chaque catégorie.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "tasks" / "jarvis-scene-window-prefab-foundation"
SWEEP = TASK / "slices" / "09-integration-hardening" / "evidence" / "privacy_sweep.py"

pytestmark = pytest.mark.skipif(not SWEEP.exists(), reason="handoff folder archived elsewhere")


def load():
    spec = importlib.util.spec_from_file_location("prefab_task_privacy_sweep", SWEEP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_committed_evidence_of_the_task_keeps_a_home_path_a_user_name_an_email_or_a_token():
    sweep = load()
    assert sweep.TASK == TASK.resolve()
    assert sweep.sweep() == {}


def test_the_sweep_sees_each_category_it_claims_to_refuse():
    sweep = load()
    home = Path.home()
    assert "<home>" in sweep.findings(f"chemin {home}\\Documents\\x.txt")
    assert "<home>" in sweep.findings(str(home).replace("\\", "\\\\") + "\\\\x")  # forme JSON
    for name in sweep.user_names():
        assert "<user>" in sweep.findings(f"auteur : {name}.")
    assert any(hit.startswith("email") for hit in sweep.findings("écrire à quelqu.un@exemple.org"))
    assert sweep.findings("contact noreply@anthropic.com") == []
    assert "token" in sweep.findings("Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345")
    assert "token" in sweep.findings('{"token": "abcdefghijklmnop1234"}')
    assert sweep.findings("Authorization: Bearer ${token}") == []

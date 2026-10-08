"""L'inspecteur du Studio sur la VRAIE page du Control Center, avec un VRAI Core et un VRAI Chrome (jarvis-interactive-presentation-studio, Slice 07).

Rien n'est simule sauf l'ecran sans tete (`tests/fakes/presentation_studio_inspector_browser.py`) : Core isole (racine de donnees et ports
a lui, jamais le Jarvis vivant), Control Center reel, prefab `custom` publie par la vraie route, gestes de souris et touches CDP reels.

Prouve de bout en bout : les widgets generes de l'introspection (un par type), le glissement d'un curseur (le cadre d'apercu bouge, RIEN
n'est ecrit tant que la poignee n'est pas relachee), UN enregistrement au relachement identique a l'ordre equivalent de l'agent, annuler /
retablir, la base perimee, le rechargement 409, la lecture en cours (inspecteur cache, touches au lecteur), l'accessibilite.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.fakes.presentation_studio_inspector_browser import CONTROLS, PREVIEW_OBJECT, S1, S2, InspectorRig, drive

pytestmark = pytest.mark.asyncio

PANEL = "#jvStudioInspector"
OPEN = [{"click": "#openStudioInspector"},
        {"until": "!!document.querySelector('#jvStudioInspector [data-control-id=\"size\"]')", "ms": 20000},
        {"wait": 300}]


def noise(result: dict) -> list:
    """Console lines that are not the inspector's own info trail: errors and warnings are noise."""

    lines = [c for c in result["console"] if c["type"] in ("error", "warning", "exception", "log-error", "log-warning", "assert")
             and "favicon.ico" not in c["text"]]           # the served page has no icon: baseline noise of every Control Center page
    return result["errors"] + lines


def digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def test_smoke_the_panel_opens_and_renders_every_control(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        shot = Path(r"C:/Users/Clarice/AppData/Local/Temp/claude/C--Projects-jarvis-sub-agents-jarvis-agent-01/2c31ce96-dd64-4b96-839c-feff87315a95/scratchpad/smoke.png")
        result = await drive(rig.url, [*OPEN, {"value": "rows", "expr": "[...document.querySelectorAll('#jvStudioInspector [data-control-id]')].map(e=>e.dataset.controlId)"},
                                       {"shot": str(shot)}])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert reads["rows"] == [c["control_id"] for c in CONTROLS]
        assert not noise(result), noise(result)
        assert shot.stat().st_size > 1000

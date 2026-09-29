"""Alertes attribuées et « Aller au Board » dans un vrai Chrome sans tête (handoff board-session, Slice 07).

La page est celle que `ControlCenter.index` sert ; seul `fetch` est un double
(`_board_alerts_browser.mjs`). On est sur `board_b` ; une alerte `failed` vient
de `default`. Ce que ce fichier épingle :

- la pastille porte la marque « d'ailleurs » et son libellé nomme le Board ;
- la liste nomme le Board de l'alerte et offre « Aller au Board » ;
- le clic passe par la bascule normale (`POST /api/boards/switch
  {board_id}` et rien d'autre), montre son attente sur le bouton, puis ferme
  la liste ; une fois sur `default`, l'alerte reste (globale, non vue) mais
  n'est plus « d'ailleurs » ;
- un refus est dit à côté du bouton ; aucune exception de console.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.unit.test_interaction_mode_hud_browser import _chrome, _served_page

HARNESS = Path(__file__).parent / "_board_alerts_browser.mjs"

OPEN = ("open", "document.querySelector('#bgPills .bgpill').click();'ok'", 700)
GO = ("go", "document.querySelector('#bgPop [data-bg-go]').click();'ok'", 500)
MID = ("mid", "(()=>{const g=document.querySelector('#bgPop [data-bg-go]');"
       "return g?{text:g.textContent,busy:g.getAttribute('aria-busy')}:null})()", 2200)


def _drive(tmp_path: Path, plan: list) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    page = _served_page(tmp_path)
    done = subprocess.run([node, str(HARNESS), str(page), chrome, json.dumps(plan)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_an_alert_from_another_board_is_named_and_leads_there_through_the_switch(tmp_path):
    before, after = _drive(tmp_path, [
        {"width": 1440, "height": 900, "actions": [OPEN]},
        {"width": 1440, "height": 900, "actions": [OPEN, GO, MID, OPEN]},
    ])
    assert before["title"] == "Projet B"
    assert "elsewhere" in before["pill"]["cls"]
    assert before["pill"]["label"] == "Arrière-plan · 1 échec · dont 1 sur « Jarvis »"
    assert before["popOpen"] and before["chip"] == "Board « Jarvis »" and "elsewhere" in before["rowCls"]
    assert before["go"]["text"] == "Aller au Board →" and before["go"]["label"] == "Aller au Board « Jarvis »"
    go = before["go"]["rect"]
    assert 0 <= go["l"] and go["r"] <= 1440 and go["b"] <= 900, "the action is on screen"

    assert after["results"]["mid"] == {"text": "Bascule… 0 s", "busy": "true"}, "the wait is shown on the button"
    assert [b for b in after["bodies"] if b["path"] == "/api/boards/switch"] == [
        {"path": "/api/boards/switch", "body": {"board_id": "default"}}], "the normal switch, only the Board"
    assert after["title"] == "Jarvis"
    assert after["popOpen"], "reopened after the switch: the alert is still there, unread and global"
    assert after["chip"] == "Ce Board · Jarvis" and after["go"] is None
    assert "elsewhere" not in after["pill"]["cls"]
    assert [line for line in after["console"] if line["type"] == "exception"] == []
    assert any("boards.alert_jump_done" in line["text"] for line in after["console"])


def test_a_refused_jump_is_said_next_to_the_button(tmp_path):
    fail = ("fail", "window.__alerts.switchPlan='fail';'ok'", 50)
    seen = _drive(tmp_path, [{"width": 500, "height": 800, "actions": [fail, OPEN, GO]}])[0]
    assert seen["title"] == "Projet B"
    assert seen["note"].startswith("L’agent du Board n’a pas pu démarrer")
    assert seen["go"]["text"] == "Aller au Board →" and seen["go"]["busy"] is None
    pop = seen["popRect"]
    assert pop["l"] >= 0 and pop["r"] <= 500, "the list fits a narrow window"
    assert pop["t"] >= 0 and pop["b"] <= 800, "re-placed after the refusal grew it: its footer stays on screen"
    assert [line for line in seen["console"] if line["type"] == "exception"] == []


def test_the_open_list_follows_its_pill_when_the_pills_are_rewritten(tmp_path):
    """Core tombe sous une liste ouverte : le Board actif devient inconnu, les pastilles sont réécrites
    (plus de marque « d'ailleurs »). La liste doit rester contre la pastille vivante, à l'écran."""

    drop = ("drop", "window.__alerts.dropBoards=true;window.__alerts.switchPlan='fail';'ok'", 2300)
    seen = _drive(tmp_path, [{"width": 1440, "height": 900, "actions": [OPEN, drop, GO]}])[0]
    assert seen["note"].startswith("L’agent du Board n’a pas pu démarrer"), "refused, then re-placed"
    assert "elsewhere" not in seen["pill"]["cls"], "the pills were rewritten"
    assert seen["popOpen"]
    pop = seen["popRect"]
    assert 0 <= pop["l"] and pop["r"] <= 1440 and 0 <= pop["t"] and pop["b"] <= 900, pop

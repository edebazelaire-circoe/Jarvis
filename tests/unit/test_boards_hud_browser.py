"""Le contrôle Boards, mesuré dans un vrai Chrome sans tête (handoff board-session, Slice 06).

La page est celle que `ControlCenter.index` sert ; seul `fetch` est un double
(`_boards_browser.mjs`), si bien que le vrai `refreshStatus` nourrit le vrai
module chaque seconde. Ce que ce fichier épingle, et qu'aucune lecture de la
feuille de style ne prouve :

- le bouton est **cliquable** alors que `.topbar` coupe les événements de
  pointeur (`elementFromPoint`), en haut à droite, sans recouvrir l'état ;
- le panneau s'ouvre sous lui, dans l'écran, **au-dessus** du dock ;
- une bascule suit le serveur (A → B → A), un refus laisse A actif et le dit ;
- `prefers-reduced-motion` arrête la barre d'attente et l'ouverture animée ;
- aucune erreur de console.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from tests.unit.test_interaction_mode_hud_browser import _chrome, _served_page

HARNESS = Path(__file__).parent / "_boards_browser.mjs"

OPEN = ("open", "document.getElementById('boardsButton').click();'ok'", 500)


def _drive(tmp_path: Path, plan: list) -> list:
    import shutil

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    page = _served_page(tmp_path)
    done = subprocess.run([node, str(HARNESS), str(page), chrome, json.dumps(plan)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _overlap(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    return min(a["r"], b["r"]) > max(a["l"], b["l"]) and min(a["b"], b["b"]) > max(a["t"], b["t"])


@pytest.mark.parametrize("width,height", [(1440, 900), (1024, 700), (500, 700)])
def test_the_control_is_clickable_top_right_and_its_panel_stays_on_screen(tmp_path, width, height):
    seen = _drive(tmp_path, [{"width": width, "height": height, "actions": [OPEN]}])[0]
    trigger, state, panel, dock = seen["trigger"], seen["state"], seen["panel"], seen["dock"]
    assert seen["title"] == "Jarvis" and seen["tone"] == "ready"
    assert seen["triggerHit"] is True, "the top bar cuts pointer events; the slot gives them back"
    assert trigger["r"] <= state["l"] and not _overlap(trigger, state)
    assert 0 <= state["l"] - trigger["r"] <= 12, "top-right, right next to the state"
    assert abs(trigger["t"] - state["t"]) <= 2, "same row as the state"
    assert panel is not None and panel["z"] == "36"
    assert panel["t"] >= trigger["b"] and panel["l"] >= 12 and panel["r"] <= width - 12 + 1
    assert panel["b"] <= height
    assert seen["panelHit"] is True, "the open panel is on top of whatever it covers (dock included)"
    assert [row["id"] for row in seen["rows"]] == ["default", "board_b"]
    assert seen["rows"][0]["current"] is True
    assert [line for line in seen["console"] if line["type"] in ("error", "exception")] == [], seen["console"]


def test_switch_a_b_a_follows_the_server_and_a_refusal_keeps_a(tmp_path):
    click_b = ("b", "document.querySelector('[data-board-id=board_b][data-bd-action=switch]').click();'ok'", 1600)
    click_a = ("a", "document.querySelector('[data-board-id=default][data-bd-action=switch]').click();'ok'", 1600)
    fail = ("fail", "window.__boards.switchPlan='fail';'ok'", 50)
    plan = [{"width": 1440, "height": 900, "actions": [
        OPEN, click_b, ("snap_b", "document.getElementById('boardsTitle').textContent", 50),
        OPEN, click_a, ("snap_a", "document.getElementById('boardsTitle').textContent", 50),
        fail, OPEN, click_b,
    ]}]
    seen = _drive(tmp_path, plan)[0]
    assert seen["results"]["snap_b"] == "Projet Atlas — refonte du tableau de bord"
    assert seen["results"]["snap_a"] == "Jarvis"
    assert seen["title"] == "Jarvis", "refused: the server truth stays"
    assert seen["rows"][0] == {"id": "default", "current": True}
    assert seen["note"].startswith("L’agent du Board n’a pas pu démarrer")
    errors = [line for line in seen["console"] if line["type"] in ("exception",)]
    assert errors == []
    assert any("boards.switch_failed" in line["text"] for line in seen["console"])


def test_reduced_motion_stops_the_wait_bar_and_the_opening_animation(tmp_path):
    hang = ("hang", "window.__boards.switchPlan='hang';'ok'", 50)
    click_b = ("b", "document.querySelector('[data-board-id=board_b][data-bd-action=switch]').click();'ok'", 1300)
    normal, reduced = _drive(tmp_path, [
        {"width": 1440, "height": 900, "actions": [hang, OPEN, click_b]},
        {"width": 1440, "height": 900, "reducedMotion": True, "actions": [hang, OPEN, click_b]},
    ])
    assert normal["tone"] == "pending" and normal["sub"].startswith("Bascule · ")
    assert normal["motion"]["sweep"] == "bdSweep" and normal["motion"]["pop"] == "bdPop"
    assert reduced["tone"] == "pending"
    assert reduced["motion"] == {"sweep": "none", "pop": "none"}

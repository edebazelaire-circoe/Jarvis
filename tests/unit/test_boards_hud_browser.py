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

Slice 08 (board-memory-workspace-inspector) : un dernier parcours, sans aucun
double, contre un vrai Core et un vrai Control Center (`CaptureStack`) — créer
un Board « Réunion », changer sa nature, filtrer les archivés, « Inspecter »
ouvre le gestionnaire sur ce Board. Captures dans `JARVIS_S8_EVIDENCE_DIR`.

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


COSMOS = ("cosmos", "window.JarvisThemeAPI.activate('cosmos',{persist:false});'ok'", 600)


@pytest.mark.parametrize("width,height", [(500, 700), (800, 700), (1440, 900)])
def test_in_cosmos_the_dock_never_covers_the_boards_button_nor_the_voice_state(tmp_path, width, height):
    """QA 06/07, point 6 : à 500 px le dock cachait l'état vocal et rognait le bouton de 4 px."""

    seen = _drive(tmp_path, [{"width": width, "height": height, "actions": [COSMOS]}])[0]
    trigger, state, dock = seen["trigger"], seen["state"], seen["dock"]
    assert seen["theme"] == "cosmos"
    assert trigger and state and dock
    assert not _overlap(trigger, dock) and not _overlap(state, dock), (trigger, state, dock)
    assert trigger["l"] >= 0 and trigger["r"] <= width and trigger["w"] >= 60, "whole, not clipped"
    assert state["r"] <= width and state["w"] > 0
    assert seen["triggerHit"] is True


def test_the_active_boards_archive_icon_looks_disabled(tmp_path):
    seen = _drive(tmp_path, [{"width": 1440, "height": 900, "actions": [OPEN]}])[0]
    off = seen["archiveActive"]
    assert off["disabled"] == "true" and off["opacity"] <= 0.3 and "grayscale" in off["filter"]


# ------------------------------------------------------------- navigateur rapide contre la vraie pile (Slice 08)

WORKSPACE_HARNESS = Path(__file__).parent / "_workspace_browser.mjs"

# Une ligne du panneau Boards par son titre ; `window.__s8` garde l'id du Board créé.
_ROW = "[...document.querySelectorAll('#boardsList .bd-row')].find(li=>li.querySelector('.bd-name')&&li.querySelector('.bd-name').textContent===%s)"


def _quick_plan(w) -> dict:
    row = lambda title: _ROW % json.dumps(title)  # noqa: E731
    kind_of = lambda title: f"((({row(title)})||document).querySelector('[data-role=kind]')||{{}}).textContent"  # noqa: E731
    action = lambda title, act: f"({row(title)}).querySelector('[data-bd-action={act}]').click()"  # noqa: E731
    pick = lambda sel, value: (f"(()=>{{const s=document.querySelector({json.dumps(sel)});s.value={json.dumps(value)};"  # noqa: E731
                               "s.dispatchEvent(new Event('change',{bubbles:true}));return true})()")
    wsp_text = "document.getElementById('wspPanel').textContent"
    return {"width": 1440, "height": 900, "steps": [
        {"wait": "(document.getElementById('boardsTitle')||{}).textContent==='Projet B'"},
        {"do": "document.getElementById('boardsButton').click()"},
        {"wait": f"({row('Projet A')})&&({row('Projet B')})"},
        {"get": "list", "expr": "[...document.querySelectorAll('#boardsList .bd-row')].map(li=>({"
                                "title:li.querySelector('.bd-name').textContent,kind:li.querySelector('[data-role=kind]').textContent,"
                                "opened:li.querySelector('[data-role=opened]').textContent,state:li.querySelector('[data-role=state]').textContent,"
                                "active:li.getAttribute('data-active')}))"},
        {"get": "filter", "expr": "document.getElementById('boardsFilter').textContent"},
        {"shot": "01-list.png"},
        # Créer un Board « Réunion ».
        {"do": "(()=>{const i=document.getElementById('boardsCreateTitle');i.value='Point hebdo S8';return true})()"},
        {"do": pick("#boardsCreateKind", "meeting")},
        {"do": "document.getElementById('boardsCreate').click()", "ms": 400},
        {"wait": f"({row('Point hebdo S8')})&&{kind_of('Point hebdo S8')}==='Réunion'"},
        {"do": f"window.__s8=({row('Point hebdo S8')}).getAttribute('data-board-id')"},
        {"get": "created_kind", "expr": kind_of("Point hebdo S8")},
        {"get": "created_focus", "expr": "document.activeElement&&document.activeElement.closest('.bd-row')&&"
                                         "document.activeElement.closest('.bd-row').getAttribute('data-board-id')===window.__s8"},
        {"shot": "02-created-meeting.png"},
        # Changer sa nature (et son titre) depuis le formulaire de la ligne.
        {"do": action("Point hebdo S8", "rename")},
        {"wait": "document.querySelector('#boardsList [data-bd-action=kind]')"},
        {"do": "(()=>{const f=document.querySelector('#boardsList [data-bd-action=title]');f.value='Démo S8';"
               "f.dispatchEvent(new Event('input',{bubbles:true}));return true})()"},
        {"do": pick("#boardsList [data-bd-action=kind]", "presentation")},
        {"shot": "03-edit-kind.png"},
        {"do": "document.querySelector('#boardsList [data-bd-action=save]').click()", "ms": 400},
        {"wait": f"({row('Démo S8')})&&{kind_of('Démo S8')}==='Présentation'"},
        {"get": "edited_kind", "expr": kind_of("Démo S8")},
        {"shot": "04-kind-changed.png"},
        # Archivés : à part, sans bascule, inspectables.
        {"do": "document.getElementById('boardsFilterArchived').click()"},
        {"wait": f"({row('Ancien')})"},
        {"get": "archived", "expr": "[...document.querySelectorAll('#boardsList .bd-row')].map(li=>({"
                                    "title:li.querySelector('.bd-name').textContent,state:li.querySelector('[data-role=state]').textContent,"
                                    "actions:[...li.querySelectorAll('[data-bd-action]')].map(b=>b.getAttribute('data-bd-action'))}))"},
        {"shot": "05-archived.png"},
        {"do": action("Ancien", "inspect"), "ms": 400},
        {"wait": f"!document.getElementById('workspaceManager').hidden&&document.querySelector('#wspPanel .wsp-row.is-open[class*=is-archived]')"
                 f"&&{wsp_text}.includes('boards/{w.board_archived}/memory')"},
        {"get": "inspect_archived", "expr": "(()=>{const r=document.querySelector('#wspPanel .wsp-row.is-open');return {"
                                            "id:r.querySelector('[data-act=board-toggle]').getAttribute('data-id'),"
                                            "text:r.textContent,tab:document.querySelector('#wspTabs [aria-selected=true]').textContent,"
                                            "panelHidden:document.getElementById('boardsPanel').hidden,"
                                            "focus:document.activeElement&&document.activeElement.getAttribute('data-id')}})()"},
        {"shot": "06-inspect-archived.png"},
        {"do": "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"},
        {"wait": "document.getElementById('workspaceManager').hidden"},
        # Depuis la liste en service : « Inspecter » sur le Board Réunion seedé.
        {"do": "document.getElementById('boardsButton').click()"},
        {"wait": f"({row('Projet A')})"},
        {"do": action("Projet A", "inspect"), "ms": 400},
        {"wait": f"document.querySelector('#wspPanel .wsp-row.is-open')&&{wsp_text}.includes('boards/{w.board_a}/memory')"},
        {"get": "inspect_meeting", "expr": "document.querySelector('#wspPanel .wsp-row.is-open [data-act=board-toggle]').getAttribute('data-id')"},
        {"shot": "07-inspect-meeting.png"},
    ]}


@pytest.mark.asyncio
async def test_quick_browser_creates_edits_filters_and_inspects_against_the_real_stack(tmp_path):
    """HV-WS-UI-002, partie automatisable : vrai Chrome, vrai Control Center, vrai Core (SQLite sous `tmp_path`)."""

    import asyncio
    import os
    import shutil

    from tests.fakes.capture_stack import CaptureStack
    from tests.unit.test_workspace_inspection_api import build

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    shots = Path(os.environ.get("JARVIS_S8_EVIDENCE_DIR") or tmp_path / "shots")
    shots.mkdir(parents=True, exist_ok=True)
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        stack.center.board_routes._transport = stack.sessions
        active_before = (await stack.call("GET", "/api/boards/active"))[1]
        proc = await asyncio.create_subprocess_exec(
            node, str(WORKSPACE_HARNESS), f"http://127.0.0.1:{stack.cc_port}/", chrome, json.dumps(_quick_plan(w)),
            str(shots), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
        assert proc.returncode == 0, err.decode("utf-8", "replace")
        seen = json.loads(out.decode("utf-8"))

        narrow = {"width": 500, "height": 760, "steps": [
            {"wait": "(document.getElementById('boardsTitle')||{}).textContent==='Projet B'"},
            {"do": "document.getElementById('boardsButton').click()"},
            {"wait": "document.querySelector('#boardsList [data-bd-action=inspect]')"},
            {"do": "document.querySelector('#boardsList .bd-row[data-active=false] [data-bd-action=rename]').click()"},
            {"wait": "document.querySelector('#boardsList [data-bd-action=kind]')"},
            {"get": "overflow", "expr": "(()=>{const p=document.getElementById('boardsPanel');"
                                        "return {panel:p.scrollWidth-p.clientWidth,page:document.documentElement.scrollWidth-innerWidth,"
                                        "right:p.getBoundingClientRect().right}})()"},
            {"shot": "08-narrow-edit.png"},
        ]}
        proc = await asyncio.create_subprocess_exec(
            node, str(WORKSPACE_HARNESS), f"http://127.0.0.1:{stack.cc_port}/", chrome, json.dumps(narrow),
            str(shots), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        assert proc.returncode == 0, err.decode("utf-8", "replace")
        small = json.loads(out.decode("utf-8"))["results"]

        listing = (await stack.call("GET", "/api/boards?include_archived=true"))[1]["boards"]
        active_after = (await stack.call("GET", "/api/boards/active"))[1]

    r = seen["results"]
    rows = {row["title"]: row for row in r["list"]}
    assert set(rows) == {"Board principal", "Projet A", "Projet B"}, "archived Boards stay out of the list in service"
    assert rows["Projet A"]["kind"] == "Réunion" and rows["Projet B"]["kind"] == "Générique"
    assert rows["Projet B"]["active"] == "true" and rows["Projet B"]["state"] == "Actif"
    assert rows["Projet A"]["opened"].startswith("ouvert") and rows["Projet B"]["opened"] == "ouvert à l’instant"
    assert rows["Board principal"]["opened"] == "jamais ouvert", "the server never recorded an opening"
    assert "En service3" in r["filter"] and "Archivés1" in r["filter"]
    assert r["created_kind"] == "Réunion" and r["created_focus"] is True
    assert r["edited_kind"] == "Présentation"
    assert r["archived"] == [{"title": "Ancien", "state": "Archivé", "actions": ["inspect"]}]
    inspected = r["inspect_archived"]
    assert inspected["id"] == w.board_archived and inspected["tab"] == "Boards" and inspected["panelHidden"] is True
    assert "Archivé" in inspected["text"] and inspected["focus"] == w.board_archived
    assert r["inspect_meeting"] == w.board_a
    taken = {k[5:] for k in r if k.startswith("shot:")}
    assert len(taken) == 7 and taken <= {p.name for p in shots.glob("*.png")}

    created = [b for b in listing if b["title"] == "Démo S8"]
    assert len(created) == 1 and created[0]["board_kind"] == "presentation" and created[0]["status"] == "active"
    assert [b["status"] for b in listing if b["board_id"] == w.board_archived] == ["archived"]
    assert active_after == active_before, "creating, editing and inspecting never switch"

    console = seen["console"]
    assert [line for line in console if line["type"] == "exception"] == []
    assert [line for line in console if line["type"] == "error" and ("[boards]" in line["text"] or "[workspace]" in line["text"])] == []
    for event in ("boards.create_done", "boards.update_done", "boards.filter_changed", "boards.inspect_requested"):
        assert any(event in line["text"] for line in console), event

    assert small["overflow"]["panel"] <= 0 and small["overflow"]["page"] <= 0 and small["overflow"]["right"] <= 500

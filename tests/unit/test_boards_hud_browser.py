"""La carte Board du bas-gauche, mesurée dans un vrai Chrome sans tête (handoff board-session,
Slice 06 ; déplacée en bas à gauche par la Slice 02 de jarvis-board-ui-wheel-dossier-refactor).

La page est celle que `ControlCenter.index` sert ; seul `fetch` est un double
(`_boards_browser.mjs`), si bien que le vrai `refreshStatus` nourrit le vrai
module chaque seconde. Ce que ce fichier épingle, et qu'aucune lecture de la
feuille de style ne prouve :

- la carte est **cliquable** (`elementFromPoint`), en bas à gauche, et dit le
  type du Board actif avant son titre ; le haut-gauche ne porte plus ni
  sélecteur, ni état permanent, ni contrôle de mode, ni œil (Slice 02) ;
- le panneau s'ouvre au-dessus d'elle, dans l'écran, par-dessus ce qu'il couvre ;
- une bascule suit le serveur (A → B → A), un refus laisse A actif et le dit ;
- `prefers-reduced-motion` arrête la barre d'attente et l'ouverture animée ;
- aucune erreur de console.

Slice 08 (board-memory-workspace-inspector) : un dernier parcours, sans aucun
double, contre un vrai Core et un vrai Control Center (`CaptureStack`) — créer
un Board « Réunion », le renommer (son type ne change pas, D02), filtrer les archivés, « Inspecter »
ouvre le gestionnaire sur ce Board. Captures dans `JARVIS_S8_EVIDENCE_DIR`.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from tests.unit.test_boards_card_browser import _chrome, _served_page

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


@pytest.mark.parametrize("width,height", [(1440, 900), (1280, 720), (1024, 700), (900, 600), (500, 700)])
def test_the_card_is_bottom_left_and_opens_a_full_screen_veil_over_the_page(tmp_path, width, height):
    seen = _drive(tmp_path, [{"width": width, "height": height, "actions": [OPEN]}])[0]
    trigger, panel, dock = seen["trigger"], seen["panel"], seen["dock"]
    assert seen["title"] == "Jarvis" and seen["tone"] == "ready"
    assert (seen["kind"], seen["eyebrow"]) == ("assistant", "Assistant "), "the type leads the card"
    # D04 / D05 : la carte est en bas à gauche ; le haut-gauche n'a plus rien de permanent.
    assert seen["retired"] == {"topbar": False, "state": False, "mode": False, "eye": False}, seen["retired"]
    assert trigger["l"] <= (84 if width <= 700 else 18) + 1, trigger
    assert trigger["b"] >= height - 160 and trigger["t"] > height / 2, trigger
    assert not _overlap(trigger, dock)
    # Refonte du sélecteur (2026-10-19) : un voile plein écran, flouté, par-dessus toute la page — la carte comprise.
    assert panel is not None and panel["z"] == "58"
    assert (panel["l"], panel["t"], panel["r"], panel["b"]) == (0, 0, width, height), panel
    assert seen["panelHit"] is True, "the open veil is on top of whatever it covers (dock included)"
    assert seen["triggerHit"] is False, "the veil covers the card that opened it"
    assert [row["id"] for row in seen["rows"]] == ["default", "board_b", "board_m"]
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
    assert seen["kind"] == "assistant", "the card follows the server's type, back on A"
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
    assert normal["motion"]["sweep"] == "bdSweep" and normal["motion"]["pop"] == "bdVeil"
    assert reduced["tone"] == "pending"
    assert reduced["motion"] == {"sweep": "none", "pop": "none"}


COSMOS = ("cosmos", "window.JarvisThemeAPI.activate('cosmos',{persist:false});'ok'", 600)


@pytest.mark.parametrize("width,height", [(500, 700), (800, 700), (1440, 900)])
def test_in_cosmos_the_card_is_whole_and_nothing_permanent_is_left_top_left(tmp_path, width, height):
    """QA 06/07, point 6 (le dock rognait le bouton du haut) : en Cosmos, la carte est entière, hors du lanceur."""

    seen = _drive(tmp_path, [{"width": width, "height": height, "actions": [COSMOS]}])[0]
    trigger, dock = seen["trigger"], seen["dock"]
    assert seen["theme"] == "cosmos"
    assert trigger and dock
    assert not _overlap(trigger, dock), (trigger, dock)
    assert trigger["l"] >= 0 and trigger["r"] <= width and trigger["w"] >= 140, "whole, not clipped"
    assert seen["retired"] == {"topbar": False, "state": False, "mode": False, "eye": False}
    assert seen["triggerHit"] is True


MEETING = ("meeting", "window.__boards.active='board_m';'ok'", 1600)


def test_a_meeting_board_says_on_the_card_that_it_is_planned(tmp_path):
    """QA 01a / D24 : l'état « prévu » d'un Board Réunion se lit à l'écran, pas seulement dans la trace."""

    seen = _drive(tmp_path, [{"width": 1440, "height": 900, "actions": [MEETING]}])[0]
    assert (seen["kind"], seen["eyebrow"], seen["title"]) == ("meeting", "Réunion · prévu ", "Point hebdo")
    assert seen["sub"] == "Agit en Assistant"


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
        # Le parcours de l'écran : l'orbe « Nouveau Board », l'orbe du type, puis le titre.
        {"do": "document.getElementById('boardsNewBoard').click()"},
        {"wait": "document.getElementById('boardsPanel').getAttribute('data-bd-screen')==='kind'"},
        {"get": "kind_screen", "expr": "(()=>{const s=document.getElementById('boardsPanel');return {"
                                       "list:!!document.getElementById('boardsList').getClientRects().length,"
                                       "kinds:[...s.querySelectorAll('#boardsCreateKindPick [role=radio]')].filter(b=>b.getClientRects().length).map(b=>b.getAttribute('data-kind')),"
                                       "focus:document.activeElement&&document.activeElement.getAttribute('data-kind')}})()"},
        {"shot": "01b-kind.png"},
        {"do": "document.querySelector('#boardsCreateKindPick [data-kind=meeting]').click()"},
        {"wait": "document.getElementById('boardsPanel').getAttribute('data-bd-screen')==='name'&&document.activeElement.id==='boardsCreateTitle'"},
        {"do": "(()=>{const i=document.getElementById('boardsCreateTitle');i.value='Point hebdo S8';return true})()"},
        {"get": "name_screen", "expr": "(()=>({heading:document.getElementById('boardsHeading').textContent,"
                                       "hint:document.getElementById('boardsCreateKindHint').getClientRects().length>0,"
                                       "kind:document.getElementById('boardsCreateKind').value}))()"},
        {"shot": "01c-name.png"},
        {"do": "document.getElementById('boardsCreate').click()", "ms": 400},
        {"wait": f"({row('Point hebdo S8')})&&{kind_of('Point hebdo S8')}==='Réunion'"},
        {"do": f"window.__s8=({row('Point hebdo S8')}).getAttribute('data-board-id')"},
        {"get": "created_kind", "expr": kind_of("Point hebdo S8")},
        {"get": "created_focus", "expr": "document.activeElement&&document.activeElement.closest('.bd-row')&&"
                                         "document.activeElement.closest('.bd-row').getAttribute('data-board-id')===window.__s8"},
        {"shot": "02-created-meeting.png"},
        # Renommer depuis le formulaire de la ligne : le type n'y est pas proposé (D02, Slice 01a).
        {"do": action("Point hebdo S8", "rename")},
        {"wait": "document.querySelector('#boardsList [data-bd-action=title]')"},
        {"get": "edit_kind_offered", "expr": "!!document.querySelector('#boardsList [data-bd-action=kind]')"},
        {"do": "(()=>{const f=document.querySelector('#boardsList [data-bd-action=title]');f.value='Démo S8';"
               "f.dispatchEvent(new Event('input',{bubbles:true}));return true})()"},
        {"shot": "03-edit-title.png"},
        {"do": "document.querySelector('#boardsList [data-bd-action=save]').click()", "ms": 400},
        {"wait": f"({row('Démo S8')})&&{kind_of('Démo S8')}==='Réunion'"},
        {"get": "edited_kind", "expr": kind_of("Démo S8")},
        {"shot": "04-renamed.png"},
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
        {"key": "Escape"},
        {"wait": "document.getElementById('workspaceManager').hidden"},
        # QA S08 point 4 : Échap rend le focus là où l'utilisateur est parti, la carte Board.
        {"get": "focus_after_escape", "expr": "document.activeElement&&document.activeElement.id"},
        # Depuis la liste en service : « Inspecter » sur le Board Réunion seedé.
        {"do": "document.getElementById('boardsButton').click()"},
        {"wait": f"({row('Projet A')})"},
        {"do": action("Projet A", "inspect"), "ms": 400},
        {"wait": f"document.querySelector('#wspPanel .wsp-row.is-open')&&{wsp_text}.includes('boards/{w.board_a}/memory')"},
        {"get": "inspect_meeting", "expr": "document.querySelector('#wspPanel .wsp-row.is-open [data-act=board-toggle]').getAttribute('data-id')"},
        {"shot": "07-inspect-meeting.png"},
        {"key": "Escape"},
        {"wait": "document.getElementById('workspaceManager').hidden&&document.activeElement&&document.activeElement.id==='boardsButton'"},
        # Bascule réelle Projet B -> Projet A -> Projet B : Core et l'hôte de la pile de test l'appliquent.
        {"do": "document.getElementById('boardsButton').click()"},
        {"wait": f"({row('Projet A')})&&({row('Projet A')}).querySelector('[data-bd-action=switch]')"},
        {"do": action("Projet A", "switch")},
        # Le panneau se ferme quand la bascule est confirmée : on le rouvre ensuite.
        {"wait": "document.getElementById('boardsTitle').textContent==='Projet A'&&document.getElementById('boardsPanel').hidden"},
        {"do": "window.JarvisBoardsControl.open()"},
        {"wait": f"!document.getElementById('boardsPanel').hidden&&({row('Projet A')})&&({row('Projet A')}).getAttribute('data-active')==='true'"},
        {"get": "on_a", "expr": f"(()=>{{const r={row('Projet A')};return {{active:r.getAttribute('data-active'),"
                                "state:r.querySelector('[data-role=state]').textContent,"
                                "opened:r.querySelector('[data-role=opened]').textContent}})()"},
        {"shot": "09-switched-to-a.png"},
        {"do": action("Projet B", "switch")},
        # Le panneau se ferme quand la bascule est confirmée : on le rouvre ensuite.
        {"wait": "document.getElementById('boardsTitle').textContent==='Projet B'&&document.getElementById('boardsPanel').hidden"},
        {"do": "window.JarvisBoardsControl.open()"},
        {"wait": f"({row('Projet B')})&&({row('Projet B')}).getAttribute('data-active')==='true'"},
        {"get": "back_on_b", "expr": "[...document.querySelectorAll('#boardsList .bd-row[data-active=true] .bd-name')].map(n=>n.textContent)"},
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
            {"wait": "document.querySelector('#boardsList [data-bd-action=title]')"},
            {"get": "overflow", "expr": "(()=>{const p=document.getElementById('boardsPanel');"
                                        "return {panel:p.scrollWidth-p.clientWidth,page:document.documentElement.scrollWidth-innerWidth,"
                                        "right:p.getBoundingClientRect().right}})()"},
            {"shot": "08-narrow-edit.png"},
        ]}
        # Écran bas (≤ 600 px) : l'aide du pied se replie, la liste garde la place.
        short = {"width": 1024, "height": 560, "steps": [
            {"wait": "(document.getElementById('boardsTitle')||{}).textContent==='Projet B'"},
            {"do": "document.getElementById('boardsButton').click()"},
            {"wait": "document.querySelector('#boardsList [data-bd-action=inspect]')"},
            {"get": "foot", "expr": "(()=>{const h=document.getElementById('boardsNewSessionHint');"
                                    "const p=document.getElementById('boardsPanel').getBoundingClientRect();"
                                    "return {hint:h.getBoundingClientRect().width<=1?'none':'shown',bottom:p.bottom,"
                                    "rows:document.querySelectorAll('#boardsList .bd-row').length,"
                                    "described:document.getElementById('boardsNewSession').getAttribute('aria-describedby')}})()"},
            {"shot": "10-short-height.png"},
        ]}
        proc = await asyncio.create_subprocess_exec(
            node, str(WORKSPACE_HARNESS), f"http://127.0.0.1:{stack.cc_port}/", chrome, json.dumps(narrow),
            str(shots), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        assert proc.returncode == 0, err.decode("utf-8", "replace")
        small = json.loads(out.decode("utf-8"))["results"]
        proc = await asyncio.create_subprocess_exec(
            node, str(WORKSPACE_HARNESS), f"http://127.0.0.1:{stack.cc_port}/", chrome, json.dumps(short),
            str(shots), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        assert proc.returncode == 0, err.decode("utf-8", "replace")
        low = json.loads(out.decode("utf-8"))["results"]

        listing = (await stack.call("GET", "/api/boards?include_archived=true"))[1]["boards"]
        active_after = (await stack.call("GET", "/api/boards/active"))[1]

    r = seen["results"]
    rows = {row["title"]: row for row in r["list"]}
    assert set(rows) == {"Board principal", "Projet A", "Projet B"}, "archived Boards stay out of the list in service"
    assert rows["Projet A"]["kind"] == "Réunion" and rows["Projet B"]["kind"] == "Assistant"
    assert rows["Projet B"]["active"] == "true" and rows["Projet B"]["state"] == "Actif"
    assert rows["Projet A"]["opened"].startswith("ouvert") and rows["Projet B"]["opened"] == "ouvert à l’instant"
    assert rows["Board principal"]["opened"].startswith("ouvert"),         "the Board a Session opened on is opened (QA S08 point 2), never « jamais ouvert »"
    assert "En service3" in r["filter"] and "Archivés1" in r["filter"]
    assert r["kind_screen"] == {"list": False, "kinds": ["assistant", "presentation", "meeting"], "focus": "assistant"},         "creating is its own screen: the grid is gone, the three types are shown, the default one has the focus"
    assert r["name_screen"] == {"heading": "Nouveau Board Réunion", "hint": True, "kind": "meeting"}
    assert r["created_kind"] == "Réunion" and r["created_focus"] is True
    assert r["edited_kind"] == "Réunion" and r["edit_kind_offered"] is False, "renaming never changes the type"
    # Slice 07 (refonte roue/dossier) : un Board archivé se lit aussi dans le Dossier plein écran (lecture seule).
    assert r["archived"] == [{"title": "Ancien", "state": "Archivé", "actions": ["dossier", "inspect"]}]
    inspected = r["inspect_archived"]
    assert inspected["id"] == w.board_archived and inspected["tab"] == "Boards" and inspected["panelHidden"] is True
    assert "Archivé" in inspected["text"] and inspected["focus"] == w.board_archived
    assert r["focus_after_escape"] == "boardsButton", "Escape in the manager goes back where the user started"
    assert r["inspect_meeting"] == w.board_a
    assert r["on_a"] == {"active": "true", "state": "Actif", "opened": "ouvert à l’instant"}
    assert r["back_on_b"] == ["Projet B"]
    taken = {k[5:] for k in r if k.startswith("shot:")}
    assert len(taken) == 10 and taken <= {p.name for p in shots.glob("*.png")}

    created = [b for b in listing if b["title"] == "Démo S8"]
    assert len(created) == 1 and created[0]["board_kind"] == "meeting" and created[0]["status"] == "active"
    assert [b["status"] for b in listing if b["board_id"] == w.board_archived] == ["archived"]
    assert active_after["board"]["board_id"] == active_before["board"]["board_id"],         "creating, editing and inspecting never switch; the real A/B/A ends where it started"

    console = seen["console"]
    assert [line for line in console if line["type"] == "exception"] == []
    assert [line for line in console if line["type"] == "error" and ("[boards]" in line["text"] or "[workspace]" in line["text"])] == []
    for event in ("boards.create_done", "boards.update_done", "boards.filter_changed", "boards.inspect_requested",
                  "boards.switch_done"):
        assert any(event in line["text"] for line in console), event

    assert low["foot"]["hint"] == "none" and low["foot"]["described"] == "boardsNewSessionHint"
    assert low["foot"]["bottom"] <= 560 and low["foot"]["rows"] == 4
    assert small["overflow"]["panel"] <= 0 and small["overflow"]["page"] <= 0 and small["overflow"]["right"] <= 500


@pytest.mark.parametrize("width,height", [(1440, 900), (1920, 1032)])
def test_on_a_large_screen_a_long_board_title_is_not_cut(tmp_path, width, height):
    """Polish S02 item 3 (Slice 08) : la carte était plafonnée à 236 px, « Projet Atlas — refonte du tableau de
    bord » était coupé à 1440 et 1920 px. Dès 1400 px elle va jusqu'à 320 px et le titre tient sur deux lignes,
    sans toucher le centre d'état."""
    read = ("t", "(()=>{const t=document.querySelector('#boardsTitle'),c=document.querySelector('#boardsButton')"
                 ".getBoundingClientRect(),s=document.querySelector('.status-centre').getBoundingClientRect();"
                 "return {cut:t.scrollWidth>t.clientWidth+1||t.scrollHeight>t.clientHeight+1,lines:Math.round(t.getBoundingClientRect().height/parseFloat(getComputedStyle(t).lineHeight||15)),text:t.textContent,right:c.right,statusLeft:s.left}})()", 0)
    seen = _drive(tmp_path, [{"width": width, "height": height, "actions": [
        ("go", "window.__boards.active='board_b';'ok'", 1800), read]}])[0]
    t = seen["results"]["t"]
    assert t["text"] == "Projet Atlas — refonte du tableau de bord", t
    assert t["cut"] is False, t
    assert t["right"] <= t["statusLeft"], ("la carte reste hors du centre d'état", t)

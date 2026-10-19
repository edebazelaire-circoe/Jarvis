"""Lanceur global du haut-droit, mesuré dans un vrai Chrome sans tête (orbital UI, Slice 08).

Contrat : `docs/control-center-shell.md` › *Global launcher* ; architecture
résolue du handoff `jarvis-board-orbital-ui-workspace-rail`, D11 et §9. La page
est celle que `ControlCenter.index` sert ; seul `fetch` est un double (le
harnais du centre d'état, `_status_centre_browser.mjs` : statut, Boards et leur
bascule, raccourcis, scène, rail). Ce que ce fichier épingle :

- chacun des dix outils de l'ancien dock a une route : visible dans la rangée,
  ou dans le popover « Plus d’outils », atteint par un vrai clic souris, et il
  ouvre ce qu'il ouvrait ; les raccourcis clavier (`e`, `t`, `a`, `s`) aussi ;
- le popover : une tabulation (roving), flèches, Home/End, Échap rend le focus
  à « Plus d’outils » avant de fermer quoi que ce soit d'autre ; un module qui
  rend le focus à son bouton replié le rend à « Plus d’outils » ;
- les badges Errors et Agents se lisent sans rien ouvrir ;
- le Board se change depuis la carte Board du bas-gauche, hors du lanceur
  (Slice 02 de jarvis-board-ui-wheel-dossier-refactor : plus de ligne d'état ni
  de contrôle de mode) ; la carte ne chevauche ni le lanceur ni le reste, dans
  les deux thèmes à 1440×900, 1280×720, 900×600 et 600×800.

Preuves visuelles : `JARVIS_S08_EVIDENCE_DIR=<dossier>` y écrit les captures.
Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.unit.test_boards_card_browser import _chrome, _served_page

HARNESS = Path(__file__).parent / "_status_centre_browser.mjs"
VIEWPORTS = ((1440, 900), (1280, 720), (900, 600), (600, 800))
THEMES = ("circuit-board", "cosmos")
EVIDENCE = os.environ.get("JARVIS_S08_EVIDENCE_DIR")

#: Les dix outils du dock d'avant la Slice 08 (sélecteur, effet attendu une fois activé).
OLD_DOCK = {
    "ERR": ('.dock button[data-panel="errors"]', "document.getElementById('panel').classList.contains('open')&&document.getElementById('panelTitle').textContent.startsWith('Errors')"),
    "TRC": ('.dock button[data-panel="trace"]', "document.getElementById('panel').classList.contains('open')&&document.getElementById('panelTitle').textContent==='Trace'"),
    "LAB": ("#openTestLab", "!document.getElementById('testlab').hidden"),
    "CNV": ("#openTimeline", "!document.getElementById('timeline').hidden"),
    "SET": ("#openSettings", "document.getElementById('overlay').classList.contains('open')"),
    "MCP": ("#openMcpInspector", "!document.getElementById('mcpInspector').hidden"),
    "WSP": ("#openWorkspace", "!document.getElementById('workspaceManager').hidden"),
    "PFB": ("#openPrefabs", "!document.getElementById('prefabLibrary').hidden"),
    # Sans présentation ouverte, l'inspecteur du Studio se refuse en le disant (bouton
    # désactivé, raison en infobulle) : sa route existe, son effet dépend du Studio.
    "INS": ("#openStudioInspector", "(b=>b.getAttribute('aria-expanded')==='true'||(b.disabled&&!!b.title))(document.getElementById('openStudioInspector'))"),
    "AGT": ("#agentsButton", "document.getElementById('panel').classList.contains('open')&&document.getElementById('panelTitle').textContent.startsWith('Agents')"),
}
#: Réglages (`SET`) est replié dans « Plus d’outils » depuis la Slice 04 de la refonte roue/dossier : la
#: catégorie Paramètres de la roue ouvre la même surface ; son raccourci `s` ne change pas.
VISIBLE = {"CNV", "AGT", "ERR"}

#: Un bouton est atteignable s'il a une boîte et si le point en son centre est à lui.
HIT = r"""(sel=>{const b=document.querySelector(sel);if(!b)return {exists:false};const r=b.getBoundingClientRect();
  const at=r.width>0?document.elementFromPoint(r.left+r.width/2,r.top+r.height/2):null;
  return {exists:true,inDock:!!b.closest('nav.dock'),inPop:!!b.closest('#dockMorePop'),w:r.width,h:r.height,
    hit:!!(at&&b.contains(at)),name:b.getAttribute('aria-label')||b.textContent.trim()}})"""

GEOMETRY = r"""(()=>{const box=el=>{if(!el)return null;const cs=getComputedStyle(el);if(cs.display==='none'||el.closest('[hidden]'))return null;
  const r=el.getBoundingClientRect();return r.width>0?{l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height}:null};
  const q=s=>document.querySelector(s);
  const row=[...document.querySelectorAll('nav.dock>.tool>button')].map(b=>({id:b.id||b.dataset.panel,box:box(b),
    name:b.getAttribute('aria-label')||b.textContent.trim(),title:b.title}));
  return {vw:innerWidth,vh:innerHeight,row,dock:box(q('.dock')),pop:box(q('#dockMorePop')),
    items:[...document.querySelectorAll('#dockMorePop button')].map(b=>({id:b.id||b.dataset.panel,box:box(b),
      name:b.getAttribute('aria-label')||'',label:b.dataset.dockLabel,text:getComputedStyle(b,'::after').content})),
    retired:{topbar:!!q('.topbar'),state:!!q('.state'),mode:!!q('#interactionModeHud')},boards:box(q('#boardsButton')),
    boardsInDock:!!q('.dock #boardsHud'),
    rail:box(q('#presentationRail')),panel:box(q('#panel.open')),centre:[...document.querySelectorAll('#bgPills .bgpill')].map(box).filter(Boolean),
    chatTab:box(q('#chatTab')),wheel:box(q('#toolWheel .tw-anchor')),
    z:getComputedStyle(q('.dock')).zIndex,expanded:q('#dockMore').getAttribute('aria-expanded'),
    overflowX:document.documentElement.scrollWidth>innerWidth}})()"""

FOCUS = "(()=>{const a=document.activeElement;return a?(a.id||a.dataset.panel||a.tagName):null})()"
ROVING = "[...document.querySelectorAll('#dockMorePop button')].filter(b=>b.tabIndex===0).map(b=>b.id||b.dataset.panel)"


def _drive(tmp_path: Path, plan: list) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    page = _served_page(tmp_path)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    done = subprocess.run([node, str(HARNESS), str(page), chrome, "@" + str(plan_file)],
                          capture_output=True, text=True, encoding="utf-8", timeout=560, check=False)
    assert done.returncode == 0, done.stderr[-4000:]
    return json.loads(done.stdout)


def _shot(name: str) -> list:
    if not EVIDENCE:
        return []
    Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
    return [["shot", "shot", str(Path(EVIDENCE) / f"{name}.png"), 100]]


def _overlap(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    return min(a["r"], b["r"]) - max(a["l"], b["l"]) > 0.5 and min(a["b"], b["b"]) - max(a["t"], b["t"]) > 0.5


def _no_errors(step: dict) -> None:
    bad = [line for line in step["console"] if line["type"] in ("exception", "error")]
    assert bad == [], bad


def test_every_pre_refactor_tool_has_a_route(tmp_path):
    steps = []
    for code, (selector, effect) in OLD_DOCK.items():
        actions = [["eval", "closed", f"{HIT}({json.dumps(selector)})", 100]]
        if code not in VISIBLE:
            actions.append(["click", "more", "#dockMore", 400])
        actions += [["eval", "reach", f"{HIT}({json.dumps(selector)})", 100],
                    ["click", "use", selector, 1500],
                    ["eval", "effect", effect, 100],
                    ["eval", "popHidden", "document.getElementById('dockMorePop').hidden", 100]]
        steps.append({"width": 1280, "height": 720, "actions": actions})
    # Les raccourcis d'avant, inchangés : Erreurs, Trace, Agents, Réglages.
    shortcut = lambda key, expr: [["eval", "blur", "document.activeElement&&document.activeElement.blur();1", 50],  # noqa: E731
                                  ["key", f"k{key}", key, 900], ["eval", f"s{key}", expr, 100]]
    steps.append({"width": 1280, "height": 720, "actions": [
        *shortcut("t", OLD_DOCK["TRC"][1]), *shortcut("e", OLD_DOCK["ERR"][1]), *shortcut("a", OLD_DOCK["AGT"][1]),
        *shortcut("s", OLD_DOCK["SET"][1])]})
    out = _drive(tmp_path, steps)
    for (code, (selector, _)), step in zip(OLD_DOCK.items(), out):
        r = step["results"]
        assert r["closed"]["exists"] and r["closed"]["inDock"], (code, r["closed"])
        # Rangée : visible et cliquable sans rien ouvrir. Popover : caché replié, atteint après « Plus d’outils ».
        assert r["closed"]["hit"] is (code in VISIBLE), (code, r["closed"])
        assert r["closed"]["inPop"] is (code not in VISIBLE), (code, r["closed"])
        assert r["reach"]["hit"] and r["reach"]["w"] >= 34 and r["reach"]["h"] >= 34, (code, r["reach"])
        assert r["reach"]["name"], code
        assert r["effect"] is True, (code, r)
        # Activer un outil replie le popover.
        assert r["popHidden"] is True, code
        if code == "INS":
            # L'inspecteur ouvert lit les présentations du Studio, que le double ne sert pas :
            # son refus dit (journal `presentations_failed`) prouve qu'il s'est bien ouvert.
            step = dict(step, console=[c for c in step["console"] if "[studio-inspector] presentations_failed" not in c["text"]])
        _no_errors(step)
    keys = out[-1]["results"]
    assert keys["st"] is True and keys["se"] is True and keys["sa"] is True and keys["ss"] is True, keys


def test_popover_keyboard_roving_escape(tmp_path):
    step = _drive(tmp_path, [{"width": 1280, "height": 720, "actions": [
        # Un panneau latéral ouvert : Échap fermera d'abord le popover, le plus haut.
        ["click", "err", '.dock button[data-panel="errors"]', 900],
        ["eval", "focusMore", "document.getElementById('dockMore').focus();1", 100],
        ["key", "enter", "Enter", 300],
        ["eval", "f1", FOCUS, 50], ["eval", "rove1", ROVING, 50],
        ["eval", "expanded", "document.getElementById('dockMore').getAttribute('aria-expanded')", 50],
        ["eval", "z", "getComputedStyle(document.querySelector('.dock')).zIndex", 50],
        ["key", "down", "ArrowDown", 150], ["eval", "f2", FOCUS, 50], ["eval", "rove2", ROVING, 50],
        ["key", "end", "End", 150], ["eval", "f3", FOCUS, 50],
        ["key", "downWrap", "ArrowDown", 150], ["eval", "f4", FOCUS, 50],
        ["key", "upWrap", "ArrowUp", 150], ["eval", "f5", FOCUS, 50],
        ["key", "home", "Home", 150], ["eval", "f6", FOCUS, 50],
        ["key", "esc", "Escape", 300],
        ["eval", "afterEsc", "({open:!document.getElementById('dockMorePop').hidden,focus:document.activeElement.id,"
                             "panel:document.getElementById('panel').classList.contains('open'),"
                             "expanded:document.getElementById('dockMore').getAttribute('aria-expanded'),"
                             "z:getComputedStyle(document.querySelector('.dock')).zIndex})", 50],
        # ArrowUp sur « Plus d’outils » : ouvert, focus sur le dernier ; Tab sort et ferme.
        ["key", "up", "ArrowUp", 300], ["eval", "f7", FOCUS, 50],
        ["key", "tab", "Tab", 300],
        ["eval", "afterTab", "!document.getElementById('dockMorePop').hidden", 50],
        # Test Lab ouvert depuis le popover au clavier, fermé par Échap : le focus revient
        # sur « Plus d’outils », jamais sur son bouton replié et caché.
        ["eval", "focusMore2", "document.getElementById('dockMore').focus();1", 100],
        ["key", "enter2", "Enter", 300], ["key", "down2", "ArrowDown", 150], ["key", "down3", "ArrowDown", 150],
        ["eval", "f8", FOCUS, 50],
        ["key", "openLab", "Enter", 1500],
        ["eval", "lab", "!document.getElementById('testlab').hidden", 50],
        ["key", "closeLab", "Escape", 800],
        ["eval", "back", FOCUS, 50],
        # Ouvert à la souris, un clic dehors le referme.
        ["click", "mouseOpen", "#dockMore", 300],
        ["eval", "mouseFocus", FOCUS, 50],
        ["click", "outside", "#statusCentre", 300],
        ["eval", "afterOutside", "!document.getElementById('dockMorePop').hidden", 50],
    ]}])[0]
    r = step["results"]
    assert r["f1"] == "openSettings" and r["rove1"] == ["openSettings"], r
    assert r["expanded"] == "true" and r["z"] == "36"
    assert r["f2"] == "trace" and r["rove2"] == ["trace"]
    assert r["f3"] == "openStudioInspector" or r["f3"] == "openPrefabs", r["f3"]  # INS désactivé sans présentation
    assert r["f4"] == "openSettings" and r["f5"] == r["f3"] and r["f6"] == "openSettings"
    assert r["afterEsc"] == {"open": False, "focus": "dockMore", "panel": True, "expanded": "false", "z": "32"}
    assert r["f7"] == r["f3"]
    assert r["afterTab"] is False
    assert r["f8"] == "openTestLab" and r["lab"] is True
    assert r["back"] == "dockMore", r["back"]
    assert r["mouseFocus"] == "dockMore" and r["afterOutside"] is False
    _no_errors(step)


def test_badges_visible_without_opening(tmp_path):
    badges = r"""(()=>{const b=id=>{const e=document.getElementById(id);const r=e.getBoundingClientRect();
      const at=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
      return {shown:getComputedStyle(e).display!=='none'&&r.width>0,text:e.textContent,inPop:!!e.closest('#dockMorePop'),hit:e===at||e.contains(at)}};
      return {err:b('errorBadge'),agt:b('agentBadge'),popOpen:!document.getElementById('dockMorePop').hidden,
        agentsTitle:document.getElementById('agentsButton').title}})()"""
    out = _drive(tmp_path, [
        {"width": w, "height": h, "theme": theme, "seed": {"errorCount": 3, "subagents": {"active": 2}},
         "actions": [["eval", "badges", badges, 100], *_shot(f"launcher-badges-{theme}-{w}x{h}")]}
        for theme in THEMES for (w, h) in ((1440, 900), (600, 800))])
    for step in out:
        seen = step["results"]["badges"]
        assert seen["popOpen"] is False
        assert seen["err"] == {"shown": True, "text": "3", "inPop": False, "hit": True}, seen
        assert seen["agt"]["shown"] and seen["agt"]["text"] == "2" and not seen["agt"]["inPop"] and seen["agt"]["hit"], seen
        assert "2 sous-agents en cours" in seen["agentsTitle"]
        _no_errors(step)


def test_board_control_visible_and_switches_board(tmp_path):
    seed = {"boards": [{"board_id": "default", "title": "Jarvis", "status": "active"},
                       {"board_id": "board_b", "title": "Projet Atlas", "status": "active"}]}
    step = _drive(tmp_path, [{"width": 1280, "height": 720, "seed": seed, "actions": [
        ["eval", "geo", GEOMETRY, 100],
        ["eval", "before", "document.getElementById('boardsTitle').textContent", 50],
        ["click", "open", "#boardsButton", 700],
        ["click", "pick", '#boardsList [data-board-id="board_b"][data-bd-action="switch"]', 2500],
        ["eval", "after", "document.getElementById('boardsTitle').textContent", 50],
        *_shot("launcher-board-switched-1280x720"),
    ]}])[0]
    r = step["results"]
    g = r["geo"]
    assert not g["boardsInDock"], "le Board n'est pas dans le lanceur"
    # D04 : la carte Board, en bas à gauche.
    assert g["boards"] and g["boards"]["l"] < g["vw"] / 2 and g["boards"]["t"] > g["vh"] / 2, g["boards"]
    assert not _overlap(g["boards"], g["dock"])
    assert r["before"] == "Jarvis" and r["after"] == "Projet Atlas", r
    switches = [b["body"] for b in step["bodies"] if b["path"] == "/api/boards/switch"]
    assert switches == [{"board_id": "board_b"}], switches
    _no_errors(step)


@pytest.mark.parametrize("theme", THEMES)
def test_board_card_bottom_left_unchanged(tmp_path, theme):
    """Le lanceur est une rangée de quatre en haut à droite, son popover tient dans
    l’écran ; la carte Board reste en bas à gauche, hors du lanceur et du haut,
    et rien ne se chevauche — popover ouvert compris, aux quatre tailles."""
    plan = []
    for (w, h) in VIEWPORTS:
        plan.append({"width": w, "height": h, "theme": theme, "actions": [
            ["eval", "closed", GEOMETRY, 100], *_shot(f"launcher-{theme}-{w}x{h}"),
            ["click", "more", "#dockMore", 400],
            ["eval", "open", GEOMETRY, 100], *_shot(f"launcher-{theme}-{w}x{h}-plus-open"),
        ]})
    out = _drive(tmp_path, plan)
    for (w, h), step in zip(VIEWPORTS, out):
        closed, opened = step["results"]["closed"], step["results"]["open"]
        gutter = 18 if w > 700 else 10
        # Rangée : quatre boutons de 34 px, au bord, un seul rang ; noms accessibles = infobulles pour l'icône seule.
        assert [b["id"] for b in closed["row"]] == ["openTimeline", "agentsButton", "errors", "dockMore"]
        assert all(b["box"] and round(b["box"]["w"]) == 34 and round(b["box"]["t"]) == gutter for b in closed["row"]), closed["row"]
        assert round(closed["dock"]["r"]) == w - gutter and round(closed["dock"]["w"]) == 154, closed["dock"]
        more = closed["row"][-1]
        assert more["name"] == more["title"] == "Plus d’outils"
        assert closed["pop"] is None and closed["z"] == "32" and closed["expanded"] == "false"
        # Slice 02 : ni ligne d'état ni contrôle de mode ; la carte Board tient le bas-gauche.
        assert closed["retired"] == {"topbar": False, "state": False, "mode": False}, closed["retired"]
        card = closed["boards"]
        # Géométrie réelle (QA S08 P2) : `GEO` de control_center_boards.js — left 18, bottom 22 ; sous 700 px la
        # carte quitte le rail gauche (`narrowLeft` 84) et se hisse de `narrowLift` 62 au-dessus du centre d'état.
        assert round(card["l"]) == (84 if w <= 700 else 18), card
        assert round(h - card["b"]) == (22 + 62 if w <= 700 else 22), (h - card["b"], card)
        for other in ("dock", "chatTab", "rail", "wheel"):
            assert not _overlap(card, closed[other]), (other, card, closed[other])
        for chip in closed["centre"]:
            assert not _overlap(card, chip), (card, chip)
        # Popover ouvert : sept lignes nommées (Réglages en tête), sous la rangée, dans l'écran, au rang 36.
        assert opened["expanded"] == "true" and opened["z"] == "36"
        pop = opened["pop"]
        assert pop and pop["t"] >= opened["dock"]["t"] + 34 and pop["r"] <= w and pop["l"] >= 0 and pop["b"] <= h, pop
        assert [i["id"] for i in opened["items"]] == ["openSettings", "trace", "openTestLab", "openMcpInspector", "openWorkspace",
                                                      "openPrefabs", "openStudioInspector"]
        for item in opened["items"]:
            assert item["box"] and item["box"]["h"] >= 34 and item["name"], item
            assert item["text"].strip('"') == item["label"], item
        assert not _overlap(pop, opened["boards"])
        assert opened["overflowX"] is False and closed["overflowX"] is False
        _no_errors(step)

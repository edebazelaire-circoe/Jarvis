"""Centre d'état du bas, mesuré dans un vrai Chrome sans tête (orbital UI, Slice 06).

Contrat : `docs/control-center-shell.md` › *Status centre* ; architecture
résolue du handoff `jarvis-board-orbital-ui-workspace-rail`, D8 et §7 (D9).
La page est celle que `ControlCenter.index` sert ; seul `fetch` est un double
(`_status_centre_browser.mjs`) : statut (pastilles, scène allumée), alertes et
acquittement, captures, scène (instantané, patchs, commandes), rail. Ce que ce
fichier épingle :

- les pastilles disent les mêmes catégories et les mêmes comptes que le résumé
  `background` du statut, dans l'ordre du registre, et ouvrent le même
  popover, dont l'acquittement efface la catégorie ;
- chaque pastille porte une icône SVG, un compte et un nom accessible : jamais
  la couleur seule, jamais un émoji ;
- un enregistrement se lit à gauche des pastilles, distinct d'un compteur, et
  s'arrête d'un geste ;
- aucune commande du centre d'état ne recouvre la carte Board (bas-gauche
  depuis la Slice 02 de jarvis-board-ui-wheel-dossier-refactor), le rail,
  l'onglet Chat ou le plateau de dépôt, dans les deux thèmes, à 1440×900,
  1280×720, 900×600 et 600×800 ; un panneau Chat ouvert ne le couvre pas ;
- plus de capsule « F9 · DÉMARRER » ni de ligne d'état : la touche reste dite,
  non affichée, par `#wakeHint`, et reste la touche de Voice ;
- l'œil permanent est **absent** du centre d'état (D06) ; sa mécanique est
  gardée pour Sélection (Slice 06) : avec un hôte `#hiddenEye` rétabli par le
  test (ce que la Slice 06 fera), `aria-pressed`, fantômes sans écriture, liste
  des masqués à l'activation secondaire, « Réafficher » = un seul
  `set_visibility` ; sans hôte, un réglage `showHidden` resté allumé ne dessine
  aucun fantôme.

Preuves visuelles : `JARVIS_S06_EVIDENCE_DIR=<dossier>` y écrit les captures.
Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain.explicit_address import ExplicitAddressSource
from jarvis.runtime.voice_v2 import activation_source_for_label
from tests.unit.test_boards_card_browser import _chrome, _served_page

HARNESS = Path(__file__).parent / "_status_centre_browser.mjs"
VIEWPORTS = ((1440, 900), (1280, 720), (900, 600), (600, 800))
THEMES = ("circuit-board", "cosmos")
EVIDENCE = os.environ.get("JARVIS_S06_EVIDENCE_DIR")

#: Rectangles calculés de ce que le centre d'état et ses voisins occupent.
BOXES = r"""(()=>{
  const box=el=>{if(!el||el.hidden||el.closest('[hidden]'))return null;const cs=getComputedStyle(el);
    if(cs.display==='none'||cs.visibility==='hidden')return null;const r=el.getBoundingClientRect();
    if(!(r.width>0&&r.height>0))return null;return {l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height}};
  const q=s=>document.querySelector(s);
  const items=[...document.querySelectorAll('#recIndicators .ri-chip, #bgPills .bgpill, #hiddenEye')].map(el=>({id:el.id||el.dataset.bgCat||el.dataset.riKey,box:box(el)})).filter(i=>i.box);
  return {vw:innerWidth,vh:innerHeight,items,eyeHost:!!q('#hiddenEye'),
    card:box(q('#boardsButton')),chatTab:box(q('#chatTab')),rail:box(q('#presentationRail')),
    railTab:box(q('#presentationRail .jvr-tab')),tray:box(q('#boardDropTray')),chatPanel:box(q('#chatPanel')),
    wheel:box(q('#toolWheel .tw-anchor')),scStatus:box(q('#sceneLayer>.sc-status')),toasts:box(q('#toasts .toast')),
    dock:box(q('.dock')),liveBanner:box(q('#liveBanner')),
    overflowX:document.documentElement.scrollWidth>innerWidth,
    z:{pills:getComputedStyle(q('#bgPills')).zIndex,rec:getComputedStyle(q('#recIndicators')).zIndex},
    theme:document.documentElement.getAttribute('data-jarvis-theme')||''};
})()"""

#: L'hôte de l'œil, rétabli par le test comme la Slice 06 le déclarera (dans Sélection) : la mécanique
#: gardée (`control_center_scene_page.js`) s'y branche par son id. Plus dans la page depuis la Slice 02.
MOUNT_EYE = r"""(()=>{if(document.getElementById('hiddenEye'))return 'present';
  const b=document.createElement('button');b.type='button';b.id='hiddenEye';b.setAttribute('aria-pressed','false');
  b.setAttribute('aria-disabled','true');b.setAttribute('aria-label','Aucun objet masqué');b.hidden=true;
  b.style.cssText='position:fixed;left:50%;bottom:90px;width:32px;height:32px;z-index:40';
  b.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12s3.4-6 9-6 9 6 9 6-3.4 6-9 6-9-6-9-6z"/></svg>';
  document.body.appendChild(b);window.dispatchEvent(new Event('resize'));return 'mounted'})()"""
EYE_HOST = ["eval", "eyeHost", MOUNT_EYE, 1200]

#: Un plateau de dépôt réel (son hôte, sa feuille) avec un envoi, pour le mesurer.
TRAY = r"""(()=>{const t=document.getElementById('boardDropTray');t.hidden=false;
  const ul=document.getElementById('boardDropList');ul.textContent='';const li=document.createElement('li');
  li.className='board-drop-item';li.dataset.status='uploading';li.textContent='rapport.pdf — envoi 40 %';ul.appendChild(li);return 1})()"""

PILLS = r"""[...document.querySelectorAll('#bgPills .bgpill')].map(p=>({cat:p.dataset.bgCat,label:p.getAttribute('aria-label'),
  title:p.title,count:(p.querySelector('.bgn')||{}).textContent||null,text:p.textContent,svg:!!p.querySelector('svg'),
  paths:[...p.querySelectorAll('svg path')].map(x=>x.getAttribute('d')).join('|'),w:p.getBoundingClientRect().width,
  h:p.getBoundingClientRect().height,cls:p.className,expanded:p.getAttribute('aria-expanded')}))"""

SCREEN_CAPTURE = {"capture_id": "jcap_s", "channel": "screen", "mode": "continuous", "state": "active",
                  "device": "default", "age_s": 65, "stop_requested_at": None}


def _drive(tmp_path: Path, plan: list) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    page = _served_page(tmp_path)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    done = subprocess.run([node, str(HARNESS), str(page), chrome, "@" + str(plan_file)],
                          capture_output=True, text=True, encoding="utf-8", timeout=420, check=False)
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


# ------------------------------------------------------------------ pastilles


def test_same_counts_and_categories_as_status_summary(tmp_path):
    steps = _drive(tmp_path, [
        {"width": 1440, "height": 900, "actions": [["eval", "pills", PILLS, 100]]},
        {"width": 1440, "height": 900, "seed": {"counts": {"failed": 0, "attention": 12, "done": 0, "said": 2}},
         "actions": [["eval", "pills", PILLS, 100]]},
    ])
    first, second = steps[0]["results"]["pills"], steps[1]["results"]["pills"]
    # Les quatre catégories canoniques, dans l'ordre du registre, avec le compte du résumé.
    assert [(p["cat"], p["count"]) for p in first] == [("failed", "2"), ("attention", "1"), ("done", "3"), ("said", "1")]
    assert [p["label"] for p in first] == ["Arrière-plan · 2 échecs", "Arrière-plan · 1 point à vérifier",
                                           "Arrière-plan · 3 tâches terminées", "Arrière-plan · 1 résultat non dit"]
    # Une catégorie à zéro n'a pas de pastille ; au-delà de 9, « 9+ » dans le badge, le compte exact dans le nom.
    assert [(p["cat"], p["count"]) for p in second] == [("attention", "9+"), ("said", "2")]
    assert second[0]["label"] == "Arrière-plan · 12 points à vérifier"
    for step in steps:
        _no_errors(step)


def test_click_opens_same_popover_and_ack_clears(tmp_path):
    pop = r"""(()=>{const p=document.getElementById('bgPop');const r=p.getBoundingClientRect();
      const pill=document.querySelector('#bgPills [data-bg-cat="attention"]');const pr=pill&&pill.getBoundingClientRect();
      return {open:!p.hidden,cls:p.className,title:(p.querySelector('header strong')||{}).textContent||null,
        items:[...p.querySelectorAll('.bgitem .emsg')].map(e=>e.textContent),svg:p.querySelectorAll('.bgitem .ico svg').length,
        rect:{l:r.left,t:r.top,r:r.right,b:r.bottom},pill:pr?{l:pr.left,t:pr.top,r:pr.right,b:pr.bottom}:null,
        expanded:pill?pill.getAttribute('aria-expanded'):null,focus:document.activeElement&&document.activeElement.className}})()"""
    step = _drive(tmp_path, [{"width": 1280, "height": 720, "actions": [
        ["click", "open", '#bgPills [data-bg-cat="attention"]', 900],
        ["eval", "pop", pop, 100],
        *_shot("status-centre-popover-1280x720"),
        ["click", "ack", "#bgPop [data-bg-ack]", 1800],
        ["eval", "after", PILLS, 100],
        ["eval", "popHidden", "document.getElementById('bgPop').hidden", 100],
    ]}])[0]
    seen = step["results"]["pop"]
    assert seen["open"] and "warn" in seen["cls"] and seen["title"] == "1 point à vérifier"
    assert seen["items"] == ["Point à vérifier : diapositive 3 1"] and seen["svg"] == 1
    assert seen["expanded"] == "true"
    # Le popover s'ouvre AU-DESSUS de la pastille (le centre d'état est en bas), à l'écran.
    assert seen["rect"]["b"] <= seen["pill"]["t"] and seen["rect"]["t"] >= 0
    assert seen["rect"]["l"] >= 0 and seen["rect"]["r"] <= 1280
    # L'acquittement : la même route, cette catégorie seulement, puis la pastille part.
    assert [a["category"] for a in step["acks"]] == ["attention"]
    assert step["results"]["popHidden"] is True
    assert [p["cat"] for p in step["results"]["after"]] == ["failed", "done", "said"]
    _no_errors(step)


def test_icons_have_label_and_count_not_colour_only(tmp_path):
    eye = r"""(()=>{const e=document.getElementById('hiddenEye');if(!e)return null;const r=e.getBoundingClientRect();
      return {label:e.getAttribute('aria-label'),title:e.title,pressed:e.getAttribute('aria-pressed'),w:r.width,h:r.height,
        svgs:e.querySelectorAll('svg').length,text:e.textContent.trim()}})()"""
    steps = _drive(tmp_path, [
        {"width": 1440, "height": 900, "theme": theme, "actions": [["eval", "pills", PILLS, 100], ["eval", "eye", eye, 100]]}
        for theme in THEMES
    ])
    for step in steps:
        pills = step["results"]["pills"]
        paths = set()
        for pill in pills:
            assert pill["svg"], pill
            # Le texte visible n'est que le compte (aucun émoji) ; le nom et l'infobulle disent le reste.
            assert pill["text"] == pill["count"] and pill["count"].rstrip("+").isdigit(), pill
            assert pill["label"] == pill["title"] and pill["count"].rstrip("+") in pill["label"]
            assert pill["w"] >= 32 and pill["h"] >= 32, pill
            paths.add(pill["paths"])
        assert len(paths) == len(pills), "chaque catégorie a sa forme, pas seulement sa couleur"
        # D06 (Slice 02 de jarvis-board-ui-wheel-dossier-refactor) : plus d'œil permanent au centre d'état.
        assert step["results"]["eye"] is None
        _no_errors(step)


def test_recording_indicator_distinct_from_counters_and_stops(tmp_path):
    chip = r"""(()=>{const c=document.querySelector('#recIndicators .ri-chip');if(!c)return null;const r=c.getBoundingClientRect();
      const pills=document.getElementById('bgPills').getBoundingClientRect();
      return {label:c.getAttribute('aria-label'),text:c.textContent.replace(/\s+/g,' ').trim(),cls:c.className,state:c.dataset.riState,
        bgpill:c.classList.contains('bgpill'),left:r.left,top:r.top,bottom:r.bottom,pillsTop:pills.top,inCentre:!!c.closest('#statusCentre'),
        desc:c.getAttribute('aria-describedby')?document.getElementById(c.getAttribute('aria-describedby')).textContent:null}})()"""
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": {"captures": [SCREEN_CAPTURE]}, "actions": [
        ["eval", "chip", chip, 1200],
        ["eval", "chip2", chip, 100],
        *_shot("status-centre-recording-1440x900"),
        ["click", "stop", "#recIndicators .ri-chip", 2500],
        ["eval", "after", chip, 100],
        ["eval", "pills", PILLS, 100],
    ]}])[0]
    first, second = step["results"]["chip"], step["results"]["chip2"]
    assert first and not first["inCentre"] and not first["bgpill"]
    assert first["state"] == "active" and "REC" in first["text"]
    # Slice 04 de la refonte roue/dossier (docs/06 › E) : en haut à gauche, loin des pastilles du bas ; un
    # enregistrement ne se lit pas comme un compteur.
    assert round(first["left"]) == 18 and round(first["top"]) == 18 and first["bottom"] < first["pillsTop"] / 2
    # Le nom ne bouge pas avec le temps ; la durée est la description (et ce que l'œil lit).
    assert first["label"] == second["label"] and not any(ch.isdigit() for ch in first["label"])
    assert first["desc"].startswith("en cours depuis 1:0")
    # L'activer arrête **cette** capture ; elle part, les pastilles restent.
    assert "POST /api/captures/jcap_s/stop" in step["calls"]
    assert step["results"]["after"] is None
    assert [p["cat"] for p in step["results"]["pills"]] == ["failed", "attention", "done", "said"]
    _no_errors(step)


# ------------------------------------------------------------------ géométrie


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("status-centre")
    plan = []
    for theme in THEMES:
        for width, height in VIEWPORTS:
            name = f"status-centre-{theme}-{width}x{height}"
            plan.append({"width": width, "height": height, "theme": theme, "seed": {"captures": [SCREEN_CAPTURE]},
                         "actions": [["eval", "tray", TRAY, 300], ["eval", "boxes", BOXES, 100], *_shot(name)]})
    steps = _drive(tmp, plan)
    out = {}
    index = 0
    for theme in THEMES:
        for size in VIEWPORTS:
            out[(theme, size)] = steps[index]
            index += 1
    return out


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("size", VIEWPORTS)
def test_no_overlap_with_board_card_rail_chat_tab_tray_at_1440_1280_900_600(measured, theme, size):
    step = measured[(theme, size)]
    seen = step["results"]["boxes"]
    assert seen["theme"] == ("cosmos" if theme == "cosmos" else seen["theme"])
    every = seen["items"]
    ids = [i["id"] for i in every]
    # L'enregistrement (haut-gauche depuis la Slice 04 de la refonte), quatre pastilles ; au rang 40. Plus d'œil (D06).
    assert ids == ["jcap_s", "failed", "attention", "done", "said"], ids
    rec = every[0]["box"]
    gutter = 18 if seen["vw"] > 700 else 10
    assert round(rec["l"]) == gutter and round(rec["t"]) == gutter, rec
    for name in ("card", "chatTab", "rail", "railTab", "wheel", "dock", "tray", "scStatus"):
        assert not _overlap(rec, seen[name]), ("enregistrement", name, rec, seen[name])
    # Le centre d'état du bas ne tient plus que les pastilles.
    items = every[1:]
    assert seen["eyeHost"] is False
    assert seen["z"] == {"pills": "40", "rec": "40"}
    others = {name: seen[name] for name in ("card", "chatTab", "rail", "railTab", "wheel")}
    assert others["card"] and others["chatTab"] and (others["rail"] or others["railTab"]), others
    for item in items:
        box = item["box"]
        assert 0 <= box["l"] and box["r"] <= seen["vw"] and box["b"] <= seen["vh"], item
        for name, other in others.items():
            assert not _overlap(box, other), (item["id"], name, box, other)
        # Le plateau de dépôt est au-dessus de la rangée (ou en haut, sur un écran étroit).
        assert not _overlap(box, seen["tray"]), (item["id"], box, seen["tray"])
    tray = seen["tray"]
    assert tray, "le plateau est mesuré"
    top = min(item["box"]["t"] for item in items)
    assert tray["b"] <= top or tray["t"] < 200
    # Les pastilles sont sur une seule rangée centrée, en bas.
    rows = {round(item["box"]["t"]) for item in items if item["id"] != "jcap_s"}
    assert len(rows) == 1, rows
    assert not seen["overflowX"]
    _no_errors(step)


@pytest.mark.parametrize("size", VIEWPORTS)
def test_status_centre_clears_open_chat_panel(tmp_path, size):
    width, height = size
    step = _drive(tmp_path, [{"width": width, "height": height, "seed": {"captures": [SCREEN_CAPTURE]}, "actions": [
        ["click", "open", "#chatTab", 900],
        ["eval", "boxes", BOXES, 100],
        *_shot(f"status-centre-chat-open-{width}x{height}"),
    ]}])[0]
    seen = step["results"]["boxes"]
    panel = seen["chatPanel"]
    assert panel, "le panneau Chat est ouvert"
    items = seen["items"]
    assert "hiddenEye" not in [i["id"] for i in items] and len(items) == 5, items
    for item in items:
        assert not _overlap(item["box"], panel), (item["id"], item["box"], panel)
    if width >= 1100:
        # Assez de place : la rangée se recentre dans l'espace libre, à gauche du panneau.
        assert max(item["box"]["r"] for item in items) < panel["l"]
    _no_errors(step)


def test_no_voicehint_and_f9_still_wakes(tmp_path):
    """Ni capsule (orbital-ui S06) ni ligne d'état (Slice 02, D05) ; depuis la Slice 04 de la refonte, la touche
    se lit dans le sous-menu JARVIS de la roue (`test_jarvis_wheel_browser.py`), plus dans un `#wakeHint` caché."""
    state = r"""(()=>({hint:!!document.getElementById('voiceHint')||!!document.querySelector('.voicehint'),
        stateLine:!!document.querySelector('.topbar,.state'),wakeHint:!!document.getElementById('wakeHint'),
        text:window.JarvisRuntimeWheel.wakeHint()}))()"""
    steps = _drive(tmp_path, [
        {"width": 1280, "height": 720, "actions": [["eval", "state", state, 100]]},
        {"width": 1280, "height": 720, "seed": {"wakeKey": "f10"}, "actions": [["eval", "state", state, 100]]},
    ])
    assert steps[0]["results"]["state"] == {"hint": False, "stateLine": False, "wakeHint": False, "text": "F9 · DÉMARRER"}
    # Le texte suit la touche réglée, à chaque statut.
    assert steps[1]["results"]["state"]["text"] == "F10 · DÉMARRER"
    # La touche elle-même est le raccourci global de Voice : la page n'y est pour rien, et rien n'a bougé.
    assert activation_source_for_label("f9") is ExplicitAddressSource.MANUAL_KEY
    assert activation_source_for_label("F10", manual_key="f10") is ExplicitAddressSource.MANUAL_KEY


# ------------------------------------------------------------------ l'œil
#
# Slice 02 de jarvis-board-ui-wheel-dossier-refactor (D06) : la page ne déclare plus
# l'œil. Sa mécanique reste dans `control_center_scene_page.js` pour la Slice 06
# (Sélection) ; les tests ci-dessous la tiennent avec un hôte rétabli par le test
# (`EYE_HOST`), comme Sélection le déclarera.


def test_without_an_eye_host_a_stored_ghost_view_draws_no_ghost(tmp_path):
    """Un navigateur qui avait allumé l'œil garde `showHidden: true` : sans hôte, aucun fantôme ne
    s'impose sans moyen de l'éteindre ; c'est dit une fois au journal, et le réglage est gardé."""
    ghosts = r"""[...document.querySelectorAll('#sceneLayer [data-object-id]')].map(n=>({id:n.dataset.objectId,
      ghost:n.classList.contains('sc-ghost')}))"""
    stored = "(()=>{try{return JSON.parse(localStorage.getItem('jarvis.scene.view')||'null')}catch(_){return 'refused'}})()"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "storage": {"version": 1, "view": {"showHidden": True}},
                              "actions": [["eval", "nodes", ghosts, 1500], ["eval", "stored", stored, 100],
                                          ["eval", "eye", "!!document.getElementById('hiddenEye')", 50]]}])[0]
    r = step["results"]
    assert r["eye"] is False
    assert [n["id"] for n in r["nodes"]] == ["jobj_star"] and not any(n["ghost"] for n in r["nodes"]), r["nodes"]
    assert r["stored"]["view"]["showHidden"] is True, "the browser's view preference is kept for Sélection"
    assert sum("scene.hidden_view_withheld" in line["text"] for line in step["console"]) == 1, step["console"]
    _no_errors(step)


def test_eye_toggle_aria_pressed_and_secondary_lists_hidden(tmp_path):
    eye = r"""(()=>{const e=document.getElementById('hiddenEye');return {pressed:e.getAttribute('aria-pressed'),
      label:e.getAttribute('aria-label'),disabled:e.getAttribute('aria-disabled'),hidden:e.hidden}})()"""
    ghosts = r"""[...document.querySelectorAll('#sceneLayer [data-object-id]')].map(n=>({id:n.dataset.objectId,
      ghost:n.classList.contains('sc-ghost'),label:n.getAttribute('aria-label')}))"""
    menu = r"""(()=>{const m=document.getElementById('ctxMenu');return m.hidden?null:{title:(m.querySelector('.mhead')||{}).textContent,
      items:[...m.querySelectorAll('button[role=menuitem]')].map(b=>b.textContent)}})()"""
    stored = "(()=>{try{return JSON.parse(localStorage.getItem('jarvis.scene.view')||'null')}catch(_){return 'refused'}})()"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "actions": [
        EYE_HOST,
        ["eval", "before", eye, 100],
        ["eval", "nodesBefore", ghosts, 100],
        ["click", "toggle", "#hiddenEye", 900],
        ["eval", "on", eye, 100],
        ["eval", "nodesOn", ghosts, 100],
        ["eval", "stored", stored, 100],
        *_shot("status-centre-eye-on-1440x900"),
        ["rclick", "secondary", "#hiddenEye", 500],
        ["eval", "list", menu, 100],
        *_shot("status-centre-eye-list-1440x900"),
        ["key", "esc", "Escape", 300],
        ["eval", "closed", menu, 100],
        ["eval", "focus", "document.getElementById('hiddenEye').focus();1", 100],
        ["key", "shiftF10", "F10", 500, True],
        ["eval", "listKbd", menu, 100],
        ["key", "esc2", "Escape", 300],
        ["rclick", "ghostMenu", '#sceneLayer [data-object-id="jobj_hidden_win"]', 500],
        ["eval", "ghostList", menu, 100],
        ["eval", "sentBefore", "window.__sc.bodies.filter(b=>b.path==='/api/scene/commands').length", 100],
        *_shot("status-centre-ghost-menu-1440x900"),
        ["click", "reveal", '#ctxMenu [data-act="reveal"]', 2500],
        ["eval", "nodesAfter", ghosts, 100],
        ["eval", "after", eye, 100],
        ["click", "toggleOff", "#hiddenEye", 900],
        ["eval", "off", eye, 100],
        ["eval", "nodesOff", ghosts, 100],
    ]}])[0]
    r = step["results"]
    assert r["before"] == {"pressed": "false", "label": "Afficher les objets masqués (3)", "disabled": "false", "hidden": False}
    assert [n["id"] for n in r["nodesBefore"]] == ["jobj_star"]
    # Allumé : pressé, nom inverse ; deux fantômes (le masqué sans place n'en a pas), dits « masqué ».
    assert r["on"]["pressed"] == "true" and r["on"]["label"] == "Cacher les objets masqués"
    ghosts_on = {n["id"]: n for n in r["nodesOn"]}
    assert set(ghosts_on) == {"jobj_star", "jobj_hidden", "jobj_hidden_win"}
    assert ghosts_on["jobj_hidden"]["ghost"] and ghosts_on["jobj_hidden_win"]["ghost"] and not ghosts_on["jobj_star"]["ghost"]
    assert ghosts_on["jobj_hidden_win"]["label"].endswith("masqué")
    # Une décision de vue de ce navigateur : stockée là, rien d'envoyé à Core par l'œil.
    assert r["stored"]["view"]["showHidden"] is True
    # Activation secondaire (clic droit, puis Maj+F10 au clavier) : la liste existante.
    expected = {"title": "3 objets masqués", "items": ["Afficher « Recherche masquée »", "Afficher « Rapport masqué »",
                                                       "Afficher « Sans place »", "Tout réafficher (3)"]}
    assert r["list"] == expected
    assert r["closed"] is None
    assert r["listKbd"] == expected
    # Un fantôme : « Réafficher » seulement, et c'est un seul `set_visibility visible`.
    assert r["ghostList"]["items"] == ["Réafficher"]
    # Rien n'a été écrit par l'œil ni par les fantômes avant « Réafficher ».
    assert r["sentBefore"] == 0
    sent = [b["body"] for b in step["bodies"] if b["path"] == "/api/scene/commands"]
    assert [b for b in sent if b["op"] == "set_visibility"] == [
        {"schema_version": 1, "op": "set_visibility", "object_id": "jobj_hidden_win", "visibility": "visible"}]
    # Réaffiché, l'objet redevient une fenêtre ordinaire ; sa place peut alors être
    # validée comme celle de tout objet visible (jamais pendant qu'il était fantôme).
    assert {b["op"] for b in sent} <= {"set_visibility", "set_geometry"}
    after = {n["id"]: n for n in r["nodesAfter"]}
    assert after["jobj_hidden_win"]["ghost"] is False
    assert r["after"]["label"] == "Cacher les objets masqués" and r["after"]["pressed"] == "true"
    # Éteint : les fantômes partent, l'objet réaffiché reste ; le compte a baissé.
    assert r["off"] == {"pressed": "false", "label": "Afficher les objets masqués (2)", "disabled": "false", "hidden": False}
    assert sorted(n["id"] for n in r["nodesOff"]) == ["jobj_hidden_win", "jobj_star"]
    _no_errors(step)


def test_eye_is_inert_looking_without_hidden_objects_and_hidden_without_scene(tmp_path):
    eye = r"""(()=>{const e=document.getElementById('hiddenEye');return {pressed:e.getAttribute('aria-pressed'),
      label:e.getAttribute('aria-label'),disabled:e.getAttribute('aria-disabled'),hidden:e.hidden,
      opacity:getComputedStyle(e).opacity}})()"""
    visible_only = [{"schema_version": 1, "object_id": "jobj_star", "kind": "agent", "category": "agent", "exec_state": "running",
                     "representation": "point", "geometry": {"x": -60, "y": -30, "w": 6, "h": 6}, "layer": 100, "order": 0,
                     "visibility": "visible", "disposition": "active", "constraints": {"placed_by": "user", "pinned_by_user": False},
                     "origin": "runtime", "work_ref": None, "payload": {"title": "Analyse", "summary": "", "items": []}}]
    steps = _drive(tmp_path, [
        {"width": 1280, "height": 720, "seed": {"objects": visible_only}, "actions": [
            EYE_HOST, ["eval", "eye", eye, 100], ["click", "click", "#hiddenEye", 600], ["eval", "after", eye, 100]]},
        {"width": 1280, "height": 720, "seed": {"sceneOn": False}, "actions": [EYE_HOST, ["eval", "eye", eye, 100]]},
    ])
    inert = steps[0]["results"]
    # L'air inerte était la feuille de la page, retirée avec l'hôte (Slice 02) : la mécanique dit l'état par ses attributs.
    assert inert["eye"]["label"] == "Aucun objet masqué" and inert["eye"]["disabled"] == "true"
    assert inert["eye"]["hidden"] is False
    # Un clic n'allume rien quand il n'y a rien à montrer.
    assert inert["after"]["pressed"] == "false"
    assert steps[1]["results"]["eye"]["hidden"] is True
    for step in steps:
        _no_errors(step)


@pytest.mark.parametrize("size", [(1000, 700), (1440, 900)])
def test_toasts_never_cover_the_capture_note_or_its_close(tmp_path, size):
    """QA S04 P4 : à 1000×700 et 1440×900 les infusions couvraient les puces
    d'indicateurs et le × de la note d'un refus. La note s'ouvre désormais
    au-dessus du centre d'état, et les infusions montent au-dessus d'elle tant
    qu'elle est là."""

    width, height = size
    read = r"""(()=>{const box=el=>{if(!el||el.hidden)return null;const r=el.getBoundingClientRect();
        return r.width?{l:r.left,t:r.top,r:r.right,b:r.bottom}:null};
      const close=document.querySelector('#recIndicatorsNote .ri-note-close');const c=close&&close.getBoundingClientRect();
      const hit=c?document.elementFromPoint(c.left+c.width/2,c.top+c.height/2):null;
      return {note:box(document.getElementById('recIndicatorsNote')),toasts:[...document.querySelectorAll('#toasts .toast')].map(box),
        closeHit:!!(hit&&close.contains(hit)),items:[...document.querySelectorAll('#bgPills .bgpill')].map(box),
        text:(document.querySelector('#recIndicatorsNote span')||{}).textContent||''}})()"""
    step = _drive(tmp_path, [{"width": width, "height": height, "actions": [
        ["eval", "start", "window.JarvisCaptureRail.act('audio');1", 1500],
        ["eval", "toast", "toast({title:'Notification',sub:'Une notification de hauteur ordinaire, sur deux lignes au moins pour la mesure.'});"
                          "toast({title:'Seconde',sub:'Une autre.'});1", 600],
        ["eval", "seen", read, 100],
        *_shot(f"status-centre-note-and-toasts-{width}x{height}"),
    ]}])[0]
    seen = step["results"]["seen"]
    assert seen["note"] and "non démarré" in seen["text"], seen
    assert seen["toasts"] and all(seen["toasts"])
    for toast in seen["toasts"]:
        assert not _overlap(toast, seen["note"]), (toast, seen["note"])
        for item in seen["items"]:
            assert not _overlap(toast, item), (toast, item)
    assert seen["closeHit"] is True, "le × de la note reçoit le clic"
    # La note est au-dessus de la rangée, jamais dessus.
    for item in seen["items"]:
        assert not _overlap(item, seen["note"]) and seen["note"]["b"] <= item["t"]


# ------------------------------------------------- S06 rework (QA S06 : B1, P1, P2)

#: La lecture de la scène échoue (Control Center injoignable) : la scène se fige et le dit.
BREAK_SCENE = r"""(()=>{const f=window.fetch;window.fetch=(p,i)=>String(p).startsWith('/api/scene')
  ?Promise.reject(new TypeError('Failed to fetch')):f(p,i);window.__sc.waiters.splice(0).forEach(fn=>fn([]));return 1})()"""

NOTES = r"""(()=>{const box=el=>{if(!el)return null;const r=el.getBoundingClientRect();return r.width>0?{l:r.left,t:r.top,r:r.right,b:r.bottom}:null};
  return {notes:[...document.querySelectorAll('#sceneLayer>.sc-status .sc-note')].map(n=>{const m=n.querySelector('.sc-note-main');
    return {text:n.textContent,main:m.textContent,title:n.title,fits:m.scrollWidth<=m.clientWidth,box:box(n)}}),
    mode:box(document.getElementById('boardsButton')),
    centre:[...document.querySelectorAll('#recIndicators .ri-chip, #bgPills .bgpill')].map(box).filter(Boolean),
    rail:box(document.getElementById('presentationRail')),chatTab:box(document.getElementById('chatTab'))}})()"""


@pytest.mark.parametrize("size", ((1440, 900), (1280, 720)), ids=lambda s: f"{s[0]}x{s[1]}")
def test_degraded_scene_note_reads_whole_cause_without_overlap(tmp_path, size):
    """B1 : au-dessus de 820 px, la note « Scène figée · <cause> » était plafonnée à
    246 px et la cause disparaissait dans les points de suspension. Elle se lit en
    entier, son `title` porte le texte entier, et elle ne touche ni la carte
    Board (ex-bouton de mode, même place) ni le centre d'état."""
    width, height = size
    step = _drive(tmp_path, [{"width": width, "height": height, "actions": [
        ["eval", "break", BREAK_SCENE, 6000],
        ["eval", "seen", NOTES, 100],
        *_shot(f"s06-rework-degraded-note-{width}x{height}"),
    ]}])[0]
    seen = step["results"]["seen"]
    frozen = [n for n in seen["notes"] if n["main"].startswith("Scène")]
    assert frozen, seen["notes"]
    for note in seen["notes"]:
        assert note["fits"], note
        assert note["title"] and note["title"].startswith(note["main"]), note
        for other in [seen["mode"], seen["rail"], seen["chatTab"], *seen["centre"]]:
            assert not _overlap(note["box"], other), (note, other)
    assert "injoignable" in frozen[0]["main"].lower(), frozen[0]


def test_eye_announces_ghosts_and_ghosts_never_move(tmp_path):
    """P1 : l'œil annonce les fantômes dessinés (2 : le masqué sans place n'en a
    pas), et le nombre de la liste (3). P2 : glisser un fantôme ou le pousser au
    clavier (Maj+flèches) n'envoie aucune commande — garde explicite `node.ghost`."""
    live = "(document.querySelector('#sceneLayer .sc-sr-actions')||{}).textContent||''"
    sent = "window.__sc.bodies.filter(b=>b.path==='/api/scene/commands').length"
    ghost = '#sceneLayer [data-object-id="jobj_hidden_win"]'
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "actions": [
        EYE_HOST,
        ["click", "on", "#hiddenEye", 900],
        ["eval", "said", live, 100],
        ["drag", "drag", ghost, 1200, [140, 90]],
        ["eval", "afterDrag", sent, 100],
        ["eval", "focus", f"document.querySelector('{ghost}').focus();document.activeElement.dataset.objectId", 100],
        ["key", "k1", "ArrowRight", 150, True],
        ["key", "k2", "ArrowDown", 150, True],
        ["key", "k3", "ArrowRight", 1500],
        ["eval", "afterKeys", sent, 100],
        ["eval", "keySaid", live, 100],
    ]}])[0]
    r = step["results"]
    assert r["said"] == "2 objets masqués affichés en fantômes ; 3 dans la liste de l’œil.", r["said"]
    assert r["focus"] == "jobj_hidden_win"
    assert r["afterDrag"] == 0 and r["afterKeys"] == 0, r
    assert "réaffichez-le" in r["keySaid"], r["keySaid"]
    _no_errors(step)


def test_a_ghost_is_never_pressed_into_a_gesture_nor_held(tmp_path):
    """QA S08 P4, le comportement que les gardes `node.ghost` protègent, de
    bout en bout : un vrai appui tenu sur un fantôme n'ouvre aucun geste
    (`JarvisScene.inspect().gesture` reste vide) alors que le même appui sur un
    objet visible en ouvre un ; la main (couture `JarvisScene.frames.begin`,
    qui passe par `holdTarget`) ne prend pas un fantôme alors qu'elle prend un
    objet visible ; rien ne part à Core. Le focus qui suit l'appui sélectionne
    le fantôme, comme au clavier (S06 : il reste focalisable pour « Réafficher »).

    Mutation (Slice 09, LOG) : retirer UNE des deux gardes ne fait pas tomber
    ce test, car un fantôme n'a pas de boîte dessinée (`drawnBox` vide : il
    n'entre pas dans la disposition résolue) et `onPointerDown` comme
    `holdTarget` s'arrêtent aussi sur elle. Les gardes sont une seconde serrure
    explicite ; ce test tient la première et la seconde ensemble."""
    ghost = '#sceneLayer [data-object-id="jobj_hidden_win"]'
    gesture = "JSON.stringify(JarvisScene.inspect().gesture)"
    hold = ("(()=>{const g=JarvisScene.frames.begin('jobj_hidden_win');const held=JarvisScene.inspect().holding.slice();"
            "const v=JarvisScene.frames.begin('jobj_star');const both=JarvisScene.inspect().holding.slice();"
            "if(v)JarvisScene.frames.cancel('jobj_star');return {ghost:g,heldAfterGhost:held,visible:!!v,heldAfterVisible:both}})()")
    sent = "window.__sc.bodies.filter(b=>b.path==='/api/scene/commands').length"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "actions": [
        EYE_HOST,
        ["click", "on", "#hiddenEye", 900],
        ["press", "down", ghost, 200],
        ["eval", "pressed", gesture, 50],
        ["release", "up", ghost, 400],
        ["press", "down2", '#sceneLayer [data-object-id="jobj_star"]', 200],
        ["eval", "pressedVisible", gesture, 50],
        ["release", "up2", '#sceneLayer [data-object-id="jobj_star"]', 600],
        ["eval", "hold", hold, 300],
        ["eval", "sent", sent, 100],
    ]}])[0]
    r = step["results"]
    assert r["pressed"] == "null", ("aucun geste sur un fantôme", r["pressed"])
    assert '"id":"jobj_star"' in r["pressedVisible"], ("le même appui sur un objet visible ouvre un geste", r["pressedVisible"])
    assert r["hold"]["ghost"] is None and r["hold"]["heldAfterGhost"] == [], r["hold"]
    assert r["hold"]["visible"] is True and r["hold"]["heldAfterVisible"] == ["jobj_star"], r["hold"]
    assert r["sent"] == 0, r
    _no_errors(step)

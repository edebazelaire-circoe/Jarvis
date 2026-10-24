"""Fondation visuelle des Réglages, dans un vrai Chrome sans tête (refonte-ui-settings, Slice 01).

Contrat : `docs/settings/visual-foundation.md`. Un VRAI Control Center isolé (fixture `served` de
`test_wake_word_settings_browser.py`) sert la page ; l'outillage de capture partagé est `tests/unit/settings_visual.py`.
Ce que ce fichier prouve :

- chaque vue cible (hub, Personnalisation, Sous-agents, Architecture, Mémoire, Memory Center) s'ouvre, se fige et se
  photographie à sa fenêtre de référence et à la fenêtre étroite, sans défilement horizontal de la page ;
- les primitives partagées (`.set-*` de la fondation, montées par `JarvisSettingsUI`) : focus clavier visible,
  état désactivé lisible et inerte, état « en cours » (`aria-busy`), interrupteur et curseur qui suivent leur
  valeur, compteur de zone de texte ;
- la grille de 12 colonnes passe à 3, 2 puis 1 colonne sans débordement horizontal aux fenêtres de référence, à la
  fenêtre étroite et à 125 % de zoom ;
- un panneau flottant reste au-dessus de la grille et rend le focus à son déclencheur ;
- `prefers-reduced-motion` coupe les transitions des primitives ;
- une fixture `stub` répond à la page sans toucher le serveur.

Se saute si Chrome ou node manque. `JARVIS_BROWSER_SHOTS=<dossier>` garde les captures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.settings_visual import (
    OVERFLOW, REFERENCE_VIEWPORT, VIEWPORTS, VIEWS, capture_steps, freeze, shot, shots_dir, stub, zoomed,
)
from tests.unit.test_wake_word_settings_browser import drive, eval_, got, key, served, type_in, wait  # noqa: F401

GALLERY_JS = Path(__file__).with_name("_settings_primitives_gallery.js")


@pytest.mark.parametrize("view", list(VIEWS))
async def test_each_target_view_opens_and_captures_without_page_overflow(served, tmp_path, view):
    shots = shots_dir(tmp_path, "views")
    names = [REFERENCE_VIEWPORT[view], "narrow"]
    out = await drive(served.url, capture_steps(VIEWS[view], shots, view, viewports=names, ext="jpg"))
    assert out["console"] == [], out["console"]
    for name, step in zip(names, out["steps"]):
        waits = [a for a in step["actions"] if a.get("a") == "wait"]
        assert all(a["ok"] for a in waits), (view, name, [a for a in waits if not a["ok"]])
        assert got(step, "overflow")["page"] == 0, (view, name, got(step, "overflow"))
        width, height = VIEWPORTS[name]
        assert (shots / f"{view}-{width}x{height}.jpg").stat().st_size > 10_000


# ------------------------------------------------------------ galerie des primitives

def mount_gallery() -> dict:
    return {"a": "script", "path": str(GALLERY_JS), "then": "mountSettingsGallery()", "id": "mounted"}


GALLERY_OPEN = [wait("!!window.JarvisSettingsUI&&!!document.getElementById('overlay')"), mount_gallery(),
                wait("!!document.querySelector('#galGrid .set-panel')")]

#: Colonnes de la grille, panneaux d'une même rangée, débordements (page, vue, chaque panneau).
GRID = """(()=>{const g=document.getElementById('galGrid'),view=document.getElementById('setGallery');
  const kids=[...g.children].map(c=>c.getBoundingClientRect());
  return {cols:getComputedStyle(g).gridTemplateColumns.split(' ').length,
    perRow:kids.filter(r=>Math.abs(r.top-kids[0].top)<1).length,
    page:Math.max(0,document.documentElement.scrollWidth-innerWidth),view:Math.max(0,view.scrollWidth-view.clientWidth),
    panels:[...g.querySelectorAll('.set-panel')].filter(p=>p.scrollWidth>p.clientWidth+1).map(p=>p.id),
    outside:[...view.querySelectorAll('.set-panel *')].filter(e=>{const r=e.getBoundingClientRect(),p=e.closest('.set-panel').getBoundingClientRect();
      return e.getClientRects().length&&!e.closest('.set-float,.set-table-scroll')&&(r.left<p.left-1||r.right>p.right+1)}).map(e=>e.id||e.className).slice(0,5)}})()"""

LAYOUTS = [  # (fenêtre, panneaux attendus sur la première rangée)
    (VIEWPORTS["wide"], 3), (VIEWPORTS["square"], 3), (VIEWPORTS["narrow"], 3),
    (zoomed(VIEWPORTS["wide"]), 3), (zoomed(VIEWPORTS["square"]), 2), ((1000, 800), 2), ((600, 900), 1),
]


async def test_gallery_grid_collapses_three_two_one_without_horizontal_overflow(served, tmp_path):
    shots = shots_dir(tmp_path, "gallery")
    out = await drive(served.url, [{"width": w, "height": h, "actions": [
        *GALLERY_OPEN, freeze(), eval_(GRID, "grid"), shot(shots / f"gallery-{w}x{h}.jpg")]} for (w, h), _ in LAYOUTS])
    assert out["console"] == [], out["console"]
    for ((w, h), per_row), step in zip(LAYOUTS, out["steps"]):
        grid = got(step, "grid")
        assert grid["perRow"] == per_row, ((w, h), grid)
        assert grid["page"] == 0 and grid["view"] == 0, ((w, h), grid)
        assert grid["panels"] == [] and grid["outside"] == [], ((w, h), grid)


PROBE = """(()=>{const e=document.activeElement,ring=e.closest('.set-choice')||e,cs=getComputedStyle(ring);
  (window.__seen=window.__seen||[]).push({id:e.id,cls:String(e.className||''),tag:e.tagName,type:e.type||'',
    inside:!!e.closest('#setGallery'),outline:cs.outlineStyle,width:parseFloat(cs.outlineWidth)||0,disabled:!!e.disabled});return 1})()"""


async def test_gallery_controls_show_focus_and_disabled_states_from_the_keyboard(served):
    tabs = []
    for _ in range(22):
        tabs += [key("Tab"), eval_(PROBE)]
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *GALLERY_OPEN, eval_("(document.getElementById('setGallery').tabIndex=-1,document.getElementById('setGallery').focus(),1)"),
        *tabs, eval_("window.__seen", "seen"),
        eval_("""(()=>{const s=id=>getComputedStyle(document.getElementById(id));return {
          disabled:{opacity:s('galDisabled').opacity,cursor:s('galDisabled').cursor,native:document.getElementById('galDisabled').disabled},
          busy:{anim:getComputedStyle(document.getElementById('galBusy'),'::after').animationName,
            aria:document.getElementById('galBusy').getAttribute('aria-busy'),native:document.getElementById('galBusy').disabled},
          range:{opacity:s('galHumour').opacity}}})()""", "states"),
    ]}])
    assert out["console"] == [], out["console"]
    step = out["steps"][0]
    seen = [s for s in got(step, "seen") if s["inside"]]
    assert len(seen) >= 12, seen
    missing = [s for s in seen if s["outline"] in ("none", "") or s["width"] < 2]
    assert missing == [], missing  # chaque arrêt de Tab montre son anneau
    assert not any(s["disabled"] for s in seen)  # un contrôle désactivé n'est jamais un arrêt de Tab
    reached = " ".join(f"{s['tag']}.{s['cls']}.{s['type']}" for s in seen)
    for needle in ("set-tab", "SELECT", "set-btn", "set-range", "TEXTAREA", "radio", "set-switch", "set-table-scroll"):
        assert needle in reached, (needle, reached)
    states = got(step, "states")
    assert float(states["disabled"]["opacity"]) < 1 and states["disabled"]["cursor"] == "not-allowed" and states["disabled"]["native"]
    assert states["busy"] == {"anim": "set-spin", "aria": "true", "native": True}
    assert float(states["range"]["opacity"]) < 1


VALUES = """(()=>{const q=s=>document.querySelector(s),r=q('#galRange');return {
  range:r.value,fill:r.style.getPropertyValue('--set-range-fill'),out:q('#galRange-value').textContent,valuetext:r.getAttribute('aria-valuetext'),
  count:q('#galText-count').textContent,t2:q('#galT2').getAttribute('aria-checked'),t3:q('#galT3').getAttribute('aria-checked'),
  master:[q('#galMaster').getAttribute('aria-checked'),q('#galMaster .set-switch-text').textContent],
  tab:(q('#galTabs [aria-selected=true]')||{}).id,focus:document.activeElement.id}})()"""

FLOAT = """(()=>{const p=document.getElementById('galFloat'),r=p.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
  return {hidden:p.hidden,top:!!hit&&p.contains(hit),expanded:document.getElementById('galOpenFloat').getAttribute('aria-expanded'),
    focusInside:p.contains(document.activeElement),focus:document.activeElement.id,overlay:document.getElementById('overlay').classList.contains('open'),
    z:getComputedStyle(p).zIndex}})()"""


async def test_gallery_controls_follow_their_value_and_the_floating_panel_returns_focus(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *GALLERY_OPEN,
        eval_("(document.getElementById('galRange').focus(),1)"), key("ArrowLeft"),
        type_in("#galText", "Bonjour"),
        {"a": "click", "selector": "#galT2"}, {"a": "click", "selector": "#galT3"}, {"a": "click", "selector": "#galMaster"},
        eval_("(document.getElementById('galTabs-one').focus(),1)"), key("ArrowRight"),
        eval_(VALUES, "values"),
        key("End"), eval_("document.querySelector('#galTabs [aria-selected=true]').id", "end"),
        {"a": "click", "selector": "#galOpenFloat"}, eval_(FLOAT, "opened"),
        key("Escape"), eval_(FLOAT, "escaped"),
        {"a": "click", "selector": "#galOpenFloat"}, {"a": "click", "selector": "#galTable .set-panel-title"}, eval_(FLOAT, "outside"),
    ]}])
    assert out["console"] == [], out["console"]
    step = out["steps"][0]
    values = got(step, "values")
    assert values["range"] == "75" and values["fill"] == "75%" and values["out"] == "75 %" and values["valuetext"] == "75 %", values
    assert values["count"] == "7/120", values
    assert values["t2"] == "true" and values["t3"] == "true", values  # le désactivé n'a pas bougé
    assert values["master"] == ["false", "Désactivé"], values
    assert values["tab"] == "galTabs-two" and values["focus"] == "galTabs-two", values
    assert got(step, "end") == "galTabs-three"
    opened = got(step, "opened")
    assert opened["hidden"] is False and opened["top"] and opened["expanded"] == "true" and opened["focusInside"], opened
    assert opened["z"] == "20", opened
    escaped = got(step, "escaped")
    assert escaped["hidden"] is True and escaped["focus"] == "galOpenFloat" and escaped["expanded"] == "false", escaped
    assert escaped["overlay"] is True, escaped  # Échap a fermé le panneau, pas les Réglages
    assert got(step, "outside")["hidden"] is True


MOTION = """(()=>{const t=document.querySelector('#galT1 .set-switch-track');return {
  track:getComputedStyle(t).transitionDuration,btn:getComputedStyle(document.getElementById('galPrimary')).transitionDuration,
  busy:getComputedStyle(document.getElementById('galBusy'),'::after').animationName}})()"""


async def test_reduced_motion_stops_primitive_transitions(served):
    out = await drive(served.url, [
        {"width": 1440, "height": 900, "reducedMotion": True, "actions": [*GALLERY_OPEN, eval_(MOTION, "m")]},
        {"width": 1440, "height": 900, "actions": [*GALLERY_OPEN, eval_(MOTION, "m")]},
    ])
    reduced, normal = got(out["steps"][0], "m"), got(out["steps"][1], "m")
    assert set(reduced["track"].split(", ")) == {"0s"} and set(reduced["btn"].split(", ")) == {"0s"}, reduced
    assert reduced["busy"] == "none", reduced
    assert "0.18s" in normal["track"] and normal["busy"] == "set-spin", normal


async def test_stub_fixture_answers_the_page_without_the_server(served):
    probe = "fetch('/api/visual-fixture-probe').then(r=>r.json().then(j=>({status:r.status,body:j})))"
    real = "fetch('/api/visual-fixture-probe').then(r=>({status:r.status}))"
    out = await drive(served.url, [
        {"width": 1280, "height": 800, "stubs": [stub("/api/visual-fixture-probe", {"notes": 3, "label": "fixture"})],
         "actions": [eval_(probe, "stubbed")]},
        {"width": 1280, "height": 800, "actions": [eval_(real, "real")]},
    ])
    assert got(out["steps"][0], "stubbed") == {"status": 200, "body": {"notes": 3, "label": "fixture"}}
    assert got(out["steps"][1], "real")["status"] == 404  # sans fixture, le vrai serveur ne connaît pas la route


#: Liaisons détachées : plus aucune réaction ; `openFloat` deux fois sur le même panneau = un seul jeu d'écouteurs.
DETACH = """(()=>{const UI=window.JarvisSettingsUI,host=document.createElement('div');document.body.append(host);
  host.innerHTML=UI.range({id:'dtR',label:'r',min:0,max:10,value:5,suffix:' u'})+UI.textarea({id:'dtT',label:'t',maxLength:9})
    +UI.tabs({id:'dtTabs',label:'o',items:[{id:'a',label:'A'},{id:'b',label:'B'}]})+UI.toggle({id:'dtS',label:'s'})
    +UI.button({id:'dtOpen',label:'Ouvrir'})+UI.float({id:'dtF',title:'F',body:'<button type=button id=dtIn>x</button>'});
  const q=s=>host.querySelector(s),r=q('#dtR'),t=q('#dtT'),list=q('#dtTabs'),sw=q('#dtS'),panel=q('#dtF');
  let selected=0,toggled=0,closed=0;
  const offAll=UI.bindAll(host),offTabs=UI.wireTabs(list,()=>selected++),offSwitch=UI.bindToggle(sw,()=>toggled++),offRange=UI.bindRange(r);
  offAll();offTabs();offSwitch();offRange();
  r.value='9';r.dispatchEvent(new Event('input'));t.value='abcdef';t.dispatchEvent(new Event('input'));
  q('#dtTabs-b').click();q('#dtTabs-a').dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true}));sw.click();
  const after={out:q('#dtR-value').textContent,count:q('#dtT-count').textContent,selected,toggled,
    tab:list.querySelector('[aria-selected=true]').id,checked:sw.getAttribute('aria-checked')};
  const opts={trigger:q('#dtOpen'),onClose:()=>closed++};
  const c1=UI.openFloat(panel,opts),c2=UI.openFloat(panel,opts);
  panel.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  const once={same:c1===c2,closed,hidden:panel.hidden};
  panel.hidden=false;panel.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  document.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
  const detached={closed,again:c1()};host.remove();return {after,once,detached}})()"""


async def test_detached_bindings_no_longer_react_and_open_float_is_idempotent(served):
    out = await drive(served.url, [{"width": 1280, "height": 800, "actions": [
        wait("!!window.JarvisSettingsUI"), eval_(DETACH, "detach")]}])
    assert out["console"] == [], out["console"]
    seen = got(out["steps"][0], "detach")
    assert seen["after"] == {"out": "5 u", "count": "0/9", "selected": 0, "toggled": 0, "tab": "dtTabs-a", "checked": "false"}, seen
    assert seen["once"] == {"same": True, "closed": 1, "hidden": True}, seen  # un seul Échap traité, une seule fermeture
    assert seen["detached"] == {"closed": 1, "again": False}, seen  # fermé : plus d'écouteur, `close` sans effet

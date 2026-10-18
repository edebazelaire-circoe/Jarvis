"""La roue d'outils dans Chrome : vrais événements souris et clavier, pointeur Bare Hands.

Contrat : `docs/control-center-shell.md` › Tool wheel (orbital-ui Slice 02).
`test_tool_wheel_js.py` tient le modèle pur ; ce fichier charge la page
**servie** (composée comme `ControlCenter.index`) — la roue y est construite
d'office depuis la Slice 04 —, branche cinq actions qui notent leurs appels (les
cinq catégories de la refonte S03 de `jarvis-board-ui-wheel-dossier-refactor`), et
conduit la roue :

- souris : de vrais `Input.dispatchMouseEvent` (CDP) vers l'ancre, un
  secteur, puis loin ; la roue se ferme après le délai de grâce ;
- clavier : de vraies frappes (Entrée, flèches, Maj+F10, Échap, Tab) ;
- Bare Hands : la séquence exacte que `control_center_barehands.js` envoie
  (`pointerover`/`mouseover` sur l'élément interactif sous le jeton, puis
  `pointerdown`, `mousedown`, `pointerup`, `mouseup`, `click`), sous le
  `pointerId` que le contrat Bare Hands donne à la fente 0 (9001) ;
- mouvement réduit, focus, et un pointeur lointain qui n'ouvre jamais rien.

Captures d'écran : dans `tmp_path`, ou dans `$TOOL_WHEEL_SHOTS` s'il est
défini (preuves de la Slice). Harnais : `_interaction_mode_browser.mjs`. Se
saute proprement sans Chrome ni node.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.unit.test_boards_card_browser import HARNESS, _chrome, _served_page

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_tool_wheel.js"
W, H = 1440, 900

#: Branche cinq actions qui notent leurs appels (la roue est construite d'office), à la place
#: des gestionnaires réels et d'attente. Sélection propose un sous-menu à deux choix, les autres
#: un seul choix informatif ; aucune n'a `menu` : l'activation principale agit.
SETUP = r"""(()=>{
  const theme=%s;
  if(theme&&window.JarvisThemeAPI)window.JarvisThemeAPI.activate(theme,{persist:false});
  const Wh=window.JarvisToolWheel;
  if(!Wh)return {error:'module absent'};
  const builtAtLoad=!!document.querySelector('#toolWheel .tw-anchor'),hiddenBefore=document.getElementById('toolWheel').hidden;
  window.__tw={activate:[],secondary:[],items:[],logs:[]};
  const info=console.info.bind(console);
  console.info=(...a)=>{window.__tw.logs.push(String(a[0]));info(...a)};
  /* Les vues de capture projettent l'état de Core sur Capture ; ce fichier
     éprouve la roue seule. */
  Wh.setStatus('capture',null);
  if(window.JarvisCaptureRail)window.JarvisCaptureRail.subscribe(()=>{Wh.setStatus('capture',null)});
  for(const id of Wh.SLOTS.map(s=>s.id))Wh.register({id,
    onActivate:ctx=>{window.__tw.activate.push(ctx)},
    onSecondary:ctx=>{window.__tw.secondary.push(ctx);
      const pick=c=>{window.__tw.items.push(c)};
      return id==='selection'
        ?[{id:'mouse',label:'Souris',checked:true,onActivate:pick},{id:'barehands',label:'Bare Hands',checked:false,onActivate:pick}]
        :[{id:'default',label:'Écran principal — seule cible disponible',onActivate:pick}]}});
  let refused=null;
  try{Wh.register({id:'filler',onActivate(){}})}catch(e){refused=e.code}
  return {builtAtLoad,hiddenBefore,refused,theme:document.documentElement.getAttribute('data-jarvis-theme')||''};
})()"""

STATE = r"""(()=>{
  const host=document.getElementById('toolWheel');
  const panel=host.querySelector('.tw-panel');
  const cs=getComputedStyle(panel);
  const label=host.querySelector('.tw-label');
  const box=e=>{const r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2,l:r.left,t:r.top,r:r.right,b:r.bottom}};
  const ae=document.activeElement;
  const name=!ae||ae===document.body?'body':ae.dataset&&ae.dataset.twSlot?ae.dataset.twSlot
    :ae.classList.contains('tw-anchor')?'anchor':ae.classList.contains('tw-item')?'item:'+ae.textContent:(ae.id||ae.tagName);
  const visible=[...host.querySelectorAll('*')].filter(e=>{
    const r=e.getBoundingClientRect();const s=getComputedStyle(e);
    return r.width>0&&r.height>0&&s.visibility==='visible'&&!e.closest('[hidden]')&&!e.closest('svg')&&!e.classList.contains('tw-sr')});
  return {open:window.JarvisToolWheel.isOpen(),dataOpen:host.hasAttribute('data-open'),z:getComputedStyle(host).zIndex,
    expanded:host.querySelector('.tw-anchor').getAttribute('aria-expanded'),
    visibility:cs.visibility,opacity:cs.opacity,transition:cs.transitionDuration,
    focused:[...host.querySelectorAll('.tw-wedge.is-focus')].map(b=>b.dataset.twSlot),
    label:label.hidden?null:label.textContent,labelBox:label.hidden?null:box(label),
    visibleKinds:[...new Set(visible.map(e=>e.className&&typeof e.className==='string'?e.className.split(' ')[0]:e.tagName))].sort(),
    active:name,activeInHiddenPanel:!!(ae&&ae.closest&&ae.closest('.tw-panel'))&&cs.visibility!=='visible',
    anchor:box(host.querySelector('.tw-anchor')),
    dots:[...host.querySelectorAll('.tw-dot')].map(box),
    items:[...host.querySelectorAll('.tw-item')].map(b=>({text:b.textContent,role:b.getAttribute('role'),checked:b.getAttribute('aria-checked'),...box(b)})),
    calls:JSON.parse(JSON.stringify({activate:__tw.activate,secondary:__tw.secondary,items:__tw.items})),
    journal:__tw.logs.filter(l=>/tool_wheel\.(open|close) /.test(l)),
    overflowX:document.documentElement.scrollWidth>innerWidth};
})()"""

#: Ce que fait `control_center_barehands.js` (`pointer`, `hover`, `click`)
#: pour une main dans la fente 0, rejoué à l'identique. `%s` : le corps.
BH = r"""(()=>{
  const C=window.JarvisBarehandsContracts;
  const id=C.pointerIdForSlot(0);
  const INTERACTIVE='button,a[href],input,select,textarea,label,summary,[role="button"],[role="tab"],[tabindex]:not([tabindex="-1"]),.choice,.acard,.toast';
  const fire=(type,el,x,y,buttons,button)=>{
    const init={bubbles:true,cancelable:true,composed:true,view:window,clientX:x,clientY:y,button:Number(button)||0,buttons};
    if(type.startsWith('pointer'))el.dispatchEvent(new PointerEvent(type,{...init,pointerId:id,pointerType:C.POINTER_TYPE,isPrimary:true}));
    else el.dispatchEvent(new MouseEvent(type,init));
  };
  let hovered=null;
  const hover=(x,y)=>{
    const raw=document.elementFromPoint(x,y);const el=raw&&raw.closest(INTERACTIVE);
    if(el===hovered)return el;
    if(hovered){fire('pointerout',hovered,0,0,0);fire('mouseout',hovered,0,0,0)}
    hovered=el;
    if(el){fire('pointerover',el,x,y,0);fire('mouseover',el,x,y,0)}
    return el;
  };
  const pinch=(x,y)=>{
    const raw=document.elementFromPoint(x,y);
    fire('pointerdown',raw,x,y,1);fire('mousedown',raw,x,y,1);
    const f=raw.closest('button,a[href],input,select,textarea,summary,[tabindex]');if(f)f.focus({preventScroll:true});
    fire('pointerup',raw,x,y,0);fire('mouseup',raw,x,y,0);fire('click',raw,x,y,0);
  };
  const context=(x,y)=>{const raw=document.elementFromPoint(x,y);fire('contextmenu',raw.closest(INTERACTIVE),x,y,0,2)};
  %s
})()"""

OPENED = "window.JarvisToolWheel.isOpen()&&getComputedStyle(document.querySelector('#toolWheel .tw-panel')).opacity==='1'"
CLOSED = "!window.JarvisToolWheel.isOpen()"


def _geometry() -> list[dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = f"process.stdout.write(JSON.stringify(require({json.dumps(str(MODULE))}).layoutWedges()))"
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _scale(width: int, height: int) -> float:
    """`--tw-scale` de la feuille du module pour cette fenêtre (dernière règle qui s'applique)."""

    scale = 1.0
    if height <= 620:
        scale = 0.86
    if height <= 520:
        scale = 0.76
    if width <= 560:
        scale = 0.84
    return scale


def _dot(wedges: list[dict], index: int, height: int = H, width: int = W) -> tuple[float, float]:
    """Centre d'une icône, roue ouverte : centre de la roue au bord gauche, à mi-hauteur."""

    s = _scale(width, height)
    return wedges[index]["x"] * s, height / 2 + wedges[index]["y"] * s


def _move(x: float, y: float, settle: int = 40) -> dict:
    return {"a": "mouse", "type": "mouseMoved", "x": x, "y": y, "settleMs": settle}


def _setup(theme: str | None = None) -> dict:
    return {"a": "eval", "expr": SETUP % json.dumps(theme)}


def _state() -> dict:
    return {"a": "eval", "expr": STATE}


def _wait(expr: str, ms: int = 3000) -> dict:
    return {"a": "wait", "expr": expr, "timeoutMs": ms}


@pytest.fixture(scope="module")
def shots(tmp_path_factory) -> Path:
    wanted = os.environ.get("TOOL_WHEEL_SHOTS")
    target = Path(wanted) if wanted else tmp_path_factory.mktemp("wheel-shots")
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.fixture(scope="module")
def run(tmp_path_factory, shots):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    wedges = _geometry()
    anchor = (7, H / 2)
    sx, sy = _dot(wedges, 2)  # Dossier
    s0x, s0y = _dot(wedges, 1)  # Sélection
    plan = {
        "mouse": {"width": W, "height": H, "mountPalette": True, "actions": [
            _setup(), _state(),
            {"a": "shot", "path": str(shots / "closed-anchor-circuit.png")},
            _move(400, 450), _move(*anchor), _state(), _wait(OPENED),
            _move(sx, sy), _state(),
            {"a": "shot", "path": str(shots / "open-focused-circuit.png")},
            _move(sx + 40, sy + 4), _state(),
            _move(900, 450, settle=0), _state(), _wait(CLOSED), _state(),
            # Clic souris : une activation, roue refermée.
            _move(*anchor), _wait(OPENED), _move(s0x, s0y),
            {"a": "mouse", "type": "mousePressed", "x": s0x, "y": s0y, "button": "left"},
            {"a": "mouse", "type": "mouseReleased", "x": s0x, "y": s0y, "button": "left"},
            _state(),
            # Clic droit : le sous-arc, puis un choix.
            _move(*anchor), _wait(OPENED), _move(s0x, s0y),
            {"a": "mouse", "type": "mousePressed", "x": s0x, "y": s0y, "button": "right"},
            {"a": "mouse", "type": "mouseReleased", "x": s0x, "y": s0y, "button": "right"},
            _state(),
            {"a": "shot", "path": str(shots / "sub-arc-circuit.png")},
        ]},
        "keyboard": {"width": W, "height": H, "mountPalette": True, "actions": [
            _setup(), {"a": "focus", "selector": "#toolWheel .tw-anchor"},
            {"a": "key", "key": "Enter"}, _state(),
            {"a": "key", "key": "ArrowDown"}, {"a": "key", "key": "ArrowDown"}, {"a": "key", "key": "ArrowDown"},
            {"a": "key", "key": "ArrowDown"}, {"a": "key", "key": "ArrowDown"}, _state(),
            {"a": "key", "key": "End"}, _state(),
            {"a": "key", "key": "F10", "shift": True}, _state(),
            {"a": "key", "key": "ArrowDown"}, _state(),
            {"a": "key", "key": "Escape"}, _state(),
            {"a": "key", "key": "Escape"}, _state(),
            {"a": "key", "key": "ArrowRight"}, {"a": "key", "key": "ArrowDown"}, {"a": "key", "key": "Enter"}, _state(),
            {"a": "key", "key": "Enter"}, {"a": "key", "key": "Tab"}, _state(),
        ]},
        "barehands": {"width": W, "height": H, "mountPalette": True, "actions": [
            _setup(),
            {"a": "eval", "expr": BH % f"const a=hover({anchor[0]},{anchor[1]});return {{id,hit:a&&a.className,open:JarvisToolWheel.isOpen()}};"},
            _wait(OPENED),
            {"a": "eval", "expr": BH % (
                f"const out={{}};const el=hover({sx},{sy});out.hover=el&&el.dataset.twSlot;"
                f"out.rim=document.elementFromPoint({wedges[2]['x'] * 210 / 150},{H / 2 + wedges[2]['y'] * 210 / 150}).closest('.tw-wedge').dataset.twSlot;"
                f"pinch({sx},{sy});out.after=JSON.parse(JSON.stringify(__tw.activate));out.open=JarvisToolWheel.isOpen();return out;")},
            {"a": "eval", "expr": BH % (
                f"hover({anchor[0]},{anchor[1]});return true;")},
            _wait(OPENED),
            {"a": "eval", "expr": BH % (
                f"hover({s0x},{s0y});context({s0x},{s0y});"
                "const items=[...document.querySelectorAll('#toolWheel .tw-item')].map(b=>{const r=b.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2,text:b.textContent}});"
                "const bh=items.find(i=>i.text==='Bare Hands');hover(bh.x,bh.y);pinch(bh.x,bh.y);"
                "return {secondary:JSON.parse(JSON.stringify(__tw.secondary)),items:JSON.parse(JSON.stringify(__tw.items)),"
                "activate:__tw.activate.length,open:JarvisToolWheel.isOpen()};")},
            _state(),
        ]},
        "reduced": {"width": W, "height": H, "mountPalette": True, "reducedMotion": True, "actions": [
            _setup(), _move(*anchor, settle=0), _state(),
            _move(sx, sy, settle=0), {"a": "shot", "path": str(shots / "open-reduced-motion.png")},
            _move(900, 450, settle=0), _wait(CLOSED), _state(),
        ]},
        "motion": {"width": W, "height": H, "mountPalette": True, "actions": [
            _setup(), _move(*anchor, settle=0), _state(),
        ]},
        "focus": {"width": W, "height": H, "mountPalette": True, "actions": [
            _setup(), {"a": "focus", "selector": "#toolWheel .tw-anchor"}, {"a": "key", "key": "Enter"},
            {"a": "eval", "expr": "JarvisToolWheel.close();true"}, _state(),
            {"a": "key", "key": "Enter"}, {"a": "key", "key": "ArrowDown"},
            # Le pointeur part : la roue (ouverte au clavier) reste, le focus aussi.
            _move(900, 450), _move(910, 455, settle=600), _state(),
            # Un clic ailleurs ferme sans laisser le focus sur un secteur caché.
            {"a": "click", "selector": ".dock"}, _state(),
            # Ouverte, chaque pastille est au-dessus de tout ce qui est en dessous (scène, colonne).
            _move(*anchor), _wait(OPENED),
            {"a": "eval", "expr": "(()=>[...document.querySelectorAll('#toolWheel .tw-dot')].map(d=>{const r=d.getBoundingClientRect();"
                                  "const e=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);"
                                  "return e&&e.closest('.tw-wedge')?e.closest('.tw-wedge').dataset.twSlot:(e?e.id||e.className:null)}))()"},
            {"a": "eval", "expr": "(()=>{const e=document.querySelector('#sceneLayer .scene,#sceneLayer');return e?getComputedStyle(e).zIndex:'absent'})()"},
        ]},
        "far": {"width": W, "height": H, "mountPalette": True, "actions": [
            _setup(),
            *[_move(x, y, settle=5) for x in (1400, 1100, 800, 500, 200, 120, 60, 30)
              for y in (60, 250, 450, 650, 860)],
            _move(20, 450, settle=5), _move(30, 300, settle=5), _move(20, 700, settle=5),
            {"a": "eval", "expr": BH % (
                "for(const [x,y] of [[700,450],[1300,80],[40,120],[200,860]])hover(x,y);return JarvisToolWheel.isOpen();")},
            _state(),
        ]},
    }
    # Reprise QA de la Slice 02 (P1-P3, P5) : pincement sur l'ancre, menu Bare
    # Hands loin d'un pincement, Échap avec le focus ailleurs, Espace sur l'ancre.
    focus_name = ("(()=>{const e=document.activeElement;return !e||e===document.body?'body':"
                  "e.closest&&e.closest('#toolWheel')?(e.dataset.twSlot||e.className):(e.id||e.tagName)})()")
    plan["polish"] = {"width": W, "height": H, "mountPalette": True, "actions": [
        _setup(),
        # P1 : le pincement Bare Hands sur l'ancre ouvre comme un pointeur, sans prendre le focus.
        {"a": "eval", "expr": "document.body.focus();document.activeElement&&document.activeElement.blur();true"},
        {"a": "eval", "expr": BH % (f"hover({anchor[0]},{anchor[1]});JarvisToolWheel.close();"
                                    f"hover(400,450);hover({anchor[0]},{anchor[1]});"
                                    f"pinch({anchor[0]},{anchor[1]});return true;")},
        _state(), {"a": "eval", "expr": focus_name},
        # P2 : pouce + majeur sur un secteur, plus de 800 ms après le dernier pincement.
        {"a": "eval", "expr": "new Promise(r=>setTimeout(()=>r(true),900))"},
        {"a": "eval", "expr": BH % (f"hover({s0x},{s0y});context({s0x},{s0y});"
                                    "return JSON.parse(JSON.stringify(__tw.secondary));")},
        # P5 : le point de la coche ne fait pas partie du nom accessible.
        {"a": "ax", "selector": "#toolWheel .tw-item[aria-checked=true]"},
        # P3 : roue ouverte à la souris, focus ailleurs dans la page, Échap ferme.
        {"a": "eval", "expr": "JarvisToolWheel.close();document.activeElement&&document.activeElement.blur();true"},
        {"a": "focus", "selector": ".dock button"},
        _move(400, 450), _move(*anchor), _wait(OPENED),
        {"a": "focus", "selector": ".dock button"}, {"a": "key", "key": "Escape"}, _state(),
        # Espace sur l'ancre : le clavier ouvre et place le focus sur le premier secteur.
        _move(900, 450), _wait(CLOSED), {"a": "focus", "selector": "#toolWheel .tw-anchor"},
        {"a": "key", "key": " "}, _state(),
    ]}
    for theme in ("cosmos",):
        plan[f"theme-{theme}"] = {"width": W, "height": H, "mountPalette": True, "actions": [
            _setup(theme), {"a": "shot", "path": str(shots / f"closed-anchor-{theme}.png")},
            _move(*anchor), _wait(OPENED), _move(s0x, s0y), _state(),
            {"a": "shot", "path": str(shots / f"open-focused-{theme}.png")},
        ]}
    for width, height in ((900, 600), (600, 800)):
        nx, ny = _dot(wedges, 3, height, width)
        plan[f"size-{width}"] = {"width": width, "height": height, "mountPalette": True, "actions": [
            _setup(), _move(7, height / 2), _wait(OPENED), _move(nx, ny), _state(),
            {"a": "shot", "path": str(shots / f"open-{width}x{height}.png")},
        ]}
    names = list(plan)
    tmp = tmp_path_factory.mktemp("wheel")
    page = _served_page(tmp)
    plan_file = tmp / "plan.json"
    plan_file.write_text(json.dumps([plan[n] for n in names]), encoding="utf-8")
    done = subprocess.run([node, str(HARNESS), str(page), chrome, "@" + str(plan_file)],
                          capture_output=True, text=True, encoding="utf-8", timeout=400, check=False)
    assert done.returncode == 0, done.stderr
    steps = json.loads(done.stdout)
    return {name: [a.get("value", a) for a in steps[i]["actions"]] for i, name in enumerate(names)}


# ------------------------------------------------------------ critères d'acceptation


def test_mouse_hotspot_opens_and_leaving_closes(run):
    (setup, closed, _shot, _m1, _m2, opened, _w, _m3, focus, _shot2, _m4, beyond, _m5, leaving, waited, after,
     *rest) = run["mouse"]
    assert setup["builtAtLoad"] is True and setup["hiddenBefore"] is False  # Slice 04 : plus de drapeau, roue là
    assert setup["refused"] == "tool_wheel_unknown_slot"  # aucun outil de remplissage
    # Fermée : l'ancre seule, au rang du bord gauche.
    assert closed["open"] is False and closed["expanded"] == "false" and closed["z"] == "30"
    assert closed["visibleKinds"] == ["tw-anchor"], closed["visibleKinds"]
    assert round(closed["anchor"]["r"] - closed["anchor"]["l"]) == 14
    # Survol de l'ancre : ouverte, rang 37, aucune activation.
    assert opened["open"] is True and opened["dataOpen"] is True and opened["expanded"] == "true"
    assert opened["z"] == "37"
    assert opened["journal"][-1].startswith("[tool_wheel] tool_wheel.open") and '"reason":"mouse"' in opened["journal"][-1]
    # Un secteur pointé : un seul relevé, le sien, au cœur de la roue (à gauche des icônes).
    assert focus["focused"] == ["dossier"] and focus["label"] == "Dossier"
    assert 0 <= focus["labelBox"]["l"] and focus["labelBox"]["r"] < focus["dots"][2]["l"] + 1
    assert focus["calls"]["activate"] == []
    # Plus loin dans le même secteur (vers le bord) : toujours lui.
    assert beyond["focused"] == ["dossier"] and beyond["open"] is True
    # Le pointeur part : encore ouverte juste après (délai de grâce), fermée ensuite.
    assert leaving["open"] is True
    assert waited["ok"] is True and waited["ms"] >= 250, waited
    assert after["open"] is False and after["z"] == "30" and after["label"] is None
    assert '"reason":"leave"' in after["journal"][-1]
    clicked = rest[5]
    assert clicked["calls"]["activate"] == [{"slot": "selection", "source": "mouse"}]
    assert clicked["open"] is False
    sub = rest[-2]
    assert sub["open"] is True
    assert sub["calls"]["secondary"] == [{"slot": "selection", "source": "mouse"}]
    assert [(i["text"], i["role"], i["checked"]) for i in sub["items"]] == [
        ("Souris", "menuitemradio", "true"), ("Bare Hands", "menuitemradio", "false")]
    assert len(sub["calls"]["activate"]) == 1  # le clic droit n'active pas


def test_keyboard_anchor_roving_enter_escape(run):
    (setup, _f, _enter, opened, _d1, _d2, _d3, _d4, _d5, wrapped, _end, at_end, _sf10, sub, _down, in_sub,
     _esc1, back, _esc2, closed, _r, _d, _enter2, activated, _enter3, _tab, tabbed) = run["keyboard"]
    assert opened["open"] is True and opened["active"] == "jarvis" and opened["focused"] == ["jarvis"]
    assert '"reason":"keyboard"' in opened["journal"][-1]
    assert wrapped["active"] == "jarvis"  # cinq fois vers le bas : retour au premier
    assert at_end["active"] == "settings" and at_end["label"] == "Paramètres"
    # Maj+F10 : une activation secondaire (pas deux), le sous-menu prend le focus.
    assert sub["calls"]["secondary"] == [{"slot": "settings", "source": "keyboard"}]
    assert sub["active"] == "item:Écran principal — seule cible disponible"
    assert in_sub["active"].startswith("item:")
    # Échap : d'abord le sous-arc (retour au secteur), puis la roue (retour à l'ancre).
    assert back["open"] is True and back["items"] == [] and back["active"] == "settings"
    assert closed["open"] is False and closed["active"] == "anchor"
    assert '"reason":"escape"' in closed["journal"][-1]
    # Flèche droite rouvre, Entrée active une fois, le focus revient à l'ancre.
    assert activated["calls"]["activate"] == [{"slot": "selection", "source": "keyboard"}]
    assert activated["open"] is False and activated["active"] == "anchor"
    # Tab hors de la roue : pas de piège, la roue se ferme, rien de caché ne garde le focus.
    assert tabbed["open"] is False and tabbed["active"] not in ("jarvis", "selection", "dossier", "capture", "settings")
    assert tabbed["activeInHiddenPanel"] is False


def test_bh_synthetic_pointer_9001_opens_and_pinch_fires_once(run):
    setup, hovered, _w, pinched, _h, _w2, context, final = run["barehands"]
    assert hovered["id"] == 9001
    assert "tw-anchor" in hovered["hit"] and hovered["open"] is True
    assert pinched["hover"] == "dossier" and pinched["rim"] == "dossier"
    # pointerdown, mousedown, pointerup, mouseup, click : une seule activation.
    assert pinched["after"] == [{"slot": "dossier", "source": "barehands"}]
    assert pinched["open"] is False
    # Pincement pouce + majeur (vrai `contextmenu`) : le sous-arc ; pincement sur un choix : une fois.
    assert context["secondary"] == [{"slot": "selection", "source": "barehands"}]
    assert context["items"] == [{"slot": "selection", "item": "barehands", "source": "barehands"}]
    assert context["activate"] == 1 and context["open"] is False
    assert any('"reason":"barehands"' in line for line in final["journal"])


def test_reduced_motion_no_transition_dependency(run):
    setup, _m, opened, _m2, _shot, _m3, _w, closed = run["reduced"]
    # Visible dès l'ouverture, sans attendre aucune transition.
    assert opened["open"] is True and opened["visibility"] == "visible" and opened["opacity"] == "1"
    assert set(opened["transition"].replace(" ", "").split(",")) == {"0s"}
    assert closed["open"] is False and closed["visibility"] == "hidden"
    # Sans la préférence, le mouvement existe (le demi-disque glisse du bord).
    normal = run["motion"][2]
    assert normal["open"] is True and "0.18s" in normal["transition"]


def test_focus_never_lost_behind_scene(run):
    setup, _f, _e, _c, closed_api, _e2, _d, _m1, _m2, stays, _click, outside, _m3, _w, hits, scene_z = run["focus"]
    assert closed_api["open"] is False and closed_api["active"] == "anchor"
    # Ouverte au clavier : le pointeur qui passe ailleurs ne la ferme pas.
    assert stays["open"] is True and stays["active"] == "selection"
    assert outside["open"] is False and outside["activeInHiddenPanel"] is False
    assert '"reason":"outside"' in outside["journal"][-1]
    # Chaque pastille, ouverte, reçoit le pointeur : rien ne la recouvre.
    assert hits == ["jarvis", "selection", "dossier", "capture", "settings"]
    # La scène (rang 20 au registre) n'est pas montée sans Core ; montée, elle est dessous.
    assert scene_z == "absent" or scene_z == "auto" or int(scene_z) < 37


def test_far_pointer_movement_never_opens(run):
    *_moves, bh_open, state = run["far"]
    assert bh_open is False
    assert state["open"] is False and state["z"] == "30"
    assert not any("tool_wheel.open" in line for line in state["journal"])


# ------------------------------------------------------------ thèmes et tailles


def test_cosmos_skin_same_wheel(run):
    setup, _shot, _m, _w, _m2, state, _shot2 = run["theme-cosmos"]
    assert setup["theme"] == "cosmos"
    assert state["open"] is True and state["z"] == "37" and state["focused"] == ["selection"]
    # Slice 03 : le libellé porte la méthode projetée par Sélection (Souris au chargement).
    assert state["label"] == "Sélection · Souris"


@pytest.mark.parametrize("width,height", ((900, 600), (600, 800)))
def test_open_wheel_fits_small_windows(run, width, height):
    state = run[f"size-{width}"][4]
    assert state["open"] is True and state["focused"] == ["capture"]
    assert state["overflowX"] is False
    for dot in state["dots"]:
        assert 0 <= dot["t"] and dot["b"] <= height and dot["r"] <= width
    assert state["labelBox"]["r"] <= width and state["labelBox"]["b"] <= height


# ------------------------------------------------------------ reprise QA de la Slice 02


def test_qa_polish_bh_anchor_pinch_context_escape_space(run):
    (setup, _blur, _pinch, pinched, focus_after_pinch, _wait900, secondary, ax,
     _close, _f0, _m1, _m2, _w, _focus, _esc, escaped, _m3, _w2, _focus2, _space, spaced) = run["polish"]
    # P1 : un pincement Bare Hands sur l'ancre est un pointeur, pas le clavier.
    assert pinched["open"] is True
    assert '"reason":"barehands"' in pinched["journal"][-1]
    assert focus_after_pinch == "tw-anchor" or "tw-wedge" not in focus_after_pinch
    assert pinched["focused"] == [] and pinched["label"] is None
    # P2 : pouce + majeur loin de tout pincement reste « barehands ».
    assert secondary[-1] == {"slot": "selection", "source": "barehands"}
    # P5 : nom accessible sans le point de coche.
    assert ax["name"] == "Souris"
    # P3 : Échap ferme une roue ouverte à la souris quand le focus est ailleurs.
    assert escaped["open"] is False and '"reason":"escape"' in escaped["journal"][-1]
    # Espace sur l'ancre : ouverte au clavier, focus sur le premier secteur.
    assert spaced["open"] is True and spaced["active"] == "jarvis"


# ------------------------------------------------------------ refonte S03 (jarvis-board-ui-wheel-dossier-refactor)

#: Le relevé du sous-menu et de la roue, gestionnaires réels (aucun SETUP).
TREE = r"""(()=>{
  const host=document.getElementById('toolWheel');
  const subs=[...host.querySelectorAll('.tw-sub')].filter(s=>!s.hidden);
  const ae=document.activeElement;
  const lit=[...host.querySelectorAll('.tw-sec.is-on')].length;
  return {open:window.JarvisToolWheel.isOpen(),subs:subs.length,
    head:(host.querySelector('.tw-subhead')||{}).textContent||null,
    items:[...host.querySelectorAll('.tw-sub:not([hidden]) .tw-item')].map(b=>({id:b.dataset.twItem||null,
      text:b.querySelector('.tw-text').textContent,disabled:b.getAttribute('aria-disabled'),role:b.getAttribute('role'),
      popup:b.getAttribute('aria-haspopup')})),
    expanded:[...host.querySelectorAll('.tw-wedge[aria-expanded=true]')].map(b=>b.dataset.twSlot),lit,
    active:!ae||ae===document.body?'body':ae.dataset&&ae.dataset.twSlot?ae.dataset.twSlot
      :ae.classList.contains('tw-anchor')?'anchor':ae.classList.contains('tw-item')?'item:'+(ae.dataset.twItem||''):(ae.id||ae.tagName),
    panel:!document.getElementById('boardsPanel').hidden,
    unbound:(window.__s03logs||[]).filter(l=>l.includes('tool_wheel.unbound')).length,
    yields:(window.__s03logs||[]).filter(l=>/tool_wheel\.yield|boards\.panel_yield|tool_wheel\.hover_blocked/.test(l))};
})()"""
LOGS = ("(()=>{window.__s03logs=[];const i=console.info.bind(console),w=console.warn.bind(console);"
        "console.info=(...a)=>{window.__s03logs.push(String(a[0]));i(...a)};"
        "console.warn=(...a)=>{window.__s03logs.push(String(a[0]));w(...a)};return true})()")


def _tree() -> dict:
    return {"a": "eval", "expr": TREE}


def _drive_one(tmp_path: Path, step: dict) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    page = _served_page(tmp_path)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps([step]), encoding="utf-8")
    done = subprocess.run([node, str(HARNESS), str(page), _chrome(), "@" + str(plan_file)],
                          capture_output=True, text=True, encoding="utf-8", timeout=300, check=False)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)[0]
    errors = [c for c in out.get("console", []) if c.get("type") in ("error", "exception")]
    assert errors == [], errors
    return [a.get("value", a) for a in out["actions"]]


def test_one_category_tree_visible_keyboard_and_switching(tmp_path, shots):
    wedges = _geometry()
    dx, dy = _dot(wedges, 2)
    k = lambda key: {"a": "key", "key": key}  # noqa: E731
    v = _drive_one(tmp_path, {"width": W, "height": H, "mountPalette": True, "actions": [
        {"a": "eval", "expr": LOGS}, {"a": "focus", "selector": "#toolWheel .tw-anchor"},
        k("Enter"), k("ArrowRight"), _tree(),                       # JARVIS : son sous-menu d'état
        {"a": "shot", "path": str(shots / "tree-jarvis.png")},
        k("Escape"), _tree(),                                       # retour sur JARVIS
        k("ArrowDown"), k("ArrowDown"), k("ArrowDown"), k("ArrowRight"), _tree(),   # Capture
        {"a": "shot", "path": str(shots / "tree-capture.png")},
        {"a": "mouse", "type": "mouseMoved", "x": dx, "y": dy},
        {"a": "mouse", "type": "mousePressed", "x": dx, "y": dy, "button": "left"},
        {"a": "mouse", "type": "mouseReleased", "x": dx, "y": dy, "button": "left", "settleMs": 200}, _tree(),  # Dossier
        k("Escape"), k("Escape"), _tree(),
    ]})
    jarvis, back, capture, dossier, closed = (v[4], v[7], v[12], v[17], v[20])
    assert jarvis["open"] and jarvis["subs"] == 1 and jarvis["head"] == "État de Jarvis"
    # Slice 04 : JARVIS est branché (`control_center_jarvis_wheel.js`) — trois lignes d'état, deux portes.
    assert [i["id"] for i in jarvis["items"]] == ["voice", "wake", "agent", "subagents", "voice_settings"]
    assert [i["disabled"] for i in jarvis["items"]] == ["true", "true", "true", None, None]
    assert jarvis["active"] == "item:voice" and jarvis["expanded"] == ["jarvis"] and jarvis["lit"] == 1
    assert jarvis["unbound"] == 0  # plus de gestionnaire d'attente pour JARVIS
    assert back["subs"] == 0 and back["active"] == "jarvis" and back["expanded"] == []
    # Capture garde Capture d'écran, Enregistrer l'écran et Enregistrer l'audio dans son arbre, chacun avec
    # son second niveau (cibles).
    assert capture["subs"] == 1 and capture["head"] == "Capture" and capture["expanded"] == ["capture"]
    assert [i["id"] for i in capture["items"]] == ["screenshot", "video", "audio"]
    assert [i["role"] for i in capture["items"]] == ["menuitem", "menuitemcheckbox", "menuitemcheckbox"]
    assert all(i["popup"] == "menu" for i in capture["items"])
    assert capture["active"] == "item:screenshot"
    # Un clic sur Dossier remplace l'arbre de Capture : un seul sous-menu, une seule catégorie allumée.
    assert dossier["subs"] == 1 and dossier["head"] == "Dossier du Board" and dossier["expanded"] == ["dossier"]
    # Slice 07 : la catégorie Dossier est branchée (`control_center_dossier.js`), plus de gestionnaire d'attente.
    assert [i["text"] for i in dossier["items"]][0] == "Ouvrir le Dossier" and dossier["lit"] == 1
    assert closed["open"] is False and closed["subs"] == 0 and closed["active"] == "anchor"


def test_wheel_and_board_panel_are_never_open_together(tmp_path):
    ax, ay = 7, H / 2
    k = lambda key: {"a": "key", "key": key}  # noqa: E731
    press = [{"a": "mouse", "type": "mousePressed", "x": ax, "y": ay, "button": "left"},
             {"a": "mouse", "type": "mouseReleased", "x": ax, "y": ay, "button": "left", "settleMs": 200}]
    v = _drive_one(tmp_path, {"width": W, "height": H, "mountPalette": True, "actions": [
        {"a": "eval", "expr": LOGS},
        {"a": "click", "selector": "#boardsButton"}, _tree(),                       # 2 : panneau ouvert
        {"a": "mouse", "type": "mouseMoved", "x": 400, "y": 450},
        {"a": "mouse", "type": "mouseMoved", "x": ax, "y": ay, "settleMs": 300}, _tree(),   # 5 : survol bloqué
        *press, _tree(),                                                           # 8 : clic -> roue, panneau fermé
        {"a": "click", "selector": "#boardsButton"}, _tree(),                       # 10 : panneau -> roue fermée
        # Plus de 800 ms après le dernier appui sur la roue : Entrée se lit comme le clavier.
        {"a": "eval", "expr": "new Promise(r=>setTimeout(()=>{document.querySelector('#toolWheel .tw-anchor').focus();r(true)},900))"},
        k("Enter"), _tree(),  # 13 : clavier -> roue
        k("Escape"), _tree(),                                                      # 15 : une Échap : la roue seule
        {"a": "click", "selector": "#boardsButton"}, {"a": "eval", "expr": "JarvisToolWheel.open();true"}, _tree(),  # 18
        {"a": "click", "selector": "#boardsButton"}, k("Escape"), _tree(),         # 21 : Échap ferme le panneau seul
    ]})
    opened, hovered, clicked, back, keyboard, escaped, api, panel_esc = (v[2], v[5], v[8], v[10], v[13], v[15], v[18], v[21])
    assert opened["panel"] is True and opened["open"] is False
    assert hovered["panel"] is True and hovered["open"] is False  # le survol ne retire pas la place
    assert any("tool_wheel.hover_blocked" in line for line in hovered["yields"])
    assert clicked["open"] is True and clicked["panel"] is False
    assert back["panel"] is True and back["open"] is False
    # À la souris, l’appui hors de la roue la ferme déjà (« outside ») avant que le panneau ne s’ouvre.
    assert keyboard["open"] is True and keyboard["panel"] is False and keyboard["active"] == "jarvis"
    assert escaped["open"] is False and escaped["panel"] is False and escaped["active"] == "anchor"
    assert api["open"] is True and api["panel"] is False
    assert any("boards.panel_yield" in line for line in api["yields"])
    assert panel_esc["panel"] is False and panel_esc["open"] is False

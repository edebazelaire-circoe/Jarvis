"""La roue d'outils dans Chrome : vrais événements souris et clavier, pointeur Bare Hands.

Contrat : `docs/control-center-shell.md` › Tool wheel (orbital-ui Slice 02).
`test_tool_wheel_js.py` tient le modèle pur ; ce fichier charge la page
**servie** (composée comme `ControlCenter.index`) — la roue y est construite
d'office depuis la Slice 04 —, branche quatre actions qui notent leurs appels, et
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

from tests.unit.test_interaction_mode_hud_browser import HARNESS, _chrome, _served_page

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_tool_wheel.js"
W, H = 1440, 900

#: Branche quatre actions qui notent leurs appels (la roue est construite d'office). Sélection
#: propose un sous-arc à deux choix, les autres un seul choix informatif.
SETUP = r"""(()=>{
  const theme=%s;
  if(theme&&window.JarvisThemeAPI)window.JarvisThemeAPI.activate(theme,{persist:false});
  const Wh=window.JarvisToolWheel;
  if(!Wh)return {error:'module absent'};
  const builtAtLoad=!!document.querySelector('#toolWheel .tw-anchor'),hiddenBefore=document.getElementById('toolWheel').hidden;
  window.__tw={activate:[],secondary:[],items:[],logs:[]};
  const info=console.info.bind(console);
  console.info=(...a)=>{window.__tw.logs.push(String(a[0]));info(...a)};
  /* Slice 04 : les vues de capture projettent l'état de Core sur Vidéo,
     Capture d'écran et Audio ; ce fichier éprouve la roue seule. */
  for(const id of ['video','screenshot','audio'])Wh.setStatus(id,null);
  if(window.JarvisCaptureRail)window.JarvisCaptureRail.subscribe(()=>{for(const id of ['video','screenshot','audio'])Wh.setStatus(id,null)});
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


def _dot(wedges: list[dict], index: int, height: int = H) -> tuple[float, float]:
    """Centre d'une pastille, roue ouverte : centre de la roue au bord gauche, à mi-hauteur."""

    return wedges[index]["x"], height / 2 + wedges[index]["y"]


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
    sx, sy = _dot(wedges, 2)
    s0x, s0y = _dot(wedges, 0)
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
            {"a": "key", "key": "ArrowDown"}, _state(),
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
                f"out.rim=document.elementFromPoint({wedges[2]['x'] * 185 / 122},{H / 2 + wedges[2]['y'] * 185 / 122}).closest('.tw-wedge').dataset.twSlot;"
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
        nx, ny = _dot(wedges, 3, height)
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
    # Un secteur pointé : un seul libellé, le sien, à côté de sa pastille.
    assert focus["focused"] == ["screenshot"] and focus["label"] == "Capture d’écran"
    assert focus["labelBox"]["l"] > focus["dots"][2]["r"] - 1
    assert focus["calls"]["activate"] == []
    # Plus loin dans le même secteur (vers le bord) : toujours lui.
    assert beyond["focused"] == ["screenshot"] and beyond["open"] is True
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
    (setup, _f, _enter, opened, _d1, _d2, _d3, _d4, wrapped, _end, at_end, _sf10, sub, _down, in_sub,
     _esc1, back, _esc2, closed, _r, _d, _enter2, activated, _enter3, _tab, tabbed) = run["keyboard"]
    assert opened["open"] is True and opened["active"] == "selection" and opened["focused"] == ["selection"]
    assert '"reason":"keyboard"' in opened["journal"][-1]
    assert wrapped["active"] == "selection"  # quatre fois vers le bas : retour au premier
    assert at_end["active"] == "audio" and at_end["label"] == "Audio"
    # Maj+F10 : une activation secondaire (pas deux), le sous-arc prend le focus.
    assert sub["calls"]["secondary"] == [{"slot": "audio", "source": "keyboard"}]
    assert sub["active"] == "item:Écran principal — seule cible disponible"
    assert in_sub["active"].startswith("item:")
    # Échap : d'abord le sous-arc (retour au secteur), puis la roue (retour à l'ancre).
    assert back["open"] is True and back["items"] == [] and back["active"] == "audio"
    assert closed["open"] is False and closed["active"] == "anchor"
    assert '"reason":"escape"' in closed["journal"][-1]
    # Flèche droite rouvre, Entrée active une fois, le focus revient à l'ancre.
    assert activated["calls"]["activate"] == [{"slot": "video", "source": "keyboard"}]
    assert activated["open"] is False and activated["active"] == "anchor"
    # Tab hors de la roue : pas de piège, la roue se ferme, rien de caché ne garde le focus.
    assert tabbed["open"] is False and tabbed["active"] not in ("selection", "video", "screenshot", "audio")
    assert tabbed["activeInHiddenPanel"] is False


def test_bh_synthetic_pointer_9001_opens_and_pinch_fires_once(run):
    setup, hovered, _w, pinched, _h, _w2, context, final = run["barehands"]
    assert hovered["id"] == 9001
    assert "tw-anchor" in hovered["hit"] and hovered["open"] is True
    assert pinched["hover"] == "screenshot" and pinched["rim"] == "screenshot"
    # pointerdown, mousedown, pointerup, mouseup, click : une seule activation.
    assert pinched["after"] == [{"slot": "screenshot", "source": "barehands"}]
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
    assert stays["open"] is True and stays["active"] == "video"
    assert outside["open"] is False and outside["activeInHiddenPanel"] is False
    assert '"reason":"outside"' in outside["journal"][-1]
    # Chaque pastille, ouverte, reçoit le pointeur : rien ne la recouvre.
    assert hits == ["selection", "video", "screenshot", "audio"]
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
    assert state["open"] is True and state["focused"] == ["audio"]
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
    assert spaced["open"] is True and spaced["active"] == "selection"

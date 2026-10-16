"""Roue d'outils orbitale, modèle pur exécuté par node (orbital-ui Slice 02).

Contrat : `docs/control-center-shell.md` › Tool wheel. Ce fichier épingle la
partie sans DOM de `control_center_tool_wheel.js` : les quatre emplacements et
leur ordre, la géométrie (séparation des cibles), le réducteur d'événements
(fermée par défaut, activation au `click` seulement, activation secondaire par
`contextmenu` / `ContextMenu` / `Maj+F10` sans double déclenchement, clavier,
délai de grâce), l'absence de tout réseau et de toute boucle, et l'insertion
dans la page servie derrière son hôte. Le DOM, le focus et les vrais
événements d'entrée sont éprouvés dans Chrome par `test_tool_wheel_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    BOARDS_SCRIPT_MARKER,
    CAPTURE_RAIL_SCRIPT_MARKER,
    ControlCenter,
    TOOL_WHEEL_SCRIPT_FILE,
    TOOL_WHEEL_SCRIPT_MARKER,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
MODULE = RUNTIME / TOOL_WHEEL_SCRIPT_FILE
PAGE_HTML = RUNTIME / "control_center.html"


def run(tmp_path: Path, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "wheel.js"
    script.write_text(
        f"const M=require({json.dumps(str(MODULE))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        # Rejoue une suite d'entrées ; rend l'état final et tous les effets.
        "const play=(inputs,state)=>{let s=state||M.initialState();const fx=[];"
        "for(const i of inputs){const r=M.reduce(s,i);s=r.state;fx.push(...r.effects)}return {s,fx}};\n"
        "const did=(fx,kind)=>fx.filter(f=>f.do===kind);\n"
        + body,
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8",
                          timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


OPEN = "{type:'pointerover',target:'anchor',source:'mouse'}"


# ------------------------------------------------------------ critères d'acceptation


def test_closed_by_default_only_anchor(tmp_path):
    v = run(tmp_path, "out({state:M.initialState(),view:M.viewOf(M.initialState())})")
    assert v["state"]["open"] is False
    view = v["view"]
    assert view["anchor"] == {"visible": True, "expanded": False}
    assert view["panel"] == {"visible": False}
    assert view["label"] is None and view["sub"] is None
    assert not any(w["focused"] for w in view["wedges"])
    # Le drapeau est éteint par défaut dans le module livré ; l'hôte de la
    # page reste déclaré vide et caché.
    source = MODULE.read_text(encoding="utf-8")
    assert re.search(r"let enabled=false,", source)
    assert '<div id="toolWheel" data-shell-control hidden></div>' in PAGE_HTML.read_text(encoding="utf-8")


def test_four_primary_slots_in_order_selection_video_screenshot_audio(tmp_path):
    v = run(tmp_path, "out({ids:M.SLOT_IDS,labels:M.SLOTS.map(s=>s.label),art:Object.keys(M.ART),"
                      "wedges:M.layoutWedges().length})")
    assert v["ids"] == ["selection", "video", "screenshot", "audio"]
    assert v["labels"] == ["Sélection", "Vidéo", "Capture d’écran", "Audio"]
    assert sorted(v["art"]) == sorted(v["ids"])
    assert v["wedges"] == 4


def test_wedge_angles_separated_by_at_least_min(tmp_path):
    v = run(tmp_path, "out({w:M.layoutWedges(),g:M.GEOMETRY,min:M.minSeparationDeg()})")
    wedges, g, minimum = v["w"], v["g"], v["min"]
    import math
    assert g["radius"] == 200 and g["wedgeMin"] == 48  # = --shell-wheel-r, --shell-wedge-min
    assert g["dot"] >= g["wedgeMin"]
    for a, b in zip(wedges, wedges[1:]):
        gap = b["midDeg"] - a["midDeg"]
        assert gap >= minimum, (a, b, minimum)
        # Écart réel entre deux pastilles voisines, en px, au moins la cible + 8.
        arc = g["iconRadius"] * math.radians(gap)
        assert arc >= g["wedgeMin"] + 8
        chord = math.dist((a["x"], a["y"]), (b["x"], b["y"]))
        assert chord - g["dot"] >= 8, chord
        # Secteurs jointifs : aucun trou où la main tomberait.
        assert a["endDeg"] == b["startDeg"]
    # Demi-cercle au bord gauche : symétrique, tout à droite du centre.
    assert wedges[0]["startDeg"] == -wedges[-1]["endDeg"] == -g["spanDeg"] / 2
    assert all(w["x"] > 0 for w in wedges)
    # La cible entière d'un secteur reste dans la boîte du panneau.
    poly = run(tmp_path, "out(M.sectorPolygon(M.layoutWedges()[0].startDeg,M.layoutWedges()[0].endDeg))")
    for x, y in re.findall(r"(-?[\d.]+)px (-?[\d.]+)px", poly):
        assert 0 <= float(x) <= g["radius"] + 0.01 and 0 <= float(y) <= 2 * g["radius"]


def test_activation_on_click_only_never_pointerup(tmp_path):
    # La séquence exacte d'un pincement Bare Hands sur le 2e secteur.
    v = run(tmp_path, f"""
      const seq=[{OPEN},
        {{type:'pointerover',target:'wedge',index:1,source:'barehands'}},
        {{type:'pointerdown',target:'wedge',index:1}},{{type:'mousedown',target:'wedge',index:1}},
        {{type:'pointerup',target:'wedge',index:1}},{{type:'mouseup',target:'wedge',index:1}}];
      const before=play(seq);
      const after=play([{{type:'click',target:'wedge',index:1,detail:1,source:'barehands'}}],before.s);
      out({{before:did(before.fx,'activate'),after:did(after.fx,'activate'),open:after.s.open,
           restore:did(after.fx,'restoreFocus').length}})""")
    assert v["before"] == []
    assert v["after"] == [{"do": "activate", "index": 1, "source": "barehands"}]
    assert v["open"] is False and v["restore"] == 1
    # Un clic sur une roue fermée n'active rien ; le code ne lit jamais pointerup.
    v = run(tmp_path, "out(did(play([{type:'click',target:'wedge',index:0,detail:1}]).fx,'activate'))")
    assert v == []
    source = MODULE.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    assert "'pointerup'" not in code and "'mouseup'" not in code


def test_secondary_on_contextmenu_and_shift_f10(tmp_path):
    v = run(tmp_path, f"""
      const o=play([{OPEN}]).s;
      const right=play([{{type:'contextmenu',target:'wedge',index:2,source:'mouse',t:1000}}],o);
      const shift=play([{{type:'keydown',target:'wedge',index:0,key:'F10',shiftKey:true,t:1000}}],o);
      const plainF10=play([{{type:'keydown',target:'wedge',index:0,key:'F10',shiftKey:false,t:1000}}],o);
      const menuKey=play([{{type:'keydown',target:'wedge',index:3,key:'ContextMenu',t:1000}}],o);
      // Maj+F10 puis le contextmenu natif que le navigateur en tire : une fois.
      const twice=play([{{type:'keydown',target:'wedge',index:1,key:'F10',shiftKey:true,t:1000}},
                        {{type:'contextmenu',target:'wedge',index:1,source:'keyboard',t:1100}}],o);
      const later=play([{{type:'contextmenu',target:'wedge',index:1,t:1000}},
                        {{type:'contextmenu',target:'wedge',index:1,t:1700}}],o);
      const closed=play([{{type:'contextmenu',target:'wedge',index:1,t:1000}}]);
      out({{right:did(right.fx,'secondary'),prevented:did(right.fx,'preventDefault').length,
           shift:did(shift.fx,'secondary'),plain:did(plainF10.fx,'secondary').length,
           menu:did(menuKey.fx,'secondary'),twice:did(twice.fx,'secondary').length,
           later:did(later.fx,'secondary').length,closed:did(closed.fx,'secondary').length,
           activates:[right,shift,menuKey].map(r=>did(r.fx,'activate').length),stillOpen:right.s.open}})""")
    assert v["right"] == [{"do": "secondary", "index": 2, "source": "mouse"}]
    assert v["prevented"] == 1  # le menu du navigateur ne s'ouvre pas
    assert v["shift"] == [{"do": "secondary", "index": 0, "source": "keyboard"}]
    assert v["menu"] == [{"do": "secondary", "index": 3, "source": "keyboard"}]
    assert v["plain"] == 0
    assert v["twice"] == 1
    assert v["later"] == 2
    assert v["closed"] == 0
    assert v["activates"] == [0, 0, 0]
    assert v["stillOpen"] is True


def test_no_network_on_reveal(tmp_path):
    # Le module n'a aucun chemin réseau ni minuterie périodique, nulle part.
    code = re.sub(r"/\*.*?\*/", "", MODULE.read_text(encoding="utf-8"), flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    for forbidden in ("fetch", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "setInterval",
                      "requestAnimationFrame", "import("):
        assert forbidden not in code, forbidden
    # Chargé sous node avec un réseau piégé : ouvrir par chacune des trois
    # entrées ne produit que des effets locaux.
    v = run(tmp_path, f"""
      let calls=0;globalThis.fetch=()=>{{calls+=1}};globalThis.setInterval=()=>{{calls+=1}};
      const fx=[...play([{OPEN}]).fx,...play([{{type:'click',target:'anchor',detail:0}}]).fx,
        ...play([{{type:'keydown',target:'anchor',key:'ArrowRight'}}]).fx,
        ...play([{{type:'pointerover',target:'anchor',source:'barehands'}}]).fx];
      out({{calls,kinds:[...new Set(fx.map(f=>f.do))].sort(),
           reasons:fx.filter(f=>f.key==='tool_wheel.open').map(f=>f.data.reason)}})""")
    assert v["calls"] == 0
    assert set(v["kinds"]) <= {"cancelLeave", "journal", "focus", "preventDefault"}
    assert v["reasons"] == ["mouse", "keyboard", "keyboard", "barehands"]


# ------------------------------------------------------------ conduite


def test_pointer_leave_closes_after_grace_and_reentry_cancels(tmp_path):
    v = run(tmp_path, f"""
      const o=play([{OPEN}]).s;
      const out1=play([{{type:'pointerout',inside:false}}],o);
      const inside=play([{{type:'pointerout',inside:true}}],o);
      const back=play([{{type:'pointerout',inside:false}},{{type:'pointerover',target:'wedge',index:2}}],o);
      const gone=play([{{type:'pointerout',inside:false}},{{type:'leave'}}],o);
      const kb=play([{{type:'click',target:'anchor',detail:0}},{{type:'pointerout',inside:false}}]);
      out({{arm:did(out1.fx,'armLeave'),inside:did(inside.fx,'armLeave').length,
           cancel:did(back.fx,'cancelLeave').length,focus:back.s.focus,
           gone:gone.s.open,kbArm:did(kb.fx,'armLeave').length,grace:M.LEAVE_GRACE_MS}})""")
    assert v["arm"] == [{"do": "armLeave", "ms": v["grace"]}]
    assert 200 <= v["grace"] <= 600
    assert v["inside"] == 0
    assert v["cancel"] == 1 and v["focus"] == 2
    assert v["gone"] is False
    # Ouverte au clavier, un pointeur qui passe ne la referme pas.
    assert v["kbArm"] == 0


def test_keyboard_roving_wraps_and_escape_returns_to_anchor(tmp_path):
    v = run(tmp_path, """
      const k=(key,index,extra)=>Object.assign({type:'keydown',target:'wedge',index,key},extra||{});
      const opened=play([{type:'click',target:'anchor',detail:0}]);
      const up=play([k('ArrowUp',0)],opened.s);
      const down=play([k('ArrowDown',3)],opened.s);
      const end=play([k('End',0)],opened.s);
      const esc=play([k('Escape',1)],opened.s);
      const view=M.viewOf(play([k('ArrowDown',0)],opened.s).s);
      out({first:did(opened.fx,'focus'),up:up.s.focus,down:down.s.focus,end:end.s.focus,
           esc:{open:esc.s.open,restore:did(esc.fx,'restoreFocus').length},
           tab:view.wedges.map(w=>w.tabindex),label:view.label})""")
    assert v["first"] == [{"do": "focus", "target": "wedge", "index": 0}]
    assert (v["up"], v["down"], v["end"]) == (3, 0, 3)
    assert v["esc"] == {"open": False, "restore": 1}
    assert v["tab"] == [-1, 0, -1, -1]  # une seule halte de tabulation
    assert v["label"] == "Vidéo"  # un seul libellé : celui du secteur en avant


def test_sub_arc_keyboard_and_escape_back_to_parent(tmp_path):
    v = run(tmp_path, f"""
      const o=play([{{type:'click',target:'anchor',detail:0}}]).s;
      const sub=play([{{type:'subOpen',slot:2,count:3,source:'keyboard'}}],o);
      const down=play([{{type:'keydown',target:'item',index:2,key:'ArrowDown'}}],sub.s);
      const back=play([{{type:'keydown',target:'item',index:0,key:'Escape'}}],sub.s);
      const pick=play([{{type:'click',target:'item',index:1,detail:1,source:'mouse'}}],sub.s);
      out({{focus:did(sub.fx,'focus'),wrap:down.s.sub.focus,back:{{sub:back.s.sub,focus:back.s.focus,open:back.s.open}},
           pick:did(pick.fx,'item'),closed:pick.s.open,
           layout:M.layoutSubArc(3,M.layoutWedges()[0].midDeg),edge:M.layoutSubArc(8,M.layoutWedges()[0].midDeg)}})""")
    assert v["focus"] == [{"do": "focus", "target": "item", "index": 0}]
    assert v["wrap"] == 0
    assert v["back"] == {"sub": None, "focus": 2, "open": True}
    assert v["pick"] == [{"do": "item", "slot": 2, "index": 1, "source": "mouse"}]
    assert v["closed"] is False
    for layout in (v["layout"], v["edge"]):
        assert all(-78 <= item["deg"] <= 78 for item in layout)
        assert all(item["x"] > 200 * 0.1 for item in layout)


def test_outside_pointer_and_focus_leaving_close_without_stealing_focus(tmp_path):
    v = run(tmp_path, f"""
      const o=play([{OPEN}]).s;
      const a=play([{{type:'pointerdownOutside'}}],o),b=play([{{type:'focusOutside'}}],o);
      out({{a:[a.s.open,did(a.fx,'restoreFocus').length],b:[b.s.open,did(b.fx,'restoreFocus').length]}})""")
    assert v == {"a": [False, 0], "b": [False, 0]}


# ------------------------------------------------------------ page servie


async def test_module_is_served_after_the_capture_rail_and_host_declared(tmp_path):
    html = PAGE_HTML.read_text(encoding="utf-8")
    assert html.index(CAPTURE_RAIL_SCRIPT_MARKER) < html.index(TOOL_WHEEL_SCRIPT_MARKER) < html.index(BOARDS_SCRIPT_MARKER)
    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    assert TOOL_WHEEL_SCRIPT_MARKER not in served
    assert MODULE.read_text(encoding="utf-8") in served
    # Rangs : 30 au repos, 37 ouverte, dans la page (registre de la coque).
    assert "#toolWheel{position:absolute;z-index:30;" in html
    assert "#toolWheel[data-open]{z-index:37}" in html
    # Aucun rang dans la feuille du module.
    assert "z-index" not in re.sub(r"/\*.*?\*/", "", MODULE.read_text(encoding="utf-8"), flags=re.S)


# ------------------------------------------------------------ reprise QA de la Slice 02


def test_hovering_another_wedge_closes_the_open_sub_arc(tmp_path):
    v = run(tmp_path, f"""
      const o=play([{OPEN},{{type:'contextmenu',target:'wedge',index:0,source:'mouse',t:10}},
                    {{type:'subOpen',slot:0,count:2,source:'mouse'}}]).s;
      const same=play([{{type:'pointerover',target:'wedge',index:0}}],o).s;
      const other=play([{{type:'pointerover',target:'wedge',index:2}}],o).s;
      out({{same:!!same.sub,other:other.sub,label:M.viewOf(other).label}})""")
    assert v == {"same": True, "other": None, "label": "Capture d’écran"}


def test_bh_pinch_on_anchor_is_a_pointer_not_the_keyboard(tmp_path):
    v = run(tmp_path, """
      const bh=play([{type:'click',target:'anchor',detail:0,source:'barehands'}]);
      const kb=play([{type:'click',target:'anchor',detail:0,source:'keyboard'}]);
      out({bh:[bh.s.openedBy,did(bh.fx,'focus').length],kb:[kb.s.openedBy,did(kb.fx,'focus').length]})""")
    assert v == {"bh": ["pointer", 0], "kb": ["keyboard", 1]}

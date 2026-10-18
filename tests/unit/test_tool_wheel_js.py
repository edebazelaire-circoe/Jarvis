"""Roue d'outils orbitale, modèle pur exécuté par node (orbital-ui Slice 02).

Contrat : `docs/control-center-shell.md` › Tool wheel. Ce fichier épingle la
partie sans DOM de `control_center_tool_wheel.js` : les cinq catégories et
leur ordre (refonte `jarvis-board-ui-wheel-dossier-refactor` S03), le sous-menu
courbe unique, la géométrie (séparation des cibles), le réducteur d'événements
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
    # Slice 04 : plus de drapeau. L'hôte reste déclaré vide et caché dans la
    # page (module absent : il le reste, la colonne Bare Hands revient) ; le
    # module le construit et le rend visible à son installation.
    source = MODULE.read_text(encoding="utf-8")
    assert "enabled" not in re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    assert re.search(r"function mount\(\)\{.*?host\.hidden=false;", source, re.S)
    assert re.search(r"\n    mount\(\);\n.*?\n    root\.JarvisToolWheel=", source, re.S)
    assert '<div id="toolWheel" data-shell-control hidden></div>' in PAGE_HTML.read_text(encoding="utf-8")


def test_five_categories_in_locked_order_and_no_retired_first_level(tmp_path):
    v = run(tmp_path, "out({ids:M.SLOT_IDS,labels:M.SLOTS.map(s=>s.label),art:Object.keys(M.ART),"
                      "wedges:M.layoutWedges().length,placeholders:Object.keys(M.PLACEHOLDERS),"
                      "items:M.SLOT_IDS.map(id=>M.placeholderItems(id))})")
    assert v["ids"] == ["jarvis", "selection", "dossier", "capture", "settings"]
    assert v["labels"] == ["JARVIS", "Sélection", "Dossier", "Capture", "Paramètres"]
    # Plus de Vidéo / Capture d'écran / Audio au premier niveau (ils vivent dans
    # l'arbre de Capture), et aucune catégorie retirée par le contrat.
    for retired in ("video", "screenshot", "audio", "boards", "files", "fichiers", "search", "recherche",
                    "tools", "outils"):
        assert retired not in v["ids"], retired
    # Chaque catégorie a son dessin ; les autres sont ceux des sous-menus
    # (Sélection, captures, arrêter, capture prise, chevron), jamais un secteur de remplissage.
    assert set(v["ids"]) <= set(v["art"])
    assert set(v["art"]) - set(v["ids"]) == {"video", "screenshot", "audio", "chevron", "mouse", "bare_hands",
                                             "pointer", "pan", "select", "sleep", "help", "diagnostics",
                                             "calibration", "stop", "done"}
    assert v["wedges"] == 5
    # JARVIS, Dossier, Paramètres : un gestionnaire d'attente, une entrée inerte qui le dit.
    assert v["placeholders"] == ["jarvis", "dossier", "settings"]
    for slot, items in zip(v["ids"], v["items"]):
        if slot in v["placeholders"]:
            assert len(items) == 1 and items[0]["disabled"] is True and items[0]["note"] == "pas encore branché"
            assert "pas encore branché" in items[0]["detail"].lower()
        else:
            assert items is None


def test_wedge_angles_separated_by_at_least_min(tmp_path):
    v = run(tmp_path, "out({w:M.layoutWedges(),g:M.GEOMETRY,min:M.minSeparationDeg()})")
    wedges, g, minimum = v["w"], v["g"], v["min"]
    import math
    assert g["radius"] == 224 and g["wedgeMin"] == 48  # = --shell-wheel-r, --shell-wedge-min
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
      const down=play([k('ArrowDown',4)],opened.s);
      const end=play([k('End',0)],opened.s);
      const esc=play([k('Escape',1)],opened.s);
      const view=M.viewOf(play([k('ArrowDown',0)],opened.s).s);
      out({first:did(opened.fx,'focus'),up:up.s.focus,down:down.s.focus,end:end.s.focus,
           esc:{open:esc.s.open,restore:did(esc.fx,'restoreFocus').length},
           tab:view.wedges.map(w=>w.tabindex),label:view.label})""")
    assert v["first"] == [{"do": "focus", "target": "wedge", "index": 0}]
    assert (v["up"], v["down"], v["end"]) == (4, 0, 4)
    assert v["esc"] == {"open": False, "restore": 1}
    assert v["tab"] == [-1, 0, -1, -1, -1]  # une seule halte de tabulation
    assert v["label"] == "Sélection"  # un seul relevé au cœur : celui du secteur en avant


def test_sub_arc_keyboard_and_escape_back_to_parent(tmp_path):
    v = run(tmp_path, f"""
      const o=play([{{type:'click',target:'anchor',detail:0}}]).s;
      const sub=play([{{type:'subOpen',slot:2,count:3,source:'keyboard'}}],o);
      const down=play([{{type:'keydown',target:'item',index:2,key:'ArrowDown'}}],sub.s);
      const back=play([{{type:'keydown',target:'item',index:0,key:'Escape'}}],sub.s);
      const pick=play([{{type:'click',target:'item',index:1,detail:1,source:'mouse'}}],sub.s);
      out({{focus:did(sub.fx,'focus'),wrap:down.s.sub.focus,back:{{sub:back.s.sub,focus:back.s.focus,open:back.s.open}},
           pick:did(pick.fx,'item'),closed:pick.s.open,
           layouts:M.layoutWedges().flatMap(w=>[1,3,9].map(n=>M.layoutSubMenu(n,w.midDeg))),g:M.GEOMETRY}})""")
    assert v["focus"] == [{"do": "focus", "target": "item", "index": 0}]
    assert v["wrap"] == 0
    assert v["back"] == {"sub": None, "focus": 2, "open": True}
    assert v["pick"] == [{"do": "item", "slot": 2, "index": 1, "source": "mouse"}]
    assert v["closed"] is False
    g = v["g"]
    import math
    for layout in v["layouts"]:
        # Le sous-menu reste dans la hauteur de la roue, au-delà de son bord, des lignes d'au moins 40 px.
        assert -g["radius"] <= layout["top"] < layout["bottom"] <= g["radius"], layout
        assert layout["rowH"] >= 40
        for row in layout["rows"]:
            near = 0 if row["top"] <= 0 <= row["top"] + row["h"] else min(abs(row["top"]), abs(row["top"] + row["h"]))
            # Le bord gauche d'une ligne suit l'arc intérieur, hors de la bande des catégories.
            assert row["x"] >= math.sqrt(g["subInner"] ** 2 - near ** 2) + g["subPad"] - 0.01
            assert math.hypot(row["x"], near) > g["radius"]
        # Assez étroit pour une fenêtre de 600 px de large.
        assert layout["right"] <= 540


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


# ------------------------------------------------------------ Slice 03 et reprise QA de la Slice 02


def test_hovering_another_wedge_closes_the_open_sub_arc(tmp_path):
    v = run(tmp_path, f"""
      const o=play([{OPEN},{{type:'contextmenu',target:'wedge',index:0,source:'mouse',t:10}},
                    {{type:'subOpen',slot:0,count:2,source:'mouse'}}]).s;
      const same=play([{{type:'pointerover',target:'wedge',index:0}}],o).s;
      const other=play([{{type:'pointerover',target:'wedge',index:2}}],o).s;
      out({{same:!!same.sub,other:other.sub,label:M.viewOf(other).label}})""")
    assert v == {"same": True, "other": None, "label": "Dossier"}


def test_bh_pinch_on_anchor_is_a_pointer_not_the_keyboard(tmp_path):
    v = run(tmp_path, """
      const bh=play([{type:'click',target:'anchor',detail:0,source:'barehands'}]);
      const kb=play([{type:'click',target:'anchor',detail:0,source:'keyboard'}]);
      out({bh:[bh.s.openedBy,did(bh.fx,'focus').length],kb:[kb.s.openedBy,did(kb.fx,'focus').length]})""")
    assert v == {"bh": ["pointer", 0], "kb": ["keyboard", 1]}


def test_menu_slot_opens_its_sub_arc_on_primary_and_items_drill_down(tmp_path):
    v = run(tmp_path, f"""
      const o=play([{OPEN}]).s;
      const menu=play([{{type:'click',target:'wedge',index:0,detail:1,source:'mouse',menu:true,t:10}}],o);
      const l1=play([{{type:'subOpen',slot:0,count:2,source:'mouse',level:1}}],menu.s).s;
      const right=play([{{type:'contextmenu',target:'item',index:1,source:'mouse',t:20}}],l1);
      const twice=play([{{type:'keydown',target:'item',index:1,key:'F10',shiftKey:true,t:30}},
                        {{type:'contextmenu',target:'item',index:1,source:'keyboard',t:60}}],l1);
      const l2=play([{{type:'subOpen',slot:0,count:7,source:'keyboard',level:2,parent:1}}],l1).s;
      const esc=play([{{type:'keydown',target:'item',index:3,key:'Escape'}}],l2);
      const back=play([{{type:'subOpen',slot:0,count:2,source:'keyboard',level:1,focus:1}}],esc.s);
      const leave=play([{{type:'keydown',target:'item',index:1,key:'Escape'}}],back.s);
      out({{menu:[menu.s.open,did(menu.fx,'activate').length,did(menu.fx,'secondary')],
        right:did(right.fx,'itemSecondary'),twice:did(twice.fx,'itemSecondary').length,
        l2:[l2.sub.level,l2.sub.parent,l2.sub.focus],esc:[did(esc.fx,'subBack'),esc.s.sub.level],
        back:[back.s.sub.level,back.s.sub.focus,did(back.fx,'focus')],leave:[leave.s.sub,leave.s.open,leave.s.focus]}})""")
    assert v["menu"] == [True, 0, [{"do": "secondary", "index": 0, "source": "mouse"}]]
    assert v["right"] == [{"do": "itemSecondary", "slot": 0, "index": 1, "source": "mouse"}]
    assert v["twice"] == 1  # Maj+F10 puis le `contextmenu` natif : une fois
    assert v["l2"] == [2, 1, 0]
    assert v["esc"] == [[{"do": "subBack", "slot": 0, "parent": 1}], 2]
    assert v["back"] == [1, 1, [{"do": "focus", "target": "item", "index": 1}]]
    assert v["leave"] == [None, True, 0]  # Échap au premier niveau : retour au secteur


def test_the_host_is_shown_only_after_the_wheel_is_published():
    """QA S04 P8 : l'hôte est rendu visible **après** la publication de
    `JarvisToolWheel`. Une exception entre les deux laisse l'hôte caché, donc
    la colonne Bare Hands revient (repli), au lieu d'une ancre que rien ne
    peut brancher."""

    code = re.sub(r"/\*.*?\*/", "", MODULE.read_text(encoding="utf-8"), flags=re.S)
    mount = code[code.index("function mount(){"):code.index("function register(action)")]
    assert "host.hidden=false" not in mount
    published = code.index("root.JarvisToolWheel=Object.freeze({")
    assert code.count("host.hidden=false") == 1
    assert code.index("host.hidden=false") > published


# ------------------------------------------------------------ refonte S03 (jarvis-board-ui-wheel-dossier-refactor)


def test_one_category_tree_at_a_time_switching_replaces_it(tmp_path):
    v = run(tmp_path, f"""
      const o=play([{OPEN}]).s;
      const a=play([{{type:'click',target:'wedge',index:0,detail:1,source:'mouse',menu:true,t:10}},
                    {{type:'subOpen',slot:0,count:1,source:'mouse',level:1}}],o).s;
      const b=play([{{type:'click',target:'wedge',index:3,detail:1,source:'mouse',menu:true,t:20}},
                    {{type:'subOpen',slot:3,count:3,source:'mouse',level:1}}],a);
      const kb=play([{{type:'keydown',target:'wedge',index:2,key:'ArrowRight',menu:true,t:30}}],o);
      const plain=play([{{type:'keydown',target:'wedge',index:2,key:'ArrowRight',t:30}}],o);
      const view=M.viewOf(b.s);
      out({{a:a.sub.slot,b:[b.s.sub.slot,did(b.fx,'secondary')],view:view.sub,
           kb:did(kb.fx,'secondary'),plain:[did(plain.fx,'secondary').length,plain.s.focus]}})""")
    # Un seul arbre : celui de Capture remplace celui de JARVIS (le modèle n'en tient qu'un).
    assert v["a"] == 0
    assert v["b"] == [3, [{"do": "secondary", "index": 3, "source": "mouse"}]]
    assert v["view"] == {"slot": 3, "count": 3, "focus": -1, "level": 1}
    # Flèche droite sur une catégorie à arbre : son sous-menu ; sans arbre : la suivante.
    assert v["kb"] == [{"do": "secondary", "index": 2, "source": "keyboard"}]
    assert v["plain"] == [0, 3]


def test_menu_item_opens_its_second_level_and_arrow_right_drills_down(tmp_path):
    v = run(tmp_path, f"""
      const o=play([{OPEN},{{type:'click',target:'wedge',index:3,detail:1,source:'mouse',menu:true,t:10}},
                    {{type:'subOpen',slot:3,count:3,source:'mouse',level:1}}]).s;
      const menu=play([{{type:'click',target:'item',index:1,detail:1,source:'barehands',menu:true,t:20}}],o);
      const plain=play([{{type:'click',target:'item',index:1,detail:1,source:'mouse',t:20}}],o);
      const right=play([{{type:'keydown',target:'item',index:2,key:'ArrowRight',popup:true,t:30}}],o);
      const noPopup=play([{{type:'keydown',target:'item',index:2,key:'ArrowRight',t:30}}],o);
      out({{menu:[did(menu.fx,'itemSecondary'),did(menu.fx,'item').length,menu.s.open],
           plain:[did(plain.fx,'item'),plain.s.open],right:did(right.fx,'itemSecondary'),
           noPopup:did(noPopup.fx,'itemSecondary').length}})""")
    assert v["menu"] == [[{"do": "itemSecondary", "slot": 3, "index": 1, "source": "barehands"}], 0, True]
    assert v["plain"] == [[{"do": "item", "slot": 3, "index": 1, "source": "mouse"}], False]
    assert v["right"] == [{"do": "itemSecondary", "slot": 3, "index": 2, "source": "keyboard"}]
    assert v["noPopup"] == 0


def test_exclusive_surface_blocks_hover_reveal_and_closes_an_open_wheel(tmp_path):
    v = run(tmp_path, f"""
      const blocked=play([{{type:'pointerover',target:'anchor',source:'mouse',blocked:'board-panel'}}]);
      const clicked=play([{{type:'click',target:'anchor',detail:1,source:'mouse'}}]);
      const o=play([{OPEN},{{type:'contextmenu',target:'wedge',index:1,source:'mouse',t:5}},
                    {{type:'subOpen',slot:1,count:2,source:'mouse'}}]).s;
      const yielded=play([{{type:'exclusive',by:'board-panel'}}],o);
      out({{blocked:[blocked.s.open,blocked.fx.filter(f=>f.do==='journal').map(f=>f.key)],clicked:clicked.s.open,
           yielded:[yielded.s.open,yielded.s.sub,did(yielded.fx,'restoreFocus').length,
                    yielded.fx.filter(f=>f.key==='tool_wheel.close').map(f=>f.data.reason)]}})""")
    # Le survol ne retire pas la place au panneau Board ; un clic explicite ouvre.
    assert v["blocked"] == [False, ["tool_wheel.hover_blocked"]]
    assert v["clicked"] is True
    # Le panneau s'ouvre : la roue se ferme, sous-menu compris, sans reprendre le focus.
    assert v["yielded"] == [False, None, 0, ["exclusive"]]


def test_exclusive_event_name_matches_the_shell():
    shell = (RUNTIME / "control_center_shell.js").read_text(encoding="utf-8")
    boards = (RUNTIME / "control_center_boards.js").read_text(encoding="utf-8")
    name = re.search(r"const EXCLUSIVE_EVENT='([^']+)'", shell).group(1)
    for source in (MODULE.read_text(encoding="utf-8"), boards):
        assert f"EXCLUSIVE_EVENT)||'{name}'" in source

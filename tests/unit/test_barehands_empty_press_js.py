"""Décision 70 — un pincement primaire dans le vide ferme le menu contextuel.

Trois étages, chacun par son vrai code :

- le **moteur d'interaction** (bloc pur) publie `empty_press` pour une descente
  primaire sans cible, jamais pour le secondaire ni sur une cible ;
- la **page Bare Hands** (vrai bloc navigateur, harnais de
  `test_barehands_interaction_js`) ne livre l'événement DOM que si la décision
  du résolveur est du vide (`none`/`out_of_reach`) — pas un refus pour
  ambiguïté, pas une cible ;
- la **page du Control Center** (extrait réel de `control_center.html`) ferme
  le menu ouvert sur cet événement, ne fait rien s'il n'y en a pas, et ne le
  ferme pas quand le point tombe dans le menu lui-même.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from tests.unit.test_barehands_interaction_js import BROWSER, FIXTURE, run_node

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
PAGE_HTML = RUNTIME / "control_center.html"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"


def test_the_engine_publishes_an_empty_press_for_a_primary_press_with_no_target(tmp_path):
    result = run_node(tmp_path, FIXTURE + """
      const dom=makeDom();
      const engine=engineOf({dom:dom.api});
      const types=step=>step.interactions.map(i=>i.type);
      const empty=engine.update({now:0,tokens:[tok(1,400,300)],targets:[],contacts:[],
        events:[ev(1,'down',400,300)]});
      const up=engine.update({now:16,tokens:[tok(1,400,300)],targets:[],contacts:[],
        events:[ev(1,'up',400,300)]});
      const secondary=engine.update({now:40,tokens:[tok(1,400,300)],targets:[],contacts:[],
        events:[ev(1,'down',400,300,'secondary')]});
      const onTarget=engine.update({now:80,tokens:[tok(3,10,10)],
        targets:[tgt(3,'w1','body',null,{kind:'content',representation:null,objectId:null})],
        contacts:[],events:[ev(3,'down',10,10)]});
      out({empty:types(empty),emitted:dom.log.map(e=>[e.type,e.x,e.y,e.channel,e.objectId]),
        up:types(up),secondary:types(secondary),onTarget:types(onTarget),
        names:C.INTERACTIONS,domEvent:C.EMPTY_PRESS_DOM_EVENT});
    """)
    assert result["empty"] == ["empty_press"]
    assert result["emitted"][0] == ["empty_press", 400, 300, "primary", None]
    assert result["up"] == [], "une pression dans le vide ne clique pas au relâchement"
    assert result["secondary"] == [], "le secondaire est une intention de clic droit"
    assert "empty_press" not in result["onTarget"], "une descente sur une cible n'est pas du vide"
    assert "empty_press" in result["names"]
    assert result["domEvent"] == "jarvis:barehands-empty-press"


PAGE_DRIVER = BROWSER + """
const heard=[];
global.CustomEvent=class{constructor(type,init){this.type=type;this.detail=(init||{}).detail}};
global.document.dispatchEvent=event=>{heard.push({type:event.type,detail:event.detail});return true};
const press=(now,x,y,channel)=>{
  shot(now,[token(1,x,y)],[contact(1,'pressed',undefined,channel)],
    [{handTrackId:1,channel:channel||'primary',phase:'down',x,y}]);
  shot(now+16,[token(1,x,y)],[],[{handTrackId:1,channel:channel||'primary',phase:'up',x,y}]);
  interaction.takeClicks();
};
"""


def test_the_page_delivers_the_dom_event_only_when_nothing_is_within_reach(tmp_path):
    result = run_node(tmp_path, PAGE_DRIVER + """
      /* 1. Loin de tout : du vide. */
      global.page=[button({left:100,top:100,width:120,height:40},'A')];
      press(0,800,600);
      const far=heard.splice(0);
      /* 2. Sur le bouton : une cible, un clic, pas de vide. */
      press(100,160,120);
      const onButton=heard.splice(0);
      /* 3. Entre deux voisines à égale distance : refus pour ambiguïté, donc
            pas du vide — la main visait l'une des deux. */
      global.page=[button({left:300,top:300,width:40,height:40},'G'),
        button({left:360,top:300,width:40,height:40},'D')];
      press(200,350,320);
      const between=heard.splice(0);
      const decision=api.adapters.interaction.decisions
        ?api.adapters.interaction.decisions().map(d=>d.reason):null;
      /* 4. Le secondaire dans le vide : rien. */
      global.page=[];
      press(300,800,600,'secondary');
      const secondary=heard.splice(0);
      out({far,onButton,between,secondary,decision});
    """)
    assert result["far"] == [{"type": "jarvis:barehands-empty-press",
                              "detail": {"x": 800, "y": 600, "channel": "primary"}}]
    assert result["onButton"] == []
    assert result["between"] == [], result["decision"]
    assert result["secondary"] == []


def test_a_throwing_page_listener_does_not_stop_tracking(tmp_path):
    result = run_node(tmp_path, PAGE_DRIVER + """
      global.document.dispatchEvent=()=>{throw new Error('listener down')};
      const warned=[];const warn=console.warn;console.warn=(...a)=>warned.push(String(a[0]));
      global.page=[];
      let threw=null;
      try{press(0,800,600)}catch(e){threw=String(e)}
      console.warn=warn;
      out({threw,warned});
    """)
    assert result["threw"] is None
    assert any("pression dans le vide" in line for line in result["warned"])


def _menu_snippet() -> str:
    raw = PAGE_HTML.read_text(encoding="utf-8")
    start = raw.index("function dismissMenuOnPress(target)")
    end = raw.index("});", raw.index("document.addEventListener('jarvis:barehands-empty-press'")) + 3
    return raw[start:end]


def _run_page(tmp_path: Path, body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "page-menu.cjs"
    script.write_text(
        "const listeners={};\n"
        "const inside={id:'in'};const outside={id:'out'};\n"
        "const ctxMenu={contains:el=>el===inside};\n"
        "const AG={menu:null};const closes=[];\n"
        "function closeMenu(restore){closes.push(!!restore);AG.menu=null}\n"
        "const document={addEventListener(type,fn){(listeners[type]=listeners[type]||[]).push(fn)},\n"
        "  elementFromPoint:(x,y)=>x<100?inside:outside};\n"
        "const fire=(type,event)=>(listeners[type]||[]).forEach(fn=>fn(event));\n"
        + _menu_snippet() + "\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n" + body,
        encoding="utf-8",
    )
    completed = subprocess.run([node, str(script)], capture_output=True, text=True,
                               encoding="utf-8", timeout=30, check=False)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_the_control_center_closes_its_open_menu_on_an_empty_press(tmp_path):
    result = _run_page(tmp_path, """
      const C=require(%s);
      fire(C.EMPTY_PRESS_DOM_EVENT,{detail:{x:500,y:500}});
      const nothingOpen=closes.length;
      AG.menu={id:'a'};
      fire(C.EMPTY_PRESS_DOM_EVENT,{detail:{x:50,y:50}});
      const insideMenu=closes.length;
      fire(C.EMPTY_PRESS_DOM_EVENT,{detail:{x:500,y:500}});
      const outsideMenu=closes.slice();
      AG.menu={id:'b'};
      fire('mousedown',{target:outside});
      out({nothingOpen,insideMenu,outsideMenu,mouse:closes.length,open:AG.menu});
    """ % json.dumps(str(CONTRACTS)))
    assert result["nothingOpen"] == 0, "rien d'ouvert : aucun effet"
    assert result["insideMenu"] == 0, "un point dans le menu ne le ferme pas"
    assert result["outsideMenu"] == [False], "fermé sans rendre le focus, comme un mousedown"
    assert result["mouse"] == 2, "la souris ferme toujours par le même chemin"
    assert result["open"] is None


def test_the_page_listens_to_the_contract_event_name():
    raw = PAGE_HTML.read_text(encoding="utf-8")
    contract = CONTRACTS.read_text(encoding="utf-8")
    name = re.search(r"EMPTY_PRESS_DOM_EVENT='([^']+)'", contract).group(1)
    assert f"document.addEventListener('{name}'" in raw

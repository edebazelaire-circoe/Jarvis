"""L'inspecteur d'edition du Studio, par node (jarvis-interactive-presentation-studio, Slice 07).

Le module teste est le VRAI `control_center_presentation_studio_inspector.js` ; seuls le DOM, l'horloge et le Core sont des doubles
(`_studio_inspector_bench.cjs` : un Core en miniature qui rend les memes formes que les routes du relais). La preuve dans un vrai
navigateur, avec un vrai Core, est `test_presentation_studio_inspector_browser.py`.

Epingle ici : les widgets rendus depuis des fixtures d'introspection (un par type, bornes, defaut, reinitialisation), les erreurs typees
(refus, base perimee, 409 de rechargement avec nouvelles tentatives bornees, historique indisponible, Core muet), l'aperçu contre
l'enregistrement (60 mouvements d'un curseur = quelques apercus et UN enregistrement), le clavier, le masquage en lecture, l'absence de
tout chemin d'ecriture propre a l'inspecteur, et les listes de variables de theme contre le code qui les pose.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
MODULE = RUNTIME / "control_center_presentation_studio_inspector.js"
BENCH = Path(__file__).parent / "_studio_inspector_bench.cjs"

PRELUDE = r"""
const {boot,DEFS,MODULE:M,Ev}=require(process.env.JARVIS_BENCH);
const stats=(t,kind)=>t.core.st.calls.filter(c=>c.kind===kind);
const inputs=(t,id,type)=>t.find(t.row(id),n=>n.tagName==='INPUT'&&n.type===type);
const range=(t,id)=>inputs(t,id,'range')[0];
const number=(t,id)=>inputs(t,id,'number')[0];
const text=(t,id)=>inputs(t,id,'text')[0];
const buttons=(root,t)=>t.find(root,n=>n.tagName==='BUTTON');
const withText=(t,root,label)=>t.find(root,n=>n.tagName==='BUTTON'&&n.textContent.includes(label))[0];
const drag=async(t,id,values,ms=16)=>{const r=range(t,id);r.dispatch('pointerdown');
  for(const v of values){r.value=String(v);r.dispatch('input');await t.env.advance(ms)}return r};
const release=async(t,id)=>{range(t,id).dispatch('pointerup');await t.env.flush(12)};
const linear=(a,b,n)=>Array.from({length:n},(_,i)=>Math.round((a+(b-a)*(i+1)/n)*100)/100);
const status=(t)=>{const s=t.find(t.panel(),n=>n.className.split(' ').includes('jvi-status')&&!n.hidden);return s.map(n=>n.textContent)};
const msg=(t,id)=>{const m=t.find(t.row(id),n=>n.className.split(' ').includes('jvi-msg'))[0];return m&&!m.hidden?m.textContent:''};
const errors=(t)=>t.env.logs.filter(l=>l[0]==='error').map(l=>l[1]);
const warns=(t)=>t.env.logs.filter(l=>l[0]==='warn').map(l=>l[1]);
"""


def run_js(tmp_path: Path, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    index = len(list(tmp_path.glob("insp-*.cjs")))
    script = tmp_path / f"insp-{index}.cjs"
    script.write_text(PRELUDE + "(async()=>{\n" + body + "\n})().then(v=>console.log(JSON.stringify(v)),"
                      "e=>{console.error(e&&e.stack||e);process.exit(1)});\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=120, check=False,
                          env={**os.environ, "JARVIS_BENCH": str(BENCH), "JARVIS_INSPECTOR_JS": str(MODULE)})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------------ pures

def test_the_widget_table_covers_every_type_the_introspection_can_answer(tmp_path):
    out = run_js(tmp_path, r"""
      const row=(type,widget,bounds,current)=>({type,widget,bounds:bounds||{},current});
      const kinds={
        number_slider:M.widgetSpec(row('number','slider',{min:0.6,max:1.8},1)),
        number_open:M.widgetSpec(row('number','number',{min:0},0)),
        integer_slider:M.widgetSpec(row('integer','slider',{min:-15,max:15},0)),
        integer_open:M.widgetSpec(row('integer','number',{},3)),
        boolean:M.widgetSpec(row('boolean','toggle')),color:M.widgetSpec(row('color','color')),
        enum_short:M.widgetSpec(row('enum','choice',{choices:['a','b','c']})),
        enum_long:M.widgetSpec(row('enum','choice',{choices:['linear','ease','ease-in','ease-out','ease-in-out','spring']})),
        enum_wide:M.widgetSpec(row('enum','choice',{choices:['a','b','c','d','e']})),
        enum_long_labels:M.widgetSpec(row('enum','choice',{choices:['une valeur très longue','b']})),
        string:M.widgetSpec(row('string','text_line',{max_length:40})),text:M.widgetSpec(row('text','text_area',{max_length:300})),
        url:M.widgetSpec(row('url','url')),
        stops:M.widgetSpec(row('array','list',{max_items:5},['#112233','#aabbcc'])),
        json_strings:M.widgetSpec(row('array','list',{max_items:5},['a','b'])),json_empty:M.widgetSpec(row('array','list',{},[])),
        object:M.widgetSpec(row('object','widget?')),
      };
      return Object.fromEntries(Object.entries(kinds).map(([k,v])=>[k,v.kind]));
    """)
    assert out == {"number_slider": "slider", "number_open": "number", "integer_slider": "slider", "integer_open": "number",
                   "boolean": "toggle", "color": "color", "enum_short": "segmented", "enum_long": "select", "enum_wide": "select",
                   "enum_long_labels": "select", "string": "text", "text": "textarea", "url": "url", "stops": "stops",
                   "json_strings": "json", "json_empty": "json", "object": "readonly"}


def test_steps_bounds_and_validation_are_derived_from_the_row(tmp_path):
    out = run_js(tmp_path, r"""
      const r=(type,bounds)=>({type,bounds});
      return {
        steps:[M.stepFor(r('integer',{min:0,max:5000})),M.stepFor(r('number',{min:0.6,max:1.8})),M.stepFor(r('number',{min:0,max:1})),
               M.stepFor(r('number',{min:0,max:100})),M.stepFor(r('number',{})),M.stepFor(r('number',{min:0}))],
        rounding:[M.roundTo(0.30000000000000004,0.01),M.roundTo(1.5649,0.01),M.roundTo(7,1)],
        v:{
          lo:M.validateValue(r('number',{min:0.6,max:1.8}),0.5), hi:M.validateValue(r('number',{min:0.6,max:1.8}),2),
          ok:M.validateValue(r('number',{min:0.6,max:1.8}),1.2),
          notInt:M.validateValue(r('integer',{min:0,max:10}),2.5), nan:M.validateValue(r('number',{}),NaN),
          str:M.validateValue(r('number',{}),'3'),
          color:[M.validateValue(r('color',{}),'#12ab9f'),M.validateValue(r('color',{}),'#12ab9'),M.validateValue(r('color',{}),'red')],
          enum:[M.validateValue(r('enum',{choices:['a','b']}),'a'),M.validateValue(r('enum',{choices:['a','b']}),'c')],
          url:[M.validateValue(r('url',{}),'https://example.org/x?y=1'),M.validateValue(r('url',{}),'javascript:alert(1)'),M.validateValue(r('url',{}),'ftp://x.org'),M.validateValue(r('url',{}),'')],
          string:[M.validateValue(r('string',{max_length:3}),'abcd'),M.validateValue(r('string',{max_length:9}),'a\nb'),M.validateValue(r('string',{max_length:9}),'ok')],
          text:[M.validateValue(r('text',{max_length:9}),'a\nb'),M.validateValue(r('text',{max_length:3}),'abcd'),M.validateValue(r('text',{}),'a\u0007')],
          array:[M.validateValue(r('array',{max_items:2}),[1,2,3]),M.validateValue(r('array',{max_items:2}),'x'),M.validateValue(r('array',{max_items:2}),[1])],
          bool:[M.validateValue(r('boolean',{}),true),M.validateValue(r('boolean',{}),'true')],
          object:M.validateValue(r('object',{}),{}),
        },
      };
    """)
    assert out["steps"] == [1, 0.01, 0.01, 1, 0.1, 0.1]
    assert out["rounding"] == [0.3, 1.56, 7]
    v = out["v"]
    assert "au moins 0.6" in v["lo"] and "au plus 1.8" in v["hi"] and v["ok"] is None
    assert "entier" in v["notInt"] and v["nan"] and v["str"]
    assert v["color"][0] is None and v["color"][1] and v["color"][2]
    assert v["enum"][0] is None and v["enum"][1]
    assert v["url"][0] is None and all(v["url"][1:]), "only http(s) URLs pass (javascript:, ftp:, empty refused)"
    assert "3 caractères" in v["string"][0] and v["string"][1] and v["string"][2] is None
    assert v["text"][0] is None and "3 caractères" in v["text"][1] and v["text"][2]
    assert "2 éléments" in v["array"][0] and v["array"][1] and v["array"][2] is None
    assert v["bool"][0] is None and v["bool"][1] and v["object"]


def test_setting_a_value_by_path_is_own_property_safe(tmp_path):
    out = run_js(tmp_path, r"""
      const base={props:{a:1,deep:{x:1}},data:{}};
      const attempts=[];
      for(const path of ['props.__proto__.polluted','props.constructor','data.prototype.x','props.a.__proto__','nope.a','props']){
        try{M.setAtPath(base,path,1);attempts.push([path,'accepted'])}catch(e){attempts.push([path,'refused'])}
      }
      const set=M.setAtPath(base,'props.deep.y.z',{n:2});
      const unset=M.setAtPath(base,'props.a',undefined);
      return {attempts,set,unset,original:base,polluted:({}).polluted===undefined&&Object.prototype.polluted===undefined};
    """)
    assert all(state == "refused" for _, state in out["attempts"]), out["attempts"]
    assert out["set"] == {"props": {"a": 1, "deep": {"x": 1, "y": {"z": {"n": 2}}}}, "data": {}}
    assert out["unset"] == {"props": {"deep": {"x": 1}}, "data": {}}
    assert out["original"] == {"props": {"a": 1, "deep": {"x": 1}}, "data": {}}, "the input is never mutated"
    assert out["polluted"] is True


def test_the_contrast_and_diff_helpers(tmp_path):
    out = run_js(tmp_path, r"""
      return {bw:M.contrastRatio('#000000','#ffffff'),same:M.contrastRatio('#123456','#123456'),bad:M.contrastRatio('red','#fff'),
        diff:M.diffControls([{control_id:'a',label:'A',current:1},{control_id:'b',label:'B',current:'x'},{control_id:'gone',label:'G',current:2}],
                            [{control_id:'a',label:'A',current:1},{control_id:'b',label:'B',current:'y'},{control_id:'new',label:'N',current:3}])};
    """)
    assert round(out["bw"], 1) == 21.0 and out["same"] == 1 and out["bad"] is None
    assert [(d["control_id"], d.get("added"), d.get("removed")) for d in out["diff"]] == [("b", None, None), ("new", True, None), ("gone", None, True)]


def test_the_theme_variable_lists_are_the_art_direction_and_shim_ones(tmp_path):
    """Slice 09 QA-1 I2: 5 variables reach the frame, 10 do not. The inspector says so; the lists must follow the code."""

    from jarvis.domain.presentation_studio_art_direction import ALLOWED_THEME_VARIABLES

    out = run_js(tmp_path, "return {applied:M.APPLIED_THEME,off:M.NOT_APPLIED_THEME};")
    shim = (ROOT / "jarvis" / "prefabs" / "runtime" / "shim.js").read_text(encoding="utf-8")
    shim_vars = re.search(r"var THEME_VARS=\{([^}]*)\}", shim)
    assert shim_vars, "the shim's THEME_VARS moved: update the inspector's APPLIED_THEME and this test"
    delivered = re.findall(r"'(--jv-[a-z-]+)'", shim_vars.group(1))
    assert sorted(out["applied"]) == sorted(delivered)
    assert sorted(out["applied"] + out["off"]) == sorted(ALLOWED_THEME_VARIABLES)
    assert not set(out["applied"]) & set(out["off"]) and len(out["off"]) == 10


# ------------------------------------------------------------------ rendu depuis le schema

def test_every_type_renders_its_widget_from_the_introspection_alone(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const id=(n)=>n.id;
      const one=(sel)=>sel[0]||null;
      const rowOf=(cid)=>t.row(cid);
      const kind=(cid)=>{
        const r=rowOf(cid);const els=t.find(r,n=>['INPUT','TEXTAREA','SELECT','BUTTON','PRE'].includes(n.tagName)&&!n.className.split(' ').includes('jvi-reset'));
        return els.map(n=>n.tagName.toLowerCase()+(n.type?':'+n.type:'')+(n.attrs.role?'#'+n.attrs.role:''));
      };
      const rowsIn=t.find(t.panel(),n=>n.attrs['data-control-id']).map(n=>n.attrs['data-control-id']);
      const label=(cid)=>{const l=t.find(rowOf(cid),n=>n.tagName==='LABEL')[0];return {text:l.textContent,for:l.attrs.for}};
      const sizeRange=range(t,'size'),tiltRange=range(t,'tilt');
      const easing=t.find(rowOf('easing'),n=>n.tagName==='SELECT')[0];
      const layout=t.find(rowOf('layout'),n=>n.attrs.role==='radio');
      const palette=t.find(rowOf('palette'),n=>n.className.split(' ').includes('jvi-stop'));
      const tabs=t.find(t.panel(),n=>n.attrs.role==='tab').map(n=>[n.textContent,n.attrs['aria-selected'],n.attrs.tabindex]);
      const resetOf=(cid)=>t.find(rowOf(cid),n=>n.className.split(' ').includes('jvi-reset'))[0];
      const glow=t.find(rowOf('glow'),n=>n.attrs.role==='switch')[0];
      return {rowsIn,
        kinds:Object.fromEntries(DEFS.map(d=>[d.control_id,kind(d.control_id)])),
        label:label('size'),sizeRange:{min:sizeRange.min,max:sizeRange.max,step:sizeRange.step,value:sizeRange.value,num:number(t,'size').value},
        tilt:{min:tiltRange.min,max:tiltRange.max,step:tiltRange.step,numStep:number(t,'tilt').step},
        delay:{range:inputs(t,'delay','range').length,min:number(t,'delay').min,max:number(t,'delay').max},
        easing:easing.children.map(o=>o.textContent),
        layout:layout.map(b=>[b.textContent,b.attrs['aria-checked'],b.attrs.tabindex]),
        palette:palette.length,tabs,
        reset:{size:resetOf('size').disabled,delay:resetOf('delay').disabled,title:resetOf('size').attrs['aria-label']},
        glow:{checked:glow.attrs['aria-checked'],label:glow.attrs['aria-label']},
        meaning:t.find(rowOf('title'),n=>n.className.split(' ').includes('jvi-meaning'))[0].textContent,
        textMax:t.find(rowOf('title'),n=>n.tagName==='INPUT')[0].maxLength,
        count:t.find(rowOf('title'),n=>n.className.split(' ').includes('jvi-count'))[0].textContent,
        accent:{pick:inputs(t,'accent','color')[0].value,hex:text(t,'accent').value},
      };
    """)
    kinds = out["kinds"]
    stepper = ["button", "input:number", "button"]
    assert kinds["title"] == ["input:text"] and kinds["code"] == ["input:text"] and kinds["body"] == ["textarea"]
    assert kinds["link"] == ["input:url"] and kinds["tags"] == ["textarea"], "an array of plain values is a JSON-guarded editor"
    assert kinds["accent"] == ["input:color", "input:text"]
    assert kinds["glow"] == ["button:button#switch"]
    assert kinds["layout"] == ["button#radio"] * 3 and kinds["easing"] == ["select"]
    assert kinds["size"] == ["input:range", *stepper] and kinds["tilt"] == ["input:range", *stepper] and kinds["speed"] == ["input:range", *stepper]
    assert kinds["delay"] == stepper, "an unbounded number is a number field with steppers, not a slider"
    assert kinds["palette"].count("input:color") == 2, "a colour array is a stops editor: one colour field per stop"
    assert out["rowsIn"] == [d for d in ["title", "body", "link", "tags", "code", "accent", "palette", "glow", "layout", "size",
                                         "tilt", "speed", "delay", "easing"]]
    assert out["label"]["text"] == "Taille" and out["label"]["for"], "a visible label bound to its input"
    assert out["sizeRange"] == {"min": "0.6", "max": "1.8", "step": "0.01", "value": "1", "num": "1"}, "the curated bounds, not the manifest's"
    assert out["tilt"] == {"min": "-15", "max": "15", "step": "1", "numStep": "1"}
    assert out["delay"] == {"range": 0, "min": "0"}
    assert out["easing"] == ["linear", "ease", "ease-in", "ease-out", "ease-in-out", "spring"]
    assert out["layout"] == [["center", "true", "0"], ["left", "false", "-1"], ["right", "false", "-1"]]
    assert out["palette"] == 2
    assert out["tabs"] == [["Contenu5", "true", "0"], ["Style3", "false", "-1"], ["Mise en page3", "false", "-1"], ["Mouvement3", "false", "-1"]]
    assert out["reset"]["size"] is False and out["reset"]["delay"] is True, "reset is offered only on a value that was set"
    assert "Rétablir" in out["reset"]["title"] and out["glow"] == {"checked": "false", "label": "Halo"}
    assert out["meaning"] == "Le titre affiché en grand." and out["textMax"] == 80 and out["count"] == "9 / 40"
    assert out["accent"] == {"pick": "#6ee7ff", "hex": "#6ee7ff"}


def test_group_tabs_follow_the_keyboard_and_remember_the_last_one(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const tabs=()=>t.find(t.panel(),n=>n.attrs.role==='tab');
      const state=()=>tabs().map(n=>[n.attrs['aria-selected'],n.attrs.tabindex]);
      const panels=()=>t.find(t.panel(),n=>n.attrs.role==='tabpanel').map(n=>n.hidden);
      const first=state(),firstPanels=panels();
      tabs()[0].dispatch('keydown',{key:'ArrowRight'});
      const afterRight=[state(),panels(),t.env.doc.activeElement===tabs()[1]];
      tabs()[1].dispatch('keydown',{key:'End'});
      const afterEnd=state();
      tabs()[3].dispatch('keydown',{key:'ArrowRight'});
      const wrapped=state();
      tabs()[2].dispatch('click');
      const stored=JSON.parse(t.env.stored[M.STORAGE_KEY]);
      const again=await boot({});
      again.env.storage.setItem(M.STORAGE_KEY,JSON.stringify({tab:'motion',preview:false}));
      await again.open();
      const restored=again.find(again.panel(),n=>n.attrs.role==='tab').map(n=>n.attrs['aria-selected']);
      return {first,firstPanels,afterRight,afterEnd,wrapped,stored,restored,previewOpen:again.env.doc.getElementById('jvStudioInspector').querySelector('.jvi-stage').open};
    """)
    assert out["first"][0] == ["true", "0"] and out["firstPanels"] == [False, True, True, True]
    assert out["afterRight"][0] == [["false", "-1"], ["true", "0"], ["false", "-1"], ["false", "-1"]]
    assert out["afterRight"][1] == [True, False, True, True] and out["afterRight"][2] is True
    assert out["afterEnd"][3] == ["true", "0"] and out["wrapped"][0] == ["true", "0"]
    assert out["stored"] == {"tab": "layout", "preview": True}, "the only thing remembered is a view preference"
    assert out["restored"] == ["false", "false", "false", "true"]
    assert out["previewOpen"] is False


def test_a_scene_picker_lists_the_scenes_in_order_and_switching_reloads_the_controls(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const sel=t.find(t.panel(),n=>n.tagName==='SELECT'&&n.attrs['aria-label']==='Scène')[0];
      const options=sel.children.map(o=>o.textContent);
      const before=t.find(t.panel(),n=>n.attrs['data-control-id']).length;
      t.inspector.selectScene('pss_2');await t.env.flush(12);
      const after=t.find(t.panel(),n=>n.attrs['data-control-id']).map(n=>n.attrs['data-control-id']);
      const nav=t.find(t.panel(),n=>n.tagName==='BUTTON'&&['Scène précédente','Scène suivante'].includes(n.attrs['aria-label'])).map(n=>[n.attrs['aria-label'],n.disabled]);
      return {options,before,after,nav,view:t.inspector.view().scene_id,requests:stats(t,'http').map(c=>c.path).filter(p=>p.includes('controls'))};
    """)
    assert out["options"] == ["1. Ouverture · Début", "2. Chiffres"]
    assert out["before"] == 14 and out["after"] == ["title", "accent", "size"]
    assert out["nav"] == [["Scène précédente", False], ["Scène suivante", True]] and out["view"] == "pss_2"
    assert len(out["requests"]) == 2


def test_an_empty_presentation_list_and_a_scene_without_controls_each_say_what_to_do(tmp_path):
    out = run_js(tmp_path, r"""
      const none=await boot({core:{presentations:[]}});await none.open();
      const noneText=none.find(none.panel(),n=>n.className.split(' ').includes('jvi-empty')&&!n.hidden).map(n=>n.textContent);
      const t=await boot({core:{defs:[]}});await t.open();
      const emptyScene=t.find(t.panel(),n=>n.className.split(' ').includes('jvi-empty')&&!n.hidden).map(n=>n.textContent);
      const p=await boot({core:{problems:['control size: props.size is not declared by lab.dial@2']}});await p.open();
      const issues=p.find(p.panel(),n=>n.className.split(' ').includes('jvi-issues')).map(n=>n.textContent);
      return {noneText,emptyScene,issues};
    """)
    assert out["noneText"] and "Aucune présentation" in out["noneText"][0]
    assert out["emptyScene"] and "n'expose aucun réglage" in out["emptyScene"][0]
    assert out["issues"] and "lab.dial@2" in out["issues"][0], "the scene's own problems are listed, controls still shown"

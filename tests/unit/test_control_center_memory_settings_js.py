"""Réglages mémoire : le module servi, exécuté par node sur la vraie section serveur.

Slice 11 de jarvis-memory-intelligence-knowledge (champs décrits par le serveur, correctif minimal, secrets absents),
rangé en sections par jarvis-settings-ui-reorganization, Slice 05 : chaque champ s'affiche dans l'unique section que
le serveur lui donne (`surface.section`), le brouillon est partagé entre les sections mémoire, la charge envoyée est
figée clé par clé, une vue détruite ignore une réponse tardive, le détail des étages vit dans Avancé › Diagnostics.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.memory_relay import memory_settings_section
from jarvis.runtime.memory_settings import SURFACE_SECTIONS

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_memory_settings.js"
UI = ROOT / "jarvis" / "runtime" / "control_center_settings_ui.js"
HTML = ROOT / "jarvis" / "runtime" / "control_center.html"

#: Hôte factice : `innerHTML`, et des éléments rendus par `querySelectorAll` qui gardent leurs écouteurs, pour jouer un
#: vrai `change` sur un champ (`change(host, path, {checked|value})`) ou un clic (`click(host, attr)`).
PRELUDE = r"""
globalThis.window=globalThis;
require(UI_PATH);
const M=require(MODULE_PATH).JarvisMemorySettings||globalThis.JarvisMemorySettings;
function fakeHost(){
  return {_h:'',els:{},clicks:{},setAttribute(){},querySelector(sel){return sel.startsWith('#')?{focus(){}}:null},
    get innerHTML(){return this._h},set innerHTML(v){this._h=v;this.els={};this.clicks={}},
    querySelectorAll(sel){
      if(sel==='[data-mem]')return [...this._h.matchAll(/data-mem="([^"]+)"/g)].map(m=>{
        const el={id:'mem_'+m[1].replace(/\./g,'_'),dataset:{mem:m[1]},checked:false,value:'',addEventListener:(ev,fn)=>{this.els[m[1]]={el,fn}}};
        return el});
      const attr=sel.slice(1,-1);
      return [...this._h.matchAll(new RegExp(attr+'(?:="([^"]*)")?','g'))].map(m=>({dataset:{memOpen:m[1]},
        addEventListener:(ev,fn)=>{(this.clicks[attr]=this.clicks[attr]||[]).push(fn)}}));
    }};
}
function change(host,path,set){const hit=host.els[path];if(!hit)throw new Error('champ absent : '+path);Object.assign(hit.el,set);hit.fn()}
function click(host,attr){const list=host.clicks[attr]||[];if(!list.length)throw new Error('bouton absent : '+attr);list[0]()}
const paths=html=>[...html.matchAll(/data-mem="([^"]+)"/g)].map(m=>m[1]);
const out=v=>process.stdout.write(JSON.stringify(v));
"""


def run_node(tmp_path: Path, settings: dict, source: str, environ: dict | None = None):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data = tmp_path / "d.json"
    data.write_text(json.dumps(memory_settings_section(settings, environ or {})), encoding="utf-8")
    script = tmp_path / "t.cjs"
    script.write_text(
        f"const MODULE_PATH={json.dumps(str(MODULE))},UI_PATH={json.dumps(str(UI))};\n"
        + PRELUDE
        + f"const MEM=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data))},'utf8'));\n"
        "const calls=[];\n"
        "const fetchFn=async(p,i)=>{calls.push([p,i&&i.body]);return {memory:MEM}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout) if done.stdout else None


SECTIONS_JS = json.dumps(list(SURFACE_SECTIONS))


def test_every_server_field_renders_in_exactly_one_section_its_server_destination(tmp_path):
    settings = {"credentials": {"openai": {"value": "sk-SECRET-123"}}, "memory": {"semantic": {"provider": "openai"}}}
    out = run_node(tmp_path, settings, f"""
const store=M.createStore(),seen={{}},html={{}};
for(const section of {SECTIONS_JS}){{
  const host=fakeHost();await M.create(host,{{fetch:fetchFn,store,section}}).load();
  seen[section]=paths(host.innerHTML);html[section]=host.innerHTML;
}}
for(const mode of ['center','diagnostics']){{const host=fakeHost();await M.create(host,{{fetch:fetchFn,store,mode}}).load();
  seen[mode]=paths(host.innerHTML);html[mode]=host.innerHTML}}
out({{seen,html,calls:calls.length,fields:MEM.schema.sections.flatMap(s=>s.fields.map(f=>[f.path,f.surface.section]))}});""")
    rendered = [path for section in SURFACE_SECTIONS for path in out["seen"][section]]
    assert sorted(rendered) == sorted(path for path, _ in out["fields"])  # chaque champ, une seule fois
    assert len(rendered) == len(set(rendered))
    for path, section in out["fields"]:
        assert path in out["seen"][section], (path, section)
    assert out["seen"]["center"] == [] and out["seen"]["diagnostics"] == []  # ni l'un ni l'autre n'édite
    assert all(out["seen"][s] for s in SURFACE_SECTIONS)
    assert out["calls"] == 1  # une seule lecture pour l'état partagé
    every = "".join(out["html"].values())
    assert "SECRET" not in every and "sk-" not in every
    # Le secret se règle dans Connexions (Slice 07 de jarvis-settings-ui-reorganization), par l'ID canonique.
    for section in ("semantic_retrieval", "knowledge_sources"):
        assert 'data-mem-open="providers">Connexions</button>' in out["html"][section]
    assert "Connaissances par agent" in out["html"]["knowledge_sources"]  # résumé des loadouts, lecture seule
    assert "Ouvrir le Memory Center" in out["html"]["center"]
    for section in SURFACE_SECTIONS:  # ligne d'état courte + lien profond, jamais le détail des étages
        assert "data-mem-diagnostics" in out["html"][section] and "État des étages mémoire" not in out["html"][section]
    assert "État des étages mémoire" in out["html"]["diagnostics"]


def test_dependent_toggles_are_blocked_and_the_patch_is_minimal(tmp_path):
    out = run_node(tmp_path, {}, """
const store=M.createStore();
const host=fakeHost(),v=M.create(host,{fetch:fetchFn,store,section:'semantic_retrieval'});await v.load();
const blocked=/id="mem_semantic_enabled"[^>]*disabled/.test(host.innerHTML);
const r=fakeHost(),recall=M.create(r,{fetch:fetchFn,store,section:'recall'});await recall.load();
change(r,'recall.max_items',{value:'3'});change(r,'recall.enabled',{checked:false});
const patch=recall.patch();
click(r,'data-mem-save');await new Promise(x=>setTimeout(x,10));
out({blocked,patch,calls,draft:store.draft});""")
    assert out["blocked"] is True
    assert out["patch"] == {"recall": {"max_items": 3, "enabled": False}}
    assert out["calls"][-1][0] == "/api/settings"
    assert json.loads(out["calls"][-1][1]) == {"memory": out["patch"]}
    assert out["draft"] == {}


def test_a_refusal_is_shown_and_keeps_the_draft(tmp_path):
    out = run_node(tmp_path, {}, """
const bad=async()=>{const e=new Error('semantic.enabled invalide');e.code='memory_settings_semantic_needs_provider';throw e};
const host=fakeHost(),v=M.create(host,{fetch:async(p,i)=>i?bad():{memory:MEM},section:'recall'});await v.load();
change(host,'recall.max_items',{value:'2'});await v.submit();
out({html:host.innerHTML,draft:v.state.draft});""")
    assert "memory_settings_semantic_needs_provider" in out["html"] and "Rien n" in out["html"]
    assert 'role="alert"' in out["html"]
    assert out["draft"] == {"recall.max_items": 2}


def test_degradation_is_counted_on_the_page_and_detailed_in_diagnostics(tmp_path):
    out = run_node(tmp_path, {"memory": {"tencent": {"enabled": True}}}, """
const store=M.createStore(),page=fakeHost(),diag=fakeHost();
let opened=0;
await M.create(page,{fetch:fetchFn,store,section:'knowledge_sources',openDiagnostics:()=>opened++}).load();
await M.create(diag,{fetch:fetchFn,store,mode:'diagnostics'}).load();
click(page,'data-mem-diagnostics');
out({page:page.innerHTML,diag:diag.innerHTML,opened});""")
    assert "1 point à vérifier" in out["page"] and "Voir le diagnostic mémoire" in out["page"]
    assert "memory_settings_tencent_needs_url" not in out["page"]  # le détail n'est pas sur la page ordinaire
    assert "coupé" in out["diag"] and "memory_settings_tencent_needs_url" in out["diag"]
    assert out["opened"] == 1


def test_env_imposed_values_are_locked_and_listed_in_diagnostics(tmp_path):
    out = run_node(tmp_path, {}, """
const store=M.createStore(),page=fakeHost(),diag=fakeHost();
await M.create(page,{fetch:fetchFn,store,section:'recall'}).load();
await M.create(diag,{fetch:fetchFn,store,mode:'diagnostics'}).load();
out({page:page.innerHTML,diag:diag.innerHTML});""", environ={"JARVIS_MEMORY_RECALL_MAX_ITEMS": "4"})
    assert "JARVIS_MEMORY_RECALL_MAX_ITEMS" in out["page"]
    assert "JARVIS_MEMORY_RECALL_MAX_ITEMS" in out["diag"] and "Valeurs imposées par l’environnement" in out["diag"]


def test_the_draft_is_shared_and_a_cross_section_fix_is_saved_with_it(tmp_path):
    """Couper la recherche sémantique ramène la consolidation automatique à « manuel » (autre section) : la section
    sémantique le dit, la section Consolidation le montre, et l'enregistrement envoie les deux."""
    settings = {"memory": {"semantic": {"enabled": True, "provider": "openai"}, "consolidation": {"mode": "auto"}}}
    out = run_node(tmp_path, settings, """
const store=M.createStore(),sem=fakeHost(),con=fakeHost();
const s=M.create(sem,{fetch:fetchFn,store,section:'semantic_retrieval'});await s.load();
change(sem,'semantic.enabled',{checked:false});
s.destroy();
const c=M.create(con,{fetch:fetchFn,store,section:'consolidation'});await c.load();
const pending=con.innerHTML;
click(con,'data-mem-save');await new Promise(x=>setTimeout(x,10));
out({semantic:sem.innerHTML,pending,body:JSON.parse(calls[calls.length-1][1]),after:con.innerHTML});""")
    assert "Mode de consolidation" in out["semantic"]  # « Enregistre aussi les changements en attente… »
    assert 'value="manual" selected' in out["pending"]
    assert "Recherche sémantique" in out["pending"]
    assert out["body"] == {"memory": {"semantic": {"enabled": False}, "consolidation": {"mode": "manual"}}}
    assert "prochain démarrage de Core" in out["after"]  # semantic.enabled ne s'applique qu'au redémarrage


def test_restart_required_notice_is_shown_while_pending(tmp_path):
    out = run_node(tmp_path, {}, """
const host=fakeHost(),v=M.create(host,{fetch:fetchFn,section:'knowledge_sources'});await v.load();
change(host,'tencent.url',{value:'http://127.0.0.1:9000'});
const pending=host.innerHTML;
change(host,'knowledge.wiki_enabled',{checked:false});
out({pending,both:host.innerHTML,draft:v.state.draft});""")
    assert "Redémarrage de Core nécessaire pour" in out["pending"] and "URL du sidecar" in out["pending"]
    assert out["draft"] == {"tencent.url": "http://127.0.0.1:9000", "knowledge.wiki_enabled": False}
    assert "Au prochain démarrage de Core" in out["both"] and "Au prochain tour" in out["both"]  # badges par groupe


def test_a_destroyed_view_ignores_a_late_response_and_the_store_reads_once(tmp_path):
    out = run_node(tmp_path, {}, """
const pending=[];const slow=(p,i)=>new Promise(r=>pending.push(()=>r({memory:MEM})));
const store=M.createStore(),a=fakeHost(),b=fakeHost();
const first=M.create(a,{fetch:slow,store,section:'recall'});const firstLoad=first.load();
first.destroy();                                   // le shell quitte la section pendant la lecture
const second=M.create(b,{fetch:slow,store,section:'consolidation'});const secondLoad=second.load();
const reads=pending.length;
pending.forEach(r=>r());await firstLoad;await secondLoad;
first.render();
out({reads,a:a.innerHTML,b:paths(b.innerHTML),destroyed:first.destroyed});""")
    assert out["reads"] == 1
    assert out["a"] == '<div class="empty">Chargement…</div>'  # la réponse tardive n'a rien dessiné
    assert out["destroyed"] is True
    assert out["b"] == ["consolidation.mode", "consolidation.auto_min_confidence", "consolidation.max_candidates_per_run"]


async def test_the_saved_payload_is_frozen_key_by_key_and_unknown_fields_survive(tmp_path, monkeypatch):
    """La charge envoyée par une section est exactement `{memory: {<section>: {<champ>: valeur}}}` ; passée par la vraie
    route d'enregistrement, elle garde les clés inconnues du bloc et ne touche ni les autres champs ni les autres blocs."""
    for name in list(os.environ):
        if name.startswith("JARVIS_MEMORY_"):
            monkeypatch.delenv(name)
    out = run_node(tmp_path, {}, """
const host=fakeHost(),v=M.create(host,{fetch:fetchFn,section:'consolidation'});await v.load();
change(host,'consolidation.max_candidates_per_run',{value:'7'});
click(host,'data-mem-save');await new Promise(x=>setTimeout(x,10));
out({body:calls[calls.length-1][1]});""")
    body = json.loads(out["body"])
    assert body == {"memory": {"consolidation": {"max_candidates_per_run": 7}}}
    assert list(body) == ["memory"] and list(body["memory"]) == ["consolidation"]

    runtime = tmp_path / "rt"
    runtime.mkdir()
    control = ControlCenter(runtime_root=runtime, project_root=runtime)
    control.settings_path.write_text(json.dumps({
        "memory": {"future_block": {"knob": 1}, "recall": {"max_items": 5, "future_knob": "x"},
                   "consolidation": {"mode": "manual", "future": True}},
        "future_top": {"keep": True},
    }), encoding="utf-8")

    class Request:
        async def json(self):
            return body

    response = await control.save_settings(Request())
    assert response.status == 200
    saved = json.loads(control.settings_path.read_text(encoding="utf-8"))
    memory = saved["memory"]
    assert memory["future_block"] == {"knob": 1}
    assert memory["recall"]["future_knob"] == "x" and memory["recall"]["max_items"] == 5
    assert memory["consolidation"]["future"] is True and memory["consolidation"]["max_candidates_per_run"] == 7
    assert memory["consolidation"]["mode"] == "manual"
    assert saved["future_top"] == {"keep": True}


# --- la page : sections enregistrées, alias, cycle de vie ---------------------------------------------------------

PAGE_LIFECYCLE = r"""
globalThis.window=globalThis;
require(UI_PATH);require(MODULE_PATH);
const pending=[];
globalThis.fetch=(path)=>new Promise(resolve=>pending.push({path,resolve}));
const errors=[];console.error=(c,e)=>errors.push(String(c));
const SET={open:true,openGeneration:3,renderRevision:1};
const esc=String,document={getElementById:()=>null};
const UI=window.JarvisSettingsUI;
function fakeHost(){const inner={innerHTML:'',setAttribute(){},querySelectorAll(){return[]},querySelector(){return null}};
  return {inner,_h:'',set innerHTML(v){this._h=v},get innerHTML(){return this._h},get firstElementChild(){return inner}}}
const context={ui:UI,open(){},revision:1,isCurrent:()=>true};
""" + "{PAGE_SOURCE}" + r"""
const reply=body=>({ok:true,status:200,headers:{get:()=>null},text:async()=>JSON.stringify(body)});
(async()=>{
  const seen={};
  for(const spec of MEMORY_SECTIONS){
    const entry=memorySectionSpec(spec),host=fakeHost();
    SET.memoryStore=null;pending.length=0;
    entry.mount(host,context);
    const reads=pending.length,store=SET.memoryStore;
    entry.destroy(host);                                   // le shell quitte la section (`destroyRegisteredSection`)
    for(const p of pending)p.resolve(reply({memory:MEM}));  // réponse tardive
    await new Promise(r=>setTimeout(r,20));
    seen[spec.id]={save:entry.save,reads,mount:host.innerHTML,inner:host.inner.innerHTML,loaded:!!store.memory};
  }
  /* L'état est partagé le temps d'une ouverture : une nouvelle ouverture le relit. */
  const a=memorySettingsStore(),b=memorySettingsStore();SET.openGeneration++;const c=memorySettingsStore();
  /* Partie Mémoire des diagnostics : montée, détruite. */
  const dh=fakeHost();SET.memoryStore=null;pending.length=0;
  MEMORY_DIAGNOSTIC.mount(dh,context);const held=!!memoryDiagnosticView;
  MEMORY_DIAGNOSTIC.destroy();for(const p of pending)p.resolve(reply({memory:MEM}));
  await new Promise(r=>setTimeout(r,20));
  process.stdout.write(JSON.stringify({seen,same:a===b,fresh:a!==c,held,after:memoryDiagnosticView,diag:dh.inner.innerHTML,errors}));
})().catch(e=>{process.stderr.write(String(e&&e.stack||e));process.exit(1)});
"""


def test_leaving_a_memory_section_destroys_its_view_and_ignores_the_late_response(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    page = HTML.read_text(encoding="utf-8")
    source = page[page.index("const MEMORY_SECTIONS=[") : page.index("function installMemorySettingsSections()")]
    data = tmp_path / "m.json"
    data.write_text(json.dumps(memory_settings_section({}, {})), encoding="utf-8")
    script = tmp_path / "page.cjs"
    script.write_text(
        f"const MODULE_PATH={json.dumps(str(MODULE))},UI_PATH={json.dumps(str(UI))};"
        f"const MEM=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data))},'utf8'));"
        + PAGE_LIFECYCLE.replace("{PAGE_SOURCE}", source),
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    seen = result["seen"]
    assert list(seen) == ["recall", "semantic_retrieval", "consolidation", "knowledge_sources", "memory_center"]
    for section, item in seen.items():
        assert item["save"] == ("readonly" if section == "memory_center" else "self"), section
        assert item["reads"] == 1 and item["mount"] == '<div id="memorySettingsMount"></div>', item
        assert item["inner"] == '<div class="empty">Chargement…</div>', item  # rien dessiné après destruction
        assert item["loaded"] is True  # l'état partagé, lui, garde la lecture pour la section suivante
    assert result["same"] is True and result["fresh"] is True
    assert result["held"] is True and result["after"] is None
    assert result["diag"] == '<div class="empty">Chargement…</div>'
    assert result["errors"] == []


def test_the_page_registers_memory_sections_and_has_no_memory_tab():
    html = HTML.read_text(encoding="utf-8")
    tabs = html[html.index("\nconst TABS=[") : html.index("\nconst SET=")]
    assert "id:'memory'" not in tabs and "SET.tab==='memory'" not in html
    block = html[html.index("const MEMORY_SECTIONS=[") : html.index("function memorySettingsStore()")]
    for section in (*SURFACE_SECTIONS, "memory_center"):
        assert f"{{id:'{section}',category:'memory_knowledge'" in block, section
    assert "aliases:['memory']" in block
    assert "if(typeof window!=='undefined'&&typeof installMemorySettingsSections==='function')installMemorySettingsSections();" in html
    assert "registerSettingsDiagnostic(MEMORY_DIAGNOSTIC);" in html


# --- retravail QA Slice 05 : vues du même store, maintien en vue du diagnostic ------------------------------------

@pytest.mark.parametrize("refused", [False, True])
def test_leaving_a_section_during_a_save_redraws_the_section_now_shown(tmp_path, refused):
    """Enregistrer depuis Recherche sémantique, passer à Consolidation pendant l'envoi : à l'issue, Consolidation n'est plus
    figée (« Enregistrement… », champs désactivés) ; elle montre l'issue réelle, succès ou refus."""
    out = run_node(tmp_path, {}, """
let answer;const held=new Promise(r=>answer=r);
const slow=async(p,i)=>{if(!i)return {memory:MEM};await held;
  if(REFUSED){const e=new Error('refusé');e.code='memory_settings_bad_type';throw e}return {memory:MEM}};
const store=M.createStore(),sem=fakeHost(),con=fakeHost();
const s=M.create(sem,{fetch:slow,store,section:'semantic_retrieval'});await s.load();
change(sem,'semantic.provider',{value:'openai'});
const saving=s.submit();
s.destroy();                                         // le shell quitte la section pendant l'envoi
const c=M.create(con,{fetch:slow,store,section:'consolidation'});await c.load();
const during=con.innerHTML;
answer();await saving;
out({during,after:con.innerHTML,busy:store.busy,draft:store.draft,views:store.views.size});""".replace("REFUSED", "true" if refused else "false"))
    assert "Enregistrement…" in out["during"]
    after = out["after"]
    assert out["busy"] is False and out["views"] == 1
    assert "Enregistrement…" not in after and "Enregistrer la mémoire" in after
    assert "mem_consolidation_mode" in after and not __import__("re").search(r'id="mem_consolidation_mode"[^>]*disabled', after)
    if refused:
        assert "memory_settings_bad_type" in after and "Rien n" in after
        assert out["draft"] == {"semantic.provider": "openai"} and "Enregistre aussi" in after
    else:
        assert "Réglages mémoire enregistrés." in after and "prochain démarrage de Core" in after
        assert out["draft"] == {} and "Enregistre aussi" not in after and "Redémarrage de Core nécessaire" not in after


def test_a_section_opened_after_a_save_does_not_repeat_its_message(tmp_path):
    out = run_node(tmp_path, {}, """
const store=M.createStore(),sem=fakeHost(),con=fakeHost();
const s=M.create(sem,{fetch:fetchFn,store,section:'semantic_retrieval'});await s.load();
change(sem,'semantic.provider',{value:'openai'});await s.submit();
const saved=sem.innerHTML;s.destroy();
await M.create(con,{fetch:fetchFn,store,section:'consolidation'}).load();
out({saved,later:con.innerHTML});""")
    assert "Réglages mémoire enregistrés." in out["saved"] and "prochain démarrage de Core" in out["saved"]
    assert "Réglages mémoire enregistrés." not in out["later"] and "prochain démarrage de Core" not in out["later"]


PIN = r"""
const listeners={},timers=new Map();let nextTimer=1,pins=0,observer=null;
globalThis.setTimeout=(fn,ms)=>{const id=nextTimer++;timers.set(id,{fn,ms});return id};
globalThis.clearTimeout=id=>{timers.delete(id)};
globalThis.ResizeObserver=class{constructor(cb){this.cb=cb;this.on=false;observer=this}observe(){this.on=true}disconnect(){this.on=false}};
const part={isConnected:true,parentElement:{},setAttribute(){},matches:()=>false,focus(){},scrollIntoView(){pins++}};
const document={getElementById:id=>id==='diagnostic_memory'?part:null,activeElement:part};
const modalContent={querySelector:sel=>sel==='#diagnostic_memory'?part:null,
  addEventListener(t,fn){(listeners[t]=listeners[t]||new Set()).add(fn)},removeEventListener(t,fn){listeners[t]&&listeners[t].delete(fn)}};
/* Le lien du shell (Slice 06) : `context.open` = `openSettingsLink`, réduit ici à la pose du focus et au maintien. */
const context={open:(target,options)=>{stopSettingsPin();focusSettingsLanding(options&&options.focus)}};
""" + "{PAGE_SOURCE}" + r"""
const live=()=>Object.values(listeners).reduce((n,s)=>n+s.size,0);
const grow=()=>{if(observer.on)observer.cb()};
const out={};
openMemoryDiagnostics(context);grow();
out.start={pins,timers:[...timers.values()].map(t=>t.ms),types:Object.keys(listeners).sort(),live:live()};
for(const type of ['wheel','keydown','pointerdown','touchstart']){
  openMemoryDiagnostics(context);const before=pins;[...listeners[type]][0]();grow();
  out[type]={pinned:pins-before,observing:observer.on,timers:timers.size,live:live()};
}
openMemoryDiagnostics(context);const before=pins;[...timers.values()][0].fn();grow();
out.timeout={pinned:pins-before,observing:observer.on,timers:timers.size,live:live()};
openMemoryDiagnostics(context);MEMORY_DIAGNOSTIC.destroy();grow();
out.destroy={observing:observer.on,timers:timers.size,live:live()};
process.stdout.write(JSON.stringify(out));
"""


def test_the_diagnostic_pin_yields_to_any_user_scroll_and_is_cleaned_up(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    page = HTML.read_text(encoding="utf-8")
    # Le maintien en vue est celui du shell depuis le retravail de la Slice 06 (`pinSettingsTarget`), réutilisé par Mémoire.
    source = (page[page.index("const SETTINGS_PIN_MS=") : page.index("function destroyAgentCatalog()")]
              + page[page.index("function openMemoryDiagnostics(context)") : page.index("/* Une vue du module dans `host`")]
              + page[page.index("let memoryDiagnosticView=null;") : page.index("function installMemorySettingsSections()")])
    script = tmp_path / "pin.cjs"
    script.write_text(PIN.replace("{PAGE_SOURCE}", source), encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["start"] == {"pins": 2, "timers": [4000], "types": ["keydown", "pointerdown", "touchstart", "wheel"], "live": 4}
    released = {"pinned": 0, "observing": False, "timers": 0, "live": 0}  # plus aucun replacement après le geste
    for case in ("wheel", "keydown", "pointerdown", "touchstart", "timeout"):
        assert out[case] == released, (case, out[case])
    assert out["destroy"] == {"observing": False, "timers": 0, "live": 0}

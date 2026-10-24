"""Memory Center (Slice 12 ; refonte-ui-settings Slice 06 : atelier dans les Réglages) : le module servi, exécuté
par node avec un faux `fetch` qui rend des formes de Core."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_memory.js"

PRELUDE = r"""
const MC=require(%MODULE%).JarvisMemoryCenter||globalThis.JarvisMemoryCenter;
const host={innerHTML:'',setAttribute(){}};
const tick=()=>new Promise(r=>setTimeout(r,5));
const calls=[];
const NOTE={id:'n1',title:'Orion <b>x</b>',level:'L2',kind:'preference',retention:'long_term_memory',scope:'private',revision:3,
  created_at:'2026-01-02T10:00:00',updated_at:'2026-02-03T11:00:00',valid_from:null,valid_to:null,confidence:0.8,agent:'brain',
  superseded_by:null,supersedes:['n0'],contradicts:['n9'],sources:[{type:'turn',ref:'turn-42',at:'2026-01-02T10:00:00'}],
  excerpt:'Lyra ORION-47',body:'# Orion\nLyra (code ORION-47) livraison le 14 mars'};
const CAND={id:'c1',title:'Cafe noir',state:'proposed',level:'L1',kind:'preference',retention:'long_term_memory',scope:'private',
  confidence:0.7,created_at:'2026-03-01T09:00:00',conflicts:['n1'],decided_by:null,decided_at:null,committed_memory_id:null,
  sources:[{type:'session',ref:'s1',at:'2026-03-01T09:00:00'}],excerpt:'aime le cafe noir',body:'Aime le cafe noir.'};
let overrides={};
const fetchFn=async(path,init)=>{
  calls.push([path,init&&init.method||'GET',init&&init.body]);
  for(const [k,v] of Object.entries(overrides)){if(path.startsWith(k)){if(v instanceof Error)throw v;return typeof v==='function'?v(path,init):v}}
  if(path.startsWith('/api/memory/notes/'))return {note:NOTE};
  if(path.startsWith('/api/memory/notes'))return {notes:[NOTE],derived:false};
  if(path.startsWith('/api/memory/search'))return {hits:[{id:'n1',title:'Orion',snippet:'...ORION-47...',level:'L2',retention:'long_term_memory',kind:'fact',scope:'private'}],derived:true};
  if(path.endsWith('/decision'))return {candidate:{...CAND,state:JSON.parse(init.body).decision==='accept'?'accepted':'rejected',committed_memory_id:'n7',decided_by:'human.owner'}};
  if(path.startsWith('/api/memory/candidates/'))return {candidate:CAND};
  if(path.startsWith('/api/memory/candidates'))return {candidates:[CAND],available:true};
  if(path.startsWith('/api/memory/status'))return {available:true,index_ready:false,recall_enabled:true,legs:{
    store:{status:'ok',reason_code:null,reason:''},lexical:{status:'ok',reason_code:null,reason:''},
    semantic:{status:'unavailable',reason_code:'semantic_no_key',reason:'pas de cle'},tencent:{status:'disabled',reason_code:'tencent_disabled',reason:''},
    'knowledge:wiki':{status:'ok',reason_code:null,reason:''}}};
  if(path.startsWith('/api/settings'))return {memory:{loadouts:{reviewer:{memory_scopes:['shared'],wiki:false}},
    schema:{sections:[{fields:[{path:'consolidation.mode',options:[{id:'manual',label:'Manuelle'},{id:'auto',label:'Automatique'}]}]}]},
    effective:{'recall.enabled':{value:true},'recall.max_items':{value:6},'semantic.enabled':{value:false},'consolidation.mode':{value:'manual'}}}};
  if(path.startsWith('/api/memory/recall-explain'))return {scopes:['private'],degraded:['index_syncing'],timings_ms:{lexical:12.4},
    budget:{max_items:6,timeout_ms:900,item_chars:400,total_chars:6000},
    items:[{id:'n1',title:'Orion',snippet:'ORION-47',score:0.0312,rank_sources:{lexical:1},why:'mot ORION-47 trouve',level:'L2',retention:'long_term_memory',source:'turn-42',revision:3}]};
  throw new Error('unrouted '+path);
};
"""


def run_node(tmp_path: Path, source: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "t.cjs"
    script.write_text(
        PRELUDE.replace("%MODULE%", json.dumps(str(MODULE)))
        + "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_notes_are_canonical_search_is_derived_and_the_detail_is_escaped(tmp_path):
    out = run_node(tmp_path, """
const v=MC.create(host,{fetch:fetchFn});await v.load();const list=host.innerHTML;
await v.act('note',{id:'n1'});const detail=host.innerHTML;
v.submit('notes',{mcQuery:'orion',mcLevel:'L2',mcRetention:'',mcKind:'',mcSuper:false});await tick();
process.stdout.write(JSON.stringify({list,detail,search:host.innerHTML,calls}));""")
    assert "Canonique" in out["list"] and "Notes Markdown" in out["list"]
    assert any(c[0] == "/api/memory/notes?limit=11&offset=0" for c in out["calls"])  # une page de 10 + 1 pour « suivante »
    d = out["detail"]
    assert "Abstraction" in d and "Rétention" in d
    assert "Scénario" in d and "Long terme" in d and "Préférence" in d and "turn-42" in d and "Révision 3" in d and "n9" in d
    assert "<b>x</b>" not in d and "&lt;b&gt;x&lt;/b&gt;" in d  # le contenu est échappé
    assert "Dérivé" in out["search"] and "index lexical" in out["search"]
    assert any(c[0].startswith("/api/memory/search?q=orion") and "level=L2" in c[0] for c in out["calls"])


def test_hero_metrics_are_live_and_never_invented(tmp_path):
    out = run_node(tmp_path, """
const v=MC.create(host,{fetch:fetchFn});await v.load();const up=host.innerHTML;
overrides['/api/memory/']=Object.assign(new Error('core is not ready'),{code:'core_unavailable'});
const w=MC.create(host,{fetch:fetchFn});await w.load();
process.stdout.write(JSON.stringify({up,down:host.innerHTML}));""")
    up, down = out["up"], out["down"]
    assert "Notes mémoire" in up and "Candidats en attente" in up and "En synchro" in up and "Sources actives (Wiki)" in up
    stats = up.split('class="mc-stats"')[1].split("</ul>")[0]
    assert "Taux de rappel" not in up and "%" not in stats
    assert "Injoignable" in down and "core_unavailable" in down and "Réessayer" in down


def test_decision_needs_confirmation_is_optimistic_and_posts_once(tmp_path):
    out = run_node(tmp_path, """
let release;const held=new Promise(r=>release=r);
overrides['/api/memory/candidates/c1/decision']=async(p,i)=>{await held;return {candidate:{...CAND,state:'rejected',decided_by:'human.owner'}}};
const v=MC.create(host,{fetch:fetchFn});await v.load();
const listed=host.innerHTML;
v.act('cand-reject',{id:'c1'});const asking=host.innerHTML;const before=calls.filter(c=>c[1]==='POST').length;
v.act('cancel');const afterCancel=calls.filter(c=>c[1]==='POST').length;
v.act('cand-reject',{id:'c1'});const deciding=v.decide();await tick();
const pending=host.innerHTML;release();await deciding;
const posts=calls.filter(c=>c[1]==='POST');
process.stdout.write(JSON.stringify({listed,asking,before,afterCancel,pending,posts,done:host.innerHTML,items:v.state.cands.items.length}));""")
    assert "Accepter" in out["listed"] and "Rejeter" in out["listed"] and "Proposition" in out["listed"]
    assert "Rejeter ce candidat" in out["asking"] and "Confirmer le rejet" in out["asking"]
    assert out["before"] == 0 and out["afterCancel"] == 0
    assert "Rejet de" in out["pending"] and "Aucun candidat à décider" in out["pending"]  # optimiste : la carte a quitté la file
    assert len(out["posts"]) == 1
    assert out["posts"][0][0] == "/api/memory/candidates/c1/decision" and json.loads(out["posts"][0][2]) == {"decision": "reject"}
    assert out["items"] == 0 and "rejeté" in out["done"].lower()


def test_a_refused_decision_puts_the_card_back_with_its_real_reason(tmp_path):
    out = run_node(tmp_path, """
overrides['/api/memory/candidates/c1/decision']=Object.assign(new Error('deja decide'),{code:'memory_conflict_revision'});
const v=MC.create(host,{fetch:fetchFn});await v.load();
v.act('cand-accept',{id:'c1'});await v.decide();
process.stdout.write(JSON.stringify({html:host.innerHTML,confirm:v.state.cands.confirm,items:v.state.cands.items.length}));""")
    assert "Décision refusée" in out["html"] and "memory_conflict_revision" in out["html"] and 'role="alert"' in out["html"]
    assert out["confirm"] is None and out["items"] == 1 and "Accepter" in out["html"]


def test_health_is_derived_and_explains_a_syncing_index(tmp_path):
    out = run_node(tmp_path, """
const v=MC.create(host,{fetch:fetchFn});await v.load();
process.stdout.write(JSON.stringify({html:host.innerHTML}));""")
    h = out["html"]
    assert "Santé des index" in h and "Index en synchronisation" in h and "Dérivé" in h
    assert "Indisponible" in h and "Désactivé" in h and "Avancé › Diagnostics" in h


def test_knowledge_is_read_only_and_lists_loadouts(tmp_path):
    out = run_node(tmp_path, """
const v=MC.create(host,{fetch:fetchFn});await v.load();await v.setTab('knowledge');
process.stdout.write(JSON.stringify({html:host.innerHTML}));""")
    k = out["html"]
    assert "Wiki" in k and "reviewer" in k and "sans wiki" in k and "mémoire canonique" in k
    assert 'data-act="decide"' not in k and 'data-act="knowledge-settings"' in k


def test_essential_settings_are_read_only_projections_with_a_link(tmp_path):
    out = run_node(tmp_path, """
const opened=[];const v=MC.create(host,{fetch:fetchFn,open:t=>opened.push(t)});await v.load();
const html=host.innerHTML;v.act('settings');v.act('knowledge-settings');
process.stdout.write(JSON.stringify({html,opened}));""")
    h = out["html"]
    assert "Réglages essentiels" in h and "6 au plus" in h and "Manuelle" in h
    assert "data-mem=" not in h and 'role="switch"' not in h  # aucune seconde copie modifiable
    assert out["opened"] == ["recall", "knowledge_sources"]


def test_recall_test_sends_the_phrase_and_shows_why_in_its_tab(tmp_path):
    out = run_node(tmp_path, """
const v=MC.create(host,{fetch:fetchFn});await v.setTab('recall');
v.submit('recall',{mcRecallQ:'ORION-47',mcRecallMax:'4'});await tick();const result=host.innerHTML;
v.submit('recall',{mcRecallQ:'  ',mcRecallMax:'4'});const empty=host.innerHTML;
process.stdout.write(JSON.stringify({calls,result,empty}));""")
    assert any(c[0] == "/api/memory/recall-explain?q=ORION-47&max_items=4" for c in out["calls"])
    r = out["result"]
    assert "Pourquoi" in r and "mot ORION-47 trouve" in r and "Aperçu dérivé" in r and "Index en synchronisation" in r
    assert "0.031" in r and "lexical 1" in r
    assert "Saisissez une phrase" in out["empty"]


def test_errors_and_empty_states_are_visible(tmp_path):
    out = run_node(tmp_path, """
overrides['/api/memory/notes?limit=11']=Object.assign(new Error('Core is unreachable'),{code:'core_unreachable'});
const v=MC.create(host,{fetch:fetchFn});await v.load();const err=host.innerHTML;
overrides={'/api/memory/notes':{notes:[]},'/api/memory/candidates':{candidates:[],available:false}};
const w=MC.create(host,{fetch:fetchFn});await w.load();const empty=host.innerHTML;
process.stdout.write(JSON.stringify({err,empty,tabs:MC.TABS.map(t=>t[0])}));""")
    assert 'role="alert"' in out["err"] and "core_unreachable" in out["err"] and "Réessayer" in out["err"]
    assert "Aucune note en mémoire" in out["empty"] and "n’est pas branchée" in out["empty"]
    assert out["tabs"] == ["notes", "candidates", "knowledge", "recall"]


def test_tabs_are_keyboard_navigable(tmp_path):
    out = run_node(tmp_path, """
const v=MC.create(host,{fetch:fetchFn});
process.stdout.write(JSON.stringify({r:v.tabKey('ArrowRight',3),l:v.tabKey('ArrowLeft',0),h:v.tabKey('Home',2),e:v.tabKey('End',0),x:v.tabKey('a',1),html:host.innerHTML}));""")
    assert out["r"] == 0 and out["l"] == 3 and out["h"] == 0 and out["e"] == 3 and out["x"] is None
    assert 'role="tablist"' in out["html"] and 'aria-selected="true"' in out["html"] and 'tabindex="-1"' in out["html"]

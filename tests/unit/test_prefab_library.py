"""Bibliothèque des prefabs du dock `PFB` (jarvis-scene-window-prefab-foundation, Slice 08).

Le module est le fichier même que `ControlCenter.index` insère. Ce que ce
fichier épingle :

- le modèle pur : nature et badges (base, base modifiée, fork, custom,
  révision) lus dans l'historique de `publication.json`, filtre, tri, chaîne de
  provenance (fork de fork, maillon absent, cycle), arbre des entrées,
  candidat de fork (source copiée telle quelle, nouvel id, alias retirés,
  réglages devenus défauts), commande « Placer sur la scène » ;
- le contrôleur : lecture à l'ouverture, un prefab publié entre deux
  ouvertures apparaît sans changer la page, l'aperçu ne poste rien, chaque
  refus garde son code ;
- le relais `POST /api/prefabs` sur la pile réelle Core + Control Center :
  acteur forcé à `user`, origine `fork` avec `derived_from`, `jarvis.*` refusé
  `base_protected` sans rien écrire, corps refusés, `Origin: null` refusé ;
- le module JS lui-même, exécuté par node contre ce Control Center réel :
  fork de `jarvis.checklist` en `team.checklist-red` (badge fork + parent),
  `jarvis.*` dans le formulaire -> `base_protected` affiché, placement sur la
  scène acteur `user` ;
- gardes statiques : aucun `innerHTML` (ni balisage en chaîne), partie pure
  sans DOM, page servie avec le bouton, la vue et le module.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import PREFABS_SCRIPT_FILE, PREFABS_SCRIPT_MARKER, ControlCenter
from jarvis.runtime.scene_view import CoreSceneTransport, CoreSceneView
from tests.fakes.capture_stack import CaptureStack
from tests.fakes.prefabs import candidate

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
PAGE = RUNTIME / "control_center.html"
MODULE = RUNTIME / PREFABS_SCRIPT_FILE

WORLD = r"""
const C=require(MODULE_PATH);
const out=v=>process.stdout.write(JSON.stringify(v));
const settle=async()=>{for(let i=0;i<40;i+=1)await new Promise(r=>setImmediate(r))};
const hist=(version,origin,extra)=>Object.assign({version,root:'data',status:'ok',origin,derived_from:null,
  created_by:{actor:origin==='base'?'system':'user'},base_edit:null,published_at:'2026-10-03T12:00:00Z',fingerprint:'f'},extra||{});
const detailOf=(id,history,manifest)=>({id,version:history[history.length-1].version,latest_version:history[history.length-1].version,
  class:id.startsWith('jarvis.')?'base':'custom',manifest:manifest||{id,title:id,family:'window'},publication:{},history});
const rowOf=(id,versions,over)=>Object.assign({id,latest_version:versions[versions.length-1],versions,title:id,family:'window',
  class:id.startsWith('jarvis.')?'base':'custom',description:'',input_names:[],event_names:[],base_edited:false},over||{});
/* Un serveur double qui parle les formes réelles de `/api/prefabs*` et `/api/scene/commands`. */
const makeServer=()=>{
  const s={calls:[],rows:[],details:{},plan:{},sources:{}};
  s.fetch=async(path,options)=>{
    const method=(options&&options.method)||'GET';
    const body=options&&options.body?JSON.parse(options.body):undefined;
    s.calls.push({method,path,body});
    const forced=s.plan[`${method} ${path.split('?')[0]}`];
    const reply=(status,payload)=>({ok:status<400,status,text:async()=>JSON.stringify(payload)});
    if(forced)return reply(forced.status,forced.body);
    const bare=path.split('?')[0];
    if(method==='GET'&&bare==='/api/prefabs'){
      const q=new URLSearchParams(path.split('?')[1]||'').get('query');
      return reply(200,{prefabs:s.rows.filter(r=>!q||r.id.includes(q))});
    }
    const m=bare.match(/^\/api\/prefabs\/([^/]+)(?:\/(\d+))?$/);
    if(method==='GET'&&m){
      const id=decodeURIComponent(m[1]);const d=s.details[id];
      if(!d)return reply(404,{error:{code:'unknown_prefab',message:`unknown prefab ${id}`}});
      return reply(200,m[2]?Object.assign({},d,{version:Number(m[2]),files:s.sources[id]}):d);
    }
    if(method==='POST'&&bare==='/api/scene/commands')return reply(200,{outcome:'applied',revision:7});
    if(method==='POST'&&bare==='/api/prefabs'){
      const id=body.candidate.manifest.id;
      if(id.startsWith('jarvis.'))return reply(403,{error:{code:'base_protected',message:`${id} is a base prefab`}});
      s.rows.push(rowOf(id,[1]));
      s.details[id]=detailOf(id,[hist(1,'fork',{derived_from:body.derived_from})],body.candidate.manifest);
      return reply(201,{prefab_id:id,version:1,provenance:{origin:'fork',derived_from:body.derived_from,created_by:{actor:'user'}}});
    }
    return reply(404,{error:{code:'not_found',message:path}});
  };
  return s;
};
const world=()=>{
  const server=makeServer();
  const logs=[];
  const client=C.createClient({fetchImpl:(p,o)=>server.fetch(p,o),setTimer:()=>0,clearTimer:()=>{}});
  const lib=C.createLibrary({client,log:(level,event,data)=>logs.push({level,event,data}),newId:()=>'abc123abc123'});
  return {server,lib,S:lib.state,logs,act:async p=>{const r=await p;await settle();return r}};
};
"""


def run_node(tmp_path: Path, source: str, name: str = "pfb") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"prefabs-{name}.cjs"
    script.write_text(f"const MODULE_PATH={json.dumps(str(MODULE))};\n" + WORLD
                      + "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
                      encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------------ modèle pur


def test_kind_and_badges_come_from_the_publication_history(tmp_path):
    seen = run_node(tmp_path, r"""
      const lin=d=>C.lineageOf(d);
      const base=detailOf('jarvis.checklist',[hist(1,'base')]);
      const edited=detailOf('jarvis.table',[hist(1,'base'),hist(2,'base_edit',{created_by:{actor:'brain'},
        derived_from:{id:'jarvis.table',version:1},base_edit:{confirmed_by_user:true,user_request:'mets le tableau en rouge',witness:'conversation_event:cev-1'}})]);
      const fork=detailOf('team.red',[hist(1,'fork',{derived_from:{id:'jarvis.checklist',version:1}})]);
      const revised=detailOf('team.red2',[hist(1,'fork',{derived_from:{id:'jarvis.checklist',version:1}}),hist(2,'revision',{derived_from:{id:'team.red2',version:1}})]);
      const custom=detailOf('lab.timer',[hist(1,'custom')]);
      const tampered=detailOf('lab.bad',[hist(1,'custom'),hist(2,'revision',{status:'tampered',problem:'fingerprint mismatch'})]);
      const cases=[[rowOf('jarvis.checklist',[1]),base],[rowOf('jarvis.table',[1,2],{base_edited:true}),edited],
        [rowOf('team.red',[1]),fork],[rowOf('team.red2',[1,2]),revised],[rowOf('lab.timer',[1]),custom],[rowOf('lab.bad',[1]),tampered],
        [rowOf('lab.unread',[1]),null],[rowOf('jarvis.window',[1]),null]];
      out({badges:cases.map(([r,d])=>C.badgesOf(r,d&&lin(d)).map(b=>[b.key,b.label,b.tone])),
        kinds:cases.map(([r,d])=>C.kindOf(r,d&&lin(d))),
        edits:lin(edited).baseEdits.map(v=>[v.version,v.actor,v.baseEdit.request,v.baseEdit.witness]),
        forkParent:lin(fork).parent,revisedParent:lin(revised).parent,tamperedLatest:lin(tampered).latestVersion});
    """)
    assert seen["badges"] == [
        [["base", "Base", "base"]],
        [["base_edited", "Base modifiée à votre demande", "edited"]],
        [["fork", "Fork", "fork"]],
        [["fork", "Fork", "fork"], ["revision", "Révision v2", "muted"]],
        [["custom", "Custom", "custom"]],
        [["custom", "Custom", "custom"]],
        [["pending", "Provenance…", "muted"]],
        [["base", "Base", "base"]],
    ]
    assert seen["kinds"] == ["base", "base_edited", "fork", "fork", "custom", "custom", None, "base"]
    assert seen["edits"] == [[2, "brain", "mets le tableau en rouge", "conversation_event:cev-1"]]
    # Le parent d'un fork reste celui de sa naissance, même après une révision.
    assert seen["forkParent"] == seen["revisedParent"] == {"id": "jarvis.checklist", "version": 1}
    # Une version altérée n'est jamais « la dernière ».
    assert seen["tamperedLatest"] == 1


def test_filter_sort_and_counts(tmp_path):
    seen = run_node(tmp_path, r"""
      const e=(id,kind,title,family)=>({row:rowOf(id,[1],{title,family:family||'window'}),kind});
      const all=[e('team.b','fork','Zeta'),e('jarvis.table','base','Tableau'),e('lab.a','custom','Alpha','indicator'),
        e('jarvis.checklist','base_edited','Checklist'),e('lab.pending',null,'Beta')];
      all[1].row.class='base';all[3].row.class='base';
      const ids=list=>list.map(x=>x.row.id);
      out({sorted:ids(C.sortEntries(all)),ranked:ids(C.sortEntries(all,{ranked:true})),
        forks:ids(C.filterEntries(all,{kind:'fork'})),edited:ids(C.filterEntries(all,{kind:'base_edited'})),
        custom:ids(C.filterEntries(all,{kind:'custom'})),family:ids(C.filterEntries(all,{family:'indicator'})),
        counts:C.countsOf(all),families:C.familiesOf(all)});
    """)
    # Bases d'abord, puis par titre.
    assert seen["sorted"] == ["jarvis.checklist", "jarvis.table", "lab.a", "lab.pending", "team.b"]
    assert seen["ranked"] == ["team.b", "jarvis.table", "lab.a", "jarvis.checklist", "lab.pending"]
    assert seen["forks"] == ["team.b"] and seen["edited"] == ["jarvis.checklist"] and seen["custom"] == ["lab.a"]
    assert seen["family"] == ["lab.a"]
    assert seen["counts"] == {"all": 5, "base": 1, "base_edited": 1, "fork": 1, "custom": 1}
    assert seen["families"] == ["indicator", "window"]


def test_the_provenance_chain_follows_forks_and_stops_at_unknown_or_cycles(tmp_path):
    seen = run_node(tmp_path, r"""
      const L={
        'team.c':{born:'fork',parent:{id:'team.b',version:2}},
        'team.b':{born:'fork',parent:{id:'jarvis.checklist',version:1}},
        'jarvis.checklist':{born:'base',parent:null},
        'x.one':{born:'fork',parent:{id:'x.two',version:1}},
        'x.two':{born:'fork',parent:{id:'x.one',version:1}},
        'y.orphan':{born:'fork',parent:{id:'y.gone',version:3}},
      };
      const look=id=>L[id]||null;
      out({deep:C.provenanceChain('team.c',look),cycle:C.provenanceChain('x.one',look).map(n=>[n.id,!!n.cycle]),
        orphan:C.provenanceChain('y.orphan',look),alone:C.provenanceChain('jarvis.checklist',look)});
    """)
    assert [(n["id"], n["version"], n["known"]) for n in seen["deep"]] == [
        ("jarvis.checklist", 1, True), ("team.b", 2, True), ("team.c", None, True)]
    assert seen["cycle"] == [["x.one", True], ["x.two", False], ["x.one", False]]
    assert [(n["id"], n["version"], n["known"]) for n in seen["orphan"]] == [("y.gone", 3, False), ("y.orphan", None, True)]
    assert len(seen["alone"]) == 1


def test_inputs_events_and_the_fork_candidate_copy_the_source_unchanged(tmp_path):
    manifest = json.loads((ROOT / "jarvis" / "prefabs" / "base" / "jarvis.checklist" / "1" / "manifest.json").read_text(encoding="utf-8"))
    seen = run_node(tmp_path, f"const M={json.dumps(manifest)};" + r"""
      const source={id:'jarvis.checklist',version:1,manifest:M,files:{template:'<ul></ul>',style:'a{}',behavior:'jarvis.on("init",()=>{})'}};
      const before=JSON.stringify(source);
      const built=C.forkCandidate(source,{id:' team.checklist-red ',title:'Checklist rouge',description:'Rouge',defaults:{accent:'#ff4d5e'}});
      out({tree:C.inputsTree(M).map(n=>[n.path,n.depth,n.type,n.required]),events:C.eventsOf(M).map(e=>[e.name,e.cls,e.writes]),
        defaults:C.editableDefaults(M).map(d=>[d.name,d.type]),built,unchanged:JSON.stringify(source)===before,
        missing:C.forkCandidate(source,{id:'  '}).error.code,
        place:C.placeCommand({id:'jarvis.checklist',version:1,manifest:M},'user-prefab-1')});
    """)
    paths = [row[0] for row in seen["tree"]]
    assert paths[:2] == ["props", "props.accent"] and "data.items" in paths and "data.items[].label" in paths
    assert ["data.items[].id", 3, "string", True] in seen["tree"]
    assert seen["events"] == [["item_toggled", "state", ["items"]], ["checklist_completed", "notify", []]]
    assert [name for name, _ in seen["defaults"]] == ["accent", "show_progress"]
    built = seen["built"]
    m = built["candidate"]["manifest"]
    assert (m["id"], m["version"], m["title"], m["description"], m["aliases"]) == (
        "team.checklist-red", 1, "Checklist rouge", "Rouge", [])
    assert m["inputs"]["props"]["properties"]["accent"]["default"] == "#ff4d5e" and m["sample"]["props"]["accent"] == "#ff4d5e"
    assert m["events"] == manifest["events"] and m["sample"]["data"] == manifest["sample"]["data"]
    assert built["candidate"]["template"] == "<ul></ul>" and built["candidate"]["behavior"] == 'jarvis.on("init",()=>{})'
    assert built["derived_from"] == {"id": "jarvis.checklist", "version": 1}
    assert seen["unchanged"] is True and seen["missing"] == "missing_id"
    place = seen["place"]
    assert place["op"] == "upsert_object" and place["object_id"] == "user-prefab-1" and "actor" not in place
    assert (place["fields"]["kind"], place["fields"]["category"], place["fields"]["representation"]) == ("window", "prefab", "window")
    assert place["fields"]["payload"]["prefab"] == {"id": "jarvis.checklist", "version": 1,
                                                     "props": manifest["sample"]["props"], "data": manifest["sample"]["data"]}


def test_the_client_refuses_every_route_outside_its_contract_before_the_network(tmp_path):
    seen = run_node(tmp_path, r"""
      const ok=[['GET','/api/prefabs?query=check&limit=50'],['GET','/api/prefabs/jarvis.checklist'],
        ['GET','/api/prefabs/jarvis.checklist/1?include_source=1'],['POST','/api/prefabs'],['POST','/api/scene/commands']];
      const bad=[['POST','/api/prefabs/jarvis.checklist/base-edits'],['POST','/api/prefabs/validate'],['POST','/api/prefabs/events'],
        ['GET','/api/prefabs/events'],['GET','/api/prefabs/validate'],['GET','/api/prefabs/a.b/1/bundle'],['DELETE','/api/prefabs/a.b'],
        ['GET','//evil/api/prefabs'],['GET','/api/prefabs/%2e%2e/x'],['GET','/api/scene'],['POST','/api/prefabs?x=1'],
        ['GET','https://evil.example/api/prefabs'],['PUT','/api/prefabs']];
      const w=world();
      let refused=null;
      try{await C.createClient({fetchImpl:w.server.fetch}).post('/api/prefabs/jarvis.checklist/base-edits',{})}
      catch(e){refused=e.code}
      out({ok:ok.map(([m,p])=>C.allowed(m,p)),bad:bad.map(([m,p])=>C.allowed(m,p)),refused,calls:w.server.calls.length});
    """)
    assert seen["ok"] == [True] * 5 and seen["bad"] == [False] * 13
    assert seen["refused"] == "forbidden_route" and seen["calls"] == 0


# ------------------------------------------------------------------ contrôleur


def test_open_reads_the_catalogue_and_a_prefab_published_meanwhile_appears_on_reopen(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      w.server.rows=[rowOf('jarvis.checklist',[1])];
      w.server.details['jarvis.checklist']=detailOf('jarvis.checklist',[hist(1,'base')]);
      await w.act(w.lib.open());
      const first=w.lib.visible().map(e=>[e.row.id,e.kind]);
      w.lib.close();
      /* JARVIS publie un fork entre deux ouvertures (MCP `prefab_save`) : rien de la page ne change. */
      w.server.rows.push(rowOf('team.brain',[1]));
      w.server.details['team.brain']=detailOf('team.brain',[hist(1,'fork',{created_by:{actor:'brain'},derived_from:{id:'jarvis.checklist',version:1}})]);
      await w.act(w.lib.open());
      const second=w.lib.visible().map(e=>[e.row.id,e.kind,e.parent&&e.parent.id]);
      await w.act(w.lib.setQuery('check'));
      out({first,second,lastList:w.server.calls.filter(c=>c.path.startsWith('/api/prefabs?')).map(c=>c.path),
        detailReads:w.server.calls.filter(c=>c.path==='/api/prefabs/jarvis.checklist').length,
        status:C.statusView(w.lib).tone,logs:w.logs.filter(l=>l.event==='prefabs.list_read').length});
    """)
    assert seen["first"] == [["jarvis.checklist", "base"]]
    assert seen["second"] == [["jarvis.checklist", "base", None], ["team.brain", "fork", "jarvis.checklist"]]
    assert seen["lastList"] == ["/api/prefabs?limit=50", "/api/prefabs?limit=50", "/api/prefabs?query=check&limit=50"]
    # Une version publiée ne change jamais : sa provenance n'est relue que si ses versions changent.
    assert seen["detailReads"] == 1
    assert seen["status"] == "live" and seen["logs"] == 3


def test_preview_events_stay_local_and_place_posts_one_user_scene_command(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      const M={id:'jarvis.checklist',title:'Checklist',family:'window',sample:{props:{accent:'#6ee7ff'},data:{items:[]}},
        events:{item_toggled:{class:'state',writes:['items']},checklist_completed:{class:'notify'}}};
      w.server.rows=[rowOf('jarvis.checklist',[1])];
      w.server.details['jarvis.checklist']=detailOf('jarvis.checklist',[hist(1,'base')],M);
      await w.act(w.lib.open());
      w.lib.select('jarvis.checklist');await w.act(Promise.resolve());
      for(let i=0;i<60;i+=1)w.lib.logPreviewEvent({event:i%2?'checklist_completed':'item_toggled',payload:{n:i}},M);
      const posts=w.server.calls.filter(c=>c.method==='POST').length;
      const placed=await w.act(w.lib.place());
      const scenePosts=w.server.calls.filter(c=>c.method==='POST');
      w.server.plan['POST /api/scene/commands']={status:200,body:{outcome:'invalid',reason:'prefab_invalid',detail:'win: invalid_definition: data.items'}};
      const refused=await w.act(w.lib.place());
      w.server.plan['POST /api/scene/commands']={status:503,body:{error:{code:'not_configured',message:'Commande de scène Core non configurée.'}}};
      const down=await w.act(w.lib.place());
      out({log:w.S.previewLog.length,first:w.S.previewLog[0],postsBeforePlace:posts,scenePosts:scenePosts.map(c=>[c.path,c.body.fields.payload.prefab.id]),
        placed:[placed.status,placed.result.objectId],refused:[refused.status,refused.error.code,refused.error.message],
        down:[down.status,down.error.code,C.errorView(down.error).title]});
    """)
    assert seen["log"] == 50 and seen["first"]["name"] == "checklist_completed" and seen["first"]["cls"] == "notify"
    assert seen["postsBeforePlace"] == 0
    assert seen["scenePosts"] == [["/api/scene/commands", "jarvis.checklist"]]
    assert seen["placed"] == ["done", "user-prefab-abc123abc123"]
    assert seen["refused"] == ["error", "prefab_invalid", "win: invalid_definition: data.items"]
    assert seen["down"] == ["error", "not_configured", "Scène non reliée à Core"]


def test_fork_flow_and_every_refusal_keeps_its_code(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      const M={id:'jarvis.checklist',title:'Checklist',description:'d',family:'window',aliases:['todo'],
        inputs:{props:{type:'object',properties:{accent:{type:'color',default:'#6ee7ff'}}},data:{type:'object',properties:{}}},
        sample:{props:{},data:{}},events:{}};
      w.server.rows=[rowOf('jarvis.checklist',[1])];
      w.server.details['jarvis.checklist']=detailOf('jarvis.checklist',[hist(1,'base')],M);
      w.server.sources['jarvis.checklist']={template:'<p></p>',style:'',behavior:''};
      await w.act(w.lib.open());w.lib.select('jarvis.checklist');await w.act(Promise.resolve());
      w.lib.openFork();
      const initial=w.S.fork.initial;
      await w.act(w.lib.submitFork({id:'jarvis.checklist-red',title:'x',description:'',defaults:{}}));
      const protectedState=[w.S.fork.status,w.S.fork.error.code,C.errorView(w.S.fork.error).title];
      w.server.plan['POST /api/prefabs']={status:400,body:{error:{code:'invalid_definition',message:'candidate refused: manifest.title too long',
        errors:['manifest.title too long','manifest.description too long']}}};
      await w.act(w.lib.submitFork({id:'team.long',title:'x'.repeat(90),description:'',defaults:{}}));
      const invalid=[w.S.fork.error.code,w.S.fork.error.errors];
      delete w.server.plan['POST /api/prefabs'];
      const pub=await w.act(w.lib.submitFork({id:'team.checklist-red',title:'Checklist rouge',description:'',defaults:{accent:'#ff4d5e'}}));
      const posted=w.server.calls.filter(c=>c.method==='POST'&&c.path==='/api/prefabs').map(c=>[c.body.candidate.manifest.id,c.body.derived_from,'actor' in c.body]);
      const red=w.lib.visible().find(e=>e.row.id==='team.checklist-red');
      out({initial:[initial.id,initial.title,initial.defaults.map(d=>[d.name,d.value])],protectedState,invalid,
        pub:pub&&pub.prefab_id,fork:w.S.fork,selected:w.S.selected,notice:w.S.notice.title,posted,
        red:[red.kind,red.parent,red.badges.map(b=>b.key)]});
    """)
    assert seen["initial"] == ["", "Checklist (fork)", [["accent", "#6ee7ff"]]]
    assert seen["protectedState"] == ["error", "base_protected", "Identifiant réservé aux prefabs de base"]
    assert seen["invalid"] == ["invalid_definition", ["manifest.title too long", "manifest.description too long"]]
    assert seen["pub"] == "team.checklist-red" and seen["fork"] is None and seen["selected"] == "team.checklist-red"
    assert seen["notice"] == "Fork publié : team.checklist-red v1"
    # La page n'envoie jamais d'acteur : le Control Center pose `user`.
    assert seen["posted"][-1] == ["team.checklist-red", {"id": "jarvis.checklist", "version": 1}, False]
    assert seen["red"] == ["fork", {"id": "jarvis.checklist", "version": 1}, ["fork"]]


def test_a_stale_list_answer_never_overwrites_a_newer_search(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      w.server.rows=[rowOf('jarvis.checklist',[1]),rowOf('jarvis.table',[1])];
      const real=w.server.fetch;let release;
      w.server.fetch=async(path,o)=>{if(path==='/api/prefabs?limit=50')await new Promise(r=>{release=r});return real(path,o)};
      const client=C.createClient({fetchImpl:w.server.fetch,setTimer:()=>0,clearTimer:()=>{}});
      const lib=C.createLibrary({client});
      const slow=lib.open();await new Promise(r=>setImmediate(r));
      await lib.setQuery('table');
      release();await slow;
      out(lib.visible().map(e=>e.row.id));
    """)
    assert seen == ["jarvis.table"]


# ------------------------------------------------------------------ relais réel


def _fork_body(prefab_id: str, **extra) -> dict:
    return {"candidate": candidate("test.counter", id=prefab_id),
            "derived_from": {"id": "jarvis.checklist", "version": 1}, **extra}


async def test_post_prefabs_forces_the_user_actor_and_core_records_a_fork(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        status, body, _ = await stack.call("POST", "/api/prefabs", json=_fork_body("team.counter", actor="brain"))
        assert status == 201, body
        assert body["prefab_id"] == "team.counter" and body["version"] == 1
        assert body["provenance"] == {"origin": "fork", "derived_from": {"id": "jarvis.checklist", "version": 1},
                                      "created_by": {"actor": "user"}, "base_edit": None}
        stored = json.loads((stack.data_root / "prefabs" / "team.counter" / "1" / "publication.json").read_text(encoding="utf-8"))
        assert stored["provenance"]["created_by"] == {"actor": "user"} and stored["provenance"]["origin"] == "fork"
        status, listed, _ = await stack.call("GET", "/api/prefabs", params={"query": "team.counter"})
        assert [row["id"] for row in listed["prefabs"]] == ["team.counter"]
        relayed = [e for e in stack.trace() if e.get("kind") == "prefab.request.relayed" and e["data"]["action"] == "prefab_save"]
        assert relayed[-1]["data"] == {"action": "prefab_save", "status": 201, "code": None, "prefab_id": "team.counter",
                                       "version": 1, "origin": "fork"}
        # Le journal ne porte jamais les sources.
        assert "jarvis.on" not in json.dumps(stack.trace())


async def test_a_jarvis_id_is_base_protected_and_nothing_is_written(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        status, body, _ = await stack.call("POST", "/api/prefabs", json=_fork_body("jarvis.checklist-red"))
        assert (status, body["error"]["code"]) == (403, "base_protected")
        status, body, _ = await stack.call("POST", "/api/prefabs", json=_fork_body("jarvis.checklist"))
        assert (status, body["error"]["code"]) == (403, "base_protected")
        assert not (stack.data_root / "prefabs" / "jarvis.checklist-red").exists()
        assert not (stack.data_root / "prefabs" / "jarvis.checklist").exists()
        relayed = [e["data"] for e in stack.trace() if e.get("kind") == "prefab.request.relayed"]
        assert relayed[-1]["code"] == "base_protected" and relayed[-1]["prefab_id"] is None


async def test_bad_bodies_and_foreign_origins_are_refused(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        for bad in (b"[]", b"not json", b""):
            status, body, _ = await stack.call("POST", "/api/prefabs", data=bad)
            assert (status, body["error"]["code"]) == (400, "invalid_request")
        status, body, _ = await stack.call("POST", "/api/prefabs", params={"x": "1"}, json=_fork_body("team.a"))
        assert (status, body["error"]["code"]) == (400, "invalid_request")
        # Core refuse les clés inconnues : le relais ne les filtre pas, il ne les cache pas non plus.
        status, body, _ = await stack.call("POST", "/api/prefabs", json={**_fork_body("team.a"), "extra": 1})
        assert (status, body["error"]["code"]) == (400, "invalid_request")
        status, body, _ = await stack.call("POST", "/api/prefabs", data=b"x" * (512 * 1024 + 1),
                                           headers={"Content-Type": "application/json"})
        assert (status, body["error"]["code"]) == (400, "invalid_request")
        for headers in ({"Origin": "null"}, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            status, body, _ = await stack.call("POST", "/api/prefabs", json=_fork_body("team.a"), headers=headers)
            assert status == 403 and body["code"] == "forbidden_origin"
        assert not (stack.data_root / "prefabs" / "team.a").exists()
        # Toujours aucune route d'édition de base côté Control Center.
        status, _, _ = await stack.call("POST", "/api/prefabs/jarvis.checklist/base-edits", json={})
        assert status in (404, 405)


async def test_the_page_module_forks_and_places_against_the_real_control_center(tmp_path):
    """Le vrai module JS, par node, contre ce Control Center et ce Core réels."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    async with CaptureStack(tmp_path) as stack:
        port = int(stack.core_url.rsplit(":", 1)[1])
        transport = CoreSceneTransport(host="127.0.0.1", port=port, token_file=tmp_path / "core.token")
        stack.center.scene_view = CoreSceneView(transport)
        base = f"http://127.0.0.1:{stack.cc_port}"
        script = tmp_path / "e2e.cjs"
        script.write_text(f"const MODULE_PATH={json.dumps(str(MODULE))};const BASE={json.dumps(base)};\n" + r"""
const C=require(MODULE_PATH);
const settle=async()=>{for(let i=0;i<20;i+=1)await new Promise(r=>setTimeout(r,15))};
(async()=>{
  const client=C.createClient({fetchImpl:(p,o)=>fetch(BASE+p,o)});
  const lib=C.createLibrary({client});
  await lib.open();await lib.setQuery('check');await settle();
  const found=lib.visible().map(e=>[e.row.id,e.kind]);
  lib.select('jarvis.checklist');await settle();
  const shown=lib.shown().data;
  const placed=await lib.place();
  lib.openFork();
  await lib.submitFork({id:'jarvis.checklist-red',title:'Rouge',description:'',defaults:{accent:'#ff4d5e'}});
  const refused=[lib.state.fork.error.code,lib.state.fork.error.status,C.errorView(lib.state.fork.error).title];
  const pub=await lib.submitFork({id:'team.checklist-red',title:'Checklist rouge',description:'Variante rouge',defaults:{accent:'#ff4d5e',show_progress:true}});
  await lib.setQuery('');await settle();
  const red=lib.visible().find(e=>e.row.id==='team.checklist-red');
  lib.select('team.checklist-red');await settle();
  const chain=C.provenanceChain('team.checklist-red',id=>lib.lineage(id)).map(n=>[n.id,n.version]);
  process.stdout.write(JSON.stringify({found,shownVersion:shown&&shown.version,placed:[placed.status,placed.result&&placed.result.objectId,placed.error&&placed.error.code],
    refused,pub:pub&&[pub.prefab_id,pub.provenance.origin,pub.provenance.created_by.actor],
    red:red&&[red.kind,red.parent,red.badges.map(b=>b.label)],chain,accent:lib.shown().data.manifest.inputs.props.properties.accent.default}));
})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});
""", encoding="utf-8")
        try:
            process = await asyncio.create_subprocess_exec(node, str(script), stdout=asyncio.subprocess.PIPE,
                                                           stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
        finally:
            await transport.close()
        assert process.returncode == 0, stderr.decode("utf-8", "replace")
        seen = json.loads(stdout)
        snapshot = await stack.core.scene.snapshot()
    assert ["jarvis.checklist", "base"] in seen["found"]
    assert seen["shownVersion"] == 1
    assert seen["placed"][0] == "done", seen["placed"]
    assert seen["placed"][1].startswith("user-prefab-")
    placed = next(o for o in snapshot.objects if o.object_id == seen["placed"][1])
    assert placed.payload.prefab.prefab_id == "jarvis.checklist" and placed.origin.value == "user"
    assert seen["refused"] == ["base_protected", 403, "Identifiant réservé aux prefabs de base"]
    assert seen["pub"] == ["team.checklist-red", "fork", "user"]
    assert seen["red"] == ["fork", {"id": "jarvis.checklist", "version": 1}, ["Fork"]]
    assert seen["chain"] == [["jarvis.checklist", 1], ["team.checklist-red", None]]
    assert seen["accent"] == "#ff4d5e"


# ------------------------------------------------------------------ gardes statiques et page


def test_no_markup_strings_and_a_pure_core():
    text = MODULE.read_text(encoding="utf-8")
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "srcdoc"):
        assert forbidden not in text, forbidden
    # Inséré dans le bloc de script de la page : ni balise de script ni commentaire HTML en clair.
    assert not re.search(r"(?i)</?script|<!--", text)
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    for forbidden in ("window.confirm", "alert(", "prompt(", "localStorage", "base-edits", "/validate"):
        assert forbidden not in code, forbidden
    core = code[: code.index("(function installJarvisPrefabLibrary(){")]
    for forbidden in ("document.", "window.", "innerHTML"):
        assert forbidden not in core, f"pure part touches {forbidden}"


@pytest.mark.asyncio
async def test_the_served_page_carries_the_dock_button_the_view_and_the_module(tmp_path):
    center = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = (await center.index(None)).text
    assert PREFABS_SCRIPT_MARKER not in html
    assert "const JarvisPrefabLibraryCore=" in html
    # Après l'hôte des cadres, dont l'aperçu se sert.
    assert html.index("root.JarvisPrefabHost=api") < html.index("const JarvisPrefabLibraryCore=")
    dock = html[html.index('<nav class="dock"'): html.index("</nav>", html.index('<nav class="dock"'))]
    button = re.search(r'<button id="openPrefabs"[^>]*>PFB</button>', dock).group(0)
    for attribute in ('aria-label="Prefabs · bibliothèque partagée, aperçu et fork"', 'aria-haspopup="dialog"',
                      'aria-expanded="false"', 'aria-controls="prefabLibrary"'):
        assert attribute in button
    assert dock.index('id="openWorkspace"') < dock.index('id="openPrefabs"')
    view = html[html.index('<section class="pfb"'): html.index("</section>", html.index('<section class="pfb"'))]
    # Nom dit en clair : le titre visible est en capitales par le CSS, que Chrome reporte dans le nom.
    for attribute in ('role="dialog"', 'aria-modal="true"', 'aria-label="Bibliothèque des prefabs"', 'aria-describedby="pfbHelp"', " hidden>"):
        assert attribute in view
    assert 'aria-live="polite"' in view and 'type="search"' in view
    # L'aide dit la règle des bases.
    assert "seul JARVIS le peut, à votre demande explicite" in view


def test_every_element_the_browser_block_reaches_for_exists_and_page_shortcuts_stop_at_the_view():
    source = MODULE.read_text(encoding="utf-8")
    browser = source[source.index("(function installJarvisPrefabLibrary(){"):]
    html = PAGE.read_text(encoding="utf-8")
    wanted = set(re.findall(r"q\('#([A-Za-z0-9_]+)'\)", browser)) | set(re.findall(r"getElementById\('([A-Za-z0-9_]+)'\)", browser))
    assert {"prefabLibrary", "openPrefabs", "pfbList", "pfbDetail", "pfbSearch", "pfbKinds"} <= wanted
    produced = set(re.findall(r"id:'([A-Za-z]+)'", source))
    assert sorted(name for name in wanted if f'id="{name}"' not in html and name not in produced) == []
    handler = html[html.index("window.addEventListener('keydown',event=>{\n  if(SET.capture"):]
    handler = handler[: handler.index("\n});")]
    assert handler.index("if(prefabLibrary&&!prefabLibrary.hidden)return;") < handler.index("const match=")
    css = html[html.index("/* ---------- Bibliothèque des prefabs (plein écran)"): html.index("</style>")]
    assert re.search(r"\.pfb\{position:fixed;inset:0;z-index:55;", css)
    assert not re.search(r"#6ee7ff|#ff6577|#ffb85c|#68e0a0", css, re.I), "page tokens, not new brand colours"
    assert "@media(max-width:700px)" in css and "@media(prefers-reduced-motion:reduce){.pfb-spin{animation:none}" in css
    # Le registre d'empilement nomme la vue au rang des autres vues plein écran.
    assert "bibliothèque des prefabs `.pfb`" in html[: html.index("</style>")]


def test_a_missing_view_is_refused_by_name_without_throwing(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "install.cjs"
    script.write_text(
        "globalThis.window=globalThis;globalThis.document={getElementById:()=>null};\n"
        "const lines=[];console.error=(...a)=>lines.push(a.join(' '));\n"
        f"require({json.dumps(str(MODULE))});\n"
        "process.stdout.write(JSON.stringify({lines,api:typeof window.JarvisPrefabLibrary}));",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["api"] == "undefined"
    assert len(result["lines"]) == 1 and "prefabs_host_missing" in result["lines"][0]


# ------------------------------------------------------------------ reprise QA (rework S08)


def test_provenance_reads_are_four_at_a_time_and_reread_when_the_versions_change(tmp_path):
    seen = run_node(tmp_path, r"""
      const server=makeServer();
      for(let i=0;i<10;i+=1){const id=`lab.p${i}`;server.rows.push(rowOf(id,[1]));server.details[id]=detailOf(id,[hist(1,'custom')])}
      let inflight=0,peak=0;const gates=[];
      const fetchImpl=async(p,o)=>{
        if(/^\/api\/prefabs\/[^/?]+$/.test(p)){inflight+=1;peak=Math.max(peak,inflight);await new Promise(r=>gates.push(r));inflight-=1}
        return server.fetch(p,o);
      };
      const lib=C.createLibrary({client:C.createClient({fetchImpl,setTimer:()=>0,clearTimer:()=>{}})});
      await lib.open();await settle();
      const firstWave=[gates.length,peak];
      const drain=async()=>{while(gates.length){gates.shift()();await settle()}};
      await drain();
      const kinds=[...new Set(lib.visible().map(e=>e.kind))];
      /* Une nouvelle version de lab.p0 : sa provenance est relue, pas celle des autres. */
      server.rows[0].versions=[1,2];server.rows[0].latest_version=2;
      server.details['lab.p0']=detailOf('lab.p0',[hist(1,'custom'),hist(2,'revision',{derived_from:{id:'lab.p0',version:1}})]);
      const again=lib.refresh();await settle();await drain();await again;await settle();
      const reads=id=>server.calls.filter(c=>c.path===`/api/prefabs/${id}`).length;
      out({firstWave,peak,kinds,p0:reads('lab.p0'),p1:reads('lab.p1'),
        badges:lib.visible().find(e=>e.row.id==='lab.p0').badges.map(b=>b.key)});
    """)
    assert seen["firstWave"] == [4, 4] and seen["peak"] == 4
    assert seen["kinds"] == ["custom"]
    assert seen["p0"] == 2 and seen["p1"] == 1
    assert seen["badges"] == ["custom", "revision"]


def test_every_request_has_a_deadline_that_actually_fires(tmp_path):
    seen = run_node(tmp_path, r"""
      const timers=[];
      const fetchImpl=(p,o)=>new Promise((_,ko)=>o.signal.addEventListener('abort',()=>ko(new Error('aborted'))));
      const client=C.createClient({fetchImpl,setTimer:(fn,ms)=>{timers.push({fn,ms});return timers.length},clearTimer:()=>{}});
      const outcome=p=>Promise.race([p.then(()=>'resolved',e=>e.code),new Promise(r=>setTimeout(()=>r('hung'),300))]);
      const read=client.get('/api/prefabs');const write=client.post('/api/prefabs',{});
      for(const t of timers)t.fn();
      out({ms:timers.map(t=>t.ms),read:await outcome(read),write:await outcome(write),title:C.errorView({code:'timeout'}).title});
    """)
    assert seen == {"ms": [15000, 35000], "read": "timeout", "write": "timeout", "title": "Pas de réponse"}


def test_a_failed_provenance_read_is_shown_kept_in_the_filters_and_retried(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      w.server.rows=[rowOf('jarvis.checklist',[1]),rowOf('lab.broken',[1]),rowOf('team.f',[1])];
      w.server.details['jarvis.checklist']=detailOf('jarvis.checklist',[hist(1,'base')]);
      w.server.details['team.f']=detailOf('team.f',[hist(1,'fork',{derived_from:{id:'jarvis.checklist',version:1}})]);
      w.server.details['lab.broken']=detailOf('lab.broken',[hist(1,'custom')]);
      w.server.plan['GET /api/prefabs/lab.broken']={status:500,body:{error:{code:'storage_io',message:'disk'}}};
      await w.act(w.lib.open());
      const broken=()=>w.lib.entries().find(e=>e.row.id==='lab.broken');
      const ids=kind=>{w.lib.setKind(kind);return w.lib.visible().map(e=>e.row.id)};
      const failed={badges:broken().badges.map(b=>[b.key,b.label,b.tone]),kind:broken().kind,fork:ids('fork'),custom:ids('custom'),
        base:ids('base'),counts:w.lib.counts(),waiting:w.lib.waiting()};
      w.lib.setKind('all');
      w.lib.select('lab.broken');await w.act(Promise.resolve());
      const shown=w.lib.shown();
      delete w.server.plan['GET /api/prefabs/lab.broken'];
      w.lib.retryDetail();await w.act(Promise.resolve());
      out({failed,shown:[shown.status,shown.error&&shown.error.code],after:broken().kind});
    """)
    failed = seen["failed"]
    # Jamais « Provenance… » pour toujours : l'échec se dit, la ligne reste sous Fork et Custom.
    assert failed["badges"] == [["unknown", "Provenance inconnue", "bad"]] and failed["kind"] == "unknown"
    assert failed["fork"] == ["lab.broken", "team.f"] and failed["custom"] == ["lab.broken"]
    assert failed["base"] == ["jarvis.checklist"] and failed["waiting"] is False
    assert failed["counts"] == {"all": 3, "base": 1, "base_edited": 0, "fork": 2, "custom": 1}
    assert seen["shown"] == ["error", "storage_io"] and seen["after"] == "custom"


def test_a_fork_outcome_survives_a_selection_change_and_never_yanks_the_selection(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      const M={id:'jarvis.checklist',title:'Checklist',family:'window',inputs:{props:{type:'object',properties:{}}},sample:{props:{},data:{}},events:{}};
      w.server.rows=[rowOf('jarvis.checklist',[1]),rowOf('lab.other',[1])];
      w.server.details['jarvis.checklist']=detailOf('jarvis.checklist',[hist(1,'base')],M);
      w.server.details['lab.other']=detailOf('lab.other',[hist(1,'custom')]);
      w.server.sources['jarvis.checklist']={template:'<p></p>',style:'',behavior:''};
      const real=w.server.fetch;let release=null;
      w.server.fetch=async(p,o)=>{if(o&&o.method==='POST'&&p==='/api/prefabs')await new Promise(r=>{release=r});return real(p,o)};
      await w.act(w.lib.open());w.lib.select('jarvis.checklist');await w.act(Promise.resolve());
      /* 1. Refus pendant que l'utilisateur regarde un autre prefab. */
      w.lib.openFork();
      w.server.plan['POST /api/prefabs']={status:400,body:{error:{code:'invalid_definition',
        message:'team.taken already exists: a revision derives from its own previous version, not from another id'}}};
      const p1=w.lib.submitFork({id:'team.taken',title:'t',description:'',defaults:{}});await settle();
      w.lib.select('lab.other');await settle();
      const during=[C.statusView(w.lib).label,w.lib.waiting(),w.S.fork];
      release();await w.act(p1);
      const refused=w.S.notice&&[w.S.notice.tone,w.S.notice.title,w.S.notice.code];
      w.lib.select('jarvis.checklist');await settle();
      const refusedKept=!!w.S.notice&&w.S.notice.tone==='bad';
      w.lib.dismissNotice();
      /* 2. Publié pendant que l'utilisateur est ailleurs : la sélection ne bouge pas. */
      delete w.server.plan['POST /api/prefabs'];
      w.lib.openFork();
      const p2=w.lib.submitFork({id:'team.fresh',title:'Fresh',description:'',defaults:{}});await settle();
      w.lib.select('lab.other');await settle();
      release();await w.act(p2);
      const away={selected:w.S.selected,notice:w.S.notice&&[w.S.notice.tone,w.S.notice.title,w.S.notice.goto],
        listed:w.lib.entries().some(e=>e.row.id==='team.fresh')};
      w.lib.select('jarvis.checklist');await settle();
      const awayKept=!!w.S.notice;
      w.lib.dismissNotice();
      /* 3. Publié depuis le formulaire : le fork est choisi ; l'avis part au changement de prefab. */
      w.lib.openFork();
      const p3=w.lib.submitFork({id:'team.onform',title:'On',description:'',defaults:{}});await settle();
      release();await w.act(p3);
      const onForm=[w.S.selected,w.S.notice&&w.S.notice.title];
      w.lib.select('lab.other');await settle();
      out({during,refused,refusedKept,away,awayKept,onForm,cleared:w.S.notice});
    """)
    assert seen["during"] == ["Publication…", True, None]
    assert seen["refused"][0] == "bad" and "Identifiant déjà pris" in seen["refused"][1] and seen["refused"][2] == "id_taken"
    assert seen["refusedKept"] is True
    assert seen["away"] == {"selected": "lab.other", "notice": ["ok", "Fork publié : team.fresh v1", "team.fresh"], "listed": True}
    assert seen["awayKept"] is True
    assert seen["onForm"] == ["team.onform", "Fork publié : team.onform v1"]
    assert seen["cleared"] is None


def test_refusals_are_worded_in_french_and_a_taken_id_is_named_before_and_by_core(tmp_path):
    seen = run_node(tmp_path, r"""
      const base=C.errorView({code:'base_protected',status:403,message:'jarvis.x is a base prefab: it changes only through the '
        +'base-edit gate (prefab_edit_base) with the explicit request of the user; save it under a new custom id instead'});
      const taken=C.errorView({code:'invalid_definition',status:400,message:'team.a already exists: a revision derives from its own previous version, not from another id'});
      const other=C.errorView({code:'invalid_definition',status:400,message:'manifest.title too long',errors:['manifest.title too long']});
      const w=world();
      const M={id:'lab.timer',title:'Timer',family:'window',inputs:{props:{type:'object',properties:{}}},sample:{props:{},data:{}},events:{}};
      w.server.rows=[rowOf('lab.timer',[1]),rowOf('lab.other',[1])];
      w.server.details['lab.timer']=detailOf('lab.timer',[hist(1,'custom')],M);
      w.server.details['lab.other']=detailOf('lab.other',[hist(1,'custom')]);
      w.server.sources['lab.timer']={template:'<p></p>',style:'',behavior:''};
      await w.act(w.lib.open());w.lib.select('lab.timer');await w.act(Promise.resolve());
      w.lib.openFork();
      const local=[];
      for(const id of ['lab.timer','lab.other']){
        await w.act(w.lib.submitFork({id,title:'x',description:'',defaults:{}}));
        local.push([w.S.fork.status,w.S.fork.error.code,C.errorView(w.S.fork.error).title]);
      }
      out({base:[base.title,base.message,base.code],taken:[taken.code,taken.coreCode,taken.title,taken.message],
        other:[other.code,other.message,other.errors],local,posts:w.server.calls.filter(c=>c.method==='POST').length});
    """)
    title, message, code = seen["base"]
    assert code == "base_protected" and title == "Identifiant réservé aux prefabs de base"
    # Pas le texte anglais de Core, qui parle d'un outil du cerveau.
    assert "prefab_edit_base" not in message and "base prefab" not in message and "jarvis." in message
    assert seen["taken"][:3] == ["id_taken", "invalid_definition", "Identifiant déjà pris"]
    assert "already exists" not in seen["taken"][3]
    assert seen["other"] == ["invalid_definition", "manifest.title too long", ["manifest.title too long"]]
    # L'id de la source (qui ferait une RÉVISION) et un id listé sont refusés avant le réseau.
    assert seen["local"] == [["error", "id_taken", "Identifiant déjà pris"]] * 2 and seen["posts"] == 0


def test_chain_links_tell_a_history_not_yet_read_from_an_absent_prefab(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      w.server.rows=[rowOf('team.c',[1])];
      w.server.details['team.c']=detailOf('team.c',[hist(1,'fork',{derived_from:{id:'team.b',version:2}})]);
      w.server.details['team.b']=detailOf('team.b',[hist(1,'fork',{derived_from:{id:'lab.gone',version:1}}),
        hist(2,'revision',{derived_from:{id:'team.b',version:1}})]);
      await w.act(w.lib.open());w.lib.select('team.c');await settle();
      const states=()=>w.lib.chain('team.c').map(l=>[l.id,l.state]);
      const first=states();await settle();
      const second=states();await settle();
      out({first,second,third:states()});
    """)
    assert seen["first"] == [["team.b", "pending"], ["team.c", "known"]]
    assert seen["second"] == [["lab.gone", "pending"], ["team.b", "known"], ["team.c", "known"]]
    assert seen["third"] == [["lab.gone", "absent"], ["team.b", "known"], ["team.c", "known"]]


# Le bloc navigateur réel, dans le faux DOM de `tests/fakes/prefab_js` (étendu ici :
# `dataset`, sélecteurs composés, `closest`, bulles), avec le VRAI hôte des cadres.
DOM_EXT = r"""
const kebab=k=>k.replace(/[A-Z]/g,c=>'-'+c.toLowerCase());
Object.defineProperty(FakeEl.prototype,'dataset',{get(){const el=this;return new Proxy({},{
  get:(_,k)=>{if(typeof k!=='string')return undefined;const v=el.getAttribute('data-'+kebab(k));return v===null?undefined:v},
  set:(_,k,v)=>{el.setAttribute('data-'+kebab(k),v);return true}})}});
function parseSel(sel){
  const parts=[];let rest=sel.trim();
  const re=/^(?:([a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:=(?:"([^"]*)"|([^\]]*)))?\]|:not\(((?:[^()]|\([^()]*\))*)\))/;
  while(rest){const m=re.exec(rest);if(!m)throw new Error('unsupported selector '+sel);parts.push(m);rest=rest.slice(m[0].length)}
  return el=>parts.every(m=>m[1]?el.tagName===m[1].toUpperCase():m[2]?el.id===m[2]:m[3]?el.classList.contains(m[3])
    :m[4]?(m[5]!==undefined||m[6]!==undefined?el.getAttribute(m[4])===(m[5]!==undefined?m[5]:m[6]):el.hasAttribute(m[4]))
    :!matcher(m[7])(el));
}
function matcher(sel){const alts=sel.split(',').map(parseSel);return el=>alts.some(f=>f(el))}
FakeEl.prototype.querySelectorAll=function(sel){const f=matcher(sel);return this.descendants().filter(f)};
FakeEl.prototype.querySelector=function(sel){return this.querySelectorAll(sel)[0]||null};
FakeEl.prototype.closest=function(sel){const f=matcher(sel);for(let n=this;n&&n.nodeType===1;n=n.parentNode)if(f(n))return n;return null};
FakeEl.prototype.select=function(){};FakeEl.prototype.scrollIntoView=function(){};
FakeEl.prototype.fire=function(type,fields){
  const ev=Object.assign({type,target:this,defaultPrevented:false,stopped:false,preventDefault(){this.defaultPrevented=true},
    stopPropagation(){this.stopped=true}},fields||{});
  for(let n=this;n&&!ev.stopped;n=n.parentNode)(n.listeners&&n.listeners[type]||[]).slice().forEach(fn=>fn(ev));
  return ev;
};
FakeEl.prototype.click=function(){return this.disabled?null:this.fire('click')};
FakeDocument.prototype.createElementNS=function(ns,tag){return this.createElement(tag)};
const doc=new FakeDocument(),win=new FakeWindow();
const lines=[];console.info=(...a)=>lines.push(a.join(' '));console.warn=console.info;
console.error=(...a)=>{lines.push(a.join(' '));process.stderr.write(a.map(x=>x&&x.stack||x).join(' ')+'\n')};
const rafq=[];globalThis.requestAnimationFrame=fn=>{rafq.push(fn);return rafq.length};
globalThis.setInterval=()=>0;globalThis.clearInterval=()=>{};
globalThis.window=win;globalThis.document=doc;win.JarvisPrefabHost=H;
const bundle=D.bundles['test.counter@1'];
const hist=(version,origin,extra)=>Object.assign({version,root:'data',status:'ok',origin,derived_from:null,
  created_by:{actor:origin==='base'?'system':'user'},base_edit:null,published_at:'2026-10-03T12:00:00Z',fingerprint:'f'},extra||{});
const RTL='اجعل الجدول';
const manifestOf=(id,extra)=>Object.assign(JSON.parse(JSON.stringify(D.manifest)),{id},extra||{});
const details={
  'test.counter':{id:'test.counter',version:1,latest_version:1,class:'custom',manifest:manifestOf('test.counter'),history:[hist(1,'custom')]},
  'jarvis.demo':{id:'jarvis.demo',version:2,latest_version:2,class:'base',manifest:manifestOf('jarvis.demo',{title:RTL,description:'x'.repeat(300)}),
    history:[hist(1,'base'),hist(2,'base_edit',{created_by:{actor:'brain'},derived_from:{id:'jarvis.demo',version:1},
      base_edit:{confirmed_by_user:true,user_request:RTL,witness:'conversation_event:cev-0123456789abcdef'}})]},
};
const rows=[{id:'test.counter',latest_version:1,versions:[1],title:'Counter',family:'window',class:'custom'},
  {id:'jarvis.demo',latest_version:2,versions:[1,2],title:RTL,family:'window',class:'base',base_edited:true}];
const calls=[];
win.fetch=async(path,options)=>{
  const method=(options&&options.method)||'GET';calls.push(`${method} ${path}`);
  const reply=(status,payload)=>({ok:status<400,status,text:async()=>JSON.stringify(payload),json:async()=>JSON.parse(JSON.stringify(payload))});
  const bare=path.split('?')[0];
  if(method==='GET'&&bare==='/api/prefabs')return reply(200,{prefabs:rows});
  let m=bare.match(/^\/api\/prefabs\/([^/]+)\/1\/bundle$/);
  if(m)return reply(200,bundle);
  m=bare.match(/^\/api\/prefabs\/([^/]+)(?:\/(\d+))?$/);
  if(method==='GET'&&m&&details[m[1]])return reply(200,details[m[1]]);
  return reply(404,{error:{code:'not_found',message:path}});
};
const mk=(tag,id,parent)=>{const n=doc.createElement(tag);if(id)n.setAttribute('id',id);parent.appendChild(n);return n};
const page=mk('main','page',doc.body);const toasts=mk('div',null,doc.body);toasts.className='toasts';
const openButton=mk('button','openPrefabs',page);
const root=mk('section','prefabLibrary',doc.body);root.hidden=true;
for(const [tag,id] of [['button','pfbClose'],['button','pfbRefresh'],['div','pfbStatus'],['strong','pfbStatusLabel'],['span','pfbStatusDetail'],
  ['input','pfbSearch'],['select','pfbFamily'],['div','pfbKinds'],['p','pfbCount'],['ul','pfbList'],['div','pfbListState'],['div','pfbDetail'],['div','pfbAnnounce']])mk(tag,id,root);
require(LIB_PATH);
const run=async()=>{for(let i=0;i<25;i+=1){await flush(3);rafq.splice(0).forEach(f=>f(0))}};
const key=k=>doc.dispatch('keydown',{key:k,target:doc.activeElement||doc.body,stopPropagation(){}});
"""


async def test_the_view_previews_locally_traps_the_page_and_escape_closes_the_form_first(tmp_path):
    from tests.fakes.prefab_js import catalogue_bundles, run_node as run_dom

    bundles = await catalogue_bundles(tmp_path, "test.counter")
    manifest = json.loads((ROOT / "tests" / "fixtures" / "prefabs" / "test.counter" / "1" / "manifest.json").read_text(encoding="utf-8"))
    seen = run_dom(tmp_path, f"const LIB_PATH={json.dumps(str(MODULE))};" + DOM_EXT + r"""
      openButton.click();await run();
      const inert={page:page.inert===true,toasts:!!toasts.inert,open:!root.hidden};
      const tabs=()=>root.querySelectorAll('.pfb-row').map(r=>[r.dataset.id,r.getAttribute('tabindex')]);
      const before=tabs();
      root.querySelector('[data-id="test.counter"]').click();await run();
      const frame=root.querySelector('iframe');
      win.dispatch({source:frame.contentWindow,origin:'null',data:{jv:1,type:'ready'}});
      const init=frame.contentWindow.posted[0].message;
      win.dispatch({source:frame.contentWindow,origin:'null',data:{jv:1,type:'event',name:'incremented',payload:{count:4}}});
      await run();
      const preview={mode:init.instance.mode,log:window.JarvisPrefabLibrary.state.previewLog.map(e=>e.name),
        posts:calls.filter(c=>c.startsWith('POST')||c.includes('/events')),hint:!!root.querySelector('.pfb-stagehint')};
      const after=tabs();
      root.querySelector('#pfbForkOpen').click();await run();
      const form=root.querySelector('#pfbForkForm');
      const idField=form.querySelector('[name="id"]');
      idField.value='jarvis.mine';idField.fire('input');
      const fork={warn:form.querySelector('.pfb-fieldwarn').textContent,heading:form.querySelector('h4').querySelector('bdi').textContent,
        titleDir:form.querySelector('[name="title"]').getAttribute('dir')};
      idField.value='test.counter';idField.fire('input');
      fork.taken=form.querySelector('.pfb-fieldwarn').textContent;
      idField.focus();key('Escape');await run();
      const firstEscape={form:!!root.querySelector('#pfbForkForm'),open:!root.hidden,focus:doc.activeElement&&doc.activeElement.id};
      key('Escape');await run();
      const secondEscape={open:!root.hidden,pageInert:!!page.inert,focus:doc.activeElement&&doc.activeElement.id};
      openButton.click();await run();
      root.querySelector('[data-id="jarvis.demo"]').click();await run();
      const quote=root.querySelector('.pfb-quote');
      const witness=quote.querySelector('.pfb-witness');
      const base={title:root.querySelector('#pfbDetailTitle').getAttribute('dir'),desc:root.querySelector('.pfb-desc').getAttribute('dir'),
        request:quote.querySelector('blockquote').querySelector('bdi').textContent,witnessTag:witness.tagName,
        witnessSummary:witness.querySelector('summary').textContent,witnessCode:witness.querySelector('code').textContent,
        name:root.querySelector('[data-id="jarvis.demo"]').querySelector('.pfb-name').getAttribute('dir'),rtl:RTL};
      return {inert,before,after,preview,fork,firstEscape,secondEscape,base};
    """, {"bundles": bundles, "manifest": manifest})
    assert seen["inert"] == {"page": True, "toasts": False, "open": True}
    # Un seul arrêt de tabulation dans la liste : la première ligne, puis la ligne choisie.
    assert seen["before"] == [["jarvis.demo", "0"], ["test.counter", "-1"]]
    assert seen["after"] == [["jarvis.demo", "-1"], ["test.counter", "0"]]
    # L'aperçu : le cadre sait qu'il est un aperçu, son événement reste dans le journal local, rien n'est posté.
    assert seen["preview"] == {"mode": "preview", "log": ["incremented"], "posts": [], "hint": True}
    assert "« jarvis. »" in seen["fork"]["warn"] and seen["fork"]["heading"] == "Counter"
    assert seen["fork"]["titleDir"] == "auto" and "déjà pris" in seen["fork"]["taken"]
    # Échap : le formulaire d'abord (la vue reste), puis la vue ; le focus revient à PFB, la page n'est plus inerte.
    assert seen["firstEscape"] == {"form": False, "open": True, "focus": "pfbForkOpen"}
    assert seen["secondEscape"] == {"open": False, "pageInert": False, "focus": "openPrefabs"}
    base = seen["base"]
    assert base["title"] == base["desc"] == base["name"] == "auto"
    assert base["request"] == base["rtl"]
    # Le témoin brut est replié sous un résumé, pas affiché sous la citation.
    assert base["witnessTag"] == "DETAILS" and base["witnessSummary"] == "Témoin"
    assert base["witnessCode"] == "conversation_event:cev-0123456789abcdef"


def test_long_words_wrap_headings_keep_their_case_and_names_are_distinct():
    from jarvis.protocol import prefab_routes
    from jarvis.runtime import prefab_relay

    html = PAGE.read_text(encoding="utf-8")
    css = html[html.index("/* ---------- Bibliothèque des prefabs (plein écran)"): html.index("</style>")]
    rules = dict(re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S)))
    rule = lambda selector: next(body for sel, body in rules.items() if sel.strip() == selector)  # noqa: E731
    for selector in (".pfb-desc", ".pfb-titleline h3", ".pfb-tdesc", ".pfb-evsum", ".pfb-quote blockquote p", ".pfb-notice>div",
                     ".pfb-error", ".pfb-empty,.pfb-none", ".pfb-placed", ".pfb-hint", ".pfb-form h4", ".pfb-defdesc"):
        assert "overflow-wrap:anywhere" in rule(selector), selector
    # Capitales visuelles sans changer le texte : Chrome reporte `text-transform` dans le nom accessible.
    for selector in (".pfb-sechead h4,.pfb-sect>h4", ".pfb-loghead h5", ".pfb-fields .pfb-field>label", ".pfb-defs legend"):
        assert "uppercase" not in rule(selector) and "all-small-caps" in rule(selector), selector
    view = html[html.index('<section class="pfb"'): html.index("</section>", html.index('<section class="pfb"'))]
    assert re.findall(r'aria-label="([^"]+)"', view).count("Bibliothèque des prefabs") == 1
    # Une seule borne de corps : celle de Core.
    assert prefab_relay.MAX_DEFINITION_BODY_BYTES == prefab_routes.MAX_DEFINITION_BODY_BYTES
    relay = (RUNTIME / "prefab_relay.py").read_text(encoding="utf-8")
    assert "from jarvis.protocol.prefab_routes import MAX_DEFINITION_BODY_BYTES" in relay

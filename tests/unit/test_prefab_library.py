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
  const client=C.createClient({fetchImpl:server.fetch,setTimer:()=>0,clearTimer:()=>{}});
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
        [["base", "Base", "base"], ["base_edited", "Modifiée à votre demande", "edited"]],
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
    for attribute in ('role="dialog"', 'aria-modal="true"', 'aria-labelledby="pfbTitle"', 'aria-describedby="pfbHelp"', " hidden>"):
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

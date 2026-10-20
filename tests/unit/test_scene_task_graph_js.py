"""Graphe des tâches, logique pure exécutée par node (jarvis-organic-agent-orchestration, Slice 09).

Modules servis tels quels : `control_center_role_identity.js` (identité des rôles, grammaire des relations),
`control_center_scene_layout.js` (`roleOf`, `laneEdges`, `relationMarks`, `relationMarkLabel`, `viewModel`),
`control_center_scene_roles.js` (cache des missions) et `control_center_relation_board.js` (modèle du tableau).
Contrat : `docs/scene-model.md` › *Interface: roles and relations*. Le rendu navigateur est épinglé par
`test_scene_task_graph_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

from jarvis.domain import subagent_roles, work_methods
from jarvis.domain.agent_relations import (
    AgentRelationKind, ParticipantPosition, RelationMessageType, RelationOutcome,
)
from jarvis.domain.work_state import WorkStatus
from jarvis.runtime.control_center import ControlCenter

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"


def _node(source: str, data: object = None) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "t.cjs"
        script.write_text(
            "const R=" + json.dumps(str(RUNTIME)) + ";const I=require(R+'/control_center_role_identity.js');"
            "const L=require(R+'/control_center_scene_layout.js');const S=require(R+'/control_center_scene_roles.js');"
            "const B=require(R+'/control_center_relation_board.js');const DATA=" + json.dumps(data) + ";\n"
            "(async()=>{const out=await (async()=>{" + source + "})();process.stdout.write(JSON.stringify(out===undefined?null:out))})()"
            ".catch(e=>{process.stderr.write(String(e&&e.stack||e));process.exit(1)});",
            encoding="utf-8")
        done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _roles_payload() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        return ControlCenter(runtime_root=Path(tmp), project_root=Path(tmp))._subagent_roles_payload({})


# ------------------------------------------------------------------ une seule source d'identité


def test_the_shared_tables_match_the_python_contracts():
    out = _node("return {kinds:Object.keys(I.RELATION_KINDS),labels:Object.fromEntries(Object.entries(I.RELATION_KINDS).map(([k,v])=>[k,v.label])),"
                "outcomes:Object.keys(I.OUTCOME_LABELS),types:Object.keys(I.MESSAGE_TYPE_LABELS),positions:Object.keys(I.POSITION_LABELS),"
                "statuses:Object.keys(I.WORK_STATUS_LABELS),icons:Object.keys(I.ICONS),"
                "directed:Object.entries(I.RELATION_KINDS).filter(([,v])=>v.directed).map(([k])=>k),"
                "layoutKinds:[...L.AGENT_RELATION_KINDS]}")
    assert set(out["kinds"]) == {kind.value for kind in AgentRelationKind} == set(out["layoutKinds"])
    # Les libellés de repli sont ceux du registre (`work_methods.RELATION_LABELS`), avec une majuscule.
    assert out["labels"] == {k: v[0].upper() + v[1:] for k, v in work_methods.RELATION_LABELS.items()}
    assert set(out["outcomes"]) == {o.value for o in RelationOutcome}
    assert set(out["types"]) == {t.value for t in RelationMessageType}
    assert set(out["positions"]) == {p.value for p in ParticipantPosition}
    assert set(out["statuses"]) == {s.value for s in WorkStatus}
    assert {role.visual.icon for role in subagent_roles.ROLES} <= set(out["icons"])
    assert set(out["directed"]) == {"delegation", "qa", "handoff"}


def test_the_settings_tab_draws_the_same_pictograms_as_the_graph():
    source = (RUNTIME / "control_center_subagents_settings.js").read_text(encoding="utf-8")
    assert "<circle cx=\"12\" cy=\"8\" r=\"3.8\"/>" not in source, "pictograms are not copied into the settings tab"
    assert "JarvisRoleIdentity" in source and "iconSvg(name,'sar-glyph')" in source


def test_the_registry_reads_the_served_payload_once_and_never_guesses_an_unknown_role():
    out = _node("""
let calls=0;const reg=I.createRoleRegistry({fetchJson:async p=>{calls++;return DATA}});
const before=reg.identity('coder');
await Promise.all([reg.load(),reg.load()]);await reg.load();
return {calls,before,coder:reg.identity('coder'),alias:reg.identity('reviewer'),ghost:reg.identity('ghost-role'),
  label:reg.relationLabel('communication'),accent:reg.accentOf('not-a-token'),qa:reg.identity('qa')};""", _roles_payload())
    assert out["calls"] == 1
    assert out["before"]["known"] is False and out["before"]["pending"] is True
    assert out["coder"] == {"id": "coder", "name": "Développement", "badge": "DEV", "icon": "code", "accent": "amber",
                            "known": True, "pending": False}
    assert out["alias"]["id"] == "qa"
    assert out["ghost"] == {"id": "ghost-role", "name": "ghost-role", "badge": "GHO", "icon": "unknown", "accent": "slate",
                            "known": False, "pending": False}
    assert out["label"] == "Échange entre agents" and out["accent"] == "slate" and out["qa"]["badge"] == "QA"


def test_a_failed_registry_read_is_logged_and_retried_only_after_its_delay():
    out = _node("""
let t=0,calls=0;const logs=[];
const reg=I.createRoleRegistry({now:()=>t,log:(l,c)=>logs.push([l,c]),fetchJson:async()=>{calls++;const e=new Error('x');e.code='prompt_overrides_invalid';throw e}});
await reg.load();await reg.load();t=31000;await reg.load();
return {calls,logs,phase:reg.phase()};""")
    assert out["calls"] == 2 and out["phase"] == "failed"
    assert out["logs"] == [["error", "prompt_overrides_invalid"], ["error", "prompt_overrides_invalid"]]


# ------------------------------------------------------------------ rôles et relations dans le modèle de vue


SCENE = """
const star=(id,x,y,ref)=>({schema_version:1,object_id:id,kind:'agent',category:'agent',exec_state:'running',representation:'point',
  geometry:{x,y,w:6,h:6},layer:100,order:0,visibility:'visible',disposition:'active',constraints:{placed_by:'user'},origin:'runtime',
  work_ref:{source:'claude_code',external_id:'t_'+id},role_ref:ref,payload:{title:'Titre '+id,summary:'',items:[]}});
const rel=(id,kind,a,b,ref)=>({relation_id:id,kind,from_id:a,to_id:b,layer:0,...(ref?{ref}:{})});
const ref=(id,state,outcome)=>({relation_id:id,mission_id:'m1',state,...(outcome?{outcome}:{})});
const objects=[star('a',-60,0,{role_id:'research-lead',instance_id:'ia',mission_id:'m1',mission_owner:true}),
  star('b',60,0,{role_id:'coder',instance_id:'ib',mission_id:'m1',mission_owner:false}),
  star('c',0,50,{role_id:'coder',mission_owner:false}),star('d',0,-50,{role_id:'Bad Role!'}),
  {...star('w',20,20,null),kind:'job'}];
const relations=[rel('parent_of!a~b','parent_of','a','b'),rel('delegation!rd','delegation','a','b',ref('rd','open')),
  rel('qa!rq','qa','a','b',ref('rq','closed','findings')),
  rel('adversary!ra!ib~ic','adversary','b','c',ref('ra','open')),rel('adversary!ra!ib~id','adversary','b','d',ref('ra','open')),
  rel('adversary!ra!ic~id','adversary','c','d',ref('ra','open')),
  rel('handoff!rh','handoff','a','ghost',ref('rh','closed','transferred'))];
const state={objects:new Map(objects.map(o=>[o.object_id,o])),relations:new Map(relations.map(r=>[r.relation_id,r]))};
"""


def test_the_view_model_reads_role_ref_and_relation_refs_never_titles():
    out = _node(SCENE + """
const placements=new Map(objects.map(o=>[o.object_id,o.geometry]));
const ident=id=>({name:id==='coder'?'Développement':'Direction de recherche',badge:id==='coder'?'DEV':'DIR',icon:'code',accent:'amber',known:true});
const missions=id=>id==='m1'?{origin:'general',liveUnknown:true}:null;
const vm=L.viewModel(state,{placements},L.viewport(1440,900),{roleIdentity:ident,missionInfo:missions});
const n=id=>vm.nodes.find(x=>x.id===id);
return {a:n('a').role,b:n('b').role,c:n('c').role,d:n('d').role,w:n('w').role,label:n('a').label,
  edges:vm.edges.map(e=>({id:e.id,kind:e.kind,rel:e.relationId,state:e.state,outcome:e.outcome,lane:e.lane}))};""")
    assert out["a"]["owner"] is True and out["a"]["origin"] == "général" and out["a"]["liveUnknown"] is True
    assert out["b"]["owner"] is False and out["b"]["origin"] == "" and out["b"]["badge"] == "DEV"
    assert out["b"]["liveUnknown"] is False                  # l'état inconnu de la mission : chez son responsable
    assert out["c"]["id"] == "coder" and out["d"] is None and out["w"] is None   # id hors forme, job : pas de rôle
    assert "rôle Direction de recherche" in out["label"] and "responsable de la mission" in out["label"]
    assert "origine général" in out["label"] and "mission : état inconnu" in out["label"]
    edges = {e["id"]: e for e in out["edges"]}
    assert "handoff!rh" not in edges                          # D15 : l'étoile « ghost » n'existe pas
    assert edges["qa!rq"]["rel"] == "rq" and edges["qa!rq"]["state"] == "closed" and edges["qa!rq"]["outcome"] == "findings"
    assert edges["parent_of!a~b"]["rel"] == "" and edges["parent_of!a~b"]["state"] == ""
    # Trois fils du même couple : trois voies, la filiation au milieu de l'ordre fixe.
    assert sorted(edges[k]["lane"] for k in ("parent_of!a~b", "delegation!rd", "qa!rq")) == [-7, 0, 7]
    assert edges["adversary!ra!ib~ic"]["lane"] == 0


def test_relation_marks_group_n_party_links_and_spread_on_a_shared_pair():
    out = _node("""
const e=(id,kind,rel,from,to,x1,y1,x2,y2,turn)=>({id,kind,relationId:rel,missionId:'m1',state:'open',outcome:'',from,to,x1,y1,x2,y2,fromTurns:turn,toTurns:turn});
const edges=[e('d','delegation','rd','a','b',0,0,200,0,true),e('q','qa','rq','a','b',0,7,200,7,true),
  e('x1','adversary','ra','b','c',200,0,100,150,true),e('x2','adversary','ra','b','d',200,0,300,150,true),e('x3','adversary','ra','c','d',100,150,300,150,true),
  e('m','communication','rc','a','e',0,0,0,300,false),{...e('mm','communication','rm','a','f',0,0,100,0,false),toTurns:true},
  {id:'p',kind:'parent_of',relationId:'',from:'a',to:'b',x1:0,y1:0,x2:200,y2:0}];
const marks=L.relationMarks(edges,{size:24,obstacles:[]});
const by=Object.fromEntries(marks.map(m=>[m.id,m]));
const moved=L.relationMarkPoint(by.rc,[{x:0,y:0},{x:0,y:100}]);
return {ids:marks.map(m=>m.id).sort(),adv:{members:by.ra.members,x:by.ra.x,y:by.ra.y,directed:by.ra.directed},
  d:by.rd,q:by.rq,turns:{rd:by.rd.turns,rc:by.rc.turns,rm:by.rm.mixed},moved};""")
    assert out["ids"] == ["ra", "rc", "rd", "rm", "rq"]                  # la filiation n'a pas de pastille
    assert out["adv"]["members"] == ["b", "c", "d"] and out["adv"]["directed"] is False
    assert (out["adv"]["x"], out["adv"]["y"]) == (200.0, 100.0)          # barycentre des trois producteurs
    assert out["d"]["directed"] and out["d"]["from"] == "a" and out["d"]["to"] == "b"
    assert abs(out["d"]["x"] - out["q"]["x"]) >= 24                      # même couple : écartées le long du fil
    assert out["turns"] == {"rd": True, "rc": False, "rm": True}
    assert out["moved"] == {"x": 0, "y": 50}


def test_marks_never_stack_and_step_off_the_role_pills():
    out = _node("""
const e=(id,rel,x2)=>({id,kind:'communication',relationId:rel,state:'open',from:'a',to:id,x1:0,y1:0,x2,y2:0,fromTurns:false,toTurns:false});
const crowded=L.relationMarks([e('b','r1',80),e('c','r2',80.5),e('d','r3',81)],{size:18,obstacles:[]});
const gap=Math.min(...crowded.flatMap((m,i)=>crowded.slice(i+1).map(n=>Math.hypot(m.x-n.x,m.y-n.y))));
const pill=L.relationMarks([e('z','r9',200)],{size:24,obstacles:[{left:90,top:-8,width:30,height:16}]})[0];
return {gap,pill:{x:pill.x,y:pill.y}};""")
    assert out["gap"] >= 20
    assert out["pill"]["y"] == 0 and not (90 - 14 < out["pill"]["x"] < 120 + 14), out["pill"]


def test_mark_labels_say_who_does_what_in_words():
    out = _node("""
const nodes=new Map([['a',{title:'Plan',role:{name:'Direction de recherche'}}],['b',{title:'Code',role:{name:'Développement'}}],
  ['c',{title:'Autre',role:null}]]);
const words=S.markWords(k=>({qa:'Contrôle qualité',adversary:'Confrontation'})[k]||k);
return {qa:L.relationMarkLabel({kind:'qa',directed:true,from:'a',to:'b',members:['a','b'],state:'closed',outcome:'approved'},nodes,words),
  adv:L.relationMarkLabel({kind:'adversary',directed:false,members:['a','b','c'],state:'open',outcome:''},nodes,words),
  comm:L.relationMarkLabel({kind:'communication',directed:false,members:['a','b'],state:'open',outcome:''},nodes,words)};""")
    assert out["qa"] == ("Contrôle qualité : Direction de recherche « Plan » relit Développement « Code » · close, approuvé"
                         " · ouvrir le détail et les messages")
    assert out["adv"].startswith("Confrontation : entre Direction de recherche « Plan », Développement « Code », « Autre »")
    assert out["comm"].endswith("ouvrir le tableau des messages") and "échange avec" in out["comm"]


# ------------------------------------------------------------------ missions lues


def test_the_mission_cache_reads_a_tree_once_refreshes_open_missions_and_logs_a_failure_once():
    out = _node("""
let t=0,calls=[],fail=false,changes=0;const logs=[];
const tree={missions:[{mission_id:'m1',origin_kind:'code',status:'open',live_unknown:false,objective:'O'},
  {mission_id:'m2',origin_kind:'general',status:'completed',live_unknown:false,objective:'S'}]};
const cache=S.createMissionCache({now:()=>t,log:(l,c)=>logs.push([l,c]),onChange:()=>changes++,setInterval:()=>1,clearInterval:()=>{},
  fetchJson:async p=>{calls.push(p);if(fail){const e=new Error('down');e.code='mission_history_unavailable';throw e}return tree}});
const first=cache.info('m1');await new Promise(r=>setTimeout(r,0));await new Promise(r=>setTimeout(r,0));
const m1=cache.info('m1'),m2=cache.info('m2');
t=16000;tree.missions[0].live_unknown=true;cache.info('m1');await new Promise(r=>setTimeout(r,0));await new Promise(r=>setTimeout(r,0));
const later=cache.info('m1');
fail=true;cache.info('m3');await new Promise(r=>setTimeout(r,5));cache.info('m3');await new Promise(r=>setTimeout(r,5));
t=50000;cache.info('m3');await new Promise(r=>setTimeout(r,5));
return {first,m1,m2,later,calls,changes,logs};""")
    assert out["first"] is None and out["m1"]["origin"] == "code" and out["m2"]["status"] == "completed"
    assert out["later"]["liveUnknown"] is True and out["changes"] == 2
    assert out["calls"].count("/api/missions/m1") == 2 and "/api/missions/m2" not in out["calls"]
    assert out["calls"].count("/api/missions/m3") == 2                 # relue 30 s après l'échec, pas avant
    assert out["logs"] == [["warn", "scene.mission_unreadable"]]


# ------------------------------------------------------------------ modèle du tableau


def test_the_board_model_keeps_deliberate_messages_in_order_and_says_unknown_missions_unknown():
    out = _node("""
const body={ok:true,relation:{relation_id:'r',kind:'communication',mission_id:'m',participants:[{instance_id:'i1',position:'member'},{bad:1}],
  purpose:'P',status:'open',outcome:null,handoff:null},messages:[{seq:2,message_id:'b',author_instance_id:'i1',type:'decision',text:'<b>x</b>'},
  {seq:1,message_id:'a',author_instance_id:'i1',type:'message',text:'y'},{seq:'3'}],participants:[{instance_id:'i1',role_id:'coder',label:'L',work_status:null}]};
const read=B.normalizeRead(body);
let invalid=null;try{B.normalizeRead({relation:{}})}catch(e){invalid=e.code}
const merged=B.mergeMessages(read.messages,[{seq:3,text:'z'},{seq:1,text:'y2'}]);
const mission=B.normalizeMission({missions:[{mission_id:'m',objective:'O',origin_kind:'code',status:'open',live_unknown:true,owner_instance_id:'succ'},
  {mission_id:'s',owner_instance_id:'subowner',status:'open'}],instances:[{instance_id:'pred',mission_owner:true}]},'m');
return {participants:read.relation.participants,seqs:read.messages.map(m=>m.seq),text:read.messages[0].text,invalid,
  merged:merged.map(m=>[m.seq,m.text]),status:B.missionStatusLabel(mission.mission),closed:B.missionStatusLabel({status:'completed'}),
  work:[B.workStatusLabel(null),B.workStatusLabel('running')],advice:B.advice('relation_unknown'),owners:[...mission.owners].sort(),
  declared:mission.instances.get('pred').owner};""")
    assert out["participants"] == [{"instanceId": "i1", "position": "member"}]
    assert out["seqs"] == [2, 1] and out["text"] == "<b>x</b>"          # le texte reste du texte (rendu par textContent)
    assert out["invalid"] == "relation_board_payload_invalid"
    assert out["merged"] == [[1, "y2"], [2, "<b>x</b>"], [3, "z"]]
    assert out["status"] == "état inconnu" and out["closed"] == "terminée"
    assert out["work"] == ["hors du suivi vivant", "en cours"]
    assert "n’existe pas" in out["advice"]
    # Après un relais, le responsable est le propriétaire COURANT, pas la déclaration d'origine du prédécesseur.
    assert out["owners"] == ["subowner", "succ"] and out["declared"] is True


def test_no_new_write_path_is_introduced_by_the_graph_modules():
    """Lecture seule : aucune option `method` dans les modules du graphe (M8 : pas seulement les littéraux POST/DELETE),
    et, exécutés, ils n'émettent que des GET."""
    import re
    for name in ("control_center_role_identity.js", "control_center_scene_roles.js", "control_center_relation_board.js"):
        source = (RUNTIME / name).read_text(encoding="utf-8")
        assert not re.search(r"\bmethod\s*:", source), f"{name} sets a request method"
        assert not re.search(r"\b(?:POST|PUT|PATCH|DELETE)\b", source), f"{name} names a write verb"
    out = _node("""
const seen=[];
const fakeFetch=async(path,init)=>{seen.push([path,(init&&init.method)||'GET']);
  return {ok:true,status:200,text:async()=>JSON.stringify(path.includes('/relations/')?{relation:{relation_id:'r',kind:'qa',participants:[]},messages:[],participants:[]}
    :path.includes('/missions/')?{missions:[{mission_id:'m',status:'open'}]}:{roles:[]})}};
globalThis.fetch=fakeFetch;
const reg=I.createRoleRegistry({fetchJson:async p=>{const r=await fakeFetch(p);return JSON.parse(await r.text())}});await reg.load();
const cache=S.createMissionCache({fetchJson:async p=>{const r=await fakeFetch(p);return JSON.parse(await r.text())},setInterval:()=>1,clearInterval:()=>{}});
cache.info('m');await new Promise(r=>setTimeout(r,5));
return seen;""")
    assert out and all(method == "GET" for _path, method in out), out


def test_a_star_without_role_ref_has_no_role_even_with_a_bracket_in_its_title():
    """M1 : le rôle ne vient que de `role_ref`, jamais d'un « [coder] » écrit dans le titre."""
    out = _node("""
const item=(id,ref,title)=>({schema_version:1,object_id:id,kind:'agent',category:'agent',exec_state:'running',representation:'point',
  geometry:{x:0,y:0,w:6,h:6},layer:100,order:0,visibility:'visible',disposition:'active',constraints:{},origin:'runtime',
  work_ref:{source:'claude',external_id:id},role_ref:ref,payload:{title,summary:'',items:[]}});
const objects=[item('a',null,'[coder] Prototype'),item('b',undefined,'[qa] [research] Relire'),item('c',{role_id:''},'[coder] Vide')];
const state={objects:new Map(objects.map(o=>[o.object_id,o])),relations:new Map()};
const vm=L.viewModel(state,L.resolveLayout(state),L.viewport(1440,900),{roleIdentity:()=>({name:'Développement',badge:'DEV',known:true})});
return vm.nodes.map(n=>({id:n.id,role:n.role,title:n.title,label:n.label}));""")
    for node in out:
        assert node["role"] is None, node
        assert "rôle" not in node["label"], node
    assert out[0]["title"] == "[coder] Prototype"


def test_role_stars_get_room_for_their_pill_and_lose_only_their_exact_role_marker():
    out = _node("""
const agent=(id,ref,title)=>({schema_version:1,object_id:id,kind:'agent',category:'agent',exec_state:'running',representation:'point',
  geometry:null,layer:100,order:0,visibility:'visible',disposition:'active',constraints:{},origin:'runtime',
  work_ref:{source:'claude',external_id:id},role_ref:ref,payload:{title,summary:'',items:[]}});
const objects=[agent('p',{role_id:'research-lead',mission_owner:true},'[general] [research-lead] Comparer'),
  ...['a','b','c','d'].map(id=>agent(id,{role_id:'coder'},'[code] [coder] Prototype '+id)),
  agent('x',{role_id:'qa'},'[general] [coder] Mal marqué'),agent('plain',null,'[general] Sans rôle')];
const relations=['a','b','c','d'].map(id=>({relation_id:'parent_of!p~'+id,kind:'parent_of',from_id:'p',to_id:id,layer:0}));
const state={objects:new Map(objects.map(o=>[o.object_id,o])),relations:new Map(relations.map(r=>[r.relation_id,r]))};
const layout=L.resolveLayout(state);
const boxes=Object.fromEntries([...layout.placements].map(([id,b])=>[id,b]));
const rooms=Object.fromEntries([...layout.placements].map(([id,b])=>[id,L.footprintOf(state.objects.get(id),b)]));
const vm=L.viewModel(state,layout,L.viewport(1440,900),{});
const title=id=>vm.nodes.find(n=>n.id===id).title;
return {room:L.ROLE_PILL_ROOM,boxes,rooms,titles:{p:title('p'),a:title('a'),x:title('x'),plain:title('plain')}};""")
    assert out["room"]["role"]["left"] == 13 and out["room"]["owner"]["left"] == 27
    boxes, rooms = out["boxes"], out["rooms"]
    # La géométrie enregistrée reste celle d'un point ; la place réservée s'étend surtout à GAUCHE (côté pastille).
    assert (boxes["a"]["w"], boxes["a"]["h"]) == (6, 6) and (boxes["plain"]["w"], boxes["plain"]["h"]) == (6, 6)
    assert rooms["a"]["x"] == boxes["a"]["x"] - 13 and rooms["p"]["x"] == boxes["p"]["x"] - 27
    assert rooms["plain"] == boxes["plain"]
    team = [rooms[k] for k in ("p", "a", "b", "c", "d", "x")]
    overlap = lambda a, b: min(a["x"] + a["w"], b["x"] + b["w"]) > max(a["x"], b["x"]) and min(a["y"] + a["h"], b["y"] + b["h"]) > max(a["y"], b["y"])
    for i, one in enumerate(team):
        for other in team[i + 1:]:
            assert not overlap(one, other), (one, other)
    assert out["titles"] == {"p": "Comparer", "a": "Prototype a", "x": "[coder] Mal marqué", "plain": "Sans rôle"}

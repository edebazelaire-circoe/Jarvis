"""Onglet Architecture : contrôleur et adaptateurs (jarvis-architecture-agents-settings-editor, Slice 04).

Le module est exécuté par node sur le fixture du contrat 11 (`tests/fixtures/architecture_snapshot_fixture_ui.json`,
que la Slice 07 remplacera par celui de la Slice 01). Seul le transport est simulé : l'adaptateur de fixture joue
le serveur, ou un adaptateur écrit ici renvoie un refus précis. Doc : `docs/settings/architecture-tab.md`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_architecture_settings.js"
FIXTURE = ROOT / "tests" / "fixtures" / "architecture_snapshot_fixture_ui.json"

TOGGLE = "voice.delegate->core.request"
RESTART = "core.events->tool.events"
LOCKED = "mic.audio_out->voice.audio_in"
GOVERNED = "core.agents->subagents.spawn"


def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def run_node(tmp_path: Path, source: str, snapshot: dict | None = None):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data = tmp_path / "snap.json"
    data.write_text(json.dumps(snapshot if snapshot is not None else fixture()), encoding="utf-8")
    script = tmp_path / "t.cjs"
    script.write_text(
        "const errors=[],infos=[];console.error=(c,e,x)=>errors.push([c,e&&e.code||null]);console.info=(c,d)=>infos.push([c,d]);\n"
        f"const A=require({json.dumps(str(MODULE))});\n"
        f"const SNAP=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data))},'utf8'));\n"
        "const host={innerHTML:'',clientWidth:1300,attrs:{},events:[],listeners:{},setAttribute(k,v){this.attrs[k]=v},"
        "addEventListener(t,f){(this.listeners[t]=this.listeners[t]||[]).push(f)},removeEventListener(t,f){this.listeners[t]=(this.listeners[t]||[]).filter(x=>x!==f)},"
        "dispatchEvent(e){this.events.push([e.type,e.detail]);return true},querySelector(){return null},querySelectorAll(){return[]},contains(){return false}};\n"
        "const quiet={setInterval:()=>null,clearInterval:()=>{}};\n"
        "const clone=v=>JSON.parse(JSON.stringify(v));\n"
        "const writes=a=>a.calls.filter(c=>!['load','loadLayout'].includes(c[0]));\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "(async()=>{" + source + "})().catch(e=>{process.stderr.write(String(e&&e.stack||e));process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout) if done.stdout else None


def test_the_snapshot_drives_every_node_link_banner_and_legend(tmp_path):
    out = run_node(tmp_path, """
const a=A.createFixtureAdapter(SNAP);const v=A.mount(host,{adapter:a,...quiet});await v.ready;
out({html:host.innerHTML,errors,infos,attrs:host.attrs,listeners:Object.keys(host.listeners)});""")
    html = out["html"]
    assert out["errors"] == [] and out["infos"][0][0] == "architecture_settings.loaded"
    for node in fixture()["nodes"]:
        assert f'data-arch-node="{node["id"]}"' in html and node["label"] in html
    for conn in fixture()["connections"]:
        assert f'<button type="button" class="arch-label m-{conn["mutability"]}' in html.replace("&gt;", ">") or conn["id"] in html
        assert f'data-arch-edge="{conn["id"].replace(">", "&gt;")}"' in html
    assert 'data-settings-open="architecture_compat"' in html and "Duplex" in html and "lecture seule" in html
    assert "Légende des liaisons" in html and "effective au prochain démarrage de Core" in html
    # Seuls les cerveaux ont le bouton « … » (équivalent tactile du clic droit).
    assert html.count("data-arch-menu-btn=") == sum(1 for n in fixture()["nodes"] if n["kind"] == "brain")
    assert {"click", "contextmenu", "keydown", "pointerdown"} <= set(out["listeners"])


def test_no_topology_is_hard_coded_a_future_brain_renders_and_colors_are_tokens(tmp_path):
    source = MODULE.read_text(encoding="utf-8")
    for literal in ("Core Brain", "Tool Brain", "Voice Brain", "'core'", "'tool'", "'subagents'", "'mic'", "'speakers'",
                    "brain_orchestration"):
        assert literal not in source, literal
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", source), "aucune couleur littérale : des jetons du thème seulement"
    snap = fixture()
    snap["nodes"].append({"id": "vision-x", "kind": "brain", "label": "Vision Brain", "brain_type": "vision", "state": "shadow",
                          "state_reason": "Observe seulement.", "activation": {"mutable": False, "reason": ""}, "configurable": True,
                          "ports": [{"id": "frames", "direction": "in", "channel": "event", "family": "brain_event"}]})
    snap["connections"].append({"id": "core.events->vision-x.frames", "source": {"node": "core", "port": "events"},
                                "target": {"node": "vision-x", "port": "frames"}, "channel": "event", "purpose": "Images",
                                "enabled": True, "mutability": "toggleable", "applies": "live", "pending": None, "governed_by": None})
    snap["connections"].append({"id": "ghost", "source": {"node": "nowhere", "port": "x"}, "target": {"node": "core", "port": "request"},
                                "channel": "request", "mutability": "toggleable", "enabled": True})
    out = run_node(tmp_path, """
const v=A.mount(host,{adapter:A.createFixtureAdapter(SNAP),...quiet});await v.ready;out(host.innerHTML);""", snap)
    assert 'data-arch-node="vision-x"' in out and "Ombre : observe sans agir" in out
    assert "ghost" not in out.split("arch-notice")[0] or "1 élément(s) du snapshot écarté(s)" in out
    assert "1 élément(s) du snapshot écarté(s)" in out


def test_loading_shows_a_counter_then_a_deadline_ends_it_as_unreachable(tmp_path):
    out = run_node(tmp_path, """
let t=1000;const never={load:()=>new Promise(()=>{})};
const v=A.mount(host,{adapter:never,timeoutMs:60,now:()=>t,...quiet});
const loading=host.innerHTML;await v.ready;
out({loading,after:host.innerHTML,phase:v.state.phase,code:v.state.error.code,errors});""")
    assert 'role="status"' in out["loading"] and "data-arch-since" in out["loading"] and "abandon après" in out["loading"]
    assert out["phase"] == "error" and out["code"] == "architecture_timeout"
    assert "Control Center injoignable" in out["after"] and 'data-arch-act="reload"' in out["after"] and 'role="alert"' in out["after"]
    assert out["errors"] == [["architecture_timeout", "architecture_timeout"]]


def test_unreachable_invalid_and_empty_states_each_say_what_happened(tmp_path):
    out = run_node(tmp_path, """
const err=code=>({load:async()=>{const e=new Error('connexion refusée');e.code=code;throw e}});
const r={};
let v=A.mount(host,{adapter:err('architecture_unreachable'),...quiet});await v.ready;r.unreachable=host.innerHTML;v.destroy();
v=A.mount(host,{adapter:{load:async()=>({nodes:'x'})},...quiet});await v.ready;r.invalid=host.innerHTML;v.destroy();
v=A.mount(host,{adapter:A.createFixtureAdapter({...SNAP,nodes:[],connections:[]}),...quiet});await v.ready;r.empty=host.innerHTML;
r.destroyedListeners=Object.values(host.listeners).flat().length;
out(r);""")
    assert "Control Center injoignable" in out["unreachable"] and "connexion refusée" in out["unreachable"] and "Rien n’a été modifié" in out["unreachable"]
    assert "Architecture illisible" in out["invalid"] and "architecture_payload_invalid" in out["invalid"]
    assert "Aucun module dans l’architecture" in out["empty"] and "Rien n’est inventé" in out["empty"]


def test_toggle_writes_with_the_revision_and_shows_the_returned_snapshot(tmp_path):
    out = run_node(tmp_path, f"""
const a=A.createFixtureAdapter(SNAP);const v=A.mount(host,{{adapter:a,...quiet}});await v.ready;
v.select('connection','{TOGGLE}');await v.toggle('{TOGGLE}');
const c=v.state.snapshot.connections.find(x=>x.id==='{TOGGLE}');
out({{writes:writes(a),enabled:c.enabled,revision:v.state.snapshot.revision,html:host.innerHTML,notice:v.state.notice}});""")
    assert out["writes"] == [["setConnection", TOGGLE, {"base_revision": "t-17", "enabled": False}]]
    assert out["enabled"] is False and out["revision"] == "f-1"
    assert 'role="switch" aria-checked="false"' in out["html"]
    assert out["notice"]["tone"] == "ok" and "au prochain tour de parole" in out["notice"]["text"]


def test_a_core_restart_link_is_shown_pending_while_the_graph_keeps_the_live_state(tmp_path):
    out = run_node(tmp_path, f"""
const a=A.createFixtureAdapter(SNAP);const v=A.mount(host,{{adapter:a,...quiet}});await v.ready;
v.select('connection','{RESTART}');await v.toggle('{RESTART}');
const c=v.state.snapshot.connections.find(x=>x.id==='{RESTART}');
out({{enabled:c.enabled,pending:c.pending,html:host.innerHTML,notice:v.state.notice.text}});""")
    assert out["enabled"] is False and out["pending"] == {"enabled": True, "applies": "core_restart"}
    assert "data-arch-pending" in out["html"] and "Effectif au prochain démarrage de Core" in out["html"]
    assert 'aria-checked="true"' in out["html"], "l'interrupteur montre la valeur enregistrée"
    assert "arch-edge m-toggleable ch-event off" in out["html"], "le trait montre l'état vivant"
    assert "effective au prochain démarrage de Core" in out["notice"]


def test_a_locked_or_governed_link_is_refused_without_any_write(tmp_path):
    out = run_node(tmp_path, f"""
const a=A.createFixtureAdapter(SNAP);const v=A.mount(host,{{adapter:a,...quiet}});await v.ready;
v.select('connection','{LOCKED}');await v.toggle('{LOCKED}');const locked={{notice:v.state.notice,html:host.innerHTML}};
await v.remove('{LOCKED}');const removed=v.state.notice.code;
v.select('connection','{GOVERNED}');await v.toggle('{GOVERNED}');
out({{writes:writes(a),locked,removed,governed:v.state.notice,html:host.innerHTML}});""")
    assert out["writes"] == []
    assert out["locked"]["notice"]["code"] == "connection_locked"
    assert "Sans micro, JARVIS n'entend plus rien" in out["locked"]["notice"]["text"]
    assert 'data-arch-act="toggle"' not in out["locked"]["html"] and "Raison du verrou" in out["locked"]["html"]
    assert out["removed"] == "connection_locked"
    assert out["governed"]["code"] == "connection_governed"
    assert "Réglé dans la fenêtre du cerveau Core Brain" in out["html"]


def test_a_server_refusal_shows_its_reason_and_the_returned_snapshot_never_a_false_state(tmp_path):
    out = run_node(tmp_path, f"""
const locked=clone(SNAP);const c=locked.connections.find(x=>x.id==='{TOGGLE}');c.mutability='required_locked';c.locked_reason='Imposé par l’environnement';locked.revision='t-18';
let loads=0;
const a={{load:async()=>{{loads+=1;return clone(SNAP)}},setConnection:async()=>({{ok:false,status:423,code:'connection_locked',reason:'Imposé par l’environnement',snapshot:locked}})}};
const v=A.mount(host,{{adapter:a,...quiet}});await v.ready;v.select('connection','{TOGGLE}');await v.toggle('{TOGGLE}');
const now=v.state.snapshot.connections.find(x=>x.id==='{TOGGLE}');
out({{loads,enabled:now.enabled,mutability:now.mutability,revision:v.state.snapshot.revision,notice:v.state.notice,html:host.innerHTML,errors}});""")
    assert out["loads"] == 1, "le snapshot du refus fait foi : pas de relecture"
    assert out["enabled"] is True and out["mutability"] == "required_locked" and out["revision"] == "t-18"
    assert out["notice"]["code"] == "connection_locked" and "Imposé par l’environnement" in out["notice"]["text"]
    assert "connection_locked" in out["html"] and 'role="alert"' in out["html"]
    assert ["connection_locked", None] in out["errors"]


def test_a_stale_revision_rereads_the_architecture(tmp_path):
    out = run_node(tmp_path, f"""
let loads=0;const fresh=clone(SNAP);fresh.revision='t-20';
const a={{load:async()=>{{loads+=1;return loads>1?fresh:clone(SNAP)}},setConnection:async()=>({{ok:false,status:409,code:'architecture_revision_stale',reason:'révision dépassée'}})}};
const v=A.mount(host,{{adapter:a,...quiet}});await v.ready;v.select('connection','{TOGGLE}');await v.toggle('{TOGGLE}');
out({{loads,revision:v.state.snapshot.revision,notice:v.state.notice,write:v.state.write}});""")
    assert out["loads"] == 2 and out["revision"] == "t-20" and out["write"] is None
    assert out["notice"]["code"] == "architecture_revision_stale" and "a changé ailleurs" in out["notice"]["text"]
    assert "relue" in out["notice"]["hint"]


def test_an_unknown_outcome_or_a_refusal_without_snapshot_forces_a_reread(tmp_path):
    out = run_node(tmp_path, f"""
let loads=0;
const mk=set=>({{load:async()=>{{loads+=1;return clone(SNAP)}},setConnection:set}});
const r={{}};
let v=A.mount(host,{{adapter:mk(async()=>{{const e=new Error('socket fermé');e.code='architecture_unreachable';throw e}}),...quiet}});await v.ready;
await v.toggle('{TOGGLE}');r.unknown={{loads,notice:v.state.notice,enabled:v.state.snapshot.connections.find(x=>x.id==='{TOGGLE}').enabled}};v.destroy();loads=0;
v=A.mount(host,{{adapter:mk(async()=>({{ok:false,status:500,code:'architecture_apply_failed',reason:'Core a refusé l’application'}})),...quiet}});await v.ready;
await v.toggle('{TOGGLE}');r.failed={{loads,notice:v.state.notice,enabled:v.state.snapshot.connections.find(x=>x.id==='{TOGGLE}').enabled}};
out(r);""")
    assert out["unknown"]["loads"] == 2 and out["unknown"]["notice"]["text"].startswith("Issue inconnue")
    assert out["unknown"]["enabled"] is True
    assert out["failed"]["loads"] == 2 and "Core a refusé l’application" in out["failed"]["notice"]["text"]
    assert out["failed"]["notice"]["code"] == "architecture_apply_failed" and out["failed"]["enabled"] is True


def test_moving_nodes_writes_the_layout_only_with_its_revision_and_rereads_on_409(tmp_path):
    out = run_node(tmp_path, """
const a=A.createFixtureAdapter(SNAP);const v=A.mount(host,{adapter:a,...quiet});await v.ready;
v.moveNode('core',500,40);await v.saveLayout();const first=v.state.layout.revision;
v.moveNode('tool',520,260);await v.saveLayout();
const saves=a.calls.filter(c=>c[0]==='saveLayout').map(c=>[c[1].base_revision,c[1].positions.core||null,c[1].positions.tool||null]);
const topo=writes(a).filter(c=>c[0]!=='saveLayout');
const stale={load:async()=>clone(SNAP),loadLayout:async()=>({revision:'l-9',positions:{core:{x:10,y:10}}}),saveLayout:async()=>({ok:false,status:409,code:'layout_revision_stale',reason:'autre onglet'})};
v.destroy();const w=A.mount(host,{adapter:stale,...quiet});await w.ready;w.moveNode('core',300,300);await w.saveLayout();
out({first,saves,topo,revision:v.state.snapshot.revision,stale:{layout:w.state.layout,moved:w.state.moved,note:w.state.layoutNotice}});""")
    assert out["topo"] == [] and out["revision"] == "t-17", "aucune écriture de topologie"
    assert out["first"] == "l-1"
    assert out["saves"] == [[None, {"x": 500, "y": 40}, None], ["l-1", {"x": 500, "y": 40}, {"x": 520, "y": 260}]]
    assert out["stale"]["layout"]["revision"] == "l-9" and out["stale"]["layout"]["positions"]["core"] == {"x": 10, "y": 10}
    assert out["stale"]["moved"] == {} and out["stale"]["note"]["code"] == "layout_revision_stale"
    assert "votre déplacement n’est pas enregistré" in out["stale"]["note"]["text"]


def test_the_brain_menu_offers_configure_and_activation_only_when_mutable(tmp_path):
    out = run_node(tmp_path, """
const seen=[];const a=A.createFixtureAdapter(SNAP);
const v=A.mount(host,{adapter:a,onConfigureBrain:(id,d)=>seen.push([id,d]),...quiet});await v.ready;
v.openMenu('voice');const voice=host.innerHTML;
v.menuAction('configure');const afterConfigure={menu:v.state.menu,html:host.innerHTML};
v.openMenu('mic');const endpoint=v.state.menu;
const snap=clone(SNAP);snap.nodes.find(n=>n.id==='tool').activation={mutable:true,reason:''};
const calls=[];const b={...A.createFixtureAdapter(snap),setNodeActivation:async(id,body)=>{calls.push([id,body]);return {ok:true,snapshot:snap}}};
v.destroy();const w=A.mount(host,{adapter:b,...quiet});await w.ready;w.openMenu('tool');const tool=host.innerHTML;
w.menuAction('activate');await new Promise(r=>setTimeout(r,10));
const noAdapter=A.mount(host,{adapter:A.createFixtureAdapter(snap),...quiet});await noAdapter.ready;noAdapter.openMenu('tool');
v.state.menu=null;
out({voice,afterConfigure,endpoint,tool,calls,noAdapter:host.innerHTML,seen,events:host.events});""")
    voice = out["voice"]
    assert 'role="menu"' in voice and voice.index("Configurer…") < voice.index("Inspecter")
    assert "La surface vocale porte l'audio" in voice.replace("&#39;", "'") and "Désactiver" not in voice
    assert out["afterConfigure"]["menu"] is None
    assert out["seen"] == [["voice", {"nodeId": "voice", "field": None, "source": "menu"}]]
    assert ["architecture:configure-brain", {"nodeId": "voice", "field": None, "source": "menu"}] in out["events"]
    assert out["endpoint"] is None, "un endpoint n'a pas de menu de cerveau"
    assert 'data-arch-menu="activate"' in out["tool"]
    assert out["calls"] == [["tool", {"base_revision": "t-17", "active": True}]]
    assert 'data-arch-menu="activate"' not in out["noAdapter"], "pas d'entrée sans opération légale côté adaptateur"


def test_a_governed_link_opens_the_brain_window_on_its_field(tmp_path):
    out = run_node(tmp_path, f"""
const seen=[];const v=A.mount(host,{{adapter:A.createFixtureAdapter(SNAP),onConfigureBrain:(id,d)=>seen.push([id,d]),...quiet}});await v.ready;
v.select('connection','{GOVERNED}');const html=host.innerHTML;
const gb=v.state.snapshot.connections.find(c=>c.id==='{GOVERNED}').governed_by;v.configure(gb.node,{{field:gb.field,source:'governed'}});
out({{html,seen,events:host.events}});""")
    assert 'data-arch-act="governed"' in out["html"] and "Gouvernée" in out["html"]
    assert out["seen"] == [["core", {"nodeId": "core", "field": "delegation", "source": "governed"}]]
    assert out["events"][-1][1]["field"] == "delegation"


def test_create_only_from_an_exposed_compatible_port_and_remove_a_removable_link(tmp_path):
    snap = fixture()
    snap["nodes"][2]["ports"].append({"id": "notes", "direction": "out", "channel": "event", "family": "brain_event"})
    snap["creatable"] = [{"source": {"node": "core", "port": "notes"}, "target": {"node": "tool", "port": "events"}, "channel": "event", "purpose": "Notes"}]
    out = run_node(tmp_path, """
const a=A.createFixtureAdapter(SNAP);const v=A.mount(host,{adapter:a,...quiet});await v.ready;
const ports=host.innerHTML;
await v.create({source:{node:'voice',port:'delegate'},target:{node:'tool',port:'events'}});const refused=v.state.notice.code;const n0=writes(a).length;
await v.create({source:{node:'core',port:'notes'},target:{node:'tool',port:'events'}});
const created=v.state.snapshot.connections.find(c=>c.id==='core.notes->tool.events');
v.select('connection',created.id);const insp=host.innerHTML;
await v.remove(created.id);
out({ports,refused,n0,writes:writes(a),created,insp,left:v.state.snapshot.connections.some(c=>c.id===created.id),creatable:v.state.snapshot.creatable.length});""", snap)
    assert out["ports"].count("data-arch-port-source=") == 1 and 'data-arch-port-source="core:notes"' in out["ports"]
    assert out["refused"] == "connection_incompatible" and out["n0"] == 0
    assert out["writes"][0] == ["createConnection", {"base_revision": "t-17", "source": {"node": "core", "port": "notes"},
                                                     "target": {"node": "tool", "port": "events"}, "channel": "event"}]
    assert out["created"]["mutability"] == "creatable_removable"
    assert 'data-arch-act="remove"' in out["insp"] and 'data-arch-act="toggle"' not in out["insp"]
    assert out["writes"][1] == ["removeConnection", "core.notes->tool.events", {"base_revision": "f-1"}]
    assert out["left"] is False and out["creatable"] == 1


def test_the_http_adapter_speaks_the_contract_routes_and_keeps_refusals_as_results(tmp_path):
    out = run_node(tmp_path, """
const seen=[];
const reply=(status,body)=>({ok:status<400,status,headers:{get:()=>null},text:async()=>JSON.stringify(body)});
const fetch=async(url,init)=>{seen.push([url,init.method,init.body?JSON.parse(init.body):null]);
  if(url==='/api/architecture')return reply(200,SNAP);
  if(init.method==='POST'&&url.includes('/connections/'))return reply(423,{ok:false,code:'connection_locked',reason:'verrou',snapshot:SNAP});
  if(init.method==='DELETE')return reply(200,{ok:true,snapshot:SNAP});
  if(url==='/api/architecture/layout'&&init.method==='PUT')return reply(409,{ok:false,code:'layout_revision_stale',reason:'vieux'});
  return reply(200,{revision:'l-1',positions:{}});};
const h=A.createHttpAdapter({fetch});
const r={};
r.load=(await h.load()).revision;
r.set=await h.setConnection('a->b',{base_revision:'t-17',enabled:false});r.set.snapshot=!!r.set.snapshot;
r.del=(await h.removeConnection('a->b',{base_revision:'t-17'})).ok;
r.layout=await h.loadLayout();r.save=await h.saveLayout({base_revision:'l-1',positions:{}});
const down=A.createHttpAdapter({fetch:async()=>{throw new Error('ECONNREFUSED')}});
try{await down.setConnection('x',{base_revision:'t',enabled:true})}catch(e){r.down=e.code}
out({r,seen});""")
    r, seen = out["r"], out["seen"]
    assert r["load"] == "t-17"
    assert r["set"] == {"ok": False, "status": 423, "code": "connection_locked", "reason": "verrou", "snapshot": True}
    assert r["del"] is True and r["layout"] == {"revision": "l-1", "positions": {}}
    assert r["save"]["status"] == 409 and r["save"]["code"] == "layout_revision_stale"
    assert r["down"] == "architecture_unreachable"
    assert seen[1] == ["/api/architecture/connections/a-%3Eb", "POST", {"base_revision": "t-17", "enabled": False}]
    assert seen[2][:2] == ["/api/architecture/connections/a-%3Eb?base_revision=t-17", "DELETE"]
    assert seen[4][:2] == ["/api/architecture/layout", "PUT"]


def test_the_fixture_matches_the_wire_contract_vocabulary():
    snap = fixture()
    assert snap["schema_version"] == 1 and snap["revision"] and snap["voice_architecture"]["settings_target"] == "architecture_compat"
    kinds, states = {"brain", "endpoint", "pool"}, {"active", "inactive", "shadow", "unavailable"}
    channels = {"audio", "request", "response", "tool_call", "event", "speech"}
    muts = {"required_locked", "toggleable", "creatable_removable", "governed"}
    applies = {"live", "next_turn", "core_restart", "voice_restart", None}
    ids = {n["id"]: n for n in snap["nodes"]}
    for n in snap["nodes"]:
        assert n["kind"] in kinds and n["state"] in states and isinstance(n["activation"]["mutable"], bool)
    for c in snap["connections"]:
        assert c["channel"] in channels and c["mutability"] in muts and c["applies"] in applies
        for end, direction in (("source", "out"), ("target", "in")):
            port = next(p for p in ids[c[end]["node"]]["ports"] if p["id"] == c[end]["port"])
            assert port["direction"] == direction and port["channel"] == c["channel"]
        assert (c["mutability"] == "governed") == (c["governed_by"] is not None)
        assert c["binding"]


SLICE01 = [ROOT / "tests" / "fixtures" / f"architecture_snapshot_{mode}.json" for mode in ("duplex", "simple")]


@pytest.mark.parametrize("path", SLICE01, ids=lambda p: p.stem)
def test_the_real_slice01_snapshots_render_and_a_voice_restart_toggle_is_pending(tmp_path, path):
    snap = json.loads(path.read_text(encoding="utf-8"))
    toggle = next(c["id"] for c in snap["connections"] if c["mutability"] == "toggleable" and c["applies"] == "voice_restart")
    governed = next(c["id"] for c in snap["connections"] if c["mutability"] == "governed")
    out = run_node(tmp_path, f"""
const a=A.createFixtureAdapter(SNAP);const v=A.mount(host,{{adapter:a,...quiet}});await v.ready;
const html=host.innerHTML;v.select('connection',{json.dumps(governed)});const gov=host.innerHTML;
v.select('connection',{json.dumps(toggle)});await v.toggle({json.dumps(toggle)});
out({{html,gov,after:host.innerHTML,notice:v.state.notice,errors,c:v.state.snapshot.connections.find(x=>x.id==={json.dumps(toggle)})}});""", snap)
    assert out["errors"] == []
    for node in snap["nodes"]:
        assert f'data-arch-node="{node["id"]}"' in out["html"]
    assert "élément(s) du snapshot écarté(s)" not in out["html"] and "Version de contrat inattendue" not in out["html"]
    assert "Prise d’effet" not in out["gov"], "une liaison gouvernée a `applies: null`"
    assert out["c"]["enabled"] is True and out["c"]["pending"] == {"enabled": False, "applies": "voice_restart"}
    assert "Effectif au prochain démarrage de la voix" in out["after"]
    assert "effective au prochain démarrage de la voix" in out["notice"]["text"]
    assert "data-arch-port-source=" not in out["html"], "aucune création proposée sans `creatable`"


@pytest.mark.parametrize("status,code", [(422, "connection_unbindable"), (422, "connection_not_removable"),
                                         (400, "architecture_request_invalid"), (500, "architecture_snapshot_failed")])
def test_any_server_refusal_code_shows_the_servers_reason(tmp_path, status, code):
    out = run_node(tmp_path, f"""
let loads=0;const a={{load:async()=>{{loads+=1;return clone(SNAP)}},setConnection:async()=>({{ok:false,status:{status},code:'{code}',reason:'Raison exacte du serveur'}})}};
const v=A.mount(host,{{adapter:a,...quiet}});await v.ready;v.select('connection','{TOGGLE}');await v.toggle('{TOGGLE}');
out({{loads,notice:v.state.notice,html:host.innerHTML}});""")
    assert out["notice"]["code"] == code and "Raison exacte du serveur" in out["notice"]["text"]
    assert code in out["html"] and out["loads"] == 2, "refus sans snapshot : relecture"


def test_a_layout_refusal_shows_the_servers_reason(tmp_path):
    out = run_node(tmp_path, """
const a={load:async()=>clone(SNAP),loadLayout:async()=>({revision:'l-1',positions:{}}),saveLayout:async()=>({ok:false,status:400,code:'layout_invalid',reason:'Position hors bornes'})};
const v=A.mount(host,{adapter:a,...quiet});await v.ready;v.moveNode('core',5,5);await v.saveLayout();
out(v.state.layoutNotice);""")
    assert out["code"] == "layout_invalid" and "Position hors bornes" in out["text"]
